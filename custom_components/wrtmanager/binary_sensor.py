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
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
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
    CONF_VLAN_NAMES,
    DOMAIN,
    VLAN_NAMES,
    classify_signal_quality,
)
from .coordinator import WrtManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# Module-level set to track which global SSID entities have been created during this HA session
_CREATED_GLOBAL_SSIDS = set()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WrtManager binary sensors."""
    coordinator: WrtManagerCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Wait for first successful data update
    if not coordinator.data:
        _LOGGER.debug("Binary sensor setup skipped - no coordinator data available")
        return

    entities = []

    # Debug logging for available data
    _LOGGER.debug(
        "Binary sensor setup - coordinator data keys: %s",
        list(coordinator.data.keys()) if coordinator.data else "None",
    )

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
                # Filter out interfaces that are not useful for monitoring
                # Skip radio configuration containers (radio0, radio1, etc.)
                if interface_name.startswith("radio") and interface_name[5:].isdigit():
                    continue

                # Skip loopback interface - not useful for network monitoring
                if interface_name == "lo":
                    continue

                entities.append(
                    WrtInterfaceStatusSensor(
                        coordinator, router_host, router_name, interface_name, config_entry
                    )
                )

    # Create SSID binary sensors with area-based grouping (global view as primary)
    _LOGGER.debug(
        "Checking for SSID data: coordinator.data exists=%s, 'ssids' in data=%s",
        bool(coordinator.data),
        "ssids" in coordinator.data if coordinator.data else False,
    )

    if coordinator.data and "ssids" in coordinator.data:
        _LOGGER.debug("SSID data found: %s", coordinator.data.get("ssids", {}))
        ssid_entities = await _create_ssid_entities(hass, coordinator, config_entry)
        entities.extend(ssid_entities)
        _LOGGER.info("Created %d SSID binary sensors", len(ssid_entities))
    else:
        # Log helpful information when no SSID sensors can be created
        if not coordinator.data:
            _LOGGER.warning("No SSID binary sensors created - coordinator has no data")
        elif "ssids" not in coordinator.data:
            _LOGGER.info(
                "No SSID binary sensors created - no SSID data available (likely dump AP mode)"
            )
            _LOGGER.debug(
                "Available data keys: %s",
                list(coordinator.data.keys()) if coordinator.data else "None",
            )
        else:
            _LOGGER.debug("SSID data structure: %s", coordinator.data.get("ssids", {}))

    async_add_entities(entities)


async def _create_ssid_entities(
    hass: HomeAssistant,
    coordinator: WrtManagerCoordinator,
    config_entry: ConfigEntry,
) -> List[BinarySensorEntity]:
    """Create SSID binary sensors with area-based grouping (global view as primary)."""
    entities = []

    # Get device and area registries
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)

    # Group SSIDs by name across all routers for global view
    global_ssids = {}

    # Aggregate SSID data from ALL WrtManager coordinators, not just the current one
    all_coordinators = []
    all_router_configs = []

    # Get all WrtManager config entries and their coordinators
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            entry_coordinator = hass.data[DOMAIN][entry.entry_id]
            if entry_coordinator.data and "ssids" in entry_coordinator.data:
                all_coordinators.append(entry_coordinator)
                all_router_configs.extend(entry.data.get("routers", []))

    _LOGGER.debug(
        "Aggregating SSID data from %d coordinators covering %d routers",
        len(all_coordinators),
        len(all_router_configs),
    )

    for router_config in all_router_configs:
        router_host = router_config["host"]
        router_name = router_config["name"]

        # Find the coordinator that has this router's data
        router_ssids = []
        for coord in all_coordinators:
            if router_host in coord.data.get("ssids", {}):
                router_ssids = coord.data["ssids"].get(router_host, [])
                break

        for ssid_info in router_ssids:
            ssid_name = ssid_info["ssid_name"]

            if ssid_name not in global_ssids:
                global_ssids[ssid_name] = {
                    "routers": [],
                    "ssid_instances": [],
                    "areas": set(),
                }

            global_ssids[ssid_name]["routers"].append(router_host)
            global_ssids[ssid_name]["ssid_instances"].append(
                {
                    "router_host": router_host,
                    "router_name": router_name,
                    "ssid_info": ssid_info,
                }
            )

            # Check if this router is assigned to an area
            router_device = device_registry.async_get_device(identifiers={(DOMAIN, router_host)})
            if router_device and router_device.area_id:
                area = area_registry.async_get_area(router_device.area_id)
                if area:
                    global_ssids[ssid_name]["areas"].add(area.name)

    # Debug SSID grouping
    _LOGGER.debug(
        "SSID grouping results: %s",
        {
            ssid_name: {
                "router_count": len(ssid_group["routers"]),
                "instance_count": len(ssid_group["ssid_instances"]),
                "routers": ssid_group["routers"],
                "instance_details": [
                    (
                        inst["router_host"],
                        inst["ssid_info"].get("ssid_interface", "?"),
                        inst["ssid_info"].get("radio", "?"),
                    )
                    for inst in ssid_group["ssid_instances"]
                ],
            }
            for ssid_name, ssid_group in global_ssids.items()
        },
    )

    # Create global SSID entities (primary usage case)
    # Use module-level tracking to prevent duplicate creation
    for ssid_name, ssid_group in global_ssids.items():
        # Only create the entity if it hasn't been created yet in this session
        if ssid_name not in _CREATED_GLOBAL_SSIDS:
            entities.append(
                WrtGlobalSSIDBinarySensor(
                    coordinator=coordinator,
                    ssid_name=ssid_name,
                    ssid_group=ssid_group,
                    config_entry=config_entry,
                )
            )
            _CREATED_GLOBAL_SSIDS.add(ssid_name)
            _LOGGER.debug("Creating new global SSID entity for: %s", ssid_name)
        else:
            _LOGGER.debug("Skipping duplicate global SSID entity for: %s", ssid_name)

        # Create area-specific entities if routers are in different areas
        if len(ssid_group["areas"]) > 1:
            for area_name in ssid_group["areas"]:
                # Filter instances for this area
                area_instances = []
                for instance in ssid_group["ssid_instances"]:
                    router_device = device_registry.async_get_device(
                        identifiers={(DOMAIN, instance["router_host"])}
                    )
                    if router_device and router_device.area_id:
                        area = area_registry.async_get_area(router_device.area_id)
                        if area and area.name == area_name:
                            area_instances.append(instance)

                if area_instances:
                    # Create area-specific key for tracking
                    area_ssid_key = f"{area_name}_{ssid_name}"

                    if area_ssid_key not in _CREATED_GLOBAL_SSIDS:
                        entities.append(
                            WrtAreaSSIDBinarySensor(
                                coordinator=coordinator,
                                ssid_name=ssid_name,
                                area_name=area_name,
                                area_instances=area_instances,
                                config_entry=config_entry,
                            )
                        )
                        _CREATED_GLOBAL_SSIDS.add(area_ssid_key)
                        _LOGGER.debug("Creating new area SSID entity: %s %s", area_name, ssid_name)
                    else:
                        _LOGGER.debug(
                            "Skipping duplicate area SSID entity: %s %s", area_name, ssid_name
                        )

    return entities


class WrtGlobalSSIDBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Global binary sensor for SSID enabled/disabled status across all routers."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        ssid_name: str,
        ssid_group: Dict[str, Any],
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the global SSID status sensor."""
        super().__init__(coordinator)
        self._ssid_name = ssid_name
        self._ssid_group = ssid_group
        self._config_entry = config_entry

        # Create unique entity ID for global SSID
        safe_ssid = ssid_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
        self._attr_unique_id = f"wrtmanager_global_{safe_ssid}_enabled"
        self._attr_name = f"Global {ssid_name} SSID"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:wifi"

    @property
    def is_on(self) -> bool:
        """Return True if SSID is enabled on any router."""
        # Use dynamic aggregation from all coordinators
        current_ssid_group = self._get_current_global_ssid_data()
        for instance in current_ssid_group["ssid_instances"]:
            ssid_data = self._get_current_ssid_data(instance["router_host"], instance["ssid_info"])
            if ssid_data and not ssid_data.get("disabled", False):
                return True
        return False

    @property
    def available(self) -> bool:
        """Return True if at least one router has this SSID available."""
        # Use dynamic aggregation from all coordinators
        current_ssid_group = self._get_current_global_ssid_data()
        return self.coordinator.last_update_success and any(
            self._get_current_ssid_data(instance["router_host"], instance["ssid_info"]) is not None
            for instance in current_ssid_group["ssid_instances"]
        )

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        enabled_routers = []
        disabled_routers = []
        total_instances = 0
        frequency_bands = set()
        all_routers = set()

        # Dynamically aggregate data from ALL coordinators
        current_ssid_group = self._get_current_global_ssid_data()

        for instance in current_ssid_group["ssid_instances"]:
            ssid_data = self._get_current_ssid_data(instance["router_host"], instance["ssid_info"])
            if ssid_data:
                total_instances += 1
                router_name = instance["router_name"]
                all_routers.add(instance["router_host"])

                if ssid_data.get("disabled", False):
                    disabled_routers.append(router_name)
                else:
                    enabled_routers.append(router_name)

                # Collect frequency band info
                if ssid_data.get("is_consolidated"):
                    frequency_bands.update(ssid_data.get("frequency_bands", []))
                else:
                    radio = ssid_data.get("radio", "")
                    if "0" in radio:
                        frequency_bands.add("2.4GHz")
                    elif "1" in radio:
                        frequency_bands.add("5GHz")

        attributes = {
            "ssid_name": self._ssid_name,
            "router_count": len(all_routers),
            "enabled_routers": enabled_routers,
            "disabled_routers": disabled_routers,
            "total_instances": total_instances,
            "frequency_bands": sorted(list(frequency_bands)),
            "coverage": "Global (all routers)",
            "areas": (
                sorted(list(current_ssid_group["areas"]))
                if current_ssid_group["areas"]
                else ["No areas assigned"]
            ),
        }

        # Get common configuration from first available instance
        for instance in self._ssid_group["ssid_instances"]:
            ssid_data = self._get_current_ssid_data(instance["router_host"], instance["ssid_info"])
            if ssid_data:
                attributes.update(
                    {
                        "ssid_mode": ssid_data.get("mode", "ap"),
                        "encryption": ssid_data.get("encryption"),
                        "hidden": ssid_data.get("hidden", False),
                        "network_name": ssid_data.get("network"),
                    }
                )
                break

        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for grouping."""
        # Check if first router device exists before using it as via_device
        via_device_id = None
        if self._ssid_group.get("routers"):
            first_router_host = self._ssid_group["routers"][0]
            device_registry = dr.async_get(self.hass)
            router_device = device_registry.async_get_device(
                identifiers={(DOMAIN, first_router_host)}
            )
            if router_device:
                via_device_id = (DOMAIN, first_router_host)

        return DeviceInfo(
            identifiers={(DOMAIN, f"global_ssid_{self._ssid_name}")},
            name=f"Global {self._ssid_name}",
            manufacturer="WrtManager",
            model="Global SSID Controller",
            via_device=via_device_id,
        )

    def _get_current_ssid_data(
        self, router_host: str, original_ssid_info: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """Get current SSID data from the correct coordinator for specific router."""
        # Search across all WrtManager coordinators to find the one with this router's data
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id in self.hass.data.get(DOMAIN, {}):
                coordinator = self.hass.data[DOMAIN][entry.entry_id]
                if (
                    coordinator.data
                    and "ssids" in coordinator.data
                    and router_host in coordinator.data["ssids"]
                ):

                    router_ssids = coordinator.data["ssids"].get(router_host, [])

                    for ssid_data in router_ssids:
                        # Match by SSID interface name and radio (most reliable identifiers)
                        if ssid_data.get("ssid_interface") == original_ssid_info.get(
                            "ssid_interface"
                        ) and ssid_data.get("radio") == original_ssid_info.get("radio"):
                            return ssid_data
                    break

        return None

    def _get_current_global_ssid_data(self) -> Dict[str, Any]:
        """Dynamically aggregate SSID data from ALL WrtManager coordinators."""
        global_ssids = {
            "ssid_instances": [],
            "routers": [],
            "areas": set(),
        }

        # Get device and area registries
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr

        device_registry = dr.async_get(self.hass)
        area_registry = ar.async_get(self.hass)

        # Get all WrtManager coordinators
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id in self.hass.data.get(DOMAIN, {}):
                coordinator = self.hass.data[DOMAIN][entry.entry_id]
                if coordinator.data and "ssids" in coordinator.data:

                    # Get router configs for this entry
                    for router_config in entry.data.get("routers", []):
                        router_host = router_config["host"]
                        router_name = router_config["name"]

                        # Get SSID data for this router
                        router_ssids = coordinator.data["ssids"].get(router_host, [])

                        for ssid_info in router_ssids:
                            # Only include our target SSID
                            if ssid_info.get("ssid_name") == self._ssid_name:
                                global_ssids["ssid_instances"].append(
                                    {
                                        "router_host": router_host,
                                        "router_name": router_name,
                                        "ssid_info": ssid_info,
                                    }
                                )

                                if router_host not in global_ssids["routers"]:
                                    global_ssids["routers"].append(router_host)

                                # Check router area assignment
                                router_device = device_registry.async_get_device(
                                    identifiers={(DOMAIN, router_host)}
                                )
                                if router_device and router_device.area_id:
                                    area = area_registry.async_get_area(router_device.area_id)
                                    if area:
                                        global_ssids["areas"].add(area.name)

        return global_ssids


class WrtAreaSSIDBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Area-specific binary sensor for SSID enabled/disabled status."""

    def __init__(
        self,
        coordinator: WrtManagerCoordinator,
        ssid_name: str,
        area_name: str,
        area_instances: List[Dict[str, Any]],
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the area SSID status sensor."""
        super().__init__(coordinator)
        self._ssid_name = ssid_name
        self._area_name = area_name
        self._area_instances = area_instances
        self._config_entry = config_entry

        # Create unique entity ID for area SSID
        safe_ssid = ssid_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
        safe_area = area_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
        self._attr_unique_id = f"wrtmanager_{safe_area}_{safe_ssid}_enabled"
        self._attr_name = f"{area_name} {ssid_name} SSID"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:wifi"

    @property
    def is_on(self) -> bool:
        """Return True if SSID is enabled on any router in this area."""
        for instance in self._area_instances:
            ssid_data = self._get_current_ssid_data(instance["router_host"], instance["ssid_info"])
            if ssid_data and not ssid_data.get("disabled", False):
                return True
        return False

    @property
    def available(self) -> bool:
        """Return True if at least one router in this area has this SSID available."""
        return self.coordinator.last_update_success and any(
            self._get_current_ssid_data(instance["router_host"], instance["ssid_info"]) is not None
            for instance in self._area_instances
        )

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        enabled_routers = []
        disabled_routers = []
        total_instances = 0
        frequency_bands = set()

        for instance in self._area_instances:
            ssid_data = self._get_current_ssid_data(instance["router_host"], instance["ssid_info"])
            if ssid_data:
                total_instances += 1
                router_name = instance["router_name"]

                if ssid_data.get("disabled", False):
                    disabled_routers.append(router_name)
                else:
                    enabled_routers.append(router_name)

                # Collect frequency band info
                if ssid_data.get("is_consolidated"):
                    frequency_bands.update(ssid_data.get("frequency_bands", []))
                else:
                    radio = ssid_data.get("radio", "")
                    if "0" in radio:
                        frequency_bands.add("2.4GHz")
                    elif "1" in radio:
                        frequency_bands.add("5GHz")

        attributes = {
            "ssid_name": self._ssid_name,
            "area_name": self._area_name,
            "router_count": len(self._area_instances),
            "enabled_routers": enabled_routers,
            "disabled_routers": disabled_routers,
            "total_instances": total_instances,
            "frequency_bands": sorted(list(frequency_bands)),
            "coverage": f"Area: {self._area_name}",
        }

        # Get common configuration from first available instance
        for instance in self._area_instances:
            ssid_data = self._get_current_ssid_data(instance["router_host"], instance["ssid_info"])
            if ssid_data:
                attributes.update(
                    {
                        "ssid_mode": ssid_data.get("mode", "ap"),
                        "encryption": ssid_data.get("encryption"),
                        "hidden": ssid_data.get("hidden", False),
                        "network_name": ssid_data.get("network"),
                    }
                )
                break

        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for grouping."""
        # Check if first router device exists before using it as via_device
        via_device_id = None
        if self._area_instances:
            first_router_host = self._area_instances[0]["router_host"]
            device_registry = dr.async_get(self.hass)
            router_device = device_registry.async_get_device(
                identifiers={(DOMAIN, first_router_host)}
            )
            if router_device:
                via_device_id = (DOMAIN, first_router_host)

        return DeviceInfo(
            identifiers={(DOMAIN, f"area_{self._area_name}_{self._ssid_name}")},
            name=f"{self._area_name} {self._ssid_name}",
            manufacturer="WrtManager",
            model="Area SSID Controller",
            suggested_area=self._area_name,
            via_device=via_device_id,
        )

    def _get_current_ssid_data(
        self, router_host: str, original_ssid_info: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """Get current SSID data from the correct coordinator for specific router."""
        # Search across all WrtManager coordinators to find the one with this router's data
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id in self.hass.data.get(DOMAIN, {}):
                coordinator = self.hass.data[DOMAIN][entry.entry_id]
                if (
                    coordinator.data
                    and "ssids" in coordinator.data
                    and router_host in coordinator.data["ssids"]
                ):

                    router_ssids = coordinator.data["ssids"].get(router_host, [])

                    for ssid_data in router_ssids:
                        # Match by SSID interface name and radio (most reliable identifiers)
                        if ssid_data.get("ssid_interface") == original_ssid_info.get(
                            "ssid_interface"
                        ) and ssid_data.get("radio") == original_ssid_info.get("radio"):
                            return ssid_data
                    break

        return None


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

        # Include router host in unique ID to avoid conflicts when same
        # device connects to different routers
        router_id = self._router_host.replace(".", "_") if self._router_host else "unknown"
        self._attr_unique_id = f"{DOMAIN}_{router_id}_{mac.lower().replace(':', '_')}_presence"
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
        if signal is not None:
            signal_quality = classify_signal_quality(signal)
            attributes["signal_quality"] = signal_quality

        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for grouping in Home Assistant."""
        device_data = self._get_device_data()
        device_name = self._get_device_name(device_data)

        # Get router information for better device context
        router_host = device_data.get(ATTR_ROUTER) if device_data else self._router_host

        # Check if router device exists before using it as via_device
        via_device_id = None
        if router_host:
            device_registry = dr.async_get(self.hass)
            router_device = device_registry.async_get_device(identifiers={(DOMAIN, router_host)})
            if router_device:
                via_device_id = (DOMAIN, router_host)
            else:
                _LOGGER.debug(
                    "Router device %s not found in device registry, skipping via_device",
                    router_host,
                )

        return DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            connections={(CONNECTION_NETWORK_MAC, self._mac)},
            name=device_name,
            manufacturer=device_data.get(ATTR_VENDOR) if device_data else "Unknown",
            model=device_data.get(ATTR_DEVICE_TYPE) if device_data else "Network Device",
            sw_version=self._get_device_firmware(device_data),
            via_device=via_device_id,
            # Note: No configuration_url for connected devices - they don't have web interfaces
            # Only routers/infrastructure devices should have configuration_url
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

    def _get_router_name(self, router_host: str) -> str:
        """Get friendly router name from host IP."""
        if not router_host:
            return "Unknown Router"

        # Look up the router name from the config entry
        config_routers = self.coordinator.config_entry.data.get("routers", [])
        for router_config in config_routers:
            if router_config.get("host") == router_host:
                return router_config.get("name", router_host)

        # Fallback to IP address if not found in config
        return router_host

    def _get_device_firmware(self, device_data: Dict[str, Any] | None) -> str | None:
        """Get device firmware/software version if available."""
        if not device_data:
            return None

        # Try to get actual device firmware/OS information
        # This would come from device fingerprinting or DHCP information
        # For now, return None to let Home Assistant handle it

        # Future enhancement: Could detect device types and provide meaningful firmware:
        # - iOS devices: iOS version
        # - Android devices: Android version
        # - Windows devices: Windows version
        # - IoT devices: firmware version if available

        return None


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

        # Create unique entity ID using router name for clean entity_id generation
        safe_router_name = router_name.lower().replace(" ", "_").replace("-", "_")
        safe_interface = interface_name.replace(".", "_").replace("-", "_")
        self._attr_unique_id = f"wrtmanager_{safe_router_name}_{safe_interface}_status"

        # Provide better naming and icons based on interface type
        self._attr_name = f"{router_name} {self._get_friendly_interface_name(interface_name)}"
        self._attr_has_entity_name = False  # Use full name for entity_id
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = self._get_interface_icon(interface_name)

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

    def _get_friendly_interface_name(self, interface_name: str) -> str:
        """Get a human-friendly interface name with type description."""
        lower_name = interface_name.lower()

        # Wireless interfaces (phy#-ap# are the actual wireless interfaces)
        if "phy" in lower_name and "ap" in lower_name:
            return f"{interface_name} (WiFi Interface)"
        elif interface_name.startswith("wlan"):
            return f"{interface_name} (WiFi)"

        # Ethernet interfaces
        elif interface_name.startswith("eth"):
            return f"{interface_name} (Ethernet)"

        # Bridge interfaces
        elif interface_name.startswith("br-"):
            bridge_name = interface_name.replace("br-", "").title()
            return f"{interface_name} ({bridge_name} Bridge)"

        # VLAN interfaces
        elif "vlan" in lower_name or "." in interface_name:
            return f"{interface_name} (VLAN)"

        # Loopback
        elif interface_name == "lo":
            return f"{interface_name} (Loopback)"

        # Tunnel interfaces
        elif interface_name.startswith("tun") or interface_name.startswith("tap"):
            return f"{interface_name} (Tunnel)"

        # Default - just return the interface name
        else:
            return interface_name

    def _get_interface_icon(self, interface_name: str) -> str:
        """Get appropriate icon for interface type."""
        lower_name = interface_name.lower()

        # Wireless interfaces
        if "phy" in lower_name and "ap" in lower_name:
            return "mdi:wifi"
        elif interface_name.startswith("wlan"):
            return "mdi:wifi"

        # Ethernet interfaces
        elif interface_name.startswith("eth"):
            return "mdi:ethernet"

        # Bridge interfaces
        elif interface_name.startswith("br-"):
            return "mdi:bridge"

        # VLAN interfaces
        elif "vlan" in lower_name or "." in interface_name:
            return "mdi:network"

        # Loopback
        elif interface_name == "lo":
            return "mdi:looping"

        # Tunnel interfaces
        elif interface_name.startswith("tun") or interface_name.startswith("tap"):
            return "mdi:tunnel"

        # Default
        else:
            return "mdi:ethernet"
