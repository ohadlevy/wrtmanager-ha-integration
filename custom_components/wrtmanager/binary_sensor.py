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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CONNECTED,
    ATTR_DEVICE_TYPE,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_IP,
    ATTR_MAC,
    ATTR_PRIMARY_AP,
    ATTR_ROAMING_COUNT,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
    ATTR_VENDOR,
    ATTR_VLAN_ID,
    CONF_VLAN_NAMES,
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

    # Create interface status binary sensors
    if coordinator.data and "interfaces" in coordinator.data:
        for router_config in coordinator.config_entry.data.get("routers", []):
            router_host = router_config["host"]
            router_name = router_config["name"]
            router_interfaces = coordinator.data["interfaces"].get(router_host, {})

            for interface_name in router_interfaces:
                entities.append(
                    WrtInterfaceStatusSensor(
                        coordinator, router_host, router_name, interface_name, config_entry
                    )
                )

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
        self._router_host = config_entry.data.get("host")

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
            "mac_address": device_data.get(ATTR_MAC),
            "ip": device_data.get(ATTR_IP),
            "hostname": device_data.get(ATTR_HOSTNAME),
            "vendor": device_data.get(ATTR_VENDOR),
            "device_type": device_data.get(ATTR_DEVICE_TYPE),
            "signal_dbm": device_data.get(ATTR_SIGNAL_DBM),
            "roaming_count": device_data.get(ATTR_ROAMING_COUNT, 0),
        }

        # Only show router if different from primary AP (to avoid duplication)
        router = device_data.get(ATTR_ROUTER)
        primary_ap = device_data.get(ATTR_PRIMARY_AP)
        if router and router != primary_ap:
            attributes["router"] = router
        if primary_ap:
            attributes["primary_ap"] = primary_ap

        # Add VLAN information
        vlan_id = device_data.get(ATTR_VLAN_ID)
        if vlan_id:
            attributes["vlan_id"] = vlan_id
            # Get custom VLAN names from config entry options
            custom_vlan_names = self._config_entry.options.get(CONF_VLAN_NAMES, {})
            # Merge custom names with defaults
            vlan_names = {**VLAN_NAMES, **custom_vlan_names}
            attributes["vlan_name"] = vlan_names.get(vlan_id, f"VLAN {vlan_id}")

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

        # Get router information for better device context
        router = device_data.get(ATTR_ROUTER) if device_data else self._router_host

        return DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            name=device_name,
            manufacturer=device_data.get(ATTR_VENDOR) if device_data else "Unknown",
            model=device_data.get(ATTR_DEVICE_TYPE) if device_data else "Network Device",
            sw_version=f"Connected to {router}" if router else None,
            # Note: No configuration_url for connected devices - they don't have web interfaces
            # Only routers/infrastructure devices should have configuration_url
            # via_device disabled until router device hierarchy is properly implemented
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
            return f"Unknown Device {self._mac[-5:].replace(':', '')}"

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
        mac_prefix = self._mac[:8].upper()  # AA:BB:CC format

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
                return f"Private Device {self._mac[-5:].replace(':', '')}"
            else:
                return f"{vendor_guess} Device {self._mac[-5:].replace(':', '')}"

        # Final fallback with shorter MAC suffix
        return f"Unknown Device {self._mac[-5:].replace(':', '')}"


class WrtInterfaceStatusSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for network interface status."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        interface_name: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the interface status sensor."""
        super().__init__(coordinator)
        self._router_host = router_host
        self._router_name = router_name
        self._interface_name = interface_name
        self._config_entry = config_entry

        # Create unique entity ID
        safe_router = router_host.replace(".", "_").replace("-", "_")
        safe_interface = interface_name.replace(".", "_").replace("-", "_")
        self._attr_unique_id = f"wrtmanager_{safe_router}_{safe_interface}_status"
        self._attr_name = f"{router_name} {interface_name}"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:ethernet"

    @property
    def is_on(self) -> bool:
        """Return True if interface is up and has carrier."""
        interface_data = self._get_interface_data()
        if not interface_data:
            return False

        # Interface is "on" if it's both up AND has carrier
        return interface_data.get("up", False) and interface_data.get("carrier", False)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._get_interface_data() is not None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        interface_data = self._get_interface_data()
        if not interface_data:
            return {}

        attributes = {
            "interface_type": interface_data.get("type"),
            "devtype": interface_data.get("devtype"),
            "mac_address": interface_data.get("macaddr"),
            "present": interface_data.get("present"),
            "up": interface_data.get("up"),
            "carrier": interface_data.get("carrier"),
            "speed": interface_data.get("speed"),
            "mtu": interface_data.get("mtu"),
        }

        # Add statistics if available
        stats = interface_data.get("statistics", {})
        if stats:
            # Convert bytes to MB for readability
            rx_mb = round(stats.get("rx_bytes", 0) / 1024 / 1024, 2)
            tx_mb = round(stats.get("tx_bytes", 0) / 1024 / 1024, 2)

            attributes.update(
                {
                    "rx_bytes_mb": rx_mb if rx_mb > 0 else stats.get("rx_bytes", 0),
                    "tx_bytes_mb": tx_mb if tx_mb > 0 else stats.get("tx_bytes", 0),
                    "rx_packets": stats.get("rx_packets"),
                    "tx_packets": stats.get("tx_packets"),
                    "rx_errors": stats.get("rx_errors"),
                    "tx_errors": stats.get("tx_errors"),
                }
            )

        # Add bridge members for bridge interfaces
        bridge_members = interface_data.get("bridge-members", [])
        if bridge_members:
            attributes["bridge_members"] = bridge_members

        # Determine status description
        if interface_data.get("up", False):
            if interface_data.get("carrier", False):
                status_desc = "Up with carrier"
            else:
                status_desc = "Up but no carrier"
        elif interface_data.get("present", False):
            status_desc = "Down"
        else:
            status_desc = "Not present"

        attributes["status_description"] = status_desc

        # Remove None values
        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for grouping."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._router_host)},
            name=self._router_name,
            manufacturer="OpenWrt",
            model="Router",
            configuration_url=f"http://{self._router_host}",
        )

    def _get_interface_data(self) -> Dict[str, Any] | None:
        """Get current interface data from coordinator."""
        if not self.coordinator.data or "interfaces" not in self.coordinator.data:
            return None

        router_interfaces = self.coordinator.data["interfaces"].get(self._router_host, {})
        return router_interfaces.get(self._interface_name)
