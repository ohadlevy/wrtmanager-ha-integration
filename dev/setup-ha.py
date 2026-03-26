#!/usr/bin/env python3
"""Programmatic HA onboarding and wrtmanager integration setup.

Automates:
1. HA onboarding (create user, set location, etc.)
2. Adding the wrtmanager integration with mock router configs

Idempotent - skips steps that are already done.

Usage:
    python dev/setup-ha.py --ha-url http://localhost:18123 --mock-port-file /tmp/mock-ports.json
    python dev/setup-ha.py --state-file .ha-test-state.json
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
_LOGGER = logging.getLogger("setup-ha")

DEFAULT_USER = "wrt"
DEFAULT_PASSWORD = "wrt-test-123"
DEFAULT_NAME = "WRT Test"


def api_request(
    url: str, data: dict | None = None, token: str | None = None, method: str = "POST"
) -> dict | None:
    """Make an HTTP request to HA API."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req, timeout=30) as resp:
            response_text = resp.read().decode()
            if response_text:
                return json.loads(response_text)
            return {}
    except HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        _LOGGER.debug("HTTP %d from %s: %s", e.code, url, body_text)
        if e.code == 400:
            # Often means "already done" for onboarding
            return None
        raise
    except URLError as e:
        _LOGGER.error("Connection failed to %s: %s", url, e)
        raise


def check_onboarding_needed(ha_url: str) -> bool:
    """Check if HA needs onboarding."""
    try:
        req = Request(f"{ha_url}/api/onboarding", method="GET")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            # Returns list of steps; if user step is not done, onboarding is needed
            if isinstance(data, list):
                for step in data:
                    if (
                        isinstance(step, dict)
                        and step.get("step") == "user"
                        and not step.get("done", False)
                    ):
                        _LOGGER.info("Onboarding needed (user step not done)")
                        return True
                _LOGGER.info("Onboarding not needed (user step done)")
                return False
            return True
    except HTTPError as e:
        if e.code == 404:
            return False  # Onboarding already done (endpoint removed)
        raise


def onboard_ha(ha_url: str) -> str | None:
    """Complete HA onboarding and return auth token."""
    _LOGGER.info("Starting HA onboarding...")

    # Step 1: Create user
    _LOGGER.info("Creating user '%s'...", DEFAULT_USER)
    result = api_request(
        f"{ha_url}/api/onboarding/users",
        {
            "client_id": ha_url,
            "name": DEFAULT_NAME,
            "username": DEFAULT_USER,
            "password": DEFAULT_PASSWORD,
            "language": "en",
        },
    )

    if result is None:
        _LOGGER.info("User creation returned None - may already exist")
        # Try to get token via auth
        return get_auth_token(ha_url)

    auth_code = result.get("auth_code")
    if not auth_code:
        _LOGGER.error("No auth_code in onboarding response: %s", result)
        return None

    # Exchange auth code for token
    token = exchange_auth_code(ha_url, auth_code)
    if not token:
        return None

    # Step 2: Set core config (skip analytics, etc.)
    _LOGGER.info("Setting core config...")
    try:
        api_request(f"{ha_url}/api/onboarding/core_config", {}, token=token)
    except Exception:
        _LOGGER.debug("Core config step failed (may be already done)")

    # Step 3: Skip analytics
    try:
        api_request(f"{ha_url}/api/onboarding/analytics", {}, token=token)
    except Exception:
        _LOGGER.debug("Analytics step failed (may be already done)")

    # Step 4: Skip integration discovery
    try:
        api_request(
            f"{ha_url}/api/onboarding/integration",
            {
                "client_id": ha_url,
                "redirect_uri": f"{ha_url}/onboarding.html",
            },
            token=token,
        )
    except Exception:
        _LOGGER.debug("Integration step failed (may be already done)")

    _LOGGER.info("Onboarding complete")
    return token


def exchange_auth_code(ha_url: str, auth_code: str) -> str | None:
    """Exchange auth code for access token."""
    data = f"grant_type=authorization_code&code={auth_code}&client_id={ha_url}".encode()
    req = Request(
        f"{ha_url}/auth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            access_token = result.get("access_token")
            if access_token:
                _LOGGER.info("Got access token")

                # Try to create a long-lived token (works on HA 2024.2+)
                try:
                    ll_req = Request(
                        f"{ha_url}/auth/long_lived_access_token",
                        data=json.dumps({"client_name": "wrt-e2e-test", "lifespan": 365}).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {access_token}",
                        },
                        method="POST",
                    )
                    with urlopen(ll_req, timeout=10) as ll_resp:
                        ll_token = json.loads(ll_resp.read().decode())
                        if isinstance(ll_token, str):
                            _LOGGER.info("Created long-lived access token")
                            return ll_token
                except Exception:
                    _LOGGER.debug("Long-lived token creation not available, using regular token")

                return access_token
    except Exception as e:
        _LOGGER.error("Token exchange failed: %s", e)
    return None


def get_auth_token(ha_url: str) -> str | None:
    """Try to authenticate with default credentials."""
    # Use HA auth flow
    data = (
        f"grant_type=password&username={DEFAULT_USER}"
        f"&password={DEFAULT_PASSWORD}&client_id={ha_url}"
    ).encode()
    req = Request(
        f"{ha_url}/auth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("access_token")
    except HTTPError as e:
        _LOGGER.error("Auth failed (HTTP %d) - HA may need onboarding", e.code)
        return None


def check_integration_exists(ha_url: str, token: str) -> bool:
    """Check if wrtmanager integration is already configured."""
    try:
        result = api_request(f"{ha_url}/api/config/config_entries/entry", method="GET", token=token)
        if isinstance(result, list):
            return any(entry.get("domain") == "wrtmanager" for entry in result)
    except Exception:
        pass
    return False


def add_wrtmanager_integration(ha_url: str, token: str, router_configs: list[dict]) -> bool:
    """Add wrtmanager integration via config flow.

    The config flow is multi-step:
    1. 'user' step: add one router (host, name, username, password)
    2. 'add_more' step: add_more=True to add another, False to finish
    3. Repeat for each router
    """
    _LOGGER.info("Adding wrtmanager integration with %d routers...", len(router_configs))

    # Start config flow
    result = api_request(
        f"{ha_url}/api/config/config_entries/flow",
        {"handler": "wrtmanager"},
        token=token,
    )

    if not result:
        _LOGGER.error("Failed to start config flow")
        return False

    flow_id = result.get("flow_id")
    step_id = result.get("step_id")
    _LOGGER.info("Config flow started: flow_id=%s, step_id=%s", flow_id, step_id)

    for i, rc in enumerate(router_configs):
        is_last = i == len(router_configs) - 1

        # Step: add router details
        _LOGGER.info(
            "Adding router %d/%d: %s (%s)", i + 1, len(router_configs), rc["name"], rc["host"]
        )
        result = api_request(
            f"{ha_url}/api/config/config_entries/flow/{flow_id}",
            {
                "host": rc["host"],
                "name": rc["name"],
                "username": rc.get("username", "hass"),
                "password": rc.get("password", "testing"),
            },
            token=token,
            method="POST",
        )

        if not result:
            _LOGGER.error("Config flow returned None for router %s", rc["name"])
            return False

        if result.get("type") == "create_entry":
            _LOGGER.info("Integration created: %s", result.get("title"))
            return True

        if result.get("errors"):
            _LOGGER.error("Config flow error for router %s: %s", rc["name"], result.get("errors"))
            return False

        # Should be on 'add_more' step now
        if result.get("step_id") == "add_more":
            result = api_request(
                f"{ha_url}/api/config/config_entries/flow/{flow_id}",
                {"add_more": not is_last},
                token=token,
                method="POST",
            )

            if not result:
                _LOGGER.error("add_more step returned None")
                return False

            if result.get("type") == "create_entry":
                _LOGGER.info("Integration created: %s", result.get("title"))
                return True

            # If add_more=True, should be back on 'user' step
            if not is_last and result.get("step_id") != "user":
                _LOGGER.error("Expected 'user' step after add_more, got: %s", result.get("step_id"))
                return False

    _LOGGER.error("Config flow did not complete after all routers")
    return False


def wait_for_ha(ha_url: str, timeout: int = 180):
    """Wait for HA to be accessible."""
    _LOGGER.info("Waiting for HA at %s...", ha_url)
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Use onboarding endpoint - it works before and after onboarding
            req = Request(f"{ha_url}/api/onboarding", method="GET")
            with urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    _LOGGER.info("HA is ready (onboarding endpoint reachable)")
                    return True
        except HTTPError as e:
            # 404 = onboarding done, HA is ready
            if e.code == 404:
                _LOGGER.info("HA is ready (onboarding already complete)")
                return True
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError(f"HA not ready after {timeout}s")


def setup_lovelace_dashboard(ha_url: str, token: str) -> bool:
    """Create a Lovelace dashboard with all wrtmanager cards via websocket API."""
    try:
        import aiohttp
    except ImportError:
        _LOGGER.warning("aiohttp not available, skipping dashboard setup")
        return False

    async def _setup():
        ws_url = ha_url.replace("http://", "ws://").replace("https://", "wss://")
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"{ws_url}/api/websocket") as ws:
                await ws.receive_json()  # auth_required
                await ws.send_json({"type": "auth", "access_token": token})
                auth_msg = await ws.receive_json()
                if auth_msg.get("type") != "auth_ok":
                    _LOGGER.error("Websocket auth failed: %s", auth_msg)
                    return False

                # Check if dashboard already has cards
                await ws.send_json({"id": 1, "type": "lovelace/config"})
                config_msg = await ws.receive_json()
                if config_msg.get("success") and config_msg.get("result"):
                    views = config_msg["result"].get("views", [])
                    views_json = json.dumps(views)
                    if (
                        "custom:router-health-card" in views_json
                        and "custom:interface-health-card" in views_json
                        and "custom:wifi-networks-card" in views_json
                    ):
                        _LOGGER.info("Lovelace dashboard already configured")
                        return True

                # Create dashboard with all wrtmanager cards
                await ws.send_json(
                    {
                        "id": 2,
                        "type": "lovelace/config/save",
                        "config": {
                            "title": "WrtManager",
                            "views": [
                                {
                                    "title": "Network Overview",
                                    "path": "network",
                                    "cards": [
                                        {"type": "custom:router-health-card"},
                                        {"type": "custom:network-devices-card"},
                                        {"type": "custom:network-topology-card"},
                                        {"type": "custom:signal-heatmap-card"},
                                        {"type": "custom:roaming-activity-card"},
                                        {"type": "custom:interface-health-card"},
                                        {"type": "custom:wifi-networks-card"},
                                    ],
                                }
                            ],
                        },
                    }
                )
                result = await ws.receive_json()
                if result.get("success"):
                    _LOGGER.info("Lovelace dashboard created with 7 wrtmanager cards")
                    return True
                _LOGGER.error("Dashboard creation failed: %s", result)
                return False

    try:
        return asyncio.run(_setup())
    except Exception as e:
        _LOGGER.warning("Dashboard setup failed: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Setup HA for E2E testing")
    parser.add_argument("--ha-url", help="HA base URL (e.g., http://localhost:18123)")
    parser.add_argument("--mock-port-file", help="Path to mock server port mapping JSON")
    parser.add_argument(
        "--state-file", help="Path to ha-env state file (provides ha-url and mock-port-file)"
    )
    parser.add_argument(
        "--router-hosts",
        help="Comma-separated router host:port pairs (alternative to mock-port-file)",
    )
    parser.add_argument(
        "--skip-onboarding", action="store_true", help="Skip onboarding (HA already set up)"
    )
    parser.add_argument("--token-file", help="Write access token to this file")
    args = parser.parse_args()

    # Load from state file if provided
    if args.state_file:
        with open(args.state_file) as f:
            state = json.load(f)
        ha_url = state["ha_url"]
        mock_port_file = state.get("mock_port_file") or args.mock_port_file
    else:
        ha_url = args.ha_url
        mock_port_file = args.mock_port_file

    if not ha_url:
        _LOGGER.error("--ha-url or --state-file required")
        sys.exit(1)

    # Determine router configs
    router_configs = []
    if mock_port_file:
        with open(mock_port_file) as f:
            mock_data = json.load(f)
        router_configs = mock_data.get("routers", [])
    elif args.router_hosts:
        for host in args.router_hosts.split(","):
            router_configs.append(
                {
                    "host": host.strip(),
                    "name": f"Router {host.strip()}",
                    "username": "hass",
                    "password": "testing",
                }
            )

    if not router_configs:
        _LOGGER.error("No router configs - provide --mock-port-file or --router-hosts")
        sys.exit(1)

    # Wait for HA
    wait_for_ha(ha_url)

    # Onboard if needed
    token = None
    if not args.skip_onboarding:
        needs_onboarding = check_onboarding_needed(ha_url)
        if needs_onboarding:
            token = onboard_ha(ha_url)
        else:
            _LOGGER.info("HA already onboarded, getting auth token")
            token = get_auth_token(ha_url)
    else:
        token = get_auth_token(ha_url)

    if not token:
        _LOGGER.error("Failed to get auth token")
        sys.exit(1)

    # Save token
    if args.token_file:
        Path(args.token_file).write_text(token)
        _LOGGER.info("Token saved to %s", args.token_file)

    # Add integration if not already present
    if check_integration_exists(ha_url, token):
        _LOGGER.info("wrtmanager integration already configured")
    else:
        success = add_wrtmanager_integration(ha_url, token, router_configs)
        if not success:
            _LOGGER.error("Failed to add wrtmanager integration")
            sys.exit(1)

    # Setup Lovelace dashboard (wait a moment for integration entities to load)
    time.sleep(3)
    setup_lovelace_dashboard(ha_url, token)

    _LOGGER.info("HA setup complete!")
    _LOGGER.info("  URL: %s", ha_url)
    _LOGGER.info("  User: %s / %s", DEFAULT_USER, DEFAULT_PASSWORD)
    _LOGGER.info("  Routers: %d configured", len(router_configs))

    # Output token to stdout for scripts
    print(f"TOKEN={token}")


if __name__ == "__main__":
    main()
