"""Config flow for WrtManager integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ROUTER_DESCRIPTION,
    CONF_ROUTER_HOST,
    CONF_ROUTER_NAME,
    CONF_ROUTER_PASSWORD,
    CONF_ROUTER_USE_HTTPS,
    CONF_ROUTER_USERNAME,
    CONF_ROUTER_VERIFY_SSL,
    CONF_ROUTERS,
    CONF_VLAN_NAMES,
    DEFAULT_USE_HTTPS,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    ERROR_ALREADY_CONFIGURED,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
    VLAN_NAMES,
)
from .ubus_client import UbusClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_NAME): str,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_ROUTER_DESCRIPTION, default=""): str,
    }
)


async def validate_router_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate that we can connect to the router and authenticate."""
    # Try to auto-detect HTTPS by attempting connection with both protocols
    use_https = data.get(CONF_ROUTER_USE_HTTPS, DEFAULT_USE_HTTPS)
    verify_ssl = data.get(CONF_ROUTER_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    # If use_https not explicitly set, try auto-detection
    if CONF_ROUTER_USE_HTTPS not in data:
        _LOGGER.debug("Auto-detecting HTTP/HTTPS for %s", data[CONF_HOST])

        # Try HTTPS first (more secure)
        try:
            https_client = UbusClient(
                host=data[CONF_HOST],
                username=data[CONF_USERNAME],
                password=data[CONF_PASSWORD],
                timeout=5,
                use_https=True,
                verify_ssl=False,  # Assume self-signed cert during auto-detection
            )
            session_id = await https_client.authenticate()
            await https_client.close()

            if session_id:
                _LOGGER.info("Auto-detected HTTPS for router %s", data[CONF_HOST])
                use_https = True
                verify_ssl = False  # Keep verify_ssl=False for self-signed certs
        except Exception as ex:
            _LOGGER.debug("HTTPS connection failed for %s: %s - trying HTTP", data[CONF_HOST], ex)
            use_https = False

    # Now create the actual client with detected/configured protocol
    ubus_client = UbusClient(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        timeout=10,
        use_https=use_https,
        verify_ssl=verify_ssl,
    )

    try:
        # Test authentication and basic ubus functionality
        session_id = await ubus_client.authenticate()

        if not session_id:
            raise InvalidAuth("Authentication failed")

        # Test basic iwinfo capability
        devices = await ubus_client.get_wireless_devices(session_id)

        if devices is None:
            raise CannotConnect("Failed to get wireless device list")

        # Get system info for router details
        system_info = await ubus_client.get_system_info(session_id)
        system_board = await ubus_client.get_system_board(session_id)

        # Test DHCP capability (optional - may not work on dump APs)
        dhcp_capability = False
        try:
            dhcp_data = await ubus_client.get_dhcp_leases(session_id)
            dhcp_capability = dhcp_data is not None
        except Exception:
            pass  # DHCP not available, which is normal for APs

        # Determine router type based on capabilities
        router_type = "Main Router" if dhcp_capability else "Access Point"

        # Close the connection
        await ubus_client.close()

        return {
            "title": data[CONF_NAME],
            "model": system_board.get("model", "Unknown") if system_board else "Unknown",
            "version": (
                system_info.get("release", {}).get("version", "Unknown")
                if system_info
                else "Unknown"
            ),
            "router_type": router_type,
            "use_https": use_https,  # Return detected protocol
            "verify_ssl": verify_ssl,
            "capabilities": {
                "wireless": len(devices) if devices else 0,
                "dhcp": dhcp_capability,
                "system_info": system_info is not None,
            },
        }

    except InvalidAuth:
        raise InvalidAuth("Invalid authentication credentials")
    except CannotConnect:
        raise CannotConnect("Cannot connect to router")
    except Exception as ex:
        _LOGGER.exception("Unexpected error validating router: %s", ex)
        raise CannotConnect(f"Unknown error: {ex}")
    finally:
        # Ensure connection is closed
        try:
            await ubus_client.close()
        except Exception:
            pass


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WrtManager."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._routers: list[dict[str, Any]] = []

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def async_step_add_to_existing(
        self,
        existing_entry: config_entries.ConfigEntry | None = None,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add router to existing WrtManager configuration."""
        # Get the existing entry if not provided
        if existing_entry is None:
            existing_entries = self._async_current_entries()
            if not existing_entries:
                return self.async_abort(reason="no_existing_entry")
            existing_entry = existing_entries[0]

        errors = {}

        if user_input is not None:
            try:
                # Validate the new router connection
                info = await validate_router_connection(self.hass, user_input)

                # Get current routers and check for duplicates
                routers = list(existing_entry.data[CONF_ROUTERS])
                for existing_router in routers:
                    if existing_router[CONF_ROUTER_HOST] == user_input[CONF_HOST]:
                        errors["base"] = ERROR_ALREADY_CONFIGURED
                        break
                else:
                    # Add new router configuration
                    new_router = {
                        CONF_ROUTER_HOST: user_input[CONF_HOST],
                        CONF_ROUTER_NAME: user_input[CONF_NAME],
                        CONF_ROUTER_USERNAME: user_input[CONF_USERNAME],
                        CONF_ROUTER_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_ROUTER_DESCRIPTION: user_input.get(CONF_ROUTER_DESCRIPTION, ""),
                        CONF_ROUTER_USE_HTTPS: info["use_https"],
                        CONF_ROUTER_VERIFY_SSL: info["verify_ssl"],
                    }
                    routers.append(new_router)

                    # Update the existing config entry
                    new_data = dict(existing_entry.data)
                    new_data[CONF_ROUTERS] = routers

                    # Update entry title to reflect new router count
                    router_count = len(routers)
                    plural = "s" if router_count > 1 else ""
                    new_title = f"WrtManager ({router_count} router{plural})"

                    self.hass.config_entries.async_update_entry(
                        existing_entry, data=new_data, title=new_title
                    )

                    # Reload the integration to apply new router
                    await self.hass.config_entries.async_reload(existing_entry.entry_id)

                    return self.async_create_entry(
                        title="Router Added",
                        data={},  # Empty data since we're not creating a new entry
                    )

            except CannotConnect:
                errors["base"] = ERROR_CANNOT_CONNECT
            except InvalidAuth:
                errors["base"] = ERROR_INVALID_AUTH
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = ERROR_UNKNOWN

        return self.async_show_form(
            step_id="add_to_existing",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_NAME): str,
                    vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_ROUTER_DESCRIPTION, default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "description": (
                    f"WrtManager is already configured with "
                    f"{len(existing_entry.data[CONF_ROUTERS])} router(s). "
                    f"Add another router to your existing configuration:"
                ),
                "existing_routers": ", ".join(
                    [r[CONF_ROUTER_NAME] for r in existing_entry.data[CONF_ROUTERS]]
                ),
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        # Check if WrtManager is already configured
        existing_entries = self._async_current_entries()
        if existing_entries:
            # If there's already a WrtManager entry, redirect to add router flow
            return await self.async_step_add_to_existing(existing_entries[0], user_input)

        errors: dict[str, str] = {}
        description_placeholders = {}

        if user_input is not None:
            try:
                # Validate connection and get router info
                info = await validate_router_connection(self.hass, user_input)

                # Check for existing config entries to prevent duplicates
                for entry in self._async_current_entries():
                    for existing_router in entry.data.get(CONF_ROUTERS, []):
                        if existing_router[CONF_HOST] == user_input[CONF_HOST]:
                            errors["base"] = ERROR_ALREADY_CONFIGURED
                            break
                    if errors:
                        break

                if not errors:
                    # Add router to our list with detected protocol settings
                    router_config = {
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_ROUTER_DESCRIPTION: user_input.get(CONF_ROUTER_DESCRIPTION, ""),
                        CONF_ROUTER_USE_HTTPS: info["use_https"],
                        CONF_ROUTER_VERIFY_SSL: info["verify_ssl"],
                    }
                    self._routers.append(router_config)

                    # Proceed to add more routers
                    return await self.async_step_add_more()

            except CannotConnect:
                errors["base"] = ERROR_CANNOT_CONNECT
                description_placeholders["error_details"] = (
                    "Check router IP, network connectivity, and ubus HTTP endpoint"
                )
            except InvalidAuth:
                errors["base"] = ERROR_INVALID_AUTH
                description_placeholders["error_details"] = (
                    "Verify username/password and ensure 'hass' user is configured "
                    "with proper ACL permissions"
                )
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = ERROR_UNKNOWN
                description_placeholders["error_details"] = str(ex)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_add_more(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask if user wants to add more routers."""
        if user_input is not None:
            if user_input.get("add_more", False):
                # Show the user form again to add another router
                return await self.async_step_user()
            else:
                # Create the config entry with all routers
                router_count = len(self._routers)
                plural = "s" if router_count > 1 else ""
                title = f"WrtManager ({router_count} router{plural})"

                # Log successful setup
                router_names = [router[CONF_NAME] for router in self._routers]
                _LOGGER.info("Setting up WrtManager with routers: %s", ", ".join(router_names))

                return self.async_create_entry(
                    title=title,
                    data={CONF_ROUTERS: self._routers},
                )

        # Format router list for display
        router_details = []
        for router in self._routers:
            router_details.append(f"• {router[CONF_NAME]} ({router[CONF_HOST]})")

        return self.async_show_form(
            step_id="add_more",
            data_schema=vol.Schema(
                {
                    vol.Required("add_more", default=False): bool,
                }
            ),
            description_placeholders={
                "router_count": str(len(self._routers)),
                "router_list": "\n".join(router_details),
                "plural": "s" if len(self._routers) > 1 else "",
            },
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle WrtManager options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry
        self.selected_router_index: int | None = None

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry."""
        return self._config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "vlan_names":
                return await self.async_step_vlan_names()
            elif action == "router_credentials":
                return await self.async_step_select_router()
            elif action == "add_router":
                return await self.async_step_add_router()
            elif action == "remove_router":
                return await self.async_step_select_router_to_remove()

        # Create main options menu
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): vol.In(
                        {
                            "vlan_names": "Customize VLAN Names",
                            "router_credentials": "Update Router Credentials",
                            "add_router": "Add New Router",
                            "remove_router": "Remove Router",
                        }
                    )
                }
            ),
            description_placeholders={"description": "Choose what you want to configure:"},
        )

    async def async_step_vlan_names(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure VLAN names."""
        if user_input is not None:
            # Transform input into proper VLAN names dictionary
            vlan_names = {}
            for key, value in user_input.items():
                if key.startswith("vlan_") and value.strip():
                    vlan_id = int(key.replace("vlan_", ""))
                    vlan_names[vlan_id] = value.strip()

            # Preserve existing options and update VLAN names
            new_options = dict(self.config_entry.options)
            new_options[CONF_VLAN_NAMES] = vlan_names

            return self.async_create_entry(title="", data=new_options)

        # Get current VLAN names from options or use defaults
        current_vlan_names = self.config_entry.options.get(CONF_VLAN_NAMES, {})

        # Create form schema for VLAN customization
        options_schema = vol.Schema(
            {
                vol.Optional(
                    f"vlan_{vlan_id}",
                    default=current_vlan_names.get(
                        vlan_id, VLAN_NAMES.get(vlan_id, f"VLAN {vlan_id}")
                    ),
                ): str
                for vlan_id in [1, 2, 3, 10, 13, 20, 100]
            }
        )

        return self.async_show_form(
            step_id="vlan_names",
            data_schema=options_schema,
            description_placeholders={
                "description": "Customize VLAN names that will be displayed in Home Assistant. "
                "These names will be used in device attributes and sensor breakdowns."
            },
        )

    async def async_step_select_router(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select router to update credentials for."""
        routers = self.config_entry.data.get(CONF_ROUTERS, [])

        if not routers:
            return self.async_abort(reason="no_routers_configured")

        if len(routers) == 1:
            # Only one router, skip selection step
            self.selected_router_index = 0
            return await self.async_step_update_credentials()

        if user_input is not None:
            self.selected_router_index = int(user_input["router"])
            return await self.async_step_update_credentials()

        # Create router selection schema
        router_options = {
            str(i): f"{router[CONF_ROUTER_NAME]} ({router[CONF_ROUTER_HOST]})"
            for i, router in enumerate(routers)
        }

        return self.async_show_form(
            step_id="select_router",
            data_schema=vol.Schema({vol.Required("router"): vol.In(router_options)}),
            description_placeholders={
                "description": "Select the router you want to update credentials for:"
            },
        )

    async def async_step_update_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update router credentials."""
        errors = {}

        if user_input is not None:
            routers = list(self.config_entry.data[CONF_ROUTERS])
            current_router = routers[self.selected_router_index]

            # Create updated router config
            updated_router = dict(current_router)
            updated_router[CONF_ROUTER_USERNAME] = user_input[CONF_ROUTER_USERNAME]
            updated_router[CONF_ROUTER_PASSWORD] = user_input[CONF_ROUTER_PASSWORD]

            # Validate new credentials
            try:
                await validate_router_connection(
                    self.hass,
                    {
                        CONF_HOST: current_router[CONF_ROUTER_HOST],
                        CONF_NAME: current_router[CONF_ROUTER_NAME],
                        CONF_USERNAME: user_input[CONF_ROUTER_USERNAME],
                        CONF_PASSWORD: user_input[CONF_ROUTER_PASSWORD],
                        CONF_ROUTER_USE_HTTPS: current_router.get(
                            CONF_ROUTER_USE_HTTPS, DEFAULT_USE_HTTPS
                        ),
                        CONF_ROUTER_VERIFY_SSL: current_router.get(
                            CONF_ROUTER_VERIFY_SSL, DEFAULT_VERIFY_SSL
                        ),
                    },
                )

                # Update the router configuration
                routers[self.selected_router_index] = updated_router

                # Update the config entry
                new_data = dict(self.config_entry.data)
                new_data[CONF_ROUTERS] = routers

                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

                # Reload the integration to apply new credentials
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(
                    title="", data=self.config_entry.options  # Keep existing options unchanged
                )

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "unknown"

        # Get current router details
        routers = self.config_entry.data[CONF_ROUTERS]
        current_router = routers[self.selected_router_index]

        return self.async_show_form(
            step_id="update_credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ROUTER_USERNAME, default=current_router[CONF_ROUTER_USERNAME]
                    ): str,
                    vol.Required(CONF_ROUTER_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "router_name": current_router[CONF_ROUTER_NAME],
                "router_host": current_router[CONF_ROUTER_HOST],
            },
        )

    async def async_step_add_router(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Add a new router to the existing configuration."""
        errors = {}

        if user_input is not None:
            try:
                # Validate the new router connection
                info = await validate_router_connection(self.hass, user_input)

                # Get current routers and add the new one
                routers = list(self.config_entry.data[CONF_ROUTERS])

                # Check if router already exists
                for existing_router in routers:
                    if existing_router[CONF_ROUTER_HOST] == user_input[CONF_HOST]:
                        errors["base"] = "already_configured"
                        break
                else:
                    # Add new router configuration
                    new_router = {
                        CONF_ROUTER_HOST: user_input[CONF_HOST],
                        CONF_ROUTER_NAME: user_input[CONF_NAME],
                        CONF_ROUTER_USERNAME: user_input[CONF_USERNAME],
                        CONF_ROUTER_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_ROUTER_DESCRIPTION: user_input.get(CONF_ROUTER_DESCRIPTION, ""),
                        CONF_ROUTER_USE_HTTPS: info["use_https"],
                        CONF_ROUTER_VERIFY_SSL: info["verify_ssl"],
                    }
                    routers.append(new_router)

                    # Update the config entry
                    new_data = dict(self.config_entry.data)
                    new_data[CONF_ROUTERS] = routers

                    # Update entry title to reflect new router count
                    router_count = len(routers)
                    plural = "s" if router_count > 1 else ""
                    new_title = f"WrtManager ({router_count} router{plural})"

                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data, title=new_title
                    )

                    # Reload the integration to apply new router
                    await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                    return self.async_create_entry(
                        title="", data=self.config_entry.options  # Keep existing options unchanged
                    )

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="add_router",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_NAME): str,
                    vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_ROUTER_DESCRIPTION, default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "description": "Add a new router to your WrtManager configuration:"
            },
        )

    async def async_step_select_router_to_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select router to remove from configuration."""
        routers = self.config_entry.data.get(CONF_ROUTERS, [])

        if len(routers) <= 1:
            return self.async_abort(reason="cannot_remove_last_router")

        if user_input is not None:
            router_index = int(user_input["router"])
            return await self.async_step_confirm_remove_router(router_index)

        # Create router selection schema
        router_options = {
            str(i): f"{router[CONF_ROUTER_NAME]} ({router[CONF_ROUTER_HOST]})"
            for i, router in enumerate(routers)
        }

        return self.async_show_form(
            step_id="select_router_to_remove",
            data_schema=vol.Schema({vol.Required("router"): vol.In(router_options)}),
            description_placeholders={"description": "Select the router you want to remove:"},
        )

    async def async_step_confirm_remove_router(
        self, router_index: int, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm router removal."""
        routers = list(self.config_entry.data[CONF_ROUTERS])
        router_to_remove = routers[router_index]

        if user_input is not None:
            if user_input.get("confirm", False):
                # Remove the router
                routers.pop(router_index)

                # Update the config entry
                new_data = dict(self.config_entry.data)
                new_data[CONF_ROUTERS] = routers

                # Update entry title to reflect new router count
                router_count = len(routers)
                plural = "s" if router_count > 1 else ""
                new_title = f"WrtManager ({router_count} router{plural})"

                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data, title=new_title
                )

                # Reload the integration to remove router entities
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(
                    title="", data=self.config_entry.options  # Keep existing options unchanged
                )
            else:
                # User cancelled, go back to main options
                return await self.async_step_init()

        return self.async_show_form(
            step_id="confirm_remove_router",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
            description_placeholders={
                "router_name": router_to_remove[CONF_ROUTER_NAME],
                "router_host": router_to_remove[CONF_ROUTER_HOST],
                "description": (
                    f"Are you sure you want to remove {router_to_remove[CONF_ROUTER_NAME]} "
                    f"({router_to_remove[CONF_ROUTER_HOST]})?\n\n"
                    f"This will remove all entities associated with this router."
                ),
            },
        )
