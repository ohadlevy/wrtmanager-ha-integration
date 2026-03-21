"""Tests for WiFi client disconnect feature."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "wrtmanager"))

from ubus_client import UbusClient

# ─── UbusClient.disconnect_client tests ───


@pytest.mark.asyncio
async def test_disconnect_client_success():
    """Test successful client disconnect via hostapd del_client."""
    response = {
        "jsonrpc": "2.0",
        "id": 100,
        "result": [0, {}],
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.disconnect_client("test_session", "phy0-ap0", "AA:BB:CC:DD:EE:FF")
            assert result is True


@pytest.mark.asyncio
async def test_disconnect_client_success_no_data():
    """Test successful disconnect when router returns [0] (no data payload)."""
    response = {
        "jsonrpc": "2.0",
        "id": 100,
        "result": [0],  # Success with no data — real router behavior
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.disconnect_client("test_session", "phy0-ap0", "AA:BB:CC:DD:EE:FF")
            assert result is True


@pytest.mark.asyncio
async def test_disconnect_client_failure():
    """Test failed client disconnect (permission denied)."""
    response = {
        "jsonrpc": "2.0",
        "id": 100,
        "result": [6],
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.disconnect_client("test_session", "phy0-ap0", "AA:BB:CC:DD:EE:FF")
            assert result is False


@pytest.mark.asyncio
async def test_disconnect_client_uses_hostapd_interface():
    """Test that disconnect prepends hostapd. to the interface name."""
    captured_requests = []

    async def mock_make_request(self, request_data):
        captured_requests.append(request_data)
        return {"jsonrpc": "2.0", "id": 100, "result": [0, {}]}

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            await client.disconnect_client("test_session", "phy0-ap0", "AA:BB:CC:DD:EE:FF")

    assert len(captured_requests) == 1
    params = captured_requests[0]["params"]
    assert params[1] == "hostapd.phy0-ap0"
    assert params[2] == "del_client"
    assert params[3]["addr"] == "AA:BB:CC:DD:EE:FF"
    assert params[3]["deauth"] is True
    assert params[3]["reason"] == 5
    assert params[3]["ban_time"] == 60000


@pytest.mark.asyncio
async def test_disconnect_client_custom_ban_time():
    """Test disconnect with custom ban_time."""
    captured_requests = []

    async def mock_make_request(self, request_data):
        captured_requests.append(request_data)
        return {"jsonrpc": "2.0", "id": 100, "result": [0, {}]}

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            await client.disconnect_client(
                "test_session", "phy0-ap0", "AA:BB:CC:DD:EE:FF", ban_time=120000
            )

    assert captured_requests[0]["params"][3]["ban_time"] == 120000


@pytest.mark.asyncio
async def test_disconnect_client_object_not_found():
    """Test disconnect when hostapd interface doesn't exist."""
    response = {
        "jsonrpc": "2.0",
        "id": 100,
        "error": {"code": -32000, "message": "Object not found"},
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.disconnect_client(
                "test_session", "nonexistent", "AA:BB:CC:DD:EE:FF"
            )
            assert result is False


@pytest.mark.asyncio
async def test_call_ubus_single_element_success():
    """Test that call_ubus treats [0] as success, not an error."""
    response = {
        "jsonrpc": "2.0",
        "id": 100,
        "result": [0],
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.call_ubus("test_session", "hostapd.phy0-ap0", "del_client", {})
            assert result == {}  # Should return empty dict, not None


@pytest.mark.asyncio
async def test_call_ubus_access_denied():
    """Test that call_ubus handles -32002 Access denied response."""
    response = {
        "jsonrpc": "2.0",
        "id": 100,
        "error": {"code": -32002, "message": "Access denied"},
    }

    async def mock_make_request(self, request_data):
        return response

    with patch.object(UbusClient, "_make_request", mock_make_request):
        async with UbusClient("192.168.1.1", "hass", "password") as client:
            result = await client.call_ubus("test_session", "hostapd.phy0-ap0", "del_client", {})
            assert result is None


# ─── Coordinator disconnect_client tests ───


@pytest.mark.asyncio
async def test_coordinator_disconnect_success():
    """Test coordinator disconnect_client delegates to the right UbusClient."""
    from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

    mock_client = AsyncMock()
    mock_client.disconnect_client = AsyncMock(return_value=True)
    mock_client.close = AsyncMock()

    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator.routers = {"192.168.1.1": mock_client}
    coordinator.sessions = {"192.168.1.1": "test_session"}
    coordinator.async_request_refresh = AsyncMock()

    result = await WrtManagerCoordinator.disconnect_client(
        coordinator, "192.168.1.1", "phy0-ap0", "AA:BB:CC:DD:EE:FF"
    )

    assert result is True
    mock_client.disconnect_client.assert_called_once_with(
        "test_session", "phy0-ap0", "AA:BB:CC:DD:EE:FF"
    )
    coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_disconnect_unknown_router():
    """Test coordinator raises ValueError for unknown router."""
    from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator.routers = {}
    coordinator.sessions = {}

    with pytest.raises(ValueError, match="not configured"):
        await WrtManagerCoordinator.disconnect_client(
            coordinator, "unknown.host", "phy0-ap0", "AA:BB:CC:DD:EE:FF"
        )


@pytest.mark.asyncio
async def test_coordinator_disconnect_not_authenticated():
    """Test coordinator raises ValueError when router not authenticated."""
    from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

    mock_client = AsyncMock()
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator.routers = {"192.168.1.1": mock_client}
    coordinator.sessions = {}

    with pytest.raises(ValueError, match="not authenticated"):
        await WrtManagerCoordinator.disconnect_client(
            coordinator, "192.168.1.1", "phy0-ap0", "AA:BB:CC:DD:EE:FF"
        )


@pytest.mark.asyncio
async def test_coordinator_disconnect_failure_no_refresh():
    """Test coordinator does not refresh when disconnect fails."""
    from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

    mock_client = AsyncMock()
    mock_client.disconnect_client = AsyncMock(return_value=False)

    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator.routers = {"192.168.1.1": mock_client}
    coordinator.sessions = {"192.168.1.1": "test_session"}
    coordinator.async_request_refresh = AsyncMock()

    result = await WrtManagerCoordinator.disconnect_client(
        coordinator, "192.168.1.1", "phy0-ap0", "AA:BB:CC:DD:EE:FF"
    )

    assert result is False
    coordinator.async_request_refresh.assert_not_called()


# ─── Button entity logic tests ───


def test_button_unique_id_format():
    """Test button unique ID includes router and MAC."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.data = {"devices": []}
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Main Router"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    assert button._attr_unique_id == "wrtmanager_192_168_1_1_aa_bb_cc_dd_ee_ff_disconnect"


def test_button_name_uses_router_name():
    """Test button name uses friendly router name from config."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.data = {"devices": []}
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Living Room AP"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    assert button.name == "Disconnect from Living Room AP"


def test_button_available_when_connected():
    """Test button is available when device is connected on this AP."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.last_update_success = True
    coordinator.data = {
        "devices": [
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "router": "192.168.1.1",
                "interface": "phy0-ap0",
                "connected": True,
            }
        ]
    }
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Router"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    assert button.available is True


def test_button_unavailable_when_disconnected():
    """Test button is unavailable when device is not on this AP."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.last_update_success = True
    coordinator.data = {"devices": []}
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Router"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    assert button.available is False


def test_button_unavailable_when_coordinator_failed():
    """Test button is unavailable when coordinator update failed."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.last_update_success = False
    coordinator.data = {
        "devices": [
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "router": "192.168.1.1",
                "interface": "phy0-ap0",
                "connected": True,
            }
        ]
    }
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Router"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    assert button.available is False


def test_button_device_info_groups_with_presence_sensor():
    """Test button device_info uses same identifiers as presence sensor."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.data = {"devices": []}
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Router"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    device_info = button.device_info
    assert ("wrtmanager", "AA:BB:CC:DD:EE:FF") in device_info["identifiers"]


def test_button_extra_attributes():
    """Test button exposes useful extra state attributes."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.data = {
        "devices": [
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "router": "192.168.1.1",
                "interface": "phy0-ap0",
                "connected": True,
                "hostname": "my-phone",
            }
        ]
    }
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Router"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    attrs = button.extra_state_attributes
    assert attrs["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert attrs["router"] == "192.168.1.1"
    assert attrs["interface"] == "phy0-ap0"
    assert attrs["hostname"] == "my-phone"


def test_button_router_name_fallback():
    """Test button falls back to host when router name not in config."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.data = {"devices": []}
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "10.0.0.1", "name": "Other Router"}]}

    button = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )

    assert button.name == "Disconnect from 192.168.1.1"


def test_button_multiple_devices_per_router():
    """Test that buttons for different devices on same router have unique IDs."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.data = {"devices": []}
    config_entry = Mock()
    config_entry.data = {"routers": [{"host": "192.168.1.1", "name": "Router"}]}

    button1 = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:01", "192.168.1.1", "phy0-ap0", config_entry
    )
    button2 = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:02", "192.168.1.1", "phy0-ap0", config_entry
    )

    assert button1._attr_unique_id != button2._attr_unique_id


def test_button_same_device_different_routers():
    """Test that buttons for same device on different routers have unique IDs."""
    from custom_components.wrtmanager.button import WrtDisconnectButton

    coordinator = Mock()
    coordinator.data = {"devices": []}
    config_entry = Mock()
    config_entry.data = {
        "routers": [
            {"host": "192.168.1.1", "name": "Router 1"},
            {"host": "192.168.1.2", "name": "Router 2"},
        ]
    }

    button1 = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.1", "phy0-ap0", config_entry
    )
    button2 = WrtDisconnectButton(
        coordinator, "AA:BB:CC:DD:EE:FF", "192.168.1.2", "phy0-ap0", config_entry
    )

    assert button1._attr_unique_id != button2._attr_unique_id
    # Both should group under the same device
    assert button1.device_info["identifiers"] == button2.device_info["identifiers"]
