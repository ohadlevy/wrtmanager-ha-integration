"""Tests for WrtManagerUptimeSensor."""

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
                "uptime": 90061,  # 1d 1h 1m 1s
                "model": "Test Router",
                "release": {"version": "22.03.0"},
                "memory": {"total": 262144000, "free": 131072000},
            },
        },
        "devices": [],
    }
    return coordinator


class TestWrtManagerUptimeSensor:
    """Tests for the uptime sensor."""

    def test_sensor_properties(self, mock_coordinator):
        """Verify sensor metadata."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")

        assert sensor._attr_device_class == SensorDeviceClass.DURATION
        assert sensor._attr_state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor._attr_icon == "mdi:timer-outline"
        assert "uptime" in sensor.unique_id
        assert "Uptime" in sensor.name

    def test_native_value_returns_seconds(self, mock_coordinator):
        """Verify native_value returns uptime in seconds."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        assert sensor.native_value == 90061

    def test_extra_state_attributes_breakdown(self, mock_coordinator):
        """Verify extra_state_attributes breaks uptime into d/h/m/s."""
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 1
        assert attrs["hours"] == 1
        assert attrs["minutes"] == 1
        assert attrs["seconds"] == 1
        assert attrs["uptime_formatted"] == "1d 01:01:01"

    def test_extra_state_attributes_zero_days(self, mock_coordinator):
        """Verify formatting when uptime is less than one day."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 3723  # 1h 2m 3s
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 0
        assert attrs["hours"] == 1
        assert attrs["minutes"] == 2
        assert attrs["seconds"] == 3
        assert attrs["uptime_formatted"] == "0d 01:02:03"

    def test_native_value_none_when_no_uptime(self, mock_coordinator):
        """Verify native_value is None when uptime key is absent."""
        del mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"]
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")

        assert sensor.native_value is None

    def test_extra_state_attributes_empty_when_no_uptime(self, mock_coordinator):
        """Verify extra_state_attributes is empty when uptime is unavailable."""
        del mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"]
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")

        assert sensor.extra_state_attributes == {}

    def test_unavailable_when_no_system_data(self, mock_coordinator):
        """Verify sensor is unavailable when system_info is missing."""
        mock_coordinator.data = {"devices": [], "system_info": {}}
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")

        assert not sensor.available

    def test_large_uptime(self, mock_coordinator):
        """Verify formatting for long uptimes (>99 days)."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["uptime"] = 8640000  # 100 days
        sensor = WrtManagerUptimeSensor(mock_coordinator, "192.168.1.1", "Main Router")
        attrs = sensor.extra_state_attributes

        assert attrs["days"] == 100
        assert attrs["hours"] == 0
        assert attrs["minutes"] == 0
        assert attrs["seconds"] == 0
