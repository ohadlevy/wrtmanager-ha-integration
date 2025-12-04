"""Tests for network traffic sensors."""


def test_wan_interface_detection():
    """Test WAN/internet interface detection logic."""

    def is_wan_interface(interface_name):
        """Check if interface is a WAN/internet interface."""
        lower_name = interface_name.lower()
        wan_patterns = ["wan", "pppoe", "eth0.2", "eth1", "internet", "modem"]
        return any(pattern in lower_name for pattern in wan_patterns)

    # Test WAN interfaces
    assert is_wan_interface("pppoe-wan") is True
    assert is_wan_interface("eth0.2") is True
    assert is_wan_interface("eth1") is True
    assert is_wan_interface("wan") is True
    assert is_wan_interface("internet") is True
    assert is_wan_interface("modem0") is True

    # Test non-WAN interfaces
    assert is_wan_interface("br-lan") is False
    assert is_wan_interface("eth0") is False
    assert is_wan_interface("wlan0") is False
    assert is_wan_interface("phy0-ap0") is False


def test_interface_friendly_names():
    """Test interface friendly name generation."""

    def get_friendly_interface_name(interface_name):
        """Get a human-friendly interface name."""
        lower_name = interface_name.lower()

        # WAN/Internet interfaces
        if "pppoe" in lower_name:
            return f"{interface_name} (Internet)"
        elif "wan" in lower_name or "eth0.2" in lower_name or "eth1" in lower_name:
            return f"{interface_name} (WAN)"

        # Wireless interfaces
        if "phy" in lower_name and "ap" in lower_name:
            return f"{interface_name} (WiFi)"
        elif interface_name.startswith("wlan"):
            return f"{interface_name} (WiFi)"

        # Ethernet interfaces
        elif interface_name.startswith("eth"):
            return f"{interface_name} (Ethernet)"

        # Bridge interfaces
        elif interface_name.startswith("br-"):
            return f"{interface_name} (Bridge)"

        # Default
        return interface_name

    assert get_friendly_interface_name("pppoe-wan") == "pppoe-wan (Internet)"
    assert get_friendly_interface_name("eth0.2") == "eth0.2 (WAN)"
    assert get_friendly_interface_name("wan") == "wan (WAN)"
    assert get_friendly_interface_name("phy0-ap0") == "phy0-ap0 (WiFi)"
    assert get_friendly_interface_name("wlan0") == "wlan0 (WiFi)"
    assert get_friendly_interface_name("eth0") == "eth0 (Ethernet)"
    assert get_friendly_interface_name("br-lan") == "br-lan (Bridge)"


def test_traffic_data_conversion():
    """Test bytes to MB conversion for traffic sensors."""

    def bytes_to_mb(bytes_value):
        """Convert bytes to MB."""
        if bytes_value:
            return round(bytes_value / (1024 * 1024), 2)
        return 0

    # Test various byte values
    assert bytes_to_mb(0) == 0
    assert bytes_to_mb(1048576) == 1.0  # 1 MB
    assert bytes_to_mb(10485760) == 10.0  # 10 MB
    assert bytes_to_mb(104857600) == 100.0  # 100 MB
    assert bytes_to_mb(1073741824) == 1024.0  # 1 GB
    assert bytes_to_mb(None) == 0


def test_interface_statistics_extraction():
    """Test extracting statistics from interface data."""

    def get_interface_statistics(interface_data):
        """Extract traffic statistics from interface data."""
        if not interface_data:
            return None

        stats = interface_data.get("statistics", {})
        return {
            "rx_bytes": stats.get("rx_bytes", 0),
            "tx_bytes": stats.get("tx_bytes", 0),
            "rx_packets": stats.get("rx_packets", 0),
            "tx_packets": stats.get("tx_packets", 0),
            "rx_errors": stats.get("rx_errors", 0),
            "tx_errors": stats.get("tx_errors", 0),
        }

    # Test with valid interface data
    interface_data = {
        "type": "ethernet",
        "up": True,
        "carrier": True,
        "statistics": {
            "rx_bytes": 1048576000,
            "tx_bytes": 524288000,
            "rx_packets": 1000000,
            "tx_packets": 500000,
            "rx_errors": 0,
            "tx_errors": 0,
        },
    }

    stats = get_interface_statistics(interface_data)
    assert stats["rx_bytes"] == 1048576000
    assert stats["tx_bytes"] == 524288000
    assert stats["rx_packets"] == 1000000
    assert stats["tx_packets"] == 500000
    assert stats["rx_errors"] == 0
    assert stats["tx_errors"] == 0

    # Test with missing statistics
    interface_data_no_stats = {"type": "ethernet", "up": True}
    stats = get_interface_statistics(interface_data_no_stats)
    assert stats["rx_bytes"] == 0
    assert stats["tx_bytes"] == 0

    # Test with None
    assert get_interface_statistics(None) is None


def test_interface_icon_selection():
    """Test icon selection based on interface type and direction."""

    def get_interface_icon(interface_name, direction="download"):
        """Get appropriate icon for interface type and direction."""
        lower_name = interface_name.lower()
        is_download = direction == "download"

        # WAN/Internet interfaces
        if "pppoe" in lower_name or "wan" in lower_name:
            return "mdi:download" if is_download else "mdi:upload"

        # Wireless interfaces
        if "phy" in lower_name or "wlan" in lower_name:
            return "mdi:wifi-arrow-down" if is_download else "mdi:wifi-arrow-up"

        # Default network icon
        return "mdi:download-network" if is_download else "mdi:upload-network"

    # Test WAN interface icons
    assert get_interface_icon("pppoe-wan", "download") == "mdi:download"
    assert get_interface_icon("pppoe-wan", "upload") == "mdi:upload"
    assert get_interface_icon("wan", "download") == "mdi:download"
    assert get_interface_icon("wan", "upload") == "mdi:upload"

    # Test WiFi interface icons
    assert get_interface_icon("wlan0", "download") == "mdi:wifi-arrow-down"
    assert get_interface_icon("wlan0", "upload") == "mdi:wifi-arrow-up"
    assert get_interface_icon("phy0-ap0", "download") == "mdi:wifi-arrow-down"
    assert get_interface_icon("phy0-ap0", "upload") == "mdi:wifi-arrow-up"

    # Test default icons
    assert get_interface_icon("eth0", "download") == "mdi:download-network"
    assert get_interface_icon("eth0", "upload") == "mdi:upload-network"
    assert get_interface_icon("br-lan", "download") == "mdi:download-network"
    assert get_interface_icon("br-lan", "upload") == "mdi:upload-network"


def test_router_traffic_card_device_counting():
    """Test device counting by interface type for traffic card."""

    def count_devices_by_interface_type(devices_data):
        """Count connected devices by interface type."""
        wifi_devices = 0
        ethernet_devices = 0
        total_devices = len(devices_data)

        for device in devices_data:
            interface = device.get("interface", "")
            if interface.startswith("wlan") or "ap" in interface.lower():
                wifi_devices += 1
            elif interface.startswith("eth"):
                ethernet_devices += 1

        return {
            "total": total_devices,
            "wifi": wifi_devices,
            "ethernet": ethernet_devices,
        }

    # Test with sample device data
    devices_data = [
        {"interface": "wlan0", "mac": "aa:bb:cc:dd:ee:01", "hostname": "phone1"},
        {"interface": "wlan0", "mac": "aa:bb:cc:dd:ee:02", "hostname": "laptop1"},
        {"interface": "phy0-ap0", "mac": "aa:bb:cc:dd:ee:03", "hostname": "tablet1"},
        {"interface": "phy1-ap0", "mac": "aa:bb:cc:dd:ee:04", "hostname": "phone2"},
        {"interface": "eth0", "mac": "aa:bb:cc:dd:ee:05", "hostname": "desktop1"},
        {"interface": "eth0", "mac": "aa:bb:cc:dd:ee:06", "hostname": "server1"},
        {"interface": "br-lan", "mac": "aa:bb:cc:dd:ee:07", "hostname": "unknown1"},
    ]

    result = count_devices_by_interface_type(devices_data)

    assert result["total"] == 7
    assert result["wifi"] == 4  # wlan0 (2) + phy0-ap0 (1) + phy1-ap0 (1)
    assert result["ethernet"] == 2  # eth0 (2)


def test_router_traffic_card_total_calculation():
    """Test total traffic calculation for router traffic card."""

    def calculate_total_traffic(interfaces_data):
        """Calculate total router traffic across all interfaces."""
        total_bytes = 0

        for interface_name, interface_data in interfaces_data.items():
            stats = interface_data.get("statistics", {})
            if stats:
                rx_bytes = stats.get("rx_bytes", 0)
                tx_bytes = stats.get("tx_bytes", 0)
                total_bytes += rx_bytes + tx_bytes

        return round(total_bytes / (1024 * 1024), 2)

    # Test with sample interface data
    interfaces_data = {
        "pppoe-wan": {
            "statistics": {
                "rx_bytes": 1073741824,  # 1 GB
                "tx_bytes": 536870912,  # 512 MB
            }
        },
        "wlan0": {
            "statistics": {
                "rx_bytes": 104857600,  # 100 MB
                "tx_bytes": 52428800,  # 50 MB
            }
        },
        "eth0": {
            "statistics": {
                "rx_bytes": 52428800,  # 50 MB
                "tx_bytes": 26214400,  # 25 MB
            }
        },
        # Interface without stats (should be ignored)
        "dummy0": {"up": True},
    }

    total_traffic = calculate_total_traffic(interfaces_data)

    # Total: 1GB + 512MB + 100MB + 50MB + 50MB + 25MB = 1761MB
    expected_total = 1024.0 + 512.0 + 100.0 + 50.0 + 50.0 + 25.0
    assert total_traffic == expected_total

    # Test with empty data
    assert calculate_total_traffic({}) == 0.0

    # Test with interfaces without statistics
    assert calculate_total_traffic({"dummy": {"up": True}}) == 0.0


def test_router_traffic_card_zero_handling():
    """Test how router traffic card handles zero and missing data.

    This test mirrors the logic in WrtManagerRouterTrafficCardSensor._get_aggregated_traffic_data()
    to ensure proper handling of None and missing data scenarios.
    """

    def safe_traffic_calculation(coordinator_data):
        """Safely calculate traffic with proper zero handling.

        Mirrors the behavior of WrtManagerRouterTrafficCardSensor._get_aggregated_traffic_data()
        which checks 'if not self.coordinator.data or "interfaces" not in self.coordinator.data'.
        """
        # Mirror the actual sensor implementation's None/empty data handling
        if not coordinator_data or "interfaces" not in coordinator_data:
            return 0.0

        interfaces_data = coordinator_data["interfaces"]
        if not interfaces_data:
            return 0.0

        total_bytes = 0
        for interface_name, interface_data in interfaces_data.items():
            if not interface_data:
                continue
            stats = interface_data.get("statistics", {})
            if not stats:
                continue

            rx_bytes = stats.get("rx_bytes", 0) or 0
            tx_bytes = stats.get("tx_bytes", 0) or 0
            total_bytes += rx_bytes + tx_bytes

        return round(total_bytes / (1024 * 1024), 2) if total_bytes > 0 else 0.0

    # Test cases that mirror what the actual sensor might receive from coordinator
    # Test with None data (coordinator.data could be None)
    assert safe_traffic_calculation(None) == 0.0

    # Test with empty data
    assert safe_traffic_calculation({}) == 0.0

    # Test with zero bytes
    zero_data = {
        "interfaces": {
            "eth0": {
                "statistics": {
                    "rx_bytes": 0,
                    "tx_bytes": 0,
                }
            }
        }
    }
    assert safe_traffic_calculation(zero_data) == 0.0

    # Test with None values
    none_data = {
        "interfaces": {
            "eth0": {
                "statistics": {
                    "rx_bytes": None,
                    "tx_bytes": None,
                }
            }
        }
    }
    assert safe_traffic_calculation(none_data) == 0.0

    # Test with missing statistics
    missing_stats_data = {"interfaces": {"eth0": {"up": True}}}
    assert safe_traffic_calculation(missing_stats_data) == 0.0
