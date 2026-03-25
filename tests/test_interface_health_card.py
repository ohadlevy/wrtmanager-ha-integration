"""Tests for WrtManagerInterfaceHealthCardSensor."""

from unittest.mock import MagicMock

from custom_components.wrtmanager.sensor import WrtManagerInterfaceHealthCardSensor


def _make_sensor(coordinator_data, router_host="10.99.0.1"):
    """Create a sensor instance with mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = coordinator_data
    coordinator.last_update_success = True
    sensor = WrtManagerInterfaceHealthCardSensor.__new__(WrtManagerInterfaceHealthCardSensor)
    sensor.coordinator = coordinator
    sensor._router_host = router_host
    sensor._router_name = "Test Router"
    return sensor


def test_interface_sort_key():
    """WAN < bridge < ethernet < other ordering."""
    assert WrtManagerInterfaceHealthCardSensor._iface_sort_key("eth0", True) == 0
    assert WrtManagerInterfaceHealthCardSensor._iface_sort_key("wan", True) == 0
    assert WrtManagerInterfaceHealthCardSensor._iface_sort_key("br-lan", False) == 1
    assert WrtManagerInterfaceHealthCardSensor._iface_sort_key("eth0", False) == 2
    assert WrtManagerInterfaceHealthCardSensor._iface_sort_key("tun0", False) == 3


def test_router_role_internet():
    """WAN up+carrier → role='internet'."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "eth0": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {
            "10.99.0.1": {
                "eth0": {"logical": "wan", "ip": "10.0.0.1/24"},
            }
        },
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    assert attrs["router_role"] == "internet"
    assert attrs["has_internet"] is True


def test_router_role_dhcp():
    """No WAN, in dhcp_routers → role='dhcp'."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {
            "10.99.0.1": {
                "br-lan": {"logical": "lan", "ip": "192.168.1.1/24"},
            }
        },
        "dhcp_routers": ["10.99.0.1"],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    assert attrs["router_role"] == "dhcp"
    assert attrs["has_dhcp"] is True
    assert attrs["has_internet"] is False


def test_router_role_ap():
    """No WAN, not in dhcp_routers → role='ap'."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {
            "10.99.0.1": {
                "br-lan": {"logical": "lan", "ip": "192.168.1.2/24"},
            }
        },
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    assert attrs["router_role"] == "ap"
    assert attrs["has_internet"] is False
    assert attrs["has_dhcp"] is False


def test_status_up():
    """up=True, carrier=True → status='up'."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {"10.99.0.1": {}},
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["status"] == "up"


def test_status_no_carrier():
    """up=True, carrier=False → status='no_carrier'."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": True, "carrier": False, "statistics": {}},
            }
        },
        "interface_ips": {"10.99.0.1": {}},
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["status"] == "no_carrier"


def test_status_down():
    """up=False → status='down'."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": False, "carrier": False, "statistics": {}},
            }
        },
        "interface_ips": {"10.99.0.1": {}},
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["status"] == "down"


def test_ip_from_dump():
    """l3_device match → ip string appears in interface attrs."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {
            "10.99.0.1": {
                "br-lan": {"logical": "lan", "ip": "192.168.1.1/24"},
            }
        },
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["ip"] == "192.168.1.1/24"
    assert iface["logical_name"] == "lan"


def test_radio_interfaces_excluded():
    """radio0, radio1, phy0-ap0, lo, wlan0 must not appear in output."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "radio0": {"up": True, "carrier": True, "interfaces": [], "statistics": {}},
                "radio1": {"up": True, "carrier": True, "interfaces": [], "statistics": {}},
                "phy0-ap0": {"up": True, "carrier": True, "statistics": {}},
                "wlan0": {"up": True, "carrier": True, "statistics": {}},
                "lo": {"up": True, "carrier": True, "statistics": {}},
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {"10.99.0.1": {}},
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    names = [i["physical_name"] for i in attrs["interfaces"]]
    assert "radio0" not in names
    assert "radio1" not in names
    assert "phy0-ap0" not in names
    assert "wlan0" not in names
    assert "lo" not in names
    assert "br-lan" in names


def test_bridge_member_classification():
    """eth0 → has_wired, phy0-ap0 → has_wireless."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {
                    "up": True,
                    "carrier": True,
                    "bridge-members": ["eth0", "phy0-ap0", "phy1-ap0"],
                    "statistics": {},
                },
            }
        },
        "interface_ips": {"10.99.0.1": {}},
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["has_wired"] is True
    assert iface["has_wireless"] is True


def test_error_count():
    """rx_errors + tx_errors summed correctly."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {
                    "up": True,
                    "carrier": True,
                    "statistics": {"rx_errors": 3, "tx_errors": 2, "rx_bytes": 0, "tx_bytes": 0},
                },
            }
        },
        "interface_ips": {"10.99.0.1": {}},
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["rx_errors"] == 3
    assert iface["tx_errors"] == 2


def test_device_count_per_network():
    """Devices grouped by network_name correctly."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {
            "10.99.0.1": {
                "br-lan": {"logical": "lan", "ip": "192.168.1.1/24"},
            }
        },
        "dhcp_routers": [],
        "devices": [
            {"router": "10.99.0.1", "network_name": "lan"},
            {"router": "10.99.0.1", "network_name": "lan"},
            {"router": "10.99.0.1", "network_name": "guest"},
            {"router": "10.99.0.2", "network_name": "lan"},
        ],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["device_count"] == 2  # only the two lan devices from this router


def test_wan_traffic_attrs():
    """rx_bytes_mb / tx_bytes_mb computed correctly."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "eth0": {
                    "up": True,
                    "carrier": True,
                    "statistics": {
                        "rx_bytes": 1048576,  # 1 MB
                        "tx_bytes": 2097152,  # 2 MB
                        "rx_errors": 0,
                        "tx_errors": 0,
                    },
                },
            }
        },
        "interface_ips": {
            "10.99.0.1": {
                "eth0": {"logical": "wan", "ip": "10.0.0.1/24"},
            }
        },
        "dhcp_routers": [],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    iface = attrs["interfaces"][0]
    assert iface["rx_bytes_mb"] == 1.0
    assert iface["tx_bytes_mb"] == 2.0


def test_has_dhcp_flag():
    """Router in dhcp_routers → has_dhcp=True."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {"10.99.0.1": {}},
        "dhcp_routers": ["10.99.0.1"],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    assert attrs["has_dhcp"] is True


def test_both_internet_and_dhcp():
    """Router with WAN up + in dhcp_routers → role=internet, has_dhcp=True."""
    data = {
        "interfaces": {
            "10.99.0.1": {
                "eth0": {"up": True, "carrier": True, "statistics": {}},
                "br-lan": {"up": True, "carrier": True, "statistics": {}},
            }
        },
        "interface_ips": {
            "10.99.0.1": {
                "eth0": {"logical": "wan", "ip": "10.0.0.1/24"},
                "br-lan": {"logical": "lan", "ip": "192.168.1.1/24"},
            }
        },
        "dhcp_routers": ["10.99.0.1"],
        "devices": [],
    }
    sensor = _make_sensor(data)
    attrs = sensor.extra_state_attributes
    assert attrs["router_role"] == "internet"
    assert attrs["has_internet"] is True
    assert attrs["has_dhcp"] is True
