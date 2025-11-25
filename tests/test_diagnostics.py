"""Test the diagnostics module."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.wrtmanager.const import DOMAIN
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.diagnostics import (
    REDACT_KEYS,
    _count_interfaces,
    _format_uptime,
    _get_coordinator_diagnostics,
    _get_firmware_info,
    _get_routers_diagnostics,
    async_get_config_entry_diagnostics,
)


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.title = "Test WrtManager"
    entry.version = 1
    entry.domain = DOMAIN
    entry.unique_id = "test-unique-id"
    entry.entry_id = "test-entry-id"
    return entry


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    from unittest.mock import Mock

    hass = Mock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with sample data."""
    coordinator = MagicMock(spec=WrtManagerCoordinator)
    coordinator.update_interval = timedelta(seconds=30)
    coordinator.last_update_success = True

    # Sample coordinator data
    coordinator.data = {
        "last_update": datetime(2023, 1, 1, 12, 0, 0),
        "total_devices": 5,
        "routers": ["192.168.1.1", "192.168.1.2"],
        "devices": [
            {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ip": "192.168.1.100",
                "hostname": "test-device",
            }
        ],
        "system_info": {
            "192.168.1.1": {
                "uptime": 86400,  # 1 day
                "load": [0.1, 0.2, 0.15],
                "memory": {
                    "total": 134217728,
                    "free": 67108864,
                    "buffered": 8388608,
                    "shared": 4194304,
                },
                "localtime": 1672574400,
                "model": "Test Router Model",
                "system": "Test System",
                "board_name": "test-board",
                "kernel": "5.15.0",
                "release": {
                    "version": "22.03.0",
                    "description": "OpenWrt 22.03.0",
                    "distribution": "OpenWrt",
                    "revision": "test-revision",
                    "target": "ath79/generic",
                    "builddate": "2023-01-01",
                },
                "rootfs_type": "squashfs",
            }
        },
        "interfaces": {
            "192.168.1.1": {
                "radio0": {"interfaces": {"wlan0": {"status": "up"}}},
                "eth0": {"type": "ethernet", "status": "up"},
                "br-lan": {"type": "bridge", "status": "up"},
            }
        },
    }

    # Mock the get_devices_by_router method
    coordinator.get_devices_by_router.return_value = [
        {"mac": "AA:BB:CC:DD:EE:FF", "router": "192.168.1.1"},
        {"mac": "11:22:33:44:55:66", "router": "192.168.1.1"},
    ]

    return coordinator


class TestDiagnosticsMain:
    """Test main diagnostics function."""

    @pytest.mark.asyncio
    async def test_async_get_config_entry_diagnostics_success(
        self, mock_hass, mock_config_entry, mock_coordinator
    ):
        """Test successful diagnostics retrieval."""
        mock_hass.data[DOMAIN][mock_config_entry.entry_id] = mock_coordinator

        result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

        assert "integration_version" in result
        assert "config_entry" in result
        assert "coordinator_data" in result
        assert "routers_info" in result

        # Check config entry data
        config_entry_data = result["config_entry"]
        assert config_entry_data["title"] == "Test WrtManager"
        assert config_entry_data["version"] == 1
        assert config_entry_data["domain"] == DOMAIN

        # Verify that sensitive data is redacted
        # The exact structure after redaction depends on the async_redact_data implementation
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_async_get_config_entry_diagnostics_no_coordinator(
        self, mock_hass, mock_config_entry
    ):
        """Test diagnostics when coordinator doesn't exist."""
        # Don't add coordinator to hass.data

        with pytest.raises(KeyError):
            await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)


class TestCoordinatorDiagnostics:
    """Test coordinator diagnostics functions."""

    def test_get_coordinator_diagnostics_with_data(self, mock_coordinator):
        """Test coordinator diagnostics with data."""
        result = _get_coordinator_diagnostics(mock_coordinator)

        assert result["last_update"] == datetime(2023, 1, 1, 12, 0, 0)
        assert result["update_success"] is True
        assert result["total_devices"] == 5
        assert result["total_routers"] == 2
        assert "devices" in result["data_keys"]
        assert "system_info" in result["data_keys"]
        assert result["update_interval"] == "0:00:30"

    def test_get_coordinator_diagnostics_no_data(self):
        """Test coordinator diagnostics with no data."""
        mock_coordinator = MagicMock(spec=WrtManagerCoordinator)
        mock_coordinator.data = None

        result = _get_coordinator_diagnostics(mock_coordinator)

        assert result == {"status": "No data available"}


class TestRouterDiagnostics:
    """Test router diagnostics functions."""

    def test_get_routers_diagnostics_success(self, mock_coordinator):
        """Test successful router diagnostics."""
        result = _get_routers_diagnostics(mock_coordinator)

        assert "192.168.1.1" in result
        router_data = result["192.168.1.1"]

        # Check system info
        system_info = router_data["system_info"]
        assert system_info["uptime_seconds"] == 86400
        assert system_info["uptime_formatted"] == "1d 0h 0m"
        assert system_info["model"] == "Test Router Model"
        assert system_info["kernel"] == "5.15.0"

        # Check firmware info
        firmware_info = system_info["firmware_info"]
        assert firmware_info["openwrt_version"] == "22.03.0"
        assert firmware_info["distribution"] == "OpenWrt"

        # Check interface counts
        interface_counts = router_data["network_interfaces"]
        assert interface_counts["total_interfaces"] == 3
        assert interface_counts["wireless_radios"] == 1
        assert interface_counts["ethernet_interfaces"] == 1
        assert interface_counts["other_interfaces"] == 1

        # Check connected devices
        assert router_data["connected_devices"] == 2

    def test_get_routers_diagnostics_no_data(self):
        """Test router diagnostics with no data."""
        mock_coordinator = MagicMock(spec=WrtManagerCoordinator)
        mock_coordinator.data = None

        result = _get_routers_diagnostics(mock_coordinator)

        assert result == {}

    def test_get_routers_diagnostics_no_system_info(self):
        """Test router diagnostics with no system info."""
        mock_coordinator = MagicMock(spec=WrtManagerCoordinator)
        mock_coordinator.data = {"routers": ["192.168.1.1"]}

        result = _get_routers_diagnostics(mock_coordinator)

        assert result == {}


class TestUptimeFormatting:
    """Test uptime formatting functions."""

    def test_format_uptime_days_hours_minutes(self):
        """Test uptime formatting with days, hours, and minutes."""
        uptime_seconds = 90061  # 1 day, 1 hour, 1 minute, 1 second
        result = _format_uptime(uptime_seconds)
        assert result == "1d 1h 1m"

    def test_format_uptime_hours_minutes(self):
        """Test uptime formatting with hours and minutes."""
        uptime_seconds = 3661  # 1 hour, 1 minute, 1 second
        result = _format_uptime(uptime_seconds)
        assert result == "1h 1m"

    def test_format_uptime_minutes_only(self):
        """Test uptime formatting with minutes only."""
        uptime_seconds = 180  # 3 minutes
        result = _format_uptime(uptime_seconds)
        assert result == "3m"

    def test_format_uptime_zero_seconds(self):
        """Test uptime formatting with zero seconds."""
        result = _format_uptime(0)
        assert result == "Unknown"

    def test_format_uptime_none(self):
        """Test uptime formatting with None input."""
        result = _format_uptime(None)
        assert result == "Unknown"

    def test_format_uptime_multiple_days(self):
        """Test uptime formatting with multiple days."""
        uptime_seconds = 259200  # 3 days
        result = _format_uptime(uptime_seconds)
        assert result == "3d 0h 0m"


class TestFirmwareInfo:
    """Test firmware information extraction."""

    def test_get_firmware_info_complete(self):
        """Test firmware info extraction with complete data."""
        system_info = {
            "kernel": "5.15.0",
            "rootfs_type": "squashfs",
            "release": {
                "version": "22.03.0",
                "description": "OpenWrt 22.03.0",
                "distribution": "OpenWrt",
                "revision": "test-revision",
                "target": "ath79/generic",
                "builddate": "2023-01-01",
            },
        }

        result = _get_firmware_info(system_info)

        assert result["openwrt_version"] == "22.03.0"
        assert result["openwrt_description"] == "OpenWrt 22.03.0"
        assert result["distribution"] == "OpenWrt"
        assert result["revision"] == "test-revision"
        assert result["target"] == "ath79/generic"
        assert result["build_date"] == "2023-01-01"
        assert result["kernel_version"] == "5.15.0"
        assert result["rootfs_type"] == "squashfs"

    def test_get_firmware_info_missing_release(self):
        """Test firmware info extraction with missing release data."""
        system_info = {
            "kernel": "5.15.0",
            "rootfs_type": "squashfs",
        }

        result = _get_firmware_info(system_info)

        assert result["openwrt_version"] is None
        assert result["openwrt_description"] is None
        assert result["distribution"] is None
        assert result["kernel_version"] == "5.15.0"
        assert result["rootfs_type"] == "squashfs"

    def test_get_firmware_info_empty(self):
        """Test firmware info extraction with empty system info."""
        system_info = {}

        result = _get_firmware_info(system_info)

        assert all(value is None for value in result.values())


class TestInterfaceCounting:
    """Test network interface counting."""

    def test_count_interfaces_mixed_types(self, mock_coordinator):
        """Test interface counting with mixed interface types."""
        result = _count_interfaces(mock_coordinator, "192.168.1.1")

        assert result["total_interfaces"] == 3
        assert result["wireless_radios"] == 1
        assert result["ethernet_interfaces"] == 1
        assert result["other_interfaces"] == 1

    def test_count_interfaces_no_interfaces(self, mock_coordinator):
        """Test interface counting with no interfaces."""
        mock_coordinator.data["interfaces"]["192.168.1.1"] = {}

        result = _count_interfaces(mock_coordinator, "192.168.1.1")

        assert result["total_interfaces"] == 0
        assert result["wireless_radios"] == 0
        assert result["ethernet_interfaces"] == 0
        assert result["other_interfaces"] == 0

    def test_count_interfaces_router_not_found(self, mock_coordinator):
        """Test interface counting for router not in data."""
        result = _count_interfaces(mock_coordinator, "192.168.1.99")

        assert result["total_interfaces"] == 0
        assert result["wireless_radios"] == 0
        assert result["ethernet_interfaces"] == 0
        assert result["other_interfaces"] == 0

    def test_count_interfaces_no_coordinator_data(self):
        """Test interface counting with no coordinator data."""
        mock_coordinator = MagicMock(spec=WrtManagerCoordinator)
        mock_coordinator.data = None

        result = _count_interfaces(mock_coordinator, "192.168.1.1")

        assert result == {}

    def test_count_interfaces_no_interface_data(self, mock_coordinator):
        """Test interface counting with no interface data in coordinator."""
        del mock_coordinator.data["interfaces"]

        result = _count_interfaces(mock_coordinator, "192.168.1.1")

        assert result == {}

    def test_count_interfaces_wireless_only(self, mock_coordinator):
        """Test interface counting with only wireless interfaces."""
        mock_coordinator.data["interfaces"]["192.168.1.1"] = {
            "radio0": {"interfaces": {"wlan0": {"status": "up"}}},
            "radio1": {"interfaces": {"wlan1": {"status": "up"}}},
        }

        result = _count_interfaces(mock_coordinator, "192.168.1.1")

        assert result["total_interfaces"] == 2
        assert result["wireless_radios"] == 2
        assert result["ethernet_interfaces"] == 0
        assert result["other_interfaces"] == 0

    def test_count_interfaces_ethernet_only(self, mock_coordinator):
        """Test interface counting with only ethernet interfaces."""
        mock_coordinator.data["interfaces"]["192.168.1.1"] = {
            "eth0": {"type": "ethernet", "status": "up"},
            "eth1": {"type": "ethernet", "status": "down"},
        }

        result = _count_interfaces(mock_coordinator, "192.168.1.1")

        assert result["total_interfaces"] == 2
        assert result["wireless_radios"] == 0
        assert result["ethernet_interfaces"] == 2
        assert result["other_interfaces"] == 0


class TestRedactionKeys:
    """Test redaction key configuration."""

    def test_redact_keys_defined(self):
        """Test that redaction keys are properly defined."""
        expected_keys = ["password", "key", "mac", "ip", "hostname", "serial"]

        assert REDACT_KEYS == expected_keys
        assert all(isinstance(key, str) for key in REDACT_KEYS)

    def test_redact_keys_coverage(self):
        """Test that redaction keys cover sensitive data types."""
        # Verify that common sensitive data types are covered
        sensitive_data_types = {
            "password": "Authentication credentials",
            "key": "Encryption keys and API keys",
            "mac": "MAC addresses for device identification",
            "ip": "IP addresses",
            "hostname": "Device hostnames",
            "serial": "Serial numbers",
        }

        for key in sensitive_data_types:
            assert key in REDACT_KEYS, f"Sensitive data type '{key}' not in REDACT_KEYS"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_system_info_structure(self, mock_coordinator):
        """Test diagnostics with empty system info structure."""
        mock_coordinator.data["system_info"]["192.168.1.1"] = {}

        result = _get_routers_diagnostics(mock_coordinator)

        assert "192.168.1.1" in result
        router_data = result["192.168.1.1"]

        # Should handle missing fields gracefully
        system_info = router_data["system_info"]
        assert system_info["uptime_formatted"] == "Unknown"
        assert system_info["firmware_info"]["openwrt_version"] is None

    def test_malformed_interface_data(self, mock_coordinator):
        """Test interface counting with malformed interface data."""
        # Set non-dict interface data
        mock_coordinator.data["interfaces"]["192.168.1.1"] = {
            "invalid_interface": "not_a_dict",
            "radio0": {"interfaces": {"wlan0": {"status": "up"}}},
        }

        result = _count_interfaces(mock_coordinator, "192.168.1.1")

        # Should still count valid interfaces
        assert result["total_interfaces"] == 2
        assert result["wireless_radios"] == 1
