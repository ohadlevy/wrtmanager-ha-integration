"""Direct tests for UbusClient without any HA dependencies."""

import asyncio
import gc
import json

# Import UbusClient directly from the file
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aioresponses import aioresponses

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "wrtmanager"))

# Import directly from the ubus_client module
from ubus_client import (
    UbusAuthenticationError,
    UbusClient,
    UbusClientError,
    UbusConnectionError,
    UbusTimeoutError,
)


@pytest_asyncio.fixture
async def ubus_client():
    """Fixture that provides a UbusClient with automatic cleanup using context manager."""
    async with UbusClient("192.168.1.1", "hass", "password") as client:
        yield client


@pytest_asyncio.fixture
async def https_ubus_client():
    """Fixture that provides an HTTPS UbusClient with automatic cleanup using context manager."""
    async with UbusClient(
        "192.168.1.1", "hass", "password", use_https=True, verify_ssl=False
    ) as client:
        yield client


@pytest_asyncio.fixture
async def ubus_client_wrong_password():
    """Fixture that provides a UbusClient with wrong password for testing auth failures."""
    async with UbusClient("192.168.1.1", "hass", "wrong_password") as client:
        yield client


@pytest.mark.asyncio
async def test_authentication_success(ubus_client):
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

    with aioresponses() as m:
        m.post(
            "http://192.168.1.1/ubus",
            payload=auth_response,
            status=200,
        )

        session_id = await ubus_client.authenticate()
        assert session_id == "test_session_123"


@pytest.mark.asyncio
async def test_authentication_failure(ubus_client_wrong_password):
    """Test authentication failure."""
    auth_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [1, {}],  # Error code 1 = authentication failed
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=auth_response, status=200)

        with pytest.raises(UbusAuthenticationError):
            await ubus_client_wrong_password.authenticate()


@pytest.mark.asyncio
async def test_call_ubus_success():
    """Test successful ubus call."""
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [0, {"test": "data"}],
    }

    async with UbusClient("192.168.1.1", "hass", "password") as client:
        with aioresponses() as m:
            m.post("http://192.168.1.1/ubus", payload=response, status=200)

            result = await client.call_ubus("session", "service", "method", {})
            assert result == {"test": "data"}


@pytest.mark.asyncio
async def test_close_session():
    """Test closing the session."""
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
    async with UbusClient("192.168.1.1", "hass", "password", use_https=True) as client:
        # Verify HTTPS URL is used
        assert client.base_url == "https://192.168.1.1/ubus"
        assert client.use_https is True
        assert client.verify_ssl is False  # Default


@pytest.mark.asyncio
async def test_http_client_url():
    """Test that HTTP client uses correct URL (default)."""
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

    async with UbusClient(
        "192.168.1.1", "hass", "password", use_https=True, verify_ssl=False
    ) as client:
        with aioresponses() as m:
            m.post(
                "https://192.168.1.1/ubus",
                payload=auth_response,
                status=200,
            )

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

    async with UbusClient("192.168.1.1", "hass", "password", use_https=True) as client:
        with aioresponses() as m:
            m.post("https://192.168.1.1/ubus", payload=response, status=200)

            result = await client.call_ubus("session", "service", "method", {})
            assert result == {"secure": "data"}
