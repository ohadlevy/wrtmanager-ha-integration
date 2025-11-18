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
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDataSize,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_MAC,
    ATTR_ROUTER,
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
    """Set up WrtManager sensor entities."""
    coordinator: WrtManagerCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    if not coordinator.last_update_success:
        _LOGGER.warning(
            "Coordinator not ready, skipping sensor setup for %s", config_entry.data.get("host")
        )
        return

    # Create sensor entities for router monitoring
    entities = []
    router_host = config_entry.data.get("host")
    router_name = config_entry.data.get("name", router_host)

    # System monitoring sensors
    entities.extend(
        [
            WrtManagerUptimeSensor(coordinator, router_host, router_name),
            WrtManagerMemoryUsageSensor(coordinator, router_host, router_name),
            WrtManagerMemoryFreeSensor(coordinator, router_host, router_name),
            WrtManagerLoadAverageSensor(coordinator, router_host, router_name),
            WrtManagerTemperatureSensor(coordinator, router_host, router_name),
        ]
    )

    # Interface status sensors
    if coordinator.data and "interfaces" in coordinator.data:
        router_interfaces = coordinator.data["interfaces"].get(router_host, {})
        for interface_name in router_interfaces:
            entities.append(
                WrtManagerInterfaceStatusSensor(
                    coordinator, router_host, router_name, interface_name
                )
            )

    # Connected devices count sensor
    entities.append(WrtManagerDeviceCountSensor(coordinator, router_host, router_name))

    async_add_entities(entities)
    _LOGGER.info("Set up %d sensors for %s", len(entities), config_entry.data.get("host"))


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
            sw_version=system_data.get("kernel", "Unknown"),
            configuration_url=f"http://{self._router_host}",
        )

    def _get_system_data(self) -> Dict[str, Any]:
        """Get system data from coordinator."""
        if not self.coordinator.data or "system_info" not in self.coordinator.data:
            return {}
        return self.coordinator.data["system_info"].get(self._router_host, {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and bool(self._get_system_data())


class WrtManagerUptimeSensor(WrtManagerSensorBase):
    """Sensor for router uptime."""

    def __init__(self, coordinator: WrtManagerCoordinator, router_host: str, router_name: str):
        """Initialize the uptime sensor."""
        super().__init__(coordinator, router_host, router_name, "uptime", "Uptime")
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> Optional[int]:
        """Return the uptime in seconds."""
        system_data = self._get_system_data()
        return system_data.get("uptime")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        system_data = self._get_system_data()
        uptime_seconds = system_data.get("uptime")

        if uptime_seconds:
            uptime_delta = timedelta(seconds=uptime_seconds)
            boot_time = datetime.now() - uptime_delta

            return {
                "uptime_formatted": str(uptime_delta),
                "boot_time": boot_time.isoformat(),
                "days": uptime_delta.days,
                "hours": uptime_delta.seconds // 3600,
            }
        return {}


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

        return {
            "total_mb": round(memory_data.get("total", 0) / 1024, 1),
            "free_mb": round(memory_data.get("free", 0) / 1024, 1),
            "used_mb": round((memory_data.get("total", 0) - memory_data.get("free", 0)) / 1024, 1),
            "available_mb": round(memory_data.get("available", 0) / 1024, 1),
            "buffers_mb": round(memory_data.get("buffers", 0) / 1024, 1),
            "cached_mb": round(memory_data.get("cached", 0) / 1024, 1),
        }


class WrtManagerMemoryFreeSensor(WrtManagerSensorBase):
    """Sensor for free memory."""

    def __init__(self, coordinator: WrtManagerCoordinator, router_host: str, router_name: str):
        """Initialize the free memory sensor."""
        super().__init__(coordinator, router_host, router_name, "memory_free", "Memory Free")
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_native_unit_of_measurement = UnitOfDataSize.MEGABYTES
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:memory"

    @property
    def native_value(self) -> Optional[float]:
        """Return free memory in MB."""
        system_data = self._get_system_data()
        memory_data = system_data.get("memory", {})
        free_kb = memory_data.get("free")

        if free_kb:
            return round(free_kb / 1024, 1)
        return None


class WrtManagerLoadAverageSensor(WrtManagerSensorBase):
    """Sensor for system load average."""

    def __init__(self, coordinator: WrtManagerCoordinator, router_host: str, router_name: str):
        """Initialize the load average sensor."""
        super().__init__(coordinator, router_host, router_name, "load_avg", "Load Average")
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:chip"

    @property
    def native_value(self) -> Optional[float]:
        """Return 1-minute load average."""
        system_data = self._get_system_data()
        load_data = system_data.get("load", [])

        if load_data and len(load_data) >= 1:
            return round(load_data[0], 2)
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return load average details."""
        system_data = self._get_system_data()
        load_data = system_data.get("load", [])

        attributes = {}
        if len(load_data) >= 3:
            attributes.update(
                {
                    "load_1min": round(load_data[0], 2),
                    "load_5min": round(load_data[1], 2),
                    "load_15min": round(load_data[2], 2),
                }
            )
        return attributes


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


class WrtManagerInterfaceStatusSensor(WrtManagerSensorBase):
    """Sensor for network interface status."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        router_host: str,
        router_name: str,
        interface_name: str,
    ):
        """Initialize the interface status sensor."""
        self._interface_name = interface_name
        super().__init__(
            coordinator,
            router_host,
            router_name,
            f"interface_{interface_name}",
            f"Interface {interface_name}",
        )
        self._attr_icon = "mdi:ethernet"

    @property
    def native_value(self) -> Optional[str]:
        """Return interface status."""
        if not self.coordinator.data or "interfaces" not in self.coordinator.data:
            return None

        router_interfaces = self.coordinator.data["interfaces"].get(self._router_host, {})
        interface_data = router_interfaces.get(self._interface_name, {})
        return interface_data.get("status", "unknown")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return interface details."""
        if not self.coordinator.data or "interfaces" not in self.coordinator.data:
            return {}

        router_interfaces = self.coordinator.data["interfaces"].get(self._router_host, {})
        interface_data = router_interfaces.get(self._interface_name, {})

        return {
            "type": interface_data.get("type"),
            "mac": interface_data.get("mac"),
            "ip": interface_data.get("ip"),
            "tx_bytes": interface_data.get("tx_bytes"),
            "rx_bytes": interface_data.get("rx_bytes"),
        }


class WrtManagerDeviceCountSensor(WrtManagerSensorBase):
    """Sensor for connected device count."""

    def __init__(self, coordinator: WrtManagerCoordinator, router_host: str, router_name: str):
        """Initialize the device count sensor."""
        super().__init__(coordinator, router_host, router_name, "device_count", "Connected Devices")
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:devices"

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

        vlan_counts = {"main": 0, "iot": 0, "guest": 0, "unknown": 0}

        for device in self.coordinator.data["devices"]:
            if device.get(ATTR_ROUTER) == self._router_host:
                vlan = device.get(ATTR_VLAN_ID, 1)
                if vlan == 1:
                    vlan_counts["main"] += 1
                elif vlan == 3:
                    vlan_counts["iot"] += 1
                elif vlan == 13:
                    vlan_counts["guest"] += 1
                else:
                    vlan_counts["unknown"] += 1

        return {
            "main_vlan_devices": vlan_counts["main"],
            "iot_vlan_devices": vlan_counts["iot"],
            "guest_vlan_devices": vlan_counts["guest"],
            "unknown_vlan_devices": vlan_counts["unknown"],
        }
