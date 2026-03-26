"""Infrastructure managers — mock ubus servers and HA containers."""

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MockServerInfo:
    """Running mock server state."""

    pid: int
    ports: dict  # {"router1": 18303, "router2": 18304, ...}
    routers: list[dict]  # [{host, name, username, password}, ...]
    port_file: Path


class MockManager:
    """Manages mock ubus server lifecycle."""

    def __init__(self, venv_python: Path, repo_root: Path):
        self.venv_python = venv_python
        self.repo_root = repo_root

    async def start(
        self,
        worktree: Path,
        base_port: int,
    ) -> MockServerInfo:
        """Start mock ubus server. Prefers worktree's copy."""
        mock_script = worktree / "dev" / "mock_ubus_server.py"
        if not mock_script.exists():
            mock_script = self.repo_root / "dev" / "mock_ubus_server.py"

        scenario = worktree / "dev" / "scenarios" / "default.json"
        if not scenario.exists():
            scenario = self.repo_root / "dev" / "scenarios" / "default.json"

        port_file = worktree / ".mock-ports.json"
        log_file = worktree / ".mock-server.log"
        pid_file = worktree / ".mock-server.pid"

        cmd = [
            str(self.venv_python),
            str(mock_script),
            "--scenario",
            str(scenario),
            "--base-port",
            str(base_port),
            "--port-file",
            str(port_file),
        ]

        logger.info("Starting mock server: base_port=%d", base_port)
        with open(log_file, "w") as log_fh:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=log_fh,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os.setsid,
            )

        pid_file.write_text(str(proc.pid))

        # Wait for port file to appear
        for _ in range(20):
            if port_file.exists():
                try:
                    data = json.loads(port_file.read_text())
                    if data.get("ports"):
                        break
                except (json.JSONDecodeError, KeyError):
                    pass
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("Mock server failed to start (no port file after 10s)")

        data = json.loads(port_file.read_text())
        logger.info("Mock server running: pid=%d ports=%s", proc.pid, data["ports"])

        return MockServerInfo(
            pid=proc.pid,
            ports=data["ports"],
            routers=data["routers"],
            port_file=port_file,
        )

    async def stop(self, info: MockServerInfo):
        """Stop a running mock server."""
        try:
            pgid = os.getpgid(info.pid)
            os.killpg(pgid, signal.SIGTERM)
            logger.info("Stopped mock server pid=%d", info.pid)
        except (OSError, ProcessLookupError):
            logger.debug("Mock server pid=%d already dead", info.pid)

    @staticmethod
    def is_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


class ContainerManager:
    """Manages HA container lifecycle via podman."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def _container_name(self, worktree: Path) -> str:
        return f"ha-wrt-test-{worktree.name}"

    async def start(
        self,
        worktree: Path,
        ha_port: int,
        mock_port_file: Path,
    ) -> str:
        """Start HA container. Returns container name."""
        ha_env_script = self.repo_root / "dev" / "ha-env.sh"
        cmd = [
            str(ha_env_script),
            "start",
            "--worktree-path",
            str(worktree),
            "--ha-port",
            str(ha_port),
            "--mock-port-file",
            str(mock_port_file),
        ]

        logger.info("Starting HA container: port=%d", ha_port)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"HA container start failed: {stdout.decode()}")

        name = self._container_name(worktree)
        logger.info("HA container started: %s", name)
        return name

    async def stop(self, worktree: Path):
        """Stop HA container for a worktree."""
        ha_env_script = self.repo_root / "dev" / "ha-env.sh"
        cmd = [
            str(ha_env_script),
            "stop",
            "--worktree-path",
            str(worktree),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.communicate()
        logger.info("HA container stopped for %s", worktree.name)

    async def get_logs(self, worktree: Path, tail: int = 200) -> list[str]:
        """Get HA container logs, filtered for wrtmanager errors."""
        name = self._container_name(worktree)
        proc = await asyncio.create_subprocess_exec(
            "podman",
            "logs",
            "--tail",
            str(tail),
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode("utf-8", errors="replace").splitlines()
        # Filter for relevant lines
        keywords = ["wrtmanager", "error", "warning", "exception", "traceback"]
        return [line for line in lines if any(kw in line.lower() for kw in keywords)]

    async def is_running(self, worktree: Path) -> bool:
        name = self._container_name(worktree)
        proc = await asyncio.create_subprocess_exec(
            "podman",
            "ps",
            "--filter",
            f"name={name}",
            "--format",
            "{{.Names}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return name in stdout.decode()


class WorktreeManager:
    """Manages git worktrees for pipeline runs."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.worktree_base = repo_root / ".claude" / "worktrees"

    def worktree_path(self, issue_number: int, branch_prefix: str = "feature") -> Path:
        """Compute worktree path for an issue (matches setup-worktree.sh)."""
        # Get existing worktree if it exists
        for d in self.worktree_base.iterdir() if self.worktree_base.exists() else []:
            if d.is_dir() and d.name.startswith(f"{issue_number}-"):
                return d
        # Will be created by setup-worktree.sh
        return self.worktree_base / f"{issue_number}-placeholder"

    async def setup(
        self,
        issue_number: int,
        branch_prefix: str = "feature",
        start_env: bool = True,
    ) -> dict:
        """Create worktree and optionally start environment.

        Returns JSON output from setup-worktree.sh.
        """
        script = self.repo_root / "dev" / "setup-worktree.sh"
        cmd = [str(script), str(issue_number), "--branch-prefix", branch_prefix]
        if not start_env:
            cmd.append("--no-env")

        logger.info("Setting up worktree: issue=%d env=%s", issue_number, start_env)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            raise RuntimeError(f"Worktree setup failed: {output}")

        # Parse JSON block from output (may be multiline)
        lines = output.splitlines()
        json_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{":
                json_start = i
                break
        if json_start is not None:
            json_text = "\n".join(lines[json_start:])
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                pass

        # Fallback: try each line as single-line JSON
        for line in lines:
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass

        # Last resort: read the state file written by setup-worktree.sh
        state_file = (
            Path(output.split("worktree_path")[1].split('"')[1]).parent / ".dev-env-state.json"
            if "worktree_path" in output
            else None
        )
        if state_file and state_file.exists():
            return json.loads(state_file.read_text())

        raise RuntimeError(f"Cannot parse setup output:\n{output[-500:]}")

    async def teardown(self, worktree: Path):
        """Teardown environment for a worktree (keeps worktree files)."""
        script = self.repo_root / "dev" / "teardown-worktree.sh"
        proc = await asyncio.create_subprocess_exec(
            str(script),
            str(worktree),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.communicate()
        logger.info("Teardown complete for %s", worktree.name)

    def has_plan(self, worktree: Path) -> bool:
        return (worktree / ".plan.md").exists()

    def get_plan(self, worktree: Path) -> Optional[str]:
        plan_file = worktree / ".plan.md"
        if plan_file.exists():
            return plan_file.read_text()
        return None


def compute_ports(issue_number: int) -> tuple[int, int]:
    """Compute deterministic mock and HA ports from issue number.

    Returns (mock_base_port, ha_port).
    """
    # Simple hash to spread across port range 18000-18999
    h = hash(str(issue_number)) % 400
    mock_base = 18000 + h * 2
    ha_port = mock_base + 100
    return mock_base, ha_port
