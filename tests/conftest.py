"""Shared test fixtures and utilities."""

from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry

from custom_components.wrtmanager.const import DOMAIN


def create_mock_entry_with_state(config_data, state, entry_id="test_entry"):
    """Create a mock config entry with a specific state."""
    entry = Mock(spec=ConfigEntry)
    entry.domain = DOMAIN
    entry.data = config_data
    entry.entry_id = entry_id
    entry.state = state
    entry.options = {}
    entry.add_update_listener = Mock(return_value=Mock())
    entry.async_on_unload = Mock(return_value=Mock())
    return entry
