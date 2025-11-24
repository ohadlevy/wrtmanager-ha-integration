"""Tests for the WrtManager integration __init__ module."""

from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager import async_unload_entry
from custom_components.wrtmanager.const import CONF_ROUTERS, DOMAIN


@pytest.mark.asyncio
async def test_async_unload_entry_calls_shutdown():
    """Test that async_unload_entry calls coordinator.async_shutdown()."""
    # Create a mock hass object
    mock_hass = Mock()
    mock_hass.data = {DOMAIN: {}}
    mock_hass.config_entries = Mock()

    # Create a mock config entry
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "test",
                    CONF_PASSWORD: "test",
                }
            ]
        },
        entry_id="test_entry",
    )

    # Create a mock coordinator with async_shutdown method
    mock_coordinator = Mock()
    mock_coordinator.async_shutdown = AsyncMock()

    # Setup hass data
    mock_hass.data[DOMAIN][config_entry.entry_id] = mock_coordinator

    # Mock the async_unload_platforms to return True
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    # Call async_unload_entry
    result = await async_unload_entry(mock_hass, config_entry)

    # Assert that the function returned True
    assert result is True

    # Assert that coordinator.async_shutdown was called
    mock_coordinator.async_shutdown.assert_called_once()

    # Assert that the coordinator was removed from hass.data
    assert config_entry.entry_id not in mock_hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry_shutdown_not_called_on_failure():
    """Test that async_shutdown is not called if platform unload fails."""
    # Create a mock hass object
    mock_hass = Mock()
    mock_hass.data = {DOMAIN: {}}
    mock_hass.config_entries = Mock()

    # Create a mock config entry
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "test",
                    CONF_PASSWORD: "test",
                }
            ]
        },
        entry_id="test_entry",
    )

    # Create a mock coordinator with async_shutdown method
    mock_coordinator = Mock()
    mock_coordinator.async_shutdown = AsyncMock()

    # Setup hass data
    mock_hass.data[DOMAIN][config_entry.entry_id] = mock_coordinator

    # Mock the async_unload_platforms to return False (failure)
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    # Call async_unload_entry
    result = await async_unload_entry(mock_hass, config_entry)

    # Assert that the function returned False
    assert result is False

    # Assert that coordinator.async_shutdown was NOT called
    mock_coordinator.async_shutdown.assert_not_called()

    # Assert that the coordinator was NOT removed from hass.data
    assert config_entry.entry_id in mock_hass.data[DOMAIN]
