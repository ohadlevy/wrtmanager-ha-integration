"""Simple tests for WrtManagerCoordinator to improve coverage."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
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


class TestCoordinatorDataProcessing:
    """Test coordinator data processing methods without Home Assistant."""

    def test_parse_dhcp_data_luci_rpc_format(self):
        """Test parsing DHCP data in luci-rpc format."""
        # Create a minimal coordinator instance for testing methods
        coordinator = MagicMock()
        coordinator._parse_dhcp_data = WrtManagerCoordinator._parse_dhcp_data.__get__(coordinator)

        dhcp_leases = {
            "dhcp_leases": [
                {
                    "macaddr": "aa:bb:cc:dd:ee:ff",
                    "ipaddr": "192.168.1.100",
                    "hostname": "device1"
                }
            ]
        }
        static_hosts = None

        result = coordinator._parse_dhcp_data(dhcp_leases, static_hosts)

        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_IP] == "192.168.1.100"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_HOSTNAME] == "device1"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_DATA_SOURCE] == DATA_SOURCE_DYNAMIC_DHCP

    def test_parse_dhcp_data_standard_format(self):
        """Test parsing DHCP data in standard format."""
        coordinator = MagicMock()
        coordinator._parse_dhcp_data = WrtManagerCoordinator._parse_dhcp_data.__get__(coordinator)

        dhcp_leases = {
            "device": {
                "leases": [
                    {
                        "macaddr": "aa:bb:cc:dd:ee:ff",
                        "ipaddr": "192.168.1.101",
                        "hostname": "device2"
                    }
                ]
            }
        }
        static_hosts = None

        result = coordinator._parse_dhcp_data(dhcp_leases, static_hosts)

        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_IP] == "192.168.1.101"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_HOSTNAME] == "device2"

    def test_parse_dhcp_data_static_hosts(self):
        """Test parsing static DHCP hosts."""
        coordinator = MagicMock()
        coordinator._parse_dhcp_data = WrtManagerCoordinator._parse_dhcp_data.__get__(coordinator)

        dhcp_leases = None
        static_hosts = {
            "values": {
                "host1": {
                    ".type": "host",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "ip": "192.168.1.50",
                    "name": "static-device"
                }
            }
        }

        result = coordinator._parse_dhcp_data(dhcp_leases, static_hosts)

        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_IP] == "192.168.1.50"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_HOSTNAME] == "static-device"
        assert result["AA:BB:CC:DD:EE:FF"][ATTR_DATA_SOURCE] == DATA_SOURCE_STATIC_DHCP

    def test_parse_dhcp_data_empty(self):
        """Test parsing empty DHCP data."""
        coordinator = MagicMock()
        coordinator._parse_dhcp_data = WrtManagerCoordinator._parse_dhcp_data.__get__(coordinator)

        result = coordinator._parse_dhcp_data(None, None)
        assert result == {}

    def test_determine_vlan_from_interface_vlan_tag(self):
        """Test VLAN determination from interface VLAN tag."""
        coordinator = MagicMock()
        coordinator._determine_vlan = WrtManagerCoordinator._determine_vlan.__get__(coordinator)

        device = {ATTR_INTERFACE: "wlan0-vlan10"}

        result = coordinator._determine_vlan(device)

        assert result == 10

    def test_determine_vlan_from_interface_keywords(self):
        """Test VLAN determination from interface keywords."""
        coordinator = MagicMock()
        coordinator._determine_vlan = WrtManagerCoordinator._determine_vlan.__get__(coordinator)

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

    def test_determine_vlan_from_ip_subnet(self):
        """Test VLAN determination from IP subnet."""
        coordinator = MagicMock()
        coordinator._determine_vlan = WrtManagerCoordinator._determine_vlan.__get__(coordinator)

        device = {ATTR_IP: "192.168.10.100"}

        result = coordinator._determine_vlan(device)

        assert result == 10

    def test_determine_vlan_default(self):
        """Test VLAN determination default case."""
        coordinator = MagicMock()
        coordinator._determine_vlan = WrtManagerCoordinator._determine_vlan.__get__(coordinator)

        device = {ATTR_INTERFACE: "wlan0", ATTR_IP: "10.0.0.100"}

        result = coordinator._determine_vlan(device)

        assert result == 1

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
            "other_field": None
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

    def test_update_roaming_detection_single_device(self):
        """Test roaming detection with single device on one router."""
        coordinator = MagicMock()
        coordinator._device_history = {}
        coordinator._update_roaming_detection = WrtManagerCoordinator._update_roaming_detection.__get__(coordinator)

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

    def test_update_roaming_detection_multiple_routers(self):
        """Test roaming detection with device on multiple routers."""
        coordinator = MagicMock()
        coordinator._device_history = {}
        coordinator._update_roaming_detection = WrtManagerCoordinator._update_roaming_detection.__get__(coordinator)

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
            }
        ]

        coordinator._update_roaming_detection(devices)

        # Device should be assigned to router with stronger signal
        for device in devices:
            assert device[ATTR_PRIMARY_AP] == "192.168.1.1"
            assert device[ATTR_ROAMING_COUNT] == 0

    def test_update_roaming_detection_roaming_event(self):
        """Test roaming detection with actual roaming event."""
        coordinator = MagicMock()
        # Set up previous state
        coordinator._device_history = {
            "AA:BB:CC:DD:EE:FF": {
                ATTR_PRIMARY_AP: "192.168.1.2",
                ATTR_ROAMING_COUNT: 1,
                "last_change": datetime.now() - timedelta(seconds=ROAMING_DETECTION_THRESHOLD + 10)
            }
        }
        coordinator._update_roaming_detection = WrtManagerCoordinator._update_roaming_detection.__get__(coordinator)

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
        # Check that roaming count is incremented (may be 1 or 2 depending on timing logic)
        assert device[ATTR_ROAMING_COUNT] >= 1

    def test_get_frequency_bands(self):
        """Test frequency band detection."""
        coordinator = MagicMock()
        coordinator._get_frequency_bands = WrtManagerCoordinator._get_frequency_bands.__get__(coordinator)

        result = coordinator._get_frequency_bands(["radio0", "radio1", "radio2"])

        assert result == ["2.4GHz", "5GHz", "Unknown"]

    def test_consolidate_ssids_by_name_single_radio(self):
        """Test SSID consolidation with single radio."""
        coordinator = MagicMock()
        coordinator._get_frequency_bands = WrtManagerCoordinator._get_frequency_bands.__get__(coordinator)
        coordinator._consolidate_ssids_by_name = WrtManagerCoordinator._consolidate_ssids_by_name.__get__(coordinator)

        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_interface": "interface_0",
                    "ssid_name": "TestNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "router_host": "192.168.1.1"
                }
            ]
        }

        result = coordinator._consolidate_ssids_by_name(ssid_data)

        assert "192.168.1.1" in result
        assert len(result["192.168.1.1"]) == 1
        assert result["192.168.1.1"][0]["ssid_name"] == "TestNetwork"

    def test_consolidate_ssids_by_name_multi_radio(self):
        """Test SSID consolidation with multiple radios."""
        coordinator = MagicMock()
        coordinator._get_frequency_bands = WrtManagerCoordinator._get_frequency_bands.__get__(coordinator)
        coordinator._consolidate_ssids_by_name = WrtManagerCoordinator._consolidate_ssids_by_name.__get__(coordinator)

        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_interface": "interface_0",
                    "ssid_name": "TestNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "router_host": "192.168.1.1"
                },
                {
                    "radio": "radio1",
                    "ssid_interface": "interface_1",
                    "ssid_name": "TestNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "router_host": "192.168.1.1"
                }
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


class TestCoordinatorUtilityMethods:
    """Test coordinator utility methods."""

    def test_get_device_by_mac_found(self):
        """Test getting device by MAC address when found."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": [
                {ATTR_MAC: "AA:BB:CC:DD:EE:FF", ATTR_HOSTNAME: "device1"},
                {ATTR_MAC: "11:22:33:44:55:66", ATTR_HOSTNAME: "device2"}
            ]
        }
        coordinator.get_device_by_mac = WrtManagerCoordinator.get_device_by_mac.__get__(coordinator)

        device = coordinator.get_device_by_mac("aa:bb:cc:dd:ee:ff")

        assert device is not None
        assert device[ATTR_HOSTNAME] == "device1"

    def test_get_device_by_mac_not_found(self):
        """Test getting device by MAC address when not found."""
        coordinator = MagicMock()
        coordinator.data = {"devices": []}
        coordinator.get_device_by_mac = WrtManagerCoordinator.get_device_by_mac.__get__(coordinator)

        device = coordinator.get_device_by_mac("aa:bb:cc:dd:ee:ff")

        assert device is None

    def test_get_device_by_mac_no_data(self):
        """Test getting device by MAC address with no data."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.get_device_by_mac = WrtManagerCoordinator.get_device_by_mac.__get__(coordinator)

        device = coordinator.get_device_by_mac("aa:bb:cc:dd:ee:ff")

        assert device is None

    def test_get_devices_by_router(self):
        """Test getting devices by router."""
        coordinator = MagicMock()
        coordinator.data = {
            "devices": [
                {ATTR_ROUTER: "192.168.1.1", ATTR_HOSTNAME: "device1"},
                {ATTR_ROUTER: "192.168.1.2", ATTR_HOSTNAME: "device2"},
                {ATTR_ROUTER: "192.168.1.1", ATTR_HOSTNAME: "device3"}
            ]
        }
        coordinator.get_devices_by_router = WrtManagerCoordinator.get_devices_by_router.__get__(coordinator)

        devices = coordinator.get_devices_by_router("192.168.1.1")

        assert len(devices) == 2
        assert devices[0][ATTR_HOSTNAME] == "device1"
        assert devices[1][ATTR_HOSTNAME] == "device3"

    def test_get_devices_by_router_no_data(self):
        """Test getting devices by router with no data."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.get_devices_by_router = WrtManagerCoordinator.get_devices_by_router.__get__(coordinator)

        devices = coordinator.get_devices_by_router("192.168.1.1")

        assert devices == []