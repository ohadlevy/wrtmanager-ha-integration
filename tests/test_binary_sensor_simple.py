"""Simple tests to boost binary_sensor.py coverage."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager.binary_sensor import (
    WrtAreaSSIDBinarySensor,
    WrtDevicePresenceSensor,
    WrtGlobalSSIDBinarySensor,
    WrtInterfaceStatusSensor,
)
from custom_components.wrtmanager.const import (
    ATTR_CONNECTED,
    ATTR_HOSTNAME,
    ATTR_MAC,
    ATTR_ROUTER,
    DOMAIN,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_CONNECTED: True,
                ATTR_ROUTER: "192.168.1.1",
                ATTR_HOSTNAME: "test-device",
            }
        ],
        "system_info": {
            "192.168.1.1": {"uptime": 86400, "memory": {"free": 50000000}, "load": [0.1, 0.2, 0.3]}
        },
        "ssids": {
            "192.168.1.1": [
                {
                    "ssid_name": "TestNetwork",
                    "disabled": False,
                    "hidden": False,
                    "encryption": "psk2",
                    "router_host": "192.168.1.1",
                }
            ]
        },
        "interfaces": {"192.168.1.1": {"wlan0": {"status": "up"}, "eth0": {"status": "down"}}},
    }
    coordinator.last_update_success = True
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "routers": [
                {
                    "host": "192.168.1.1",
                    "name": "Test Router",
                    "username": "root",
                    "password": "test",
                }
            ]
        },
        entry_id="test_entry",
    )


class TestWrtGlobalSSIDBinarySensor:
    """Test global SSID binary sensor."""

    def test_init(self, mock_coordinator, mock_config_entry):
        """Test sensor initialization."""
        ssid_name = "TestNetwork"
        ssid_group = {
            "routers": ["192.168.1.1"],
            "ssid_instances": [
                {
                    "router_host": "192.168.1.1",
                    "router_name": "Test Router",
                    "ssid_info": {
                        "ssid_name": "TestNetwork",
                        "disabled": False,
                        "router_host": "192.168.1.1",
                        "ssid_interface": "wlan0",
                        "radio": "radio0",
                    },
                }
            ],
            "areas": set(),
        }

        # Note: WrtGlobalSSIDBinarySensor needs hass for dynamic lookups,
        # but for basic init test we can verify constructor args
        sensor = WrtGlobalSSIDBinarySensor(
            mock_coordinator, ssid_name, ssid_group, mock_config_entry
        )

        assert sensor.coordinator == mock_coordinator
        assert sensor._ssid_name == ssid_name
        assert sensor._ssid_group == ssid_group
        assert "TestNetwork" in sensor._attr_name
        assert sensor._attr_unique_id is not None


class TestWrtDevicePresenceSensor:
    """Test device presence sensor."""

    def test_init(self, mock_coordinator, mock_config_entry):
        """Test sensor initialization."""
        device_mac = "AA:BB:CC:DD:EE:FF"
        sensor = WrtDevicePresenceSensor(mock_coordinator, device_mac, mock_config_entry)

        assert sensor.coordinator == mock_coordinator
        assert sensor._mac == device_mac.upper()
        assert sensor._attr_unique_id is not None

    def test_is_on_connected(self, mock_coordinator, mock_config_entry):
        """Test sensor when device is connected."""
        device_mac = "AA:BB:CC:DD:EE:FF"
        sensor = WrtDevicePresenceSensor(mock_coordinator, device_mac, mock_config_entry)

        assert sensor.is_on is True

    def test_is_on_disconnected(self, mock_coordinator, mock_config_entry):
        """Test sensor when device is disconnected."""
        # Set device as disconnected
        mock_coordinator.data["devices"][0][ATTR_CONNECTED] = False
        device_mac = "AA:BB:CC:DD:EE:FF"
        sensor = WrtDevicePresenceSensor(mock_coordinator, device_mac, mock_config_entry)

        assert sensor.is_on is False

    def test_is_on_missing_device(self, mock_coordinator, mock_config_entry):
        """Test sensor when device is missing."""
        device_mac = "FF:FF:FF:FF:FF:FF"  # Non-existent device
        sensor = WrtDevicePresenceSensor(mock_coordinator, device_mac, mock_config_entry)

        assert sensor.is_on is False

    def test_available_no_data(self, mock_coordinator, mock_config_entry):
        """Test sensor availability when no data."""
        mock_coordinator.data = None
        device_mac = "AA:BB:CC:DD:EE:FF"
        sensor = WrtDevicePresenceSensor(mock_coordinator, device_mac, mock_config_entry)

        assert sensor.is_on is False


class TestWrtInterfaceStatusSensor:
    """Test interface status sensor."""

    def test_init(self, mock_coordinator, mock_config_entry):
        """Test sensor initialization."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface_name = "wlan0"
        sensor = WrtInterfaceStatusSensor(
            mock_coordinator, router_host, router_name, interface_name, mock_config_entry
        )

        assert sensor.coordinator == mock_coordinator
        assert sensor._router_host == router_host
        assert sensor._router_name == router_name
        assert sensor._interface_name == interface_name
        assert sensor._attr_unique_id is not None

    def test_is_on_interface_up(self, mock_coordinator, mock_config_entry):
        """Test sensor when interface is up."""
        # Update mock data to include carrier and up status
        mock_coordinator.data["interfaces"]["192.168.1.1"]["wlan0"] = {
            "status": "up",
            "up": True,
            "carrier": True,
        }

        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface_name = "wlan0"
        sensor = WrtInterfaceStatusSensor(
            mock_coordinator, router_host, router_name, interface_name, mock_config_entry
        )

        assert sensor.is_on is True

    def test_is_on_interface_down(self, mock_coordinator, mock_config_entry):
        """Test sensor when interface is down."""
        # Update mock data to reflect down state
        mock_coordinator.data["interfaces"]["192.168.1.1"]["eth0"] = {
            "status": "down",
            "up": False,
            "carrier": False,
        }

        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface_name = "eth0"
        sensor = WrtInterfaceStatusSensor(
            mock_coordinator, router_host, router_name, interface_name, mock_config_entry
        )

        assert sensor.is_on is False

    def test_is_on_missing_interface(self, mock_coordinator, mock_config_entry):
        """Test sensor when interface doesn't exist."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface_name = "nonexistent0"
        sensor = WrtInterfaceStatusSensor(
            mock_coordinator, router_host, router_name, interface_name, mock_config_entry
        )

        assert sensor.is_on is False

    def test_is_on_missing_router(self, mock_coordinator, mock_config_entry):
        """Test sensor when router doesn't exist."""
        router_host = "192.168.1.99"
        router_name = "Missing Router"
        interface_name = "wlan0"
        sensor = WrtInterfaceStatusSensor(
            mock_coordinator, router_host, router_name, interface_name, mock_config_entry
        )

        assert sensor.is_on is False
