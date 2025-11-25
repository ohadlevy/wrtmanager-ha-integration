"""Simple tests for WrtManager sensors."""

from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.wrtmanager.sensor import (
    WrtManagerDeviceCountSensor,
    WrtManagerSignalStrengthSensor,
    async_setup_entry,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return ConfigEntry(
        version=1,
        minor_version=0,
        domain="wrtmanager",
        title="Test WrtManager",
        data={"routers": [{"host": "192.168.1.1", "username": "test", "password": "test"}]},
        source="user",
        entry_id="test_entry",
        unique_id="test_unique_id",
        discovery_keys=set(),
        options={},
        subentries_data={},
    )


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock()
    coordinator.data = {
        "devices": [
            {
                "mac": "AA:BB:CC:DD:EE:FF",
                "hostname": "test-device",
                "router": "192.168.1.1",
                "signal_dbm": -45,
                "interface": "wlan0",
            }
        ],
        "system_info": {"192.168.1.1": {"hostname": "OpenWrt", "uptime": 86400}},
        "ssids": {"192.168.1.1": [{"ssid_name": "TestNetwork", "ssid_interface": "wlan0"}]},
        "interfaces": {"192.168.1.1": {"wlan0": {"up": True}}},
        "routers": ["192.168.1.1"],
        "total_devices": 1,
    }
    coordinator.async_add_listener = Mock()
    return coordinator


class TestSensorSetup:
    """Test sensor setup."""

    async def test_async_setup_entry(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test setting up sensors."""
        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        async_add_entities = AsyncMock()

        await async_setup_entry(hass, mock_config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities = async_add_entities.call_args[0][0]
        assert len(entities) > 0


class TestDeviceCountSensor:
    """Test device count sensor."""

    def test_init(self, mock_coordinator):
        """Test device count sensor initialization."""
        sensor = WrtManagerDeviceCountSensor(
            coordinator=mock_coordinator,
            router_host="192.168.1.1",
        )

        assert sensor.router_host == "192.168.1.1"
        assert sensor.name == "WrtManager 192.168.1.1 Device Count"
        assert sensor.unique_id == "wrtmanager_192.168.1.1_device_count"

    def test_native_value(self, mock_coordinator):
        """Test device count sensor value."""
        sensor = WrtManagerDeviceCountSensor(
            coordinator=mock_coordinator,
            router_host="192.168.1.1",
        )

        assert sensor.native_value == 1

    def test_native_value_no_devices(self, mock_coordinator):
        """Test device count sensor with no devices."""
        mock_coordinator.data = {"devices": []}

        sensor = WrtManagerDeviceCountSensor(
            coordinator=mock_coordinator,
            router_host="192.168.1.1",
        )

        assert sensor.native_value == 0

    def test_device_info(self, mock_coordinator):
        """Test device count sensor device info."""
        sensor = WrtManagerDeviceCountSensor(
            coordinator=mock_coordinator,
            router_host="192.168.1.1",
        )

        device_info = sensor.device_info
        assert device_info["identifiers"] == {("wrtmanager", "192.168.1.1")}
        assert device_info["name"] == "OpenWrt (192.168.1.1)"


class TestSignalStrengthSensor:
    """Test signal strength sensor."""

    def test_init(self, mock_coordinator):
        """Test signal strength sensor initialization."""
        device_data = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "hostname": "test-device",
            "signal_dbm": -45,
        }

        sensor = WrtManagerSignalStrengthSensor(
            coordinator=mock_coordinator,
            device_mac="AA:BB:CC:DD:EE:FF",
            device_data=device_data,
        )

        assert sensor.device_mac == "AA:BB:CC:DD:EE:FF"
        assert sensor.name == "test-device Signal Strength"
        assert sensor.unique_id == "wrtmanager_AA:BB:CC:DD:EE:FF_signal_strength"

    def test_native_value(self, mock_coordinator):
        """Test signal strength sensor value."""
        device_data = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "hostname": "test-device",
            "signal_dbm": -45,
        }

        sensor = WrtManagerSignalStrengthSensor(
            coordinator=mock_coordinator,
            device_mac="AA:BB:CC:DD:EE:FF",
            device_data=device_data,
        )

        assert sensor.native_value == -45

    def test_native_value_no_signal(self, mock_coordinator):
        """Test signal strength sensor with no signal data."""
        device_data = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "hostname": "test-device",
        }

        sensor = WrtManagerSignalStrengthSensor(
            coordinator=mock_coordinator,
            device_mac="AA:BB:CC:DD:EE:FF",
            device_data=device_data,
        )

        assert sensor.native_value is None

    def test_device_info(self, mock_coordinator):
        """Test signal strength sensor device info."""
        device_data = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "hostname": "test-device",
            "signal_dbm": -45,
        }

        sensor = WrtManagerSignalStrengthSensor(
            coordinator=mock_coordinator,
            device_mac="AA:BB:CC:DD:EE:FF",
            device_data=device_data,
        )

        device_info = sensor.device_info
        assert device_info["identifiers"] == {("wrtmanager", "AA:BB:CC:DD:EE:FF")}
        assert device_info["name"] == "test-device"

    def test_extra_state_attributes(self, mock_coordinator):
        """Test signal strength sensor extra state attributes."""
        device_data = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "hostname": "test-device",
            "signal_dbm": -45,
            "interface": "wlan0",
            "router": "192.168.1.1",
        }

        sensor = WrtManagerSignalStrengthSensor(
            coordinator=mock_coordinator,
            device_mac="AA:BB:CC:DD:EE:FF",
            device_data=device_data,
        )

        attributes = sensor.extra_state_attributes
        assert attributes["interface"] == "wlan0"
        assert attributes["router"] == "192.168.1.1"
        assert attributes["mac"] == "AA:BB:CC:DD:EE:FF"
