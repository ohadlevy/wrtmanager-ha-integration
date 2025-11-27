"""Tests for binary sensor unique ID generation fix (Issue #95)."""

from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntry

from custom_components.wrtmanager.binary_sensor import WrtDevicePresenceSensor
from custom_components.wrtmanager.const import ATTR_ROUTER, CONF_ROUTERS, DOMAIN
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry with multiple routers."""
    config_entry = Mock(spec=ConfigEntry)
    config_entry.data = {
        CONF_ROUTERS: [
            {
                "host": "192.168.1.1",
                "name": "Main Router",
                "username": "admin",
                "password": "password123",
            },
            {
                "host": "192.168.1.2",
                "name": "Secondary Router",
                "username": "admin",
                "password": "password123",
            },
        ]
    }
    return config_entry


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with device data."""
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator.data = {
        "devices": [
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "hostname": "test-device-1",
                ATTR_ROUTER: "192.168.1.1",
                "connected": True,
            },
            {
                "mac_address": "11:22:33:44:55:66",
                "hostname": "test-device-2",
                ATTR_ROUTER: "192.168.1.2",
                "connected": True,
            },
            {
                "mac_address": "77:88:99:AA:BB:CC",
                "hostname": "test-device-3",
                ATTR_ROUTER: "192.168.1.1",
                "connected": True,
            },
        ]
    }
    return coordinator


class TestBinarySensorUniqueID:
    """Test unique ID generation for device presence sensors."""

    def test_unique_id_generation_with_router_from_device_data(
        self, mock_coordinator, mock_config_entry
    ):
        """Test that unique IDs are generated using router from device data."""
        # Test device on first router
        sensor1 = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="AA:BB:CC:DD:EE:FF",
            config_entry=mock_config_entry,
        )

        # Test device on second router
        sensor2 = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="11:22:33:44:55:66",
            config_entry=mock_config_entry,
        )

        # Test another device on first router
        sensor3 = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="77:88:99:AA:BB:CC",
            config_entry=mock_config_entry,
        )

        # Verify unique IDs are different for devices on different routers
        expected_id_1 = f"{DOMAIN}_192_168_1_1_aa_bb_cc_dd_ee_ff_presence"
        expected_id_2 = f"{DOMAIN}_192_168_1_2_11_22_33_44_55_66_presence"
        expected_id_3 = f"{DOMAIN}_192_168_1_1_77_88_99_aa_bb_cc_presence"

        assert sensor1._attr_unique_id == expected_id_1
        assert sensor2._attr_unique_id == expected_id_2
        assert sensor3._attr_unique_id == expected_id_3

        # Ensure all unique IDs are different
        unique_ids = {sensor1._attr_unique_id, sensor2._attr_unique_id, sensor3._attr_unique_id}
        assert len(unique_ids) == 3, "All unique IDs should be different"

    def test_unique_id_fallback_when_no_device_data(self, mock_config_entry):
        """Test unique ID fallback when device data is not available."""
        # Create coordinator with no device data
        empty_coordinator = Mock(spec=WrtManagerCoordinator)
        empty_coordinator.data = {"devices": []}

        sensor = WrtDevicePresenceSensor(
            coordinator=empty_coordinator,
            mac="FF:EE:DD:CC:BB:AA",
            config_entry=mock_config_entry,
        )

        # Should fallback to "unknown" when device is not found
        expected_id = f"{DOMAIN}_unknown_ff_ee_dd_cc_bb_aa_presence"
        assert sensor._attr_unique_id == expected_id

    def test_unique_id_fallback_when_coordinator_data_is_none(self, mock_config_entry):
        """Test unique ID fallback when coordinator data is None."""
        # Create coordinator with None data
        none_coordinator = Mock(spec=WrtManagerCoordinator)
        none_coordinator.data = None

        sensor = WrtDevicePresenceSensor(
            coordinator=none_coordinator,
            mac="FF:EE:DD:CC:BB:AA",
            config_entry=mock_config_entry,
        )

        # Should fallback to "unknown" when coordinator data is None
        expected_id = f"{DOMAIN}_unknown_ff_ee_dd_cc_bb_aa_presence"
        assert sensor._attr_unique_id == expected_id

    def test_router_host_property_reflects_device_data(self, mock_coordinator, mock_config_entry):
        """Test that _router_host property reflects the router from device data."""
        sensor = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="AA:BB:CC:DD:EE:FF",
            config_entry=mock_config_entry,
        )

        # Verify _router_host is set from device data
        assert sensor._router_host == "192.168.1.1"

    def test_router_host_none_when_no_device_data(self, mock_config_entry):
        """Test that _router_host is None when no device data is available."""
        empty_coordinator = Mock(spec=WrtManagerCoordinator)
        empty_coordinator.data = {"devices": []}

        sensor = WrtDevicePresenceSensor(
            coordinator=empty_coordinator,
            mac="FF:EE:DD:CC:BB:AA",
            config_entry=mock_config_entry,
        )

        # _router_host should be None when device is not found
        assert sensor._router_host is None

    def test_mac_address_normalization_in_unique_id(self, mock_coordinator, mock_config_entry):
        """Test that MAC addresses are properly normalized in unique IDs."""
        # Test with lowercase MAC
        sensor_lower = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="aa:bb:cc:dd:ee:ff",
            config_entry=mock_config_entry,
        )

        # Test with uppercase MAC
        sensor_upper = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="AA:BB:CC:DD:EE:FF",
            config_entry=mock_config_entry,
        )

        # Both should generate the same unique ID
        expected_id = f"{DOMAIN}_192_168_1_1_aa_bb_cc_dd_ee_ff_presence"
        assert sensor_lower._attr_unique_id == expected_id
        assert sensor_upper._attr_unique_id == expected_id

    def test_router_ip_normalization_in_unique_id(self, mock_config_entry):
        """Test that router IP addresses are properly normalized in unique IDs."""
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = {
            "devices": [
                {
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "hostname": "test-device",
                    ATTR_ROUTER: "10.0.0.1",  # Different IP format
                    "connected": True,
                }
            ]
        }

        sensor = WrtDevicePresenceSensor(
            coordinator=coordinator,
            mac="AA:BB:CC:DD:EE:FF",
            config_entry=mock_config_entry,
        )

        # Dots should be replaced with underscores
        expected_id = f"{DOMAIN}_10_0_0_1_aa_bb_cc_dd_ee_ff_presence"
        assert sensor._attr_unique_id == expected_id

    def test_device_not_found_case(self, mock_config_entry):
        """Test behavior when device MAC is not found in coordinator data."""
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = {
            "devices": [
                {
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "hostname": "test-device",
                    ATTR_ROUTER: "192.168.1.1",
                    "connected": True,
                }
            ]
        }

        # Try to create sensor for a MAC that doesn't exist in data
        sensor = WrtDevicePresenceSensor(
            coordinator=coordinator,
            mac="99:88:77:66:55:44",
            config_entry=mock_config_entry,
        )

        # Should fallback to "unknown" when device MAC is not found
        expected_id = f"{DOMAIN}_unknown_99_88_77_66_55_44_presence"
        assert sensor._attr_unique_id == expected_id
        assert sensor._router_host is None

    def test_unique_id_prevents_conflicts_across_routers(self, mock_config_entry):
        """Test that the fix prevents unique ID conflicts across multiple routers."""
        # Simulate same device MAC detected on different routers
        coordinator_router1 = Mock(spec=WrtManagerCoordinator)
        coordinator_router1.data = {
            "devices": [
                {
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "hostname": "device-on-router1",
                    ATTR_ROUTER: "192.168.1.1",
                    "connected": True,
                }
            ]
        }

        coordinator_router2 = Mock(spec=WrtManagerCoordinator)
        coordinator_router2.data = {
            "devices": [
                {
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "hostname": "device-on-router2",
                    ATTR_ROUTER: "192.168.1.2",
                    "connected": True,
                }
            ]
        }

        # Same MAC but different routers should generate different unique IDs
        sensor1 = WrtDevicePresenceSensor(
            coordinator=coordinator_router1,
            mac="AA:BB:CC:DD:EE:FF",
            config_entry=mock_config_entry,
        )

        sensor2 = WrtDevicePresenceSensor(
            coordinator=coordinator_router2,
            mac="AA:BB:CC:DD:EE:FF",
            config_entry=mock_config_entry,
        )

        expected_id_1 = f"{DOMAIN}_192_168_1_1_aa_bb_cc_dd_ee_ff_presence"
        expected_id_2 = f"{DOMAIN}_192_168_1_2_aa_bb_cc_dd_ee_ff_presence"

        assert sensor1._attr_unique_id == expected_id_1
        assert sensor2._attr_unique_id == expected_id_2
        assert sensor1._attr_unique_id != sensor2._attr_unique_id

    def test_regression_issue_95_no_unknown_router_ids(self, mock_coordinator, mock_config_entry):
        """Test regression for issue #95: ensure router IDs are not 'unknown'."""
        # Create sensors for devices with known router data
        sensor1 = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="AA:BB:CC:DD:EE:FF",
            config_entry=mock_config_entry,
        )

        sensor2 = WrtDevicePresenceSensor(
            coordinator=mock_coordinator,
            mac="11:22:33:44:55:66",
            config_entry=mock_config_entry,
        )

        # Verify that unique IDs contain actual router IPs, not "unknown"
        assert "unknown" not in sensor1._attr_unique_id
        assert "unknown" not in sensor2._attr_unique_id
        assert "192_168_1_1" in sensor1._attr_unique_id
        assert "192_168_1_2" in sensor2._attr_unique_id
