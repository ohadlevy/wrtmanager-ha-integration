"""
WrtManager Sensor implementation.

Provides system monitoring sensors for OpenWrt routers including uptime,
memory usage, CPU load, and network interface status.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry

# Handle HA version compatibility for units
from homeassistant.const import CONF_HOST, CONF_NAME, PERCENTAGE

# Try to import modern units, fallback to legacy values
try:
    from homeassistant.const import UnitOfDataSize, UnitOfTime

    UNIT_MEGABYTES = UnitOfDataSize.MEGABYTES
    UNIT_SECONDS = UnitOfTime.SECONDS
except ImportError:
    # Fallback for older HA versions - use string constants directly
    UNIT_MEGABYTES = "MB"
    UNIT_SECONDS = "s"
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DEVICE_TYPE,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_MAC,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
    ATTR_VLAN_ID,
    CONF_ROUTERS,
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
    """Set up WrtManager sensor entities."""
    coordinator: WrtManagerCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    if not coordinator.last_update_success:
        _LOGGER.warning("Coordinator not ready, skipping sensor setup for %s", config_entry.title)
        return

    # Create sensor entities for each router
    entities = []
    routers = config_entry.data.get(CONF_ROUTERS, [])

    for router_config in routers:
        router_host = router_config[CONF_HOST]
        router_name = router_config[CONF_NAME]

        # System monitoring sensors (create for each router)
        entities.extend(
            [
                WrtManagerMemoryUsageSensor(coordinator, router_host, router_name),
                WrtManagerMemoryFreeSensor(coordinator, router_host, router_name),
            ]
        )

        # Only add temperature sensor if router provides temperature data
        if coordinator.data and "system_info" in coordinator.data:
            system_data = coordinator.data["system_info"].get(router_host, {})
            if system_data.get("temperature") is not None:
                entities.append(WrtManagerTemperatureSensor(coordinator, router_host, router_name))
        _LOGGER.info("Created system monitoring sensors for %s", router_name)

        # Interface binary sensors are now in binary_sensor.py for better UX

        # Connected devices count sensor
        entities.append(
            WrtManagerDeviceCountSensor(coordinator, router_host, router_name, config_entry)
        )

        # Create interface device count sensors (devices per wireless interface/SSID)
        if coordinator.data and "devices" in coordinator.data:
            # Get unique wireless interfaces for this router
            wireless_interfaces = set()
            for device in coordinator.data["devices"]:
                if device.get(ATTR_ROUTER) == router_host:
                    interface = device.get(ATTR_INTERFACE)
                    if interface and (interface.startswith("wlan") or "ap" in interface.lower()):
                        wireless_interfaces.add(interface)

            # Create a device count sensor for each wireless interface
            for interface in wireless_interfaces:
                entities.append(
                    WrtManagerInterfaceDeviceCountSensor(
                        coordinator, router_host, router_name, interface, config_entry
                    )
                )

            _LOGGER.info(
                "Created %d interface device count sensors for %s: %s",
                len(wireless_interfaces),
                router_name,
                list(wireless_interfaces),
            )

    async_add_entities(entities)
    _LOGGER.info("Set up %d sensors for %d routers", len(entities), len(routers))


class WrtManagerSensorBase(CoordinatorEntity[WrtManagerCoordinator], SensorEntity):
    """Base class for WrtManager sensor entities."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        sensor_type: str,
        sensor_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._router_host = router_host
        self._router_name = router_name
        self._sensor_type = sensor_type

        # Create unique entity ID
        self._attr_unique_id = f"{router_host}_{sensor_type}"
        self._attr_name = f"{router_name} {sensor_name}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the router."""
        system_data = self._get_system_data()

        return DeviceInfo(
            identifiers={(DOMAIN, self._router_host)},
            name=self._router_name,
            manufacturer="OpenWrt",
            model=system_data.get("model", "Unknown"),
            sw_version=self._get_openwrt_version(system_data),
            configuration_url=f"http://{self._router_host}",
        )

    def _get_system_data(self) -> Dict[str, Any]:
        """Get system data from coordinator."""
        if not self.coordinator.data or "system_info" not in self.coordinator.data:
            return {}
        return self.coordinator.data["system_info"].get(self._router_host, {})

    def _get_openwrt_version(self, system_data: Dict[str, Any]) -> str:
        """Get OpenWrt version from system data, fallback to kernel version."""
        release_info = system_data.get("release", {})

        # Try to get OpenWrt version first
        openwrt_version = release_info.get("version")
        if openwrt_version:
            return openwrt_version

        # Fallback to kernel version if OpenWrt version is not available
        kernel_version = system_data.get("kernel")
        if kernel_version:
            return f"Kernel {kernel_version}"

        return "Unknown"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and bool(self._get_system_data())


class WrtManagerMemoryUsageSensor(WrtManagerSensorBase):
    """Sensor for memory usage percentage."""

    def __init__(self, coordinator: WrtManagerCoordinator, router_host: str, router_name: str):
        """Initialize the memory usage sensor."""
        super().__init__(coordinator, router_host, router_name, "memory_usage", "Memory Usage")
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:memory"

    @property
    def native_value(self) -> Optional[float]:
        """Return memory usage percentage."""
        system_data = self._get_system_data()
        memory_data = system_data.get("memory", {})

        total = memory_data.get("total")
        free = memory_data.get("free")

        if total and free:
            used = total - free
            return round((used / total) * 100, 1)
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return memory details."""
        system_data = self._get_system_data()
        memory_data = system_data.get("memory", {})

        # OpenWrt returns memory values in bytes, convert to MB
        return {
            "total_mb": round(memory_data.get("total", 0) / (1024 * 1024), 1),
            "free_mb": round(memory_data.get("free", 0) / (1024 * 1024), 1),
            "used_mb": round(
                (memory_data.get("total", 0) - memory_data.get("free", 0)) / (1024 * 1024), 1
            ),
            "available_mb": round(memory_data.get("available", 0) / (1024 * 1024), 1),
            "buffers_mb": round(memory_data.get("buffers", 0) / (1024 * 1024), 1),
            "cached_mb": round(memory_data.get("cached", 0) / (1024 * 1024), 1),
        }


class WrtManagerMemoryFreeSensor(WrtManagerSensorBase):
    """Sensor for free memory."""

    def __init__(self, coordinator: WrtManagerCoordinator, router_host: str, router_name: str):
        """Initialize the free memory sensor."""
        super().__init__(coordinator, router_host, router_name, "memory_free", "Memory Free")
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_native_unit_of_measurement = UNIT_MEGABYTES
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:memory"

    @property
    def native_value(self) -> Optional[float]:
        """Return free memory in MB."""
        system_data = self._get_system_data()
        memory_data = system_data.get("memory", {})
        free_bytes = memory_data.get("free")

        if free_bytes:
            # OpenWrt returns memory in bytes, convert to MB
            return round(free_bytes / (1024 * 1024), 1)
        return None


class WrtManagerTemperatureSensor(WrtManagerSensorBase):
    """Sensor for router temperature if available."""

    def __init__(self, coordinator: WrtManagerCoordinator, router_host: str, router_name: str):
        """Initialize the temperature sensor."""
        super().__init__(coordinator, router_host, router_name, "temperature", "Temperature")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = "°C"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Optional[float]:
        """Return temperature in Celsius."""
        system_data = self._get_system_data()
        # Temperature data varies by router model
        return system_data.get("temperature")

    @property
    def available(self) -> bool:
        """Return if temperature is available."""
        return super().available and self._get_system_data().get("temperature") is not None


class WrtManagerDeviceCountSensor(WrtManagerSensorBase):
    """Sensor for connected device count."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        config_entry: ConfigEntry,
    ):
        """Initialize the device count sensor."""
        super().__init__(coordinator, router_host, router_name, "device_count", "Connected Devices")
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:devices"
        self._config_entry = config_entry

    @property
    def native_value(self) -> Optional[int]:
        """Return number of connected devices."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return 0

        # Count devices connected to this specific router
        device_count = 0
        for device in self.coordinator.data["devices"]:
            if device.get(ATTR_ROUTER) == self._router_host:
                device_count += 1

        return device_count

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return device breakdown by VLAN."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return {}

        # Get custom VLAN names from config entry options
        custom_vlan_names = self._config_entry.options.get(CONF_VLAN_NAMES, {})
        # Merge custom names with defaults
        vlan_names = {**VLAN_NAMES, **custom_vlan_names}

        # Count devices by VLAN and device type
        vlan_counts = {}
        device_type_counts = {}

        for device in self.coordinator.data["devices"]:
            if device.get(ATTR_ROUTER) == self._router_host:
                # Count by VLAN
                vlan_id = device.get(ATTR_VLAN_ID, 1)
                vlan_name = vlan_names.get(vlan_id, f"VLAN {vlan_id}")
                vlan_key = vlan_name.lower().replace(" ", "_").replace("-", "_")
                vlan_counts[vlan_key] = vlan_counts.get(vlan_key, 0) + 1

                # Count by device type for categorization
                device_type = device.get(ATTR_DEVICE_TYPE, "Unknown Device")
                type_key = device_type.lower().replace(" ", "_").replace("-", "_")
                device_type_counts[type_key] = device_type_counts.get(type_key, 0) + 1

        # Create dynamic attributes based on actual VLANs and device types found
        attributes = {}

        # Add VLAN breakdown
        for vlan_key, count in vlan_counts.items():
            attributes[f"{vlan_key}_devices"] = count

        # Add device type categorization breakdown
        for type_key, count in device_type_counts.items():
            attributes[f"{type_key}_count"] = count

        # Add total if we have multiple VLANs
        if len(vlan_counts) > 1:
            attributes["total_devices"] = sum(vlan_counts.values())

        return attributes


class WrtManagerInterfaceDeviceCountSensor(WrtManagerSensorBase):
    """Sensor for device count per wireless interface (SSID)."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        interface: str,
        config_entry: ConfigEntry,
    ):
        """Initialize the interface device count sensor."""
        super().__init__(
            coordinator,
            router_host,
            router_name,
            f"device_count_{interface.replace('.', '_').replace('-', '_')}",
            f"{interface.upper()} Devices",
        )
        self._interface = interface
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:wifi-marker"
        self._config_entry = config_entry

    @property
    def native_value(self) -> Optional[int]:
        """Return number of devices connected to this wireless interface."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return 0

        # Count devices connected to this specific interface on this router
        device_count = 0
        interface_matches = []
        all_device_interfaces = []

        for device in self.coordinator.data["devices"]:
            if device.get(ATTR_ROUTER) == self._router_host:
                device_interface = device.get(ATTR_INTERFACE)
                all_device_interfaces.append(device_interface)

                if device_interface == self._interface:
                    device_count += 1
                    interface_matches.append(device.get(ATTR_MAC, "unknown"))

        # Debug logging to track interface matching issues
        _LOGGER.debug(
            "Interface %s on %s: found %d devices. Sensor interface='%s', "
            "device interfaces=%s, matches=%s",
            self._interface,
            self._router_host,
            device_count,
            self._interface,
            all_device_interfaces,
            interface_matches,
        )

        return device_count

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return device breakdown and signal statistics for this interface."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return {}

        # Get custom VLAN names from config entry options
        custom_vlan_names = self._config_entry.options.get(CONF_VLAN_NAMES, {})
        # Merge custom names with defaults
        vlan_names = {**VLAN_NAMES, **custom_vlan_names}

        # Analyze devices connected to this interface
        interface_devices = []
        signal_readings = []
        vlan_counts = {}
        device_type_counts = {}

        for device in self.coordinator.data["devices"]:
            if (
                device.get(ATTR_ROUTER) == self._router_host
                and device.get(ATTR_INTERFACE) == self._interface
            ):
                interface_devices.append(device)

                # Collect signal strength for statistics
                signal = device.get(ATTR_SIGNAL_DBM)
                if signal:
                    signal_readings.append(signal)

                # Count by VLAN
                vlan_id = device.get(ATTR_VLAN_ID, 1)
                vlan_name = vlan_names.get(vlan_id, f"VLAN {vlan_id}")
                vlan_key = vlan_name.lower().replace(" ", "_").replace("-", "_")
                vlan_counts[vlan_key] = vlan_counts.get(vlan_key, 0) + 1

                # Count by device type for categorization
                device_type = device.get(ATTR_DEVICE_TYPE, "Unknown Device")
                # Create a clean key for device type counting
                type_key = device_type.lower().replace(" ", "_").replace("-", "_")
                device_type_counts[type_key] = device_type_counts.get(type_key, 0) + 1

        attributes = {
            "interface": self._interface,
            "router": self._router_name,
            "total_devices": len(interface_devices),
        }

        # Add VLAN breakdown if devices exist
        if vlan_counts:
            attributes.update(
                {f"{vlan_key}_devices": count for vlan_key, count in vlan_counts.items()}
            )

        # Add device type categorization breakdown
        if device_type_counts:
            attributes.update(
                {f"{type_key}_count": count for type_key, count in device_type_counts.items()}
            )

        # Add signal statistics if available
        if signal_readings:
            attributes.update(
                {
                    "avg_signal_dbm": round(sum(signal_readings) / len(signal_readings), 1),
                    "min_signal_dbm": min(signal_readings),
                    "max_signal_dbm": max(signal_readings),
                    "signal_quality": self._calculate_signal_quality(signal_readings),
                }
            )

        # Add device list (up to 10 devices for brevity)
        if interface_devices:
            device_list = []
            for i, device in enumerate(interface_devices[:10]):
                device_name = device.get(ATTR_HOSTNAME, device.get(ATTR_MAC, "Unknown"))
                device_list.append(device_name)

            attributes["connected_devices"] = device_list
            if len(interface_devices) > 10:
                attributes["additional_devices"] = len(interface_devices) - 10

        return attributes

    def _calculate_signal_quality(self, signal_readings: List[float]) -> str:
        """Calculate overall signal quality for the interface."""
        avg_signal = sum(signal_readings) / len(signal_readings)

        if avg_signal >= -50:
            return "Excellent"
        elif avg_signal >= -60:
            return "Good"
        elif avg_signal >= -70:
            return "Fair"
        else:
            return "Poor"
