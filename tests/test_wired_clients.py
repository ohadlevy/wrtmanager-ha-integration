"""Tests for connection_type attribute on WiFi devices."""

from unittest.mock import Mock

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


def _make_coordinator_mock():
    """Create a mock coordinator with device_manager."""
    coordinator = Mock()
    coordinator.device_manager = Mock()
    coordinator.device_manager.identify_device = Mock(return_value=None)
    return coordinator


def test_wifi_devices_tagged_with_connection_type():
    """Test that all WiFi devices get connection_type=wifi."""
    coordinator = _make_coordinator_mock()

    wifi_devices = [
        {
            "mac_address": "AA:BB:CC:DD:EE:01",
            "interface": "phy0-ap0",
            "router": "10.0.0.1",
            "connected": True,
        },
        {
            "mac_address": "AA:BB:CC:DD:EE:02",
            "interface": "phy1-ap0",
            "router": "10.0.0.1",
            "connected": True,
        },
    ]

    result = WrtManagerCoordinator._correlate_device_data(coordinator, wifi_devices, {})

    assert all(d["connection_type"] == "wifi" for d in result)


def test_connection_type_present_with_dhcp_merge():
    """Test that connection_type is set even when DHCP data is merged."""
    coordinator = _make_coordinator_mock()

    wifi_devices = [
        {
            "mac_address": "AA:BB:CC:DD:EE:01",
            "interface": "phy0-ap0",
            "router": "10.0.0.1",
            "connected": True,
        }
    ]
    dhcp_data = {
        "AA:BB:CC:DD:EE:01": {
            "ip_address": "10.0.0.100",
            "hostname": "my-phone",
            "data_source": "dynamic_dhcp",
        },
    }

    result = WrtManagerCoordinator._correlate_device_data(coordinator, wifi_devices, dhcp_data)

    assert len(result) == 1
    assert result[0]["connection_type"] == "wifi"
    assert result[0]["ip_address"] == "10.0.0.100"


def test_unmatched_dhcp_entries_not_created_as_devices():
    """Test that DHCP entries not in WiFi assoclist are NOT created as devices.

    Wired client detection is deferred to ARP-based approach (#116).
    """
    coordinator = _make_coordinator_mock()

    wifi_devices = [
        {
            "mac_address": "AA:BB:CC:DD:EE:01",
            "interface": "phy0-ap0",
            "router": "10.0.0.1",
            "connected": True,
        }
    ]
    dhcp_data = {
        "AA:BB:CC:DD:EE:01": {
            "ip_address": "10.0.0.100",
            "hostname": "wifi-phone",
            "data_source": "dynamic_dhcp",
        },
        "AA:BB:CC:DD:EE:02": {
            "ip_address": "10.0.0.101",
            "hostname": "wired-printer",
            "data_source": "dynamic_dhcp",
        },
    }

    result = WrtManagerCoordinator._correlate_device_data(coordinator, wifi_devices, dhcp_data)

    # Only the WiFi device should be in results
    assert len(result) == 1
    assert result[0]["mac_address"] == "AA:BB:CC:DD:EE:01"
