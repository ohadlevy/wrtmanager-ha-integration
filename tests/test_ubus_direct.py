"""Direct tests for UbusClient without any HA dependencies."""

import asyncio
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


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow lingering timers for aiohttp tests.

    This is needed because aiohttp creates background threads/timers that
    are cleaned up asynchronously and may not finish before test teardown.
    See: https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/issues/153
    """
    return True


@pytest_asyncio.fixture
async def ubus_client():
    """Fixture that provides a UbusClient with automatic cleanup."""
    client = UbusClient("192.168.1.1", "hass", "password")
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def https_ubus_client():
    """Fixture that provides an HTTPS UbusClient with automatic cleanup."""
    client = UbusClient("192.168.1.1", "hass", "password", use_https=True, verify_ssl=False)
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def ubus_client_wrong_password():
    """Fixture that provides a UbusClient with wrong password for testing auth failures."""
    client = UbusClient("192.168.1.1", "hass", "wrong_password")
    try:
        yield client
    finally:
        await client.close()


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
    client = UbusClient("192.168.1.1", "hass", "password")

    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [0, {"test": "data"}],
    }

    try:
        with aioresponses() as m:
            m.post("http://192.168.1.1/ubus", payload=response, status=200)

            result = await client.call_ubus("session", "service", "method", {})
            assert result == {"test": "data"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_close_session():
    """Test closing the session."""
    client = UbusClient("192.168.1.1", "hass", "password")

    try:
        # Mock the session
        mock_session = AsyncMock()
        client._session = mock_session

        await client.close()

        # Verify close was called on the mock session
        mock_session.close.assert_called_once()
        assert client._session is None
    finally:
        # Ensure cleanup even if test fails
        if client._session:
            await client.close()


@pytest.mark.asyncio
async def test_https_client_url():
    """Test that HTTPS client uses correct URL."""
    client = UbusClient("192.168.1.1", "hass", "password", use_https=True)

    try:
        # Verify HTTPS URL is used
        assert client.base_url == "https://192.168.1.1/ubus"
        assert client.use_https is True
        assert client.verify_ssl is False  # Default
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_http_client_url():
    """Test that HTTP client uses correct URL (default)."""
    client = UbusClient("192.168.1.1", "hass", "password")

    try:
        # Verify HTTP URL is used by default
        assert client.base_url == "http://192.168.1.1/ubus"
        assert client.use_https is False
        assert client.verify_ssl is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_https_authentication_success():
    """Test successful authentication with HTTPS."""
    client = UbusClient("192.168.1.1", "hass", "password", use_https=True, verify_ssl=False)

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

    try:
        with aioresponses() as m:
            m.post(
                "https://192.168.1.1/ubus",
                payload=auth_response,
                status=200,
            )

            session_id = await client.authenticate()
            assert session_id == "test_https_session"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_https_call_ubus_success():
    """Test successful ubus call with HTTPS."""
    client = UbusClient("192.168.1.1", "hass", "password", use_https=True)

    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [0, {"secure": "data"}],
    }

    try:
        with aioresponses() as m:
            m.post("https://192.168.1.1/ubus", payload=response, status=200)

            result = await client.call_ubus("session", "service", "method", {})
            assert result == {"secure": "data"}
    finally:
        await client.close()
