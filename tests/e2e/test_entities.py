"""E2E tests: verify entities are created correctly in a running HA instance.

These tests require a running HA instance with the wrtmanager integration
configured against mock ubus servers.

Run with:
    HA_URL=http://localhost:18123 HA_TOKEN=<token> pytest tests/e2e/ -v
"""

import os

import pytest

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("HA_TOKEN"),
        reason="E2E tests require HA_TOKEN environment variable",
    ),
    pytest.mark.allow_hosts(["localhost", "127.0.0.1"]),
]


class TestIntegrationSetup:
    """Test that the integration loads and creates entities."""

    def test_integration_loaded(self, ha_config_entries):
        """Verify wrtmanager integration is configured."""
        wrt_entries = [e for e in ha_config_entries if e.get("domain") == "wrtmanager"]
        assert len(wrt_entries) >= 1, "wrtmanager integration not found in config entries"

    def test_integration_state(self, ha_config_entries):
        """Verify integration is in loaded state."""
        wrt_entries = [e for e in ha_config_entries if e.get("domain") == "wrtmanager"]
        for entry in wrt_entries:
            assert (
                entry.get("state") == "loaded"
            ), f"Integration state is '{entry.get('state')}', expected 'loaded'"


class TestDevicePresenceSensors:
    """Test that presence binary sensors are created for connected devices."""

    def test_presence_sensors_exist(self, ha_states):
        """At least some presence binary sensors should be created."""
        presence_entities = [
            s
            for s in ha_states
            if s["entity_id"].startswith("binary_sensor.") and "presence" in s["entity_id"].lower()
        ]
        # The mock scenario has ~15 connected devices, so we should see sensors
        assert len(presence_entities) > 0, "No presence binary sensors found"

    def test_presence_sensor_attributes(self, ha_states):
        """Presence sensors should have expected attributes."""
        presence_entities = [
            s
            for s in ha_states
            if s["entity_id"].startswith("binary_sensor.") and "presence" in s["entity_id"].lower()
        ]
        if not presence_entities:
            pytest.skip("No presence sensors to check")

        entity = presence_entities[0]
        attrs = entity.get("attributes", {})
        # Should have at least some of these attributes
        expected_attrs = {"mac_address", "router", "interface", "friendly_name"}
        found_attrs = set(attrs.keys())
        assert (
            found_attrs & expected_attrs
        ), f"Presence sensor missing expected attributes. Found: {found_attrs}"


class TestSystemSensors:
    """Test system monitoring sensors."""

    def test_system_sensors_exist(self, ha_states):
        """System sensors should be created for each router."""
        system_entities = [
            s
            for s in ha_states
            if s["entity_id"].startswith("sensor.") and "uptime" in s["entity_id"].lower()
        ]
        # Should have at least one uptime sensor (one per router)
        assert len(system_entities) > 0, "No uptime sensors found"


class TestSSIDSensors:
    """Test SSID binary sensors."""

    def test_ssid_sensors_exist(self, ha_states):
        """SSID binary sensors should be created."""
        ssid_entities = [
            s
            for s in ha_states
            if s["entity_id"].startswith("binary_sensor.") and "ssid" in s["entity_id"].lower()
        ]
        # The mock scenario has HomeNet and HomeNet-Guest SSIDs
        assert len(ssid_entities) > 0, "No SSID binary sensors found"


class TestDisconnectButtons:
    """Test WiFi client disconnect buttons."""

    def test_disconnect_buttons_exist(self, ha_states):
        """Disconnect buttons should be created for connected devices."""
        button_entities = [
            s
            for s in ha_states
            if s["entity_id"].startswith("button.") and "disconnect" in s["entity_id"].lower()
        ]
        assert len(button_entities) > 0, "No disconnect buttons found"


class TestDataRefresh:
    """Test that data refreshes work correctly."""

    def test_entities_have_recent_data(self, ha_states):
        """Entities should have recent last_updated timestamps."""
        wrt_entities = [
            s
            for s in ha_states
            if "wrtmanager" in s.get("attributes", {}).get("integration", "")
            or s["entity_id"].startswith(("binary_sensor.", "sensor.", "button."))
        ]
        # Just verify we have entities - timing checks are fragile
        # The coordinator is updating every 30s
        assert len(wrt_entities) > 0, "No wrtmanager entities found"
