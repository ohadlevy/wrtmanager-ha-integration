"""Tests for Home Assistant deprecation warnings and proper usage patterns."""

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.wrtmanager import async_setup_entry
from custom_components.wrtmanager.const import CONF_ROUTERS, DOMAIN
from tests.conftest import create_mock_entry_with_state

# MockConfigEntry not needed since we create custom mocks


class TestHADeprecationWarnings:
    """Test class for Home Assistant deprecation warnings and proper integration patterns."""

    @pytest.fixture
    def sample_config_data(self):
        """Sample configuration data for testing."""
        return {
            CONF_ROUTERS: [
                {
                    CONF_HOST: "192.168.1.1",
                    CONF_NAME: "Test Router",
                    CONF_USERNAME: "test",
                    CONF_PASSWORD: "test",
                }
            ]
        }

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = Mock()
        hass.data = {DOMAIN: {}}
        hass.config_entries = Mock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        return hass

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock coordinator."""
        coordinator = Mock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.async_refresh = AsyncMock()
        coordinator.last_update_success = True
        return coordinator

    @pytest.mark.asyncio
    async def test_setup_in_progress_uses_first_refresh(
        self, mock_hass, sample_config_data, mock_coordinator
    ):
        """Test async_config_entry_first_refresh used when entry state is SETUP_IN_PROGRESS."""
        # Create config entry with SETUP_IN_PROGRESS state
        entry = create_mock_entry_with_state(sample_config_data, ConfigEntryState.SETUP_IN_PROGRESS)

        # Mock the coordinator creation
        with patch(
            "custom_components.wrtmanager.WrtManagerCoordinator",
            return_value=mock_coordinator,
        ):
            # Setup entry
            result = await async_setup_entry(mock_hass, entry)

            # Verify setup succeeded
            assert result is True

            # Verify async_config_entry_first_refresh was called
            mock_coordinator.async_config_entry_first_refresh.assert_called_once()
            mock_coordinator.async_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_loaded_state_uses_regular_refresh(
        self, mock_hass, sample_config_data, mock_coordinator
    ):
        """Test async_refresh used when entry state is LOADED (avoids deprecation warning)."""
        # Create config entry with LOADED state
        entry = create_mock_entry_with_state(sample_config_data, ConfigEntryState.LOADED)

        # Mock the coordinator creation
        with patch(
            "custom_components.wrtmanager.WrtManagerCoordinator",
            return_value=mock_coordinator,
        ):
            # Setup entry
            result = await async_setup_entry(mock_hass, entry)

            # Verify setup succeeded
            assert result is True

            # Verify async_refresh was called instead of async_config_entry_first_refresh
            mock_coordinator.async_refresh.assert_called_once()
            mock_coordinator.async_config_entry_first_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_loaded_state_uses_regular_refresh(
        self, mock_hass, sample_config_data, mock_coordinator
    ):
        """Test that async_refresh is used for NOT_LOADED state."""
        # Create config entry with NOT_LOADED state
        entry = create_mock_entry_with_state(sample_config_data, ConfigEntryState.NOT_LOADED)

        # Mock the coordinator creation
        with patch(
            "custom_components.wrtmanager.WrtManagerCoordinator",
            return_value=mock_coordinator,
        ):
            # Setup entry
            result = await async_setup_entry(mock_hass, entry)

            # Verify setup succeeded
            assert result is True

            # Verify async_refresh was called instead of async_config_entry_first_refresh
            mock_coordinator.async_refresh.assert_called_once()
            mock_coordinator.async_config_entry_first_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_deprecation_warnings_logged(
        self, mock_hass, sample_config_data, mock_coordinator, caplog
    ):
        """Test that no deprecation warnings are logged during setup."""
        # Create config entry with LOADED state (common scenario that would trigger warning)
        entry = create_mock_entry_with_state(sample_config_data, ConfigEntryState.LOADED)

        # Mock the coordinator creation
        with patch(
            "custom_components.wrtmanager.WrtManagerCoordinator",
            return_value=mock_coordinator,
        ):
            # Capture log output at WARNING level and above
            with caplog.at_level(logging.WARNING):
                result = await async_setup_entry(mock_hass, entry)

                # Verify setup succeeded
                assert result is True

                # Check that no deprecation warnings were logged
                warning_messages = [record.message for record in caplog.records]
                deprecation_warnings = [
                    msg
                    for msg in warning_messages
                    if "async_config_entry_first_refresh" in msg
                    or "deprecation" in msg.lower()
                    or "2025.11" in msg
                ]
                assert (
                    len(deprecation_warnings) == 0
                ), f"Found deprecation warnings: {deprecation_warnings}"

    @pytest.mark.asyncio
    async def test_failed_coordinator_refresh_raises_not_ready(self, mock_hass, sample_config_data):
        """Test that failed coordinator refresh raises ConfigEntryNotReady."""
        # Create a coordinator that fails refresh
        failed_coordinator = Mock()
        failed_coordinator.async_config_entry_first_refresh = AsyncMock()
        failed_coordinator.async_refresh = AsyncMock()
        failed_coordinator.last_update_success = False

        entry = create_mock_entry_with_state(sample_config_data, ConfigEntryState.SETUP_IN_PROGRESS)

        # Mock the coordinator creation
        with patch(
            "custom_components.wrtmanager.WrtManagerCoordinator",
            return_value=failed_coordinator,
        ):
            # Setup should raise ConfigEntryNotReady
            with pytest.raises(ConfigEntryNotReady, match="Failed to initialize WrtManager"):
                await async_setup_entry(mock_hass, entry)

            # Verify the appropriate refresh method was still called
            failed_coordinator.async_config_entry_first_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_coordinator_exception_propagated(self, mock_hass, sample_config_data):
        """Test that coordinator exceptions are properly propagated."""
        # Create a coordinator that raises an exception during refresh
        failing_coordinator = Mock()
        failing_coordinator.async_config_entry_first_refresh = AsyncMock(
            side_effect=Exception("Connection failed")
        )
        failing_coordinator.async_refresh = AsyncMock(side_effect=Exception("Connection failed"))

        entry = create_mock_entry_with_state(sample_config_data, ConfigEntryState.SETUP_IN_PROGRESS)

        # Mock the coordinator creation
        with patch(
            "custom_components.wrtmanager.WrtManagerCoordinator",
            return_value=failing_coordinator,
        ):
            # Setup should propagate the exception
            with pytest.raises(Exception, match="Connection failed"):
                await async_setup_entry(mock_hass, entry)

    @pytest.mark.asyncio
    async def test_multiple_state_scenarios_warning_detection(
        self, mock_hass, sample_config_data, caplog
    ):
        """Test multiple config entry states to ensure no warnings are generated."""
        states_to_test = [
            ConfigEntryState.SETUP_IN_PROGRESS,
            ConfigEntryState.LOADED,
            ConfigEntryState.NOT_LOADED,
            ConfigEntryState.SETUP_ERROR,
            ConfigEntryState.MIGRATION_ERROR,
            ConfigEntryState.SETUP_RETRY,
            ConfigEntryState.FAILED_UNLOAD,
        ]

        for state in states_to_test:
            # Create fresh coordinator for each test
            test_coordinator = Mock()
            test_coordinator.async_config_entry_first_refresh = AsyncMock()
            test_coordinator.async_refresh = AsyncMock()
            test_coordinator.last_update_success = True

            entry = create_mock_entry_with_state(
                sample_config_data, state, f"test_entry_{state.value}"
            )

            # Clear previous log records
            caplog.clear()
            mock_hass.data[DOMAIN].clear()

            with patch(
                "custom_components.wrtmanager.WrtManagerCoordinator",
                return_value=test_coordinator,
            ):
                # Capture logs at WARNING level
                with caplog.at_level(logging.WARNING):
                    result = await async_setup_entry(mock_hass, entry)

                    # Verify setup succeeded for all states
                    assert result is True

                    # Check for any deprecation warnings
                    warning_messages = [record.message for record in caplog.records]
                    deprecation_warnings = [
                        msg
                        for msg in warning_messages
                        if "async_config_entry_first_refresh" in msg
                        or "deprecation" in msg.lower()
                        or "2025.11" in msg
                    ]
                    assert (
                        len(deprecation_warnings) == 0
                    ), f"Found deprecation warnings for state {state}: {deprecation_warnings}"

                    # Verify the correct method was called based on state
                    if state == ConfigEntryState.SETUP_IN_PROGRESS:
                        test_coordinator.async_config_entry_first_refresh.assert_called_once()
                        test_coordinator.async_refresh.assert_not_called()
                    else:
                        test_coordinator.async_refresh.assert_called_once()
                        test_coordinator.async_config_entry_first_refresh.assert_not_called()
