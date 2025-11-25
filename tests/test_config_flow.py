"""Test the WrtManager config flow."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.wrtmanager.config_flow import (
    CannotConnect,
    ConfigFlow,
    InvalidAuth,
    OptionsFlowHandler,
    validate_router_connection,
)
from custom_components.wrtmanager.const import (
    CONF_ROUTER_DESCRIPTION,
    CONF_ROUTER_HOST,
    CONF_ROUTER_NAME,
    CONF_ROUTER_PASSWORD,
    CONF_ROUTER_USE_HTTPS,
    CONF_ROUTER_USERNAME,
    CONF_ROUTER_VERIFY_SSL,
    CONF_ROUTERS,
    CONF_VLAN_NAMES,
    DEFAULT_USERNAME,
    DOMAIN,
    ERROR_ALREADY_CONFIGURED,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock(spec=HomeAssistant)
    hass.config_entries = Mock()
    hass.config_entries.async_entries = Mock(return_value=[])
    hass.data = {}
    return hass


@pytest.fixture
def mock_ubus_client():
    """Create a mock UbusClient."""
    with patch("custom_components.wrtmanager.config_flow.UbusClient") as mock:
        mock_instance = AsyncMock()
        mock_instance.authenticate.return_value = "test-session-id"
        mock_instance.get_wireless_devices.return_value = ["wlan0", "wlan1"]
        mock_instance.get_system_info.return_value = {"release": {"version": "22.03.0"}}
        mock_instance.get_system_board.return_value = {"model": "test-router"}
        mock_instance.get_dhcp_leases.return_value = {"dhcp_leases": []}
        mock_instance.close.return_value = None
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def router_data():
    """Return test router data."""
    return {
        CONF_HOST: "192.168.1.1",
        CONF_NAME: "Test Router",
        CONF_USERNAME: "root",
        CONF_PASSWORD: "password123",
        CONF_ROUTER_DESCRIPTION: "Test Description",
    }


class TestValidateRouterConnection:
    """Test the validate_router_connection function."""

    async def test_validate_connection_success(
        self, hass: HomeAssistant, mock_ubus_client, router_data
    ):
        """Test successful router validation."""
        result = await validate_router_connection(hass, router_data)

        assert result["title"] == "Test Router"
        assert result["model"] == "test-router"
        assert result["version"] == "22.03.0"
        assert result["router_type"] == "Main Router"
        assert result["capabilities"]["wireless"] == 2
        assert result["capabilities"]["dhcp"] is True
        assert result["capabilities"]["system_info"] is True

    async def test_validate_connection_https_autodetect(self, hass: HomeAssistant, router_data):
        """Test HTTPS auto-detection."""
        with patch("custom_components.wrtmanager.config_flow.UbusClient") as mock_ubus:
            # First HTTPS attempt succeeds
            mock_https_instance = AsyncMock()
            mock_https_instance.authenticate.return_value = "test-session"
            mock_https_instance.close.return_value = None

            # Second HTTP instance for actual validation
            mock_http_instance = AsyncMock()
            mock_http_instance.authenticate.return_value = "test-session"
            mock_http_instance.get_wireless_devices.return_value = ["wlan0"]
            mock_http_instance.get_system_info.return_value = None
            mock_http_instance.get_system_board.return_value = None
            mock_http_instance.get_dhcp_leases.return_value = None
            mock_http_instance.close.return_value = None

            mock_ubus.side_effect = [mock_https_instance, mock_http_instance]

            result = await validate_router_connection(hass, router_data)

            assert result["use_https"] is True
            assert result["verify_ssl"] is False

    async def test_validate_connection_https_fails_fallback_http(
        self, hass: HomeAssistant, router_data
    ):
        """Test HTTPS fails, fallback to HTTP."""
        with patch("custom_components.wrtmanager.config_flow.UbusClient") as mock_ubus:
            # First HTTPS attempt fails
            mock_https_instance = AsyncMock()
            mock_https_instance.authenticate.side_effect = Exception("HTTPS failed")

            # Second HTTP instance succeeds
            mock_http_instance = AsyncMock()
            mock_http_instance.authenticate.return_value = "test-session"
            mock_http_instance.get_wireless_devices.return_value = ["wlan0"]
            mock_http_instance.get_system_info.return_value = None
            mock_http_instance.get_system_board.return_value = None
            mock_http_instance.get_dhcp_leases.return_value = None
            mock_http_instance.close.return_value = None

            mock_ubus.side_effect = [mock_https_instance, mock_http_instance]

            result = await validate_router_connection(hass, router_data)

            assert result["use_https"] is False

    async def test_validate_connection_auth_failure(
        self, hass: HomeAssistant, mock_ubus_client, router_data
    ):
        """Test authentication failure."""
        mock_ubus_client.authenticate.return_value = None

        with pytest.raises(InvalidAuth):
            await validate_router_connection(hass, router_data)

    async def test_validate_connection_no_wireless_devices(
        self, hass: HomeAssistant, mock_ubus_client, router_data
    ):
        """Test when no wireless devices are found."""
        mock_ubus_client.get_wireless_devices.return_value = None

        with pytest.raises(CannotConnect):
            await validate_router_connection(hass, router_data)

    async def test_validate_connection_access_point(
        self, hass: HomeAssistant, mock_ubus_client, router_data
    ):
        """Test access point detection (no DHCP)."""
        mock_ubus_client.get_dhcp_leases.return_value = None

        result = await validate_router_connection(hass, router_data)

        assert result["router_type"] == "Access Point"
        assert result["capabilities"]["dhcp"] is False

    async def test_validate_connection_exception_handling(
        self, hass: HomeAssistant, mock_ubus_client, router_data
    ):
        """Test exception handling during validation."""
        mock_ubus_client.authenticate.side_effect = Exception("Network error")

        with pytest.raises(CannotConnect):
            await validate_router_connection(hass, router_data)


class TestConfigFlow:
    """Test the ConfigFlow class."""

    async def test_form_initial(self, hass: HomeAssistant):
        """Test we get the form for initial setup."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        result = await config_flow.async_step_user()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    async def test_form_user_successful(self, hass: HomeAssistant, mock_ubus_client, router_data):
        """Test successful user input."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        result = await config_flow.async_step_user(router_data)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "add_more"

    async def test_form_user_cannot_connect(self, hass: HomeAssistant, router_data):
        """Test cannot connect error."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection",
            side_effect=CannotConnect("Cannot connect"),
        ):
            result = await config_flow.async_step_user(router_data)

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == ERROR_CANNOT_CONNECT

    async def test_form_user_invalid_auth(self, hass: HomeAssistant, router_data):
        """Test invalid auth error."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection",
            side_effect=InvalidAuth("Invalid auth"),
        ):
            result = await config_flow.async_step_user(router_data)

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == ERROR_INVALID_AUTH

    async def test_form_user_unknown_error(self, hass: HomeAssistant, router_data):
        """Test unknown error."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection",
            side_effect=Exception("Unknown error"),
        ):
            result = await config_flow.async_step_user(router_data)

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == ERROR_UNKNOWN

    async def test_form_user_existing_entry_redirect(self, hass: HomeAssistant, router_data):
        """Test redirect to add_to_existing when entry exists."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        # Mock existing entry
        existing_entry = MagicMock()
        existing_entry.data = {CONF_ROUTERS: [{"host": "192.168.1.2", "name": "Existing"}]}

        with patch.object(config_flow, "_async_current_entries", return_value=[existing_entry]):
            with patch.object(config_flow, "async_step_add_to_existing") as mock_add:
                await config_flow.async_step_user(router_data)
                mock_add.assert_called_once()

    async def test_add_more_step_add_another(self, hass: HomeAssistant, mock_ubus_client):
        """Test adding another router."""
        config_flow = ConfigFlow()
        config_flow.hass = hass
        config_flow._routers = [{"name": "Router1", "host": "192.168.1.1"}]

        with patch.object(config_flow, "async_step_user") as mock_user:
            await config_flow.async_step_add_more({"add_more": True})
            mock_user.assert_called_once()

    async def test_add_more_step_finish(self, hass: HomeAssistant):
        """Test finishing configuration with multiple routers."""
        config_flow = ConfigFlow()
        config_flow.hass = hass
        config_flow._routers = [
            {"name": "Router1", "host": "192.168.1.1"},
            {"name": "Router2", "host": "192.168.1.2"},
        ]

        result = await config_flow.async_step_add_more({"add_more": False})

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "WrtManager (2 routers)"
        assert result["data"][CONF_ROUTERS] == config_flow._routers

    async def test_add_to_existing_success(
        self, hass: HomeAssistant, mock_ubus_client, router_data
    ):
        """Test successfully adding to existing configuration."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        existing_entry = MagicMock()
        existing_entry.data = {CONF_ROUTERS: [{"host": "192.168.1.2", "name": "Existing"}]}
        existing_entry.entry_id = "test-entry-id"

        # Mock the update_entry and reload methods
        with patch.object(hass.config_entries, "async_update_entry") as mock_update:
            with patch.object(hass.config_entries, "async_reload") as mock_reload:
                result = await config_flow.async_step_add_to_existing(existing_entry, router_data)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Router Added"
        mock_update.assert_called_once()
        mock_reload.assert_called_once_with("test-entry-id")

    async def test_add_to_existing_duplicate_error(self, hass: HomeAssistant, router_data):
        """Test adding duplicate router to existing configuration."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        existing_entry = MagicMock()
        existing_entry.data = {CONF_ROUTERS: [{"host": "192.168.1.1", "name": "Existing"}]}

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection"
        ) as mock_validate:
            mock_validate.return_value = {"use_https": True, "verify_ssl": False}

            result = await config_flow.async_step_add_to_existing(existing_entry, router_data)

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == ERROR_ALREADY_CONFIGURED

    async def test_add_to_existing_no_existing_entry(self, hass: HomeAssistant):
        """Test add to existing when no entry exists."""
        config_flow = ConfigFlow()
        config_flow.hass = hass

        with patch.object(config_flow, "_async_current_entries", return_value=[]):
            result = await config_flow.async_step_add_to_existing()

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_existing_entry"


class TestOptionsFlow:
    """Test the OptionsFlow class."""

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry."""
        entry = MagicMock()
        entry.data = {
            CONF_ROUTERS: [
                {
                    CONF_ROUTER_HOST: "192.168.1.1",
                    CONF_ROUTER_NAME: "Main Router",
                    CONF_ROUTER_USERNAME: "root",
                    CONF_ROUTER_PASSWORD: "password",
                },
                {
                    CONF_ROUTER_HOST: "192.168.1.2",
                    CONF_ROUTER_NAME: "AP Router",
                    CONF_ROUTER_USERNAME: "root",
                    CONF_ROUTER_PASSWORD: "password2",
                },
            ]
        }
        entry.options = {}
        entry.entry_id = "test-entry-id"
        return entry

    async def test_options_init(self, hass: HomeAssistant, mock_config_entry):
        """Test options initialization."""
        options_flow = OptionsFlowHandler(mock_config_entry)

        result = await options_flow.async_step_init()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

    async def test_options_vlan_names(self, hass: HomeAssistant, mock_config_entry):
        """Test VLAN names configuration."""
        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass

        # Test form display
        result = await options_flow.async_step_init({"action": "vlan_names"})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "vlan_names"

        # Test configuration
        vlan_input = {"vlan_1": "Main Network", "vlan_2": "IoT Network", "vlan_3": "Guest Network"}
        result = await options_flow.async_step_vlan_names(vlan_input)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_VLAN_NAMES] == {
            1: "Main Network",
            2: "IoT Network",
            3: "Guest Network",
        }

    async def test_options_select_router_single(self, hass: HomeAssistant, mock_config_entry):
        """Test router selection with single router."""
        mock_config_entry.data[CONF_ROUTERS] = [mock_config_entry.data[CONF_ROUTERS][0]]

        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass

        with patch.object(options_flow, "async_step_update_credentials") as mock_update:
            await options_flow.async_step_init({"action": "router_credentials"})
            mock_update.assert_called_once()

    async def test_options_select_router_multiple(self, hass: HomeAssistant, mock_config_entry):
        """Test router selection with multiple routers."""
        options_flow = OptionsFlowHandler(mock_config_entry)

        result = await options_flow.async_step_init({"action": "router_credentials"})

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "select_router"

    async def test_options_update_credentials_success(self, hass: HomeAssistant, mock_config_entry):
        """Test successful credential update."""
        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass
        options_flow.selected_router_index = 0

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection"
        ) as mock_validate:
            mock_validate.return_value = {}
            with patch.object(hass.config_entries, "async_update_entry") as mock_update:
                with patch.object(hass.config_entries, "async_reload") as mock_reload:
                    result = await options_flow.async_step_update_credentials(
                        {CONF_ROUTER_USERNAME: "newuser", CONF_ROUTER_PASSWORD: "newpass"}
                    )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        mock_update.assert_called_once()
        mock_reload.assert_called_once()

    async def test_options_update_credentials_invalid_auth(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test credential update with invalid auth."""
        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass
        options_flow.selected_router_index = 0

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection",
            side_effect=InvalidAuth("Invalid"),
        ):
            result = await options_flow.async_step_update_credentials(
                {CONF_ROUTER_USERNAME: "newuser", CONF_ROUTER_PASSWORD: "newpass"}
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "invalid_auth"

    async def test_options_add_router_success(
        self, hass: HomeAssistant, mock_config_entry, router_data
    ):
        """Test successfully adding router through options."""
        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection"
        ) as mock_validate:
            mock_validate.return_value = {"use_https": True, "verify_ssl": False}
            with patch.object(hass.config_entries, "async_update_entry") as mock_update:
                with patch.object(hass.config_entries, "async_reload") as mock_reload:
                    result = await options_flow.async_step_add_router(router_data)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        mock_update.assert_called_once()
        mock_reload.assert_called_once()

    async def test_options_add_router_already_configured(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test adding router that's already configured."""
        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass

        duplicate_router_data = {
            CONF_HOST: "192.168.1.1",  # Same as existing
            CONF_NAME: "Duplicate",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "pass",
        }

        with patch(
            "custom_components.wrtmanager.config_flow.validate_router_connection"
        ) as mock_validate:
            mock_validate.return_value = {"use_https": True, "verify_ssl": False}

            result = await options_flow.async_step_add_router(duplicate_router_data)

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "already_configured"

    async def test_options_remove_router_success(self, hass: HomeAssistant, mock_config_entry):
        """Test successfully removing router."""
        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass

        # Select router to remove
        result = await options_flow.async_step_select_router_to_remove({"router": "1"})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "confirm_remove_router"

        # Confirm removal
        with patch.object(hass.config_entries, "async_update_entry") as mock_update:
            with patch.object(hass.config_entries, "async_reload") as mock_reload:
                result = await options_flow.async_step_confirm_remove_router(1, {"confirm": True})

        assert result["type"] == FlowResultType.CREATE_ENTRY
        mock_update.assert_called_once()
        mock_reload.assert_called_once()

    async def test_options_remove_router_cancel(self, hass: HomeAssistant, mock_config_entry):
        """Test cancelling router removal."""
        options_flow = OptionsFlowHandler(mock_config_entry)
        options_flow.hass = hass

        with patch.object(options_flow, "async_step_init") as mock_init:
            await options_flow.async_step_confirm_remove_router(1, {"confirm": False})
            mock_init.assert_called_once()

    async def test_options_remove_router_cannot_remove_last(
        self, hass: HomeAssistant, mock_config_entry
    ):
        """Test cannot remove last router."""
        mock_config_entry.data[CONF_ROUTERS] = [mock_config_entry.data[CONF_ROUTERS][0]]

        options_flow = OptionsFlowHandler(mock_config_entry)

        result = await options_flow.async_step_select_router_to_remove()

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "cannot_remove_last_router"

    async def test_options_no_routers_configured(self, hass: HomeAssistant, mock_config_entry):
        """Test options with no routers configured."""
        mock_config_entry.data[CONF_ROUTERS] = []

        options_flow = OptionsFlowHandler(mock_config_entry)

        result = await options_flow.async_step_select_router()

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_routers_configured"

    def test_options_flow_properties(self, mock_config_entry):
        """Test OptionsFlow properties."""
        options_flow = OptionsFlowHandler(mock_config_entry)

        assert options_flow.config_entry == mock_config_entry
        assert options_flow.selected_router_index is None

    def test_config_flow_properties(self):
        """Test ConfigFlow properties."""
        config_flow = ConfigFlow()

        assert config_flow.VERSION == 1
        assert config_flow._routers == []

        # Test options flow creation
        mock_entry = MagicMock()
        options_flow = config_flow.async_get_options_flow(mock_entry)
        assert isinstance(options_flow, OptionsFlowHandler)


class TestExceptionClasses:
    """Test the custom exception classes."""

    def test_cannot_connect_exception(self):
        """Test CannotConnect exception."""
        ex = CannotConnect("Test message")
        assert str(ex) == "Test message"
        assert isinstance(ex, Exception)

    def test_invalid_auth_exception(self):
        """Test InvalidAuth exception."""
        ex = InvalidAuth("Test auth message")
        assert str(ex) == "Test auth message"
        assert isinstance(ex, Exception)
