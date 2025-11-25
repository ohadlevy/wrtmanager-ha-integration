"""Tests for SSID discovery and monitoring functionality."""


def test_ssid_extraction_from_wireless_data():
    """Test SSID extraction from wireless status data."""

    def extract_ssid_data(interfaces):
        """Extract SSID information from wireless status data."""
        ssid_data = {}

        for router_host, router_interfaces in interfaces.items():
            router_ssids = []

            # Check if this router has wireless status data accessible via ubus
            has_wireless_data = any(
                isinstance(interface_data, dict) and "interfaces" in interface_data
                for interface_data in router_interfaces.values()
            )

            if not has_wireless_data:
                # Router is in dump AP mode - SSIDs exist but are not accessible via ubus
                continue

            # Look for wireless status data (has radio structure)
            for interface_name, interface_data in router_interfaces.items():
                # Skip network interfaces, focus on wireless status structure
                if isinstance(interface_data, dict) and "interfaces" in interface_data:
                    # This is a radio (e.g., radio0, radio1)
                    radio_name = interface_name
                    radio_interfaces = interface_data.get("interfaces", {})

                    if not isinstance(radio_interfaces, dict):
                        continue

                    for ssid_interface_name, ssid_interface_data in radio_interfaces.items():
                        config = ssid_interface_data.get("config", {})
                        ssid_name = config.get("ssid")

                        if ssid_name:
                            ssid_info = {
                                "radio": radio_name,
                                "ssid_interface": ssid_interface_name,
                                "ssid_name": ssid_name,
                                "mode": config.get("mode", "ap"),
                                "disabled": config.get("disabled", False),
                                "network_interface": ssid_interface_data.get("ifname"),
                                "router_host": router_host,
                                "encryption": config.get("encryption"),
                                "hidden": config.get("hidden", False),
                                "network": config.get("network"),
                            }
                            router_ssids.append(ssid_info)

            if router_ssids:
                ssid_data[router_host] = router_ssids

        return ssid_data

    # Test full router with wireless status accessible
    full_router_interfaces = {
        "192.168.1.1": {
            "radio0": {
                "interfaces": {
                    "default_radio0.network1": {
                        "config": {
                            "ssid": "MainNetwork",
                            "mode": "ap",
                            "disabled": False,
                            "encryption": "psk2",
                            "key": "password123",
                            "network": "lan",
                        },
                        "ifname": "wlan0",
                    },
                    "default_radio0.network2": {
                        "config": {
                            "ssid": "GuestNetwork",
                            "mode": "ap",
                            "disabled": False,
                            "encryption": "psk2",
                            "key": "guestpass",
                            "network": "guest",
                            "hidden": True,
                        },
                        "ifname": "wlan0-1",
                    },
                }
            },
            "radio1": {
                "interfaces": {
                    "default_radio1.network1": {
                        "config": {
                            "ssid": "MainNetwork_5G",
                            "mode": "ap",
                            "disabled": False,
                            "encryption": "psk2",
                            "key": "password123",
                            "network": "lan",
                        },
                        "ifname": "wlan1",
                    }
                }
            },
        }
    }

    result = extract_ssid_data(full_router_interfaces)

    assert "192.168.1.1" in result
    router_ssids = result["192.168.1.1"]
    assert len(router_ssids) == 3

    # Check MainNetwork 2.4GHz
    main_24 = next(s for s in router_ssids if s["ssid_name"] == "MainNetwork")
    assert main_24["radio"] == "radio0"
    assert main_24["mode"] == "ap"
    assert main_24["disabled"] is False
    assert main_24["encryption"] == "psk2"
    assert main_24["network"] == "lan"

    # Check GuestNetwork (hidden)
    guest = next(s for s in router_ssids if s["ssid_name"] == "GuestNetwork")
    assert guest["hidden"] is True
    assert guest["network"] == "guest"

    # Check MainNetwork 5GHz
    main_5g = next(s for s in router_ssids if s["ssid_name"] == "MainNetwork_5G")
    assert main_5g["radio"] == "radio1"

    # Test dump AP mode - wireless status not accessible via ubus
    # NOTE: The AP still has SSIDs running, but ubus wireless status is unavailable
    dump_ap_interfaces = {
        "192.168.1.2": {
            "eth0": {"up": True, "ipv4": "192.168.1.2"},
            "br-lan": {"up": True, "ipv4": "192.168.1.2"},
            # No radio0/radio1 with wireless status - ubus access restricted
        }
    }

    result = extract_ssid_data(dump_ap_interfaces)
    assert result == {}  # No SSID data accessible via ubus in dump AP mode

    # Test mixed environment (full router + dump AP)
    mixed_interfaces = {**full_router_interfaces, **dump_ap_interfaces}

    result = extract_ssid_data(mixed_interfaces)
    assert "192.168.1.1" in result  # Full router has accessible SSID data
    assert "192.168.1.2" not in result  # Dump AP mode - SSID data not accessible


def test_ssid_binary_sensor_state():
    """Test SSID binary sensor state determination."""

    def get_ssid_binary_state(ssid_data):
        """Determine if SSID is enabled (binary sensor state)."""
        if not ssid_data:
            return False
        # SSID is "on" (enabled) when disabled = False or None
        return not ssid_data.get("disabled", False)

    # Test enabled SSID
    enabled_ssid = {"ssid_name": "MainNetwork", "disabled": False, "mode": "ap"}
    assert get_ssid_binary_state(enabled_ssid) is True

    # Test disabled SSID
    disabled_ssid = {"ssid_name": "MainNetwork", "disabled": True, "mode": "ap"}
    assert get_ssid_binary_state(disabled_ssid) is False

    # Test SSID with no disabled field (defaults to enabled)
    default_ssid = {"ssid_name": "MainNetwork", "mode": "ap"}
    assert get_ssid_binary_state(default_ssid) is True

    # Test no SSID data
    assert get_ssid_binary_state(None) is False
    assert get_ssid_binary_state({}) is False


def test_ssid_availability_check():
    """Test SSID binary sensor availability logic."""

    def check_ssid_sensor_availability(coordinator_data, router_host, ssid_interface, radio):
        """Check if SSID sensor should be available."""
        if not coordinator_data or "ssids" not in coordinator_data:
            return False

        router_ssids = coordinator_data["ssids"].get(router_host, [])

        # Find matching SSID data
        for ssid_data in router_ssids:
            if (
                ssid_data.get("ssid_interface") == ssid_interface
                and ssid_data.get("radio") == radio
            ):
                return True
        return False

    # Test with valid coordinator data
    coordinator_data = {
        "ssids": {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_interface": "default_radio0.network1",
                    "ssid_name": "MainNetwork",
                    "disabled": False,
                }
            ]
        }
    }

    # Should be available when SSID data exists
    assert (
        check_ssid_sensor_availability(
            coordinator_data, "192.168.1.1", "default_radio0.network1", "radio0"
        )
        is True
    )

    # Should not be available for non-existent SSID
    assert (
        check_ssid_sensor_availability(
            coordinator_data, "192.168.1.1", "missing_interface", "radio0"
        )
        is False
    )

    # Should not be available for dump AP (wireless status not accessible)
    assert (
        check_ssid_sensor_availability(
            coordinator_data, "192.168.1.2", "default_radio0.network1", "radio0"
        )
        is False
    )

    # Should not be available with no coordinator data
    assert (
        check_ssid_sensor_availability(None, "192.168.1.1", "default_radio0.network1", "radio0")
        is False
    )

    # Should not be available with no SSID data
    no_ssid_data = {"devices": [], "system_info": {}}
    assert (
        check_ssid_sensor_availability(
            no_ssid_data, "192.168.1.1", "default_radio0.network1", "radio0"
        )
        is False
    )


def test_ssid_frequency_band_detection():
    """Test frequency band detection from radio name."""

    def detect_frequency_band(radio_name):
        """Detect frequency band from radio name."""
        if not radio_name:
            return "Unknown"
        if "0" in radio_name:
            return "2.4GHz"
        elif "1" in radio_name:
            return "5GHz"
        else:
            return "Unknown"

    # Test typical radio names
    assert detect_frequency_band("radio0") == "2.4GHz"
    assert detect_frequency_band("radio1") == "5GHz"
    assert detect_frequency_band("phy0") == "2.4GHz"
    assert detect_frequency_band("phy1") == "5GHz"

    # Test edge cases
    assert detect_frequency_band("radio2") == "Unknown"
    assert detect_frequency_band("") == "Unknown"
    assert detect_frequency_band(None) == "Unknown"


def test_interface_device_count_logic():
    """Test counting devices per wireless interface/SSID."""

    def count_devices_per_interface(devices, target_router):
        """Count devices per wireless interface for a router."""
        interface_counts = {}

        for device in devices:
            if device.get("router") == target_router:
                interface = device.get("interface")
                if interface and (interface.startswith("wlan") or "ap" in interface.lower()):
                    interface_counts[interface] = interface_counts.get(interface, 0) + 1

        return interface_counts

    devices = [
        {"mac_address": "AA:BB:CC:DD:EE:01", "router": "192.168.1.1", "interface": "wlan0"},
        {"mac_address": "AA:BB:CC:DD:EE:02", "router": "192.168.1.1", "interface": "wlan0"},
        {"mac_address": "AA:BB:CC:DD:EE:03", "router": "192.168.1.1", "interface": "wlan1"},
        {"mac_address": "AA:BB:CC:DD:EE:04", "router": "192.168.1.1", "interface": "eth0"},  # Wired
        {
            "mac_address": "AA:BB:CC:DD:EE:05",
            "router": "192.168.1.2",
            "interface": "wlan0",
        },  # Different router
    ]

    result = count_devices_per_interface(devices, "192.168.1.1")

    assert result["wlan0"] == 2  # Two devices on wlan0
    assert result["wlan1"] == 1  # One device on wlan1
    assert "eth0" not in result  # Wired interface ignored

    # Test with different router
    result = count_devices_per_interface(devices, "192.168.1.2")
    assert result["wlan0"] == 1

    # Test with no devices
    result = count_devices_per_interface([], "192.168.1.1")
    assert result == {}


def test_dump_ap_mode_detection():
    """Test detection of dump AP mode vs full OpenWrt router."""

    def detect_router_mode(interface_data):
        """Detect if router is in dump AP mode or full router mode."""
        # Full router has wireless status data accessible
        has_wireless_status = any(
            isinstance(data, dict) and "interfaces" in data for data in interface_data.values()
        )

        return "full_router" if has_wireless_status else "dump_ap"

    # Test full router with wireless status
    full_router_data = {
        "radio0": {"interfaces": {"default_radio0.network1": {"config": {"ssid": "TestSSID"}}}}
    }
    assert detect_router_mode(full_router_data) == "full_router"

    # Test dump AP mode (no wireless status accessible)
    dump_ap_data = {"eth0": {"up": True}, "br-lan": {"up": True}}
    assert detect_router_mode(dump_ap_data) == "dump_ap"

    # Test empty data
    assert detect_router_mode({}) == "dump_ap"


def test_ssid_sensor_entity_id_generation():
    """Test SSID binary sensor entity ID generation."""

    def generate_ssid_entity_id(router_host, radio, ssid_name):
        """Generate unique entity ID for SSID binary sensor."""
        safe_ssid = ssid_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
        safe_radio = radio.replace("radio", "")
        safe_router = router_host.replace(".", "_").replace("-", "_")

        return f"wrtmanager_{safe_router}_{safe_radio}_{safe_ssid}_enabled"

    # Test typical SSID names
    assert (
        generate_ssid_entity_id("192.168.1.1", "radio0", "MainNetwork")
        == "wrtmanager_192_168_1_1_0_mainnetwork_enabled"
    )
    assert (
        generate_ssid_entity_id("192.168.1.1", "radio1", "Guest-Network")
        == "wrtmanager_192_168_1_1_1_guest_network_enabled"
    )
    assert (
        generate_ssid_entity_id("192.168.1.1", "radio0", "IoT.Devices")
        == "wrtmanager_192_168_1_1_0_iot_devices_enabled"
    )

    # Test with spaces and special characters
    assert (
        generate_ssid_entity_id("10.0.0.1", "radio0", "Home WiFi 2024")
        == "wrtmanager_10_0_0_1_0_home_wifi_2024_enabled"
    )


def test_ssid_attributes_extraction():
    """Test extraction of SSID attributes for Home Assistant."""

    def extract_ssid_attributes(ssid_data):
        """Extract attributes for SSID binary sensor."""
        if not ssid_data:
            return {}

        attributes = {
            "ssid_name": ssid_data.get("ssid_name"),
            "radio": ssid_data.get("radio"),
            "ssid_interface": ssid_data.get("ssid_interface"),
            "network_interface": ssid_data.get("network_interface"),
            "ssid_mode": ssid_data.get("mode", "ap"),
            "encryption": ssid_data.get("encryption"),
            "hidden": ssid_data.get("hidden", False),
            "client_isolation": ssid_data.get("isolate", False),
            "network_name": ssid_data.get("network"),
        }

        # Add frequency band
        radio_name = ssid_data.get("radio", "")
        if "0" in radio_name:
            attributes["frequency_band"] = "2.4GHz"
        elif "1" in radio_name:
            attributes["frequency_band"] = "5GHz"
        else:
            attributes["frequency_band"] = "Unknown"

        # Remove None values
        return {k: v for k, v in attributes.items() if v is not None}

    # Test complete SSID data
    ssid_data = {
        "ssid_name": "MainNetwork",
        "radio": "radio0",
        "ssid_interface": "default_radio0.network1",
        "network_interface": "wlan0",
        "mode": "ap",
        "encryption": "psk2",
        "hidden": False,
        "isolate": True,
        "network": "lan",
    }

    attributes = extract_ssid_attributes(ssid_data)

    assert attributes["ssid_name"] == "MainNetwork"
    assert attributes["frequency_band"] == "2.4GHz"
    assert attributes["client_isolation"] is True
    assert attributes["hidden"] is False

    # Test minimal SSID data
    minimal_data = {"ssid_name": "TestSSID", "radio": "radio1"}

    attributes = extract_ssid_attributes(minimal_data)
    assert attributes["ssid_name"] == "TestSSID"
    assert attributes["frequency_band"] == "5GHz"
    assert "encryption" not in attributes  # None values removed

    # Test empty data
    assert extract_ssid_attributes({}) == {}
    assert extract_ssid_attributes(None) == {}
