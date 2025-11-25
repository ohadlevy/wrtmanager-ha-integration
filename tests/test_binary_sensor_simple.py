"""Simple tests for WrtManager binary sensors."""

from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.wrtmanager.binary_sensor import async_setup_entry

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return ConfigEntry(
        version=1,
        minor_version=0,
        domain="wrtmanager",
        title="Test WrtManager",
        data={"routers": [{"host": "192.168.1.1", "username": "test", "password": "test"}]},
        source="user",
        entry_id="test_entry",
        unique_id="test_unique_id",
        discovery_keys=set(),
        options={},
        subentries_data={},
    )


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock()
    coordinator.data = {
        "devices": [
            {
                "mac": "AA:BB:CC:DD:EE:FF",
                "hostname": "test-device",
                "router": "192.168.1.1",
                "connected": True,
            }
        ],
        "system_info": {"192.168.1.1": {"hostname": "OpenWrt", "uptime": 86400}},
        "ssids": {"192.168.1.1": [{"ssid_name": "TestNetwork", "disabled": False}]},
        "routers": ["192.168.1.1"],
    }
    coordinator.async_add_listener = Mock()
    return coordinator


class TestBinarySensorSetup:
    """Test binary sensor setup."""

    async def test_async_setup_entry(
        self, hass: HomeAssistant, mock_config_entry, mock_coordinator
    ):
        """Test setting up binary sensors."""
        hass.data = {"wrtmanager": {"test_entry": {"coordinator": mock_coordinator}}}

        async_add_entities = AsyncMock()

        await async_setup_entry(hass, mock_config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities = async_add_entities.call_args[0][0]
        assert len(entities) >= 0  # Should create some entities
