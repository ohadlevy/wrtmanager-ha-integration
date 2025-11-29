"""
WrtManager Sensor implementation.

Provides system monitoring sensors for OpenWrt routers including uptime,
memory usage, CPU load, and network interface status.
"""

from __future__ import annotations

import logging
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
from homeassistant.core import HomeAssistant
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
    classify_signal_quality,
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

            # Create sensors for each wireless interface
            for interface in wireless_interfaces:
                entities.extend(
                    [
                        # Device count sensor
                        WrtManagerInterfaceDeviceCountSensor(
                            coordinator, router_host, router_name, interface, config_entry
                        ),
                        # Signal strength sensors
                        WrtManagerSignalStrengthSensor(
                            coordinator, router_host, router_name, interface
                        ),
                        WrtManagerSignalQualitySensor(
                            coordinator, router_host, router_name, interface
                        ),
                    ]
                )

            _LOGGER.info(
                "Created %d interface sensors (device count + signal) for %s: %s",
                len(wireless_interfaces) * 3,  # device count + signal strength + signal quality
                router_name,
                list(wireless_interfaces),
            )

        # Create traffic sensors for network interfaces
        if coordinator.data and "interfaces" in coordinator.data:
            router_interfaces = coordinator.data["interfaces"].get(router_host, {})

            for interface_name, interface_data in router_interfaces.items():
                # Only create sensors for interfaces with statistics
                if interface_data.get("statistics"):
                    # Create download sensor
                    entities.append(
                        WrtManagerInterfaceDownloadSensor(
                            coordinator, router_host, router_name, interface_name
                        )
                    )
                    # Create upload sensor
                    entities.append(
                        WrtManagerInterfaceUploadSensor(
                            coordinator, router_host, router_name, interface_name
                        )
                    )

            _LOGGER.info("Created traffic sensors for %s interfaces", len(router_interfaces))

            # Create router traffic card sensor (aggregated traffic view)
            entities.append(
                WrtManagerRouterTrafficCardSensor(coordinator, router_host, router_name)
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

        # Create unique entity ID using router name for clean entity_id generation
        safe_router_name = router_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_unique_id = f"wrtmanager_{safe_router_name}_{sensor_type}"
        self._attr_name = f"{router_name} {sensor_name}"
        self._attr_has_entity_name = False  # Use full name for entity_id

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

    @staticmethod
    def _is_wan_interface(interface_name: str) -> bool:
        """Check if interface is a WAN/internet interface."""
        lower_name = interface_name.lower()
        wan_patterns = ["wan", "pppoe", "eth0.2", "eth1", "internet", "modem"]
        return any(pattern in lower_name for pattern in wan_patterns)

    @staticmethod
    def _get_friendly_interface_name(interface_name: str) -> str:
        """Get a human-friendly interface name."""
        lower_name = interface_name.lower()

        # WAN/Internet interfaces
        if "pppoe" in lower_name:
            return f"{interface_name} (Internet)"
        elif "wan" in lower_name or "eth0.2" in lower_name or "eth1" in lower_name:
            return f"{interface_name} (WAN)"

        # Wireless interfaces
        if "phy" in lower_name and "ap" in lower_name:
            return f"{interface_name} (WiFi)"
        elif interface_name.startswith("wlan"):
            return f"{interface_name} (WiFi)"

        # Ethernet interfaces
        elif interface_name.startswith("eth"):
            return f"{interface_name} (Ethernet)"

        # Bridge interfaces
        elif interface_name.startswith("br-"):
            return f"{interface_name} (Bridge)"

        # Default
        return interface_name

    @staticmethod
    def _get_interface_icon(interface_name: str, direction: str = "download") -> str:
        """Get appropriate icon for interface type and direction."""
        lower_name = interface_name.lower()
        is_download = direction == "download"

        # WAN/Internet interfaces
        if "pppoe" in lower_name or "wan" in lower_name:
            return "mdi:download" if is_download else "mdi:upload"

        # Wireless interfaces
        if "phy" in lower_name or "wlan" in lower_name:
            return "mdi:wifi-arrow-down" if is_download else "mdi:wifi-arrow-up"

        # Default network icon
        return "mdi:download-network" if is_download else "mdi:upload-network"

    def _get_router_devices(self) -> List[Dict[str, Any]]:
        """Get all devices for this router."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return []

        return [
            device
            for device in self.coordinator.data["devices"]
            if device.get(ATTR_ROUTER) == self._router_host
        ]

    def _get_interface_devices(self, interface: str) -> List[Dict[str, Any]]:
        """Get all devices for this router and interface."""
        router_devices = self._get_router_devices()
        return [device for device in router_devices if device.get(ATTR_INTERFACE) == interface]

    def _get_interface_data_by_name(self, interface_name: str) -> Dict[str, Any] | None:
        """Get interface data from coordinator by interface name."""
        if not self.coordinator.data or "interfaces" not in self.coordinator.data:
            return None

        router_interfaces = self.coordinator.data["interfaces"].get(self._router_host, {})
        return router_interfaces.get(interface_name)

    def _get_signal_readings_for_interface(self, interface: str) -> List[float]:
        """Get signal strength readings for all devices on a given interface."""
        interface_devices = self._get_interface_devices(interface)

        signal_readings = []
        for device in interface_devices:
            signal = device.get(ATTR_SIGNAL_DBM)
            if signal is not None:
                signal_readings.append(signal)

        return signal_readings


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
        router_devices = self._get_router_devices()
        return len(router_devices)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return device breakdown by VLAN."""
        router_devices = self._get_router_devices()
        if not router_devices:
            return {}

        # Get custom VLAN names from config entry options
        custom_vlan_names = self._config_entry.options.get(CONF_VLAN_NAMES, {})
        # Merge custom names with defaults
        vlan_names = {**VLAN_NAMES, **custom_vlan_names}

        # Count devices by VLAN and device type
        vlan_counts = {}
        device_type_counts = {}

        for device in router_devices:
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
        interface_devices = self._get_interface_devices(self._interface)

        # Debug logging to track interface matching issues
        router_devices = self._get_router_devices()
        all_device_interfaces = [device.get(ATTR_INTERFACE) for device in router_devices]
        interface_matches = [device.get(ATTR_MAC, "unknown") for device in interface_devices]

        _LOGGER.debug(
            "Interface %s on %s: found %d devices. Sensor interface='%s', "
            "device interfaces=%s, matches=%s",
            self._interface,
            self._router_host,
            len(interface_devices),
            self._interface,
            all_device_interfaces,
            interface_matches,
        )

        return len(interface_devices)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return device breakdown and signal statistics for this interface."""
        interface_devices = self._get_interface_devices(self._interface)
        if not interface_devices:
            return {}

        # Get custom VLAN names from config entry options
        custom_vlan_names = self._config_entry.options.get(CONF_VLAN_NAMES, {})
        # Merge custom names with defaults
        vlan_names = {**VLAN_NAMES, **custom_vlan_names}

        # Analyze devices connected to this interface
        signal_readings = []
        vlan_counts = {}
        device_type_counts = {}

        for device in interface_devices:
            # Collect signal strength for statistics
            signal = device.get(ATTR_SIGNAL_DBM)
            if signal is not None:
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
        return classify_signal_quality(avg_signal)


class WrtManagerInterfaceDownloadSensor(WrtManagerSensorBase):
    """Sensor for interface download traffic."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        interface_name: str,
    ):
        """Initialize the interface download sensor."""
        safe_interface = interface_name.replace(".", "_").replace("-", "_")
        sensor_type = f"{safe_interface}_download"
        sensor_name = f"{self._get_friendly_interface_name(interface_name)} Download"

        super().__init__(coordinator, router_host, router_name, sensor_type, sensor_name)
        self._interface_name = interface_name
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_native_unit_of_measurement = UNIT_MEGABYTES
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = self._get_interface_icon(interface_name, "download")

    @property
    def native_value(self) -> Optional[float]:
        """Return download traffic in MB."""
        interface_data = self._get_interface_data_by_name(self._interface_name)
        if not interface_data:
            return None

        stats = interface_data.get("statistics", {})
        rx_bytes = stats.get("rx_bytes", 0)

        if rx_bytes:
            # Convert bytes to MB
            return round(rx_bytes / (1024 * 1024), 2)
        return 0

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        interface_data = self._get_interface_data_by_name(self._interface_name)
        if not interface_data:
            return {}

        stats = interface_data.get("statistics", {})
        return {
            "interface": self._interface_name,
            "interface_type": interface_data.get("type"),
            "rx_packets": stats.get("rx_packets", 0),
            "rx_errors": stats.get("rx_errors", 0),
            "rx_bytes": stats.get("rx_bytes", 0),
            "is_wan": self._is_wan_interface(self._interface_name),
        }


class WrtManagerInterfaceUploadSensor(WrtManagerSensorBase):
    """Sensor for interface upload traffic."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        interface_name: str,
    ):
        """Initialize the interface upload sensor."""
        safe_interface = interface_name.replace(".", "_").replace("-", "_")
        sensor_type = f"{safe_interface}_upload"
        sensor_name = f"{self._get_friendly_interface_name(interface_name)} Upload"

        super().__init__(coordinator, router_host, router_name, sensor_type, sensor_name)
        self._interface_name = interface_name
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_native_unit_of_measurement = UNIT_MEGABYTES
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = self._get_interface_icon(interface_name, "upload")

    @property
    def native_value(self) -> Optional[float]:
        """Return upload traffic in MB."""
        interface_data = self._get_interface_data_by_name(self._interface_name)
        if not interface_data:
            return None

        stats = interface_data.get("statistics", {})
        tx_bytes = stats.get("tx_bytes", 0)

        if tx_bytes:
            # Convert bytes to MB
            return round(tx_bytes / (1024 * 1024), 2)
        return 0

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        interface_data = self._get_interface_data_by_name(self._interface_name)
        if not interface_data:
            return {}

        stats = interface_data.get("statistics", {})
        return {
            "interface": self._interface_name,
            "interface_type": interface_data.get("type"),
            "tx_packets": stats.get("tx_packets", 0),
            "tx_errors": stats.get("tx_errors", 0),
            "tx_bytes": stats.get("tx_bytes", 0),
            "is_wan": self._is_wan_interface(self._interface_name),
        }


class WrtManagerSignalStrengthSensor(WrtManagerSensorBase):
    """Sensor for average signal strength per wireless interface."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        interface: str,
    ):
        """Initialize the signal strength sensor."""
        super().__init__(
            coordinator,
            router_host,
            router_name,
            f"signal_strength_{interface.replace('.', '_').replace('-', '_')}",
            f"{interface.upper()} Signal Strength",
        )
        self._interface = interface
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_native_unit_of_measurement = "dBm"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:wifi-strength-2"

    @property
    def native_value(self) -> Optional[float]:
        """Return average signal strength for this interface."""
        signal_readings = self._get_signal_readings_for_interface(self._interface)

        if signal_readings:
            return round(sum(signal_readings) / len(signal_readings), 1)
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return signal strength statistics."""
        interface_devices = self._get_interface_devices(self._interface)
        signal_readings = self._get_signal_readings_for_interface(self._interface)

        attributes = {
            "interface": self._interface,
            "router": self._router_name,
            "device_count": len(interface_devices),
        }

        if signal_readings:
            min_signal = min(signal_readings)
            max_signal = max(signal_readings)
            attributes.update(
                {
                    "min_signal_dbm": min_signal,
                    "max_signal_dbm": max_signal,
                    "signal_range_dbm": max_signal - min_signal,
                    "devices_with_signal": len(signal_readings),
                }
            )

        return attributes


class WrtManagerSignalQualitySensor(WrtManagerSensorBase):
    """Sensor for signal quality rating per wireless interface."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        interface: str,
    ):
        """Initialize the signal quality sensor."""
        super().__init__(
            coordinator,
            router_host,
            router_name,
            f"signal_quality_{interface.replace('.', '_').replace('-', '_')}",
            f"{interface.upper()} Signal Quality",
        )
        self._interface = interface
        self._attr_icon = "mdi:signal"

    @property
    def native_value(self) -> Optional[str]:
        """Return signal quality rating for this interface."""
        signal_readings = self._get_signal_readings_for_interface(self._interface)

        if signal_readings:
            avg_signal = sum(signal_readings) / len(signal_readings)
            return classify_signal_quality(avg_signal)

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return signal quality breakdown."""
        signal_readings = self._get_signal_readings_for_interface(self._interface)

        quality_counts = {"Excellent": 0, "Good": 0, "Fair": 0, "Poor": 0}

        # Categorize each signal reading
        for signal in signal_readings:
            signal_quality = classify_signal_quality(signal)
            quality_counts[signal_quality] += 1

        attributes = {
            "interface": self._interface,
            "router": self._router_name,
            "total_devices": len(signal_readings),
        }

        if signal_readings:
            attributes.update(
                {
                    "avg_signal_dbm": round(sum(signal_readings) / len(signal_readings), 1),
                    "excellent_devices": quality_counts["Excellent"],
                    "good_devices": quality_counts["Good"],
                    "fair_devices": quality_counts["Fair"],
                    "poor_devices": quality_counts["Poor"],
                }
            )

            # Add percentage breakdown if we have multiple devices
            if len(signal_readings) > 1:
                total = len(signal_readings)
                attributes.update(
                    {
                        "excellent_percent": round((quality_counts["Excellent"] / total) * 100, 1),
                        "good_percent": round((quality_counts["Good"] / total) * 100, 1),
                        "fair_percent": round((quality_counts["Fair"] / total) * 100, 1),
                        "poor_percent": round((quality_counts["Poor"] / total) * 100, 1),
                    }
                )

        return attributes


class WrtManagerRouterTrafficCardSensor(WrtManagerSensorBase):
    """Sensor that aggregates traffic data from all router interfaces for a traffic card view."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
    ):
        """Initialize the router traffic card sensor."""
        super().__init__(
            coordinator, router_host, router_name, "router_traffic_total", "Total Traffic"
        )
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_native_unit_of_measurement = UNIT_MEGABYTES
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:router-wireless"

    @property
    def native_value(self) -> Optional[float]:
        """Return total traffic (download + upload) across all interfaces in MB."""
        return self._get_total_traffic()

    def _get_total_traffic(self) -> float:
        """Calculate total traffic across all interfaces."""
        agg_data = self._get_aggregated_traffic_data()

        # Sum all categorized traffic including "other" interfaces
        total_download = (
            agg_data["wan_traffic"]["download"]
            + agg_data["wifi_traffic"]["download"]
            + agg_data["ethernet_traffic"]["download"]
            + agg_data["other_traffic"]["download"]
        )
        total_upload = (
            agg_data["wan_traffic"]["upload"]
            + agg_data["wifi_traffic"]["upload"]
            + agg_data["ethernet_traffic"]["upload"]
            + agg_data["other_traffic"]["upload"]
        )

        return total_download + total_upload

    def _get_aggregated_traffic_data(self) -> Dict[str, Any]:
        """Get all traffic and interface data in a single pass through interfaces."""
        if not self.coordinator.data or "interfaces" not in self.coordinator.data:
            return {
                "wan_traffic": {"download": 0, "upload": 0},
                "wifi_traffic": {"download": 0, "upload": 0},
                "ethernet_traffic": {"download": 0, "upload": 0},
                "other_traffic": {"download": 0, "upload": 0},
                "interface_counts": {"wan": 0, "wifi": 0, "ethernet": 0, "other": 0},
            }

        router_interfaces = self.coordinator.data["interfaces"].get(self._router_host, {})
        wan_traffic = {"download": 0, "upload": 0}
        wifi_traffic = {"download": 0, "upload": 0}
        ethernet_traffic = {"download": 0, "upload": 0}
        other_traffic = {"download": 0, "upload": 0}
        interface_counts = {"wan": 0, "wifi": 0, "ethernet": 0, "other": 0}

        for interface_name, interface_data in router_interfaces.items():
            stats = interface_data.get("statistics", {})
            if not stats:
                continue

            rx_bytes = stats.get("rx_bytes", 0) or 0
            tx_bytes = stats.get("tx_bytes", 0) or 0
            download_mb = round(rx_bytes / (1024 * 1024), 2)
            upload_mb = round(tx_bytes / (1024 * 1024), 2)

            # Categorize interface and accumulate traffic
            if self._is_wan_interface(interface_name):
                wan_traffic["download"] += download_mb
                wan_traffic["upload"] += upload_mb
                interface_counts["wan"] += 1
            elif (
                interface_name.startswith("wlan")
                or "phy" in interface_name.lower()
                or "ap" in interface_name.lower()
            ):
                wifi_traffic["download"] += download_mb
                wifi_traffic["upload"] += upload_mb
                interface_counts["wifi"] += 1
            elif interface_name.startswith("eth"):
                ethernet_traffic["download"] += download_mb
                ethernet_traffic["upload"] += upload_mb
                interface_counts["ethernet"] += 1
            else:
                other_traffic["download"] += download_mb
                other_traffic["upload"] += upload_mb
                interface_counts["other"] += 1

        return {
            "wan_traffic": wan_traffic,
            "wifi_traffic": wifi_traffic,
            "ethernet_traffic": ethernet_traffic,
            "other_traffic": other_traffic,
            "interface_counts": interface_counts,
        }

    def _get_connected_devices_info(self) -> Dict[str, Any]:
        """Get connected devices information for the traffic card."""
        router_devices = self._get_router_devices()
        if not router_devices:
            return {"total": 0, "wifi": 0, "ethernet": 0}

        wifi_devices = 0
        ethernet_devices = 0

        for device in router_devices:
            interface = device.get(ATTR_INTERFACE, "")
            if interface.startswith("wlan") or "ap" in interface.lower():
                wifi_devices += 1
            elif interface.startswith("eth"):
                ethernet_devices += 1

        return {
            "total": len(router_devices),
            "wifi": wifi_devices,
            "ethernet": ethernet_devices,
        }

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return detailed traffic breakdown and router information."""
        agg_data = self._get_aggregated_traffic_data()
        wan_traffic = agg_data["wan_traffic"]
        wifi_traffic = agg_data["wifi_traffic"]
        ethernet_traffic = agg_data["ethernet_traffic"]
        other_traffic = agg_data["other_traffic"]
        interface_counts = agg_data["interface_counts"]
        device_info = self._get_connected_devices_info()

        attributes = {
            # Total traffic breakdown (now includes other interfaces)
            "total_download_mb": (
                wan_traffic["download"]
                + wifi_traffic["download"]
                + ethernet_traffic["download"]
                + other_traffic["download"]
            ),
            "total_upload_mb": (
                wan_traffic["upload"]
                + wifi_traffic["upload"]
                + ethernet_traffic["upload"]
                + other_traffic["upload"]
            ),
            # WAN/Internet traffic
            "wan_download_mb": wan_traffic["download"],
            "wan_upload_mb": wan_traffic["upload"],
            "wan_total_mb": wan_traffic["download"] + wan_traffic["upload"],
            # WiFi traffic
            "wifi_download_mb": wifi_traffic["download"],
            "wifi_upload_mb": wifi_traffic["upload"],
            "wifi_total_mb": wifi_traffic["download"] + wifi_traffic["upload"],
            # Ethernet traffic
            "ethernet_download_mb": ethernet_traffic["download"],
            "ethernet_upload_mb": ethernet_traffic["upload"],
            "ethernet_total_mb": ethernet_traffic["download"] + ethernet_traffic["upload"],
            # Other interfaces traffic (bridges, loopback, etc.)
            "other_download_mb": other_traffic["download"],
            "other_upload_mb": other_traffic["upload"],
            "other_total_mb": other_traffic["download"] + other_traffic["upload"],
            # Interface counts
            "wan_interfaces": interface_counts["wan"],
            "wifi_interfaces": interface_counts["wifi"],
            "ethernet_interfaces": interface_counts["ethernet"],
            "other_interfaces": interface_counts["other"],
            "total_interfaces": sum(interface_counts.values()),
            # Connected devices
            "total_devices": device_info["total"],
            "wifi_devices": device_info["wifi"],
            "ethernet_devices": device_info["ethernet"],
            # Router info
            "router_name": self._router_name,
            "router_host": self._router_host,
        }

        return attributes
