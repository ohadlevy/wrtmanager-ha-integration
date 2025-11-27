"""Tests for device registry and entity ID fixes."""

from unittest.mock import Mock, patch

import pytest
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from custom_components.wrtmanager.binary_sensor import WrtDevicePresenceSensor
from custom_components.wrtmanager.const import DOMAIN


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock()
    coordinator.data = {
        "devices": [
            {
                "mac_address": "2E:34:E7:D0:21:AA",
                "hostname": "test-device",
                "vendor": "Apple",
                "device_type": "Mobile Device",
                "router": "192.168.1.1",
                "connected": True,
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


class TestDeviceRegistryFixes:
    """Test device registry via_device fixes."""

    def test_unique_id_includes_router_host(self, mock_coordinator, mock_config_entry):
        """Test that unique IDs include router host to prevent collisions."""
        with patch("custom_components.wrtmanager.binary_sensor.dr"):
            mock_hass = Mock()

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            # Check that unique ID includes router host
            expected_unique_id = "wrtmanager_192_168_1_1_2e_34_e7_d0_21_aa_presence"
            assert sensor.unique_id == expected_unique_id

    def test_unique_id_different_routers(self):
        """Test that same device on different routers gets different unique IDs."""
        # Create coordinator with device on first router
        coordinator1 = Mock()
        coordinator1.data = {
            "devices": [
                {
                    "mac_address": "2E:34:E7:D0:21:AA",
                    "hostname": "test-device",
                    "vendor": "Apple",
                    "device_type": "Mobile Device",
                    "router": "192.168.1.1",
                    "connected": True,
                }
            ]
        }

        # Create coordinator with device on second router
        coordinator2 = Mock()
        coordinator2.data = {
            "devices": [
                {
                    "mac_address": "2E:34:E7:D0:21:AA",
                    "hostname": "test-device",
                    "vendor": "Apple",
                    "device_type": "Mobile Device",
                    "router": "192.168.1.2",
                    "connected": True,
                }
            ]
        }

        config_entry = Mock()
        config_entry.data = {
            "routers": [
                {"host": "192.168.1.1", "name": "Router1"},
                {"host": "192.168.1.2", "name": "Router2"},
            ]
        }

        with patch("custom_components.wrtmanager.binary_sensor.dr"):
            mock_hass = Mock()

            sensor1 = WrtDevicePresenceSensor(
                coordinator=coordinator1,
                mac="2E:34:E7:D0:21:AA",
                config_entry=config_entry,
            )
            sensor1.hass = mock_hass

            sensor2 = WrtDevicePresenceSensor(
                coordinator=coordinator2,
                mac="2E:34:E7:D0:21:AA",
                config_entry=config_entry,
            )
            sensor2.hass = mock_hass

            # Same MAC, different routers should have different unique IDs
            assert sensor1.unique_id != sensor2.unique_id
            assert "192_168_1_1" in sensor1.unique_id
            assert "192_168_1_2" in sensor2.unique_id

    def test_via_device_with_existing_router(self, mock_coordinator, mock_config_entry):
        """Test via_device is set when router device exists."""
        mock_hass = Mock()
        mock_device_registry = Mock()
        mock_router_device = Mock()

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = mock_router_device

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Should have via_device since router exists
            assert device_info["via_device"] == (DOMAIN, "192.168.1.1")

    def test_via_device_with_missing_router(self, mock_coordinator, mock_config_entry):
        """Test via_device is None when router device doesn't exist."""
        mock_hass = Mock()
        mock_device_registry = Mock()

        with patch("custom_components.wrtmanager.binary_sensor.dr") as mock_dr:
            mock_dr.async_get.return_value = mock_device_registry
            mock_device_registry.async_get_device.return_value = None  # Router doesn't exist

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Should not have via_device since router doesn't exist
            assert device_info["via_device"] is None

    def test_device_info_identifiers(self, mock_coordinator, mock_config_entry):
        """Test device info identifiers are correct."""
        with patch("custom_components.wrtmanager.binary_sensor.dr"):
            mock_hass = Mock()

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Check identifiers use MAC address
            expected_identifiers = {(DOMAIN, "2E:34:E7:D0:21:AA")}
            assert device_info["identifiers"] == expected_identifiers

    def test_device_info_has_network_mac_connection(self, mock_coordinator, mock_config_entry):
        """Test device info includes CONNECTION_NETWORK_MAC for cross-integration linking."""
        with patch("custom_components.wrtmanager.binary_sensor.dr"):
            mock_hass = Mock()

            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Check connections include network MAC for device linking
            expected_connections = {(CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA")}
            assert device_info["connections"] == expected_connections

    def test_device_linking_across_integrations(self, mock_coordinator, mock_config_entry):
        """Test that devices can be linked across multiple integrations using MAC address."""
        with patch("custom_components.wrtmanager.binary_sensor.dr"):
            mock_hass = Mock()

            # Create device from our integration
            sensor = WrtDevicePresenceSensor(
                coordinator=mock_coordinator,
                mac="2E:34:E7:D0:21:AA",
                config_entry=mock_config_entry,
            )
            sensor.hass = mock_hass

            device_info = sensor.device_info

            # Verify both identifiers and connections are set correctly
            assert device_info["identifiers"] == {(DOMAIN, "2E:34:E7:D0:21:AA")}
            assert device_info["connections"] == {(CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA")}

            # This device should be linkable by other integrations using the same MAC
            # For example, a UniFi integration with:
            # DeviceInfo(
            #     identifiers={("unifi", "some_unifi_id")},
            #     connections={(CONNECTION_NETWORK_MAC, "2E:34:E7:D0:21:AA")}
            # )
            # Would be automatically linked by Home Assistant's device registry

    def test_mac_address_normalization_in_connections(self, mock_config_entry):
        """Test that MAC addresses in connections are properly formatted."""
        # Test with different MAC address formats
        test_cases = [
            ("2e:34:e7:d0:21:aa", "2e:34:e7:d0:21:aa"),  # lowercase
            ("2E:34:E7:D0:21:AA", "2E:34:E7:D0:21:AA"),  # uppercase
            ("2e-34-e7-d0-21-aa", "2e-34-e7-d0-21-aa"),  # dash format
        ]

        for input_mac, expected_mac in test_cases:
            mock_coordinator = Mock()
            mock_coordinator.data = {
                "devices": [
                    {
                        "mac_address": input_mac,
                        "hostname": "test-device",
                        "vendor": "Apple",
                        "device_type": "Mobile Device",
                        "router": "192.168.1.1",
                        "connected": True,
                    }
                ]
            }

            with patch("custom_components.wrtmanager.binary_sensor.dr"):
                mock_hass = Mock()

                sensor = WrtDevicePresenceSensor(
                    coordinator=mock_coordinator,
                    mac=input_mac,
                    config_entry=mock_config_entry,
                )
                sensor.hass = mock_hass

                device_info = sensor.device_info

                # Check that MAC address in connections matches the sensor's stored MAC
                expected_connections = {(CONNECTION_NETWORK_MAC, sensor._mac)}
                assert device_info["connections"] == expected_connections
