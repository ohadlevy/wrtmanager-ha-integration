"""Comprehensive tests for UbusClient coverage."""

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
        # Force garbage collection to prevent lingering resources
        import gc

        gc.collect()


@pytest.mark.asyncio
async def test_get_wireless_devices_success(ubus_client):
    """Test getting wireless devices successfully."""
    response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": [0, {"devices": ["phy0-ap0", "phy1-ap0", "phy0-ap1"]}],
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=response, status=200)

        devices = await ubus_client.get_wireless_devices("test_session")
        assert devices == ["phy0-ap0", "phy1-ap0", "phy0-ap1"]


@pytest.mark.asyncio
async def test_get_wireless_devices_error(ubus_client):
    """Test getting wireless devices with error response."""
    response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": [1, {}],  # Error code 1
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=response, status=200)

        devices = await ubus_client.get_wireless_devices("test_session")
        assert devices is None


@pytest.mark.asyncio
async def test_get_device_associations_success(ubus_client):
    """Test getting device associations successfully."""

    response = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": [
            0,
            {
                "results": [
                    {
                        "mac": "CC:8C:BF:0A:B7:F4",
                        "signal": -69,
                        "rx": {"rate": 24000},
                        "tx": {"rate": 48000},
                    }
                ]
            },
        ],
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=response, status=200)

        associations = await ubus_client.get_device_associations("test_session", "phy0-ap0")
        assert len(associations) == 1
        assert associations[0]["mac"] == "CC:8C:BF:0A:B7:F4"
        assert associations[0]["signal"] == -69


@pytest.mark.asyncio
async def test_get_device_associations_empty(ubus_client):
    """Test getting device associations with no clients."""

    response = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": [0, {"results": []}],
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=response, status=200)

        associations = await ubus_client.get_device_associations("test_session", "phy0-ap0")
        assert associations == []


@pytest.mark.asyncio
async def test_get_dhcp_leases_success(ubus_client):
    """Test getting DHCP leases successfully via luci-rpc."""

    # Mock successful luci-rpc response
    luci_response = {
        "jsonrpc": "2.0",
        "id": 4,
        "result": [
            0,
            {
                "dhcp_leases": [
                    {
                        "macaddr": "CC:8C:BF:0A:B7:F4",
                        "ipaddr": "192.168.1.100",
                        "hostname": "gree-ac",
                    }
                ]
            },
        ],
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=luci_response, status=200)

        leases = await ubus_client.get_dhcp_leases("test_session")
        assert leases is not None
        assert "dhcp_leases" in leases
        assert len(leases["dhcp_leases"]) == 1


@pytest.mark.asyncio
async def test_get_dhcp_leases_fallback_success(ubus_client):
    """Test getting DHCP leases successfully via fallback method."""

    # Mock luci-rpc access denied, then dhcp.ipv4leases success
    luci_denied_response = {
        "jsonrpc": "2.0",
        "id": 4,
        "error": {"code": -32002, "message": "Access denied"},
    }

    dhcp_response = {
        "jsonrpc": "2.0",
        "id": 5,
        "result": [
            0,
            {
                "device": {
                    "leases": [
                        {
                            "macaddr": "CC:8C:BF:0A:B7:F4",
                            "ipaddr": "192.168.1.100",
                            "hostname": "gree-ac",
                            "valid": 1234567890,
                        }
                    ]
                }
            },
        ],
    }

    with aioresponses() as m:
        # First call (luci-rpc) returns access denied
        m.post("http://192.168.1.1/ubus", payload=luci_denied_response, status=200)
        # Second call (dhcp.ipv4leases) returns success
        m.post("http://192.168.1.1/ubus", payload=dhcp_response, status=200)

        leases = await ubus_client.get_dhcp_leases("test_session")
        assert leases is not None
        assert "device" in leases
        assert len(leases["device"]["leases"]) == 1


@pytest.mark.asyncio
async def test_get_dhcp_leases_not_available(ubus_client):
    """Test getting DHCP leases when not available (AP mode)."""

    response = {
        "jsonrpc": "2.0",
        "id": 4,
        "result": [1, {}],  # Error - normal for APs
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=response, status=200)

        leases = await ubus_client.get_dhcp_leases("test_session")
        assert leases is None


@pytest.mark.asyncio
async def test_get_system_info_success(ubus_client):
    """Test getting system information successfully."""

    response = {
        "jsonrpc": "2.0",
        "id": 5,
        "result": [
            0,
            {
                "hostname": "test-router",
                "model": "OpenWrt Test Router",
                "release": {
                    "distribution": "OpenWrt",
                    "version": "23.05.0",
                },
                "uptime": 123456,
            },
        ],
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=response, status=200)

        info = await ubus_client.get_system_info("test_session")
        assert info["hostname"] == "test-router"
        assert info["model"] == "OpenWrt Test Router"


@pytest.mark.asyncio
async def test_get_system_info_error(ubus_client):
    """Test getting system information with error."""

    response = {
        "jsonrpc": "2.0",
        "id": 5,
        "result": [1, {}],  # Error
    }

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", payload=response, status=200)

        info = await ubus_client.get_system_info("test_session")
        assert info is None


@pytest.mark.asyncio
async def test_http_error_handling(ubus_client):
    """Test handling of HTTP errors."""

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", status=500)

        result = await ubus_client.call_ubus("session", "service", "method", {})
        assert result is None


@pytest.mark.asyncio
async def test_invalid_json_handling(ubus_client):
    """Test handling of invalid JSON response."""

    with aioresponses() as m:
        m.post("http://192.168.1.1/ubus", body="invalid json", status=200)

        result = await ubus_client.call_ubus("session", "service", "method", {})
        assert result is None
