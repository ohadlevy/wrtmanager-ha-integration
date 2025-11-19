"""Tests for SSID consolidation functionality."""

from unittest.mock import Mock

import pytest

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


class TestSSIDConsolidation:
    """Test SSID consolidation logic."""

    @pytest.fixture
    def coordinator(self):
        """Create a coordinator instance for testing."""
        return WrtManagerCoordinator(
            hass=Mock(), logger=Mock(), name="test", update_interval=Mock(), config_entry=Mock()
        )

    def test_single_radio_ssid_no_consolidation(self, coordinator):
        """Test that single radio SSIDs are not consolidated."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "MainNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "network": "lan",
                }
            ]
        }

        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)

        # Should have one SSID, not consolidated
        assert len(consolidated["192.168.1.1"]) == 1
        ssid = consolidated["192.168.1.1"][0]
        assert ssid.get("is_consolidated", False) is False
        assert ssid["radio"] == "radio0"
        assert ssid["ssid_name"] == "MainNetwork"

    def test_dual_radio_ssid_consolidation(self, coordinator):
        """Test that same SSID on multiple radios gets consolidated."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "DualBandNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "network": "lan",
                    "network_interface": "wlan0",
                },
                {
                    "radio": "radio1",
                    "ssid_name": "DualBandNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "network": "lan",
                    "network_interface": "wlan1",
                },
            ]
        }

        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)

        # Should have one consolidated SSID
        assert len(consolidated["192.168.1.1"]) == 1
        ssid = consolidated["192.168.1.1"][0]

        # Verify consolidation properties
        assert ssid["is_consolidated"] is True
        assert ssid["radio_count"] == 2
        assert ssid["radios"] == ["radio0", "radio1"]
        assert ssid["ssid_interfaces"] == ["interface_0", "interface_0"]
        assert ssid["network_interfaces"] == ["wlan0", "wlan1"]
        assert ssid["frequency_bands"] == ["2.4GHz", "5GHz"]
        assert ssid["radio"] == "multi_radio_dualbandnetwork"
        assert ssid["ssid_name"] == "DualBandNetwork"

    def test_mixed_ssid_consolidation(self, coordinator):
        """Test consolidation with both single and multi-radio SSIDs."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "MainNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
                {
                    "radio": "radio1",
                    "ssid_name": "MainNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
                {
                    "radio": "radio0",
                    "ssid_name": "Guest5GHzOnly",
                    "ssid_interface": "interface_1",
                    "mode": "ap",
                    "disabled": False,
                },
            ]
        }

        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)

        # Should have two SSIDs: one consolidated, one single
        assert len(consolidated["192.168.1.1"]) == 2

        # Find the consolidated and single SSIDs
        consolidated_ssid = next(
            s for s in consolidated["192.168.1.1"] if s.get("is_consolidated", False)
        )
        single_ssid = next(
            s for s in consolidated["192.168.1.1"] if not s.get("is_consolidated", False)
        )

        # Verify consolidated SSID
        assert consolidated_ssid["ssid_name"] == "MainNetwork"
        assert consolidated_ssid["radio_count"] == 2

        # Verify single SSID
        assert single_ssid["ssid_name"] == "Guest5GHzOnly"
        assert single_ssid["radio"] == "radio0"

    def test_frequency_band_detection(self, coordinator):
        """Test frequency band detection from radio names."""
        # Test common radio naming patterns
        assert coordinator._get_frequency_bands(["radio0"]) == ["2.4GHz"]
        assert coordinator._get_frequency_bands(["radio1"]) == ["5GHz"]
        assert coordinator._get_frequency_bands(["radio0", "radio1"]) == ["2.4GHz", "5GHz"]
        assert coordinator._get_frequency_bands(["unknown_radio"]) == ["Unknown"]
        assert coordinator._get_frequency_bands([]) == []

    def test_consolidation_with_different_configurations(self, coordinator):
        """Test consolidation with SSIDs having different configurations."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "TestNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "hidden": False,
                    "isolate": False,
                    "network": "lan",
                },
                {
                    "radio": "radio1",
                    "ssid_name": "TestNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": True,  # Different disabled state
                    "encryption": "psk2",
                    "hidden": False,
                    "isolate": False,
                    "network": "lan",
                },
            ]
        }

        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)

        # Should still consolidate despite different disabled states
        assert len(consolidated["192.168.1.1"]) == 1
        ssid = consolidated["192.168.1.1"][0]
        assert ssid["is_consolidated"] is True
        assert ssid["radio_count"] == 2

        # Should preserve the configuration from the first SSID
        assert ssid["disabled"] is False
        assert ssid["encryption"] == "psk2"

    def test_consolidation_across_multiple_routers(self, coordinator):
        """Test consolidation works independently for each router."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "SharedNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
                {
                    "radio": "radio1",
                    "ssid_name": "SharedNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
            ],
            "192.168.1.2": [
                {
                    "radio": "radio0",
                    "ssid_name": "SharedNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                }
            ],
        }

        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)

        # Router 1 should have consolidated SSID
        assert len(consolidated["192.168.1.1"]) == 1
        assert consolidated["192.168.1.1"][0]["is_consolidated"] is True
        assert consolidated["192.168.1.1"][0]["radio_count"] == 2

        # Router 2 should have single SSID
        assert len(consolidated["192.168.1.2"]) == 1
        assert consolidated["192.168.1.2"][0].get("is_consolidated", False) is False

    def test_consolidation_empty_input(self, coordinator):
        """Test consolidation with empty input."""
        # Empty data
        consolidated = coordinator._consolidate_ssids_by_name({})
        assert consolidated == {}

        # Router with no SSIDs
        ssid_data = {"192.168.1.1": []}
        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)
        assert consolidated == {"192.168.1.1": []}

    def test_consolidation_virtual_radio_naming(self, coordinator):
        """Test virtual radio naming for consolidated SSIDs."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "My Home WiFi",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
                {
                    "radio": "radio1",
                    "ssid_name": "My Home WiFi",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                },
            ]
        }

        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)
        ssid = consolidated["192.168.1.1"][0]

        # Virtual radio name should be based on SSID name
        assert ssid["radio"] == "multi_radio_my_home_wifi"

    def test_consolidation_preserves_all_original_data(self, coordinator):
        """Test that consolidation preserves all original data fields."""
        ssid_data = {
            "192.168.1.1": [
                {
                    "radio": "radio0",
                    "ssid_name": "TestNetwork",
                    "ssid_interface": "interface_0",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "key": "secret123",
                    "hidden": False,
                    "isolate": True,
                    "network": "lan",
                    "router_host": "192.168.1.1",
                    "network_interface": "wlan0",
                    "full_config": {"custom_field": "value"},
                },
                {
                    "radio": "radio1",
                    "ssid_name": "TestNetwork",
                    "ssid_interface": "interface_1",
                    "mode": "ap",
                    "disabled": False,
                    "encryption": "psk2",
                    "key": "secret123",
                    "hidden": False,
                    "isolate": True,
                    "network": "lan",
                    "router_host": "192.168.1.1",
                    "network_interface": "wlan1",
                    "full_config": {"custom_field": "value"},
                },
            ]
        }

        consolidated = coordinator._consolidate_ssids_by_name(ssid_data)
        ssid = consolidated["192.168.1.1"][0]

        # Check that original fields are preserved
        assert ssid["mode"] == "ap"
        assert ssid["disabled"] is False
        assert ssid["encryption"] == "psk2"
        assert ssid["key"] == "secret123"
        assert ssid["hidden"] is False
        assert ssid["isolate"] is True
        assert ssid["network"] == "lan"
        assert ssid["router_host"] == "192.168.1.1"
        assert ssid["full_config"] == {"custom_field": "value"}

        # Check new consolidation fields
        assert ssid["is_consolidated"] is True
        assert ssid["radios"] == ["radio0", "radio1"]
        assert ssid["ssid_interfaces"] == ["interface_0", "interface_1"]
        assert ssid["network_interfaces"] == ["wlan0", "wlan1"]
        assert ssid["radio_count"] == 2
        assert ssid["frequency_bands"] == ["2.4GHz", "5GHz"]
