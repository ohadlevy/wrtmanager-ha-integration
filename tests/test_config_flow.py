"""Test config flow for WrtManager."""

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.wrtmanager.const import DOMAIN

pytestmark = pytest.mark.asyncio


class TestConfigFlow:
    """Test the config flow."""

    @pytest.mark.skip(
        reason="Fixture setup needs to be updated to match current HomeAssistant testing patterns"
    )
    async def test_form(self, hass: HomeAssistant):
        """Test we get the form."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {}

    @pytest.mark.skip(
        reason="Fixture setup needs to be updated to match current HomeAssistant testing patterns"
    )
    async def test_form_invalid_auth(self, hass: HomeAssistant):
        """Test we handle invalid auth."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        with pytest.patch(
            "custom_components.wrtmanager.config_flow.UbusClient.authenticate",
            side_effect=Exception("Invalid credentials"),
        ):
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "host": "192.168.1.1",
                    "username": "test",
                    "password": "test",
                },
            )

        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"] == {"base": "invalid_auth"}

    @pytest.mark.skip(
        reason="Fixture setup needs to be updated to match current HomeAssistant testing patterns"
    )
    async def test_form_cannot_connect(self, hass: HomeAssistant):
        """Test we handle cannot connect error."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        with pytest.patch(
            "custom_components.wrtmanager.config_flow.UbusClient.authenticate",
            side_effect=ConnectionError("Cannot connect"),
        ):
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "host": "192.168.1.1",
                    "username": "test",
                    "password": "test",
                },
            )

        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"] == {"base": "cannot_connect"}

    @pytest.mark.skip(
        reason="Fixture setup needs to be updated to match current HomeAssistant testing patterns"
    )
    async def test_form_success(self, hass: HomeAssistant):
        """Test successful configuration."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        with (
            pytest.patch(
                "custom_components.wrtmanager.config_flow.UbusClient.authenticate",
                return_value="test_session_id",
            ),
            pytest.patch("custom_components.wrtmanager.config_flow.UbusClient.close"),
        ):
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "host": "192.168.1.1",
                    "username": "test",
                    "password": "test",
                },
            )
            await hass.async_block_till_done()

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["title"] == "WrtManager"
        assert result2["data"] == {
            "routers": [
                {
                    "host": "192.168.1.1",
                    "username": "test",
                    "password": "test",
                    "use_https": False,
                    "verify_ssl": False,
                }
            ]
        }
