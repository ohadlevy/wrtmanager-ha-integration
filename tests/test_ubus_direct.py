"""Direct tests for UbusClient without any HA dependencies."""

# Import UbusClient directly from the file
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "wrtmanager"))

# Import directly from the ubus_client module
from ubus_client import UbusAuthenticationError, UbusClient

# All tests now use individual mocking to avoid aiohttp threading issues


@pytest.mark.asyncio
async def test_authentication_success():
    """Test successful authentication."""
    auth_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [
            0,
            {
                "ubus_rpc_session": "test_session_123",
                "timeout": 300,
                "expires": 299,
            },
        ],
    }

    async def mock_make_request(self, request_data):
        return auth_response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            session_id = await client.authenticate()
            assert session_id == "test_session_123"


@pytest.mark.asyncio
async def test_authentication_failure():
    """Test authentication failure."""
    auth_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [1, {}],  # Error code 1 = authentication failed
    }

    async def mock_make_request(self, request_data):
        return auth_response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "wrong_password") as client:
            with pytest.raises(UbusAuthenticationError):
                await client.authenticate()


@pytest.mark.asyncio
async def test_call_ubus_success():
    """Test successful ubus call."""
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [0, {"test": "data"}],
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.call_ubus("session", "service", "method", {})
            assert result == {"test": "data"}


@pytest.mark.asyncio
async def test_close_session():
    """Test closing the session."""
    with patch.object(UbusClient, "_make_request", AsyncMock()):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            # Mock the session
            mock_session = AsyncMock()
            client._session = mock_session

            await client.close()

            # Verify close was called on the mock session
            mock_session.close.assert_called_once()
            assert client._session is None


@pytest.mark.asyncio
async def test_https_client_url():
    """Test that HTTPS client uses correct URL."""
    with patch.object(UbusClient, "_make_request", AsyncMock()):
        async with UbusClient("192.168.1.1", "hass", "password", use_https=True) as client:
            # Verify HTTPS URL is used
            assert client.base_url == "https://192.168.1.1/ubus"
            assert client.use_https is True
            assert client.verify_ssl is False  # Default


@pytest.mark.asyncio
async def test_http_client_url():
    """Test that HTTP client uses correct URL (default)."""
    with patch.object(UbusClient, "_make_request", AsyncMock()):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            # Verify HTTP URL is used by default
            assert client.base_url == "http://192.168.1.1/ubus"
            assert client.use_https is False
            assert client.verify_ssl is False


@pytest.mark.asyncio
async def test_https_authentication_success():
    """Test successful authentication with HTTPS."""
    auth_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [
            0,
            {
                "ubus_rpc_session": "test_https_session",
                "timeout": 300,
                "expires": 299,
            },
        ],
    }

    async def mock_make_request(self, request_data):
        return auth_response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient(
            "192.168.1.1", "hass", "password", use_https=True, verify_ssl=False
        ) as client:
            session_id = await client.authenticate()
            assert session_id == "test_https_session"


@pytest.mark.asyncio
async def test_https_call_ubus_success():
    """Test successful ubus call with HTTPS."""
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [0, {"secure": "data"}],
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password", use_https=True) as client:
            result = await client.call_ubus("session", "service", "method", {})
            assert result == {"secure": "data"}
