"""Tests for network detection from OpenWrt wireless status."""

from unittest.mock import Mock

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

# ─── _build_interface_network_map tests ───


def test_build_map_from_wireless_status():
    """Test building interface-to-network map from real wireless status data."""
    interfaces = {
        "10.0.0.1": {
            "radio0": {
                "interfaces": [
                    {
                        "ifname": "phy0-ap0",
                        "config": {"ssid": "MyWiFi", "network": ["lan"]},
                    },
                    {
                        "ifname": "phy0-ap1",
                        "config": {"ssid": "IoT", "network": ["iot"]},
                    },
                ],
            },
            "radio1": {
                "interfaces": [
                    {
                        "ifname": "phy1-ap0",
                        "config": {"ssid": "MyWiFi", "network": ["lan"]},
                    },
                ],
            },
            # Non-wireless interfaces should be skipped
            "br-lan": {"up": True, "mtu": 1500},
        },
    }

    result = WrtManagerCoordinator._build_interface_network_map(interfaces)

    assert result == {
        "10.0.0.1:phy0-ap0": "lan",
        "10.0.0.1:phy0-ap1": "iot",
        "10.0.0.1:phy1-ap0": "lan",
    }


def test_build_map_multiple_routers():
    """Test mapping across multiple routers."""
    interfaces = {
        "10.0.0.1": {
            "radio0": {
                "interfaces": [
                    {"ifname": "phy0-ap0", "config": {"network": ["lan"]}},
                ],
            },
        },
        "10.0.0.2": {
            "radio0": {
                "interfaces": [
                    {"ifname": "phy0-ap0", "config": {"network": ["lan"]}},
                    {"ifname": "phy0-ap1", "config": {"network": ["guest"]}},
                ],
            },
        },
    }

    result = WrtManagerCoordinator._build_interface_network_map(interfaces)

    assert result["10.0.0.1:phy0-ap0"] == "lan"
    assert result["10.0.0.2:phy0-ap0"] == "lan"
    assert result["10.0.0.2:phy0-ap1"] == "guest"


def test_build_map_network_as_string():
    """Test handling network as string instead of list."""
    interfaces = {
        "10.0.0.1": {
            "radio0": {
                "interfaces": [
                    {"ifname": "phy0-ap0", "config": {"network": "lan"}},
                ],
            },
        },
    }

    result = WrtManagerCoordinator._build_interface_network_map(interfaces)
    assert result["10.0.0.1:phy0-ap0"] == "lan"


def test_build_map_empty_interfaces():
    """Test with no wireless data."""
    result = WrtManagerCoordinator._build_interface_network_map({})
    assert result == {}


def test_build_map_skips_missing_ifname():
    """Test that entries without ifname are skipped."""
    interfaces = {
        "10.0.0.1": {
            "radio0": {
                "interfaces": [
                    {"config": {"network": ["lan"]}},  # No ifname
                ],
            },
        },
    }

    result = WrtManagerCoordinator._build_interface_network_map(interfaces)
    assert result == {}


def test_build_map_skips_missing_network():
    """Test that entries without network config are skipped."""
    interfaces = {
        "10.0.0.1": {
            "radio0": {
                "interfaces": [
                    {"ifname": "phy0-ap0", "config": {"ssid": "test"}},  # No network
                ],
            },
        },
    }

    result = WrtManagerCoordinator._build_interface_network_map(interfaces)
    assert result == {}


# ─── _correlate_device_data network enrichment tests ───


def test_correlate_sets_network_name():
    """Test that _correlate_device_data sets network_name from the map."""
    coordinator = Mock()
    coordinator.device_manager = Mock()
    coordinator.device_manager.identify_device = Mock(return_value=None)

    devices = [
        {
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "interface": "phy0-ap0",
            "router": "10.0.0.1",
        }
    ]
    interface_map = {"10.0.0.1:phy0-ap0": "iot"}

    result = WrtManagerCoordinator._correlate_device_data(coordinator, devices, {}, interface_map)

    assert result[0]["network_name"] == "iot"


def test_correlate_no_map_no_network_name():
    """Test that network_name is not set when no map is provided."""
    coordinator = Mock()
    coordinator.device_manager = Mock()
    coordinator.device_manager.identify_device = Mock(return_value=None)

    devices = [
        {
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "interface": "phy0-ap0",
            "router": "10.0.0.1",
        }
    ]

    result = WrtManagerCoordinator._correlate_device_data(coordinator, devices, {})

    assert result[0].get("network_name") is None
