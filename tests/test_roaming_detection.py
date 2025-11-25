"""Tests for roaming detection functionality."""

from datetime import datetime, timedelta
from unittest.mock import Mock

from custom_components.wrtmanager.const import (
    ATTR_MAC,
    ATTR_PRIMARY_AP,
    ATTR_ROAMING_COUNT,
    ATTR_ROUTER,
    ROAMING_DETECTION_THRESHOLD,
)
from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


def check_roaming_event(coordinator, mac, current_router):
    """Helper function to check if a roaming event should be detected.

    This implements the same logic as the coordinator's _update_roaming_detection
    method for testing purposes.

    Returns:
        tuple: (roaming_count, time_diff) - The updated roaming count and elapsed time
    """
    previous_primary = coordinator._device_history.get(mac, {}).get(ATTR_PRIMARY_AP)
    roaming_count = coordinator._device_history.get(mac, {}).get(ATTR_ROAMING_COUNT, 0)

    time_diff = (
        datetime.now() - coordinator._device_history.get(mac, {}).get("last_change", datetime.min)
    ).total_seconds()

    if (
        previous_primary
        and previous_primary != current_router
        and time_diff >= ROAMING_DETECTION_THRESHOLD
    ):
        roaming_count += 1

    return roaming_count, time_diff


def test_roaming_detection_threshold_exceeded():
    """Test that roaming is detected when threshold is exceeded."""
    # Create a mock coordinator
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator._device_history = {}

    # Simulate device history with a change that happened more than threshold ago
    mac = "AA:BB:CC:DD:EE:FF"
    old_time = datetime.now() - timedelta(seconds=ROAMING_DETECTION_THRESHOLD + 5)

    coordinator._device_history[mac] = {
        ATTR_PRIMARY_AP: "192.168.1.1",
        ATTR_ROAMING_COUNT: 0,
        "last_change": old_time,
    }

    # Simulate device data
    current_router = "192.168.1.2"  # Different router

    # Call the roaming detection helper
    roaming_count, time_diff = check_roaming_event(coordinator, mac, current_router)

    # Assert roaming was detected
    assert roaming_count == 1
    assert time_diff >= ROAMING_DETECTION_THRESHOLD


def test_roaming_detection_threshold_not_exceeded():
    """Test that roaming is NOT detected when threshold is not exceeded."""
    # Create a mock coordinator
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator._device_history = {}

    # Simulate device history with a recent change (less than threshold)
    mac = "AA:BB:CC:DD:EE:FF"
    recent_time = datetime.now() - timedelta(seconds=ROAMING_DETECTION_THRESHOLD - 5)

    coordinator._device_history[mac] = {
        ATTR_PRIMARY_AP: "192.168.1.1",
        ATTR_ROAMING_COUNT: 0,
        "last_change": recent_time,
    }

    # Simulate device data
    current_router = "192.168.1.2"  # Different router

    # Call the roaming detection helper
    roaming_count, time_diff = check_roaming_event(coordinator, mac, current_router)

    # Assert roaming was NOT detected
    assert roaming_count == 0
    assert time_diff < ROAMING_DETECTION_THRESHOLD


def test_roaming_detection_with_time_over_60_seconds():
    """Test that roaming is detected when time difference is over 60 seconds.

    This is the bug scenario from issue #14. Using .seconds instead of
    .total_seconds() would fail this test because .seconds only returns
    the seconds component (0-59), not the total elapsed time.
    """
    # Create a mock coordinator
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator._device_history = {}

    # Simulate device history with a change that happened 65 seconds ago
    # This is > 60 seconds to test the bug scenario
    mac = "AA:BB:CC:DD:EE:FF"
    old_time = datetime.now() - timedelta(seconds=65)

    coordinator._device_history[mac] = {
        ATTR_PRIMARY_AP: "192.168.1.1",
        ATTR_ROAMING_COUNT: 0,
        "last_change": old_time,
    }

    # Simulate device data
    current_router = "192.168.1.2"  # Different router

    # Call the roaming detection helper
    roaming_count, time_diff = check_roaming_event(coordinator, mac, current_router)

    # Assert roaming was detected
    # With the bug (.seconds instead of .total_seconds()), this would fail
    # because .seconds would return 5 (65 % 60), which is < threshold (10)
    assert roaming_count == 1
    assert time_diff >= 60  # Verify time is actually over 60 seconds
    assert time_diff >= ROAMING_DETECTION_THRESHOLD


def test_roaming_detection_with_time_over_multiple_minutes():
    """Test that roaming is detected when time difference spans multiple minutes."""
    # Create a mock coordinator
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator._device_history = {}

    # Simulate device history with a change that happened 5 minutes ago
    mac = "AA:BB:CC:DD:EE:FF"
    old_time = datetime.now() - timedelta(minutes=5)

    coordinator._device_history[mac] = {
        ATTR_PRIMARY_AP: "192.168.1.1",
        ATTR_ROAMING_COUNT: 2,  # Already roamed twice
        "last_change": old_time,
    }

    # Simulate device data
    current_router = "192.168.1.2"  # Different router

    # Call the roaming detection helper
    roaming_count, time_diff = check_roaming_event(coordinator, mac, current_router)

    # Assert roaming was detected and count incremented
    assert roaming_count == 3
    assert time_diff >= 300  # 5 minutes = 300 seconds


def test_roaming_not_detected_same_router():
    """Test that roaming is NOT detected when device stays on same router."""
    # Create a mock coordinator
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator._device_history = {}

    # Simulate device history
    mac = "AA:BB:CC:DD:EE:FF"
    old_time = datetime.now() - timedelta(seconds=ROAMING_DETECTION_THRESHOLD + 5)

    coordinator._device_history[mac] = {
        ATTR_PRIMARY_AP: "192.168.1.1",
        ATTR_ROAMING_COUNT: 0,
        "last_change": old_time,
    }

    # Simulate device data - SAME router
    current_router = "192.168.1.1"  # Same router

    # Call the roaming detection helper
    roaming_count, time_diff = check_roaming_event(coordinator, mac, current_router)

    # Assert roaming was NOT detected (same router)
    assert roaming_count == 0


def test_roaming_not_detected_no_previous_history():
    """Test that roaming is NOT detected when there's no previous history."""
    # Create a mock coordinator
    coordinator = Mock(spec=WrtManagerCoordinator)
    coordinator._device_history = {}  # No history

    # Simulate device data
    mac = "AA:BB:CC:DD:EE:FF"
    current_router = "192.168.1.1"

    # Call the roaming detection helper
    roaming_count, time_diff = check_roaming_event(coordinator, mac, current_router)

    # Assert roaming was NOT detected (no previous history)
    assert roaming_count == 0
    previous_primary = coordinator._device_history.get(mac, {}).get(ATTR_PRIMARY_AP)
    assert previous_primary is None
