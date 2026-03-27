"""E2E test fixtures - connects to a running HA instance."""

import os

import pytest

HA_URL = os.environ.get("HA_URL", "http://localhost:18123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")


def ha_api_request(path: str, method: str = "GET", data: dict | None = None) -> dict:
    """Make request to HA REST API."""
    import json
    from urllib.request import Request, urlopen

    url = f"{HA_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {HA_TOKEN}",
    }
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)

    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


@pytest.fixture
def ha_url():
    return HA_URL


@pytest.fixture
def ha_token():
    return HA_TOKEN


@pytest.fixture
def ha_api():
    """Return a callable for HA API requests."""
    return ha_api_request


@pytest.fixture
def ha_states(ha_api, socket_enabled):
    """Get all entity states from HA."""
    return ha_api("/api/states")


@pytest.fixture
def ha_config_entries(ha_api, socket_enabled):
    """Get all config entries."""
    return ha_api("/api/config/config_entries/entry")
