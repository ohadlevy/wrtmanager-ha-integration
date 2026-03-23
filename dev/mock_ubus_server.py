#!/usr/bin/env python3
"""Mock ubus server that simulates OpenWrt routers for E2E testing.

Implements the ubus JSON-RPC protocol over HTTP, supporting authentication,
wireless device queries, DHCP leases, system info, and more.

Supports time-varying scenarios where devices roam, connect, and disconnect.

Usage:
    # Start servers for all routers in a scenario
    python dev/mock_ubus_server.py --scenario dev/scenarios/default.json --base-port 18001

    # Start and print the port mapping (for scripts to consume)
    python dev/mock_ubus_server.py \
        --scenario dev/scenarios/default.json --base-port 18001 --print-ports
"""

import argparse
import asyncio
import copy
import json
import logging
import os
import secrets
import signal
import time
from pathlib import Path

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
_LOGGER = logging.getLogger("mock-ubus")


class MockRouter:
    """Simulates a single OpenWrt router's ubus interface."""

    def __init__(self, router_id: str, config: dict):
        self.router_id = router_id
        self.config = config
        self.name = config["name"]
        self.sessions: dict[str, float] = {}  # session_id -> expiry timestamp
        self.start_time = time.time()

        # Deep copy associations so time events can mutate them
        self.associations = copy.deepcopy(config.get("associations", {}))
        self.dhcp_leases = copy.deepcopy(config.get("dhcp_leases", []))
        self.extra_dhcp_leases: list[dict] = []

    def _valid_session(self, session_id: str) -> bool:
        if session_id == "00000000000000000000000000000000":
            return True  # Anonymous session for login
        expiry = self.sessions.get(session_id)
        if expiry is None:
            return False
        if time.time() > expiry:
            del self.sessions[session_id]
            return False
        return True

    def handle_request(self, data: dict) -> dict:
        """Process a ubus JSON-RPC request and return response."""
        request_id = data.get("id", 1)
        method = data.get("method")
        params = data.get("params", [])

        if method != "call" or len(params) < 4:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32600, "message": "Invalid request"},
            }

        session_id, service, ubus_method, call_params = params[0], params[1], params[2], params[3]

        # Handle login specially
        if service == "session" and ubus_method == "login":
            return self._handle_login(request_id, call_params)

        # Validate session
        if not self._valid_session(session_id):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32002, "message": "Access denied"},
            }

        # Route to handler
        handler = self._get_handler(service, ubus_method)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": "Object not found"},
            }

        result_data = handler(call_params)
        if result_data is None:
            return {"jsonrpc": "2.0", "id": request_id, "result": [0]}
        return {"jsonrpc": "2.0", "id": request_id, "result": [0, result_data]}

    def _handle_login(self, request_id: int, params: dict) -> dict:
        username = params.get("username", "")

        # Accept any credentials (test server)
        if username:
            session_id = secrets.token_hex(16)
            self.sessions[session_id] = time.time() + 300
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": [
                    0,
                    {
                        "ubus_rpc_session": session_id,
                        "timeout": 300,
                        "expires": 299,
                        "acls": {
                            "access-group": {username: ["read", "write"]},
                            "ubus": {
                                "dhcp": ["ipv4leases", "ipv6leases"],
                                "hostapd.*": ["get_clients", "del_client"],
                                "iwinfo": ["assoclist", "devices", "info"],
                                "luci-rpc": ["getDHCPLeases"],
                                "network.device": ["status"],
                                "network.wireless": ["status"],
                                "session": ["login", "access"],
                                "system": ["board", "info"],
                                "file": ["read"],
                                "uci": ["get"],
                            },
                        },
                        "data": {"username": username},
                    },
                ],
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": [6]}

    def _get_handler(self, service: str, method: str):
        handlers = {
            ("iwinfo", "devices"): self._handle_iwinfo_devices,
            ("iwinfo", "assoclist"): self._handle_iwinfo_assoclist,
            ("system", "info"): self._handle_system_info,
            ("system", "board"): self._handle_system_board,
            ("network.device", "status"): self._handle_network_device_status,
            ("network.wireless", "status"): self._handle_wireless_status,
            ("luci-rpc", "getDHCPLeases"): self._handle_dhcp_leases,
            ("dhcp", "ipv4leases"): self._handle_dhcp_ipv4leases,
            ("uci", "get"): self._handle_uci_get,
            ("file", "read"): self._handle_file_read,
        }

        # Handle hostapd.* wildcard
        if service.startswith("hostapd.") and method == "del_client":
            return self._handle_del_client

        return handlers.get((service, method))

    def _handle_iwinfo_devices(self, params: dict) -> dict:
        return {"devices": self.config.get("wireless_devices", [])}

    def _handle_iwinfo_assoclist(self, params: dict) -> dict:
        device = params.get("device", "")
        results = self.associations.get(device, [])
        return {"results": results}

    def _handle_system_info(self, params: dict) -> dict:
        info = copy.deepcopy(self.config.get("system_info", {}))
        elapsed = int(time.time() - self.start_time)

        # Update uptime dynamically
        info["uptime"] = info.get("uptime", 0) + elapsed

        # Vary memory realistically (±10% fluctuation around base)
        import math

        mem = info.get("memory", {})
        if mem:
            wave = math.sin(elapsed / 30.0)  # 30s cycle
            total = mem.get("total", 524288000)
            base_free = mem.get("free", 262144000)
            # Free memory fluctuates ±10% of total
            fluctuation = int(total * 0.10 * wave)
            mem["free"] = max(total // 10, base_free + fluctuation)
            mem["available"] = mem["free"] + mem.get("cached", 0)
            info["memory"] = mem

        # Vary load averages (sinusoidal around base values)
        load = info.get("load", [2048, 4096, 3072])
        if load:
            # Different frequencies for 1m/5m/15m
            info["load"] = [
                max(0, load[0] + int(2000 * math.sin(elapsed / 15.0))),
                max(0, load[1] + int(1500 * math.sin(elapsed / 45.0))),
                max(0, load[2] + int(1000 * math.sin(elapsed / 90.0))),
            ]

        return info

    def _handle_system_board(self, params: dict) -> dict:
        return self.config.get("system_board", {})

    def _handle_file_read(self, params: dict) -> dict:
        path = params.get("path", "")
        if path == "/proc/stat":
            # Return incrementing CPU counters so delta-based CPU usage can be computed
            elapsed = int(time.time() - self.start_time)
            # Simulate ~20% CPU usage: idle grows slower than total
            user = 1000 + elapsed * 20
            nice = 0
            system = 500 + elapsed * 5
            idle = 8000 + elapsed * 75
            iowait = 100 + elapsed * 2
            irq = 50
            softirq = 50
            proc_stat = (
                f"cpu  {user} {nice} {system} {idle} {iowait} {irq} {softirq} 0 0 0\n"
                f"cpu0 {user} {nice} {system} {idle} {iowait} {irq} {softirq} 0 0 0\n"
            )
            return {"data": proc_stat}
        return None

    def _handle_network_device_status(self, params: dict) -> dict:
        return self.config.get("network_device_status", {})

    def _handle_wireless_status(self, params: dict) -> dict:
        return self.config.get("wireless_status", {})

    def _handle_dhcp_leases(self, params: dict) -> dict | None:
        if not self.config.get("is_dhcp_server", False):
            return {"dhcp_leases": []}
        all_leases = self.dhcp_leases + self.extra_dhcp_leases
        return {"dhcp_leases": all_leases}

    def _handle_dhcp_ipv4leases(self, params: dict) -> dict | None:
        if not self.config.get("is_dhcp_server", False):
            return None
        all_leases = self.dhcp_leases + self.extra_dhcp_leases
        return {"device": {"leases": all_leases}}

    def _handle_uci_get(self, params: dict) -> dict | None:
        config_name = params.get("config")
        config_type = params.get("type")
        if config_name == "dhcp" and config_type == "host":
            if not self.config.get("is_dhcp_server", False):
                return None
            return self.config.get("static_dhcp_hosts", {})
        return None

    def _handle_del_client(self, params: dict) -> dict:
        mac = params.get("addr", "").upper()
        # Remove from associations
        for iface, devices in self.associations.items():
            self.associations[iface] = [d for d in devices if d.get("mac", "").upper() != mac]
        return {}

    # -- Mutation methods for time events --

    def add_device(self, interface: str, mac: str, signal: int, dhcp_lease: dict | None = None):
        if interface not in self.associations:
            self.associations[interface] = []
        self.associations[interface].append(
            {
                "mac": mac.upper(),
                "signal": signal,
                "rx": {"rate": 433300},
                "tx": {"rate": 433300},
            }
        )
        if dhcp_lease:
            self.extra_dhcp_leases.append(
                {
                    "macaddr": mac.upper(),
                    "ipaddr": dhcp_lease["ipaddr"],
                    "hostname": dhcp_lease.get("hostname", ""),
                    "expires": 43200,
                }
            )

    def remove_device(self, interface: str, mac: str):
        mac = mac.upper()
        if interface in self.associations:
            self.associations[interface] = [
                d for d in self.associations[interface] if d.get("mac", "").upper() != mac
            ]

    def update_signal(self, interface: str, mac: str, new_signal: int):
        mac = mac.upper()
        if interface in self.associations:
            for device in self.associations[interface]:
                if device.get("mac", "").upper() == mac:
                    device["signal"] = new_signal


class MockUbusServerManager:
    """Manages multiple mock router servers and time-based events."""

    def __init__(self, scenario_path: str, base_port: int):
        self.scenario_path = scenario_path
        self.base_port = base_port
        self.routers: dict[str, MockRouter] = {}
        self.router_ports: dict[str, int] = {}
        self.apps: list[web.Application] = []
        self.runners: list[web.AppRunner] = []
        self.time_events: list[dict] = []
        self._event_task: asyncio.Task | None = None

    def load_scenario(self):
        with open(self.scenario_path) as f:
            scenario = json.load(f)

        port = self.base_port
        for router_id, router_config in scenario.get("routers", {}).items():
            self.routers[router_id] = MockRouter(router_id, router_config)
            self.router_ports[router_id] = port
            port += 1

        self.time_events = scenario.get("time_events", [])
        _LOGGER.info(
            "Loaded scenario with %d routers, %d time events",
            len(self.routers),
            len(self.time_events),
        )

    def _create_app(self, router: MockRouter) -> web.Application:
        app = web.Application()

        async def handle_ubus(request: web.Request) -> web.Response:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                return web.json_response(
                    {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}},
                    status=400,
                )
            response = router.handle_request(data)
            return web.json_response(response)

        async def handle_health(request: web.Request) -> web.Response:
            return web.json_response(
                {"status": "ok", "router": router.router_id, "name": router.name}
            )

        app.router.add_post("/ubus", handle_ubus)
        app.router.add_get("/health", handle_health)
        return app

    async def _process_time_events(self):
        """Process time-based scenario events."""
        start = time.time()
        processed = set()

        while True:
            elapsed = time.time() - start
            for i, event in enumerate(self.time_events):
                if i in processed:
                    continue
                if elapsed >= event["at_seconds"]:
                    self._apply_event(event)
                    processed.add(i)
                    _LOGGER.info("Event at %ds: %s", event["at_seconds"], event["description"])

            if len(processed) == len(self.time_events):
                _LOGGER.info("All time events processed, looping scenario")
                # Reset and loop
                start = time.time()
                processed.clear()
                # Reload associations from scenario
                with open(self.scenario_path) as f:
                    scenario = json.load(f)
                for router_id, router_config in scenario.get("routers", {}).items():
                    if router_id in self.routers:
                        self.routers[router_id].associations = copy.deepcopy(
                            router_config.get("associations", {})
                        )
                        self.routers[router_id].extra_dhcp_leases.clear()

            await asyncio.sleep(1)

    def _apply_event(self, event: dict):
        action = event["action"]

        if action == "connect":
            router = self.routers.get(event["router"])
            if router:
                router.add_device(
                    event["interface"],
                    event["mac"],
                    event["signal"],
                    event.get("dhcp_lease"),
                )

        elif action == "disconnect":
            router = self.routers.get(event["router"])
            if router:
                router.remove_device(event["interface"], event["mac"])

        elif action == "roam":
            from_router = self.routers.get(event["from_router"])
            to_router = self.routers.get(event["to_router"])
            if from_router and to_router:
                from_router.remove_device(event["from_interface"], event["mac"])
                to_router.add_device(event["to_interface"], event["mac"], event["new_signal"])

        elif action == "signal_change":
            router = self.routers.get(event["router"])
            if router:
                router.update_signal(event["interface"], event["mac"], event["new_signal"])

    async def start(self):
        self.load_scenario()

        for router_id, router in self.routers.items():
            port = self.router_ports[router_id]
            app = self._create_app(router)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            self.runners.append(runner)
            _LOGGER.info("Router '%s' (%s) listening on port %d", router.name, router_id, port)

        # Start time event processor
        if self.time_events:
            self._event_task = asyncio.create_task(self._process_time_events())

    async def stop(self):
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
        for runner in self.runners:
            await runner.cleanup()

    def get_port_mapping(self) -> dict[str, int]:
        """Return router_id -> port mapping."""
        return dict(self.router_ports)

    def get_router_configs(self, host: str = "host.containers.internal") -> list[dict]:
        """Return router configs formatted for HA wrtmanager setup.

        Args:
            host: Hostname the HA container uses to reach the mock servers.
                  Default is 'host.containers.internal' for podman bridge networking.
                  Use 'localhost' if HA runs on the host directly.
        """
        configs = []
        for router_id, router in self.routers.items():
            port = self.router_ports[router_id]
            configs.append(
                {
                    "host": f"{host}:{port}",
                    "name": router.name,
                    "username": "hass",
                    "password": "testing",
                }
            )
        return configs


def write_port_file(manager: MockUbusServerManager, port_file: str, router_host: str):
    """Write port mapping to a file for other scripts to read."""
    data = {
        "ports": manager.get_port_mapping(),
        "routers": manager.get_router_configs(host=router_host),
        "pid": os.getpid(),
    }
    with open(port_file, "w") as f:
        json.dump(data, f, indent=2)
    _LOGGER.info("Port mapping written to %s", port_file)


async def main():
    parser = argparse.ArgumentParser(description="Mock ubus server for E2E testing")
    parser.add_argument(
        "--scenario",
        default=str(Path(__file__).parent / "scenarios" / "default.json"),
        help="Path to scenario JSON file",
    )
    parser.add_argument("--base-port", type=int, default=18001, help="Base port for first router")
    parser.add_argument("--port-file", default=None, help="Write port mapping JSON to this file")
    parser.add_argument("--print-ports", action="store_true", help="Print port mapping to stdout")
    parser.add_argument(
        "--router-host",
        default="host.containers.internal",
        help="Hostname HA uses to reach mock servers (default: host.containers.internal)",
    )
    args = parser.parse_args()

    manager = MockUbusServerManager(args.scenario, args.base_port)
    await manager.start()

    if args.port_file:
        write_port_file(manager, args.port_file, args.router_host)

    if args.print_ports:
        print(json.dumps(manager.get_port_mapping()))

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        _LOGGER.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    _LOGGER.info("Mock ubus servers running. Press Ctrl+C to stop.")
    await stop_event.wait()
    await manager.stop()
    _LOGGER.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
