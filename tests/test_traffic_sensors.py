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
