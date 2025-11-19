"""
WrtManager Device Tracker implementation.

Tracks connected devices on OpenWrt routers using ubus API.
Provides real-time device presence detection with VLAN and roaming support.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DEVICE_TYPE,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_IP,
    ATTR_LAST_SEEN,
    ATTR_MAC,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
    ATTR_VENDOR,
    ATTR_VLAN_ID,
    DOMAIN,
)
from .coordinator import WrtManagerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WrtManager device tracker entities."""
    coordinator: WrtManagerCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    if not coordinator.last_update_success:
        _LOGGER.warning(
            "Coordinator not ready, skipping device tracker setup for %s",
            config_entry.data.get("host"),
        )
        return

    # Create device tracker entities for all discovered devices
    entities = []

    if coordinator.data and "devices" in coordinator.data:
        for device in coordinator.data["devices"]:
            if device.get(ATTR_MAC):
                entities.append(WrtManagerDeviceTracker(coordinator, device[ATTR_MAC]))

    async_add_entities(entities)
    _LOGGER.info("Set up %d device trackers for %s", len(entities), config_entry.data.get("host"))


class WrtManagerDeviceTracker(CoordinatorEntity[WrtManagerCoordinator], ScannerEntity):
    """Representation of a device tracked by WrtManager."""

    def __init__(self, coordinator: WrtManagerCoordinator, mac_address: str) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator)
        self._mac_address = mac_address.upper()

        # Get device info from coordinator data
        self._device_info = self._get_device_data()

        # Create unique entity ID based on router and MAC
        # Get the router name from device data if available, or use a safe default
        device_data = self._get_device_data()
        router_host = device_data.get(ATTR_ROUTER, "unknown_router")
        # Use safe characters for unique ID
        safe_router = router_host.replace(".", "_").replace("-", "_")
        self._attr_unique_id = f"wrtmanager_{safe_router}_{self._mac_address.replace(':', '')}"
        self._attr_name = self._generate_device_name()

    def _get_device_data(self) -> Dict[str, Any]:
        """Get current device data from coordinator."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return {}

        for device in self.coordinator.data["devices"]:
            if device.get(ATTR_MAC, "").upper() == self._mac_address:
                return device
        return {}

    def _generate_device_name(self) -> str:
        """Generate a friendly name for the device."""
        device_data = self._device_info

        # Try to use hostname if available and meaningful
        hostname = device_data.get(ATTR_HOSTNAME)
        if hostname and hostname.strip() and hostname != "*" and hostname != "?":
            # Clean up hostname (remove domain suffixes, etc.)
            clean_name = hostname.split(".")[0].strip()
            if clean_name and len(clean_name) > 1:
                return clean_name

        # Try to use vendor + device type combination
        vendor = device_data.get(ATTR_VENDOR)
        device_type = device_data.get(ATTR_DEVICE_TYPE)

        if vendor and device_type and device_type != "Unknown Device":
            # Create more descriptive names based on device type
            if "shelly" in vendor.lower():
                return f"{vendor} Switch"
            elif "gree" in vendor.lower() or "air" in device_type.lower():
                return f"{vendor} AC Unit"
            elif device_type == "IoT Switch":
                return f"{vendor} Smart Switch"
            elif device_type == "Mobile Device":
                return f"{vendor} Phone"
            elif device_type == "Computer":
                return f"{vendor} Computer"
            elif "smart" in device_type.lower():
                return f"{vendor} {device_type}"
            else:
                return f"{vendor} {device_type}"

        # Try just vendor
        if vendor and vendor != "Unknown":
            return f"{vendor} Device"

        # Try to identify by MAC OUI (first 3 octets)
        mac_prefix = self._mac_address[:8].upper()  # AA:BB:CC format

        # Common MAC OUI mappings
        oui_vendors = {
            "00:1B:44": "Apple",
            "00:25:00": "Apple",
            "28:F0:76": "Apple",
            "A4:5E:60": "Apple",
            "B8:8D:12": "Apple",
            "CC:08:8D": "Apple",
            "10:FE:ED": "Ubiquiti",
            "F0:9F:C2": "Ubiquiti",
            "78:8A:20": "Ubiquiti",
            "C8:47:8C": "Shelly",
            "CC:8C:BF": "Gree",
            "AE:72:AD": "Random MAC",  # Locally administered
        }

        vendor_guess = oui_vendors.get(mac_prefix)
        if vendor_guess:
            if vendor_guess == "Random MAC":
                return f"Private Device {self._mac_address[-5:].replace(':', '')}"
            else:
                return f"{vendor_guess} Device {self._mac_address[-5:].replace(':', '')}"

        # Final fallback with shorter MAC suffix
        return f"Unknown Device {self._mac_address[-5:].replace(':', '')}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        device_data = self._device_info

        return DeviceInfo(
            identifiers={(DOMAIN, self._mac_address)},
            name=self._attr_name,
            manufacturer=device_data.get(ATTR_VENDOR, "Unknown"),
            model=device_data.get(ATTR_DEVICE_TYPE, "Network Device"),
            via_device=(DOMAIN, self.coordinator.config_entry.data.get("host")),
        )

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        return SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        """Return true if the device is connected."""
        device_data = self._get_device_data()
        return bool(device_data)

    @property
    def ip_address(self) -> str | None:
        """Return the IP address of the device."""
        device_data = self._get_device_data()
        return device_data.get(ATTR_IP)

    @property
    def mac_address(self) -> str:
        """Return the MAC address of the device."""
        return self._mac_address

    @property
    def hostname(self) -> str | None:
        """Return the hostname of the device."""
        device_data = self._get_device_data()
        return device_data.get(ATTR_HOSTNAME)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        device_data = self._get_device_data()

        attributes = {
            "mac_address": self._mac_address,
            "router": self.coordinator.config_entry.data.get("host"),
        }

        # Add wireless-specific attributes
        if device_data.get(ATTR_INTERFACE):
            attributes["interface"] = device_data[ATTR_INTERFACE]

        if device_data.get(ATTR_SIGNAL_DBM) is not None:
            attributes["signal_strength"] = device_data[ATTR_SIGNAL_DBM]

        # Add VLAN information if available
        if device_data.get(ATTR_VLAN_ID):
            attributes["vlan"] = device_data[ATTR_VLAN_ID]

        # Add device identification
        if device_data.get(ATTR_VENDOR):
            attributes["vendor"] = device_data[ATTR_VENDOR]

        if device_data.get(ATTR_DEVICE_TYPE):
            attributes["device_type"] = device_data[ATTR_DEVICE_TYPE]

        # Add last seen timestamp
        if device_data.get(ATTR_LAST_SEEN):
            attributes["last_seen"] = device_data[ATTR_LAST_SEEN]

        return attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update device info when coordinator updates
        self._device_info = self._get_device_data()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Added device tracker for %s (%s) on %s",
            self._attr_name,
            self._mac_address,
            self.coordinator.config_entry.data.get("host"),
        )
