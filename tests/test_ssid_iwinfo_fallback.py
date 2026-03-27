"""Tests for SSID resolution using iwinfo.info as primary source."""

import pytest

from custom_components.wrtmanager.coordinator import WrtManagerCoordinator


class MockCoordinator:
    """Minimal coordinator stub for testing _extract_ssid_data."""

    def _extract_ssid_data(self, interfaces):
        return WrtManagerCoordinator._extract_ssid_data(self, interfaces)

    def _consolidate_ssids_by_name(self, ssid_data):
        return WrtManagerCoordinator._consolidate_ssids_by_name(self, ssid_data)

    def _get_frequency_bands(self, radios):
        return WrtManagerCoordinator._get_frequency_bands(self, radios)

    def _sanitize_config(self, config):
        return WrtManagerCoordinator._sanitize_config(config)


def _make_interfaces(router_host, ifname, config_ssid, iwinfo_ssids=None):
    """Build a minimal interfaces dict as produced by _collect_router_data."""
    data = {
        "radio0": {
            "up": True,
            "interfaces": [
                {
                    "ifname": ifname,
                    "config": {
                        "mode": "ap",
                        "ssid": config_ssid,
                        "encryption": "sae-mixed",
                        "disabled": False,
                    },
                }
            ],
        }
    }
    if iwinfo_ssids:
        data["_iwinfo_ssids"] = iwinfo_ssids
    return {router_host: data}


class TestIwinfoSsidFallback:
    """Test that iwinfo SSID is preferred over config SSID."""

    @pytest.fixture
    def coord(self):
        return MockCoordinator()

    def test_iwinfo_ssid_overrides_config_ssid(self, coord):
        """iwinfo SSID wins when config has a different (stale/masked) value."""
        interfaces = _make_interfaces(
            "192.168.1.1",
            "phy0-ap0",
            config_ssid="old-name",
            iwinfo_ssids={"phy0-ap0": "HomeNet"},
        )
        result = coord._extract_ssid_data(interfaces)
        assert "192.168.1.1" in result
        ssids = result["192.168.1.1"]
        assert any(s["ssid_name"] == "HomeNet" for s in ssids)
        assert not any(s["ssid_name"] == "old-name" for s in ssids)

    def test_iwinfo_ssid_used_even_when_config_matches(self, coord):
        """When both sources agree, the result is still correct."""
        interfaces = _make_interfaces(
            "192.168.1.1",
            "phy0-ap0",
            config_ssid="HomeNet",
            iwinfo_ssids={"phy0-ap0": "HomeNet"},
        )
        result = coord._extract_ssid_data(interfaces)
        assert "192.168.1.1" in result
        ssids = result["192.168.1.1"]
        assert any(s["ssid_name"] == "HomeNet" for s in ssids)

    def test_config_ssid_used_when_iwinfo_unavailable(self, coord):
        """Falls back to config SSID when no iwinfo data is present."""
        interfaces = _make_interfaces(
            "192.168.1.1",
            "phy0-ap0",
            config_ssid="GuestNet",
        )
        result = coord._extract_ssid_data(interfaces)
        assert "192.168.1.1" in result
        ssids = result["192.168.1.1"]
        assert any(s["ssid_name"] == "GuestNet" for s in ssids)

    def test_config_ssid_preserved_when_no_iwinfo_data(self, coord):
        """'unknown' is preserved as-is when no iwinfo override — legitimate SSID name."""
        interfaces = _make_interfaces(
            "192.168.1.1",
            "phy0-ap0",
            config_ssid="unknown",
        )
        result = coord._extract_ssid_data(interfaces)
        assert "192.168.1.1" in result
        ssids = result["192.168.1.1"]
        assert any(s["ssid_name"] == "unknown" for s in ssids)

    def test_iwinfo_ssid_overrides_unknown_config(self, coord):
        """iwinfo SSID replaces ACL-masked 'unknown' value from config."""
        interfaces = _make_interfaces(
            "192.168.1.2",
            "phy0-ap0",
            config_ssid="unknown",
            iwinfo_ssids={"phy0-ap0": "HomeNet"},
        )
        result = coord._extract_ssid_data(interfaces)
        assert "192.168.1.2" in result
        ssids = result["192.168.1.2"]
        assert any(s["ssid_name"] == "HomeNet" for s in ssids)
        assert not any(s["ssid_name"] == "unknown" for s in ssids)

    def test_iwinfo_ssids_key_removed_after_extraction(self, coord):
        """_iwinfo_ssids is consumed (popped) during extraction and not left in interfaces."""
        interfaces = _make_interfaces(
            "192.168.1.1",
            "phy0-ap0",
            config_ssid="HomeNet",
            iwinfo_ssids={"phy0-ap0": "HomeNet"},
        )
        coord._extract_ssid_data(interfaces)
        assert "_iwinfo_ssids" not in interfaces["192.168.1.1"]
