"""Integration tests for WrtManager Home Assistant integration."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from custom_components.wrtmanager.binary_sensor import (
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.wrtmanager.const import CONF_ROUTERS, DOMAIN
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.sensor import async_setup_entry as async_setup_sensors


class TestWrtManagerIntegration:
    """Test WrtManager integration setup and entity creation."""

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry."""
        return Mock(spec=ConfigEntry)

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
        return hass

    @pytest.fixture
    def sample_router_config(self):
        """Sample router configuration."""
        return {
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Main Router",
                    CONF_USERNAME: "hass",
                    CONF_PASSWORD: "testing123",
                }
            ]
        }

    @pytest.fixture
    def mock_coordinator_data(self):
        """Sample coordinator data with devices and SSIDs."""
        return {
            "devices": [
                {
                    "mac": "AA:BB:CC:DD:EE:FF",
                    "interface": "wlan0",
                    "signal_dbm": -45,
                    "router": "192.168.1.1",
                    "connected": True,
                    "hostname": "test-device",
                    "ip": "192.168.1.100",
                    "vendor": "Apple",
                    "device_type": "Mobile Device",
                    "vlan_id": 1,
                }
            ],
            "system_info": {
                "192.168.1.1": {
                    "uptime": 86400,
                    "memory": {"total": 131072, "free": 65536},
                    "load": [0.1, 0.2, 0.3],
                    "model": "Test Router",
                }
            },
            "interfaces": {
                "192.168.1.1": {
                    "eth0": {"up": True, "carrier": True, "type": "ethernet"},
                    "radio0": {
                        "interfaces": [
                            {
                                "config": {
                                    "ssid": "TestNetwork",
                                    "mode": "ap",
                                    "disabled": False,
                                    "encryption": "psk2",
                                    "network": "lan",
                                },
                                "ifname": "wlan0",
                            }
                        ]
                    },
                    "radio1": {
                        "interfaces": [
                            {
                                "config": {
                                    "ssid": "TestNetwork",
                                    "mode": "ap",
                                    "disabled": False,
                                    "encryption": "psk2",
                                    "network": "lan",
                                },
                                "ifname": "wlan1",
                            }
                        ]
                    },
                }
            },
            "ssids": {
                "192.168.1.1": [
                    {
                        "radio": "multi_radio_testnetwork",
                        "ssid_interface": "interface_0",
                        "ssid_name": "TestNetwork",
                        "mode": "ap",
                        "disabled": False,
                        "network_interface": "wlan0",
                        "router_host": "192.168.1.1",
                        "encryption": "psk2",
                        "hidden": False,
                        "isolate": False,
                        "network": "lan",
                        "is_consolidated": True,
                        "radios": ["radio0", "radio1"],
                        "ssid_interfaces": ["interface_0", "interface_0"],
                        "network_interfaces": ["wlan0", "wlan1"],
                        "radio_count": 2,
                        "frequency_bands": ["2.4GHz", "5GHz"],
                    }
                ]
            },
            "routers": ["192.168.1.1"],
            "last_update": datetime.now(),
            "total_devices": 1,
        }

    def test_coordinator_import(self):
        """Test that coordinator imports without errors."""
        from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

        assert WrtManagerCoordinator is not None

    def test_binary_sensor_imports(self):
        """Test that binary sensor module imports without errors."""
        from custom_components.wrtmanager.binary_sensor import (
            WrtDevicePresenceSensor,
            WrtInterfaceStatusSensor,
            WrtSSIDBinarySensor,
            async_setup_entry,
        )

        # Verify all required attributes are imported
        from custom_components.wrtmanager.const import (
            ATTR_HOSTNAME,
            ATTR_INTERFACE,
            ATTR_MAC,
            ATTR_RADIO,
            ATTR_SIGNAL_DBM,
            ATTR_SSID_NAME,
        )

        assert WrtDevicePresenceSensor is not None
        assert WrtInterfaceStatusSensor is not None
        assert WrtSSIDBinarySensor is not None
        assert async_setup_entry is not None

    def test_sensor_imports(self):
        """Test that sensor module imports without errors."""
        from custom_components.wrtmanager.sensor import (
            WrtManagerDeviceCountSensor,
            WrtManagerInterfaceDeviceCountSensor,
            WrtManagerMemoryUsageSensor,
            WrtManagerUptimeSensor,
            async_setup_entry,
        )

        assert WrtManagerUptimeSensor is not None
        assert WrtManagerMemoryUsageSensor is not None
        assert WrtManagerDeviceCountSensor is not None
        assert WrtManagerInterfaceDeviceCountSensor is not None
        assert async_setup_entry is not None

    @pytest.mark.asyncio
    async def test_coordinator_data_update_structure(self, sample_router_config):
        """Test coordinator data update creates expected structure."""
        import logging
        from datetime import timedelta

        from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

        # Mock Home Assistant
        hass = Mock()
        hass.data = {DOMAIN: {}}

        # Mock config entry
        config_entry = Mock()
        config_entry.data = sample_router_config
        config_entry.entry_id = "test_entry"

        coordinator = WrtManagerCoordinator(
            hass=hass,
            logger=logging.getLogger(__name__),
            name="test",
            update_interval=timedelta(minutes=1),
            config_entry=config_entry,
        )

        # Mock ubus client methods
        with (
            patch.object(coordinator, "_authenticate_router", return_value="session123"),
            patch.object(coordinator, "_collect_router_data") as mock_collect,
        ):

            # Setup mock data response
            mock_collect.return_value = (
                [
                    {
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "interface": "wlan0",
                        "router": "192.168.1.1",
                        "connected": True,
                    }
                ],
                {"AA:BB:CC:DD:EE:FF": {"ip": "192.168.1.100", "hostname": "test"}},
                {"uptime": 86400, "memory": {"total": 131072, "free": 65536}},
                {"eth0": {"up": True, "carrier": True}},
            )

            # Test data update
            data = await coordinator._async_update_data()

            # Verify structure
            assert "devices" in data
            assert "system_info" in data
            assert "interfaces" in data
            assert "ssids" in data
            assert "routers" in data
            assert "last_update" in data
            assert "total_devices" in data

    def test_ssid_consolidation_logic(self, mock_coordinator_data):
        """Test SSID consolidation logic works correctly."""
        from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

        coordinator = WrtManagerCoordinator(
            hass=Mock(), logger=Mock(), name="test", update_interval=Mock(), config_entry=Mock()
        )

        # Test consolidation with sample data
        sample_ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "TestNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
                {
                    "radio": "radio1",
                    "ssid_name": "TestNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
            ]
        }

        consolidated = coordinator._consolidate_ssids_by_name(sample_ssid_data)

        # Should have one router with one consolidated SSID
        assert len(consolidated["192.168.1.1"]) == 1
        consolidated_ssid = consolidated["192.168.1.1"][0]

        # Check consolidation properties
        assert consolidated_ssid["is_consolidated"] is True
        assert consolidated_ssid["radio_count"] == 2
        assert "radio0" in consolidated_ssid["radios"]
        assert "radio1" in consolidated_ssid["radios"]
        assert consolidated_ssid["frequency_bands"] == ["2.4GHz", "5GHz"]

    @pytest.mark.asyncio
    async def test_binary_sensor_entity_creation(
        self, mock_hass, mock_config_entry, mock_coordinator_data
    ):
        """Test that binary sensor entities are created correctly."""
        # Setup coordinator with data
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = mock_coordinator_data
        coordinator.last_update_success = True
        coordinator.config_entry = mock_config_entry

        # Mock config entry data
        mock_config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Test Router"}]}
        mock_config_entry.options = {}
        mock_config_entry.entry_id = "test_entry"

        # Setup hass data
        mock_hass.data[DOMAIN] = {"test_entry": coordinator}

        # Mock entity add callback
        entities_added = []
        async_add_entities = Mock(side_effect=lambda entities: entities_added.extend(entities))

        # Test binary sensor setup
        await async_setup_binary_sensors(mock_hass, mock_config_entry, async_add_entities)

        # Verify entities were created
        assert len(entities_added) > 0

        # Check for device presence sensor
        device_sensors = [e for e in entities_added if hasattr(e, "_mac")]
        assert len(device_sensors) >= 1

        # Check for interface status sensors
        interface_sensors = [e for e in entities_added if hasattr(e, "_interface_name")]
        assert len(interface_sensors) >= 1

        # Check for SSID binary sensors
        ssid_sensors = [e for e in entities_added if hasattr(e, "_ssid_info")]
        assert len(ssid_sensors) >= 1

    @pytest.mark.asyncio
    async def test_sensor_entity_creation(
        self, mock_hass, mock_config_entry, mock_coordinator_data
    ):
        """Test that sensor entities are created correctly."""
        # Setup coordinator with data
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = mock_coordinator_data
        coordinator.last_update_success = True

        # Mock config entry data
        mock_config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Test Router"}]}

        # Setup hass data
        mock_hass.data[DOMAIN] = {"test_entry": coordinator}

        # Mock entity add callback
        entities_added = []
        async_add_entities = Mock(side_effect=lambda entities: entities_added.extend(entities))

        # Test sensor setup
        await async_setup_sensors(mock_hass, mock_config_entry, async_add_entities)

        # Verify entities were created
        assert len(entities_added) > 0

        # Check for system monitoring sensors
        system_sensors = [e for e in entities_added if hasattr(e, "_sensor_type")]
        assert len(system_sensors) >= 4  # uptime, memory, load, temperature

        # Check for device count sensors
        device_count_sensors = [
            e for e in entities_added if "device_count" in getattr(e, "_sensor_type", "")
        ]
        assert len(device_count_sensors) >= 1

    def test_error_handling_coordinator_no_data(self, mock_hass, mock_config_entry):
        """Test entity setup handles coordinator with no data gracefully."""
        # Setup coordinator with no data
        coordinator = Mock(spec=WrtManagerCoordinator)
        coordinator.data = None
        coordinator.last_update_success = False

        mock_config_entry.entry_id = "test_entry"
        mock_hass.data[DOMAIN] = {"test_entry": coordinator}

        # Mock entity add callback
        async_add_entities = Mock()

        # This should not raise an exception
        asyncio.get_event_loop().run_until_complete(
            async_setup_binary_sensors(mock_hass, mock_config_entry, async_add_entities)
        )

    def test_frequency_band_detection(self):
        """Test frequency band detection from radio names."""
        from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

        coordinator = WrtManagerCoordinator(
            hass=Mock(), logger=Mock(), name="test", update_interval=Mock(), config_entry=Mock()
        )

        # Test radio name to frequency mapping
        bands = coordinator._get_frequency_bands(["radio0", "radio1"])
        assert bands == ["2.4GHz", "5GHz"]

        bands = coordinator._get_frequency_bands(["radio0"])
        assert bands == ["2.4GHz"]

        bands = coordinator._get_frequency_bands(["radio1"])
        assert bands == ["5GHz"]

        bands = coordinator._get_frequency_bands(["unknown_radio"])
        assert bands == ["Unknown"]
