"""Data update coordinator for WrtManager."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_CONNECTED,
    ATTR_CONNECTION_TYPE,
    ATTR_DATA_SOURCE,
    ATTR_DEVICE_TYPE,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_IP,
    ATTR_LAST_SEEN,
    ATTR_MAC,
    ATTR_NETWORK_NAME,
    ATTR_PRIMARY_AP,
    ATTR_ROAMING_COUNT,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
    ATTR_VENDOR,
    CONF_ROUTER_USE_HTTPS,
    CONF_ROUTER_VERIFY_SSL,
    CONF_ROUTERS,
    CONNECTION_TYPE_WIFI,
    CONNECTION_TYPE_WIRED,
    DATA_SOURCE_DYNAMIC_DHCP,
    DATA_SOURCE_LIVE_ARP,
    DATA_SOURCE_STATIC_DHCP,
    DATA_SOURCE_WIFI_ONLY,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    ROAMING_DETECTION_THRESHOLD,
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

        # DHCP router tracking for optimization
        self._dhcp_routers: Set[str] = set()  # Track which routers actually serve DHCP
        self._tried_dhcp: Set[str] = set()  # Track which routers we've already tested

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
            "About to collect data from %d routers: %s",
            len(self.sessions),
            list(self.sessions.keys()),
        )
        data_tasks = [
            self._collect_router_data(host, session_id)
            for host, session_id in self.sessions.items()
        ]

        router_data_results = await asyncio.gather(*data_tasks, return_exceptions=True)
        _LOGGER.debug("Data collection completed for %d routers", len(router_data_results))

        # Process collected data
        all_devices: List[Dict[str, Any]] = []
        dhcp_data: Dict[str, Any] = {}
        system_info: Dict[str, Any] = {}
        interfaces: Dict[str, Any] = {}
        interface_ips: Dict[str, Any] = {}
        host_hints: Optional[Dict[str, Any]] = None
        dhcp_router_ip_map: Dict[str, Any] = {}

        for i, (host, result) in enumerate(zip(self.sessions.keys(), router_data_results)):
            if isinstance(result, Exception):
                _LOGGER.error("Data collection failed for %s: %s", host, result)
                continue

            (
                wifi_devices,
                router_dhcp_data,
                router_system_data,
                router_interface_data,
                router_ip_map,
                router_host_hints,
            ) = result
            all_devices.extend(wifi_devices)

            # Store system data for each router
            if router_system_data:
                system_info[host] = router_system_data

            # Store interface data for each router
            if router_interface_data:
                interfaces[host] = router_interface_data

            interface_ips[host] = router_ip_map

            # Use DHCP data from the first router that provides it
            if not dhcp_data and router_dhcp_data:
                dhcp_data = router_dhcp_data
                if router_host_hints is not None:
                    host_hints = router_host_hints
                    dhcp_router_ip_map = router_ip_map

        # Fallback: If no DHCP data was collected, try other routers that haven't been tested yet
        if not dhcp_data:
            _LOGGER.info("No DHCP data collected from known DHCP servers, trying fallback routers")
            untested_routers = [
                host
                for host in self.sessions.keys()
                if host not in self._dhcp_routers and host not in self._tried_dhcp
            ]

            for fallback_host in untested_routers:
                try:
                    session_id = self.sessions[fallback_host]
                    client = self.routers[fallback_host]

                    _LOGGER.debug("Fallback: trying DHCP on router %s", fallback_host)
                    dhcp_leases = await client.get_dhcp_leases(session_id)
                    static_hosts = await client.get_static_dhcp_hosts(session_id)

                    has_leases = bool(
                        (
                            dhcp_leases
                            and (dhcp_leases.get("dhcp_leases") or dhcp_leases.get("device"))
                        )
                        or static_hosts
                    )
                    if has_leases:
                        # Found DHCP data on fallback router
                        self._dhcp_routers.add(fallback_host)
                        dhcp_data = self._parse_dhcp_data(dhcp_leases, static_hosts)
                        _LOGGER.info("Fallback: found DHCP data on router %s", fallback_host)
                        break
                    else:
                        self._tried_dhcp.add(fallback_host)
                except Exception as ex:
                    _LOGGER.warning("Fallback DHCP query failed for %s: %s", fallback_host, ex)
                    self._tried_dhcp.add(fallback_host)

        # Build interface-to-network mapping from wireless status data
        interface_network_map = self._build_interface_network_map(interfaces)

        # Correlate and enrich device data
        enriched_devices = self._correlate_device_data(
            all_devices, dhcp_data, interface_network_map
        )

        # Merge wired clients from host hints, excluding MACs already in WiFi assoclist
        wifi_mac_set: Set[str] = {d[ATTR_MAC] for d in enriched_devices}
        wired_devices: List[Dict[str, Any]] = []
        if host_hints is not None:
            wired_devices = self._build_wired_devices(
                host_hints, wifi_mac_set, dhcp_data, dhcp_router_ip_map
            )
        enriched_devices = enriched_devices + wired_devices

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
            "interface_ips": interface_ips,
            "dhcp_routers": list(self._dhcp_routers),
        }

    async def _authenticate_router(self, host: str, client: UbusClient) -> str:
        """Authenticate with a single router with retry logic."""
        max_retries = 3
        base_delay = 1.0  # Base delay in seconds

        for attempt in range(max_retries):
            try:
                session_id = await client.authenticate()
                if not session_id:
                    raise UpdateFailed(f"Authentication failed for {host}")

                if attempt > 0:
                    _LOGGER.info("Authentication succeeded for %s on attempt %d", host, attempt + 1)

                return session_id

            except UpdateFailed:
                # Re-raise UpdateFailed exceptions immediately (no retry for invalid session)
                raise
            except UbusClientError as ex:
                if attempt == max_retries - 1:
                    # Last attempt failed, raise the error
                    raise UpdateFailed(
                        f"Authentication error for {host} after {max_retries} attempts: {ex}"
                    )

                # Calculate exponential backoff delay
                delay = base_delay * (2**attempt)
                _LOGGER.warning(
                    "Authentication failed for %s (attempt %d/%d): %s. Retrying in %.1f seconds",
                    host,
                    attempt + 1,
                    max_retries,
                    ex,
                    delay,
                )

                await asyncio.sleep(delay)

    async def _collect_router_data(self, host: str, session_id: str) -> tuple[
        List[Dict[str, Any]],
        Dict[str, Any],
        Dict[str, Any],
        Dict[str, Any],
        Dict[str, Any],
        Optional[Dict[str, Any]],
    ]:
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

            # Build iwinfo SSID map for this router (real SSID, not ACL-masked config value)
            iwinfo_ssid_map: Dict[str, str] = {}
            if interfaces:
                for interface in interfaces:
                    iwinfo_info = await client.get_iwinfo_info(session_id, interface)
                    if iwinfo_info and iwinfo_info.get("ssid"):
                        iwinfo_ssid_map[interface] = iwinfo_info["ssid"]

            # Get system information for monitoring
            system_info = await client.get_system_info(session_id)
            system_board = await client.get_system_board(session_id)

            if system_info:
                system_data = {**system_info, **(system_board or {})}

            # Get network interface status
            network_interfaces = await client.get_network_interfaces(session_id)
            wireless_status = await client.get_wireless_status(session_id)
            interface_dump = await client.get_interface_dump(session_id)

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
            if iwinfo_ssid_map:
                interface_data["_iwinfo_ssids"] = iwinfo_ssid_map

            # Smart DHCP polling - only query DHCP from known DHCP servers or untested routers
            should_try_dhcp = host in self._dhcp_routers or host not in self._tried_dhcp

            if should_try_dhcp:
                _LOGGER.debug("Router %s - attempting to get DHCP leases...", host)
                dhcp_leases = await client.get_dhcp_leases(session_id)
                _LOGGER.debug("Router %s - DHCP leases result: %s", host, dhcp_leases)

                _LOGGER.debug("Router %s - attempting to get static DHCP hosts...", host)
                static_hosts = await client.get_static_dhcp_hosts(session_id)
                _LOGGER.debug("Router %s - static hosts result: %s", host, static_hosts)

                has_leases = bool(
                    (dhcp_leases and (dhcp_leases.get("dhcp_leases") or dhcp_leases.get("device")))
                    or static_hosts
                )
                if has_leases:
                    # Mark this router as a DHCP server
                    self._dhcp_routers.add(host)
                    _LOGGER.debug("Router %s - parsing DHCP data", host)
                    dhcp_data = self._parse_dhcp_data(dhcp_leases, static_hosts)
                    _LOGGER.debug("Router %s - parsed DHCP data: %s", host, dhcp_data)
                else:
                    # If this was previously a known DHCP server but now returns no data,
                    # remove it from DHCP servers and mark as non-DHCP
                    if host in self._dhcp_routers:
                        _LOGGER.info(
                            "Router %s - previously served DHCP but no longer provides data, "
                            "removing from DHCP server list",
                            host,
                        )
                        self._dhcp_routers.discard(host)

                    # Mark as tested (no DHCP service detected)
                    self._tried_dhcp.add(host)
                    _LOGGER.debug("Router %s - no DHCP service detected", host)
            else:
                _LOGGER.debug("Router %s - skipping DHCP query (not a DHCP server)", host)

            # Host hints — all ARP+DHCP hosts from main/DHCP router via luci-rpc
            host_hints: Optional[Dict[str, Any]] = None
            if host in self._dhcp_routers:
                host_hints = await client.get_host_hints(session_id)
                _LOGGER.debug(
                    "Router %s - host hints: %d entries",
                    host,
                    len(host_hints) if host_hints else 0,
                )

        except Exception as ex:
            _LOGGER.error("Error collecting data from %s: %s", host, ex)
            raise UpdateFailed(f"Data collection failed for {host}: {ex}")

        # Build IP + logical name map from interface dump
        ip_map: Dict[str, Any] = {}
        if interface_dump and "interface" in interface_dump:
            for iface in interface_dump["interface"]:
                l3dev = iface.get("l3_device")
                logical = iface.get("interface")
                addrs = iface.get("ipv4-address", [])
                if l3dev and logical:
                    ip_str = None
                    if addrs:
                        a = addrs[0]
                        ip_str = f"{a['address']}/{a['mask']}"
                    ip_map[l3dev] = {"ip": ip_str, "logical": logical}

        return wifi_devices, dhcp_data, system_data, interface_data, ip_map, host_hints

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
        self,
        wifi_devices: List[Dict[str, Any]],
        dhcp_data: Dict[str, Any],
        interface_network_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Correlate WiFi devices with DHCP data and enrich with additional info."""
        enriched_devices = []

        for device in wifi_devices:
            mac = device[ATTR_MAC]

            # Tag as WiFi device
            device[ATTR_CONNECTION_TYPE] = CONNECTION_TYPE_WIFI

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

            # Look up OpenWrt network name from wireless status data
            if interface_network_map:
                router = device.get(ATTR_ROUTER, "")
                interface = device.get(ATTR_INTERFACE, "")
                map_key = f"{router}:{interface}"
                device[ATTR_NETWORK_NAME] = interface_network_map.get(map_key)

            enriched_devices.append(device)

        return enriched_devices

    @staticmethod
    def _build_interface_network_map(
        interfaces: Dict[str, Any],
    ) -> Dict[str, str]:
        """Build a mapping from (router:interface) to OpenWrt network name.

        Extracts network assignments from wireless status data which contains
        the actual OpenWrt network configuration for each wireless interface.

        Returns:
            Dict mapping "router_host:interface_name" to network name string.
        """
        network_map: Dict[str, str] = {}

        for router_host, router_interfaces in interfaces.items():
            for interface_name, interface_data in router_interfaces.items():
                # Only process wireless radio data (has 'interfaces' key)
                if not isinstance(interface_data, dict) or "interfaces" not in interface_data:
                    continue

                radio_interfaces = interface_data.get("interfaces", [])
                if not isinstance(radio_interfaces, list):
                    continue

                for iface in radio_interfaces:
                    ifname = iface.get("ifname")
                    config = iface.get("config", {})
                    network = config.get("network")

                    if ifname and network:
                        # network can be a list (e.g. ['lan']) or string
                        if isinstance(network, list):
                            net_name = network[0] if network else None
                        else:
                            net_name = network

                        if net_name:
                            map_key = f"{router_host}:{ifname}"
                            network_map[map_key] = net_name

        _LOGGER.debug("Interface-to-network map: %s", network_map)
        return network_map

    @staticmethod
    def _build_subnet_map(ip_map: Dict[str, Any]) -> List[tuple]:
        """Build list of (network, logical_name) from interface dump ip_map.

        ip_map format: {physical_device: {"ip": "192.168.1.1/24", "logical": "lan"}}
        Returns sorted list (longest prefix first) for longest-match lookup.
        """
        import ipaddress

        subnets = []
        for _phys, info in ip_map.items():
            ip_str = info.get("ip")
            logical = info.get("logical")
            if not ip_str or not logical:
                continue
            try:
                network = ipaddress.ip_interface(ip_str).network
                subnets.append((network, logical))
            except ValueError:
                continue
        subnets.sort(key=lambda x: x[0].prefixlen, reverse=True)
        return subnets

    @staticmethod
    def _ip_to_network(ip: str, subnets: List[tuple]) -> Optional[str]:
        """Find logical network name for an IP using longest-prefix match."""
        import ipaddress

        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for network, logical in subnets:
            if addr in network:
                return logical
        return None

    def _build_wired_devices(
        self,
        host_hints: Dict[str, Any],
        wifi_mac_set: Set[str],
        dhcp_data: Dict[str, Any],
        ip_map: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Build wired device records from host hints not in the WiFi assoclist.

        Hostname priority:
        1. Static DHCP reservation name  (DATA_SOURCE_STATIC_DHCP)
        2. Dynamic DHCP lease hostname   (DATA_SOURCE_DYNAMIC_DHCP)
        3. dnsmasq name from host hints  (DATA_SOURCE_LIVE_ARP, may be empty)
        """
        subnet_map = self._build_subnet_map(ip_map)
        wired = []

        for mac_raw, hints in host_hints.items():
            mac = mac_raw.upper()
            if mac in wifi_mac_set:
                continue  # Already tracked as WiFi

            ipaddrs = hints.get("ipaddrs", [])
            ip = ipaddrs[0] if ipaddrs else None
            if not ip:
                continue  # No IP = cannot place on a network

            network_name = self._ip_to_network(ip, subnet_map)

            device: Dict[str, Any] = {
                ATTR_MAC: mac,
                ATTR_IP: ip,
                ATTR_CONNECTED: True,
                ATTR_CONNECTION_TYPE: CONNECTION_TYPE_WIRED,
                ATTR_NETWORK_NAME: network_name,
                ATTR_LAST_SEEN: datetime.now(),
            }

            # Hostname priority: DHCP data (static reservation or dynamic lease) > hints name
            if mac in dhcp_data:
                dhcp_entry = dhcp_data[mac]
                device[ATTR_HOSTNAME] = dhcp_entry.get(ATTR_HOSTNAME, "")
                device[ATTR_DATA_SOURCE] = dhcp_entry.get(ATTR_DATA_SOURCE, DATA_SOURCE_LIVE_ARP)
            else:
                # Static-IP device: use dnsmasq name if known (ARP snooping / /etc/hosts)
                device[ATTR_HOSTNAME] = hints.get("name", "")
                device[ATTR_DATA_SOURCE] = DATA_SOURCE_LIVE_ARP

            device_info = self.device_manager.identify_device(mac)
            if device_info:
                device[ATTR_VENDOR] = device_info.get("vendor")
                device[ATTR_DEVICE_TYPE] = device_info.get("device_type")

            wired.append(device)
            _LOGGER.debug("Wired client from host hints: %s (%s) on %s", mac, ip, network_name)

        return wired

    def _update_roaming_detection(self, devices: List[Dict[str, Any]]) -> None:
        """Update roaming detection for devices."""
        device_by_mac = {}

        # Group devices by MAC (same device seen on multiple routers)
        # Skip wired devices — they have no router/AP association
        for device in devices:
            if not device.get(ATTR_ROUTER):
                continue
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
                    ).total_seconds()
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

    async def disconnect_client(self, router_host: str, interface: str, mac_address: str) -> bool:
        """Disconnect a WiFi client from a specific router/interface.

        Args:
            router_host: The router host to disconnect from.
            interface: Wireless interface name (e.g. "phy0-ap0").
            mac_address: MAC address of the client.

        Returns:
            True if successful, False otherwise.

        Raises:
            ValueError: If the router is not configured or not authenticated.
        """
        client = self.routers.get(router_host)
        if not client:
            raise ValueError(f"Router {router_host} is not configured")

        session_id = self.sessions.get(router_host)
        if not session_id:
            raise ValueError(f"Router {router_host} is not authenticated")

        _LOGGER.info(
            "Disconnecting client %s from %s (interface: %s)",
            mac_address,
            router_host,
            interface,
        )

        success = await client.disconnect_client(session_id, interface, mac_address)

        if success:
            _LOGGER.info("Successfully disconnected %s from %s", mac_address, router_host)
            # Trigger a data refresh to update entity states
            await self.async_request_refresh()
        else:
            _LOGGER.warning("Failed to disconnect %s from %s", mac_address, router_host)

        return success

    def get_devices_by_router(self, router: str) -> List[Dict[str, Any]]:
        """Get all devices connected to a specific router."""
        if not self.data or "devices" not in self.data:
            return []

        return [device for device in self.data["devices"] if device.get(ATTR_ROUTER) == router]

    @staticmethod
    def _sanitize_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize sensitive fields from config data before logging.

        Redacts WiFi passwords and other sensitive fields to prevent
        exposure in debug logs. Preserves None values to distinguish
        between no password (open network) and redacted passwords.
        """
        sensitive_fields = ["key", "wpa_passphrase", "wpa_psk", "password"]
        return {
            k: "***REDACTED***" if k in sensitive_fields and v is not None else v
            for k, v in config.items()
        }

    def _extract_ssid_data(self, interfaces: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Extract SSID information from wireless status data."""
        ssid_data = {}

        _LOGGER.debug("_extract_ssid_data called with interfaces: %s", interfaces.keys())

        for router_host, router_interfaces in interfaces.items():
            router_ssids = []
            iwinfo_ssids = router_interfaces.pop("_iwinfo_ssids", {})

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
                            (iface_data.get("ifname", f"interface_{i}"), iface_data)
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
                        # Prefer iwinfo SSID over config SSID (config may be ACL-masked)
                        iface_name = ssid_interface_data.get("ifname", ssid_interface_name)
                        iwinfo_ssid = iwinfo_ssids.get(iface_name)
                        if iwinfo_ssid:
                            ssid_name = iwinfo_ssid

                        _LOGGER.debug(
                            "Processing SSID interface %s: ssid_name=%s, config_keys=%s",
                            ssid_interface_name,
                            ssid_name,
                            list(config.keys()),
                        )

                        # Extract SSID information
                        sanitized_config = self._sanitize_config(config)
                        ssid_info = {
                            "radio": radio_name,
                            "ssid_interface": ssid_interface_name,
                            "ssid_name": ssid_name,
                            "mode": config.get("mode", "ap"),  # default to access point
                            "disabled": config.get("disabled", False),
                            "network_interface": ssid_interface_data.get("ifname"),
                            "router_host": router_host,
                            "encryption": config.get("encryption"),
                            "key": sanitized_config.get("key"),
                            "hidden": config.get("hidden", False),
                            "isolate": config.get("isolate", False),  # client isolation
                            "network": config.get("network"),  # OpenWrt network name
                            "full_config": sanitized_config,
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
                            "hidden": any(s.get("hidden", False) for s in ssid_instances),
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
