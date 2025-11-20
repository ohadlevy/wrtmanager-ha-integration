"""Diagnostics support for WrtManager integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import WrtManagerCoordinator

REDACT_KEYS = ["password", "key", "mac", "ip", "hostname", "serial"]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: WrtManagerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Gather diagnostic data
    diagnostics_data = {
        "integration_version": "1.0.0",
        "config_entry": {
            "title": entry.title,
            "version": entry.version,
            "domain": entry.domain,
            "unique_id": entry.unique_id,
        },
        "coordinator_data": _get_coordinator_diagnostics(coordinator),
        "routers_info": _get_routers_diagnostics(coordinator),
    }

    # Redact sensitive information
    return async_redact_data(diagnostics_data, REDACT_KEYS)


def _get_coordinator_diagnostics(coordinator: WrtManagerCoordinator) -> Dict[str, Any]:
    """Get coordinator-level diagnostics."""
    if not coordinator.data:
        return {"status": "No data available"}

    return {
        "last_update": coordinator.data.get("last_update", "Unknown"),
        "update_success": coordinator.last_update_success,
        "total_devices": coordinator.data.get("total_devices", 0),
        "total_routers": len(coordinator.data.get("routers", [])),
        "data_keys": list(coordinator.data.keys()),
        "update_interval": str(coordinator.update_interval),
    }


def _get_routers_diagnostics(coordinator: WrtManagerCoordinator) -> Dict[str, Any]:
    """Get detailed router diagnostics including uptime and system info."""
    if not coordinator.data or "system_info" not in coordinator.data:
        return {}

    routers_diagnostics = {}

    for router_host in coordinator.data.get("routers", []):
        system_info = coordinator.data.get("system_info", {}).get(router_host, {})

        router_diagnostics = {
            "system_info": {
                "uptime_seconds": system_info.get("uptime"),
                "uptime_formatted": _format_uptime(system_info.get("uptime")),
                "load_average": system_info.get("load"),
                "memory": system_info.get("memory"),
                "local_time": system_info.get("localtime"),
                "model": system_info.get("model"),
                "system": system_info.get("system"),
                "board_name": system_info.get("board_name"),
                "kernel": system_info.get("kernel"),
                "firmware_info": _get_firmware_info(system_info),
            },
            "network_interfaces": _count_interfaces(coordinator, router_host),
            "connected_devices": len(coordinator.get_devices_by_router(router_host)),
        }

        routers_diagnostics[router_host] = router_diagnostics

    return routers_diagnostics


def _format_uptime(uptime_seconds: int | None) -> str:
    """Format uptime seconds into human-readable string."""
    if not uptime_seconds:
        return "Unknown"

    uptime_delta = timedelta(seconds=uptime_seconds)
    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def _get_firmware_info(system_info: Dict[str, Any]) -> Dict[str, Any]:
    """Extract firmware information from system info."""
    release_info = system_info.get("release", {})
    return {
        "openwrt_version": release_info.get("version"),
        "openwrt_description": release_info.get("description"),
        "distribution": release_info.get("distribution"),
        "revision": release_info.get("revision"),
        "target": release_info.get("target"),
        "build_date": release_info.get("builddate"),
        "kernel_version": system_info.get("kernel"),
        "rootfs_type": system_info.get("rootfs_type"),
    }


def _count_interfaces(coordinator: WrtManagerCoordinator, router_host: str) -> Dict[str, Any]:
    """Count different types of network interfaces for the router."""
    if not coordinator.data or "interfaces" not in coordinator.data:
        return {}

    interfaces = coordinator.data.get("interfaces", {}).get(router_host, {})

    interface_counts = {
        "total_interfaces": len(interfaces),
        "wireless_radios": 0,
        "ethernet_interfaces": 0,
        "other_interfaces": 0,
    }

    for interface_name, interface_data in interfaces.items():
        if isinstance(interface_data, dict):
            if "interfaces" in interface_data:
                # This is a wireless radio
                interface_counts["wireless_radios"] += 1
            elif interface_data.get("type") == "ethernet":
                interface_counts["ethernet_interfaces"] += 1
            else:
                interface_counts["other_interfaces"] += 1

    return interface_counts
