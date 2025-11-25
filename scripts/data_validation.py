#!/usr/bin/env python3
"""
OpenWrt Data Validation Script
Tests all available ubus endpoints to understand what data we can collect.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "wrtmanager"))

from ubus_client import UbusClient

# Configure logging for this script
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
_LOGGER = logging.getLogger(__name__)


class DataValidator:
    """Validates available data from OpenWrt routers."""

    def __init__(self, host: str, username: str, password: str):
        self.client = UbusClient(host, username, password)
        self.data_sources = {}
        self.errors = {}

    async def validate_all_data_sources(self):
        """Test all possible ubus data sources."""
        _LOGGER.info("Validating data sources on %s", self.client.host)

        try:
            session_id = await self.client.authenticate()
            _LOGGER.info("Authentication successful: %s", session_id)
        except Exception as e:
            _LOGGER.error("Authentication failed: %s", e)
            return False

        # Test all data sources
        await self._test_wireless_data(session_id)
        await self._test_network_data(session_id)
        await self._test_system_data(session_id)
        await self._test_dhcp_data(session_id)
        await self._test_firewall_data(session_id)
        await self._test_advanced_apis(session_id)

        await self.client.close()
        return True

    async def _test_wireless_data(self, session_id: str):
        """Test wireless/WiFi related data."""
        _LOGGER.info("Testing Wireless Data Sources")

        # iwinfo APIs
        await self._test_api(session_id, "iwinfo", "devices", {}, "Wireless device list")

        # Get first device for further testing
        devices = await self.client.get_wireless_devices(session_id)
        if devices:
            device = devices[0]
            await self._test_api(
                session_id,
                "iwinfo",
                "assoclist",
                {"device": device},
                f"Associated clients on {device}",
            )
            await self._test_api(
                session_id, "iwinfo", "info", {"device": device}, f"Device info for {device}"
            )
            await self._test_api(
                session_id,
                "iwinfo",
                "scanlist",
                {"device": device},
                f"WiFi scan results on {device}",
            )
            await self._test_api(
                session_id, "iwinfo", "freqlist", {"device": device}, f"Frequency list for {device}"
            )
            await self._test_api(
                session_id,
                "iwinfo",
                "txpowerlist",
                {"device": device},
                f"TX power list for {device}",
            )

            # hostapd APIs (for AP mode)
            await self._test_api(
                session_id, f"hostapd.{device}", "get_clients", {}, f"hostapd clients on {device}"
            )
            await self._test_api(
                session_id, f"hostapd.{device}", "get_status", {}, f"hostapd status on {device}"
            )

    async def _test_network_data(self, session_id: str):
        """Test network configuration and status."""
        _LOGGER.info("Testing Network Data Sources")

        await self._test_api(session_id, "network.interface", "dump", {}, "Network interfaces")
        await self._test_api(session_id, "network.device", "status", {}, "Network device status")
        await self._test_api(
            session_id, "network.wireless", "status", {}, "Wireless network status"
        )
        await self._test_api(session_id, "network", "reload", {}, "Network reload capability")

    async def _test_system_data(self, session_id: str):
        """Test system information."""
        _LOGGER.info("Testing System Data Sources")

        await self._test_api(session_id, "system", "board", {}, "System board information")
        await self._test_api(session_id, "system", "info", {}, "System information")
        await self._test_api(session_id, "system", "reboot", {}, "Reboot capability (dry-run)")

    async def _test_dhcp_data(self, session_id: str):
        """Test DHCP lease information."""
        _LOGGER.info("Testing DHCP Data Sources")

        await self._test_api(session_id, "dhcp", "ipv4leases", {}, "DHCP IPv4 leases")
        await self._test_api(session_id, "dhcp", "ipv6leases", {}, "DHCP IPv6 leases")

    async def _test_firewall_data(self, session_id: str):
        """Test firewall and traffic data."""
        _LOGGER.info("Testing Firewall Data Sources")

        await self._test_api(session_id, "luci-rpc", "getConntrackList", {}, "Connection tracking")
        await self._test_api(
            session_id,
            "luci-rpc",
            "getRealtimeStats",
            {"mode": "interface"},
            "Real-time interface stats",
        )
        await self._test_api(
            session_id, "luci-rpc", "getNetworkDevices", {}, "Network devices via LuCI"
        )

    async def _test_advanced_apis(self, session_id: str):
        """Test advanced/experimental APIs."""
        _LOGGER.info("Testing Advanced APIs")

        # UCI (configuration)
        await self._test_api(session_id, "uci", "configs", {}, "Available UCI configurations")
        await self._test_api(
            session_id, "uci", "get", {"config": "wireless"}, "Wireless UCI configuration"
        )
        await self._test_api(
            session_id, "uci", "get", {"config": "network"}, "Network UCI configuration"
        )

        # Log files
        await self._test_api(session_id, "log", "read", {"lines": 10}, "System log (last 10 lines)")

        # File system
        await self._test_api(
            session_id, "file", "list", {"path": "/proc/net"}, "Network proc files"
        )

    async def _test_api(
        self, session_id: str, service: str, method: str, params: dict, description: str
    ):
        """Test a specific ubus API call."""
        try:
            result = await self.client.call_ubus(session_id, service, method, params)
            if result is not None:
                _LOGGER.info("SUCCESS: %s", description)
                self.data_sources[f"{service}.{method}"] = {
                    "description": description,
                    "sample_data": self._truncate_data(result),
                    "data_keys": list(result.keys()) if isinstance(result, dict) else "non-dict",
                    "status": "success",
                }
            else:
                _LOGGER.warning("NO DATA: %s", description)
                self.data_sources[f"{service}.{method}"] = {
                    "description": description,
                    "status": "no_data",
                }
        except Exception as e:
            _LOGGER.error("FAILED: %s - %s", description, e)
            self.errors[f"{service}.{method}"] = {"description": description, "error": str(e)}

    def _truncate_data(self, data, max_length=200):
        """Truncate data for display purposes."""
        data_str = str(data)
        if len(data_str) > max_length:
            return data_str[:max_length] + "..."
        return data

    def generate_report(self):
        """Generate a comprehensive data availability report."""
        _LOGGER.info("=" * 80)
        _LOGGER.info("DATA AVAILABILITY REPORT")
        _LOGGER.info("=" * 80)

        _LOGGER.info("Successfully tested APIs: %d", len(self.data_sources))
        _LOGGER.info("Failed APIs: %d", len(self.errors))

        _LOGGER.info("Available Data Sources:")
        for api, info in self.data_sources.items():
            status = "SUCCESS" if info["status"] == "success" else "NO DATA"
            _LOGGER.info("  [%s] %s: %s", status, api, info["description"])
            if info["status"] == "success" and "data_keys" in info:
                if isinstance(info["data_keys"], list):
                    keys_display = ", ".join(info["data_keys"][:5])
                    if len(info["data_keys"]) > 5:
                        keys_display += "..."
                    _LOGGER.info("    Keys: %s", keys_display)

        if self.errors:
            _LOGGER.info("Failed APIs:")
            for api, error_info in self.errors.items():
                _LOGGER.error("  [FAILED] %s: %s", api, error_info["error"])

        # Generate feature mapping
        _LOGGER.info("FEATURE IMPLEMENTATION GUIDANCE:")
        self._suggest_feature_mapping()

    def _suggest_feature_mapping(self):
        """Suggest which APIs to use for each feature."""
        features = {
            "Device Discovery": ["iwinfo.devices", "iwinfo.assoclist", "hostapd.*.get_clients"],
            "Device Information": ["iwinfo.assoclist", "dhcp.ipv4leases", "network.device.status"],
            "Network Status": ["network.interface.dump", "network.wireless.status"],
            "System Monitoring": ["system.info", "system.board", "log.read"],
            "Traffic Analysis": ["luci-rpc.getRealtimeStats", "luci-rpc.getConntrackList"],
            "Configuration": ["uci.get", "network.interface.dump"],
        }

        for feature, apis in features.items():
            available_apis = [
                api
                for api in apis
                if any(api.replace("*", "") in source for source in self.data_sources.keys())
            ]
            if available_apis:
                _LOGGER.info("  [AVAILABLE] %s: %s", feature, ", ".join(available_apis))
            else:
                _LOGGER.warning("  [MISSING] %s: No compatible APIs found", feature)


async def main():
    """Main validation function."""
    if len(sys.argv) != 4:
        _LOGGER.error("Usage: python data_validation.py <host> <username> <password>")
        _LOGGER.error("Example: python data_validation.py 192.168.1.1 hass password")
        sys.exit(1)

    host = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]

    validator = DataValidator(host, username, password)

    success = await validator.validate_all_data_sources()
    if success:
        validator.generate_report()

        # Save detailed results
        results = {
            "data_sources": validator.data_sources,
            "errors": validator.errors,
            "summary": {
                "total_apis_tested": len(validator.data_sources) + len(validator.errors),
                "successful_apis": len(validator.data_sources),
                "failed_apis": len(validator.errors),
            },
        }

        with open("openwrt_data_validation.json", "w") as f:
            json.dump(results, f, indent=2)
        _LOGGER.info("Detailed results saved to: openwrt_data_validation.json")

    return success


if __name__ == "__main__":
    asyncio.run(main())
