"""Tests for the router uptime sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.sensor import WrtManagerUptimeSensor


class TestWrtManagerUptimeSensor:
    """Test WrtManagerUptimeSensor functionality."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with system info data."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = {
            "system_info": {
                "192.168.1.1": {
                    "uptime": 90061,  # 1 day, 1 hour, 1 minute, 1 second
                    "memory": {"total": 262144000, "free": 131072000},
                    "model": "Test Router",
                }
            }
        }
        return coordinator

    @pytest.fixture
    def uptime_sensor(self, mock_coordinator):
        """Create an uptime sensor instance."""
        return WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")

    def test_sensor_attributes(self, uptime_sensor):
        """Test sensor has correct device class, state class, and unit."""
        assert uptime_sensor._attr_device_class == SensorDeviceClass.DURATION
        assert uptime_sensor._attr_state_class == SensorStateClass.TOTAL_INCREASING
        assert uptime_sensor._attr_native_unit_of_measurement in ("s", "s")  # UnitOfTime.SECONDS
        assert uptime_sensor._attr_icon == "mdi:clock-outline"

    def test_native_value(self, uptime_sensor):
        """Test native value returns uptime in seconds."""
        assert uptime_sensor.native_value == 90061

    def test_native_value_missing(self, mock_coordinator):
        """Test native value returns None when uptime not in data."""
        mock_coordinator.data["system_info"]["192.168.1.1"].pop("uptime")
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.native_value is None

    def test_native_value_no_data(self, mock_coordinator):
        """Test native value returns None when coordinator has no data."""
        mock_coordinator.data = None
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.native_value is None

    def test_extra_state_attributes(self, uptime_sensor):
        """Test extra attributes provide human-readable uptime breakdown."""
        attrs = uptime_sensor.extra_state_attributes
        # 90061 seconds = 1 day, 1 hour, 1 minute, 1 second
        assert attrs["days"] == 1
        assert attrs["hours"] == 1
        assert attrs["minutes"] == 1
        assert attrs["uptime_formatted"] == "1d 1h 1m"

    def test_extra_state_attributes_zero(self, mock_coordinator):
        """Test extra attributes when uptime is 0."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 0
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        attrs = sensor.extra_state_attributes
        assert attrs["days"] == 0
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 0
        assert attrs["uptime_formatted"] == "0d 0h 0m"

    def test_extra_state_attributes_none(self, mock_coordinator):
        """Test extra attributes returns empty dict when uptime is None."""
        mock_coordinator.data["system_info"]["192.168.1.1"].pop("uptime")
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.extra_state_attributes == {}

    def test_unique_id(self, uptime_sensor):
        """Test unique ID is correctly formed."""
        assert uptime_sensor._attr_unique_id == "wrtmanager_test_router_uptime"

    def test_name(self, uptime_sensor):
        """Test sensor name is correctly formed."""
        assert uptime_sensor._attr_name == "Test Router Uptime"

    def test_availability(self, uptime_sensor):
        """Test sensor is available when coordinator has data."""
        assert uptime_sensor.available is True

    def test_unavailability(self, mock_coordinator):
        """Test sensor is unavailable when coordinator update fails."""
        mock_coordinator.last_update_success = False
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.available is False

    def test_uptime_formatting_large_value(self, mock_coordinator):
        """Test formatting for large uptime values (multiple days)."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 864000  # 10 days
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        attrs = sensor.extra_state_attributes
        assert attrs["days"] == 10
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 0
        assert attrs["uptime_formatted"] == "10d 0h 0m"

    def test_uptime_formatting_minutes_only(self, mock_coordinator):
        """Test formatting when uptime is only minutes."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 300  # 5 minutes
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        attrs = sensor.extra_state_attributes
        assert attrs["days"] == 0
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 5
        assert attrs["uptime_formatted"] == "0d 0h 5m"
