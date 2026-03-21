"""Button platform for WrtManager - WiFi client disconnect."""

from __future__ import annotations

import logging
from typing import Any, Dict

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CONNECTED,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_MAC,
    ATTR_ROUTER,
    DOMAIN,
)
from .coordinator import WrtManagerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WrtManager disconnect buttons."""
    coordinator: WrtManagerCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    if not coordinator.data:
        _LOGGER.debug("Button setup skipped - no coordinator data available")
        return

    # Track created buttons to avoid duplicates
    created_buttons: set[str] = set()

    @callback
    def _async_add_new_buttons() -> None:
        """Add disconnect buttons for newly discovered devices."""
        if not coordinator.data or "devices" not in coordinator.data:
            return

        new_entities = []
        for device in coordinator.data["devices"]:
            mac = device.get(ATTR_MAC)
            router = device.get(ATTR_ROUTER)
            interface = device.get(ATTR_INTERFACE)

            if not mac or not router or not interface:
                continue

            # Unique key per device per router
            button_key = f"{mac}_{router}"
            if button_key in created_buttons:
                continue

            created_buttons.add(button_key)
            new_entities.append(
                WrtDisconnectButton(coordinator, mac, router, interface, config_entry)
            )

        if new_entities:
            async_add_entities(new_entities)
            _LOGGER.debug("Added %d new disconnect buttons", len(new_entities))

    # Create buttons for initially known devices
    _async_add_new_buttons()

    # Listen for coordinator updates to add buttons for newly discovered devices
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_new_buttons))


class WrtDisconnectButton(CoordinatorEntity, ButtonEntity):
    """Button to disconnect a WiFi client from a specific AP."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:wifi-remove"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        mac: str,
        router_host: str,
        interface: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the disconnect button."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        self._router_host = router_host
        self._interface = interface
        self._config_entry = config_entry

        # Include router in unique ID since same device can appear on multiple APs
        router_id = router_host.replace(".", "_")
        mac_id = mac.lower().replace(":", "_")
        self._attr_unique_id = f"{DOMAIN}_{router_id}_{mac_id}_disconnect"

    @property
    def name(self) -> str:
        """Return the name of the button."""
        router_name = self._get_router_name()
        return f"Disconnect from {router_name}"

    @property
    def available(self) -> bool:
        """Return True if button is available (device connected on this AP)."""
        if not self.coordinator.last_update_success:
            return False
        device_data = self._get_device_data()
        return device_data is not None and device_data.get(ATTR_CONNECTED, False)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to group button under the WiFi client device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            connections={(CONNECTION_NETWORK_MAC, self._mac)},
        )

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        device_data = self._get_device_data()
        attrs = {
            "mac_address": self._mac,
            "router": self._router_host,
            "interface": self._interface,
        }
        if device_data:
            hostname = device_data.get(ATTR_HOSTNAME)
            if hostname:
                attrs["hostname"] = hostname
        return attrs

    async def async_press(self) -> None:
        """Disconnect the client when button is pressed."""
        device_data = self._get_device_data()
        if not device_data:
            raise HomeAssistantError(
                f"Device {self._mac} is not currently connected to {self._router_host}"
            )

        # Use current interface from live data (may have changed due to band steering)
        interface = device_data.get(ATTR_INTERFACE, self._interface)

        try:
            success = await self.coordinator.disconnect_client(
                self._router_host, interface, self._mac
            )
            if not success:
                raise HomeAssistantError(
                    f"Failed to disconnect {self._mac} from {self._router_host}. "
                    f"Check logs - you may need to re-run the setup script on the router "
                    f"to grant hostapd del_client permission."
                )
        except ValueError as ex:
            raise HomeAssistantError(str(ex)) from ex

    def _get_device_data(self) -> Dict[str, Any] | None:
        """Get current device data for this MAC on this router."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None

        for device in self.coordinator.data["devices"]:
            if device.get(ATTR_MAC) == self._mac and device.get(ATTR_ROUTER) == self._router_host:
                return device
        return None

    def _get_router_name(self) -> str:
        """Get friendly router name from config."""
        for router_config in self._config_entry.data.get("routers", []):
            if router_config.get("host") == self._router_host:
                return router_config.get("name", self._router_host)
        return self._router_host
