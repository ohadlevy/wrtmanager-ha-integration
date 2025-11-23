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
    CONF_ROUTER_USE_HTTPS,
    CONF_ROUTER_VERIFY_SSL,
    CONF_ROUTERS,
    DATA_SOURCE_DYNAMIC_DHCP,
    DATA_SOURCE_STATIC_DHCP,
    DATA_SOURCE_WIFI_ONLY,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
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
                use_https=router_config.get(CONF_ROUTER_USE_HTTPS, DEFAULT_USE_HTTPS),
                verify_ssl=router_config.get(CONF_ROUTER_VERIFY_SSL, DEFAULT_VERIFY_SSL),
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
        _LOGGER.debug(
            "🔍 DEBUG: About to collect data from %d routers: %s",
            len(self.sessions),
            list(self.sessions.keys()),
        )
        data_tasks = [
            self._collect_router_data(host, session_id)
            for host, session_id in self.sessions.items()
        ]

        router_data_results = await asyncio.gather(*data_tasks, return_exceptions=True)
        _LOGGER.debug(
            "🔍 DEBUG: Data collection completed for %d routers", len(router_data_results)
        )

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

        # Extract SSID information from wireless status data
        ssid_data = self._extract_ssid_data(interfaces)
        _LOGGER.debug("Extracted SSID data: %s", ssid_data)

        return {
            "devices": enriched_devices,
            "system_info": system_info,
            "interfaces": interfaces,
            "ssids": ssid_data,
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
        _LOGGER.debug("🔍 DEBUG: _collect_router_data() called for host %s", host)
        client = self.routers[host]
        wifi_devices = []
        dhcp_data = {}
        system_data = {}
        interface_data = {}

        try:
            _LOGGER.debug("🔍 DEBUG: Starting data collection for %s", host)
            # Get wireless interfaces and device associations
            _LOGGER.debug("🔍 DEBUG: Getting wireless devices for %s", host)
            interfaces = await client.get_wireless_devices(session_id)
            if not interfaces:
                _LOGGER.warning("No wireless interfaces found on %s", host)

            # Get device associations for each interface
            if interfaces:
                _LOGGER.debug("🔍 DEBUG: Found %d interfaces on %s", len(interfaces), host)
                for interface in interfaces:
                    associations = await client.get_device_associations(session_id, interface)
                    if associations:
                        _LOGGER.debug(
                            "🔍 DEBUG: Found %d associations on interface %s",
                            len(associations),
                            interface,
                        )
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
            _LOGGER.debug("🔍 DEBUG: Getting system info for %s", host)
            system_info = await client.get_system_info(session_id)
            system_board = await client.get_system_board(session_id)

            if system_info:
                system_data = {**system_info, **(system_board or {})}
                _LOGGER.debug("🔍 DEBUG: Got system data for %s", host)

            # Get network interface status
            _LOGGER.debug("🔍 DEBUG: Getting network interfaces for %s", host)
            network_interfaces = await client.get_network_interfaces(session_id)
            wireless_status = await client.get_wireless_status(session_id)

            _LOGGER.debug(
                "Router %s - network_interfaces result: %s",
                host,
                list(network_interfaces.keys()) if network_interfaces else None,
            )
            _LOGGER.debug(
                "Router %s - wireless_status result: %s",
                host,
                list(wireless_status.keys()) if wireless_status else None,
            )

            # Log detailed information about wireless status availability for SSID features
            if wireless_status is None:
                _LOGGER.warning(
                    "Router %s - network.wireless.status call failed. "
                    "Check previous logs for specific error codes.",
                    host,
                )
                _LOGGER.info(
                    "Router %s - SSID monitoring unavailable due to wireless status failure", host
                )
            else:
                _LOGGER.debug("Router %s - Wireless status available for SSID monitoring", host)

            if network_interfaces:
                interface_data.update(network_interfaces)
            if wireless_status:
                interface_data.update(wireless_status)

            # Try to get DHCP data (usually only from main router)
            _LOGGER.debug("🔍🔍🔍 CRITICAL DEBUG: About to start DHCP calls for %s", host)
            _LOGGER.debug("Router %s - attempting to get DHCP leases...", host)
            dhcp_leases = await client.get_dhcp_leases(session_id)
            _LOGGER.debug("Router %s - DHCP leases result: %s", host, dhcp_leases)

            _LOGGER.debug("Router %s - attempting to get static DHCP hosts...", host)
            static_hosts = await client.get_static_dhcp_hosts(session_id)
            _LOGGER.debug("Router %s - static hosts result: %s", host, static_hosts)

            if dhcp_leases or static_hosts:
                _LOGGER.debug("Router %s - parsing DHCP data", host)
                dhcp_data = self._parse_dhcp_data(dhcp_leases, static_hosts)
                _LOGGER.debug("Router %s - parsed DHCP data: %s", host, dhcp_data)
            else:
                _LOGGER.warning("Router %s - no DHCP data returned from ubus calls", host)

        except Exception as ex:
            _LOGGER.error("🔍 DEBUG: Exception in _collect_router_data for %s: %s", host, ex)
            _LOGGER.error("Error collecting data from %s: %s", host, ex)
            raise UpdateFailed(f"Data collection failed for {host}: {ex}")

        _LOGGER.debug(
            "🔍 DEBUG: Finished _collect_router_data for %s, %d wifi devices, %d dhcp entries",
            host,
            len(wifi_devices),
            len(dhcp_data),
        )
        return wifi_devices, dhcp_data, system_data, interface_data

    def _parse_dhcp_data(
        self, dhcp_leases: Optional[Dict], static_hosts: Optional[Dict]
    ) -> Dict[str, Any]:
        """Parse DHCP lease and static host data."""
        dhcp_devices = {}

        # Parse dynamic leases - handle both luci-rpc and standard dhcp formats
        if dhcp_leases:
            if "dhcp_leases" in dhcp_leases:
                # luci-rpc.getDHCPLeases format
                for lease in dhcp_leases["dhcp_leases"]:
                    mac = lease.get("macaddr", "").upper()
                    if mac:
                        dhcp_devices[mac] = {
                            ATTR_IP: lease.get("ipaddr"),
                            ATTR_HOSTNAME: lease.get("hostname", ""),
                            ATTR_DATA_SOURCE: DATA_SOURCE_DYNAMIC_DHCP,
                        }
            elif "device" in dhcp_leases:
                # Standard dhcp.ipv4leases format
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

    def _extract_ssid_data(self, interfaces: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Extract SSID information from wireless status data."""
        ssid_data = {}

        _LOGGER.debug("_extract_ssid_data called with interfaces: %s", interfaces.keys())

        for router_host, router_interfaces in interfaces.items():
            router_ssids = []

            _LOGGER.debug(
                "Processing router %s with interfaces: %s",
                router_host,
                list(router_interfaces.keys()),
            )

            # Check if this router has any wireless status data available
            has_wireless_data = any(
                isinstance(interface_data, dict) and "interfaces" in interface_data
                for interface_data in router_interfaces.values()
            )

            if not has_wireless_data:
                _LOGGER.info(
                    "Router %s - No wireless SSID data available (likely dump AP mode)", router_host
                )
                continue

            # Look for wireless status data (has radio structure)
            for interface_name, interface_data in router_interfaces.items():
                _LOGGER.debug(
                    "Checking interface %s: type=%s, has_interfaces=%s",
                    interface_name,
                    type(interface_data),
                    "interfaces" in interface_data if isinstance(interface_data, dict) else False,
                )

                # Skip network interfaces, focus on wireless status structure
                if isinstance(interface_data, dict) and "interfaces" in interface_data:
                    # This is a radio (e.g., radio0, radio1)
                    radio_name = interface_name
                    radio_interfaces = interface_data.get("interfaces", {})

                    _LOGGER.debug(
                        "Found radio %s with interfaces: %s (type: %s)",
                        radio_name,
                        (
                            list(radio_interfaces.keys())
                            if isinstance(radio_interfaces, dict)
                            else radio_interfaces
                        ),
                        type(radio_interfaces),
                    )

                    # Handle both dict and list formats for radio interfaces
                    if isinstance(radio_interfaces, list):
                        # OpenWrt returns interfaces as a list
                        _LOGGER.debug(
                            "Processing radio %s with %d interfaces (list format)",
                            radio_name,
                            len(radio_interfaces),
                        )
                        interface_items = [
                            (f"interface_{i}", iface_data)
                            for i, iface_data in enumerate(radio_interfaces)
                        ]
                    elif isinstance(radio_interfaces, dict):
                        # Some versions might return as dict
                        _LOGGER.debug(
                            "Processing radio %s with %d interfaces (dict format)",
                            radio_name,
                            len(radio_interfaces),
                        )
                        interface_items = radio_interfaces.items()
                    else:
                        _LOGGER.debug(
                            "Skipping radio %s - interfaces is neither dict nor list: %s",
                            radio_name,
                            type(radio_interfaces),
                        )
                        continue

                    for ssid_interface_name, ssid_interface_data in interface_items:
                        config = ssid_interface_data.get("config", {})
                        ssid_name = config.get("ssid")

                        _LOGGER.debug(
                            "Processing SSID interface %s: ssid_name=%s, config_keys=%s",
                            ssid_interface_name,
                            ssid_name,
                            list(config.keys()),
                        )

                        # Extract SSID information
                        ssid_info = {
                            "radio": radio_name,
                            "ssid_interface": ssid_interface_name,
                            "ssid_name": ssid_name,
                            "mode": config.get("mode", "ap"),  # default to access point
                            "disabled": config.get("disabled", False),
                            "network_interface": ssid_interface_data.get("ifname"),
                            "router_host": router_host,
                            "encryption": config.get("encryption"),
                            "key": config.get("key"),  # WiFi password (if any)
                            "hidden": config.get("hidden", False),
                            "isolate": config.get("isolate", False),  # client isolation
                            "network": config.get("network"),  # OpenWrt network name
                            "full_config": config,
                        }

                        # Only include valid SSIDs (must have a name)
                        if ssid_info["ssid_name"]:
                            router_ssids.append(ssid_info)
                            _LOGGER.debug("Added SSID %s for router %s", ssid_name, router_host)
                        else:
                            _LOGGER.debug(
                                "Skipping SSID interface %s - no SSID name", ssid_interface_name
                            )

            if router_ssids:
                ssid_data[router_host] = router_ssids
                _LOGGER.debug("Router %s has %d SSIDs", router_host, len(router_ssids))
            else:
                _LOGGER.debug("Router %s has no SSIDs found", router_host)

        # Consolidate SSIDs by name (group same SSID across multiple radios)
        consolidated_ssid_data = self._consolidate_ssids_by_name(ssid_data)
        _LOGGER.debug("Final SSID data: %s", consolidated_ssid_data)
        return consolidated_ssid_data

    def _consolidate_ssids_by_name(
        self, ssid_data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Consolidate SSIDs with the same name across multiple radios."""
        consolidated = {}

        for router_host, router_ssids in ssid_data.items():
            # Group SSIDs by name
            ssid_groups = {}
            for ssid_info in router_ssids:
                ssid_name = ssid_info["ssid_name"]
                if ssid_name not in ssid_groups:
                    ssid_groups[ssid_name] = []
                ssid_groups[ssid_name].append(ssid_info)

            consolidated_router_ssids = []

            for ssid_name, ssid_instances in ssid_groups.items():
                if len(ssid_instances) == 1:
                    # Single radio SSID - keep as is
                    consolidated_router_ssids.append(ssid_instances[0])
                else:
                    # Multiple radios with same SSID name - consolidate
                    primary_ssid = ssid_instances[0].copy()

                    # Combine radio information
                    radios = [ssid["radio"] for ssid in ssid_instances]
                    interfaces = [ssid["ssid_interface"] for ssid in ssid_instances]
                    network_interfaces = [ssid.get("network_interface") for ssid in ssid_instances]

                    # Create consolidated SSID entry
                    primary_ssid.update(
                        {
                            "radios": radios,  # List of all radios
                            "ssid_interfaces": interfaces,  # List of all interfaces
                            "network_interfaces": network_interfaces,  # List of all networks
                            "radio": f"multi_radio_{ssid_name.lower().replace(' ', '_')}",
                            "is_consolidated": True,
                            "radio_count": len(radios),
                            "frequency_bands": self._get_frequency_bands(radios),
                        }
                    )

                    consolidated_router_ssids.append(primary_ssid)

                    _LOGGER.debug(
                        "Consolidated SSID '%s' across %d radios: %s",
                        ssid_name,
                        len(radios),
                        radios,
                    )

            consolidated[router_host] = consolidated_router_ssids

        return consolidated

    def _get_frequency_bands(self, radios: List[str]) -> List[str]:
        """Get frequency bands from radio names."""
        bands = []
        for radio in radios:
            if "0" in radio:
                bands.append("2.4GHz")
            elif "1" in radio:
                bands.append("5GHz")
            else:
                bands.append("Unknown")
        return bands
