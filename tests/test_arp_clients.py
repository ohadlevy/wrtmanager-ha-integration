"""Tests for ARP-based wired client detection via luci-rpc.getHostHints."""

from unittest.mock import Mock

from custom_components.wrtmanager.const import (
    ATTR_CONNECTION_TYPE,
    ATTR_DATA_SOURCE,
    ATTR_HOSTNAME,
    ATTR_IP,
    ATTR_MAC,
    ATTR_NETWORK_NAME,
    CONNECTION_TYPE_WIRED,
    DATA_SOURCE_DYNAMIC_DHCP,
    DATA_SOURCE_LIVE_ARP,
    DATA_SOURCE_STATIC_DHCP,
)
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


def _make_coordinator_mock():
    """Create a mock coordinator with device_manager."""
    coordinator = Mock()
    coordinator.device_manager = Mock()
    coordinator.device_manager.identify_device = Mock(return_value=None)
    return coordinator


# ip_map matching what coordinator builds from interface dump
LAN_IP_MAP = {
    "br-lan": {"ip": "192.168.1.1/24", "logical": "lan"},
    "br-iot": {"ip": "192.168.5.1/24", "logical": "iot"},
}


def test_build_wired_from_host_hints():
    """Basic: hints entry with IP becomes wired device."""
    coordinator = _make_coordinator_mock()
    host_hints = {
        "B8:27:EB:00:00:01": {"name": "nas", "ipaddrs": ["192.168.1.50"], "ip6addrs": []},
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, set(), {}, LAN_IP_MAP
    )
    assert len(result) == 1
    assert result[0][ATTR_MAC] == "B8:27:EB:00:00:01"
    assert result[0][ATTR_IP] == "192.168.1.50"


def test_build_wired_excludes_wifi_macs():
    """MAC in wifi_mac_set is not in wired output."""
    coordinator = _make_coordinator_mock()
    host_hints = {
        "AA:BB:CC:DD:EE:01": {"name": "phone", "ipaddrs": ["192.168.1.100"], "ip6addrs": []},
        "AA:BB:CC:DD:EE:02": {"name": "nas", "ipaddrs": ["192.168.1.50"], "ip6addrs": []},
    }
    wifi_mac_set = {"AA:BB:CC:DD:EE:01"}
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, wifi_mac_set, {}, LAN_IP_MAP
    )
    assert len(result) == 1
    assert result[0][ATTR_MAC] == "AA:BB:CC:DD:EE:02"


def test_build_wired_sets_connection_type():
    """All wired devices have connection_type=wired."""
    coordinator = _make_coordinator_mock()
    host_hints = {
        "AA:BB:CC:DD:EE:01": {"name": "dev1", "ipaddrs": ["192.168.1.10"], "ip6addrs": []},
        "AA:BB:CC:DD:EE:02": {"name": "dev2", "ipaddrs": ["192.168.1.20"], "ip6addrs": []},
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, set(), {}, LAN_IP_MAP
    )
    assert all(d[ATTR_CONNECTION_TYPE] == CONNECTION_TYPE_WIRED for d in result)


def test_ip_to_network_lan():
    """192.168.1.x IP matches lan subnet."""
    subnets = WrtManagerCoordinator._build_subnet_map(LAN_IP_MAP)
    result = WrtManagerCoordinator._ip_to_network("192.168.1.50", subnets)
    assert result == "lan"


def test_ip_to_network_iot():
    """192.168.5.x IP matches iot subnet."""
    subnets = WrtManagerCoordinator._build_subnet_map(LAN_IP_MAP)
    result = WrtManagerCoordinator._ip_to_network("192.168.5.100", subnets)
    assert result == "iot"


def test_build_subnet_map_longest_prefix():
    """More specific subnet wins over broader one."""
    ip_map = {
        "br-lan": {"ip": "192.168.1.0/24", "logical": "lan"},
        "br-mgmt": {"ip": "192.168.1.128/25", "logical": "mgmt"},
    }
    subnets = WrtManagerCoordinator._build_subnet_map(ip_map)
    result = WrtManagerCoordinator._ip_to_network("192.168.1.200", subnets)
    assert result == "mgmt"


def test_build_wired_enriches_from_dhcp():
    """MAC in dhcp_data: DHCP hostname used, data_source from DHCP."""
    coordinator = _make_coordinator_mock()
    host_hints = {
        "AA:BB:CC:DD:EE:01": {"name": "hints-name", "ipaddrs": ["192.168.1.100"], "ip6addrs": []},
    }
    dhcp_data = {
        "AA:BB:CC:DD:EE:01": {
            ATTR_IP: "192.168.1.100",
            ATTR_HOSTNAME: "dhcp-name",
            ATTR_DATA_SOURCE: DATA_SOURCE_DYNAMIC_DHCP,
        }
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, set(), dhcp_data, LAN_IP_MAP
    )
    assert len(result) == 1
    assert result[0][ATTR_HOSTNAME] == "dhcp-name"
    assert result[0][ATTR_DATA_SOURCE] == DATA_SOURCE_DYNAMIC_DHCP


def test_build_wired_static_reservation_hostname_wins():
    """Static reservation name beats hints name."""
    coordinator = _make_coordinator_mock()
    host_hints = {
        "AA:BB:CC:DD:EE:01": {"name": "hints-name", "ipaddrs": ["192.168.1.10"], "ip6addrs": []},
    }
    dhcp_data = {
        "AA:BB:CC:DD:EE:01": {
            ATTR_IP: "192.168.1.10",
            ATTR_HOSTNAME: "static-name",
            ATTR_DATA_SOURCE: DATA_SOURCE_STATIC_DHCP,
        }
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, set(), dhcp_data, LAN_IP_MAP
    )
    assert result[0][ATTR_HOSTNAME] == "static-name"
    assert result[0][ATTR_DATA_SOURCE] == DATA_SOURCE_STATIC_DHCP


def test_build_wired_hints_only_device():
    """No dhcp_data match: hints name used, data_source=live_arp."""
    coordinator = _make_coordinator_mock()
    host_hints = {
        "B8:27:EB:00:00:01": {"name": "static-server", "ipaddrs": ["192.168.1.50"], "ip6addrs": []},
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, set(), {}, LAN_IP_MAP
    )
    assert result[0][ATTR_HOSTNAME] == "static-server"
    assert result[0][ATTR_DATA_SOURCE] == DATA_SOURCE_LIVE_ARP


def test_build_wired_skips_no_ip():
    """Entry with empty ipaddrs is skipped."""
    coordinator = _make_coordinator_mock()
    host_hints = {
        "AA:BB:CC:DD:EE:01": {"name": "no-ip", "ipaddrs": [], "ip6addrs": []},
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, set(), {}, LAN_IP_MAP
    )
    assert len(result) == 0


def test_no_duplicate_macs_in_output():
    """Full pipeline: WiFi + hints -> no MAC appears twice."""
    coordinator = _make_coordinator_mock()
    wifi_macs = {"9A:50:0E:F2:D4:45", "4E:5C:42:0D:BB:1D"}
    host_hints = {
        # These two are WiFi — should be excluded
        "9A:50:0E:F2:D4:45": {"name": "MacBookAir", "ipaddrs": ["192.168.1.195"], "ip6addrs": []},
        "4E:5C:42:0D:BB:1D": {"name": "iPhone-Tom", "ipaddrs": ["192.168.1.220"], "ip6addrs": []},
        # These two are wired-only
        "B8:27:EB:00:00:01": {"name": "", "ipaddrs": ["192.168.1.50"], "ip6addrs": []},
        "AA:BB:CC:00:00:01": {"name": "iot-sensor", "ipaddrs": ["192.168.5.100"], "ip6addrs": []},
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, wifi_macs, {}, LAN_IP_MAP
    )
    macs = [d[ATTR_MAC] for d in result]
    assert len(macs) == len(set(macs)), "Duplicate MACs found"
    assert "9A:50:0E:F2:D4:45" not in macs
    assert "4E:5C:42:0D:BB:1D" not in macs
    assert "B8:27:EB:00:00:01" in macs
    assert "AA:BB:CC:00:00:01" in macs


def test_build_wired_network_name_assigned():
    """Wired devices get the correct network_name from ip_map."""
    coordinator = _make_coordinator_mock()
    # Use real static methods so subnet matching works correctly
    coordinator._build_subnet_map = WrtManagerCoordinator._build_subnet_map
    coordinator._ip_to_network = WrtManagerCoordinator._ip_to_network
    host_hints = {
        "AA:BB:CC:00:00:01": {"name": "iot-sensor", "ipaddrs": ["192.168.5.100"], "ip6addrs": []},
    }
    result = WrtManagerCoordinator._build_wired_devices(
        coordinator, host_hints, set(), {}, LAN_IP_MAP
    )
    assert result[0][ATTR_NETWORK_NAME] == "iot"
