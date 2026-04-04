"""The WrtManager integration."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import WrtManagerCoordinator

_INTEGRATION_DIR = Path(__file__).parent
_MANIFEST = json.loads((_INTEGRATION_DIR / "manifest.json").read_text())
CARDS_VERSION = _MANIFEST["version"]
CARDS_URL = f"/{DOMAIN}/wrtmanager-cards.js"
CARDS_RESOURCE_URL = f"{CARDS_URL}?v={CARDS_VERSION}"
CARDS_PATH = _INTEGRATION_DIR / "www" / "wrtmanager-cards.js"

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WrtManager from a config entry."""
    _LOGGER.debug("Setting up WrtManager integration")

    # Get scan interval from options or use default
    scan_interval_seconds = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    scan_interval = timedelta(seconds=scan_interval_seconds)

    _LOGGER.debug("Using scan interval: %d seconds", scan_interval_seconds)

    # Create coordinator for data updates
    coordinator = WrtManagerCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_interval=scan_interval,
        config_entry=entry,
    )

    # Fetch initial data so we have data when entities subscribe
    # Only use async_config_entry_first_refresh when entry is in SETUP_IN_PROGRESS state
    # to avoid deprecation warning in Home Assistant 2025.11+
    if entry.state == ConfigEntryState.SETUP_IN_PROGRESS:
        await coordinator.async_config_entry_first_refresh()
    else:
        # For entries not in SETUP_IN_PROGRESS, use regular refresh
        await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady("Failed to initialize WrtManager")

    # Store coordinator in hass data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Register custom Lovelace cards (only once across all config entries)
    if not hass.data.get(f"{DOMAIN}_cards_registered"):
        hass.data[f"{DOMAIN}_cards_registered"] = True
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARDS_URL, str(CARDS_PATH), cache_headers=False)]
            )
        except Exception:
            _LOGGER.info(
                "Could not register Lovelace card path. "
                "Add '%s' as a JS module resource manually.",
                CARDS_URL,
            )

        async def _register_cards(_event: Event | None = None) -> None:
            try:
                resources = hass.data["lovelace"].resources
                if not any(r.get("url", "").startswith(CARDS_URL) for r in resources.async_items()):
                    await resources.async_create_item(
                        {"res_type": "module", "url": CARDS_RESOURCE_URL}
                    )
                    _LOGGER.info("Registered WrtManager Lovelace cards v%s", CARDS_VERSION)
            except Exception:
                _LOGGER.info(
                    "Could not auto-register Lovelace cards. "
                    "Add '%s' as a JS module resource manually.",
                    CARDS_URL,
                )

        if hass.is_running:
            await _register_cards()
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_cards)

    # Forward the setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading WrtManager integration")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(f"{DOMAIN}_cards_registered", None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
