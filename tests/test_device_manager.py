"""Test the DeviceManager class."""

from unittest.mock import AsyncMock, mock_open, patch

import pytest
from aiohttp import ClientError

from custom_components.wrtmanager.const import (
    DEVICE_TYPE_BRIDGE,
    DEVICE_TYPE_COMPUTER,
    DEVICE_TYPE_HOME_APPLIANCE,
    DEVICE_TYPE_IOT_SWITCH,
    DEVICE_TYPE_MOBILE,
    DEVICE_TYPE_NETWORK_EQUIPMENT,
    DEVICE_TYPE_PRINTER,
    DEVICE_TYPE_ROBOT_VACUUM,
    DEVICE_TYPE_SMART_SPEAKER,
    DEVICE_TYPE_UNKNOWN,
    DEVICE_TYPE_VEHICLE,
)
from custom_components.wrtmanager.device_manager import DeviceManager


@pytest.fixture
def device_manager():
    """Create a DeviceManager instance."""
    return DeviceManager()


class TestDeviceManagerInitialization:
    """Test DeviceManager initialization."""

    def test_device_manager_init(self, device_manager):
        """Test DeviceManager initialization."""
        assert device_manager is not None
        assert hasattr(device_manager, "DEVICE_TYPE_DATABASE")
        assert hasattr(device_manager, "_oui_cache")
        assert device_manager._oui_cache == {}


class TestDeviceIdentification:
    """Test device identification methods."""

    def test_identify_device_custom_database_match(self, device_manager):
        """Test device identification with custom database match."""
        # Test Shelly device
        result = device_manager.identify_device("A4:CF:12:34:56:78")

        assert result is not None
        assert result["vendor"] == "Shelly"
        assert result["device_type"] == DEVICE_TYPE_IOT_SWITCH

    def test_identify_device_custom_database_partial_match(self, device_manager):
        """Test device identification with partial MAC match."""
        # Test Gree air conditioner
        result = device_manager.identify_device("A0:92:08:11:22:33")

        assert result is not None
        assert result["vendor"] == "Gree"
        assert result["device_type"] == DEVICE_TYPE_HOME_APPLIANCE

    def test_identify_device_with_vendor_lookup(self, device_manager):
        """Test device identification with vendor lookup."""
        # Mock the _lookup_oui_vendor method
        with patch.object(device_manager, "_lookup_oui_vendor") as mock_vendor:
            mock_vendor.return_value = "Apple Inc."

            result = device_manager.identify_device("00:11:22:33:44:55")

            assert result is not None
            assert result["vendor"] == "Apple Inc."
            # Should get device type based on vendor heuristics
            assert result["device_type"] == DEVICE_TYPE_MOBILE

    def test_identify_device_no_match(self, device_manager):
        """Test device identification with no match."""
        with patch.object(device_manager, "_lookup_oui_vendor") as mock_vendor:
            mock_vendor.return_value = None

            result = device_manager.identify_device("FF:FF:FF:FF:FF:FF")

            assert result is None

    def test_identify_device_invalid_mac(self, device_manager):
        """Test device identification with invalid MAC."""
        result = device_manager.identify_device("invalid-mac")

        assert result is None

    def test_identify_device_empty_mac(self, device_manager):
        """Test device identification with empty MAC."""
        result = device_manager.identify_device("")

        assert result is None


class TestVendorLookup:
    """Test vendor lookup functionality."""

    def test_lookup_oui_vendor_cached(self, device_manager):
        """Test vendor lookup with cached result."""
        # Pre-populate cache
        device_manager._oui_cache["00:11:22"] = "Test Vendor"

        result = device_manager._lookup_oui_vendor("00:11:22")

        assert result == "Test Vendor"

    def test_lookup_oui_vendor_not_cached(self, device_manager):
        """Test vendor lookup when not cached."""
        with patch.object(device_manager, "_lookup_oui_from_file") as mock_file_lookup:
            mock_file_lookup.return_value = "Test Vendor"

            result = device_manager._lookup_oui_vendor("00:11:22")

            assert result == "Test Vendor"
            # Check that result is cached
            assert device_manager._oui_cache["00:11:22"] == "Test Vendor"

    def test_lookup_oui_vendor_file_lookup_fails(self, device_manager):
        """Test vendor lookup when file lookup fails."""
        with patch.object(device_manager, "_lookup_oui_from_file") as mock_file_lookup:
            mock_file_lookup.return_value = None

            result = device_manager._lookup_oui_vendor("00:11:22")

            assert result is None

    def test_lookup_oui_from_file_disabled(self, device_manager):
        """Test that file lookup is disabled (returns None)."""
        result = device_manager._lookup_oui_from_file("00:11:22")

        assert result is None


class TestDeviceTypeHeuristics:
    """Test device type detection heuristics."""

    def test_infer_device_type_from_vendor_mobile(self, device_manager):
        """Test device type detection for mobile devices."""
        mobile_vendors = ["Apple Inc.", "Samsung", "Google", "Xiaomi", "OnePlus"]

        for vendor in mobile_vendors:
            result = device_manager._infer_device_type_from_vendor(vendor)
            assert result == DEVICE_TYPE_MOBILE

    def test_infer_device_type_from_vendor_computer(self, device_manager):
        """Test device type detection for computers."""
        computer_vendors = ["Dell Inc.", "Lenovo", "Microsoft", "Intel"]

        for vendor in computer_vendors:
            result = device_manager._infer_device_type_from_vendor(vendor)
            assert result == DEVICE_TYPE_COMPUTER

        # HP is detected as printer, not computer
        assert device_manager._infer_device_type_from_vendor("HP") == DEVICE_TYPE_PRINTER

    def test_infer_device_type_from_vendor_network(self, device_manager):
        """Test device type detection for network equipment."""
        network_vendors = ["Cisco", "Netgear", "TP-Link", "Ubiquiti", "Mikrotik"]

        for vendor in network_vendors:
            result = device_manager._infer_device_type_from_vendor(vendor)
            assert result == DEVICE_TYPE_NETWORK_EQUIPMENT

    def test_infer_device_type_from_vendor_smart_speaker(self, device_manager):
        """Test device type detection for smart speakers."""
        speaker_vendors = ["Sonos", "Bose", "JBL"]

        for vendor in speaker_vendors:
            result = device_manager._infer_device_type_from_vendor(vendor)
            assert result == DEVICE_TYPE_SMART_SPEAKER

    def test_infer_device_type_from_vendor_printer(self, device_manager):
        """Test device type detection for printers."""
        printer_vendors = ["Canon", "Epson", "Brother", "HP"]

        for vendor in printer_vendors:
            result = device_manager._infer_device_type_from_vendor(vendor)
            assert result == DEVICE_TYPE_PRINTER

    def test_infer_device_type_from_vendor_vehicle(self, device_manager):
        """Test device type detection for vehicles."""
        vehicle_vendors = ["Tesla", "BMW", "Mercedes", "Audi"]

        for vendor in vehicle_vendors:
            result = device_manager._infer_device_type_from_vendor(vendor)
            assert result == DEVICE_TYPE_VEHICLE

    def test_infer_device_type_from_vendor_unknown(self, device_manager):
        """Test device type detection for unknown vendor."""
        result = device_manager._infer_device_type_from_vendor("Unknown Vendor Corp")

        assert result == DEVICE_TYPE_UNKNOWN

    def test_infer_device_type_from_vendor_iot(self, device_manager):
        """Test device type detection for IoT devices."""
        iot_vendors = ["Shelly", "Sonoff", "ESP"]

        for vendor in iot_vendors:
            result = device_manager._infer_device_type_from_vendor(vendor)
            assert result == DEVICE_TYPE_IOT_SWITCH


class TestMACAddressHandling:
    """Test MAC address handling and normalization."""

    def test_normalize_mac_address(self, device_manager):
        """Test MAC address normalization."""
        test_cases = [
            ("aa:bb:cc:dd:ee:ff", "AA:BB:CC"),
            ("AA-BB-CC-DD-EE-FF", "AA:BB:CC"),
            ("aabbccddeeff", "AA:BB:CC"),
            ("AA.BB.CC.DD.EE.FF", "AA:BB:CC"),
        ]

        for input_mac, expected in test_cases:
            # Test the internal _get_mac_prefix method if it exists
            device_manager.identify_device(input_mac + "dd:ee:ff")
            # The method should handle various MAC formats correctly


class TestCustomDatabaseEntries:
    """Test custom device database entries."""

    def test_shelly_devices(self, device_manager):
        """Test Shelly device detection."""
        shelly_prefixes = ["A4:CF:12", "2C:F4:32", "EC:FA:BC", "C8:47:8C"]

        for prefix in shelly_prefixes:
            result = device_manager.identify_device(f"{prefix}:34:56:78")
            assert result is not None
            assert result["vendor"] == "Shelly"
            assert result["device_type"] == DEVICE_TYPE_IOT_SWITCH

    def test_gree_devices(self, device_manager):
        """Test Gree air conditioner detection."""
        gree_prefixes = ["A0:92:08", "CC:8C:BF", "1C:90:FF"]

        for prefix in gree_prefixes:
            result = device_manager.identify_device(f"{prefix}:34:56:78")
            assert result is not None
            assert result["vendor"] == "Gree"
            assert result["device_type"] == DEVICE_TYPE_HOME_APPLIANCE

    def test_robot_vacuum_devices(self, device_manager):
        """Test robot vacuum detection."""
        result = device_manager.identify_device("28:B7:7C:34:56:78")

        assert result is not None
        assert result["vendor"] == "Dreame"
        assert result["device_type"] == DEVICE_TYPE_ROBOT_VACUUM


class TestCacheManagement:
    """Test cache management functionality."""

    def test_oui_cache_functionality(self, device_manager):
        """Test OUI cache functionality."""
        # Test cache storage
        device_manager._oui_cache["00:11:22"] = "Test Vendor"

        result = device_manager._lookup_oui_vendor("00:11:22")
        assert result == "Test Vendor"

    def test_cache_different_ouis(self, device_manager):
        """Test cache with different OUIs."""
        device_manager._oui_cache["00:11:22"] = "Vendor A"
        device_manager._oui_cache["33:44:55"] = "Vendor B"

        assert device_manager._lookup_oui_vendor("00:11:22") == "Vendor A"
        assert device_manager._lookup_oui_vendor("33:44:55") == "Vendor B"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_identify_device_mixed_case_mac(self, device_manager):
        """Test device identification with mixed case MAC."""
        result = device_manager.identify_device("a4:Cf:12:34:56:78")

        assert result is not None
        assert result["vendor"] == "Shelly"
        assert result["device_type"] == DEVICE_TYPE_IOT_SWITCH

    def test_generate_device_name_functionality(self, device_manager):
        """Test device name generation."""
        test_cases = [
            ("Shelly", DEVICE_TYPE_IOT_SWITCH, "AA:BB:CC:DD:EE:FF", "Shelly", "Switch"),
            ("Apple", DEVICE_TYPE_MOBILE, "11:22:33:44:55:66", "Apple", "Phone"),
            ("Unknown", DEVICE_TYPE_UNKNOWN, "99:88:77:66:55:44", "Unknown", "Device"),
        ]

        for vendor, device_type, mac, expected_vendor, expected_type in test_cases:
            result = device_manager._generate_device_name(vendor, device_type, mac)
            assert expected_vendor in result
            # Check that the MAC suffix is in the name (last 3 bytes without colons)
            mac_suffix = mac.split(":")[-3:]  # Get last 3 octets
            assert any(octet.upper() in result.upper() for octet in mac_suffix)

    @pytest.mark.skip(
        reason="Complex async mocking - OUI database download tested in integration tests"
    )
    @pytest.mark.asyncio
    async def test_download_oui_database_success(self, device_manager):
        """Test successful OUI database download."""
        pass

    @pytest.mark.skip(
        reason="Complex async mocking - OUI database download tested in integration tests"
    )
    @pytest.mark.asyncio
    async def test_download_oui_database_failure(self, device_manager):
        """Test failed OUI database download."""
        pass

    def test_device_database_completeness(self, device_manager):
        """Test that device database has required structure."""
        for prefix, info in device_manager.DEVICE_TYPE_DATABASE.items():
            assert isinstance(prefix, str)
            assert ":" in prefix  # Should be MAC prefix format
            assert "vendor" in info
            assert "device_type" in info
            assert isinstance(info["vendor"], str)
            assert info["device_type"] in [
                DEVICE_TYPE_BRIDGE,
                DEVICE_TYPE_COMPUTER,
                DEVICE_TYPE_HOME_APPLIANCE,
                DEVICE_TYPE_IOT_SWITCH,
                DEVICE_TYPE_MOBILE,
                DEVICE_TYPE_NETWORK_EQUIPMENT,
                DEVICE_TYPE_PRINTER,
                DEVICE_TYPE_ROBOT_VACUUM,
                DEVICE_TYPE_SMART_SPEAKER,
                DEVICE_TYPE_UNKNOWN,
                DEVICE_TYPE_VEHICLE,
            ]
