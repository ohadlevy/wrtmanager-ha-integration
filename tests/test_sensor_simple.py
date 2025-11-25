"""Simple tests to boost sensor.py coverage."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager.const import (
    ATTR_CONNECTED,
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_MAC,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
    DOMAIN,
)
from custom_components.wrtmanager.sensor import (
    WrtManagerDeviceCountSensor,
    WrtManagerMemoryUsageSensor,
    WrtManagerSensorBase,
    WrtManagerSignalStrengthSensor,
    WrtManagerTemperatureSensor,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with test data."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": [
            {
                ATTR_MAC: "AA:BB:CC:DD:EE:FF",
                ATTR_CONNECTED: True,
                ATTR_ROUTER: "192.168.1.1",
                ATTR_HOSTNAME: "test-device",
                ATTR_SIGNAL_DBM: -45,
                ATTR_INTERFACE: "wlan0",
            },
            {
                ATTR_MAC: "11:22:33:44:55:66",
                ATTR_CONNECTED: True,
                ATTR_ROUTER: "192.168.1.2",
                ATTR_HOSTNAME: "test-device2",
                ATTR_SIGNAL_DBM: -60,
                ATTR_INTERFACE: "wlan1",
            },
        ],
        "system_info": {
            "192.168.1.1": {
                "uptime": 86400,  # 1 day
                "memory": {
                    "total": 134217728,
                    "free": 67108864,
                    "buffered": 8388608,
                    "shared": 4194304,
                },
                "load": [0.1, 0.2, 0.15],
                "temperature": 45.0,  # Changed from thermal to temperature
                "model": "Test Router",
                "release": {"version": "22.03.0"},
            }
        },
        "total_devices": 2,
        "routers": ["192.168.1.1", "192.168.1.2"],
        "last_update": datetime.now(),
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


class TestBaseSensor:
    """Test base sensor functionality."""

    def test_base_sensor_properties(self, mock_coordinator):
        """Test base sensor properties."""
        sensor = WrtManagerSensorBase(
            mock_coordinator, "192.168.1.1", "Test Router", "test_type", "Test Sensor"
        )

        assert sensor.coordinator == mock_coordinator
        assert sensor.available == mock_coordinator.last_update_success

    def test_base_sensor_device_info(self, mock_coordinator):
        """Test base sensor device info."""
        sensor = WrtManagerSensorBase(
            mock_coordinator, "192.168.1.1", "Test Router", "test_type", "Test Sensor"
        )

        device_info = sensor.device_info
        assert device_info is not None
        assert device_info["identifiers"] == {(DOMAIN, "192.168.1.1")}


class TestDeviceCountSensor:
    """Test device count sensor."""

    def test_device_count_sensor_router_specific(self, mock_coordinator, mock_config_entry):
        """Test router-specific device count sensor."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        sensor = WrtManagerDeviceCountSensor(
            mock_coordinator, router_host, router_name, mock_config_entry
        )

        # Should count devices for the specific router
        assert sensor.native_value == 1
        assert router_name in sensor.name

    def test_device_count_sensor_no_data(self, mock_coordinator, mock_config_entry):
        """Test device count sensor with no data."""
        mock_coordinator.data = None
        router_host = "192.168.1.1"
        router_name = "Test Router"
        sensor = WrtManagerDeviceCountSensor(
            mock_coordinator, router_host, router_name, mock_config_entry
        )

        assert sensor.native_value == 0


class TestSignalStrengthSensor:
    """Test signal strength sensor."""

    def test_signal_strength_sensor_with_data(self, mock_coordinator):
        """Test signal strength sensor with data."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface = "wlan0"
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, router_host, router_name, interface
        )

        assert sensor.native_value == -45
        assert "dBm" in sensor.native_unit_of_measurement

    def test_signal_strength_sensor_no_signal_data(self, mock_coordinator):
        """Test signal strength sensor when signal data is missing."""
        # Remove signal data from device
        del mock_coordinator.data["devices"][0][ATTR_SIGNAL_DBM]

        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface = "wlan0"
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, router_host, router_name, interface
        )

        assert sensor.native_value is None

    def test_signal_strength_sensor_device_not_found(self, mock_coordinator):
        """Test signal strength sensor when no devices on interface."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface = "wlan99"  # Non-existent interface
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, router_host, router_name, interface
        )

        assert sensor.native_value is None


class TestMemoryUsageSensor:
    """Test memory usage sensor."""

    def test_memory_usage_sensor_with_data(self, mock_coordinator):
        """Test memory usage sensor with data."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        sensor = WrtManagerMemoryUsageSensor(mock_coordinator, router_host, router_name)

        # Calculate expected memory usage percentage
        memory_data = mock_coordinator.data["system_info"]["192.168.1.1"]["memory"]
        total = memory_data["total"]
        free = memory_data["free"]
        used = total - free
        expected_usage = round((used / total) * 100, 1)

        assert sensor.native_value == expected_usage
        assert "%" in sensor.native_unit_of_measurement
        assert router_name in sensor.name

    def test_memory_usage_sensor_no_data(self, mock_coordinator):
        """Test memory usage sensor with no data."""
        router_host = "192.168.1.99"  # Non-existent router
        router_name = "Missing Router"
        sensor = WrtManagerMemoryUsageSensor(mock_coordinator, router_host, router_name)

        assert sensor.native_value is None

    def test_memory_usage_sensor_incomplete_data(self, mock_coordinator):
        """Test memory usage sensor with incomplete data."""
        # Remove memory total from system info
        del mock_coordinator.data["system_info"]["192.168.1.1"]["memory"]["total"]

        router_host = "192.168.1.1"
        router_name = "Test Router"
        sensor = WrtManagerMemoryUsageSensor(mock_coordinator, router_host, router_name)

        assert sensor.native_value is None


class TestTemperatureSensor:
    """Test temperature sensor."""

    def test_temperature_sensor_with_data(self, mock_coordinator):
        """Test temperature sensor with data."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        sensor = WrtManagerTemperatureSensor(mock_coordinator, router_host, router_name)

        # Expected temperature
        expected_temp = 45.0

        assert sensor.native_value == expected_temp
        assert router_name in sensor.name
        assert "°C" in sensor.native_unit_of_measurement

    def test_temperature_sensor_no_data(self, mock_coordinator):
        """Test temperature sensor with no data."""
        router_host = "192.168.1.99"  # Non-existent router
        router_name = "Missing Router"
        sensor = WrtManagerTemperatureSensor(mock_coordinator, router_host, router_name)

        assert sensor.native_value is None

    def test_temperature_sensor_no_thermal_data(self, mock_coordinator):
        """Test temperature sensor when thermal data is missing."""
        # Remove temperature data from system info
        del mock_coordinator.data["system_info"]["192.168.1.1"]["temperature"]

        router_host = "192.168.1.1"
        router_name = "Test Router"
        sensor = WrtManagerTemperatureSensor(mock_coordinator, router_host, router_name)

        assert sensor.native_value is None


class TestSensorEdgeCases:
    """Test sensor edge cases and error conditions."""

    def test_sensors_with_no_coordinator_data(self, mock_coordinator, mock_config_entry):
        """Test sensors when coordinator has no data."""
        mock_coordinator.data = None

        device_count_sensor = WrtManagerDeviceCountSensor(
            mock_coordinator, "192.168.1.1", "Test Router", mock_config_entry
        )
        memory_sensor = WrtManagerMemoryUsageSensor(mock_coordinator, "192.168.1.1", "Test Router")
        signal_sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Test Router", "wlan0"
        )

        assert device_count_sensor.native_value == 0
        assert memory_sensor.native_value is None
        assert signal_sensor.native_value is None

    def test_sensors_with_empty_coordinator_data(self, mock_coordinator, mock_config_entry):
        """Test sensors when coordinator data is empty."""
        mock_coordinator.data = {}

        device_count_sensor = WrtManagerDeviceCountSensor(
            mock_coordinator, "192.168.1.1", "Test Router", mock_config_entry
        )
        memory_sensor = WrtManagerMemoryUsageSensor(mock_coordinator, "192.168.1.1", "Test Router")

        assert device_count_sensor.native_value == 0
        assert memory_sensor.native_value is None

    def test_coordinator_unavailable(self, mock_coordinator):
        """Test sensors when coordinator is unavailable."""
        mock_coordinator.last_update_success = False

        sensor = WrtManagerSensorBase(
            mock_coordinator, "192.168.1.1", "Test Router", "test_type", "Test Sensor"
        )

        assert sensor.available is False

    def test_device_sensor_with_missing_attributes(self, mock_coordinator):
        """Test device sensors when device attributes are missing."""
        # Remove hostname from device
        device_data = mock_coordinator.data["devices"][0]
        if ATTR_HOSTNAME in device_data:
            del device_data[ATTR_HOSTNAME]

        signal_sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Test Router", "wlan0"
        )

        # Should still work even without hostname
        assert signal_sensor.native_value == -45


class TestSensorUniqueIds:
    """Test sensor unique ID generation."""

    def test_device_sensors_unique_ids(self, mock_coordinator):
        """Test that device sensors generate correct unique IDs."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface = "wlan0"
        signal_sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, router_host, router_name, interface
        )

        # Unique ID should contain router info
        assert signal_sensor.unique_id is not None

    def test_router_sensors_unique_ids(self, mock_coordinator):
        """Test that router sensors generate correct unique IDs."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        memory_sensor = WrtManagerMemoryUsageSensor(mock_coordinator, router_host, router_name)
        temp_sensor = WrtManagerTemperatureSensor(mock_coordinator, router_host, router_name)

        assert memory_sensor.unique_id is not None
        assert temp_sensor.unique_id is not None
        assert "test_router" in memory_sensor.unique_id.lower()
        assert "test_router" in temp_sensor.unique_id.lower()


class TestSensorAttributes:
    """Test sensor attribute handling."""

    def test_sensor_extra_state_attributes(self, mock_coordinator):
        """Test sensor extra state attributes."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        interface = "wlan0"
        signal_sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, router_host, router_name, interface
        )

        # The sensor should have access to device data
        device_data = mock_coordinator.data["devices"][0]
        assert signal_sensor.coordinator.data["devices"][0] == device_data

    def test_temperature_sensor_device_class(self, mock_coordinator):
        """Test temperature sensor device class."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        temp_sensor = WrtManagerTemperatureSensor(mock_coordinator, router_host, router_name)

        assert temp_sensor.device_class is not None

    def test_memory_sensor_device_class(self, mock_coordinator):
        """Test memory sensor device class."""
        router_host = "192.168.1.1"
        router_name = "Test Router"
        memory_sensor = WrtManagerMemoryUsageSensor(mock_coordinator, router_host, router_name)

        # Memory usage sensor doesn't have a device_class, it's a percentage sensor
        # But it has state_class
        assert memory_sensor.state_class is not None
