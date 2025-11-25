"""Test diagnostics for WrtManager."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.wrtmanager.diagnostics import async_get_config_entry_diagnostics

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return ConfigEntry(
        version=1,
        minor_version=0,
        domain="wrtmanager",
        title="Test WrtManager",
        data={
            "routers": [
                {
                    "host": "192.168.1.1",
                    "username": "test",
                    "password": "test",
                    "use_https": False,
                    "verify_ssl": False,
                }
            ]
        },
        source="user",
        entry_id="test_entry",
        unique_id="test_unique_id",
        discovery_keys=set(),
        options={},
        subentries_data={},
    )


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock()
    coordinator.data = {
        "devices": [
            {
                "mac": "AA:BB:CC:DD:EE:FF",
                "hostname": "test-device",
                "ip": "192.168.1.100",
                "router": "192.168.1.1",
                "interface": "wlan0",
                "connected": True,
                "last_seen": datetime.now(),
                "vendor": "Apple",
                "device_type": "smartphone",
                "data_source": "dhcp",
                "vlan_id": 1,
                "primary_ap": "192.168.1.1",
                "roaming_count": 0,
            }
        ],
        "system_info": {
            "192.168.1.1": {
                "hostname": "OpenWrt",
                "model": "Test Router",
                "uptime": 86400,
            }
        },
        "interfaces": {
            "192.168.1.1": {
                "wlan0": {
                    "up": True,
                    "type": "wifi",
                }
            }
        },
        "ssids": {
            "192.168.1.1": [
                {
                    "ssid_name": "TestNetwork",
                    "radio": "radio0",
                    "disabled": False,
                    "encryption": "psk2",
                    "hidden": False,
                }
            ]
        },
        "routers": ["192.168.1.1"],
        "last_update": datetime.now(),
        "total_devices": 1,
    }
    coordinator.config_entry = mock_config_entry
    return coordinator


class TestDiagnostics:
    """Test diagnostic data collection."""

    async def test_async_get_config_entry_diagnostics(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test getting diagnostic data."""
        # Mock the coordinator in hass data
        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        assert "config" in result
        assert "data" in result
        assert "coordinator_info" in result

        # Check config data (should be sanitized)
        config = result["config"]
        assert config["routers"][0]["host"] == "192.168.1.1"
        assert config["routers"][0]["password"] == "***REDACTED***"

        # Check coordinator data
        data = result["data"]
        assert "devices" in data
        assert "system_info" in data
        assert "interfaces" in data
        assert "ssids" in data

        # Check coordinator info
        info = result["coordinator_info"]
        assert "entry_id" in info
        assert "last_update_success" in info

    async def test_diagnostics_data_sanitization(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test that sensitive data is properly sanitized."""
        # Add some sensitive data to the coordinator
        mock_coordinator.data["ssids"]["192.168.1.1"][0]["key"] = "supersecret"
        mock_coordinator.data["ssids"]["192.168.1.1"][0]["wpa_passphrase"] = "password123"

        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        # Check that passwords are redacted
        ssid_data = result["data"]["ssids"]["192.168.1.1"][0]
        assert ssid_data["key"] == "***REDACTED***"
        assert ssid_data["wpa_passphrase"] == "***REDACTED***"

    async def test_diagnostics_with_no_coordinator(self, hass: HomeAssistant, mock_config_entry):
        """Test diagnostics when coordinator is not available."""
        hass.data = {}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        assert "config" in result
        assert "error" in result
        assert result["error"] == "Coordinator not found"

    async def test_diagnostics_with_empty_data(self, hass: HomeAssistant, mock_config_entry):
        """Test diagnostics with empty coordinator data."""
        mock_coordinator = Mock()
        mock_coordinator.data = None
        mock_coordinator.config_entry = mock_config_entry
        mock_coordinator.last_update_success = True
        mock_coordinator.last_update_success_time = datetime.now()

        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        assert result["data"] is None
        assert "coordinator_info" in result

    async def test_diagnostics_device_data_structure(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test the structure of device data in diagnostics."""
        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        devices = result["data"]["devices"]
        assert len(devices) == 1

        device = devices[0]
        assert "mac" in device
        assert "hostname" in device
        assert "ip" in device
        assert "router" in device
        assert "interface" in device
        assert "connected" in device
        assert "vendor" in device
        assert "device_type" in device

    async def test_diagnostics_system_info_structure(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test the structure of system info in diagnostics."""
        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        system_info = result["data"]["system_info"]
        assert "192.168.1.1" in system_info

        router_info = system_info["192.168.1.1"]
        assert "hostname" in router_info
        assert "model" in router_info
        assert "uptime" in router_info

    async def test_diagnostics_coordinator_info(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test coordinator information in diagnostics."""
        mock_coordinator.last_update_success = True
        mock_coordinator.last_update_success_time = datetime.now()
        mock_coordinator.update_interval.total_seconds.return_value = 60

        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        info = result["coordinator_info"]
        assert info["entry_id"] == "test_entry"
        assert info["last_update_success"] is True
        assert "last_update_success_time" in info
        assert info["update_interval"] == 60

    async def test_diagnostics_multiple_routers(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test diagnostics with multiple routers."""
        # Add a second router to the data
        mock_coordinator.data["system_info"]["192.168.1.2"] = {
            "hostname": "Router2",
            "model": "Another Router",
            "uptime": 43200,
        }
        mock_coordinator.data["routers"].append("192.168.1.2")

        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        system_info = result["data"]["system_info"]
        assert len(system_info) == 2
        assert "192.168.1.1" in system_info
        assert "192.168.1.2" in system_info

        routers = result["data"]["routers"]
        assert len(routers) == 2
        assert "192.168.1.1" in routers
        assert "192.168.1.2" in routers
