"""Data update coordinator for WrtManager."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Pattern, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
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
    CONF_VLAN_DETECTION_RULES,
    DATA_SOURCE_DYNAMIC_DHCP,
    DATA_SOURCE_STATIC_DHCP,
    DATA_SOURCE_WIFI_ONLY,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    DEFAULT_VLAN_DETECTION_RULES,
    ROAMING_DETECTION_THRESHOLD,
)
from .device_manager import DeviceManager
from .ubus_client import UbusClient, UbusClientError

_LOGGER = logging.getLogger(__name__)


def _validate_regex_pattern(pattern: str) -> bool:
    """Validate regex pattern for safety against ReDoS attacks.

    Args:
        pattern: The regex pattern to validate

    Returns:
        True if the pattern is safe to use, False otherwise
    """
    if len(pattern) > 100:  # Reasonable length limit
        return False

    # Block known dangerous patterns that can cause ReDoS
    # Check for actual dangerous patterns (not escaped strings)
    dangerous_patterns = [
        r"\+\)+",  # (a+)+ type patterns
        r"\*\)+",  # (a*)+ type patterns
        r"\+\*",  # a+* type patterns
        r"\*\*",  # a** type patterns (though invalid syntax)
        r"\(\*",  # (*... patterns
        r"\(\+",  # (+... patterns
        r"\)\+\*",  # )+* patterns
        r"\)\*\+",  # )*+ patterns
        r"\+\+",  # ++ patterns
    ]

    # Check for actual ReDoS-vulnerable patterns using better detection
    import re as re_module

    try:
        # First check if it compiles
        compiled = re_module.compile(pattern)

        # Check for dangerous pattern combinations
        for danger in dangerous_patterns:
            if re_module.search(danger, pattern):
                return False

        # Check for nested quantifiers which are the main ReDoS cause
        # Look for patterns like (a+)+ or (a*)* or (a+)*
        nested_quantifier_pattern = r"\([^)]*[*+][^)]*\)[*+]"
        if re_module.search(nested_quantifier_pattern, pattern):
            return False

        # Check for alternation with overlapping patterns
        # This is a simplified check for patterns like (a+|a)*
        alternation_overlap_pattern = r"\([^|]*\+[^|]*\|[^)]*\*[^)]*\)[*+]"
        if re_module.search(alternation_overlap_pattern, pattern):
            return False

        # Check for dangerous quantifier patterns with high repetition counts
        # Patterns like (.*a){10,} or (.+){5,} can be very slow
        high_rep_pattern = r"\([^)]*[.*+][^)]*\)\{[0-9]+,"
        if re_module.search(high_rep_pattern, pattern):
            return False

        # Check for character classes with unlimited quantifiers inside groups
        # Patterns like ([a-zA-Z]+)* can be dangerous
        char_class_quantifier_pattern = r"\(\[[^\]]*\]\+[^)]*\)[*+]"
        if re_module.search(char_class_quantifier_pattern, pattern):
            return False

        # Check for (.+)* or (.*)+ patterns which are extremely dangerous
        any_char_quantifier_pattern = r"\(\.[*+]\)[*+]"
        if re_module.search(any_char_quantifier_pattern, pattern):
            return False

        # Test with progressively complex strings that could trigger ReDoS
        # Use simple synchronous testing instead of threading for validation
        try:
            test_strings = [
                "test_string",
                "a" * 50 + "b",
                "aaa" * 20 + "bbb" * 20 + "x",  # More complex test
            ]

            for test_str in test_strings:
                compiled.search(test_str)

        except Exception:
            return False

        return True

    except (re_module.error, Exception):
        return False


def _determine_vlan_with_rules(device: Dict[str, Any], vlan_rules: Dict[str, Any]) -> int:
    """Determine VLAN ID from device information using configurable rules.

    Standalone function for easier testing.

    Args:
        device: Device information dictionary
        vlan_rules: VLAN detection rules configuration

    Returns:
        VLAN ID as integer
    """
    interface = device.get(ATTR_INTERFACE, "")

    static_mappings = vlan_rules.get("static_mappings", {})
    interface_patterns = vlan_rules.get("interface_patterns", {})

    if interface:
        # First, check static mappings (exact interface name matches)
        if interface in static_mappings:
            return static_mappings[interface]

        # Check for explicit VLAN tags in interface names
        # (checked before configurable patterns but after static mappings)
        interface_lower = interface.lower()
        if "vlan" in interface_lower:
            # Extract VLAN ID from names like "wlan0-vlan3", "phy0-ap1-vlan13"
            vlan_match = re.search(r"vlan(\d+)", interface_lower)
            if vlan_match:
                return int(vlan_match.group(1))

        # Then, check configurable patterns (pre-validated in config flow)
        for pattern, vlan_id in interface_patterns.items():
            try:
                if re.search(pattern, interface, re.IGNORECASE):
                    return vlan_id
            except re.error:
                # Skip invalid patterns (should be rare due to config flow validation)
                continue

        # Fall back to hardcoded patterns if no custom rules match
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
                # If IP segment is not an integer, fall back to default VLAN
                pass

    return 1  # Default to main VLAN


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

        # Router failure tracking for graceful degradation
        self._failed_routers: Dict[str, Dict[str, Any]] = (
            {}
        )  # Track failed routers with timestamps and error details
        self._consecutive_failures: Dict[str, int] = {}  # Track consecutive failures per router
        self._extended_failure_threshold = timedelta(
            minutes=30
        )  # Consider router truly failed after 30 minutes
        self._max_consecutive_failures = 5  # Mark router as failed after 5 consecutive failures

        # Compile regex patterns once for performance optimization
        self._vlan_pattern: Pattern[str] = re.compile(r"vlan(\d+)")

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from all routers."""
        _LOGGER.debug("Starting data update for %d routers", len(self.routers))

        # Authenticate with all routers in parallel, but skip permanently failed ones
        auth_tasks = []
        eligible_hosts = []
        for host, client in self.routers.items():
            # Skip routers that are permanently failed due to too many consecutive failures
            # But periodically retry them (every ~1 hour) to check if they've recovered
            if host in self._failed_routers and self._failed_routers[host].get(
                "is_permanently_failed", False
            ):
                # Allow retry if it's been more than 1 hour since last failure
                last_failure = self._failed_routers[host]["last_failure"]
                if (datetime.now() - last_failure) < timedelta(hours=1):
                    _LOGGER.debug(
                        "Skipping authentication for permanently failed router %s "
                        "(will retry after 1 hour)",
                        host,
                    )
                    continue
                else:
                    _LOGGER.info(
                        "Retrying permanently failed router %s after 1 hour cooldown", host
                    )
                    # Reset permanently failed flag for fresh attempt
                    self._failed_routers[host]["is_permanently_failed"] = False
            auth_tasks.append(self._authenticate_router(host, client))
            eligible_hosts.append(host)

        auth_results = await asyncio.gather(*auth_tasks, return_exceptions=True)

        # Process authentication results with graceful degradation
        successful_auths = 0
        for host, result in zip(eligible_hosts, auth_results):
            if isinstance(result, Exception):
                self._handle_router_failure(host, result, "authentication")
                self.sessions.pop(host, None)
            else:
                self._handle_router_success(host)
                self.sessions[host] = result
                successful_auths += 1

        # Check if we should continue with partial operation or fail completely
        if successful_auths == 0:
            if self._should_fail_completely():
                raise UpdateFailed("Failed to authenticate with any router")
            else:
                _LOGGER.warning(
                    "No routers currently available, but continuing with graceful degradation. "
                    "Failed routers: %s",
                    list(self._failed_routers.keys()),
                )
                # Return empty data rather than failing completely
                return self._create_update_data_response(graceful_degradation=True)

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

        for host, result in zip(self.sessions.keys(), router_data_results):
            if isinstance(result, Exception):
                self._handle_router_failure(host, result, "data_collection")
                continue

            # Mark this router as successful for data collection
            self._handle_router_success(host)
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

                    if dhcp_leases or static_hosts:
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

        return self._create_update_data_response(
            devices=enriched_devices,
            system_info=system_info,
            interfaces=interfaces,
            ssids=ssid_data,
            routers=list(self.sessions.keys()),
            graceful_degradation=len(self._failed_routers) > 0,
        )

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

            # Smart DHCP polling - only query DHCP from known DHCP servers or untested routers
            should_try_dhcp = host in self._dhcp_routers or host not in self._tried_dhcp

            if should_try_dhcp:
                _LOGGER.debug("Router %s - attempting to get DHCP leases...", host)
                dhcp_leases = await client.get_dhcp_leases(session_id)
                _LOGGER.debug("Router %s - DHCP leases result: %s", host, dhcp_leases)

                _LOGGER.debug("Router %s - attempting to get static DHCP hosts...", host)
                static_hosts = await client.get_static_dhcp_hosts(session_id)
                _LOGGER.debug("Router %s - static hosts result: %s", host, static_hosts)

                if dhcp_leases or static_hosts:
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

        except Exception as ex:
            _LOGGER.error("Error collecting data from %s: %s", host, ex)
            raise UpdateFailed(f"Data collection failed for {host}: {ex}")

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
        """Determine VLAN ID from device information using configurable rules."""
        # Get VLAN detection rules from options or use defaults
        vlan_rules = self.config_entry.options.get(
            CONF_VLAN_DETECTION_RULES, DEFAULT_VLAN_DETECTION_RULES
        )
        return _determine_vlan_with_rules(device, vlan_rules)

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

    def _handle_router_failure(self, host: str, error: Exception, operation: str) -> None:
        """Handle router failure with tracking for graceful degradation."""
        current_time = datetime.now()

        # Increment consecutive failures
        self._consecutive_failures[host] = self._consecutive_failures.get(host, 0) + 1

        # Log the failure with appropriate level based on consecutive failures
        consecutive_failures = self._consecutive_failures.get(host, 0)
        if consecutive_failures <= 3:
            _LOGGER.warning(
                "Router %s failed during %s (attempt %d): %s",
                host,
                operation,
                consecutive_failures,
                error,
            )
        else:
            _LOGGER.error(
                "Router %s repeatedly failing during %s (failure %d): %s",
                host,
                operation,
                consecutive_failures,
                error,
            )

        # Track failure details
        # If router was not in _failed_routers before this call, it means it had recovered
        # or this is the first failure - reset first_failure to current_time
        if host not in self._failed_routers:
            first_failure_time = current_time
            _LOGGER.debug(
                "Router %s - first failure or recovered, resetting failure timestamp", host
            )
        else:
            # Router was already in failed state, preserve original failure time
            first_failure_time = self._failed_routers[host].get("first_failure", current_time)
            _LOGGER.debug(
                "Router %s - continuing failure sequence from %s",
                host,
                first_failure_time.isoformat(),
            )

        self._failed_routers[host] = {
            "first_failure": first_failure_time,
            "last_failure": current_time,
            "consecutive_failures": self._consecutive_failures.get(host, 0),
            "last_error": str(error),
            "last_operation": operation,
            "is_extended_failure": (
                self._failed_routers[host].get("is_extended_failure", False)
                if host in self._failed_routers
                else False
            ),
            "is_permanently_failed": (
                self._failed_routers[host].get("is_permanently_failed", False)
                if host in self._failed_routers
                else False
            ),
        }

        # Check if this is now an extended failure
        first_failure_time = self._failed_routers[host]["first_failure"]
        if current_time - first_failure_time >= self._extended_failure_threshold:
            if not self._failed_routers[host]["is_extended_failure"]:
                _LOGGER.error(
                    "Router %s has been failing for over %s minutes - marking as extended failure",
                    host,
                    self._extended_failure_threshold.total_seconds() / 60,
                )
                self._failed_routers[host]["is_extended_failure"] = True

        # Check if router exceeded maximum consecutive failures threshold
        if self._consecutive_failures.get(host, 0) >= self._max_consecutive_failures:
            if not self._failed_routers[host].get("is_permanently_failed", False):
                _LOGGER.error(
                    "Router %s exceeded %d consecutive failures - marking as permanently failed",
                    host,
                    self._max_consecutive_failures,
                )
                self._failed_routers[host]["is_permanently_failed"] = True

    def _handle_router_success(self, host: str) -> None:
        """Handle router success - clear failure tracking."""
        if host in self._failed_routers:
            # Router recovered from failure
            failure_duration = datetime.now() - self._failed_routers[host]["first_failure"]
            _LOGGER.info(
                "Router %s recovered after %d consecutive failures over %s",
                host,
                self._consecutive_failures.get(host, 0),
                failure_duration,
            )

            # Clear failure tracking
            self._failed_routers.pop(host, None)
            self._consecutive_failures.pop(host, None)

    def _should_fail_completely(self) -> bool:
        """Determine if integration should fail completely or continue with graceful degradation."""
        # If we have no routers configured, we must fail
        if not self.routers:
            return True

        # Count routers in different failure states
        total_routers = len(self.routers)
        extended_failures = 0

        for host, failure_info in self._failed_routers.items():
            if failure_info["is_extended_failure"]:
                extended_failures += 1

        # If all routers are in extended failure state, we should fail completely
        if extended_failures >= total_routers:
            _LOGGER.error(
                "All %d routers have been in extended failure state - integration must fail",
                total_routers,
            )
            return True

        # If all routers are failing (but not all extended), continue with graceful degradation
        if len(self._failed_routers) >= total_routers:
            _LOGGER.warning(
                "All routers currently failing but not all in extended failure - "
                "continuing with graceful degradation"
            )
            return False

        # If we have at least one working router, continue normally
        return False

    def _create_failed_router_status(self, host: str, current_time: datetime) -> Dict[str, Any]:
        """Create status dictionary for a failed router."""
        failure_info = self._failed_routers[host]
        return {
            "status": "failed",
            "is_extended_failure": failure_info["is_extended_failure"],
            "consecutive_failures": failure_info["consecutive_failures"],
            "first_failure": failure_info["first_failure"].isoformat(),
            "last_failure": failure_info["last_failure"].isoformat(),
            "failure_duration_minutes": (
                current_time - failure_info["first_failure"]
            ).total_seconds()
            / 60,
            "last_error": failure_info["last_error"],
            "last_operation": failure_info["last_operation"],
        }

    def _create_healthy_router_status(self, host: str) -> Dict[str, Any]:
        """Create status dictionary for a healthy router."""
        return {
            "status": "healthy",
            "is_authenticated": host in self.sessions,
            "session_id": self.sessions.get(host, "N/A"),
        }

    def _create_update_data_response(
        self,
        devices: List[Dict[str, Any]] = None,
        system_info: Dict[str, Any] = None,
        interfaces: Dict[str, Any] = None,
        ssids: Dict[str, Any] = None,
        routers: List[str] = None,
        graceful_degradation: bool = False,
    ) -> Dict[str, Any]:
        """Create standardized data update response dictionary."""
        if devices is None:
            devices = []
        if system_info is None:
            system_info = {}
        if interfaces is None:
            interfaces = {}
        if ssids is None:
            ssids = {}
        if routers is None:
            routers = []

        return {
            "devices": devices,
            "system_info": system_info,
            "interfaces": interfaces,
            "ssids": ssids,
            "routers": routers,
            "last_update": datetime.now(),
            "total_devices": len(devices),
            "failed_routers": list(self._failed_routers.keys()),
            "graceful_degradation": graceful_degradation,
        }

    def get_router_status(self) -> Dict[str, Any]:
        """Get detailed status of all routers for diagnostics or monitoring.

        Returns:
            Dict[str, Any]: A dictionary mapping each router host to its status information.
                - For failed routers: includes status ("failed"), extended failure flag,
                  consecutive failures, first and last failure timestamps, failure duration
                  in minutes, last error, and last operation.
                - For healthy routers: includes status ("healthy"), authentication state,
                  and session ID.

        Usage:
            Call this method to retrieve the current health and diagnostic status of all
            managed routers. Useful for diagnostics panels, logging, or external monitoring
            tools.
        """
        current_time = datetime.now()
        router_status = {}

        for host in self.routers.keys():
            if host in self._failed_routers:
                status = self._create_failed_router_status(host, current_time)
            else:
                status = self._create_healthy_router_status(host)

            router_status[host] = status

        return router_status
