"""Tests for router uptime sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.sensor import WrtManagerUptimeSensor


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with uptime data."""
    coordinator = MagicMock(spec=WrtManagerCoordinator)
    coordinator.last_update_success = True
    coordinator.data = {
        "system_info": {
            "192.168.1.1": {
                "uptime": 353156,
                "model": "Test Router",
                "release": {"version": "22.03.0"},
                "memory": {"total": 124063744, "free": 57556992},
            }
        }
    }
    return coordinator


class TestUptimeSensorProperties:
    """Test uptime sensor properties and metadata."""

    def test_sensor_properties(self, mock_coordinator):
        """Test uptime sensor basic properties."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")

        assert sensor._attr_device_class == SensorDeviceClass.DURATION
        assert sensor._attr_state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor._attr_icon == "mdi:clock-outline"
        assert "uptime" in sensor.unique_id
        assert "Uptime" in sensor.name

    def test_unique_id_contains_router(self, mock_coordinator):
        """Test that unique ID encodes the router name."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        assert "main_router" in sensor.unique_id

    def test_availability(self, mock_coordinator):
        """Test sensor availability."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        assert sensor.available

        mock_coordinator.last_update_success = False
        assert not sensor.available

    def test_unavailable_when_no_system_data(self):
        """Test sensor unavailable when no system data."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = {"system_info": {}}

        sensor = WrtManagerUptimeSensor(coordinator, "192.168.1.1", "Main Router")
        assert not sensor.available


class TestUptimeSensorValue:
    """Test uptime sensor native value."""

    def test_native_value(self, mock_coordinator):
        """Test uptime returns seconds."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        assert sensor.native_value == 353156

    def test_native_value_none_when_no_data(self):
        """Test returns None when coordinator has no data."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = None

        sensor = WrtManagerUptimeSensor(coordinator, "192.168.1.1", "Main Router")
        assert sensor.native_value is None

    def test_native_value_zero_uptime(self, mock_coordinator):
        """Test zero uptime."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 0
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        assert sensor.native_value == 0


class TestUptimeSensorAttributes:
    """Test uptime sensor extra state attributes."""

    def test_formatted_attributes(self, mock_coordinator):
        """Test uptime formatted attributes - 353156s = 4d 2h 5m."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        attrs = sensor.extra_state_attributes

        # 353156 seconds = 4 days, 2 hours, 5 minutes, 56 seconds
        assert attrs["days"] == 4
        assert attrs["hours"] == 2
        assert attrs["minutes"] == 5
        assert "uptime_formatted" in attrs
        assert "4d" in attrs["uptime_formatted"]
        assert "2h" in attrs["uptime_formatted"]
        assert "5m" in attrs["uptime_formatted"]

    def test_formatted_uptime_days_only(self, mock_coordinator):
        """Test formatted uptime with only days and minutes."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 86460  # 1d 1m
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 1
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 1
        assert "1d" in attrs["uptime_formatted"]
        assert "h" not in attrs["uptime_formatted"]  # hours omitted when 0
        assert "1m" in attrs["uptime_formatted"]

    def test_formatted_uptime_minutes_only(self, mock_coordinator):
        """Test formatted uptime less than an hour."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 300  # 5m
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 0
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 5
        assert attrs["uptime_formatted"] == "5m"

    def test_formatted_uptime_hours_and_minutes(self, mock_coordinator):
        """Test formatted uptime with hours and minutes."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 3900  # 1h 5m
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 0
        assert attrs["hours"] == 1
        assert attrs["minutes"] == 5
        assert "1h" in attrs["uptime_formatted"]
        assert "5m" in attrs["uptime_formatted"]
        assert "d" not in attrs["uptime_formatted"]

    def test_no_attributes_when_no_data(self):
        """Test empty attributes when no data."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = None

        sensor = WrtManagerUptimeSensor(coordinator, "192.168.1.1", "Main Router")
        assert sensor.extra_state_attributes == {}
