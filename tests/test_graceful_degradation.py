"""Test graceful degradation when routers fail."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator
from custom_components.wrtmanager.ubus_client import (
    UbusAuthenticationError,
    UbusClient,
    UbusConnectionError,
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
        self.config_entry = MagicMock()
        self.config_entry.options = {}

        # Initialize graceful degradation tracking
        self._failed_routers = {}
        self._consecutive_failures = {}
        self._extended_failure_threshold = timedelta(minutes=30)
        self._max_consecutive_failures = 5

        # Other required attributes
        self._dhcp_routers = set()
        self._tried_dhcp = set()
        self._vlan_pattern = None

        # Set minimal required attributes
        self.name = "test_coordinator"
        self.data = None
        self.last_update_success = True


@pytest.mark.asyncio
async def test_single_router_failure_continues_operation():
    """Test that integration continues when some routers fail."""
    coordinator = TestCoordinator()

    # Setup two routers
    coordinator.routers = {
        "192.168.1.1": AsyncMock(spec=UbusClient),
        "192.168.1.2": AsyncMock(spec=UbusClient),
    }

    # Router 1 fails authentication, Router 2 succeeds
    coordinator.routers["192.168.1.1"].authenticate.side_effect = UbusAuthenticationError(
        "Auth failed"
    )
    coordinator.routers["192.168.1.2"].authenticate.return_value = "session_123"

    # Mock data collection for successful router
    coordinator.routers["192.168.1.2"].get_wireless_devices.return_value = ["wlan0"]
    coordinator.routers["192.168.1.2"].get_device_associations.return_value = []
    coordinator.routers["192.168.1.2"].get_system_info.return_value = {"model": "test"}
    coordinator.routers["192.168.1.2"].get_system_board.return_value = {"board": "test"}
    coordinator.routers["192.168.1.2"].get_network_interfaces.return_value = {}
    coordinator.routers["192.168.1.2"].get_wireless_status.return_value = {}
    coordinator.routers["192.168.1.2"].get_dhcp_leases.return_value = {}
    coordinator.routers["192.168.1.2"].get_static_dhcp_hosts.return_value = {}

    with patch.object(coordinator, "_correlate_device_data", return_value=[]):
        with patch.object(coordinator, "_update_roaming_detection"):
            with patch.object(coordinator, "_extract_ssid_data", return_value={}):
                data = await coordinator._async_update_data()

    # Should continue with partial operation
    assert data is not None
    assert data["graceful_degradation"] is True
    assert "192.168.1.1" in data["failed_routers"]
    assert "192.168.1.2" in data["routers"]
    assert coordinator._failed_routers["192.168.1.1"]["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_all_routers_fail_but_not_extended():
    """Test graceful degradation when all routers fail but not for extended period."""
    coordinator = TestCoordinator()

    # Setup two routers
    coordinator.routers = {
        "192.168.1.1": AsyncMock(spec=UbusClient),
        "192.168.1.2": AsyncMock(spec=UbusClient),
    }

    # Both routers fail authentication
    coordinator.routers["192.168.1.1"].authenticate.side_effect = UbusAuthenticationError(
        "Auth failed"
    )
    coordinator.routers["192.168.1.2"].authenticate.side_effect = UbusConnectionError(
        "Connection failed"
    )

    data = await coordinator._async_update_data()

    # Should continue with graceful degradation (empty data)
    assert data is not None
    assert data["graceful_degradation"] is True
    assert len(data["failed_routers"]) == 2
    assert len(data["routers"]) == 0
    assert len(data["devices"]) == 0


@pytest.mark.asyncio
async def test_all_routers_extended_failure():
    """Test complete failure when all routers are in extended failure state."""
    coordinator = TestCoordinator()

    # Setup one router
    coordinator.routers = {"192.168.1.1": AsyncMock(spec=UbusClient)}

    # Set up extended failure (simulate 31 minutes ago)
    past_time = datetime.now() - timedelta(minutes=31)
    coordinator._failed_routers["192.168.1.1"] = {
        "first_failure": past_time,
        "last_failure": datetime.now(),
        "consecutive_failures": 10,
        "last_error": "Auth failed",
        "last_operation": "authentication",
        "is_extended_failure": True,
    }

    coordinator.routers["192.168.1.1"].authenticate.side_effect = UbusAuthenticationError(
        "Auth failed"
    )

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()

    assert "Failed to authenticate with any router" in str(exc_info.value)


def test_handle_router_failure_tracking():
    """Test router failure tracking functionality."""
    coordinator = TestCoordinator()

    # First failure
    error = UbusAuthenticationError("Auth failed")
    coordinator._handle_router_failure("192.168.1.1", error, "authentication")

    assert "192.168.1.1" in coordinator._failed_routers
    assert coordinator._consecutive_failures["192.168.1.1"] == 1
    assert coordinator._failed_routers["192.168.1.1"]["last_error"] == "Auth failed"
    assert coordinator._failed_routers["192.168.1.1"]["last_operation"] == "authentication"
    assert coordinator._failed_routers["192.168.1.1"]["is_extended_failure"] is False


def test_handle_router_success_clears_failure():
    """Test that router success clears failure tracking."""
    coordinator = TestCoordinator()

    # Set up failure state
    coordinator._failed_routers["192.168.1.1"] = {
        "first_failure": datetime.now() - timedelta(minutes=10),
        "last_failure": datetime.now(),
        "consecutive_failures": 3,
        "last_error": "Auth failed",
        "last_operation": "authentication",
        "is_extended_failure": False,
    }
    coordinator._consecutive_failures["192.168.1.1"] = 3

    # Handle success
    coordinator._handle_router_success("192.168.1.1")

    # Failure tracking should be cleared
    assert "192.168.1.1" not in coordinator._failed_routers
    assert "192.168.1.1" not in coordinator._consecutive_failures


def test_extended_failure_detection():
    """Test extended failure detection after threshold."""
    coordinator = TestCoordinator()

    # Set up failure that started 31 minutes ago
    past_time = datetime.now() - timedelta(minutes=31)
    coordinator._failed_routers["192.168.1.1"] = {
        "first_failure": past_time,
        "last_failure": datetime.now(),
        "consecutive_failures": 5,
        "last_error": "Auth failed",
        "last_operation": "authentication",
        "is_extended_failure": False,
    }

    # Trigger another failure to check extended failure detection
    error = UbusAuthenticationError("Auth failed")
    coordinator._handle_router_failure("192.168.1.1", error, "authentication")

    assert coordinator._failed_routers["192.168.1.1"]["is_extended_failure"] is True


def test_should_fail_completely_logic():
    """Test the logic for determining when to fail completely."""
    coordinator = TestCoordinator()
    coordinator.routers = {"192.168.1.1": MagicMock(), "192.168.1.2": MagicMock()}

    # No failures - should not fail
    assert coordinator._should_fail_completely() is False

    # One router failed but not extended
    coordinator._failed_routers["192.168.1.1"] = {
        "first_failure": datetime.now() - timedelta(minutes=5),
        "is_extended_failure": False,
    }
    assert coordinator._should_fail_completely() is False

    # All routers failed but not extended
    coordinator._failed_routers["192.168.1.2"] = {
        "first_failure": datetime.now() - timedelta(minutes=3),
        "is_extended_failure": False,
    }
    assert coordinator._should_fail_completely() is False

    # All routers in extended failure
    coordinator._failed_routers["192.168.1.1"]["is_extended_failure"] = True
    coordinator._failed_routers["192.168.1.2"]["is_extended_failure"] = True
    assert coordinator._should_fail_completely() is True


def test_get_router_status():
    """Test router status reporting for diagnostics."""
    coordinator = TestCoordinator()
    coordinator.routers = {"192.168.1.1": MagicMock(), "192.168.1.2": MagicMock()}
    coordinator.sessions = {"192.168.1.2": "session_123"}

    # Set up one failed router
    failure_time = datetime.now() - timedelta(minutes=10)
    coordinator._failed_routers["192.168.1.1"] = {
        "first_failure": failure_time,
        "last_failure": datetime.now(),
        "consecutive_failures": 3,
        "last_error": "Auth failed",
        "last_operation": "authentication",
        "is_extended_failure": False,
    }

    status = coordinator.get_router_status()

    assert len(status) == 2

    # Failed router status
    failed_status = status["192.168.1.1"]
    assert failed_status["status"] == "failed"
    assert failed_status["consecutive_failures"] == 3
    assert failed_status["last_error"] == "Auth failed"
    assert failed_status["is_extended_failure"] is False
    assert failed_status["failure_duration_minutes"] >= 10

    # Healthy router status
    healthy_status = status["192.168.1.2"]
    assert healthy_status["status"] == "healthy"
    assert healthy_status["is_authenticated"] is True
    assert healthy_status["session_id"] == "session_123"


@pytest.mark.asyncio
async def test_data_collection_failure_handling():
    """Test graceful degradation when data collection fails for some routers."""
    coordinator = TestCoordinator()

    # Setup two routers, both authenticate successfully
    coordinator.routers = {
        "192.168.1.1": AsyncMock(spec=UbusClient),
        "192.168.1.2": AsyncMock(spec=UbusClient),
    }
    coordinator.sessions = {"192.168.1.1": "session_1", "192.168.1.2": "session_2"}

    # Mock _collect_router_data to simulate failure on one router
    async def mock_collect_router_data(host, session_id):
        if host == "192.168.1.1":
            raise UbusConnectionError("Data collection failed")
        else:
            return [], {}, {"model": "test"}, {}

    with patch.object(coordinator, "_collect_router_data", side_effect=mock_collect_router_data):
        with patch.object(coordinator, "_correlate_device_data", return_value=[]):
            with patch.object(coordinator, "_update_roaming_detection"):
                with patch.object(coordinator, "_extract_ssid_data", return_value={}):
                    data = await coordinator._async_update_data()

    # Should continue with partial data
    assert data is not None
    assert "192.168.1.1" in coordinator._failed_routers
    assert coordinator._failed_routers["192.168.1.1"]["last_operation"] == "data_collection"


@pytest.mark.asyncio
async def test_consecutive_failure_escalation():
    """Test that consecutive failures escalate properly."""
    coordinator = TestCoordinator()

    error = UbusAuthenticationError("Auth failed")

    # First 3 failures should be warnings
    for i in range(3):
        coordinator._handle_router_failure("192.168.1.1", error, "authentication")
        assert coordinator._consecutive_failures["192.168.1.1"] == i + 1

    # 4th failure should escalate to error level
    coordinator._handle_router_failure("192.168.1.1", error, "authentication")
    assert coordinator._consecutive_failures["192.168.1.1"] == 4


def test_empty_routers_always_fails():
    """Test that coordinator fails if no routers are configured."""
    coordinator = TestCoordinator()
    coordinator.routers = {}  # No routers configured

    assert coordinator._should_fail_completely() is True


def test_partial_router_availability_continues():
    """Test that integration continues with partial router availability."""
    coordinator = TestCoordinator()
    coordinator.routers = {
        "192.168.1.1": MagicMock(),
        "192.168.1.2": MagicMock(),
        "192.168.1.3": MagicMock(),
    }

    # Two routers failed, one still working
    coordinator._failed_routers = {
        "192.168.1.1": {
            "first_failure": datetime.now() - timedelta(minutes=2),
            "is_extended_failure": False,
        },
        "192.168.1.2": {
            "first_failure": datetime.now() - timedelta(minutes=3),
            "is_extended_failure": False,
        },
    }

    # Should continue (not all routers failed)
    assert coordinator._should_fail_completely() is False

    # Even if all routers failed but not extended, should continue
    coordinator._failed_routers["192.168.1.3"] = {
        "first_failure": datetime.now() - timedelta(minutes=1),
        "is_extended_failure": False,
    }
    assert coordinator._should_fail_completely() is False

    # Only fail when ALL routers are in extended failure
    coordinator._failed_routers["192.168.1.1"]["is_extended_failure"] = True
    coordinator._failed_routers["192.168.1.2"]["is_extended_failure"] = True
    coordinator._failed_routers["192.168.1.3"]["is_extended_failure"] = True
    assert coordinator._should_fail_completely() is True
