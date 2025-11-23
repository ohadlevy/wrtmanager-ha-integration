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
    CONF_ROUTER_USE_HTTPS,
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
    ERROR_TIMEOUT,
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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
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
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Transform input into proper VLAN names dictionary
            vlan_names = {}
            for key, value in user_input.items():
                if key.startswith("vlan_") and value.strip():
                    vlan_id = int(key.replace("vlan_", ""))
                    vlan_names[vlan_id] = value.strip()

            # Save the custom VLAN names
            return self.async_create_entry(title="", data={CONF_VLAN_NAMES: vlan_names})

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
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "description": "Customize VLAN names that will be displayed in Home Assistant. "
                "These names will be used in device attributes and sensor breakdowns."
            },
        )
