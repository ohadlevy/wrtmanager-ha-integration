"""Tests for router uptime sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.sensor import WrtManagerUptimeSensor


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with system info including uptime."""
    coordinator = MagicMock(spec=WrtManagerCoordinator)
    coordinator.last_update_success = True
    coordinator.data = {
        "system_info": {
            "192.168.1.1": {
                "uptime": 864000,  # 10 days
                "model": "Test Router",
                "release": {"version": "23.05.0"},
                "memory": {"total": 268435456, "free": 134217728},
            }
        },
        "devices": [],
        "interfaces": {},
    }
    return coordinator


class TestWrtManagerUptimeSensor:
    """Test uptime sensor functionality."""

    def test_sensor_properties(self, mock_coordinator):
        """Test that sensor has correct properties."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")

        assert sensor._attr_device_class == SensorDeviceClass.DURATION
        assert sensor._attr_state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor._attr_icon == "mdi:clock-outline"
        assert "uptime" in sensor._attr_unique_id

    def test_native_value_returns_uptime_seconds(self, mock_coordinator):
        """Test that native_value returns uptime in seconds."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.native_value == 864000

    def test_native_value_none_when_no_data(self, mock_coordinator):
        """Test that native_value returns None when system data is absent."""
        mock_coordinator.data = {"system_info": {}, "devices": [], "interfaces": {}}
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.native_value is None

    def test_native_value_none_when_uptime_missing(self, mock_coordinator):
        """Test that native_value returns None when uptime key is missing."""
        mock_coordinator.data["system_info"]["192.168.1.1"].pop("uptime")
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.native_value is None

    def test_extra_state_attributes_10_days(self, mock_coordinator):
        """Test extra_state_attributes for 10-day uptime."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 10
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 0
        assert attrs["uptime_formatted"] == "10d 0h 0m"

    def test_extra_state_attributes_complex_uptime(self, mock_coordinator):
        """Test extra_state_attributes with hours and minutes."""
        # 2 days, 3 hours, 45 minutes = 2*86400 + 3*3600 + 45*60
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = (
            2 * 86400 + 3 * 3600 + 45 * 60
        )
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 2
        assert attrs["hours"] == 3
        assert attrs["minutes"] == 45
        assert attrs["uptime_formatted"] == "2d 3h 45m"

    def test_extra_state_attributes_empty_when_no_uptime(self, mock_coordinator):
        """Test that extra_state_attributes returns empty dict when uptime is missing."""
        mock_coordinator.data["system_info"]["192.168.1.1"].pop("uptime")
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.extra_state_attributes == {}

    def test_extra_state_attributes_zero_uptime(self, mock_coordinator):
        """Test extra_state_attributes with zero uptime (just booted)."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 0
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 0
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 0
        assert attrs["uptime_formatted"] == "0d 0h 0m"

    def test_unique_id_per_router(self, mock_coordinator):
        """Test that each router gets a distinct unique ID."""
        mock_coordinator.data["system_info"]["192.168.1.2"] = {
            "uptime": 100,
            "model": "Router 2",
        }
        sensor1 = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Router One")
        sensor2 = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.2", "Router Two")
        assert sensor1._attr_unique_id != sensor2._attr_unique_id

    def test_availability(self, mock_coordinator):
        """Test sensor availability based on coordinator state."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Test Router")
        assert sensor.available is True

        mock_coordinator.last_update_success = False
        assert sensor.available is False
