"""Test authentication retry logic."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

# Import directly from modules
from custom_components.wrtmanager.ubus_client import (
    UbusAuthenticationError,
    UbusClient,
    UbusConnectionError,
    UbusTimeoutError,
)


class TestCoordinator(WrtManagerCoordinator):
    """Test coordinator that bypasses Home Assistant setup."""

    def __init__(self):
        """Initialize test coordinator with minimal setup."""
        import logging

        # Skip the parent __init__ to avoid Home Assistant dependencies
        self.routers = {}
        self.sessions = {}
        self.device_manager = MagicMock()
        self._device_history = {}
        self.logger = logging.getLogger(__name__)

        # Set minimal required attributes
        self.name = "test_coordinator"
        self.data = None
        self.last_update_success = True


@pytest.mark.asyncio
async def test_authentication_success_first_attempt():
    """Test successful authentication on first attempt."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    mock_client.authenticate.return_value = "test_session_123"

    session_id = await coordinator._authenticate_router("192.168.1.1", mock_client)

    assert session_id == "test_session_123"
    mock_client.authenticate.assert_called_once()


@pytest.mark.asyncio
async def test_authentication_success_second_attempt():
    """Test successful authentication on second attempt after one failure."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    # First call fails, second succeeds
    mock_client.authenticate.side_effect = [
        UbusConnectionError("Network unreachable"),
        "test_session_456",
    ]

    with patch("asyncio.sleep") as mock_sleep:
        session_id = await coordinator._authenticate_router("192.168.1.1", mock_client)

    assert session_id == "test_session_456"
    assert mock_client.authenticate.call_count == 2
    # Verify exponential backoff delay (1.0 * 2^0 = 1.0 second)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_authentication_success_third_attempt():
    """Test successful authentication on third attempt after two failures."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    # First two calls fail, third succeeds
    mock_client.authenticate.side_effect = [
        UbusTimeoutError("Timeout"),
        UbusAuthenticationError("Permission denied"),
        "test_session_789",
    ]

    with patch("asyncio.sleep") as mock_sleep:
        session_id = await coordinator._authenticate_router("192.168.1.1", mock_client)

    assert session_id == "test_session_789"
    assert mock_client.authenticate.call_count == 3
    # Verify exponential backoff delays (1.0, then 2.0 seconds)
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)  # First retry delay
    mock_sleep.assert_any_call(2.0)  # Second retry delay


@pytest.mark.asyncio
async def test_authentication_fails_all_attempts():
    """Test authentication failure after all 3 attempts exhausted."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    error_msg = "Permission denied"
    mock_client.authenticate.side_effect = UbusAuthenticationError(error_msg)

    with patch("asyncio.sleep") as mock_sleep:
        with pytest.raises(UpdateFailed) as exc_info:
            await coordinator._authenticate_router("192.168.1.1", mock_client)

    # Should have tried 3 times
    assert mock_client.authenticate.call_count == 3
    # Should have slept twice (before 2nd and 3rd attempts)
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)  # First retry delay
    mock_sleep.assert_any_call(2.0)  # Second retry delay

    # Check error message contains retry count
    assert "after 3 attempts" in str(exc_info.value)
    assert error_msg in str(exc_info.value)


@pytest.mark.asyncio
async def test_authentication_different_error_types():
    """Test retry logic with different types of authentication errors."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    # Different error types for each attempt
    mock_client.authenticate.side_effect = [
        UbusConnectionError("Connection refused"),
        UbusTimeoutError("Request timeout"),
        UbusAuthenticationError("Invalid credentials"),
    ]

    with patch("asyncio.sleep") as mock_sleep:
        with pytest.raises(UpdateFailed) as exc_info:
            await coordinator._authenticate_router("192.168.1.1", mock_client)

    assert mock_client.authenticate.call_count == 3
    assert mock_sleep.call_count == 2
    assert "Invalid credentials" in str(exc_info.value)


@pytest.mark.asyncio
async def test_authentication_exponential_backoff_timing():
    """Test that exponential backoff timing is correct."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    mock_client.authenticate.side_effect = [
        UbusConnectionError("Network error"),
        UbusTimeoutError("Timeout"),
        UbusAuthenticationError("Permission denied"),
    ]

    sleep_calls = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(UpdateFailed):
            await coordinator._authenticate_router("192.168.1.1", mock_client)

    # Verify exponential backoff: 1.0 * 2^0 = 1.0, 1.0 * 2^1 = 2.0
    assert sleep_calls == [1.0, 2.0]


@pytest.mark.asyncio
async def test_authentication_no_session_id_returned():
    """Test authentication failure when no session ID is returned."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    mock_client.authenticate.return_value = None  # No session ID

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._authenticate_router("192.168.1.1", mock_client)

    assert "Authentication failed for 192.168.1.1" in str(exc_info.value)
    mock_client.authenticate.assert_called_once()


@pytest.mark.asyncio
async def test_authentication_empty_session_id_returned():
    """Test authentication failure when empty session ID is returned."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    mock_client.authenticate.return_value = ""  # Empty session ID

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._authenticate_router("192.168.1.1", mock_client)

    assert "Authentication failed for 192.168.1.1" in str(exc_info.value)
    mock_client.authenticate.assert_called_once()


@pytest.mark.asyncio
async def test_multiple_routers_authentication_parallel():
    """Test that multiple routers authenticate in parallel even with retries."""
    coordinator = TestCoordinator()
    # Create clients for multiple routers
    mock_client1 = AsyncMock(spec=UbusClient)
    mock_client2 = AsyncMock(spec=UbusClient)

    # Client 1 succeeds immediately, Client 2 needs retry
    mock_client1.authenticate.return_value = "session_1"
    mock_client2.authenticate.side_effect = [UbusTimeoutError("Timeout"), "session_2"]

    with patch("asyncio.sleep"):
        # Simulate parallel authentication
        tasks = [
            coordinator._authenticate_router("192.168.1.1", mock_client1),
            coordinator._authenticate_router("192.168.1.2", mock_client2),
        ]

        results = await asyncio.gather(*tasks)

    assert results == ["session_1", "session_2"]
    mock_client1.authenticate.assert_called_once()
    assert mock_client2.authenticate.call_count == 2


@pytest.mark.asyncio
async def test_authentication_retry_preserves_original_error_message():
    """Test that the original error message is preserved in the final failure."""
    coordinator = TestCoordinator()
    mock_client = AsyncMock(spec=UbusClient)
    original_error = UbusAuthenticationError("Invalid username or password")
    mock_client.authenticate.side_effect = original_error

    with patch("asyncio.sleep"):
        with pytest.raises(UpdateFailed) as exc_info:
            await coordinator._authenticate_router("192.168.1.1", mock_client)

    # Original error message should be preserved
    assert "Invalid username or password" in str(exc_info.value)
    assert "after 3 attempts" in str(exc_info.value)
