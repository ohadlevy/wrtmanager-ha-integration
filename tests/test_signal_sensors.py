"""
Test signal strength and signal quality sensors.

These tests verify the new Phase 4 enhanced sensor functionality.
"""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.wrtmanager.const import (
    ATTR_HOSTNAME,
    ATTR_INTERFACE,
    ATTR_MAC,
    ATTR_ROUTER,
    ATTR_SIGNAL_DBM,
)
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.sensor import (
    WrtManagerSignalQualitySensor,
    WrtManagerSignalStrengthSensor,
)


class TestSignalStrengthSensor:
    """Test signal strength sensor functionality."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with signal data."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = {
            "devices": [
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -45,
                    ATTR_MAC: "aa:bb:cc:dd:ee:01",
                    ATTR_HOSTNAME: "laptop",
                },
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -65,
                    ATTR_MAC: "aa:bb:cc:dd:ee:02",
                    ATTR_HOSTNAME: "phone",
                },
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan1",
                    ATTR_SIGNAL_DBM: -55,
                    ATTR_MAC: "aa:bb:cc:dd:ee:03",
                    ATTR_HOSTNAME: "tablet",
                },
                {
                    ATTR_ROUTER: "192.168.1.2",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -70,
                    ATTR_MAC: "aa:bb:cc:dd:ee:04",
                    ATTR_HOSTNAME: "camera",
                },
            ],
            "system_info": {
                "192.168.1.1": {
                    "model": "Test Router",
                    "release": {"version": "22.03.0"},
                },
                "192.168.1.2": {
                    "model": "Secondary Router",
                    "release": {"version": "22.03.0"},
                },
            },
        }
        return coordinator

    def test_signal_strength_sensor_properties(self, mock_coordinator):
        """Test signal strength sensor basic properties."""
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        assert sensor._attr_device_class == SensorDeviceClass.SIGNAL_STRENGTH
        assert sensor._attr_native_unit_of_measurement == "dBm"
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT
        assert sensor._attr_icon == "mdi:wifi-strength-2"
        assert "signal_strength_wlan0" in sensor.unique_id
        assert "WLAN0 Signal Strength" in sensor.name

    def test_signal_strength_calculation(self, mock_coordinator):
        """Test average signal strength calculation."""
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        # Should calculate average of -45 and -65 = -55.0
        assert sensor.native_value == -55.0

    def test_signal_strength_single_device(self, mock_coordinator):
        """Test signal strength with single device."""
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan1"
        )

        # Should return the single device's signal: -55
        assert sensor.native_value == -55.0

    def test_signal_strength_no_devices(self, mock_coordinator):
        """Test signal strength with no devices."""
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan2"
        )

        # Should return None for interface with no devices
        assert sensor.native_value is None

    def test_signal_strength_different_router(self, mock_coordinator):
        """Test signal strength filtering by router."""
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.2", "Secondary Router", "wlan0"
        )

        # Should only see device on router 192.168.1.2: -70
        assert sensor.native_value == -70.0

    def test_signal_strength_attributes(self, mock_coordinator):
        """Test signal strength sensor attributes."""
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        attributes = sensor.extra_state_attributes

        assert attributes["interface"] == "wlan0"
        assert attributes["router"] == "Main Router"
        assert attributes["device_count"] == 2  # Two devices on wlan0
        assert attributes["min_signal_dbm"] == -65
        assert attributes["max_signal_dbm"] == -45
        assert attributes["signal_range_dbm"] == 20  # -45 - (-65)
        assert attributes["devices_with_signal"] == 2

    def test_signal_strength_no_data(self):
        """Test signal strength sensor with no coordinator data."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = None

        sensor = WrtManagerSignalStrengthSensor(coordinator, "192.168.1.1", "Main Router", "wlan0")

        assert sensor.native_value is None
        assert not sensor.available  # Unavailable with no system data

    def test_signal_strength_availability(self, mock_coordinator):
        """Test signal strength sensor availability."""
        sensor = WrtManagerSignalStrengthSensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        assert sensor.available

        # Test unavailable when coordinator fails
        mock_coordinator.last_update_success = False
        assert not sensor.available


class TestSignalQualitySensor:
    """Test signal quality sensor functionality."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator with varied signal quality data."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = {
            "devices": [
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -45,  # Excellent
                    ATTR_MAC: "aa:bb:cc:dd:ee:01",
                },
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -55,  # Good
                    ATTR_MAC: "aa:bb:cc:dd:ee:02",
                },
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -65,  # Fair
                    ATTR_MAC: "aa:bb:cc:dd:ee:03",
                },
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -75,  # Poor
                    ATTR_MAC: "aa:bb:cc:dd:ee:04",
                },
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan1",
                    ATTR_SIGNAL_DBM: -40,  # Excellent
                    ATTR_MAC: "aa:bb:cc:dd:ee:05",
                },
            ],
            "system_info": {
                "192.168.1.1": {
                    "model": "Test Router",
                    "release": {"version": "22.03.0"},
                },
            },
        }
        return coordinator

    def test_signal_quality_sensor_properties(self, mock_coordinator):
        """Test signal quality sensor basic properties."""
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        assert sensor._attr_icon == "mdi:signal"
        assert "signal_quality_wlan0" in sensor.unique_id
        assert "WLAN0 Signal Quality" in sensor.name

    def test_signal_quality_calculation_good(self, mock_coordinator):
        """Test signal quality calculation - average should be Good."""
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        # Average of -45, -55, -65, -75 = -60.0 = "Good"
        assert sensor.native_value == "Good"

    def test_signal_quality_excellent(self, mock_coordinator):
        """Test excellent signal quality."""
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan1"
        )

        # Single device at -40 = "Excellent"
        assert sensor.native_value == "Excellent"

    def test_signal_quality_classification_ranges(self):
        """Test signal quality classification for different dBm values."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True

        # Test Excellent (-50 and above)
        coordinator.data = {
            "devices": [
                {
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_INTERFACE: "wlan0",
                    ATTR_SIGNAL_DBM: -40,
                    ATTR_MAC: "aa:bb:cc:dd:ee:01",
                }
            ]
        }
        sensor = WrtManagerSignalQualitySensor(coordinator, "192.168.1.1", "Main Router", "wlan0")
        assert sensor.native_value == "Excellent"

        # Test Good (-60 to -51)
        coordinator.data["devices"][0][ATTR_SIGNAL_DBM] = -55
        assert sensor.native_value == "Good"

        # Test Fair (-70 to -61)
        coordinator.data["devices"][0][ATTR_SIGNAL_DBM] = -65
        assert sensor.native_value == "Fair"

        # Test Poor (-71 and below)
        coordinator.data["devices"][0][ATTR_SIGNAL_DBM] = -80
        assert sensor.native_value == "Poor"

    def test_signal_quality_attributes(self, mock_coordinator):
        """Test signal quality sensor attributes."""
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        attributes = sensor.extra_state_attributes

        assert attributes["interface"] == "wlan0"
        assert attributes["router"] == "Main Router"
        assert attributes["total_devices"] == 4
        assert attributes["avg_signal_dbm"] == -60.0
        assert attributes["excellent_devices"] == 1
        assert attributes["good_devices"] == 1
        assert attributes["fair_devices"] == 1
        assert attributes["poor_devices"] == 1
        assert attributes["excellent_percent"] == 25.0
        assert attributes["good_percent"] == 25.0
        assert attributes["fair_percent"] == 25.0
        assert attributes["poor_percent"] == 25.0

    def test_signal_quality_attributes_single_device(self, mock_coordinator):
        """Test signal quality attributes with single device (no percentages)."""
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan1"
        )

        attributes = sensor.extra_state_attributes

        assert attributes["total_devices"] == 1
        assert attributes["avg_signal_dbm"] == -40.0
        assert attributes["excellent_devices"] == 1
        assert attributes["good_devices"] == 0
        # No percentage breakdowns for single device
        assert "excellent_percent" not in attributes

    def test_signal_quality_no_devices(self, mock_coordinator):
        """Test signal quality with no devices."""
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan2"
        )

        assert sensor.native_value is None
        attributes = sensor.extra_state_attributes
        assert attributes["total_devices"] == 0

    def test_signal_quality_availability(self, mock_coordinator):
        """Test signal quality sensor availability."""
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan0"
        )

        assert sensor.available

        # Test still available when no signal data but system data exists
        sensor = WrtManagerSignalQualitySensor(
            mock_coordinator, "192.168.1.1", "Main Router", "wlan_nonexistent"
        )
        assert sensor.available  # Available with system data present


class TestSignalSensorIntegration:
    """Test integration of signal sensors with sensor setup."""

    def test_sensor_entity_creation(self):
        """Test that signal sensors are properly created during setup."""
        # This test verifies that the sensor setup logic includes the new sensors
        # It's more of an integration test to ensure the classes are properly imported
        # and can be instantiated without errors.

        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = {
            "devices": [],
            "system_info": {
                "192.168.1.1": {
                    "model": "Test Router",
                    "release": {"version": "22.03.0"},
                },
            },
        }

        # Test instantiation doesn't raise errors
        signal_strength = WrtManagerSignalStrengthSensor(
            coordinator, "192.168.1.1", "Test Router", "wlan0"
        )
        signal_quality = WrtManagerSignalQualitySensor(
            coordinator, "192.168.1.1", "Test Router", "wlan0"
        )

        assert signal_strength is not None
        assert signal_quality is not None
        assert hasattr(signal_strength, "native_value")
        assert hasattr(signal_quality, "native_value")

    def test_unique_id_generation(self):
        """Test unique ID generation for signal sensors."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = {
            "devices": [],
            "system_info": {
                "192.168.1.1": {
                    "model": "Test Router",
                    "release": {"version": "22.03.0"},
                },
            },
        }

        # Test with different interface names
        interfaces = ["wlan0", "wlan1", "ap0", "wlan0.1"]

        for interface in interfaces:
            signal_strength = WrtManagerSignalStrengthSensor(
                coordinator, "192.168.1.1", "Test Router", interface
            )
            signal_quality = WrtManagerSignalQualitySensor(
                coordinator, "192.168.1.1", "Test Router", interface
            )

            # Unique IDs should be different for strength vs quality
            assert signal_strength.unique_id != signal_quality.unique_id

            # Should contain interface name (sanitized)
            interface_clean = interface.replace(".", "_").replace("-", "_")
            assert interface_clean in signal_strength.unique_id
            assert interface_clean in signal_quality.unique_id

    def test_device_info_consistency(self):
        """Test that device info is consistent across signal sensors."""
        coordinator = MagicMock(spec=WrtManagerCoordinator)
        coordinator.last_update_success = True
        coordinator.data = {
            "system_info": {
                "192.168.1.1": {
                    "model": "Test Model",
                    "release": {"version": "22.03.0"},
                }
            }
        }

        signal_strength = WrtManagerSignalStrengthSensor(
            coordinator, "192.168.1.1", "Test Router", "wlan0"
        )
        signal_quality = WrtManagerSignalQualitySensor(
            coordinator, "192.168.1.1", "Test Router", "wlan0"
        )

        # Device info should be the same for sensors from the same router
        strength_device_info = signal_strength.device_info
        quality_device_info = signal_quality.device_info

        assert strength_device_info["identifiers"] == quality_device_info["identifiers"]
        assert strength_device_info["name"] == quality_device_info["name"]
        assert strength_device_info["manufacturer"] == quality_device_info["manufacturer"]
