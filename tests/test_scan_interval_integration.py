"""Tests for scan interval integration with coordinator setup."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wrtmanager import async_setup_entry
from custom_components.wrtmanager.const import (
    CONF_ROUTERS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    mock_hass = Mock()
    mock_hass.data = {}
    mock_hass.config_entries = Mock()
    mock_hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    return mock_hass


@pytest.fixture
def config_entry_default_scan_interval():
    """Config entry with default scan interval (no options set)."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "hass",
                    CONF_PASSWORD: "test123",
                }
            ]
        },
        options={},  # No options set, should use default
        entry_id="test_entry",
    )


@pytest.fixture
def config_entry_custom_scan_interval():
    """Config entry with custom scan interval."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "hass",
                    CONF_PASSWORD: "test123",
                }
            ]
        },
        options={CONF_SCAN_INTERVAL: 120},  # Custom 2-minute interval
        entry_id="test_entry",
    )


@pytest.mark.asyncio
@patch("custom_components.wrtmanager.WrtManagerCoordinator")
async def test_setup_entry_uses_default_scan_interval(
    mock_coordinator_class, mock_hass, config_entry_default_scan_interval
):
    """Test that setup uses default scan interval when no options are set."""
    # Mock the coordinator instance
    mock_coordinator_instance = Mock()
    mock_coordinator_instance.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_instance.last_update_success = True
    mock_coordinator_class.return_value = mock_coordinator_instance

    # Mock add_update_listener
    config_entry_default_scan_interval.add_update_listener = Mock()
    config_entry_default_scan_interval.async_on_unload = Mock()

    result = await async_setup_entry(mock_hass, config_entry_default_scan_interval)

    assert result is True

    # Verify coordinator was created with default scan interval
    mock_coordinator_class.assert_called_once()
    call_args = mock_coordinator_class.call_args

    # Check that update_interval is set correctly
    assert call_args.kwargs["update_interval"] == timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    assert call_args.kwargs["config_entry"] == config_entry_default_scan_interval


@pytest.mark.asyncio
@patch("custom_components.wrtmanager.WrtManagerCoordinator")
async def test_setup_entry_uses_custom_scan_interval(
    mock_coordinator_class, mock_hass, config_entry_custom_scan_interval
):
    """Test that setup uses custom scan interval from options."""
    # Mock the coordinator instance
    mock_coordinator_instance = Mock()
    mock_coordinator_instance.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_instance.last_update_success = True
    mock_coordinator_class.return_value = mock_coordinator_instance

    # Mock add_update_listener
    config_entry_custom_scan_interval.add_update_listener = Mock()
    config_entry_custom_scan_interval.async_on_unload = Mock()

    result = await async_setup_entry(mock_hass, config_entry_custom_scan_interval)

    assert result is True

    # Verify coordinator was created with custom scan interval
    mock_coordinator_class.assert_called_once()
    call_args = mock_coordinator_class.call_args

    # Check that update_interval is set correctly (120 seconds from options)
    assert call_args.kwargs["update_interval"] == timedelta(seconds=120)
    assert call_args.kwargs["config_entry"] == config_entry_custom_scan_interval


@pytest.mark.asyncio
@patch("custom_components.wrtmanager.WrtManagerCoordinator")
async def test_setup_entry_registers_update_listener(
    mock_coordinator_class, mock_hass, config_entry_default_scan_interval
):
    """Test that setup registers an update listener for option changes."""
    # Mock the coordinator instance
    mock_coordinator_instance = Mock()
    mock_coordinator_instance.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_instance.last_update_success = True
    mock_coordinator_class.return_value = mock_coordinator_instance

    # Mock add_update_listener and async_on_unload
    mock_update_listener = Mock()
    config_entry_default_scan_interval.add_update_listener = Mock(return_value=mock_update_listener)
    config_entry_default_scan_interval.async_on_unload = Mock()

    result = await async_setup_entry(mock_hass, config_entry_default_scan_interval)

    assert result is True

    # Verify update listener was added
    config_entry_default_scan_interval.add_update_listener.assert_called_once()
    config_entry_default_scan_interval.async_on_unload.assert_called_once_with(mock_update_listener)


def test_scan_interval_boundary_values():
    """Test that scan interval boundary values are handled correctly."""
    # Test minimum allowed value
    config_entry_min = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ROUTERS: [{"host": "192.168.1.1", "name": "Test"}]},
        options={CONF_SCAN_INTERVAL: 10},  # Minimum allowed
        entry_id="test",
    )

    scan_interval = config_entry_min.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    assert scan_interval == 10
    assert timedelta(seconds=scan_interval) == timedelta(seconds=10)

    # Test maximum allowed value
    config_entry_max = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ROUTERS: [{"host": "192.168.1.1", "name": "Test"}]},
        options={CONF_SCAN_INTERVAL: 300},  # Maximum allowed
        entry_id="test",
    )

    scan_interval = config_entry_max.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    assert scan_interval == 300
    assert timedelta(seconds=scan_interval) == timedelta(minutes=5)


@pytest.mark.asyncio
@patch("custom_components.wrtmanager.WrtManagerCoordinator")
async def test_setup_entry_coordinator_failure_with_custom_interval(
    mock_coordinator_class, mock_hass, config_entry_custom_scan_interval
):
    """Test setup handles coordinator failure with custom scan interval."""
    from homeassistant.exceptions import ConfigEntryNotReady

    # Mock coordinator to fail initial refresh
    mock_coordinator_instance = Mock()
    mock_coordinator_instance.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_instance.last_update_success = False  # Simulate failure
    mock_coordinator_class.return_value = mock_coordinator_instance

    # Mock add_update_listener
    config_entry_custom_scan_interval.add_update_listener = Mock()
    config_entry_custom_scan_interval.async_on_unload = Mock()

    # Expect ConfigEntryNotReady to be raised
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(mock_hass, config_entry_custom_scan_interval)

    # Verify coordinator was still created with correct interval
    mock_coordinator_class.assert_called_once()
    call_args = mock_coordinator_class.call_args
    assert call_args.kwargs["update_interval"] == timedelta(seconds=120)


def test_scan_interval_logging_values():
    """Test different scan interval values produce correct log messages."""
    test_cases = [
        (None, DEFAULT_SCAN_INTERVAL),  # No options set
        (60, 60),  # Custom value
        (10, 10),  # Minimum value
        (300, 300),  # Maximum value
    ]

    for option_value, expected_seconds in test_cases:
        config_entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_ROUTERS: [{"host": "192.168.1.1", "name": "Test"}]},
            options={CONF_SCAN_INTERVAL: option_value} if option_value else {},
            entry_id="test",
        )

        actual_seconds = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        assert actual_seconds == expected_seconds

        # Test timedelta conversion
        interval = timedelta(seconds=actual_seconds)
        assert interval.total_seconds() == expected_seconds


def test_scan_interval_constants_consistency():
    """Test that scan interval constants are consistent."""
    # Verify DEFAULT_SCAN_INTERVAL is within valid range (10-300)
    assert 10 <= DEFAULT_SCAN_INTERVAL <= 300
    assert DEFAULT_SCAN_INTERVAL == 30

    # Verify CONF_SCAN_INTERVAL is a string
    assert isinstance(CONF_SCAN_INTERVAL, str)
    assert CONF_SCAN_INTERVAL == "scan_interval"
