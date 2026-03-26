"""Tests for HA client."""

import pytest
from aioresponses import aioresponses

from dev.pipeline.ha_client import HAClient, HADiagnostics


class TestHADiagnostics:
    def test_is_healthy_true(self):
        d = HADiagnostics(10, 0, [], ["card1"], [], [])
        assert d.is_healthy

    def test_is_healthy_false_no_entities(self):
        d = HADiagnostics(0, 0, [], [], [], [])
        assert not d.is_healthy

    def test_is_healthy_false_unavailable(self):
        d = HADiagnostics(10, 3, [], [], [], [])
        assert not d.is_healthy

    def test_summary_includes_counts(self):
        d = HADiagnostics(
            entity_count=10,
            unavailable_count=2,
            entities=[],
            dashboard_cards=["custom:router-health-card"],
            ha_log_errors=["ERROR wrtmanager: auth timeout"],
            console_errors=[],
        )
        s = d.summary()
        assert "10 total" in s
        assert "2 unavailable" in s
        assert "router-health-card" in s
        assert "auth timeout" in s

    def test_summary_truncates_long_errors(self):
        d = HADiagnostics(1, 0, [], [], ["x" * 200], [])
        s = d.summary()
        for line in s.split("\n"):
            assert len(line) <= 125


HA_URL = "http://ha-test:8123"
STATES = [
    {
        "entity_id": "binary_sensor.iphone_presence",
        "state": "on",
        "attributes": {"signal": -55},
    },
    {"entity_id": "sensor.main_router_memory_usage", "state": "45.2", "attributes": {}},
    {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
]
CONFIG_ENTRIES = [
    {"domain": "wrtmanager", "state": "loaded", "entry_id": "abc123"},
]
CONFIG_ENTRIES_NOT_LOADED = [
    {"domain": "wrtmanager", "state": "setup_error", "entry_id": "abc123"},
]


class TestHAClient:
    @pytest.mark.asyncio
    async def test_is_ready(self):
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/", payload={"message": "API running"})
            client = HAClient(HA_URL, "token")
            assert await client.is_ready()
            await client.close()

    @pytest.mark.asyncio
    async def test_is_ready_connection_error(self):
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/", exception=ConnectionError("refused"))
            client = HAClient(HA_URL, "token")
            assert not await client.is_ready()
            await client.close()

    @pytest.mark.asyncio
    async def test_is_integration_loaded(self):
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES)
            client = HAClient(HA_URL, "token")
            assert await client.is_integration_loaded()
            await client.close()

    @pytest.mark.asyncio
    async def test_is_integration_not_loaded(self):
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES_NOT_LOADED)
            client = HAClient(HA_URL, "token")
            assert not await client.is_integration_loaded()
            await client.close()

    @pytest.mark.asyncio
    async def test_get_wrt_entities_returns_all_states(self):
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/states", payload=STATES)
            client = HAClient(HA_URL, "token")
            entities = await client.get_wrt_entities()
            assert len(entities) == 3  # returns all states
            await client.close()

    @pytest.mark.asyncio
    async def test_get_states_bad_status(self):
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/states", status=401)
            client = HAClient(HA_URL, "bad-token")
            states = await client.get_states()
            assert states == []
            await client.close()

    @pytest.mark.asyncio
    async def test_wait_for_integration_immediate(self):
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES)
            client = HAClient(HA_URL, "token")
            loaded = await client.wait_for_integration(timeout=5)
            assert loaded is True
            await client.close()

    @pytest.mark.asyncio
    async def test_wait_for_integration_polls(self):
        """Polls until integration is loaded."""
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES_NOT_LOADED)
            m.get(f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES_NOT_LOADED)
            m.get(f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES)

            client = HAClient(HA_URL, "token")
            loaded = await client.wait_for_integration(timeout=10)
            assert loaded is True
            await client.close()

    @pytest.mark.asyncio
    async def test_wait_for_integration_timeout(self):
        with aioresponses() as m:
            for _ in range(5):
                m.get(
                    f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES_NOT_LOADED
                )
            client = HAClient(HA_URL, "token")
            loaded = await client.wait_for_integration(timeout=3)
            assert loaded is False
            await client.close()

    @pytest.mark.asyncio
    async def test_capture_diagnostics(self):
        states_with_unavail = [
            {"entity_id": "binary_sensor.iphone_presence", "state": "on", "attributes": {}},
            {"entity_id": "sensor.main_router_load", "state": "unavailable", "attributes": {}},
        ]
        with aioresponses() as m:
            m.get(f"{HA_URL}/api/config/config_entries/entry", payload=CONFIG_ENTRIES)
            m.get(f"{HA_URL}/api/states", payload=states_with_unavail)

            client = HAClient(HA_URL, "token")
            diag = await client.capture_diagnostics(
                ha_log_lines=["ERROR: something"],
                console_errors=["JS error"],
            )
            assert diag.entity_count == 2
            assert diag.unavailable_count == 1
            assert len(diag.ha_log_errors) == 1
            assert len(diag.console_errors) == 1
            await client.close()

    @pytest.mark.asyncio
    async def test_restart(self):
        with aioresponses() as m:
            m.post(f"{HA_URL}/api/services/homeassistant/restart", payload={})
            # Don't wait for ready in test
            client = HAClient(HA_URL, "token")
            result = await client.restart(wait=False)
            assert result is True
            await client.close()

    @pytest.mark.asyncio
    async def test_restart_failure(self):
        with aioresponses() as m:
            m.post(f"{HA_URL}/api/services/homeassistant/restart", status=500)
            client = HAClient(HA_URL, "token")
            result = await client.restart(wait=False)
            assert result is False
            await client.close()

    @pytest.mark.asyncio
    async def test_update_token(self):
        client = HAClient(HA_URL, "old-token")
        await client.update_token("new-token")
        assert client.token == "new-token"
        await client.close()
