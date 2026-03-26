"""Home Assistant REST + WebSocket client for pipeline operations."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class HADiagnostics:
    """Captured state from a running HA instance."""

    entity_count: int
    unavailable_count: int
    entities: list[dict]  # [{entity_id, state, attr_count}]
    dashboard_cards: list[str]  # card types on dashboard
    ha_log_errors: list[str]  # wrtmanager-related errors
    console_errors: list[str]  # browser console errors

    @property
    def is_healthy(self) -> bool:
        return self.entity_count > 0 and self.unavailable_count == 0

    def summary(self) -> str:
        lines = [
            f"Entities: {self.entity_count} total, {self.unavailable_count} unavailable",
            f"Dashboard cards: {len(self.dashboard_cards)}",
        ]
        if self.dashboard_cards:
            for c in self.dashboard_cards:
                lines.append(f"  {c}")
        if self.ha_log_errors:
            lines.append(f"HA log errors: {len(self.ha_log_errors)}")
            for e in self.ha_log_errors[:5]:
                lines.append(f"  {e[:120]}")
        if self.console_errors:
            lines.append(f"Console errors: {len(self.console_errors)}")
            for e in self.console_errors[:5]:
                lines.append(f"  {e[:120]}")
        return "\n".join(lines)


class HAClient:
    """Async client for Home Assistant REST API and WebSocket."""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {self.token}"})
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def is_ready(self) -> bool:
        """Check if HA API is responding."""
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.url}/api/", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def wait_for_ready(self, timeout: int = 60) -> bool:
        """Wait for HA API to respond after restart."""
        logger.info("Waiting for HA API (up to %ds)...", timeout)
        for i in range(timeout):
            if await self.is_ready():
                logger.info("HA API ready after %ds", i + 1)
                return True
            await asyncio.sleep(1)
        logger.warning("HA API not ready after %ds", timeout)
        return False

    async def get_states(self) -> list[dict]:
        """Get all entity states."""
        session = await self._get_session()
        async with session.get(f"{self.url}/api/states") as resp:
            if resp.status != 200:
                logger.error("GET /api/states returned %d", resp.status)
                return []
            return await resp.json()

    async def is_integration_loaded(self) -> bool:
        """Check if wrtmanager config entry is in 'loaded' state."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.url}/api/config/config_entries/entry") as resp:
                if resp.status != 200:
                    return False
                entries = await resp.json()
                return any(
                    e.get("domain") == "wrtmanager" and e.get("state") == "loaded" for e in entries
                )
        except Exception:
            return False

    async def get_wrt_entities(self) -> list[dict]:
        """Get all entity states (for diagnostics). Only call after is_integration_loaded()."""
        return await self.get_states()

    async def wait_for_integration(self, timeout: int = 60) -> bool:
        """Wait for wrtmanager integration to reach 'loaded' state."""
        logger.info("Waiting for wrtmanager integration (up to %ds)...", timeout)
        for i in range(timeout):
            if await self.is_integration_loaded():
                logger.info("Integration loaded after %ds", i + 1)
                return True
            await asyncio.sleep(1)
        logger.warning("Integration not loaded after %ds", timeout)
        return False

    async def restart(self, wait: bool = True, wait_timeout: int = 60) -> bool:
        """Restart HA and optionally wait for it to come back."""
        logger.info("Restarting HA...")
        session = await self._get_session()
        try:
            async with session.post(
                f"{self.url}/api/services/homeassistant/restart",
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status not in (200, 201):
                    logger.error("Restart request failed: %d", resp.status)
                    return False
        except Exception as e:
            logger.error("Restart request error: %s", e)
            return False

        if wait:
            # HA goes down briefly after restart
            await asyncio.sleep(2)
            # Close existing session (connection will be reset)
            await self.close()
            return await self.wait_for_ready(wait_timeout)
        return True

    async def get_dashboard_cards(self) -> list[str]:
        """Get card types from the Lovelace dashboard via WebSocket."""
        try:
            session = await self._get_session()
            async with session.ws_connect(f"{self.url}/api/websocket") as ws:
                # Auth
                await ws.receive_json()
                await ws.send_json({"type": "auth", "access_token": self.token})
                msg = await ws.receive_json()
                if msg.get("type") != "auth_ok":
                    logger.error("WebSocket auth failed: %s", msg)
                    return []

                # Get dashboard config
                await ws.send_json({"id": 1, "type": "lovelace/config"})
                config = await ws.receive_json()
                views = config.get("result", {}).get("views", [])
                if not views:
                    return []
                cards = views[0].get("cards", [])
                return [c.get("type", "?") for c in cards]
        except Exception as e:
            logger.error("Dashboard cards error: %s", e)
            return []

    async def capture_diagnostics(
        self,
        ha_log_lines: Optional[list[str]] = None,
        console_errors: Optional[list[str]] = None,
    ) -> HADiagnostics:
        """Capture full diagnostics from HA instance."""
        entities = await self.get_wrt_entities()
        dashboard_cards = await self.get_dashboard_cards()

        entity_summaries = []
        unavail = 0
        for e in entities:
            state = e.get("state", "?")
            attrs = e.get("attributes", {})
            entity_summaries.append(
                {
                    "entity_id": e["entity_id"],
                    "state": state,
                    "attr_count": len(attrs),
                }
            )
            if state in ("unavailable", "unknown"):
                unavail += 1

        return HADiagnostics(
            entity_count=len(entities),
            unavailable_count=unavail,
            entities=entity_summaries,
            dashboard_cards=dashboard_cards,
            ha_log_errors=ha_log_lines or [],
            console_errors=console_errors or [],
        )

    async def update_token(self, new_token: str):
        """Update the auth token (after refresh)."""
        self.token = new_token
        await self.close()  # force new session with new token
