"""HTTP ubus client for OpenWrt routers."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)


class UbusClientError(Exception):
    """Base exception for ubus client."""


class UbusAuthenticationError(UbusClientError):
    """Authentication failed."""


class UbusTimeoutError(UbusClientError):
    """Request timed out."""


class UbusConnectionError(UbusClientError):
    """Connection failed."""


class UbusClient:
    """Client for communicating with OpenWrt ubus over HTTP."""

    def __init__(
        self,
        host: str,
        username: str = "hass",
        password: str = "",
        timeout: int = 10,
    ) -> None:
        """Initialize the ubus client."""
        self.host = host
        self.username = username
        self.password = password
        self.timeout = timeout
        self.base_url = f"http://{host}/ubus"
        self._session: Optional[aiohttp.ClientSession] = None

    async def authenticate(self) -> Optional[str]:
        """Authenticate with the router and return session ID."""
        login_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call",
            "params": [
                "00000000000000000000000000000000",
                "session",
                "login",
                {"username": self.username, "password": self.password},
            ],
        }

        try:
            response_data = await self._make_request(login_request)
            session_id = response_data.get("result", [None, {}])[1].get("ubus_rpc_session")

            if session_id:
                _LOGGER.debug("Successfully authenticated with %s", self.host)
                return session_id
            else:
                _LOGGER.error("Authentication failed for %s", self.host)
                raise UbusAuthenticationError("No session ID returned")

        except Exception as ex:
            _LOGGER.error("Authentication error for %s: %s", self.host, ex)
            raise UbusAuthenticationError(f"Authentication failed: {ex}")

    async def call_ubus(
        self, session_id: str, service: str, method: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Make a ubus call and return the result."""
        request_data = {
            "jsonrpc": "2.0",
            "id": random.randint(100, 999),
            "method": "call",
            "params": [session_id, service, method, params],
        }

        try:
            response_data = await self._make_request(request_data)
            result = response_data.get("result")

            if result and len(result) >= 2:
                status_code = result[0]
                if status_code == 0:
                    return result[1]  # Return the data part
                else:
                    _LOGGER.warning(
                        "ubus call %s.%s failed with status %s",
                        service,
                        method,
                        status_code,
                    )
                    return None
            elif result and len(result) == 1:
                # Single element result is usually an error code
                error_code = result[0]
                if error_code == 6:
                    # Permission denied - common for dump APs
                    _LOGGER.debug(
                        "ubus call %s.%s: permission denied (code 6) - normal for dump APs",
                        service,
                        method,
                    )
                    return None
                else:
                    _LOGGER.warning(
                        "ubus call %s.%s failed with error code %s", service, method, error_code
                    )
                    return None
            else:
                # Check for common errors that aren't really errors
                if "error" in response_data and response_data["error"].get("code") == -32000:
                    # "Object not found" - normal for dump APs and missing services
                    _LOGGER.debug(
                        "ubus object/method not available: %s",
                        response_data["error"].get("message", "Unknown"),
                    )
                    return None
                else:
                    _LOGGER.debug("Unexpected ubus response format: %s", response_data)
                    return None

        except Exception as ex:
            _LOGGER.error("ubus call %s.%s failed: %s", service, method, ex)
            return None

    async def get_wireless_devices(self, session_id: str) -> Optional[List[str]]:
        """Get list of wireless interfaces."""
        result = await self.call_ubus(session_id, "iwinfo", "devices", {})
        return result.get("devices", []) if result else None

    async def get_device_associations(
        self, session_id: str, interface: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Get associated devices for a wireless interface."""
        result = await self.call_ubus(session_id, "iwinfo", "assoclist", {"device": interface})
        return result.get("results", []) if result else None

    async def get_dhcp_leases(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get DHCP lease information."""
        result = await self.call_ubus(session_id, "dhcp", "ipv4leases", {})
        return result if result else None

    async def get_static_dhcp_hosts(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get static DHCP host configurations."""
        result = await self.call_ubus(session_id, "uci", "get", {"config": "dhcp", "type": "host"})
        return result if result else None

    async def get_system_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get system information."""
        result = await self.call_ubus(session_id, "system", "info", {})
        return result if result else None

    async def _make_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP request to ubus endpoint."""
        if not self._session:
            self._session = aiohttp.ClientSession()

        try:
            async with async_timeout.timeout(self.timeout):
                async with self._session.post(
                    self.base_url,
                    json=data,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status != 200:
                        raise UbusConnectionError(
                            f"HTTP {response.status}: {await response.text()}"
                        )

                    response_text = await response.text()
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError as ex:
                        raise UbusConnectionError(f"Invalid JSON response: {ex}")

        except asyncio.TimeoutError:
            raise UbusTimeoutError(f"Request timeout after {self.timeout} seconds")
        except aiohttp.ClientError as ex:
            raise UbusConnectionError(f"Connection error: {ex}")

    async def get_network_interfaces(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get network interface information."""
        result = await self.call_ubus(session_id, "network.device", "status", {})
        return result if result else None

    async def get_wireless_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get wireless interface status."""
        result = await self.call_ubus(session_id, "network.wireless", "status", {})
        return result if result else None

    async def get_system_board(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get system board information."""
        result = await self.call_ubus(session_id, "system", "board", {})
        return result if result else None

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
