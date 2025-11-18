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
    CONF_ROUTERS,
    DEFAULT_USERNAME,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_TIMEOUT,
    ERROR_UNKNOWN,
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
    ubus_client = UbusClient(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        timeout=10,
    )

    try:
        # Test authentication and basic ubus functionality
        session_id = await hass.async_add_executor_job(ubus_client.authenticate)

        if not session_id:
            raise InvalidAuth("Authentication failed")

        # Test basic iwinfo capability
        devices = await hass.async_add_executor_job(ubus_client.get_wireless_devices, session_id)

        if devices is None:
            raise CannotConnect("Failed to get wireless device list")

        # Return info about the router
        system_info = await hass.async_add_executor_job(ubus_client.get_system_info, session_id)

        return {
            "title": data[CONF_NAME],
            "model": system_info.get("model", "Unknown") if system_info else "Unknown",
            "version": (
                system_info.get("release", {}).get("version", "Unknown")
                if system_info
                else "Unknown"
            ),
            "capabilities": ["iwinfo", "ubus", "dhcp"] if devices else ["basic"],
        }

    except InvalidAuth:
        raise InvalidAuth("Invalid authentication credentials")
    except CannotConnect:
        raise CannotConnect("Cannot connect to router")
    except Exception as ex:
        _LOGGER.exception("Unexpected error validating router: %s", ex)
        raise CannotConnect(f"Unknown error: {ex}")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WrtManager."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._routers: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await validate_router_connection(self.hass, user_input)

                # Add router to our list
                router_config = {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_ROUTER_DESCRIPTION: user_input.get(CONF_ROUTER_DESCRIPTION, ""),
                }
                self._routers.append(router_config)

                # Check if user wants to add more routers
                return await self.async_step_add_more()

            except CannotConnect:
                errors["base"] = ERROR_CANNOT_CONNECT
            except InvalidAuth:
                errors["base"] = ERROR_INVALID_AUTH
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = ERROR_UNKNOWN

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
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
                return self.async_create_entry(
                    title=title,
                    data={CONF_ROUTERS: self._routers},
                )

        return self.async_show_form(
            step_id="add_more",
            data_schema=vol.Schema(
                {
                    vol.Required("add_more", default=False): bool,
                }
            ),
            description_placeholders={
                "router_count": str(len(self._routers)),
                "router_list": ", ".join(router[CONF_NAME] for router in self._routers),
            },
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
