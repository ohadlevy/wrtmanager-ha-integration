"""Tests for the WrtManager integration __init__ module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager import async_setup_entry, async_unload_entry
from custom_components.wrtmanager.const import CONF_ROUTERS, DOMAIN


def _make_hass(is_running=True):
    """Create a mock hass object suitable for testing async_setup_entry."""
    mock_hass = Mock()
    mock_hass.data = {}
    mock_hass.is_running = is_running
    mock_hass.config_entries = Mock()
    mock_hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    mock_hass.http = Mock()
    mock_hass.http.async_register_static_paths = AsyncMock()
    mock_hass.bus = Mock()
    mock_hass.bus.async_listen_once = Mock()

    resources_mock = Mock()
    resources_mock.async_items = Mock(return_value=[])
    resources_mock.async_create_item = AsyncMock()
    lovelace_mock = Mock()
    lovelace_mock.resources = resources_mock
    mock_hass.data["lovelace"] = lovelace_mock

    return mock_hass


def _make_entry(entry_id="test_entry"):
    """Create a mock config entry."""
    from homeassistant.config_entries import ConfigEntryState

    entry = MockConfigEntry(
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
        entry_id=entry_id,
    )
    # Set state so setup uses regular refresh path
    entry._state = ConfigEntryState.LOADED
    return entry


def _make_coordinator():
    mock_coordinator = Mock()
    mock_coordinator.last_update_success = True
    mock_coordinator.async_refresh = AsyncMock()
    mock_coordinator.async_shutdown = AsyncMock()
    return mock_coordinator


@pytest.mark.asyncio
async def test_deferred_registration_when_ha_not_running():
    """async_listen_once is called (not async_create_item) when HA hasn't started."""
    mock_hass = _make_hass(is_running=False)
    entry = _make_entry()
    coordinator = _make_coordinator()

    with patch("custom_components.wrtmanager.WrtManagerCoordinator", return_value=coordinator):
        result = await async_setup_entry(mock_hass, entry)

    assert result is True
    # Static path registered immediately
    mock_hass.http.async_register_static_paths.assert_called_once()
    # Listener registered for deferred resource write
    mock_hass.bus.async_listen_once.assert_called_once()
    event_name, callback = mock_hass.bus.async_listen_once.call_args[0]
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

    assert event_name == EVENT_HOMEASSISTANT_STARTED
    # Resource not created yet
    mock_hass.data["lovelace"].resources.async_create_item.assert_not_called()

    # Simulate HA started event firing
    await callback(None)
    mock_hass.data["lovelace"].resources.async_create_item.assert_called_once()


@pytest.mark.asyncio
async def test_immediate_registration_when_ha_running():
    """async_create_item is called immediately when HA is already running (reload)."""
    mock_hass = _make_hass(is_running=True)
    entry = _make_entry()
    coordinator = _make_coordinator()

    with patch("custom_components.wrtmanager.WrtManagerCoordinator", return_value=coordinator):
        result = await async_setup_entry(mock_hass, entry)

    assert result is True
    mock_hass.data["lovelace"].resources.async_create_item.assert_called_once()
    mock_hass.bus.async_listen_once.assert_not_called()


@pytest.mark.asyncio
async def test_guard_prevents_double_registration():
    """Guard flag prevents double registration when two config entries load."""
    mock_hass = _make_hass(is_running=True)
    entry1 = _make_entry("entry1")
    entry2 = _make_entry("entry2")
    coordinator1 = _make_coordinator()
    coordinator2 = _make_coordinator()

    with patch(
        "custom_components.wrtmanager.WrtManagerCoordinator",
        side_effect=[coordinator1, coordinator2],
    ):
        await async_setup_entry(mock_hass, entry1)
        await async_setup_entry(mock_hass, entry2)

    mock_hass.http.async_register_static_paths.assert_called_once()
    mock_hass.data["lovelace"].resources.async_create_item.assert_called_once()


@pytest.mark.asyncio
async def test_guard_cleared_after_all_entries_unloaded():
    """Guard is cleared only when the last entry is unloaded; re-registration works."""
    mock_hass = _make_hass(is_running=True)
    entry1 = _make_entry("entry1")
    entry2 = _make_entry("entry2")
    coordinator1 = _make_coordinator()
    coordinator2 = _make_coordinator()

    with patch(
        "custom_components.wrtmanager.WrtManagerCoordinator",
        side_effect=[coordinator1, coordinator2],
    ):
        await async_setup_entry(mock_hass, entry1)
        await async_setup_entry(mock_hass, entry2)

    # Unload first entry — guard should still be set
    await async_unload_entry(mock_hass, entry1)
    assert f"{DOMAIN}_cards_registered" in mock_hass.data

    # Unload second entry — guard should be cleared
    await async_unload_entry(mock_hass, entry2)
    assert f"{DOMAIN}_cards_registered" not in mock_hass.data

    # Re-setup should re-register
    entry3 = _make_entry("entry3")
    coordinator3 = _make_coordinator()
    with patch("custom_components.wrtmanager.WrtManagerCoordinator", return_value=coordinator3):
        await async_setup_entry(mock_hass, entry3)

    assert mock_hass.data["lovelace"].resources.async_create_item.call_count == 2


@pytest.mark.asyncio
async def test_already_registered_resource_is_skipped():
    """async_create_item is not called if the resource URL is already present."""
    from custom_components.wrtmanager import CARDS_RESOURCE_URL

    mock_hass = _make_hass(is_running=True)
    mock_hass.data["lovelace"].resources.async_items = Mock(
        return_value=[{"res_type": "module", "url": CARDS_RESOURCE_URL}]
    )
    entry = _make_entry()
    coordinator = _make_coordinator()

    with patch("custom_components.wrtmanager.WrtManagerCoordinator", return_value=coordinator):
        await async_setup_entry(mock_hass, entry)

    mock_hass.data["lovelace"].resources.async_create_item.assert_not_called()


@pytest.mark.asyncio
async def test_exception_during_resource_write_is_swallowed():
    """Exception in async_create_item is caught; setup still returns True."""
    mock_hass = _make_hass(is_running=True)
    mock_hass.data["lovelace"].resources.async_create_item = AsyncMock(
        side_effect=Exception("boom")
    )
    entry = _make_entry()
    coordinator = _make_coordinator()

    with patch("custom_components.wrtmanager.WrtManagerCoordinator", return_value=coordinator):
        result = await async_setup_entry(mock_hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_unload_entry_calls_shutdown():
    """Test that async_unload_entry calls coordinator.async_shutdown()."""
    mock_hass = Mock()
    mock_hass.data = {DOMAIN: {}}
    mock_hass.config_entries = Mock()

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

    mock_coordinator = Mock()
    mock_coordinator.async_shutdown = AsyncMock()

    mock_hass.data[DOMAIN][config_entry.entry_id] = mock_coordinator
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    result = await async_unload_entry(mock_hass, config_entry)

    assert result is True
    mock_coordinator.async_shutdown.assert_called_once()
    assert config_entry.entry_id not in mock_hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry_shutdown_not_called_on_failure():
    """Test that async_shutdown is not called if platform unload fails."""
    mock_hass = Mock()
    mock_hass.data = {DOMAIN: {}}
    mock_hass.config_entries = Mock()

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

    mock_coordinator = Mock()
    mock_coordinator.async_shutdown = AsyncMock()

    mock_hass.data[DOMAIN][config_entry.entry_id] = mock_coordinator
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    result = await async_unload_entry(mock_hass, config_entry)

    assert result is False
    mock_coordinator.async_shutdown.assert_not_called()
    assert config_entry.entry_id in mock_hass.data[DOMAIN]
