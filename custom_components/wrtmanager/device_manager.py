"""Device identification and management for WrtManager."""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

import aiofiles
import aiohttp

from .const import (
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

_LOGGER = logging.getLogger(__name__)


class DeviceManager:
    """Manage device identification and tracking."""

    # Custom device type database for specific device type classification
    DEVICE_TYPE_DATABASE = {
        # IoT Switches (Shelly)
        "A4:CF:12": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "2C:F4:32": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "EC:FA:BC": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "C8:47:8C": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "68:C6:3A": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "98:F4:AB": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "3C:61:05": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "54:32:04": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "E8:DB:84": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "DC:4F:22": {"vendor": "Shelly", "device_type": DEVICE_TYPE_IOT_SWITCH},
        # Air Conditioners (Gree)
        "A0:92:08": {"vendor": "Gree", "device_type": DEVICE_TYPE_HOME_APPLIANCE},
        "CC:8C:BF": {"vendor": "Gree", "device_type": DEVICE_TYPE_HOME_APPLIANCE},
        "1C:90:FF": {"vendor": "Gree", "device_type": DEVICE_TYPE_HOME_APPLIANCE},
        # Robot Vacuums
        "28:B7:7C": {"vendor": "Dreame", "device_type": DEVICE_TYPE_ROBOT_VACUUM},
        # Vehicles
        "4C:FC:AA": {"vendor": "Tesla", "device_type": DEVICE_TYPE_VEHICLE},
        # Smart Speakers (Sonos)
        "94:9F:3E": {"vendor": "Sonos", "device_type": DEVICE_TYPE_SMART_SPEAKER},
        "00:0E:58": {"vendor": "Sonos", "device_type": DEVICE_TYPE_SMART_SPEAKER},
        "5C:AA:FD": {"vendor": "Sonos", "device_type": DEVICE_TYPE_SMART_SPEAKER},
        "B8:E9:37": {"vendor": "Sonos", "device_type": DEVICE_TYPE_SMART_SPEAKER},
        # Single Board Computers (Raspberry Pi)
        "B8:27:EB": {"vendor": "Raspberry Pi", "device_type": DEVICE_TYPE_COMPUTER},
        "DC:A6:32": {"vendor": "Raspberry Pi", "device_type": DEVICE_TYPE_COMPUTER},
        "E4:5F:01": {"vendor": "Raspberry Pi", "device_type": DEVICE_TYPE_COMPUTER},
        # ESP devices (IoT/DIY)
        "30:AE:A4": {"vendor": "Espressif", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "24:0A:C4": {"vendor": "Espressif", "device_type": DEVICE_TYPE_IOT_SWITCH},
        "7C:9E:BD": {"vendor": "Espressif", "device_type": DEVICE_TYPE_IOT_SWITCH},
    }

    def __init__(self) -> None:
        """Initialize device manager."""
        self._oui_cache: Dict[str, str] = {}
        self._oui_database_path: Optional[str] = None

    def identify_device(self, mac: str) -> Optional[Dict[str, str]]:
        """Identify device by MAC address."""
        if not mac:
            return None

        oui = mac[:8].upper()  # First 3 bytes: "A4:CF:12"

        # Try custom database first
        if oui in self.DEVICE_TYPE_DATABASE:
            device_info = self.DEVICE_TYPE_DATABASE[oui].copy()
            device_info["device_name"] = self._generate_device_name(
                device_info["vendor"], device_info["device_type"], mac
            )
            return device_info

        # Fall back to public OUI lookup
        vendor = self._lookup_oui_vendor(oui)
        if vendor:
            device_type = self._infer_device_type_from_vendor(vendor)
            return {
                "vendor": vendor,
                "device_type": device_type,
                "device_name": self._generate_device_name(vendor, device_type, mac),
            }

        return None

    def _lookup_oui_vendor(self, oui: str) -> Optional[str]:
        """Look up vendor name from OUI database."""
        # Check cache first
        if oui in self._oui_cache:
            return self._oui_cache[oui]

        vendor = self._lookup_oui_from_file(oui)
        if vendor:
            self._oui_cache[oui] = vendor
            return vendor

        return None

    def _lookup_oui_from_file(self, oui: str) -> Optional[str]:
        """Look up OUI from local database file (disabled to prevent blocking I/O)."""
        # TODO: Implement async file reading or pre-load OUI database during startup
        # Disabled to prevent blocking the event loop - return None immediately
        return None

    def _infer_device_type_from_vendor(self, vendor: str) -> str:
        """Infer device type based on vendor name patterns."""
        vendor_lower = vendor.lower()

        # Mobile devices
        if any(
            keyword in vendor_lower
            for keyword in [
                "apple",
                "samsung",
                "huawei",
                "oneplus",
                "xiaomi",
                "oppo",
                "vivo",
                "google",
                "motorola",
                "lg electronics",
            ]
        ):
            return DEVICE_TYPE_MOBILE

        # IoT and smart home
        if any(
            keyword in vendor_lower for keyword in ["shelly", "sonoff", "tasmota", "esp", "tuya"]
        ):
            return DEVICE_TYPE_IOT_SWITCH

        # Vehicles
        if any(
            keyword in vendor_lower
            for keyword in ["tesla", "bmw", "audi", "mercedes", "ford", "toyota"]
        ):
            return DEVICE_TYPE_VEHICLE

        # Printers
        if any(
            keyword in vendor_lower for keyword in ["brother", "canon", "hp", "epson", "lexmark"]
        ):
            return DEVICE_TYPE_PRINTER

        # Computers
        if any(
            keyword in vendor_lower
            for keyword in [
                "raspberry",
                "intel",
                "amd",
                "nvidia",
                "dell",
                "hp inc",
                "lenovo",
                "asus",
                "msi",
                "microsoft",
            ]
        ):
            return DEVICE_TYPE_COMPUTER

        # Smart speakers
        if any(keyword in vendor_lower for keyword in ["sonos", "bose", "jbl", "harman"]):
            return DEVICE_TYPE_SMART_SPEAKER

        # Home appliances
        if any(
            keyword in vendor_lower
            for keyword in [
                "lg",
                "sony",
                "panasonic",
                "philips",
                "toshiba",
                "gree",
                "mitsubishi",
                "daikin",
                "carrier",
            ]
        ):
            return DEVICE_TYPE_HOME_APPLIANCE

        # Network bridges (specific bridge devices)
        if any(
            keyword in vendor_lower
            for keyword in [
                "bridge",
                "hub",
                "switch",
            ]
        ):
            return DEVICE_TYPE_BRIDGE

        # Network equipment
        if any(
            keyword in vendor_lower
            for keyword in [
                "tp-link",
                "netgear",
                "linksys",
                "cisco",
                "ubiquiti",
                "mikrotik",
                "d-link",
                "asus",
            ]
        ):
            return DEVICE_TYPE_NETWORK_EQUIPMENT

        # Robot vacuums
        if any(keyword in vendor_lower for keyword in ["dreame", "roborock", "irobot", "xiaomi"]):
            return DEVICE_TYPE_ROBOT_VACUUM

        return DEVICE_TYPE_UNKNOWN

    def _generate_device_name(self, vendor: str, device_type: str, mac: str) -> str:
        """Generate a friendly device name."""
        mac_suffix = mac[-8:].replace(":", "")  # Last 4 hex chars

        if device_type == DEVICE_TYPE_IOT_SWITCH:
            return f"{vendor} Switch-{mac_suffix}"
        elif device_type == DEVICE_TYPE_MOBILE:
            return f"{vendor} Phone-{mac_suffix}"
        elif device_type == DEVICE_TYPE_COMPUTER:
            return f"{vendor} Computer-{mac_suffix}"
        elif device_type == DEVICE_TYPE_SMART_SPEAKER:
            return f"{vendor} Speaker-{mac_suffix}"
        elif device_type == DEVICE_TYPE_HOME_APPLIANCE:
            return f"{vendor} Appliance-{mac_suffix}"
        elif device_type == DEVICE_TYPE_VEHICLE:
            return f"{vendor} Vehicle-{mac_suffix}"
        elif device_type == DEVICE_TYPE_PRINTER:
            return f"{vendor} Printer-{mac_suffix}"
        elif device_type == DEVICE_TYPE_ROBOT_VACUUM:
            return f"{vendor} Vacuum-{mac_suffix}"
        elif device_type == DEVICE_TYPE_NETWORK_EQUIPMENT:
            return f"{vendor} Network-{mac_suffix}"
        elif device_type == DEVICE_TYPE_BRIDGE:
            return f"{vendor} Bridge-{mac_suffix}"
        else:
            return f"{vendor} Device-{mac_suffix}"

    async def download_oui_database(self, target_dir: str) -> bool:
        """Download the latest OUI database from nmap repository."""
        try:
            url = "https://raw.githubusercontent.com/nmap/nmap/master/nmap-mac-prefixes"
            target_path = os.path.join(target_dir, "nmap-mac-prefixes")

            _LOGGER.info("Downloading OUI database from %s", url)

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        content = await response.text()
                        async with aiofiles.open(target_path, "w", encoding="utf-8") as file:
                            await file.write(content)

                        self._oui_database_path = target_path
                        _LOGGER.info(
                            "Downloaded OUI database (%d bytes) to %s",
                            len(content),
                            target_path,
                        )
                        return True
                    else:
                        _LOGGER.error("Failed to download OUI database: HTTP %d", response.status)
                        return False

        except Exception as ex:
            _LOGGER.error("Error downloading OUI database: %s", ex)
            return False
