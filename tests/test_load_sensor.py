"""Tests for WrtManagerLoadAverageSensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorStateClass

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.sensor import WrtManagerLoadAverageSensor


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with load average data."""
    coordinator = MagicMock(spec=WrtManagerCoordinator)
    coordinator.last_update_success = True
    coordinator.data = {
        "system_info": {
            "192.168.1.1": {
                "uptime": 3600,
                "model": "Test Router",
                "release": {"version": "22.03.0"},
                "memory": {"total": 262144000, "free": 131072000},
                "load": [32768, 24576, 16384],  # 0.5, 0.375, 0.25
            },
        },
        "devices": [],
    }
    return coordinator


class TestWrtManagerLoadAverageSensor:
    """Tests for the load average sensor."""

    def test_sensor_properties(self, mock_coordinator):
        """Verify sensor metadata."""
        sensor = WrtManagerLoadAverageSensor(
            mock_coordinator, "192.168.1.1", "Main Router", 0, "1m"
        )

        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT
        assert sensor._attr_icon == "mdi:gauge"
        assert getattr(sensor, "_attr_native_unit_of_measurement", None) is None
        assert getattr(sensor, "_attr_device_class", None) is None
        assert "load_average_1m" in sensor.unique_id
        assert "Load Average 1m" in sensor.name

    def test_native_value_1m(self, mock_coordinator):
        """Verify 1m load average is correctly calculated."""
        sensor = WrtManagerLoadAverageSensor(
            mock_coordinator, "192.168.1.1", "Main Router", 0, "1m"
        )
        assert sensor.native_value == 0.5

    def test_native_value_5m(self, mock_coordinator):
        """Verify 5m load average is correctly calculated."""
        sensor = WrtManagerLoadAverageSensor(
            mock_coordinator, "192.168.1.1", "Main Router", 1, "5m"
        )
        assert sensor.native_value == 0.38

    def test_native_value_15m(self, mock_coordinator):
        """Verify 15m load average is correctly calculated."""
        sensor = WrtManagerLoadAverageSensor(
            mock_coordinator, "192.168.1.1", "Main Router", 2, "15m"
        )
        assert sensor.native_value == 0.25

    def test_native_value_missing_load(self, mock_coordinator):
        """Verify None when load key is absent."""
        del mock_coordinator.data["system_info"]["192.168.1.1"]["load"]
        sensor = WrtManagerLoadAverageSensor(
            mock_coordinator, "192.168.1.1", "Main Router", 0, "1m"
        )
        assert sensor.native_value is None

    def test_native_value_short_load(self, mock_coordinator):
        """Verify None when load array is too short for the requested index."""
        mock_coordinator.data["system_info"]["192.168.1.1"]["load"] = [32768]
        sensor = WrtManagerLoadAverageSensor(
            mock_coordinator, "192.168.1.1", "Main Router", 1, "5m"
        )
        assert sensor.native_value is None

    def test_native_value_no_system_data(self, mock_coordinator):
        """Verify None when system_info is empty."""
        mock_coordinator.data = {"devices": [], "system_info": {}}
        sensor = WrtManagerLoadAverageSensor(
            mock_coordinator, "192.168.1.1", "Main Router", 0, "1m"
        )
        assert sensor.native_value is None
