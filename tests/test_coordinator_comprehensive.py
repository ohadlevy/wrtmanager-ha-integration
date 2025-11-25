"""Comprehensive tests for WrtManagerCoordinator."""

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager.const import (
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
    ROAMING_DETECTION_THRESHOLD,
)
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.ubus_client import UbusClientError


@pytest.fixture
def mock_config_entry(sample_config_data):
    """Create a mock config entry."""
    return MockConfigEntry(
        domain="wrtmanager", data=sample_config_data, unique_id="test_coordinator"
    )


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    # Instead of trying to instantiate the coordinator, we'll test methods directly
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    return MagicMock()


@pytest.fixture
def sample_config_data():
    """Sample configuration data."""
    return {
        CONF_ROUTERS: [
            {
                "host": "192.168.1.1",
                "username": "root",
                "password": "password123",
                "use_https": False,
                "verify_ssl": False,
            },
            {
                "host": "192.168.1.2",
                "username": "admin",
                "password": "password456",
                "use_https": True,
                "verify_ssl": True,
            },
        ]
    }


@pytest.fixture
def coordinator(mock_hass, mock_logger, mock_config_entry, sample_config_data):
    """Create a mock WrtManagerCoordinator for testing methods."""
    # Create a mock coordinator and attach the actual methods we want to test
    coordinator = MagicMock()
    coordinator.logger = mock_logger
    coordinator.config_entry = mock_config_entry

    # Initialize the attributes as the real coordinator would
    coordinator.routers = {}
    coordinator.sessions = {}
    coordinator.data = {}
    coordinator._device_history = {}
    coordinator.device_manager = MagicMock()

    # Initialize router clients like the real coordinator does
    for router_config in sample_config_data["routers"]:
        host = router_config["host"]
        coordinator.routers[host] = MagicMock()  # Mock UbusClient

    # Attach the actual methods we want to test
    coordinator._parse_dhcp_data = WrtManagerCoordinator._parse_dhcp_data.__get__(coordinator)
    coordinator._correlate_device_data = WrtManagerCoordinator._correlate_device_data.__get__(
        coordinator
    )
    coordinator._determine_vlan = WrtManagerCoordinator._determine_vlan.__get__(coordinator)
    coordinator._update_roaming_detection = WrtManagerCoordinator._update_roaming_detection.__get__(
        coordinator
    )
    coordinator.get_device_by_mac = WrtManagerCoordinator.get_device_by_mac.__get__(coordinator)
    coordinator.get_devices_by_router = WrtManagerCoordinator.get_devices_by_router.__get__(
        coordinator
    )
    coordinator._extract_ssid_data = WrtManagerCoordinator._extract_ssid_data.__get__(coordinator)
    coordinator._consolidate_ssids_by_name = (
        WrtManagerCoordinator._consolidate_ssids_by_name.__get__(coordinator)
    )
    coordinator._get_frequency_bands = WrtManagerCoordinator._get_frequency_bands.__get__(
        coordinator
    )

    return coordinator


class TestCoordinatorInitialization:
    """Test coordinator initialization."""

    def test_coordinator_init(self, coordinator, sample_config_data):
        """Test coordinator initialization."""
        assert len(coordinator.routers) == 2
        assert "192.168.1.1" in coordinator.routers
        assert "192.168.1.2" in coordinator.routers
        assert coordinator.sessions == {}
        assert coordinator._device_history == {}
        assert coordinator.device_manager is not None


class TestCoordinatorDataUpdate:
    """Test data update functionality."""

    async def test_async_update_data_success(self, coordinator):
        """Test successful data update."""
        # Mock authentication results
        coordinator.sessions = {"192.168.1.1": "session1", "192.168.1.2": "session2"}

        # Mock the authentication step
        with patch.object(coordinator, "_authenticate_router") as mock_auth:
            mock_auth.side_effect = ["session1", "session2"]

            # Mock the data collection step
            with patch.object(coordinator, "_collect_router_data") as mock_collect:
                wifi_devices = [
                    {
                        ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                        ATTR_INTERFACE: "wlan0",
                        ATTR_SIGNAL_DBM: -45,
                        ATTR_ROUTER: "192.168.1.1",
                        ATTR_CONNECTED: True,
                        ATTR_LAST_SEEN: datetime.now(),
                    }
                ]
                dhcp_data = {
                    "AA:BB:CC:DD:EE:FF": {
                        ATTR_IP: "192.168.1.100",
                        ATTR_HOSTNAME: "test-device",
                        ATTR_DATA_SOURCE: DATA_SOURCE_DYNAMIC_DHCP,
                    }
                }
                system_data = {"hostname": "test-router"}
                interface_data = {"wlan0": {"status": "up"}}

                mock_collect.side_effect = [
                    (wifi_devices, dhcp_data, system_data, interface_data),
                    ([], {}, {}, {}),  # Second router returns empty data
                ]

                # Mock correlation and roaming detection
                with patch.object(coordinator, "_correlate_device_data") as mock_correlate:
                    enriched_devices = wifi_devices.copy()
                    enriched_devices[0].update(dhcp_data["AA:BB:CC:DD:EE:FF"])
                    mock_correlate.return_value = enriched_devices

                    with patch.object(coordinator, "_update_roaming_detection"):
                        with patch.object(coordinator, "_extract_ssid_data") as mock_ssid:
                            mock_ssid.return_value = {}

                            result = await coordinator._async_update_data()

        assert "devices" in result
        assert "system_info" in result
        assert "interfaces" in result
        assert "ssids" in result
        assert "routers" in result
        assert "last_update" in result
        assert "total_devices" in result

    async def test_async_update_data_auth_failure(self, coordinator):
        """Test data update with authentication failure."""
        with patch.object(coordinator, "_authenticate_router") as mock_auth:
            mock_auth.side_effect = [Exception("Auth failed"), Exception("Auth failed")]

            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    async def test_async_update_data_partial_auth_success(self, coordinator):
        """Test data update with partial authentication success."""
        coordinator.sessions = {"192.168.1.1": "session1"}

        with patch.object(coordinator, "_authenticate_router") as mock_auth:
            mock_auth.side_effect = ["session1", Exception("Auth failed for second")]

            with patch.object(coordinator, "_collect_router_data") as mock_collect:
                mock_collect.return_value = ([], {}, {}, {})

                with patch.object(coordinator, "_correlate_device_data") as mock_correlate:
                    mock_correlate.return_value = []

                    with patch.object(coordinator, "_update_roaming_detection"):
                        with patch.object(coordinator, "_extract_ssid_data") as mock_ssid:
                            mock_ssid.return_value = {}

                            result = await coordinator._async_update_data()

        assert result is not None
        assert len(result["routers"]) == 1

    async def test_authenticate_router_success(self, coordinator):
        """Test successful router authentication."""
        mock_client = coordinator.routers["192.168.1.1"]
        mock_client.authenticate.return_value = "test-session-id"

        result = await coordinator._authenticate_router("192.168.1.1", mock_client)

        assert result == "test-session-id"

    async def test_authenticate_router_failure(self, coordinator):
        """Test router authentication failure."""
        mock_client = coordinator.routers["192.168.1.1"]
        mock_client.authenticate.return_value = None

        with pytest.raises(UpdateFailed):
            await coordinator._authenticate_router("192.168.1.1", mock_client)

    async def test_authenticate_router_exception(self, coordinator):
        """Test router authentication with exception."""
        mock_client = coordinator.routers["192.168.1.1"]
        mock_client.authenticate.side_effect = UbusClientError("Connection failed")

        with pytest.raises(UpdateFailed):
            await coordinator._authenticate_router("192.168.1.1", mock_client)


class TestDataCollection:
    """Test data collection methods."""

    async def test_collect_router_data_success(self, coordinator):
        """Test successful data collection from router."""
        mock_client = coordinator.routers["192.168.1.1"]

        # Mock all the client methods
        mock_client.get_wireless_devices.return_value = ["wlan0", "wlan1"]
        mock_client.get_device_associations.return_value = [
            {"mac": "aa:bb:cc:dd:ee:ff", "signal": -45}
        ]
        mock_client.get_system_info.return_value = {"hostname": "test-router"}
        mock_client.get_system_board.return_value = {"model": "test-model"}
        mock_client.get_network_interfaces.return_value = {"eth0": {"status": "up"}}
        mock_client.get_wireless_status.return_value = {"radio0": {"status": "up"}}
        mock_client.get_dhcp_leases.return_value = {"dhcp_leases": []}
        mock_client.get_static_dhcp_hosts.return_value = None

        with patch.object(coordinator, "_parse_dhcp_data") as mock_parse:
            mock_parse.return_value = {}

            wifi_devices, dhcp_data, system_data, interface_data = (
                await coordinator._collect_router_data("192.168.1.1", "test-session")
            )

        assert len(wifi_devices) == 2  # 2 interfaces
        assert wifi_devices[0][ATTR_MAC] == "AA:BB:CC:DD:EE:FF"
        assert wifi_devices[0][ATTR_SIGNAL_DBM] == -45
        assert wifi_devices[0][ATTR_ROUTER] == "192.168.1.1"
        assert system_data["hostname"] == "test-router"
        assert system_data["model"] == "test-model"

    async def test_collect_router_data_no_interfaces(self, coordinator):
        """Test data collection with no wireless interfaces."""
        mock_client = coordinator.routers["192.168.1.1"]

        mock_client.get_wireless_devices.return_value = []
        mock_client.get_system_info.return_value = None
        mock_client.get_system_board.return_value = None
        mock_client.get_network_interfaces.return_value = None
        mock_client.get_wireless_status.return_value = None
        mock_client.get_dhcp_leases.return_value = None
        mock_client.get_static_dhcp_hosts.return_value = None

        wifi_devices, dhcp_data, system_data, interface_data = (
            await coordinator._collect_router_data("192.168.1.1", "test-session")
        )

        assert wifi_devices == []
        assert dhcp_data == {}
        assert system_data == {}
        assert interface_data == {}

    async def test_collect_router_data_wireless_status_failure(self, coordinator):
        """Test data collection when wireless status fails."""
        mock_client = coordinator.routers["192.168.1.1"]

        mock_client.get_wireless_devices.return_value = ["wlan0"]
        mock_client.get_device_associations.return_value = []
        mock_client.get_system_info.return_value = None
        mock_client.get_system_board.return_value = None
        mock_client.get_network_interfaces.return_value = None
        mock_client.get_wireless_status.return_value = None  # Failure case
        mock_client.get_dhcp_leases.return_value = None
        mock_client.get_static_dhcp_hosts.return_value = None

        wifi_devices, dhcp_data, system_data, interface_data = (
            await coordinator._collect_router_data("192.168.1.1", "test-session")
        )

        # Should still work but log warnings
        assert wifi_devices == []
        assert interface_data == {}

    async def test_collect_router_data_exception(self, coordinator):
        """Test data collection with exception."""
        mock_client = coordinator.routers["192.168.1.1"]
        mock_client.get_wireless_devices.side_effect = Exception("Connection failed")

        with pytest.raises(UpdateFailed):
            await coordinator._collect_router_data("192.168.1.1", "test-session")


class TestDHCPParsing:
    """Test DHCP data parsing."""

    def test_parse_dhcp_data_luci_rpc_format(self, coordinator):
        """Test parsing DHCP data in luci-rpc format."""
        dhcp_leases = {
            "dhcp_leases": [
                {"macaddr": "aa:bb:cc:dd:ee:ff", "ipaddr": "192.168.1.100", "hostname": "device1"}
            ]
        }
        static_hosts = None

        result = coordinator._parse_dhcp_data(dhcp_leases, static_hosts)

        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_IP] == "192.168.1.100"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_HOSTNAME] == "device1"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_DATA_SOURCE] == DATA_SOURCE_DYNAMIC_DHCP

    def test_parse_dhcp_data_standard_format(self, coordinator):
        """Test parsing DHCP data in standard format."""
        dhcp_leases = {
            "device": {
                "leases": [
                    {
                        "macaddr": "aa:bb:cc:dd:ee:ff",
                        "ipaddr": "192.168.1.101",
                        "hostname": "device2",
                    }
                ]
            }
        }
        static_hosts = None

        result = coordinator._parse_dhcp_data(dhcp_leases, static_hosts)

        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_IP] == "192.168.1.101"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_HOSTNAME] == "device2"

    def test_parse_dhcp_data_static_hosts(self, coordinator):
        """Test parsing static DHCP hosts."""
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
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_DATA_SOURCE] == DATA_SOURCE_STATIC_DHCP

    def test_parse_dhcp_data_empty(self, coordinator):
        """Test parsing empty DHCP data."""
        result = coordinator._parse_dhcp_data(None, None)
        assert result == {}


class TestDeviceCorrelation:
    """Test device data correlation."""

    def test_correlate_device_data_with_dhcp(self, coordinator):
        """Test device correlation with DHCP data."""
        wifi_devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_INTERFACE: "wlan0",
                ATTR_SIGNAL_DBM: -45,
                ATTR_ROUTER: "192.168.1.1",
                ATTR_CONNECTED: True,
                ATTR_LAST_SEEN: datetime.now(),
            }
        ]
        dhcp_data = {
            "AA:BB:CC:DD:EE:FF": {
                ATTR_IP: "192.168.1.100",
                ATTR_HOSTNAME: "test-device",
                ATTR_DATA_SOURCE: DATA_SOURCE_DYNAMIC_DHCP,
            }
        }

        with patch.object(coordinator.device_manager, "identify_device") as mock_identify:
            mock_identify.return_value = {"vendor": "Test Vendor", "device_type": "phone"}

            with patch.object(coordinator, "_determine_vlan") as mock_vlan:
                mock_vlan.return_value = 1

                result = coordinator._correlate_device_data(wifi_devices, dhcp_data)

        assert len(result) == 1
        device = result[0]
        assert device[ATTR_IP] == "192.168.1.100"
        assert device[ATTR_HOSTNAME] == "test-device"
        assert device[ATTR_DATA_SOURCE] == DATA_SOURCE_DYNAMIC_DHCP
        assert device[ATTR_VENDOR] == "Test Vendor"
        assert device[ATTR_DEVICE_TYPE] == "phone"
        assert device[ATTR_VLAN_ID] == 1

    def test_correlate_device_data_wifi_only(self, coordinator):
        """Test device correlation with WiFi data only."""
        wifi_devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_INTERFACE: "wlan0",
                ATTR_SIGNAL_DBM: -45,
                ATTR_ROUTER: "192.168.1.1",
                ATTR_CONNECTED: True,
                ATTR_LAST_SEEN: datetime.now(),
            }
        ]
        dhcp_data = {}

        with patch.object(coordinator.device_manager, "identify_device") as mock_identify:
            mock_identify.return_value = None

            with patch.object(coordinator, "_determine_vlan") as mock_vlan:
                mock_vlan.return_value = 1

                result = coordinator._correlate_device_data(wifi_devices, dhcp_data)

        assert len(result) == 1
        device = result[0]
        assert device[ATTR_DATA_SOURCE] == DATA_SOURCE_WIFI_ONLY
        assert ATTR_IP not in device
        assert ATTR_HOSTNAME not in device


class TestVLANDetermination:
    """Test VLAN determination logic."""

    def test_determine_vlan_from_interface_vlan_tag(self, coordinator):
        """Test VLAN determination from interface VLAN tag."""
        device = {ATTR_INTERFACE: "wlan0-vlan10"}

        result = coordinator._determine_vlan(device)

        assert result == 10

    def test_determine_vlan_from_interface_keywords(self, coordinator):
        """Test VLAN determination from interface keywords."""
        test_cases = [
            ({"interface": "wlan0-iot"}, 3),
            ({"interface": "wlan1-guest"}, 100),
            ({"interface": "wlan0-main"}, 1),
            ({"interface": "phy0-ap1"}, 10),
            ({"interface": "phy0-ap2"}, 100),
            ({"interface": "phy0-ap0"}, 1),
        ]

        for device, expected_vlan in test_cases:
            result = coordinator._determine_vlan({ATTR_INTERFACE: device["interface"]})
            assert result == expected_vlan

    def test_determine_vlan_from_ip_subnet(self, coordinator):
        """Test VLAN determination from IP subnet."""
        device = {ATTR_IP: "192.168.10.100"}

        result = coordinator._determine_vlan(device)

        assert result == 10

    def test_determine_vlan_default(self, coordinator):
        """Test VLAN determination default case."""
        device = {ATTR_INTERFACE: "wlan0", ATTR_IP: "10.0.0.100"}

        result = coordinator._determine_vlan(device)

        assert result == 1


class TestRoamingDetection:
    """Test roaming detection functionality."""

    def test_update_roaming_detection_single_device(self, coordinator):
        """Test roaming detection with single device on one router."""
        devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_ROUTER: "192.168.1.1",
                ATTR_SIGNAL_DBM: -45,
            }
        ]

        coordinator._update_roaming_detection(devices)

        device = devices[0]
        assert device[ATTR_PRIMARY_AP] == "192.168.1.1"
        assert device[ATTR_ROAMING_COUNT] == 0

    def test_update_roaming_detection_multiple_routers(self, coordinator):
        """Test roaming detection with device on multiple routers."""
        devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_ROUTER: "192.168.1.1",
                ATTR_SIGNAL_DBM: -45,
            },
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_ROUTER: "192.168.1.2",
                ATTR_SIGNAL_DBM: -60,
            },
        ]

        coordinator._update_roaming_detection(devices)

        # Device should be assigned to router with stronger signal
        for device in devices:
            assert device[ATTR_PRIMARY_AP] == "192.168.1.1"
            assert device[ATTR_ROAMING_COUNT] == 0

    def test_update_roaming_detection_roaming_event(self, coordinator):
        """Test roaming detection with actual roaming event."""
        # Set up previous state
        coordinator._device_history = {
            "AA:BB:CC:DD:EE:FF": {
                ATTR_PRIMARY_AP: "192.168.1.2",
                ATTR_ROAMING_COUNT: 1,
                "last_change": datetime.now() - timedelta(seconds=ROAMING_DETECTION_THRESHOLD + 10),
            }
        }

        devices = [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_ROUTER: "192.168.1.1",
                ATTR_SIGNAL_DBM: -45,
            }
        ]

        coordinator._update_roaming_detection(devices)

        device = devices[0]
        assert device[ATTR_PRIMARY_AP] == "192.168.1.1"
        assert device[ATTR_ROAMING_COUNT] == 2  # Incremented due to roaming


class TestUtilityMethods:
    """Test utility methods."""

    async def test_async_shutdown(self, coordinator):
        """Test coordinator shutdown."""
        mock_client1 = coordinator.routers["192.168.1.1"]
        mock_client2 = coordinator.routers["192.168.1.2"]

        await coordinator.async_shutdown()

        mock_client1.close.assert_called_once()
        mock_client2.close.assert_called_once()

    def test_get_device_by_mac_found(self, coordinator):
        """Test getting device by MAC address when found."""
        coordinator.data = {
            "devices": [
                {ATTR_MAC: "AA:BB:CC:DD:EE:FF", ATTR_HOSTNAME: "device1"},
                {ATTR_MAC: "11:22:33:44:55:66", ATTR_HOSTNAME: "device2"},
            ]
        }

        device = coordinator.get_device_by_mac("aa:bb:cc:dd:ee:ff")

        assert device is not None
        assert device[ATTR_HOSTNAME] == "device1"

    def test_get_device_by_mac_not_found(self, coordinator):
        """Test getting device by MAC address when not found."""
        coordinator.data = {"devices": []}

        device = coordinator.get_device_by_mac("aa:bb:cc:dd:ee:ff")

        assert device is None

    def test_get_device_by_mac_no_data(self, coordinator):
        """Test getting device by MAC address with no data."""
        coordinator.data = None

        device = coordinator.get_device_by_mac("aa:bb:cc:dd:ee:ff")

        assert device is None

    def test_get_devices_by_router(self, coordinator):
        """Test getting devices by router."""
        coordinator.data = {
            "devices": [
                {ATTR_ROUTER: "192.168.1.1", ATTR_HOSTNAME: "device1"},
                {ATTR_ROUTER: "192.168.1.2", ATTR_HOSTNAME: "device2"},
                {ATTR_ROUTER: "192.168.1.1", ATTR_HOSTNAME: "device3"},
            ]
        }

        devices = coordinator.get_devices_by_router("192.168.1.1")

        assert len(devices) == 2
        assert devices[0][ATTR_HOSTNAME] == "device1"
        assert devices[1][ATTR_HOSTNAME] == "device3"

    def test_get_devices_by_router_no_data(self, coordinator):
        """Test getting devices by router with no data."""
        coordinator.data = None

        devices = coordinator.get_devices_by_router("192.168.1.1")

        assert devices == []

    def test_sanitize_config(self):
        """Test config sanitization."""
        config = {
            "ssid": "MyNetwork",
            "key": "secret_password",
            "wpa_passphrase": "another_secret",
            "wpa_psk": "psk_secret",
            "password": "admin_pass",
            "channel": 6,
            "encryption": "psk2",
            "other_field": None,
        }

        result = WrtManagerCoordinator._sanitize_config(config)

        assert result["ssid"] == "MyNetwork"
        assert result["key"] == "***REDACTED***"
        assert result["wpa_passphrase"] == "***REDACTED***"
        assert result["wpa_psk"] == "***REDACTED***"
        assert result["password"] == "***REDACTED***"
        assert result["channel"] == 6
        assert result["encryption"] == "psk2"
        assert result["other_field"] is None  # None values preserved


class TestSSIDExtraction:
    """Test SSID data extraction."""

    def test_extract_ssid_data_success(self, coordinator):
        """Test successful SSID data extraction."""
        interfaces = {
            "192.168.1.1": {
                "radio0": {
                    "interfaces": [
                        {
                            "config": {
                                "ssid": "TestNetwork",
                                "mode": "ap",
                                "encryption": "psk2",
                                "key": "secret123",
                                "disabled": False,
                                "hidden": False,
                                "isolate": False,
                                "network": "lan",
                            },
                            "ifname": "wlan0",
                        }
                    ]
                }
            }
        }

        with patch.object(coordinator, "_consolidate_ssids_by_name") as mock_consolidate:
            mock_consolidate.return_value = interfaces

            coordinator._extract_ssid_data(interfaces)

        mock_consolidate.assert_called_once()

    def test_extract_ssid_data_no_wireless_data(self, coordinator):
        """Test SSID extraction with no wireless data."""
        interfaces = {"192.168.1.1": {"eth0": {"status": "up"}}}  # No wireless interfaces

        result = coordinator._extract_ssid_data(interfaces)

        assert result == {}

    def test_consolidate_ssids_by_name_single_radio(self, coordinator):
        """Test SSID consolidation with single radio."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_interface": "interface_0",
                    "ssid_name": "TestNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "router_host": "192.168.1.1",
                }
            ]
        }

        result = coordinator._consolidate_ssids_by_name(ssid_data)

        assert "192.168.1.1" in result
        assert len(result["192.168.1.1"]) == 1
        assert result["192.168.1.1"][0]["ssid_name"] == "TestNetwork"

    def test_consolidate_ssids_by_name_multi_radio(self, coordinator):
        """Test SSID consolidation with multiple radios."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_interface": "interface_0",
                    "ssid_name": "TestNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "router_host": "192.168.1.1",
                },
                {
                    "radio": "radio1",
                    "ssid_interface": "interface_1",
                    "ssid_name": "TestNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "router_host": "192.168.1.1",
                },
            ]
        }

        result = coordinator._consolidate_ssids_by_name(ssid_data)

        assert "192.168.1.1" in result
        assert len(result["192.168.1.1"]) == 1
        consolidated_ssid = result["192.168.1.1"][0]
        assert consolidated_ssid["ssid_name"] == "TestNetwork"
        assert consolidated_ssid["is_consolidated"] is True
        assert consolidated_ssid["radio_count"] == 2
        assert "radio0" in consolidated_ssid["radios"]
        assert "radio1" in consolidated_ssid["radios"]

    def test_get_frequency_bands(self, coordinator):
        """Test frequency band detection."""
        result = coordinator._get_frequency_bands(["radio0", "radio1", "radio2"])

        assert result == ["2.4GHz", "5GHz", "Unknown"]
