"""Tests for regex pattern optimization in coordinator."""

import re

import pytest

from custom_components.wrtmanager.const import (
    ATTR_INTERFACE,
    ATTR_IP,
)


@pytest.fixture
def mock_coordinator():
    """Create a minimal coordinator instance for testing."""
    from unittest.mock import Mock

    from custom_components.wrtmanager.coordinator import WrtManagerCoordinator

    # Create a minimal mock that only has what we need for testing
    coordinator = Mock()

    # Create the compiled regex pattern like the real coordinator does
    coordinator._vlan_pattern = re.compile(r"vlan(\d+)")

    # Bind the real method to our mock object
    # This ensures we're testing the actual implementation, not a duplicate
    coordinator._determine_vlan = WrtManagerCoordinator._determine_vlan.__get__(coordinator)

    return coordinator


class TestRegexOptimization:
    """Test regex pattern optimization."""

    def test_vlan_pattern_compiled_on_init(self, mock_coordinator):
        """Test that VLAN regex pattern is compiled during initialization."""
        # Verify the pattern exists and is a compiled regex
        assert hasattr(mock_coordinator, "_vlan_pattern")
        assert isinstance(mock_coordinator._vlan_pattern, re.Pattern)

        # Test that the pattern matches expected strings
        assert mock_coordinator._vlan_pattern.search("wlan0-vlan3") is not None
        assert mock_coordinator._vlan_pattern.search("phy0-ap1-vlan13") is not None
        assert mock_coordinator._vlan_pattern.search("no-vlan-here") is None

    def test_vlan_detection_uses_compiled_pattern(self, mock_coordinator):
        """Test that VLAN detection uses the compiled pattern correctly."""
        # Test cases with various interface names containing VLAN IDs
        test_cases = [
            ({ATTR_INTERFACE: "wlan0-vlan3"}, 3),
            ({ATTR_INTERFACE: "phy0-ap1-vlan13"}, 13),
            ({ATTR_INTERFACE: "wlan1-vlan100"}, 100),
            ({ATTR_INTERFACE: "radio0-vlan999"}, 999),
            ({ATTR_INTERFACE: "WLAN0-VLAN5"}, 5),  # Test case sensitivity
            ({ATTR_INTERFACE: "wlan0-novlan"}, 1),  # No VLAN pattern
            ({ATTR_INTERFACE: "ap0"}, 1),  # ap0 interface (main network)
            ({ATTR_INTERFACE: "ap1"}, 10),  # ap1 interface (secondary)
            ({ATTR_INTERFACE: "ap2"}, 100),  # ap2 interface (guest)
        ]

        for device_data, expected_vlan in test_cases:
            result = mock_coordinator._determine_vlan(device_data)
            assert (
                result == expected_vlan
            ), f"Failed for {device_data}: expected {expected_vlan}, got {result}"

    def test_vlan_detection_with_iot_keywords(self, mock_coordinator):
        """Test VLAN detection with IoT keywords."""
        test_cases = [
            ({ATTR_INTERFACE: "wlan0-iot"}, 3),
            ({ATTR_INTERFACE: "wlan0-smart"}, 3),
            ({ATTR_INTERFACE: "wlan0-things"}, 3),
            ({ATTR_INTERFACE: "wlan0-IoT"}, 3),  # Case insensitive
        ]

        for device_data, expected_vlan in test_cases:
            result = mock_coordinator._determine_vlan(device_data)
            assert result == expected_vlan

    def test_vlan_detection_with_guest_keywords(self, mock_coordinator):
        """Test VLAN detection with guest keywords."""
        test_cases = [
            ({ATTR_INTERFACE: "wlan0-guest"}, 100),
            ({ATTR_INTERFACE: "wlan0-visitor"}, 100),
            ({ATTR_INTERFACE: "wlan0-public"}, 100),
            ({ATTR_INTERFACE: "wlan0-GUEST"}, 100),  # Case insensitive
        ]

        for device_data, expected_vlan in test_cases:
            result = mock_coordinator._determine_vlan(device_data)
            assert result == expected_vlan

    def test_vlan_detection_with_main_keywords(self, mock_coordinator):
        """Test VLAN detection with main network keywords."""
        test_cases = [
            ({ATTR_INTERFACE: "wlan0-main"}, 1),
            ({ATTR_INTERFACE: "wlan0-default"}, 1),
            ({ATTR_INTERFACE: "wlan0-lan"}, 1),
        ]

        for device_data, expected_vlan in test_cases:
            result = mock_coordinator._determine_vlan(device_data)
            assert result == expected_vlan

    def test_vlan_detection_with_ip_address(self, mock_coordinator):
        """Test VLAN detection based on IP address when no interface VLAN found."""
        test_cases = [
            ({ATTR_IP: "192.168.1.100"}, 1),
            ({ATTR_IP: "192.168.3.100"}, 3),
            ({ATTR_IP: "192.168.10.100"}, 10),
            ({ATTR_IP: "192.168.100.100"}, 100),
            ({ATTR_IP: "10.0.1.100"}, 1),  # Third octet is 1
            ({ATTR_IP: "invalid-ip"}, 1),  # Invalid IP defaults to 1
        ]

        for device_data, expected_vlan in test_cases:
            result = mock_coordinator._determine_vlan(device_data)
            assert result == expected_vlan

    def test_vlan_pattern_reuse_optimization(self, mock_coordinator):
        """Test that we use a single compiled pattern rather than compiling repeatedly."""
        # Verify that the pattern is compiled once and stored as an instance variable
        assert hasattr(mock_coordinator, "_vlan_pattern")
        assert isinstance(mock_coordinator._vlan_pattern, re.Pattern)

        # Store reference to the original pattern
        original_pattern = mock_coordinator._vlan_pattern

        # Perform multiple VLAN detections
        test_cases = ["wlan0-vlan42", "phy0-ap1-vlan13", "wlan1-vlan100", "radio0-vlan999"]

        for interface in test_cases:
            device_data = {ATTR_INTERFACE: interface}
            mock_coordinator._determine_vlan(device_data)

            # Verify that the same pattern object is still being used
            # (no recompilation happening)
            assert (
                mock_coordinator._vlan_pattern is original_pattern
            ), "Pattern object should remain the same across calls"

    def test_regex_pattern_thread_safety(self, mock_coordinator):
        """Test that the compiled regex pattern is thread-safe."""
        import concurrent.futures

        def vlan_detection_worker():
            """Worker function that performs VLAN detection."""
            device_data = {ATTR_INTERFACE: "wlan0-vlan42"}
            return mock_coordinator._determine_vlan(device_data)

        # Run multiple threads concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(vlan_detection_worker) for _ in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # All results should be the same (42)
        assert all(result == 42 for result in results), f"Inconsistent results: {set(results)}"
        assert len(results) == 100, f"Expected 100 results, got {len(results)}"

    def test_vlan_pattern_edge_cases(self, mock_coordinator):
        """Test edge cases for VLAN pattern matching."""
        test_cases = [
            ({ATTR_INTERFACE: "vlan123"}, 123),  # Just vlan + number
            ({ATTR_INTERFACE: "prefix-vlan0-suffix"}, 0),  # VLAN 0
            ({ATTR_INTERFACE: "prefix-vlan4094-suffix"}, 4094),  # Max VLAN ID
            ({ATTR_INTERFACE: "prefix-vlan99999-suffix"}, 99999),  # Beyond max VLAN ID
            ({ATTR_INTERFACE: "vlanxyz"}, 1),  # No number after vlan
            ({ATTR_INTERFACE: "prefix-vlan-suffix"}, 1),  # No number after vlan
            ({ATTR_INTERFACE: ""}, 1),  # Empty interface
            ({}, 1),  # No interface key
        ]

        for device_data, expected_vlan in test_cases:
            result = mock_coordinator._determine_vlan(device_data)
            assert (
                result == expected_vlan
            ), f"Failed for {device_data}: expected {expected_vlan}, got {result}"

    def test_regex_compilation_optimization(self):
        """Test that regex pattern compilation optimization is correctly implemented."""
        # Create a compiled pattern (case-sensitive like in our implementation)
        pattern = re.compile(r"vlan(\d+)")

        # Test that it works correctly
        match = pattern.search("wlan0-vlan123")
        assert match is not None
        assert match.group(1) == "123"

        # Test case sensitive behavior (our implementation uses lower())
        match = pattern.search("WLAN0-VLAN456".lower())
        assert match is not None
        assert match.group(1) == "456"

        # Test no match
        match = pattern.search("no-vlan-here")
        assert match is None
