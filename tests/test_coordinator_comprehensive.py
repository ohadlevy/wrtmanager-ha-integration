"""Comprehensive tests for WrtManager coordinator."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.wrtmanager.const import (
    ATTR_CONNECTED,
    ATTR_DATA_SOURCE,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_IP,
    ATTR_LAST_SEEN,
    ATTR_MAC,
    ATTR_ROUTER,
    CONF_ROUTERS,
    DATA_SOURCE_WIFI_ONLY,
)
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

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
            CONF_ROUTERS: [
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
def coordinator(hass: HomeAssistant, mock_config_entry):
    """Create a coordinator instance."""
    return WrtManagerCoordinator(
        hass=hass,
        logger=Mock(),
        name="Test WrtManager",
        update_interval=timedelta(minutes=1),
        config_entry=mock_config_entry,
    )


class TestWrtManagerCoordinator:
    """Test the WrtManager coordinator."""

    async def test_init(self, coordinator):
        """Test coordinator initialization."""
        assert len(coordinator.routers) == 1
        assert "192.168.1.1" in coordinator.routers
        assert coordinator.sessions == {}
        assert coordinator.device_manager is not None

    async def test_authenticate_router_success(self, coordinator):
        """Test successful router authentication."""
        client = coordinator.routers["192.168.1.1"]
        client.authenticate = AsyncMock(return_value="test_session")

        result = await coordinator._authenticate_router("192.168.1.1", client)
        assert result == "test_session"

    async def test_authenticate_router_failure(self, coordinator):
        """Test failed router authentication."""
        client = coordinator.routers["192.168.1.1"]
        client.authenticate = AsyncMock(return_value=None)

        with pytest.raises(UpdateFailed):
            await coordinator._authenticate_router("192.168.1.1", client)

    async def test_collect_router_data_success(self, coordinator):
        """Test successful data collection from router."""
        client = coordinator.routers["192.168.1.1"]
        client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
        client.get_device_associations = AsyncMock(
            return_value=[{"mac": "aa:bb:cc:dd:ee:ff", "signal": -50}]
        )
        client.get_system_info = AsyncMock(return_value={"hostname": "OpenWrt"})
        client.get_system_board = AsyncMock(return_value={"model": "Test Router"})
        client.get_network_interfaces = AsyncMock(return_value={})
        client.get_wireless_status = AsyncMock(return_value={})
        client.get_dhcp_leases = AsyncMock(return_value={})
        client.get_static_dhcp_hosts = AsyncMock(return_value={})

        result = await coordinator._collect_router_data("192.168.1.1", "test_session")

        wifi_devices, dhcp_data, system_data, interface_data = result
        assert len(wifi_devices) == 1
        assert wifi_devices[0][ATTR_MAC] == "AA:BB:CC:DD:EE:FF"
        assert wifi_devices[0][ATTR_INTERFACE] == "wlan0"
        assert wifi_devices[0][ATTR_ROUTER] == "192.168.1.1"

    async def test_collect_router_data_failure(self, coordinator):
        """Test data collection failure."""
        client = coordinator.routers["192.168.1.1"]
        client.get_wireless_devices = AsyncMock(side_effect=Exception("Connection error"))

        with pytest.raises(UpdateFailed):
            await coordinator._collect_router_data("192.168.1.1", "test_session")

    async def test_parse_dhcp_data_dynamic(self, coordinator):
        """Test parsing dynamic DHCP data."""
        dhcp_leases = {
            "dhcp_leases": [
                {
                    "macaddr": "aa:bb:cc:dd:ee:ff",
                    "ipaddr": "192.168.1.100",
                    "hostname": "test-device",
                }
            ]
        }
        static_hosts = None

        result = coordinator._parse_dhcp_data(dhcp_leases, static_hosts)

        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_IP] == "192.168.1.100"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_HOSTNAME] == "test-device"

    async def test_parse_dhcp_data_static(self, coordinator):
        """Test parsing static DHCP data."""
        dhcp_leases = None
        static_hosts = {
            "values": {
                "host1": {
                    ".type": "host",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "ip": "192.168.1.50",
                    "name": "static-device",
                }
            }
        }

        result = coordinator._parse_dhcp_data(dhcp_leases, static_hosts)

        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_IP] == "192.168.1.50"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_HOSTNAME] == "static-device"

    async def test_correlate_device_data(self, coordinator):
        """Test device data correlation."""
        wifi_devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_INTERFACE: "wlan0",
                ATTR_ROUTER: "192.168.1.1",
                ATTR_CONNECTED: True,
                ATTR_LAST_SEEN: datetime.now(),
            }
        ]
        dhcp_data = {
            "AA:BB:CC:DD:EE:FF": {
                ATTR_IP: "192.168.1.100",
                ATTR_HOSTNAME: "test-device",
                ATTR_DATA_SOURCE: "dhcp",
            }
        }

        result = coordinator._correlate_device_data(wifi_devices, dhcp_data)

        assert len(result) == 1
        device = result[0]
        assert device[ATTR_MAC] == "AA:BB:CC:DD:EE:FF"
        assert device[ATTR_IP] == "192.168.1.100"
        assert device[ATTR_HOSTNAME] == "test-device"

    async def test_correlate_device_data_wifi_only(self, coordinator):
        """Test device data correlation with WiFi-only devices."""
        wifi_devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_INTERFACE: "wlan0",
                ATTR_ROUTER: "192.168.1.1",
                ATTR_CONNECTED: True,
                ATTR_LAST_SEEN: datetime.now(),
            }
        ]
        dhcp_data = {}

        result = coordinator._correlate_device_data(wifi_devices, dhcp_data)

        assert len(result) == 1
        device = result[0]
        assert device[ATTR_MAC] == "AA:BB:CC:DD:EE:FF"
        assert device[ATTR_DATA_SOURCE] == DATA_SOURCE_WIFI_ONLY

    async def test_determine_vlan(self, coordinator):
        """Test VLAN determination logic."""
        # Test IoT VLAN detection
        device = {"interface": "wlan0-iot"}
        assert coordinator._determine_vlan(device) == 3

        # Test guest VLAN detection
        device = {"interface": "wlan1-guest"}
        assert coordinator._determine_vlan(device) == 100

        # Test IP-based VLAN detection
        device = {"ip": "192.168.10.100"}
        assert coordinator._determine_vlan(device) == 10

        # Test default VLAN
        device = {"interface": "wlan0"}
        assert coordinator._determine_vlan(device) == 1

    async def test_update_roaming_detection(self, coordinator):
        """Test roaming detection functionality."""
        devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_ROUTER: "192.168.1.1",
                "signal_dbm": -50,
            },
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_ROUTER: "192.168.1.2",
                "signal_dbm": -60,
            },
        ]

        coordinator._update_roaming_detection(devices)

        # Both devices should have the same primary AP (best signal)
        for device in devices:
            assert device.get("primary_ap") == "192.168.1.1"

    async def test_async_shutdown(self, coordinator):
        """Test coordinator shutdown."""
        client = coordinator.routers["192.168.1.1"]
        client.close = AsyncMock()

        await coordinator.async_shutdown()

        client.close.assert_called_once()

    async def test_get_device_by_mac(self, coordinator):
        """Test getting device by MAC address."""
        coordinator.data = {
            "devices": [
                {ATTR_MAC: "AA:BB:CC:DD:EE:FF", "name": "Device 1"},
                {ATTR_MAC: "11:22:33:44:55:66", "name": "Device 2"},
            ]
        }

        device = coordinator.get_device_by_mac("AA:BB:CC:DD:EE:FF")
        assert device is not None
        assert device["name"] == "Device 1"

        device = coordinator.get_device_by_mac("nonexistent")
        assert device is None

    async def test_get_devices_by_router(self, coordinator):
        """Test getting devices by router."""
        coordinator.data = {
            "devices": [
                {ATTR_ROUTER: "192.168.1.1", "name": "Device 1"},
                {ATTR_ROUTER: "192.168.1.2", "name": "Device 2"},
                {ATTR_ROUTER: "192.168.1.1", "name": "Device 3"},
            ]
        }

        devices = coordinator.get_devices_by_router("192.168.1.1")
        assert len(devices) == 2
        assert devices[0]["name"] == "Device 1"
        assert devices[1]["name"] == "Device 3"

    async def test_full_update_cycle_success(self, coordinator):
        """Test a complete successful update cycle."""
        # Mock all client methods
        client = coordinator.routers["192.168.1.1"]
        client.authenticate = AsyncMock(return_value="test_session")
        client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
        client.get_device_associations = AsyncMock(
            return_value=[{"mac": "aa:bb:cc:dd:ee:ff", "signal": -50}]
        )
        client.get_system_info = AsyncMock(return_value={"hostname": "OpenWrt"})
        client.get_system_board = AsyncMock(return_value={"model": "Test Router"})
        client.get_network_interfaces = AsyncMock(return_value={})
        client.get_wireless_status = AsyncMock(return_value={})
        client.get_dhcp_leases = AsyncMock(return_value={})
        client.get_static_dhcp_hosts = AsyncMock(return_value={})

        result = await coordinator._async_update_data()

        assert "devices" in result
        assert "system_info" in result
        assert "interfaces" in result
        assert "ssids" in result
        assert len(result["devices"]) == 1

    async def test_full_update_cycle_auth_failure(self, coordinator):
        """Test update cycle with authentication failure."""
        client = coordinator.routers["192.168.1.1"]
        client.authenticate = AsyncMock(side_effect=Exception("Auth failed"))

        with pytest.raises(UpdateFailed, match="Failed to authenticate with any router"):
            await coordinator._async_update_data()

    async def test_sanitize_config(self, coordinator):
        """Test configuration sanitization."""
        config = {
            "ssid": "TestNetwork",
            "key": "supersecret",
            "wpa_passphrase": "password123",
            "other_field": "normal_value",
        }

        result = coordinator._sanitize_config(config)

        assert result["ssid"] == "TestNetwork"
        assert result["key"] == "***REDACTED***"
        assert result["wpa_passphrase"] == "***REDACTED***"
        assert result["other_field"] == "normal_value"

    async def test_extract_ssid_data_basic(self, coordinator):
        """Test basic SSID data extraction."""
        interfaces = {
            "192.168.1.1": {
                "radio0": {
                    "interfaces": [
                        {
                            "config": {
                                "ssid": "TestNetwork",
                                "mode": "ap",
                                "disabled": False,
                            },
                            "ifname": "wlan0",
                        }
                    ]
                }
            }
        }

        result = coordinator._extract_ssid_data(interfaces)

        assert "192.168.1.1" in result
        assert len(result["192.168.1.1"]) == 1
        ssid_info = result["192.168.1.1"][0]
        assert ssid_info["ssid_name"] == "TestNetwork"
        assert ssid_info["radio"] == "radio0"
        assert ssid_info["disabled"] is False
