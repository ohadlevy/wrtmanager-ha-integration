"""Tests for DHCP polling optimization feature."""

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.ubus_client import UbusClientError


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    mock = MagicMock()
    mock.loop = MagicMock()  # Use regular MagicMock instead of AsyncMock to avoid threading issues
    return mock


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    mock = MagicMock()
    mock.data = {
        "routers": [{"host": "192.168.1.1", "username": "test_user", "password": "test_pass"}]
    }
    mock.options = {}
    return mock


class MockCoordinator(WrtManagerCoordinator):
    """Test coordinator with properly mocked dependencies."""

    def __init__(self, hass, config_entry):
        """Initialize test coordinator with proper dependency injection."""
        # Use dependency injection by patching dependencies and frame usage
        # before calling super().__init__
        with (
            patch("custom_components.wrtmanager.coordinator.UbusClient") as mock_ubus,
            patch("custom_components.wrtmanager.coordinator.DeviceManager") as mock_device_manager,
            patch("homeassistant.helpers.frame.report_usage"),  # Disable frame usage reporting
        ):
            # Configure mocks to return usable objects
            mock_ubus.return_value = MagicMock()
            mock_device_manager.return_value = MagicMock()

            # Call parent initialization with mocked dependencies
            super().__init__(
                hass,
                logging.getLogger(__name__),
                "test_coordinator",
                timedelta(seconds=30),
                config_entry,
            )

        # Override routers with test mocks for better test control
        self.routers = {
            "192.168.1.1": MagicMock(),
            "192.168.1.2": MagicMock(),
            "192.168.1.3": MagicMock(),
        }
        self.sessions = {}
        self.device_manager = MagicMock()
        self._device_history = {}

    def _parse_dhcp_data(self, dhcp_leases, static_hosts):
        """Mock DHCP parsing for tests."""
        dhcp_devices = {}
        if dhcp_leases and "device" in dhcp_leases:
            for lease in dhcp_leases["device"].get("leases", []):
                mac = lease.get("macaddr", "").upper()
                if mac:
                    dhcp_devices[mac] = {
                        "ip_address": lease.get("ipaddr"),
                        "hostname": lease.get("hostname", ""),
                        "data_source": "dynamic_dhcp",
                    }
        if static_hosts and "values" in static_hosts:
            for section_data in static_hosts["values"].values():
                if section_data.get(".type") == "host":
                    mac = section_data.get("mac", "").upper()
                    if mac:
                        dhcp_devices[mac] = {
                            "ip_address": section_data.get("ip"),
                            "hostname": section_data.get("name", ""),
                            "data_source": "static_dhcp",
                        }
        return dhcp_devices

    def _correlate_device_data(self, wifi_devices, dhcp_data):
        """Mock device correlation for tests."""
        return wifi_devices

    def _update_roaming_detection(self, devices):
        """Mock roaming detection for tests."""
        pass


@pytest.fixture
def coordinator(mock_hass, mock_config_entry):
    """Create a coordinator instance."""
    return MockCoordinator(mock_hass, mock_config_entry)


class TestDHCPPollingOptimization:
    """Test DHCP polling optimization logic."""

    def test_initial_state(self, coordinator):
        """Test that coordinator starts with empty DHCP tracking sets."""
        assert len(coordinator._dhcp_routers) == 0
        assert len(coordinator._tried_dhcp) == 0

    @pytest.mark.asyncio
    async def test_first_dhcp_discovery(self, coordinator):
        """Test initial DHCP server discovery."""
        # Mock successful authentication for all routers
        coordinator.sessions = {
            "192.168.1.1": "session1",
            "192.168.1.2": "session2",
            "192.168.1.3": "session3",
        }

        # Mock DHCP responses - only first router has DHCP
        dhcp_responses = {
            "192.168.1.1": (
                {
                    "device": {
                        "leases": [{"macaddr": "aa:bb:cc:dd:ee:ff", "ipaddr": "192.168.1.100"}]
                    }
                },
                {},
            ),
            "192.168.1.2": (None, None),
            "192.168.1.3": (None, None),
        }

        # Mock wireless and system calls
        for host, client in coordinator.routers.items():
            client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
            client.get_device_associations = AsyncMock(return_value=[])
            client.get_system_info = AsyncMock(return_value={})
            client.get_system_board = AsyncMock(return_value={})
            client.get_network_interfaces = AsyncMock(return_value={})
            client.get_wireless_status = AsyncMock(return_value={})

            # Mock DHCP calls based on expected responses
            dhcp_leases, static_hosts = dhcp_responses[host]
            client.get_dhcp_leases = AsyncMock(return_value=dhcp_leases)
            client.get_static_dhcp_hosts = AsyncMock(return_value=static_hosts)

        # Call _collect_router_data for each router
        for host, session_id in coordinator.sessions.items():
            await coordinator._collect_router_data(host, session_id)

        # Verify only the first router is marked as DHCP server
        assert "192.168.1.1" in coordinator._dhcp_routers
        assert "192.168.1.2" in coordinator._tried_dhcp
        assert "192.168.1.3" in coordinator._tried_dhcp

        # Verify non-DHCP routers are not in DHCP servers set
        assert "192.168.1.2" not in coordinator._dhcp_routers
        assert "192.168.1.3" not in coordinator._dhcp_routers

    @pytest.mark.asyncio
    async def test_skip_dhcp_query_for_known_non_dhcp_routers(self, coordinator):
        """Test that known non-DHCP routers are skipped."""
        # Pre-populate tried_dhcp set
        coordinator._tried_dhcp.add("192.168.1.2")
        coordinator._tried_dhcp.add("192.168.1.3")
        coordinator.sessions = {"192.168.1.2": "session2"}

        # Mock client
        client = coordinator.routers["192.168.1.2"]
        client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
        client.get_device_associations = AsyncMock(return_value=[])
        client.get_system_info = AsyncMock(return_value={})
        client.get_system_board = AsyncMock(return_value={})
        client.get_network_interfaces = AsyncMock(return_value={})
        client.get_wireless_status = AsyncMock(return_value={})
        client.get_dhcp_leases = AsyncMock(return_value=None)
        client.get_static_dhcp_hosts = AsyncMock(return_value=None)

        # Call _collect_router_data
        await coordinator._collect_router_data("192.168.1.2", "session2")

        # Verify DHCP methods were NOT called (router was skipped)
        client.get_dhcp_leases.assert_not_called()
        client.get_static_dhcp_hosts.assert_not_called()

    @pytest.mark.asyncio
    async def test_dhcp_server_failure_recovery(self, coordinator):
        """Test recovery when known DHCP server stops providing data."""
        # Pre-mark router as DHCP server
        coordinator._dhcp_routers.add("192.168.1.1")
        coordinator.sessions = {"192.168.1.1": "session1"}

        # Mock client - now returns no DHCP data
        client = coordinator.routers["192.168.1.1"]
        client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
        client.get_device_associations = AsyncMock(return_value=[])
        client.get_system_info = AsyncMock(return_value={})
        client.get_system_board = AsyncMock(return_value={})
        client.get_network_interfaces = AsyncMock(return_value={})
        client.get_wireless_status = AsyncMock(return_value={})
        client.get_dhcp_leases = AsyncMock(return_value=None)
        client.get_static_dhcp_hosts = AsyncMock(return_value=None)

        # Call _collect_router_data
        await coordinator._collect_router_data("192.168.1.1", "session1")

        # Verify router was removed from DHCP servers and added to tried set
        assert "192.168.1.1" not in coordinator._dhcp_routers
        assert "192.168.1.1" in coordinator._tried_dhcp

    @pytest.mark.asyncio
    async def test_fallback_logic_in_async_update(self, coordinator):
        """Test fallback logic when no DHCP data is collected."""
        # Pre-mark router as DHCP server but it will fail
        coordinator._dhcp_routers.add("192.168.1.1")
        coordinator.sessions = {
            "192.168.1.1": "session1",
            "192.168.1.2": "session2",
            "192.168.1.3": "session3",
        }

        # Mock authentication
        coordinator._authenticate_router = AsyncMock(
            side_effect=lambda host, client: f"session_{host.split('.')[-1]}"
        )

        # Mock _collect_router_data to simulate first router failure and second router success
        async def mock_collect_data(host, session_id):
            if host == "192.168.1.1":
                # DHCP server failed - return no DHCP data
                return [], {}, {"uptime": 12345}, {}
            elif host == "192.168.1.2":
                # This will be tested in fallback
                return [], {}, {"uptime": 12345}, {}
            else:
                return [], {}, {"uptime": 12345}, {}

        coordinator._collect_router_data = AsyncMock(side_effect=mock_collect_data)

        # Mock fallback DHCP discovery
        with patch.object(coordinator, "_parse_dhcp_data") as mock_parse:
            mock_parse.return_value = {
                "AA:BB:CC:DD:EE:FF": {"ip_address": "192.168.1.100", "hostname": "test"}
            }

            # Mock the fallback DHCP calls
            for host, client in coordinator.routers.items():
                if host == "192.168.1.2":
                    # This router will provide DHCP data in fallback
                    client.get_dhcp_leases = AsyncMock(
                        return_value={
                            "device": {
                                "leases": [
                                    {"macaddr": "aa:bb:cc:dd:ee:ff", "ipaddr": "192.168.1.100"}
                                ]
                            }
                        }
                    )
                    client.get_static_dhcp_hosts = AsyncMock(return_value=None)
                else:
                    client.get_dhcp_leases = AsyncMock(return_value=None)
                    client.get_static_dhcp_hosts = AsyncMock(return_value=None)

            # Call the main update method
            await coordinator._async_update_data()

            # Verify fallback was triggered and found DHCP data
            assert "192.168.1.2" in coordinator._dhcp_routers
            mock_parse.assert_called()

    @pytest.mark.asyncio
    async def test_only_query_dhcp_from_known_servers(self, coordinator):
        """Test that only known DHCP servers are queried after initial discovery."""
        # Pre-populate with known DHCP server
        coordinator._dhcp_routers.add("192.168.1.1")
        coordinator._tried_dhcp.add("192.168.1.2")
        coordinator._tried_dhcp.add("192.168.1.3")

        coordinator.sessions = {
            "192.168.1.1": "session1",
            "192.168.1.2": "session2",
            "192.168.1.3": "session3",
        }

        # Mock all clients
        for host, client in coordinator.routers.items():
            client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
            client.get_device_associations = AsyncMock(return_value=[])
            client.get_system_info = AsyncMock(return_value={})
            client.get_system_board = AsyncMock(return_value={})
            client.get_network_interfaces = AsyncMock(return_value={})
            client.get_wireless_status = AsyncMock(return_value={})

            if host == "192.168.1.1":
                # Known DHCP server - should be queried
                client.get_dhcp_leases = AsyncMock(
                    return_value={"device": {"leases": [{"macaddr": "aa:bb:cc:dd:ee:ff"}]}}
                )
                client.get_static_dhcp_hosts = AsyncMock(return_value=None)
            else:
                # Non-DHCP routers - should NOT be queried
                client.get_dhcp_leases = AsyncMock(return_value=None)
                client.get_static_dhcp_hosts = AsyncMock(return_value=None)

        # Collect data from all routers
        for host, session_id in coordinator.sessions.items():
            await coordinator._collect_router_data(host, session_id)

        # Verify only DHCP server was queried
        coordinator.routers["192.168.1.1"].get_dhcp_leases.assert_called()
        coordinator.routers["192.168.1.2"].get_dhcp_leases.assert_not_called()
        coordinator.routers["192.168.1.3"].get_dhcp_leases.assert_not_called()

    @pytest.mark.asyncio
    async def test_static_dhcp_hosts_detection(self, coordinator):
        """Test detection of DHCP servers that only provide static hosts."""
        coordinator.sessions = {"192.168.1.1": "session1"}

        # Mock client to return only static hosts
        client = coordinator.routers["192.168.1.1"]
        client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
        client.get_device_associations = AsyncMock(return_value=[])
        client.get_system_info = AsyncMock(return_value={})
        client.get_system_board = AsyncMock(return_value={})
        client.get_network_interfaces = AsyncMock(return_value={})
        client.get_wireless_status = AsyncMock(return_value={})
        client.get_dhcp_leases = AsyncMock(return_value=None)
        client.get_static_dhcp_hosts = AsyncMock(
            return_value={
                "values": {
                    "cfg001": {
                        ".type": "host",
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "ip": "192.168.1.50",
                        "name": "static-device",
                    }
                }
            }
        )

        # Call _collect_router_data
        await coordinator._collect_router_data("192.168.1.1", "session1")

        # Verify router was marked as DHCP server (even with only static hosts)
        assert "192.168.1.1" in coordinator._dhcp_routers
        assert "192.168.1.1" not in coordinator._tried_dhcp

    @pytest.mark.asyncio
    async def test_exception_during_dhcp_query(self, coordinator):
        """Test handling of exceptions during DHCP queries."""
        coordinator.sessions = {"192.168.1.1": "session1"}

        # Mock client to raise exception during DHCP query
        client = coordinator.routers["192.168.1.1"]
        client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
        client.get_device_associations = AsyncMock(return_value=[])
        client.get_system_info = AsyncMock(return_value={})
        client.get_system_board = AsyncMock(return_value={})
        client.get_network_interfaces = AsyncMock(return_value={})
        client.get_wireless_status = AsyncMock(return_value={})
        client.get_dhcp_leases = AsyncMock(side_effect=UbusClientError("DHCP query failed"))
        client.get_static_dhcp_hosts = AsyncMock(return_value=None)

        # Call _collect_router_data and expect UpdateFailed
        with pytest.raises(UpdateFailed):
            await coordinator._collect_router_data("192.168.1.1", "session1")

    def test_dhcp_router_tracking_persistence(self, coordinator):
        """Test that DHCP router tracking persists across updates."""
        # Simulate successful DHCP discovery
        coordinator._dhcp_routers.add("192.168.1.1")
        coordinator._tried_dhcp.add("192.168.1.2")
        coordinator._tried_dhcp.add("192.168.1.3")

        # Verify state is maintained
        assert len(coordinator._dhcp_routers) == 1
        assert len(coordinator._tried_dhcp) == 2
        assert "192.168.1.1" in coordinator._dhcp_routers
        assert "192.168.1.2" in coordinator._tried_dhcp

    @pytest.mark.asyncio
    async def test_multiple_dhcp_servers_support(self, coordinator):
        """Test support for multiple DHCP servers."""
        coordinator.sessions = {
            "192.168.1.1": "session1",
            "192.168.1.2": "session2",
        }

        # Mock both routers to provide DHCP data
        for host, client in coordinator.routers.items():
            client.get_wireless_devices = AsyncMock(return_value=["wlan0"])
            client.get_device_associations = AsyncMock(return_value=[])
            client.get_system_info = AsyncMock(return_value={})
            client.get_system_board = AsyncMock(return_value={})
            client.get_network_interfaces = AsyncMock(return_value={})
            client.get_wireless_status = AsyncMock(return_value={})
            client.get_dhcp_leases = AsyncMock(
                return_value={
                    "device": {
                        "leases": [
                            {
                                "macaddr": f"aa:bb:cc:dd:ee:{host.split('.')[-1]}",
                                "ipaddr": f"192.168.1.{100 + int(host.split('.')[-1])}",
                            }
                        ]
                    }
                }
            )
            client.get_static_dhcp_hosts = AsyncMock(return_value=None)

        # Collect data from both routers
        for host, session_id in coordinator.sessions.items():
            await coordinator._collect_router_data(host, session_id)

        # Verify both routers are marked as DHCP servers
        assert "192.168.1.1" in coordinator._dhcp_routers
        assert "192.168.1.2" in coordinator._dhcp_routers
        assert len(coordinator._dhcp_routers) == 2

    @pytest.mark.asyncio
    async def test_fallback_exception_handling(self, coordinator):
        """Test proper exception handling during fallback DHCP queries."""
        coordinator._dhcp_routers.add("192.168.1.1")
        coordinator.sessions = {
            "192.168.1.1": "session1",
            "192.168.1.2": "session2",
        }

        # Mock authentication and collection to simulate no DHCP data from known server
        coordinator._authenticate_router = AsyncMock(
            side_effect=lambda host, client: f"session_{host.split('.')[-1]}"
        )
        coordinator._collect_router_data = AsyncMock(return_value=([], {}, {"uptime": 12345}, {}))

        # Mock fallback client to raise exception
        client = coordinator.routers["192.168.1.2"]
        client.get_dhcp_leases = AsyncMock(side_effect=UbusClientError("Connection failed"))
        client.get_static_dhcp_hosts = AsyncMock(return_value=None)

        # Call the main update method
        result = await coordinator._async_update_data()

        # Verify fallback router was marked as tried despite exception
        assert "192.168.1.2" in coordinator._tried_dhcp

        # Verify update completed successfully despite fallback failure
        assert "devices" in result
        assert "system_info" in result
