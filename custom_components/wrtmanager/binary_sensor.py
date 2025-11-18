"""Binary sensor platform for WrtManager."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CONNECTED,
    ATTR_DEVICE_TYPE,
    ATTR_HOSTNAME,
    ATTR_IP,
    ATTR_MAC,
    ATTR_PRIMARY_AP,
    ATTR_ROAMING_COUNT,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
    ATTR_VENDOR,
    ATTR_VLAN_ID,
    DOMAIN,
    VLAN_NAMES,
)
from .coordinator import WrtManagerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WrtManager binary sensors."""
    coordinator: WrtManagerCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Wait for first successful data update
    if not coordinator.data:
        return

    entities = []

    # Create binary sensors for device presence
    for device in coordinator.data.get("devices", []):
        mac = device.get(ATTR_MAC)
        if mac:
            entities.append(WrtDevicePresenceSensor(coordinator, mac, config_entry))

    async_add_entities(entities)


class WrtDevicePresenceSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for device presence on network."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        mac: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the device presence sensor."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        self._config_entry = config_entry

        # Get device info for initial setup
        device_data = self._get_device_data()
        device_name = self._get_device_name(device_data)

        self._attr_unique_id = f"{DOMAIN}_{mac.lower().replace(':', '_')}_presence"
        self._attr_name = f"{device_name} Presence"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return True if device is connected."""
        device_data = self._get_device_data()
        return device_data.get(ATTR_CONNECTED, False) if device_data else False

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._get_device_data() is not None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        device_data = self._get_device_data()
        if not device_data:
            return {}

        attributes = {
            ATTR_MAC: device_data.get(ATTR_MAC),
            ATTR_IP: device_data.get(ATTR_IP),
            ATTR_HOSTNAME: device_data.get(ATTR_HOSTNAME),
            ATTR_VENDOR: device_data.get(ATTR_VENDOR),
            ATTR_DEVICE_TYPE: device_data.get(ATTR_DEVICE_TYPE),
            ATTR_ROUTER: device_data.get(ATTR_ROUTER),
            ATTR_PRIMARY_AP: device_data.get(ATTR_PRIMARY_AP),
            ATTR_SIGNAL_DBM: device_data.get(ATTR_SIGNAL_DBM),
            ATTR_ROAMING_COUNT: device_data.get(ATTR_ROAMING_COUNT, 0),
        }

        # Add VLAN information
        vlan_id = device_data.get(ATTR_VLAN_ID)
        if vlan_id:
            attributes["vlan_id"] = vlan_id
            attributes["vlan_name"] = VLAN_NAMES.get(vlan_id, f"VLAN {vlan_id}")

        # Add signal quality description
        signal = device_data.get(ATTR_SIGNAL_DBM)
        if signal:
            if signal >= -50:
                signal_quality = "Excellent"
            elif signal >= -60:
                signal_quality = "Good"
            elif signal >= -70:
                signal_quality = "Fair"
            else:
                signal_quality = "Poor"
            attributes["signal_quality"] = signal_quality

        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for grouping in Home Assistant."""
        device_data = self._get_device_data()
        device_name = self._get_device_name(device_data)

        return DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            name=device_name,
            manufacturer=device_data.get(ATTR_VENDOR) if device_data else "Unknown",
            model=device_data.get(ATTR_DEVICE_TYPE) if device_data else "Network Device",
            sw_version=device_data.get(ATTR_ROUTER) if device_data else None,
            via_device=(DOMAIN, self._config_entry.entry_id),
        )

    def _get_device_data(self) -> Dict[str, Any] | None:
        """Get current device data from coordinator."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None

        for device in self.coordinator.data["devices"]:
            if device.get(ATTR_MAC) == self._mac:
                return device
        return None

    def _get_device_name(self, device_data: Dict[str, Any] | None) -> str:
        """Get friendly device name."""
        if not device_data:
            return f"Device {self._mac[-8:].replace(':', '')}"

        # Priority: hostname > device identification > MAC suffix
        hostname = device_data.get(ATTR_HOSTNAME)
        if hostname and hostname != "*" and hostname.strip():
            return hostname

        vendor = device_data.get(ATTR_VENDOR, "")
        device_type = device_data.get(ATTR_DEVICE_TYPE, "")
        mac_suffix = self._mac[-8:].replace(":", "")

        if vendor and device_type != "Unknown Device":
            if device_type == "IoT Switch":
                return f"{vendor} Switch-{mac_suffix}"
            elif device_type == "Mobile Device":
                return f"{vendor} Phone-{mac_suffix}"
            elif device_type == "Computer":
                return f"{vendor} Computer-{mac_suffix}"
            else:
                return f"{vendor} Device-{mac_suffix}"

        return f"Device-{mac_suffix}"
