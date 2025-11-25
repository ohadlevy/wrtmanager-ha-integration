"""Comprehensive tests for UbusClient coverage."""

# Import UbusClient directly from the file
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "wrtmanager"))

from ubus_client import UbusClient

# All tests now use individual mocking to avoid aiohttp threading issues


@pytest.mark.asyncio
async def test_get_wireless_devices_success():
    """Test getting wireless devices successfully."""
    response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": [0, {"devices": ["phy0-ap0", "phy1-ap0", "phy0-ap1"]}],
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            devices = await client.get_wireless_devices("test_session")
            assert devices == ["phy0-ap0", "phy1-ap0", "phy0-ap1"]


@pytest.mark.asyncio
async def test_get_wireless_devices_error():
    """Test getting wireless devices with error response."""
    response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": [1, {}],  # Error code 1
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            devices = await client.get_wireless_devices("test_session")
            assert devices is None


@pytest.mark.asyncio
async def test_get_device_associations_success():
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

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            associations = await client.get_device_associations("test_session", "phy0-ap0")
            assert len(associations) == 1
            assert associations[0]["mac"] == "CC:8C:BF:0A:B7:F4"
            assert associations[0]["signal"] == -69


@pytest.mark.asyncio
async def test_get_device_associations_empty():
    """Test getting device associations with no clients."""
    response = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": [0, {"results": []}],
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            associations = await client.get_device_associations("test_session", "phy0-ap0")
            assert associations == []


@pytest.mark.asyncio
async def test_get_dhcp_leases_success():
    """Test getting DHCP leases successfully via luci-rpc."""
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

    async def mock_make_request(self, request_data):
        return luci_response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            leases = await client.get_dhcp_leases("test_session")
            assert leases is not None
            assert "dhcp_leases" in leases
            assert len(leases["dhcp_leases"]) == 1


@pytest.mark.asyncio
async def test_get_dhcp_leases_not_available():
    """Test getting DHCP leases when not available (AP mode)."""
    response = {
        "jsonrpc": "2.0",
        "id": 4,
        "result": [1, {}],  # Error - normal for APs
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            leases = await client.get_dhcp_leases("test_session")
            assert leases is None


@pytest.mark.asyncio
async def test_get_system_info_success():
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

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            info = await client.get_system_info("test_session")
            assert info["hostname"] == "test-router"
            assert info["model"] == "OpenWrt Test Router"


@pytest.mark.asyncio
async def test_get_system_info_error():
    """Test getting system information with error."""
    response = {
        "jsonrpc": "2.0",
        "id": 5,
        "result": [1, {}],  # Error
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            info = await client.get_system_info("test_session")
            assert info is None


@pytest.mark.asyncio
async def test_http_error_handling():
    """Test handling of HTTP errors."""

    async def mock_make_request(self, request_data):
        return None  # Simulate HTTP error

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.call_ubus("session", "service", "method", {})
            assert result is None


@pytest.mark.asyncio
async def test_invalid_json_handling():
    """Test handling of invalid JSON response."""

    async def mock_make_request(self, request_data):
        return None  # Simulate invalid JSON

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.call_ubus("session", "service", "method", {})
            assert result is None
