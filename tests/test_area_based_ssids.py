"""Tests for area-based SSID grouping functionality."""

from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.wrtmanager.binary_sensor import (
    WrtAreaSSIDBinarySensor,
    WrtGlobalSSIDBinarySensor,
    _create_ssid_entities,
)
from custom_components.wrtmanager.const import DOMAIN
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


@pytest.fixture
def mock_device_registry():
    """Create a mock device registry."""
    device_reg = Mock()

    # Mock router devices
    router_1_device = Mock()
    router_1_device.area_id = "living_room"

    router_2_device = Mock()
    router_2_device.area_id = "bedroom"

    router_3_device = Mock()
    router_3_device.area_id = None  # No area assigned

    def get_device(identifiers):
        device_map = {
            frozenset([(DOMAIN, "192.168.1.1")]): router_1_device,
            frozenset([(DOMAIN, "192.168.1.2")]): router_2_device,
            frozenset([(DOMAIN, "192.168.1.3")]): router_3_device,
        }
        return device_map.get(frozenset(identifiers))

    device_reg.async_get_device = get_device
    return device_reg


@pytest.fixture
def mock_area_registry():
    """Create a mock area registry."""
    area_reg = Mock()

    living_room_area = Mock()
    living_room_area.name = "Living Room"

    bedroom_area = Mock()
    bedroom_area.name = "Bedroom"

    def get_area(area_id):
        area_map = {
            "living_room": living_room_area,
            "bedroom": bedroom_area,
        }
        return area_map.get(area_id)

    area_reg.async_get_area = get_area
    return area_reg


@pytest.fixture
def mock_hass_with_registries(mock_device_registry, mock_area_registry):
    """Create a mock Home Assistant with registries."""
    hass = Mock()

    def get_registry(registry_type):
        if "device_registry" in str(registry_type):
            return mock_device_registry
        elif "area_registry" in str(registry_type):
            return mock_area_registry
        return None

    # Mock the registry async_get functions
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr

    ar.async_get = Mock(return_value=mock_area_registry)
    dr.async_get = Mock(return_value=mock_device_registry)

    return hass


@pytest.fixture
def sample_coordinator_data():
    """Sample coordinator data with SSIDs across multiple routers."""
    return {
        "ssids": {
            "192.168.1.1": [
                {
                    "radio": "multi_radio_mainnetwork",
                    "ssid_interface": "interface_0",
                    "ssid_name": "MainNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "network": "lan",
                    "is_consolidated": True,
                    "radios": ["radio0", "radio1"],
                    "frequency_bands": ["2.4GHz", "5GHz"],
                    "radio_count": 2,
                },
                {
                    "radio": "radio0",
                    "ssid_interface": "interface_1",
                    "ssid_name": "GuestNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "network": "guest",
                    "is_consolidated": False,
                },
            ],
            "192.168.1.2": [
                {
                    "radio": "multi_radio_mainnetwork",
                    "ssid_interface": "interface_0",
                    "ssid_name": "MainNetwork",
                    "mode": "ap",
                    "disabled": True,  # Disabled in bedroom
                    "encryption": "psk2",
                    "network": "lan",
                    "is_consolidated": True,
                    "radios": ["radio0", "radio1"],
                    "frequency_bands": ["2.4GHz", "5GHz"],
                    "radio_count": 2,
                },
            ],
            "192.168.1.3": [
                {
                    "radio": "radio0",
                    "ssid_interface": "interface_0",
                    "ssid_name": "MainNetwork",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "network": "lan",
                    "is_consolidated": False,
                },
            ],
        }
    }


@pytest.fixture
def sample_config_entry():
    """Sample config entry with multiple routers."""
    config_entry = Mock()
    config_entry.data = {
        "routers": [
            {"host": "192.168.1.1", "name": "Living Room Router"},
            {"host": "192.168.1.2", "name": "Bedroom Router"},
            {"host": "192.168.1.3", "name": "Kitchen Router"},
        ]
    }
    return config_entry


class TestAreaBasedSSIDGrouping:
    """Test area-based SSID grouping functionality."""

    @pytest.mark.asyncio
    async def test_create_ssid_entities_with_areas(
        self, mock_hass_with_registries, sample_coordinator_data, sample_config_entry
    ):
        """Test creation of SSID entities with area-based grouping."""
        # Setup coordinator with data
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = sample_coordinator_data

        # Mock the registry functions to return our mocks
        with pytest.MonkeyPatch().context() as m:
            import custom_components.wrtmanager.binary_sensor as bs

            m.setattr(bs.dr, "async_get", lambda hass: mock_hass_with_registries)
            m.setattr(bs.ar, "async_get", lambda hass: mock_hass_with_registries)

        entities = await _create_ssid_entities(
            mock_hass_with_registries, coordinator, sample_config_entry
        )

        # Should create global entities for each unique SSID
        global_entities = [e for e in entities if isinstance(e, WrtGlobalSSIDBinarySensor)]
        area_entities = [e for e in entities if isinstance(e, WrtAreaSSIDBinarySensor)]

        # Should have 2 global SSIDs: MainNetwork and GuestNetwork
        assert len(global_entities) == 2

        # MainNetwork exists in multiple areas, should have area entities
        # GuestNetwork only in one area, should not have area entities
        assert len(area_entities) >= 1  # At least MainNetwork area entities

    def test_global_ssid_sensor_properties(self, sample_coordinator_data):
        """Test global SSID sensor properties."""
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = sample_coordinator_data
        coordinator.last_update_success = True

        # Create sample SSID group for MainNetwork
        ssid_group = {
            "routers": ["192.168.1.1", "192.168.1.2", "192.168.1.3"],
            "ssid_instances": [
                {
                    "router_host": "192.168.1.1",
                    "router_name": "Living Room Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.1"][0],
                },
                {
                    "router_host": "192.168.1.2",
                    "router_name": "Bedroom Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.2"][0],
                },
                {
                    "router_host": "192.168.1.3",
                    "router_name": "Kitchen Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.3"][0],
                },
            ],
            "areas": {"Living Room", "Bedroom"},
        }

        config_entry = Mock()

        sensor = WrtGlobalSSIDBinarySensor(
            coordinator=coordinator,
            ssid_name="MainNetwork",
            ssid_group=ssid_group,
            config_entry=config_entry,
        )

        # Test unique ID
        assert sensor.unique_id == "wrtmanager_global_mainnetwork_enabled"

        # Test name
        assert sensor.name == "Global MainNetwork SSID"

        # Test is_on - should be True if enabled on any router
        # Living Room: enabled, Bedroom: disabled, Kitchen: enabled
        assert sensor.is_on is True

        # Test availability
        assert sensor.available is True

        # Test attributes
        attributes = sensor.extra_state_attributes
        assert attributes["ssid_name"] == "MainNetwork"
        assert attributes["router_count"] == 3
        assert "Living Room Router" in attributes["enabled_routers"]
        assert "Kitchen Router" in attributes["enabled_routers"]
        assert "Bedroom Router" in attributes["disabled_routers"]
        assert attributes["coverage"] == "Global (all routers)"
        assert "Living Room" in attributes["areas"]
        assert "Bedroom" in attributes["areas"]

    def test_area_ssid_sensor_properties(self, sample_coordinator_data):
        """Test area SSID sensor properties."""
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = sample_coordinator_data
        coordinator.last_update_success = True

        # Create area instances for Living Room
        area_instances = [
            {
                "router_host": "192.168.1.1",
                "router_name": "Living Room Router",
                "ssid_info": sample_coordinator_data["ssids"]["192.168.1.1"][0],
            }
        ]

        config_entry = Mock()

        sensor = WrtAreaSSIDBinarySensor(
            coordinator=coordinator,
            ssid_name="MainNetwork",
            area_name="Living Room",
            area_instances=area_instances,
            config_entry=config_entry,
        )

        # Test unique ID
        assert sensor.unique_id == "wrtmanager_living_room_mainnetwork_enabled"

        # Test name
        assert sensor.name == "Living Room MainNetwork SSID"

        # Test is_on - should be True for Living Room (enabled)
        assert sensor.is_on is True

        # Test availability
        assert sensor.available is True

        # Test attributes
        attributes = sensor.extra_state_attributes
        assert attributes["ssid_name"] == "MainNetwork"
        assert attributes["area_name"] == "Living Room"
        assert attributes["router_count"] == 1
        assert "Living Room Router" in attributes["enabled_routers"]
        assert len(attributes["disabled_routers"]) == 0
        assert attributes["coverage"] == "Area: Living Room"

    def test_global_ssid_sensor_all_disabled(self, sample_coordinator_data):
        """Test global SSID sensor when all instances are disabled."""
        # Modify data to have all SSIDs disabled
        for router_ssids in sample_coordinator_data["ssids"].values():
            for ssid in router_ssids:
                if ssid["ssid_name"] == "MainNetwork":
                    ssid["disabled"] = True

        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = sample_coordinator_data
        coordinator.last_update_success = True

        ssid_group = {
            "routers": ["192.168.1.1", "192.168.1.2", "192.168.1.3"],
            "ssid_instances": [
                {
                    "router_host": "192.168.1.1",
                    "router_name": "Living Room Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.1"][0],
                },
                {
                    "router_host": "192.168.1.2",
                    "router_name": "Bedroom Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.2"][0],
                },
                {
                    "router_host": "192.168.1.3",
                    "router_name": "Kitchen Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.3"][0],
                },
            ],
            "areas": {"Living Room", "Bedroom"},
        }

        config_entry = Mock()

        sensor = WrtGlobalSSIDBinarySensor(
            coordinator=coordinator,
            ssid_name="MainNetwork",
            ssid_group=ssid_group,
            config_entry=config_entry,
        )

        # Should be False when all are disabled
        assert sensor.is_on is False

        # All routers should be in disabled list
        attributes = sensor.extra_state_attributes
        assert len(attributes["enabled_routers"]) == 0
        assert len(attributes["disabled_routers"]) == 3

    def test_ssid_sensor_no_area_assignment(self, sample_coordinator_data):
        """Test SSID sensor behavior when routers have no area assignment."""
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = sample_coordinator_data
        coordinator.last_update_success = True

        # Create SSID group with no areas (all routers unassigned)
        ssid_group = {
            "routers": ["192.168.1.3"],
            "ssid_instances": [
                {
                    "router_host": "192.168.1.3",
                    "router_name": "Kitchen Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.3"][0],
                }
            ],
            "areas": set(),  # No areas
        }

        config_entry = Mock()

        sensor = WrtGlobalSSIDBinarySensor(
            coordinator=coordinator,
            ssid_name="MainNetwork",
            ssid_group=ssid_group,
            config_entry=config_entry,
        )

        # Test attributes show no areas assigned
        attributes = sensor.extra_state_attributes
        assert attributes["areas"] == ["No areas assigned"]

        # Global sensor should still work normally
        assert sensor.is_on is True  # Kitchen router has MainNetwork enabled
        assert sensor.available is True

    def test_frequency_band_aggregation(self, sample_coordinator_data):
        """Test frequency band aggregation across routers."""
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = sample_coordinator_data
        coordinator.last_update_success = True

        # Mix of consolidated and single radio SSIDs
        ssid_group = {
            "routers": ["192.168.1.1", "192.168.1.3"],
            "ssid_instances": [
                {
                    "router_host": "192.168.1.1",
                    "router_name": "Living Room Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.1"][
                        0
                    ],  # Consolidated: 2.4GHz + 5GHz
                },
                {
                    "router_host": "192.168.1.3",
                    "router_name": "Kitchen Router",
                    "ssid_info": sample_coordinator_data["ssids"]["192.168.1.3"][
                        0
                    ],  # Single: radio0 (2.4GHz)
                },
            ],
            "areas": {"Living Room"},
        }

        config_entry = Mock()

        sensor = WrtGlobalSSIDBinarySensor(
            coordinator=coordinator,
            ssid_name="MainNetwork",
            ssid_group=ssid_group,
            config_entry=config_entry,
        )

        # Should aggregate frequency bands from both routers
        attributes = sensor.extra_state_attributes
        frequency_bands = attributes["frequency_bands"]
        assert "2.4GHz" in frequency_bands
        assert "5GHz" in frequency_bands
        assert sorted(frequency_bands) == ["2.4GHz", "5GHz"]

    def test_device_info_generation(self, sample_coordinator_data):
        """Test device info generation for global and area SSID sensors."""
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = sample_coordinator_data

        # Test global sensor device info
        ssid_group = {
            "routers": ["192.168.1.1"],
            "ssid_instances": [],
            "areas": set(),
        }

        config_entry = Mock()

        global_sensor = WrtGlobalSSIDBinarySensor(
            coordinator=coordinator,
            ssid_name="MainNetwork",
            ssid_group=ssid_group,
            config_entry=config_entry,
        )

        device_info = global_sensor.device_info
        assert device_info["identifiers"] == {(DOMAIN, "global_ssid_MainNetwork")}
        assert device_info["name"] == "Global MainNetwork"
        assert device_info["manufacturer"] == "WrtManager"
        assert device_info["model"] == "Global SSID Controller"

        # Test area sensor device info
        area_instances = [
            {
                "router_host": "192.168.1.1",
                "router_name": "Living Room Router",
                "ssid_info": {},
            }
        ]

        area_sensor = WrtAreaSSIDBinarySensor(
            coordinator=coordinator,
            ssid_name="MainNetwork",
            area_name="Living Room",
            area_instances=area_instances,
            config_entry=config_entry,
        )

        device_info = area_sensor.device_info
        assert device_info["identifiers"] == {(DOMAIN, "area_Living Room_MainNetwork")}
        assert device_info["name"] == "Living Room MainNetwork"
        assert device_info["manufacturer"] == "WrtManager"
        assert device_info["model"] == "Area SSID Controller"
        assert device_info["suggested_area"] == "Living Room"
