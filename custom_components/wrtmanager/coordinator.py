"""Data update coordinator for WrtManager."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_CONNECTED,
    ATTR_DATA_SOURCE,
    ATTR_DEVICE_TYPE,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_IP,
    ATTR_LAST_SEEN,
    ATTR_MAC,
    ATTR_PRIMARY_AP,
    ATTR_ROAMING_COUNT,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
    ATTR_VENDOR,
    ATTR_VLAN_ID,
    CONF_ROUTERS,
    DATA_SOURCE_DYNAMIC_DHCP,
    DATA_SOURCE_STATIC_DHCP,
    DATA_SOURCE_WIFI_ONLY,
    DOMAIN,
    ROAMING_DETECTION_THRESHOLD,
    ROAMING_SIGNAL_HYSTERESIS,
)
from .device_manager import DeviceManager
from .ubus_client import UbusClient, UbusClientError

_LOGGER = logging.getLogger(__name__)


class WrtManagerCoordinator(DataUpdateCoordinator):
    """Coordinate data updates from multiple OpenWrt routers."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        update_interval: timedelta,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, logger, name=name, update_interval=update_interval)

        self.config_entry = config_entry
        self.routers: Dict[str, UbusClient] = {}
        self.sessions: Dict[str, str] = {}  # Router host -> session ID
        self.device_manager = DeviceManager()

        # Initialize router clients
        for router_config in config_entry.data[CONF_ROUTERS]:
            host = router_config[CONF_HOST]
            client = UbusClient(
                host=host,
                username=router_config[CONF_USERNAME],
                password=router_config[CONF_PASSWORD],
                timeout=10,
            )
            self.routers[host] = client

        # Device tracking for roaming detection
        self._device_history: Dict[str, Dict] = {}  # MAC -> device history

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from all routers."""
        _LOGGER.debug("Starting data update for %d routers", len(self.routers))

        # Authenticate with all routers in parallel
        auth_tasks = [
            self._authenticate_router(host, client) for host, client in self.routers.items()
        ]

        auth_results = await asyncio.gather(*auth_tasks, return_exceptions=True)

        # Process authentication results
        successful_auths = 0
        for i, (host, result) in enumerate(zip(self.routers.keys(), auth_results)):
            if isinstance(result, Exception):
                _LOGGER.error("Authentication failed for %s: %s", host, result)
                self.sessions.pop(host, None)
            else:
                self.sessions[host] = result
                successful_auths += 1

        if successful_auths == 0:
            raise UpdateFailed("Failed to authenticate with any router")

        # Collect data from all authenticated routers
        data_tasks = [
            self._collect_router_data(host, session_id)
            for host, session_id in self.sessions.items()
        ]

        router_data_results = await asyncio.gather(*data_tasks, return_exceptions=True)

        # Process collected data
        all_devices: List[Dict[str, Any]] = []
        dhcp_data: Dict[str, Any] = {}
        system_info: Dict[str, Any] = {}
        interfaces: Dict[str, Any] = {}

        for i, (host, result) in enumerate(zip(self.sessions.keys(), router_data_results)):
            if isinstance(result, Exception):
                _LOGGER.error("Data collection failed for %s: %s", host, result)
                continue

            wifi_devices, router_dhcp_data, router_system_data, router_interface_data = result
            all_devices.extend(wifi_devices)

            # Store system data for each router
            if router_system_data:
                system_info[host] = router_system_data

            # Store interface data for each router
            if router_interface_data:
                interfaces[host] = router_interface_data

            # Use DHCP data from the first router that provides it
            if not dhcp_data and router_dhcp_data:
                dhcp_data = router_dhcp_data

        # Correlate and enrich device data
        enriched_devices = self._correlate_device_data(all_devices, dhcp_data)

        # Update roaming detection
        self._update_roaming_detection(enriched_devices)

        _LOGGER.debug(
            "Successfully updated data: %d devices, %d routers",
            len(enriched_devices),
            len(system_info),
        )

        return {
            "devices": enriched_devices,
            "system_info": system_info,
            "interfaces": interfaces,
            "routers": list(self.sessions.keys()),
            "last_update": datetime.now(),
            "total_devices": len(enriched_devices),
        }

    async def _authenticate_router(self, host: str, client: UbusClient) -> str:
        """Authenticate with a single router."""
        try:
            session_id = await client.authenticate()
            if not session_id:
                raise UpdateFailed(f"Authentication failed for {host}")
            return session_id
        except UbusClientError as ex:
            raise UpdateFailed(f"Authentication error for {host}: {ex}")

    async def _collect_router_data(
        self, host: str, session_id: str
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Collect data from a single router."""
        client = self.routers[host]
        wifi_devices = []
        dhcp_data = {}
        system_data = {}
        interface_data = {}

        try:
            # Get wireless interfaces and device associations
            interfaces = await client.get_wireless_devices(session_id)
            if not interfaces:
                _LOGGER.warning("No wireless interfaces found on %s", host)

            # Get device associations for each interface
            if interfaces:
                for interface in interfaces:
                    associations = await client.get_device_associations(session_id, interface)
                    if associations:
                        for device_data in associations:
                            wifi_devices.append(
                                {
                                    ATTR_MAC: device_data.get("mac", "").upper(),
                                    ATTR_INTERFACE: interface,
                                    ATTR_SIGNAL_DBM: device_data.get("signal"),
                                    ATTR_ROUTER: host,
                                    ATTR_CONNECTED: True,
                                    ATTR_LAST_SEEN: datetime.now(),
                                }
                            )

            # Get system information for monitoring
            system_info = await client.get_system_info(session_id)
            system_board = await client.get_system_board(session_id)

            if system_info:
                system_data = {**system_info, **(system_board or {})}

            # Get network interface status
            network_interfaces = await client.get_network_interfaces(session_id)
            wireless_status = await client.get_wireless_status(session_id)

            if network_interfaces:
                interface_data.update(network_interfaces)
            if wireless_status:
                interface_data.update(wireless_status)

            # Try to get DHCP data (usually only from main router)
            dhcp_leases = await client.get_dhcp_leases(session_id)
            static_hosts = await client.get_static_dhcp_hosts(session_id)

            if dhcp_leases or static_hosts:
                dhcp_data = self._parse_dhcp_data(dhcp_leases, static_hosts)

        except Exception as ex:
            _LOGGER.error("Error collecting data from %s: %s", host, ex)
            raise UpdateFailed(f"Data collection failed for {host}: {ex}")

        return wifi_devices, dhcp_data, system_data, interface_data

    def _parse_dhcp_data(
        self, dhcp_leases: Optional[Dict], static_hosts: Optional[Dict]
    ) -> Dict[str, Any]:
        """Parse DHCP lease and static host data."""
        dhcp_devices = {}

        # Parse dynamic leases
        if dhcp_leases and "device" in dhcp_leases:
            for lease in dhcp_leases["device"].get("leases", []):
                mac = lease.get("macaddr", "").upper()
                if mac:
                    dhcp_devices[mac] = {
                        ATTR_IP: lease.get("ipaddr"),
                        ATTR_HOSTNAME: lease.get("hostname", ""),
                        ATTR_DATA_SOURCE: DATA_SOURCE_DYNAMIC_DHCP,
                    }

        # Parse static hosts
        if static_hosts and "values" in static_hosts:
            for section_data in static_hosts["values"].values():
                if section_data.get(".type") == "host":
                    mac = section_data.get("mac", "").upper()
                    if mac:
                        dhcp_devices[mac] = {
                            ATTR_IP: section_data.get("ip"),
                            ATTR_HOSTNAME: section_data.get("name", ""),
                            ATTR_DATA_SOURCE: DATA_SOURCE_STATIC_DHCP,
                        }

        return dhcp_devices

    def _correlate_device_data(
        self, wifi_devices: List[Dict[str, Any]], dhcp_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Correlate WiFi devices with DHCP data and enrich with additional info."""
        enriched_devices = []

        for device in wifi_devices:
            mac = device[ATTR_MAC]

            # Merge DHCP data if available
            if mac in dhcp_data:
                device.update(dhcp_data[mac])
            else:
                device[ATTR_DATA_SOURCE] = DATA_SOURCE_WIFI_ONLY

            # Add device identification
            device_info = self.device_manager.identify_device(mac)
            if device_info:
                device[ATTR_VENDOR] = device_info.get("vendor")
                device[ATTR_DEVICE_TYPE] = device_info.get("device_type")

            # Determine VLAN based on IP address or interface
            device[ATTR_VLAN_ID] = self._determine_vlan(device)

            enriched_devices.append(device)

        return enriched_devices

    def _determine_vlan(self, device: Dict[str, Any]) -> int:
        """Determine VLAN ID from device information."""
        interface = device.get(ATTR_INTERFACE, "")

        # Try to determine VLAN from WiFi interface name patterns
        if interface:
            # Common OpenWrt VLAN interface naming patterns
            interface_lower = interface.lower()

            # Check for explicit VLAN tags in interface names
            if "vlan" in interface_lower:
                # Extract VLAN ID from names like "wlan0-vlan3", "phy0-ap1-vlan13"
                import re

                vlan_match = re.search(r"vlan(\d+)", interface_lower)
                if vlan_match:
                    return int(vlan_match.group(1))

            # Check for common naming patterns (generic, not network-specific)
            if any(keyword in interface_lower for keyword in ["iot", "smart", "things"]):
                return 3  # Common IoT VLAN
            elif any(keyword in interface_lower for keyword in ["guest", "visitor", "public"]):
                return 100  # Common Guest VLAN
            elif any(keyword in interface_lower for keyword in ["main", "default", "lan"]):
                return 1  # Main VLAN

            # Check for multi-AP interface patterns (ap0=main, ap1=secondary, ap2=guest)
            elif "ap1" in interface_lower:
                return 10  # Secondary network
            elif "ap2" in interface_lower:
                return 100  # Guest network
            elif "ap0" in interface_lower:
                return 1  # Main network

        # For devices with IP addresses, try to infer from common subnet patterns
        ip = device.get(ATTR_IP)
        if ip:
            # Common patterns - these are generic enough for most networks
            ip_parts = ip.split(".")
            if len(ip_parts) >= 3:
                third_octet = ip_parts[2]
                # Many networks use the third octet to indicate VLAN
                try:
                    vlan_candidate = int(third_octet)
                    # Only return as VLAN if it's a reasonable VLAN ID (1-4094)
                    if 1 <= vlan_candidate <= 4094:
                        return vlan_candidate
                except ValueError:
                    pass

        return 1  # Default to main VLAN

    def _update_roaming_detection(self, devices: List[Dict[str, Any]]) -> None:
        """Update roaming detection for devices."""
        device_by_mac = {}

        # Group devices by MAC (same device seen on multiple routers)
        for device in devices:
            mac = device[ATTR_MAC]
            if mac not in device_by_mac:
                device_by_mac[mac] = []
            device_by_mac[mac].append(device)

        # Process roaming detection for each device
        for mac, device_list in device_by_mac.items():
            if len(device_list) == 1:
                # Device only seen on one router
                device = device_list[0]
                device[ATTR_PRIMARY_AP] = device[ATTR_ROUTER]
                device[ATTR_ROAMING_COUNT] = self._device_history.get(mac, {}).get(
                    ATTR_ROAMING_COUNT, 0
                )
            else:
                # Device seen on multiple routers - determine primary
                device_list.sort(key=lambda d: d.get(ATTR_SIGNAL_DBM, -999), reverse=True)
                primary_device = device_list[0]

                # Check if this is a roaming event
                previous_primary = self._device_history.get(mac, {}).get(ATTR_PRIMARY_AP)
                current_primary = primary_device[ATTR_ROUTER]

                roaming_count = self._device_history.get(mac, {}).get(ATTR_ROAMING_COUNT, 0)

                if (
                    previous_primary
                    and previous_primary != current_primary
                    and (
                        datetime.now()
                        - self._device_history.get(mac, {}).get("last_change", datetime.min)
                    ).seconds
                    >= ROAMING_DETECTION_THRESHOLD
                ):
                    roaming_count += 1

                # Update all instances of this device
                for device in device_list:
                    device[ATTR_PRIMARY_AP] = current_primary
                    device[ATTR_ROAMING_COUNT] = roaming_count

                # Update history
                self._device_history[mac] = {
                    ATTR_PRIMARY_AP: current_primary,
                    ATTR_ROAMING_COUNT: roaming_count,
                    "last_change": datetime.now(),
                }

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        # Close all ubus client sessions
        for client in self.routers.values():
            await client.close()

    def get_device_by_mac(self, mac: str) -> Optional[Dict[str, Any]]:
        """Get device data by MAC address."""
        if not self.data or "devices" not in self.data:
            return None

        for device in self.data["devices"]:
            if device.get(ATTR_MAC) == mac.upper():
                return device
        return None

    def get_devices_by_router(self, router: str) -> List[Dict[str, Any]]:
        """Get all devices connected to a specific router."""
        if not self.data or "devices" not in self.data:
            return []

        return [device for device in self.data["devices"] if device.get(ATTR_ROUTER) == router]
