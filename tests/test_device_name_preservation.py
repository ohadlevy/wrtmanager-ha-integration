"""Tests for device name and area preservation during device merges (Issue #56)."""

from unittest.mock import Mock, patch

import pytest
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from custom_components.wrtmanager.binary_sensor import WrtDevicePresenceSensor
from custom_components.wrtmanager.const import (
    ATTR_CONNECTED,
    ATTR_DEVICE_TYPE,
    ATTR_HOSTNAME,
    ATTR_MAC,
    ATTR_ROUTER,
    ATTR_VENDOR,
    DOMAIN,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock()
    coordinator.data = {
        "devices": [
            {
                ATTR_MAC: "2E:34:E7:D0:21:AA",
                ATTR_HOSTNAME: "test-device",
                ATTR_VENDOR: "Apple",
                ATTR_DEVICE_TYPE: "Mobile Device",
                ATTR_ROUTER: "192.168.1.1",
                ATTR_CONNECTED: True,
            }
        ]
    }
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    config_entry = Mock()
    config_entry.data = {"host": "192.168.1.1"}
    return config_entry


class TestDeviceNamePreservation:
    """Test device name and area preservation during device merges."""

    def test_new_device_gets_generated_name(self, mock_coordinator, mock_config_entry):
        """Test that new devices get generated names."""
        mock_hass = Mock()
        mock_device_registry = Mock()

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            # No existing device found
            mock_device_registry.async_get_device.return_value = None

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # New device should have generated name
            assert "name" in device_info
            assert device_info["name"] == "test-device"  # Uses hostname

    def test_existing_device_name_preserved_by_connection(
        self, mock_coordinator, mock_config_entry
    ):
        """Test that existing device names are preserved when found by MAC connection."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_existing_device = Mock()
        mock_existing_device.name = "User Custom Name"
        mock_existing_device.name_by_user = "User Custom Name"
        mock_existing_device.area_id = "living_room"

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry

            def mock_get_device(**kwargs):
                # Return existing device when searched by MAC connection
                if (
                    "connections" in kwargs
                    and (CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA") in kwargs["connections"]
                ):
                    return mock_existing_device
                # Return None for router device lookup
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Existing device should NOT have name set to preserve user customization
            assert "name" not in device_info

    def test_existing_device_name_preserved_by_identifier(
        self, mock_coordinator, mock_config_entry
    ):
        """Test that existing device names are preserved when found by integration identifier."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_existing_device = Mock()
        mock_existing_device.name = "Another Custom Name"
        mock_existing_device.name_by_user = None  # Only name, not name_by_user
        mock_existing_device.area_id = "kitchen"

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry

            def mock_get_device(**kwargs):
                # Return None when searched by MAC connection
                if "connections" in kwargs:
                    return None
                # Return existing device when searched by integration identifier
                if (
                    "identifiers" in kwargs
                    and (DOMAIN, "2E:34:E7:D0:21:AA") in kwargs["identifiers"]
                ):
                    return mock_existing_device
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Existing device should NOT have name set to preserve user customization
            assert "name" not in device_info

    def test_name_by_user_preferred_over_name(self, mock_coordinator, mock_config_entry):
        """Test that name_by_user is preferred over name when both exist."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_existing_device = Mock()
        mock_existing_device.name = "Original Name"
        mock_existing_device.name_by_user = "User Renamed Device"

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = mock_existing_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            # Verify that device_info does not include name, preserving user customization
            device_info = sensor.device_info
            assert "name" not in device_info

    def test_device_merge_scenario(self, mock_coordinator, mock_config_entry):
        """Test the complete device merge scenario that caused issue #56."""
        mock_hass = Mock()
        mock_device_registry = Mock()

        # Simulate sequence: device created, user customizes, then merge happens

        # Step 1: Initial device creation (no existing device)
        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = None  # No existing device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            initial_device_info = sensor.device_info
            # Initial creation should have generated name
            assert "name" in initial_device_info
            assert initial_device_info["name"] == "test-device"

        # Step 2: User customizes device in HA (simulate existing device with custom name)
        mock_customized_device = Mock()
        mock_customized_device.name = "test-device"  # Original generated name
        mock_customized_device.name_by_user = "My iPhone"  # User customized name
        mock_customized_device.area_id = "bedroom"  # User assigned area

        # Step 3: Device merge happens - integration should preserve customizations
        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = mock_customized_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            merge_device_info = sensor.device_info

            # After merge, name should NOT be set to preserve user customizations
            assert "name" not in merge_device_info
            # Device should still have proper identifiers and connections
            assert merge_device_info["identifiers"] == {(DOMAIN, "2E:34:E7:D0:21:AA")}
            assert merge_device_info["connections"] == {
                (CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA")
            }

    def test_device_name_generation_from_vendor_and_type(self, mock_config_entry):
        """Test device name generation for devices without hostname."""
        mock_hass = Mock()
        mock_device_registry = Mock()

        # Create coordinator with device that has no hostname
        coordinator = Mock()
        coordinator.data = {
            "devices": [
                {
                    ATTR_MAC: "C8:47:8C:12:34:56",  # Shelly MAC prefix
                    ATTR_HOSTNAME: "",  # No hostname
                    ATTR_VENDOR: "Shelly",
                    ATTR_DEVICE_TYPE: "IoT Switch",
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_CONNECTED: True,
                }
            ]
        }

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = None  # New device

            sensor = WrtDevicePresenceSensor(
                coordinator=coordinator,
                mac="C8:47:8C:12:34:56",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Should generate name based on vendor and device type
            assert "name" in device_info
            assert device_info["name"] == "Shelly Switch"

    def test_unknown_device_name_generation(self, mock_config_entry):
        """Test device name generation for completely unknown devices."""
        mock_hass = Mock()
        mock_device_registry = Mock()

        # Create coordinator with unknown device
        coordinator = Mock()
        coordinator.data = {
            "devices": [
                {
                    ATTR_MAC: "FF:FF:FF:12:34:56",  # Unknown MAC prefix
                    ATTR_HOSTNAME: None,
                    ATTR_VENDOR: None,
                    ATTR_DEVICE_TYPE: None,
                    ATTR_ROUTER: "192.168.1.1",
                    ATTR_CONNECTED: True,
                }
            ]
        }

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = None  # New device

            sensor = WrtDevicePresenceSensor(
                coordinator=coordinator,
                mac="FF:FF:FF:12:34:56",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Should generate fallback name with MAC suffix
            assert "name" in device_info
            assert device_info["name"] == "Unknown Device 3456"

    def test_device_info_preserves_other_attributes(self, mock_coordinator, mock_config_entry):
        """Test that device info preserves all other attributes correctly."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_existing_device = Mock()
        mock_existing_device.name = "Existing Device"
        mock_existing_device.name_by_user = None

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry

            def mock_get_device(**kwargs):
                # Return existing device when searched for our device
                if (
                    "connections" in kwargs
                    and (CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA") in kwargs["connections"]
                ):
                    return mock_existing_device
                if (
                    "identifiers" in kwargs
                    and (DOMAIN, "2E:34:E7:D0:21:AA") in kwargs["identifiers"]
                ):
                    return mock_existing_device
                # Return None for router device lookup or any other lookups
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Required attributes should always be present
            assert device_info["identifiers"] == {(DOMAIN, "2E:34:E7:D0:21:AA")}
            assert device_info["connections"] == {(CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA")}
            assert device_info["via_device"] is None  # Router doesn't exist in this test

            # For existing devices, manufacturer/model should NOT be overridden
            assert "manufacturer" not in device_info
            assert "model" not in device_info
            assert "name" not in device_info  # Name preserved by not being in device_info

    def test_logging_for_preserved_device(self, mock_coordinator, mock_config_entry, caplog):
        """Test that preservation is logged for debugging purposes."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_existing_device = Mock()
        mock_existing_device.name = "Original Name"
        mock_existing_device.name_by_user = "User Custom Name"

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = mock_existing_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            # Access device_info to trigger logging for preservation
            device_info = sensor.device_info

            # Verify logging occurred at DEBUG level
            assert any(
                "already exists with name" in record.message and record.levelname == "DEBUG"
                for record in caplog.records
            )
            assert "preserving existing name" in caplog.text
            assert "User Custom Name" in caplog.text
            # Verify that name is not set in device_info to preserve customization
            assert "name" not in device_info


class TestAreaPreservation:
    """Test area preservation during device merges."""

    def test_new_device_gets_suggested_area_from_router(self, mock_coordinator, mock_config_entry):
        """Test that new devices get suggested area based on router's area."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_area_registry = Mock()

        # Create mock router device in "living_room" area
        mock_router_device = Mock()
        mock_router_device.area_id = "living_room_id"

        # Create mock area
        mock_area = Mock()
        mock_area.name = "Living Room"

        with (
            patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr,
            patch("custom_components.wrtmanager.binary_sensor.ar") as mock_ar,
        ):

            mock_dr.async_get.return_value = mock_device_registry
            mock_ar.async_get.return_value = mock_area_registry

            def mock_get_device(**kwargs):
                # Return None for our device lookup (new device)
                if "connections" in kwargs or (
                    "identifiers" in kwargs
                    and (DOMAIN, "2E:34:E7:D0:21:AA") in kwargs.get("identifiers", set())
                ):
                    return None
                # Return router device when looking up router
                if "identifiers" in kwargs and (DOMAIN, "192.168.1.1") in kwargs.get(
                    "identifiers", set()
                ):
                    return mock_router_device
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device
            mock_area_registry.async_get_area.return_value = mock_area

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # New device should have both name and suggested_area
            assert "name" in device_info
            assert device_info["name"] == "test-device"
            assert "suggested_area" in device_info
            assert device_info["suggested_area"] == "Living Room"

    def test_new_device_no_suggested_area_when_router_has_no_area(
        self, mock_coordinator, mock_config_entry
    ):
        """Test that new devices get no suggested area when router has no area."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_area_registry = Mock()

        # Create mock router device with no area
        mock_router_device = Mock()
        mock_router_device.area_id = None

        with (
            patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr,
            patch("custom_components.wrtmanager.binary_sensor.ar") as mock_ar,
        ):

            mock_dr.async_get.return_value = mock_device_registry
            mock_ar.async_get.return_value = mock_area_registry

            def mock_get_device(**kwargs):
                # Return None for our device lookup (new device)
                if "connections" in kwargs or (
                    "identifiers" in kwargs
                    and (DOMAIN, "2E:34:E7:D0:21:AA") in kwargs.get("identifiers", set())
                ):
                    return None
                # Return router device when looking up router
                if "identifiers" in kwargs and (DOMAIN, "192.168.1.1") in kwargs.get(
                    "identifiers", set()
                ):
                    return mock_router_device
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # New device should have name but no suggested_area
            assert "name" in device_info
            assert device_info["name"] == "test-device"
            assert "suggested_area" not in device_info

    def test_existing_device_preserves_area_by_omitting_suggested_area(
        self, mock_coordinator, mock_config_entry
    ):
        """Test that existing devices preserve their area by not setting suggested_area."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_area_registry = Mock()

        # Create existing device in "bedroom" area
        mock_existing_device = Mock()
        mock_existing_device.name = "User Custom Name"
        mock_existing_device.name_by_user = "User Custom Name"
        mock_existing_device.area_id = "bedroom_id"

        # Create mock router device in different area ("living_room")
        mock_router_device = Mock()
        mock_router_device.area_id = "living_room_id"

        # Create mock area
        mock_router_area = Mock()
        mock_router_area.name = "Living Room"

        with (
            patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr,
            patch("custom_components.wrtmanager.binary_sensor.ar") as mock_ar,
        ):

            mock_dr.async_get.return_value = mock_device_registry
            mock_ar.async_get.return_value = mock_area_registry

            def mock_get_device(**kwargs):
                # Return existing device when searched by MAC connection
                if (
                    "connections" in kwargs
                    and (CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA") in kwargs["connections"]
                ):
                    return mock_existing_device
                # Return router device when looking up router
                if "identifiers" in kwargs and (DOMAIN, "192.168.1.1") in kwargs.get(
                    "identifiers", set()
                ):
                    return mock_router_device
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device
            mock_area_registry.async_get_area.return_value = mock_router_area

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Existing device should NOT have name or suggested_area set to preserve customizations
            assert "name" not in device_info
            assert "suggested_area" not in device_info

    def test_area_preservation_complete_scenario(self, mock_coordinator, mock_config_entry):
        """Test complete area preservation scenario from creation to merge."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_area_registry = Mock()

        # Mock router device in "kitchen" area
        mock_router_device = Mock()
        mock_router_device.area_id = "kitchen_id"

        # Mock kitchen area
        mock_kitchen_area = Mock()
        mock_kitchen_area.name = "Kitchen"

        # Step 1: Device creation - should get suggested area from router
        with (
            patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr,
            patch("custom_components.wrtmanager.binary_sensor.ar") as mock_ar,
        ):

            mock_dr.async_get.return_value = mock_device_registry
            mock_ar.async_get.return_value = mock_area_registry

            def mock_get_device_initial(**kwargs):
                # No existing device
                if "connections" in kwargs or (
                    "identifiers" in kwargs
                    and (DOMAIN, "2E:34:E7:D0:21:AA") in kwargs.get("identifiers", set())
                ):
                    return None
                # Return router device
                if "identifiers" in kwargs and (DOMAIN, "192.168.1.1") in kwargs.get(
                    "identifiers", set()
                ):
                    return mock_router_device
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device_initial
            mock_area_registry.async_get_area.return_value = mock_kitchen_area

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            initial_device_info = sensor.device_info

            # Initial creation should suggest router's area
            assert "name" in initial_device_info
            assert initial_device_info["name"] == "test-device"
            assert "suggested_area" in initial_device_info
            assert initial_device_info["suggested_area"] == "Kitchen"

        # Step 2: User moves device to different area (simulate existing device)
        mock_existing_device = Mock()
        mock_existing_device.name = "test-device"
        mock_existing_device.name_by_user = "My Smart Device"
        mock_existing_device.area_id = "bedroom_id"  # User moved it to bedroom

        # Step 3: Device merge - should preserve user's area choice
        with (
            patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr,
            patch("custom_components.wrtmanager.binary_sensor.ar") as mock_ar,
        ):

            mock_dr.async_get.return_value = mock_device_registry
            mock_ar.async_get.return_value = mock_area_registry

            def mock_get_device_merge(**kwargs):
                # Return existing device
                if (
                    "connections" in kwargs
                    and (CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA") in kwargs["connections"]
                ):
                    return mock_existing_device
                # Return router device (still in kitchen)
                if "identifiers" in kwargs and (DOMAIN, "192.168.1.1") in kwargs.get(
                    "identifiers", set()
                ):
                    return mock_router_device
                return None

            mock_device_registry.async_get_device.side_effect = mock_get_device_merge
            mock_area_registry.async_get_area.return_value = mock_kitchen_area

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            merge_device_info = sensor.device_info

            # After merge, should NOT set name or suggested_area to preserve user customizations
            assert "name" not in merge_device_info
            assert "suggested_area" not in merge_device_info
            # But should still have proper identifiers
            assert merge_device_info["identifiers"] == {(DOMAIN, "2E:34:E7:D0:21:AA")}
            assert merge_device_info["connections"] == {
                (CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA")
            }

    def test_suggested_area_method_directly(self, mock_coordinator, mock_config_entry):
        """Test the _get_suggested_area method directly."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_area_registry = Mock()

        # Test case 1: Router has area
        mock_router_device = Mock()
        mock_router_device.area_id = "office_id"

        mock_office_area = Mock()
        mock_office_area.name = "Office"

        with (
            patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr,
            patch("custom_components.wrtmanager.binary_sensor.ar") as mock_ar,
        ):

            mock_dr.async_get.return_value = mock_device_registry
            mock_ar.async_get.return_value = mock_area_registry
            mock_device_registry.async_get_device.return_value = mock_router_device
            mock_area_registry.async_get_area.return_value = mock_office_area

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            # Should return router's area name
            result = sensor._get_suggested_area("192.168.1.1")
            assert result == "Office"

        # Test case 2: Router not found
        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_hass_2 = Mock()
            mock_device_registry_2 = Mock()
            mock_dr.async_get.return_value = mock_device_registry_2
            mock_device_registry_2.async_get_device.return_value = None

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass_2
            result = sensor._get_suggested_area("192.168.1.1")
            assert result is None

        # Test case 3: No router host
        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_hass_3 = Mock()
            mock_device_registry_3 = Mock()
            mock_dr.async_get.return_value = mock_device_registry_3

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass_3
            result = sensor._get_suggested_area(None)
            assert result is None
