"""HTTP ubus client for OpenWrt routers."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
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
    """Client for communicating with OpenWrt ubus over HTTP/HTTPS."""

    def __init__(
        self,
        host: str,
        username: str = "hass",
        password: str = "",  # nosec B107
        timeout: int = 10,
        use_https: bool = False,
        verify_ssl: bool = False,
    ) -> None:
        """Initialize the ubus client."""
        self.host = host
        self.username = username
        self.password = password
        self.timeout = timeout
        self.use_https = use_https
        self.verify_ssl = verify_ssl
        protocol = "https" if use_https else "http"
        self.base_url = f"{protocol}://{host}/ubus"
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
            _LOGGER.debug("Authentication response for %s: %s", self.host, response_data)

            result = response_data.get("result", [])
            if not isinstance(result, list) or len(result) == 0:
                _LOGGER.error(
                    "Unexpected authentication response format for %s: %s", self.host, response_data
                )
                raise UbusAuthenticationError(
                    f"Invalid response format: expected list with elements, got {result}"
                )

            # Handle different ubus response formats
            if len(result) == 1:
                # Single element response is usually an error code
                error_code = result[0]
                error_messages = {
                    1: "Invalid command",
                    2: "Invalid argument",
                    3: "Method not found",
                    4: "Not found",
                    5: "No data",
                    6: "Permission denied - check username/password and ACL permissions",
                    7: "Timeout",
                    8: "Not supported",
                }
                error_msg = error_messages.get(error_code, f"Unknown error code {error_code}")
                _LOGGER.error(
                    "Authentication failed for %s: %s (error code %s)",
                    self.host,
                    error_msg,
                    error_code,
                )
                raise UbusAuthenticationError(f"Authentication failed: {error_msg}")

            elif len(result) >= 2:
                # Standard ubus response: [status_code, data]
                status_code, auth_data = result[0], result[1]

                if status_code != 0:
                    _LOGGER.error(
                        "Authentication failed for %s with status code %s", self.host, status_code
                    )
                    raise UbusAuthenticationError(
                        f"Authentication failed with status code {status_code}"
                    )

                if not isinstance(auth_data, dict):
                    _LOGGER.error(
                        "Authentication data is not a dictionary for %s: %s", self.host, auth_data
                    )
                    raise UbusAuthenticationError(f"Invalid auth data format: {auth_data}")

                session_id = auth_data.get("ubus_rpc_session")
            else:
                _LOGGER.error("Unexpected result length for %s: %s", self.host, result)
                raise UbusAuthenticationError(f"Unexpected response format: {result}")

            if session_id:
                _LOGGER.debug("Successfully authenticated with %s", self.host)
                return session_id
            else:
                _LOGGER.error("Authentication failed for %s: No session ID in response", self.host)
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
            "id": secrets.randbelow(900) + 100,
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
                        "ubus call %s.%s failed with status %s "
                        "(common codes: 1=Invalid command, 2=Invalid argument, "
                        "3=Method not found, 4=Not found, 6=Permission denied)",
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
                        "ubus call %s.%s failed with error code %s "
                        "(common codes: 1=Invalid command, 2=Invalid argument, "
                        "3=Method not found, 4=Not found, 6=Permission denied)",
                        service,
                        method,
                        error_code,
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
        """Get DHCP lease information using best available method."""
        # First try luci-rpc method (more reliable when available)
        _LOGGER.debug("Trying luci-rpc.getDHCPLeases on %s", self.host)
        result = await self.call_ubus(session_id, "luci-rpc", "getDHCPLeases", {"family": 4})

        if result and "dhcp_leases" in result:
            _LOGGER.debug(
                "Successfully got DHCP leases via luci-rpc from %s: %d leases",
                self.host,
                len(result["dhcp_leases"]),
            )
            return result

        # Fallback to standard dhcp method
        _LOGGER.debug("luci-rpc failed, trying dhcp.ipv4leases on %s", self.host)
        fallback_result = await self.call_ubus(session_id, "dhcp", "ipv4leases", {})

        if fallback_result and "device" in fallback_result:
            _LOGGER.debug("Successfully got DHCP leases via dhcp.ipv4leases from %s", self.host)
            return fallback_result

        _LOGGER.debug("No DHCP lease data available from %s", self.host)
        return None

    async def get_static_dhcp_hosts(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get static DHCP host configurations."""
        _LOGGER.debug("Calling ubus uci.get for DHCP hosts on %s", self.host)
        result = await self.call_ubus(session_id, "uci", "get", {"config": "dhcp", "type": "host"})
        _LOGGER.debug("Static DHCP hosts ubus call result on %s: %s", self.host, result)
        return result if result else None

    async def get_system_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get system information."""
        result = await self.call_ubus(session_id, "system", "info", {})
        return result if result else None

    def _create_ssl_context(self):
        """Create SSL context in a thread-safe manner."""
        import ssl

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    async def _make_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP/HTTPS request to ubus endpoint."""
        if not self._session:
            # Create SSL context for HTTPS connections
            connector = None
            if self.use_https and not self.verify_ssl:
                # Disable SSL verification for self-signed certificates
                ssl_context = self._create_ssl_context()
                connector = aiohttp.TCPConnector(ssl=ssl_context)

            self._session = aiohttp.ClientSession(connector=connector)

        try:
            async with async_timeout.timeout(self.timeout):
                async with self._session.post(
                    self.base_url,
                    json=data,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if response.status == 403:
                            error_msg = (
                                f"HTTP 403 Forbidden - Check if 'hass' user has "
                                f"proper ACL permissions on {self.host}"
                            )
                        elif response.status == 404:
                            error_msg = (
                                f"HTTP 404 Not Found - ubus endpoint not available on {self.host}"
                            )
                        elif response.status == 401:
                            error_msg = (
                                f"HTTP 401 Unauthorized - Authentication failed for {self.host}"
                            )
                        else:
                            error_msg = f"HTTP {response.status}: {error_text}"
                        raise UbusConnectionError(error_msg)

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
            # Store connector reference before closing session
            connector = self._session.connector
            await self._session.close()

            # Properly close connector if it exists
            if connector and not connector.closed:
                await connector.close()

            # Give time for internal threads to cleanup (needed for CI environments)
            await asyncio.sleep(0.25)
            self._session = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        # Give extra time for aiohttp background tasks
        await asyncio.sleep(0.01)
