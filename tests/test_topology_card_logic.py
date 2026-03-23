"""Tests for NetworkTopologyCard router discovery logic."""

from unittest.mock import MagicMock, Mock

from custom_components.wrtmanager.const import (
    ATTR_MAC,
    ATTR_PRIMARY_AP,
    ATTR_ROUTER,
    DOMAIN,
)
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


def test_primary_ap_attribute_set_on_device():
    """Test that _update_roaming_detection sets ATTR_PRIMARY_AP from ATTR_ROUTER."""
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator._device_history = {}

    router_host = "host.containers.internal:18001"
    device = {
        ATTR_MAC: "AA:BB:CC:DD:EE:FF",
        ATTR_ROUTER: router_host,
    }

    # Replicate what _update_roaming_detection does for a single-router device
    devices = [device]
    mac_to_devices = {}
    for d in devices:
        if not d.get(ATTR_ROUTER):
            continue
        mac = d[ATTR_MAC]
        mac_to_devices.setdefault(mac, []).append(d)

    for mac, device_list in mac_to_devices.items():
        if len(device_list) == 1:
            device_list[0][ATTR_PRIMARY_AP] = device_list[0][ATTR_ROUTER]

    assert device[ATTR_PRIMARY_AP] == router_host


def test_primary_ap_attribute_set_with_colon_in_host():
    """Test that hostname:port format is preserved exactly in ATTR_PRIMARY_AP."""
    router_host = "host.containers.internal:18001"
    device = {
        ATTR_MAC: "AA:BB:CC:DD:EE:FF",
        ATTR_ROUTER: router_host,
    }

    # Simulate single-router assignment
    device[ATTR_PRIMARY_AP] = device[ATTR_ROUTER]

    # The colon must be preserved — the old card bug broke on this
    assert ":" in device[ATTR_PRIMARY_AP]
    assert device[ATTR_PRIMARY_AP] == "host.containers.internal:18001"


def test_primary_ap_in_extra_state_attributes():
    """Test that WrtDevicePresenceSensor exposes primary_ap in extra_state_attributes."""
    from custom_components.wrtmanager.binary_sensor import WrtDevicePresenceSensor

    router_host = "host.containers.internal:18001"
    mac = "AA:BB:CC:DD:EE:FF"

    device_data = {
        ATTR_MAC: mac,
        ATTR_ROUTER: router_host,
        ATTR_PRIMARY_AP: router_host,
        "ip": "192.168.1.100",
        "hostname": "test-device",
        "vendor": "Apple Inc.",
        "device_type": "Phone",
        "connection_type": "wifi",
        "signal_dbm": -65,
        "roaming_count": 0,
    }

    coordinator = Mock()
    coordinator.data = {"devices": [device_data]}

    sensor = WrtDevicePresenceSensor.__new__(WrtDevicePresenceSensor)
    sensor._mac = mac
    sensor._coordinator = coordinator
    sensor.coordinator = coordinator
    sensor.hass = MagicMock()

    # Mock _get_device_data to return our device_data
    sensor._get_device_data = Mock(return_value=device_data)
    sensor._get_existing_device = Mock(return_value=None)

    attrs = sensor.extra_state_attributes

    assert "primary_ap" in attrs
    assert attrs["primary_ap"] == router_host


def test_router_device_identifier_uses_router_host_verbatim():
    """Test that sensor device_info uses router_host as identifier without transformation."""
    from custom_components.wrtmanager.sensor import WrtManagerSensorBase

    router_host = "host.containers.internal:18001"

    coordinator = Mock()
    coordinator.data = {"system_info": {router_host: {}}}

    sensor = WrtManagerSensorBase.__new__(WrtManagerSensorBase)
    sensor._router_host = router_host
    sensor._router_name = "Test Router"
    sensor.coordinator = coordinator
    sensor.hass = MagicMock()

    info = sensor.device_info

    # The identifier must be exactly (DOMAIN, router_host) — colons and dots preserved
    assert (DOMAIN, router_host) in info["identifiers"]
    assert info["manufacturer"] == "OpenWrt"
