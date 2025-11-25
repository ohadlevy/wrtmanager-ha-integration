"""Tests for core business logic without HA dependencies."""


def test_vlan_detection_logic():
    """Test VLAN detection based on IP address."""

    def determine_vlan(device):
        """VLAN detection logic."""
        ip = device.get("ip_address")
        if ip:
            if ip.startswith("192.168.5."):
                return 3  # IoT VLAN
            elif ip.startswith("192.168.13."):
                return 13  # Guest VLAN
            else:
                return 1  # Main VLAN
        return 1  # Default to main VLAN

    # Test IoT VLAN
    device = {"ip_address": "192.168.5.100"}
    assert determine_vlan(device) == 3

    # Test Guest VLAN
    device = {"ip_address": "192.168.13.50"}
    assert determine_vlan(device) == 13

    # Test Main VLAN
    device = {"ip_address": "192.168.1.100"}
    assert determine_vlan(device) == 1

    # Test no IP
    device = {}
    assert determine_vlan(device) == 1


def test_signal_quality_classification():
    """Test WiFi signal quality classification."""

    def classify_signal(signal_dbm):
        """Classify signal strength."""
        if signal_dbm is None:
            return "Unknown"
        elif signal_dbm >= -50:
            return "Excellent"
        elif signal_dbm >= -60:
            return "Good"
        elif signal_dbm >= -70:
            return "Fair"
        else:
            return "Poor"

    assert classify_signal(-45) == "Excellent"
    assert classify_signal(-55) == "Good"
    assert classify_signal(-65) == "Fair"
    assert classify_signal(-85) == "Poor"
    assert classify_signal(None) == "Unknown"


def test_dhcp_lease_parsing():
    """Test DHCP lease data parsing."""

    def parse_dhcp_leases(dhcp_leases):
        """Parse DHCP lease data."""
        devices = {}
        if dhcp_leases and "device" in dhcp_leases:
            for lease in dhcp_leases["device"].get("leases", []):
                mac = lease.get("macaddr", "").upper()
                if mac:
                    devices[mac] = {
                        "ip_address": lease.get("ipaddr"),
                        "hostname": lease.get("hostname", ""),
                        "data_source": "dynamic_dhcp",
                    }
        return devices

    dhcp_data = {
        "device": {
            "leases": [
                {
                    "macaddr": "cc:8c:bf:0a:b7:f4",
                    "ipaddr": "192.168.1.100",
                    "hostname": "test-device",
                },
                {
                    "macaddr": "aa:bb:cc:dd:ee:ff",
                    "ipaddr": "192.168.5.50",
                    "hostname": "iot-device",
                },
            ]
        }
    }

    result = parse_dhcp_leases(dhcp_data)

    assert len(result) == 2
    assert "CC:8C:BF:0A:B7:F4" in result
    assert result["CC:8C:BF:0A:B7:F4"]["ip_address"] == "192.168.1.100"
    assert result["CC:8C:BF:0A:B7:F4"]["hostname"] == "test-device"
    assert result["CC:8C:BF:0A:B7:F4"]["data_source"] == "dynamic_dhcp"


def test_static_dhcp_parsing():
    """Test static DHCP host parsing."""

    def parse_static_hosts(static_hosts):
        """Parse static DHCP hosts."""
        devices = {}
        if static_hosts and "values" in static_hosts:
            for section_data in static_hosts["values"].values():
                if section_data.get(".type") == "host":
                    mac = section_data.get("mac", "").upper()
                    if mac:
                        devices[mac] = {
                            "ip_address": section_data.get("ip"),
                            "hostname": section_data.get("name", ""),
                            "data_source": "static_dhcp",
                        }
        return devices

    static_data = {
        "values": {
            "cfg001": {
                ".type": "host",
                "mac": "CC:8C:BF:0A:B7:F4",
                "ip": "192.168.1.50",
                "name": "static-device",
            },
            "cfg002": {
                ".type": "dnsmasq",  # Should be ignored
                "option": "log-queries",
            },
        }
    }

    result = parse_static_hosts(static_data)

    assert len(result) == 1
    assert "CC:8C:BF:0A:B7:F4" in result
    assert result["CC:8C:BF:0A:B7:F4"]["ip_address"] == "192.168.1.50"
    assert result["CC:8C:BF:0A:B7:F4"]["hostname"] == "static-device"
    assert result["CC:8C:BF:0A:B7:F4"]["data_source"] == "static_dhcp"


def test_device_data_correlation():
    """Test correlating WiFi and DHCP data."""

    def correlate_device_data(wifi_devices, dhcp_data):
        """Correlate WiFi devices with DHCP data."""
        enriched_devices = []

        for device in wifi_devices:
            mac = device["mac_address"]

            # Merge DHCP data if available
            if mac in dhcp_data:
                device.update(dhcp_data[mac])
            else:
                device["data_source"] = "wifi_only"

            enriched_devices.append(device)

        return enriched_devices

    wifi_devices = [
        {
            "mac_address": "CC:8C:BF:0A:B7:F4",
            "router": "192.168.1.1",
            "signal_dbm": -69,
            "connected": True,
        },
        {
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "router": "192.168.1.1",
            "signal_dbm": -55,
            "connected": True,
        },
    ]

    dhcp_data = {
        "CC:8C:BF:0A:B7:F4": {
            "ip_address": "192.168.1.100",
            "hostname": "test-device",
            "data_source": "dynamic_dhcp",
        }
    }

    result = correlate_device_data(wifi_devices, dhcp_data)

    assert len(result) == 2

    # First device should have DHCP data
    device1 = next(d for d in result if d["mac_address"] == "CC:8C:BF:0A:B7:F4")
    assert device1["ip_address"] == "192.168.1.100"
    assert device1["hostname"] == "test-device"
    assert device1["data_source"] == "dynamic_dhcp"

    # Second device should be wifi-only
    device2 = next(d for d in result if d["mac_address"] == "AA:BB:CC:DD:EE:FF")
    assert device2["data_source"] == "wifi_only"
    assert "ip_address" not in device2


def test_router_capability_detection():
    """Test router capability detection logic."""

    def detect_router_capabilities(dhcp_available, wireless_interfaces, system_info):
        """Detect router capabilities."""
        router_type = "Main Router" if dhcp_available else "Access Point"

        return {
            "router_type": router_type,
            "capabilities": {
                "wireless": len(wireless_interfaces) if wireless_interfaces else 0,
                "dhcp": dhcp_available,
                "system_info": system_info is not None,
            },
        }

    # Test main router
    result = detect_router_capabilities(
        dhcp_available=True,
        wireless_interfaces=["phy0-ap0", "phy1-ap0"],
        system_info={"hostname": "main-router"},
    )

    assert result["router_type"] == "Main Router"
    assert result["capabilities"]["wireless"] == 2
    assert result["capabilities"]["dhcp"]
    assert result["capabilities"]["system_info"]

    # Test access point
    result = detect_router_capabilities(
        dhcp_available=False,
        wireless_interfaces=["phy0-ap0"],
        system_info={"hostname": "ap-device"},
    )

    assert result["router_type"] == "Access Point"
    assert result["capabilities"]["wireless"] == 1
    assert not result["capabilities"]["dhcp"]


def test_memory_usage_calculation():
    """Test memory usage calculation."""

    def calculate_memory_usage(memory_data):
        """Calculate memory usage percentage."""
        if not memory_data:
            return None

        total = memory_data.get("total")
        free = memory_data.get("free")

        if total and free:
            used = total - free
            return round((used / total) * 100, 1)
        return None

    # Test normal memory data
    memory_data = {
        "total": 524288,  # 512MB in KB
        "free": 262144,  # 256MB in KB
    }
    result = calculate_memory_usage(memory_data)
    assert result == 50.0  # 50% used

    # Test with missing data
    assert calculate_memory_usage({}) is None
    assert calculate_memory_usage(None) is None


def test_device_vlan_counting():
    """Test counting devices by VLAN."""

    def count_devices_by_vlan(devices, target_router):
        """Count devices by VLAN for a specific router."""
        vlan_counts = {"main": 0, "iot": 0, "guest": 0, "unknown": 0}

        for device in devices:
            if device.get("router") == target_router:
                vlan = device.get("vlan_id", 1)
                if vlan == 1:
                    vlan_counts["main"] += 1
                elif vlan == 3:
                    vlan_counts["iot"] += 1
                elif vlan == 13:
                    vlan_counts["guest"] += 1
                else:
                    vlan_counts["unknown"] += 1

        return vlan_counts

    devices = [
        {"mac_address": "AA:BB:CC:DD:EE:01", "router": "192.168.1.1", "vlan_id": 1},
        {"mac_address": "AA:BB:CC:DD:EE:02", "router": "192.168.1.1", "vlan_id": 3},
        {"mac_address": "AA:BB:CC:DD:EE:03", "router": "192.168.1.1", "vlan_id": 13},
        {"mac_address": "AA:BB:CC:DD:EE:04", "router": "192.168.1.1", "vlan_id": 99},
        {
            "mac_address": "AA:BB:CC:DD:EE:05",
            "router": "192.168.1.2",
            "vlan_id": 1,
        },  # Different router
    ]

    result = count_devices_by_vlan(devices, "192.168.1.1")

    assert result["main"] == 1
    assert result["iot"] == 1
    assert result["guest"] == 1
    assert result["unknown"] == 1

    # Test with different router
    result = count_devices_by_vlan(devices, "192.168.1.2")
    assert result["main"] == 1
    assert result["iot"] == 0


def test_uptime_formatting():
    """Test uptime formatting logic."""
    from datetime import timedelta

    def format_uptime(uptime_seconds):
        """Format uptime for display."""
        if not uptime_seconds:
            return {}

        uptime_delta = timedelta(seconds=uptime_seconds)

        return {
            "uptime_formatted": str(uptime_delta),
            "days": uptime_delta.days,
            "hours": uptime_delta.seconds // 3600,
        }

    # Test normal uptime
    result = format_uptime(123456)  # ~1.4 days
    assert "uptime_formatted" in result
    assert result["days"] == 1
    assert result["hours"] == 10  # (123456 - 86400) // 3600 = 10

    # Test no uptime
    assert format_uptime(None) == {}
    assert format_uptime(0) == {}


def test_load_average_parsing():
    """Test load average data parsing."""

    def parse_load_average(load_data):
        """Parse load average data."""
        if not load_data or len(load_data) < 3:
            return {"load_1min": None}

        return {
            "load_1min": round(load_data[0], 2),
            "load_5min": round(load_data[1], 2),
            "load_15min": round(load_data[2], 2),
        }

    # Test normal load data
    load_data = [0.15, 0.25, 0.30]
    result = parse_load_average(load_data)

    assert result["load_1min"] == 0.15
    assert result["load_5min"] == 0.25
    assert result["load_15min"] == 0.30

    # Test incomplete data
    result = parse_load_average([0.15])
    assert result["load_1min"] is None

    # Test no data
    result = parse_load_average([])
    assert result["load_1min"] is None
