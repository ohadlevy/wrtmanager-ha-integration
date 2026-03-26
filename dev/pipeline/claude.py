"""Claude CLI wrapper — spawn, stream, timeout, cleanup."""

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Code-only tools for fix/entity steps — no infrastructure
CODE_ONLY_TOOLS = (
    "Read,Write,Edit,Glob,Grep,"
    "Bash(git status:*),Bash(git diff:*),Bash(git log:*),"
    "Bash(git add:*),Bash(git commit:*),Bash(git branch:*),"
    "Bash(git show:*),"
    "Bash(PYTHONPATH=. .venv/bin/python -m pytest:*),"
    "Bash(.venv/bin/python -m pytest:*),"
    "Bash(.venv/bin/python -m black:*),"
    "Bash(.venv/bin/python -m isort:*),"
    "Bash(.venv/bin/python -m flake8:*),"
    "Bash(ls:*),Bash(tree:*)"
)

# Review tools (read-only)
REVIEW_TOOLS = "Read,Write"


@dataclass
class ClaudeResult:
    """Result from a Claude CLI invocation."""

    exit_code: int
    num_turns: int
    cost_usd: float
    duration_ms: int
    output: str  # final text output
    permission_denials: list[dict]


async def run_claude(
    prompt: str,
    *,
    model: str = "claude-sonnet-4-6",
    allowed_tools: Optional[str] = None,
    cwd: Optional[Path] = None,
    timeout: Optional[float] = None,
    log_file: Optional[Path] = None,
) -> ClaudeResult:
    """Run claude -p and stream output. Returns structured result.

    Handles:
    - Stream-json parsing for cost/turn tracking
    - Child process cleanup (prevents orphaned mock servers)
    - Timeout with graceful shutdown
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])

    env = os.environ.copy()
    logger.info("Starting claude: model=%s cwd=%s", model, cwd)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        env=env,
        # Claude stream-json can have very long lines (base64 images)
        limit=10 * 1024 * 1024,  # 10MB
        # Start new process group so we can kill all children
        preexec_fn=os.setsid,
    )

    result_data = {
        "exit_code": -1,
        "num_turns": 0,
        "cost_usd": 0.0,
        "duration_ms": 0,
        "output": "",
        "permission_denials": [],
    }

    log_fh = None
    if log_file:
        log_fh = open(log_file, "a")

    try:

        async def read_stream():
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if log_fh:
                    log_fh.write(decoded + "\n")
                    log_fh.flush()

                # Parse stream-json
                try:
                    data = json.loads(decoded)
                    msg_type = data.get("type")

                    if msg_type == "result":
                        result_data["num_turns"] = data.get("num_turns", 0)
                        result_data["cost_usd"] = data.get("total_cost_usd", 0.0)
                        result_data["duration_ms"] = data.get("duration_ms", 0)
                        result_data["permission_denials"] = data.get("permission_denials", [])
                        subtype = data.get("subtype", "")
                        if subtype == "error":
                            result_data["exit_code"] = 1

                    elif msg_type == "assistant":
                        content = data.get("message", {}).get("content", [])
                        for block in content:
                            if block.get("type") == "text":
                                result_data["output"] = block["text"]

                except (json.JSONDecodeError, KeyError):
                    pass  # non-JSON output lines

        if timeout:
            await asyncio.wait_for(read_stream(), timeout=timeout)
        else:
            await read_stream()

        result_data["exit_code"] = await proc.wait()

    except asyncio.TimeoutError:
        logger.warning("Claude timed out after %ds, killing", timeout)
        _kill_process_group(proc)
        result_data["exit_code"] = -1
        result_data["output"] = f"Timed out after {timeout}s"
        raise
    except asyncio.CancelledError:
        logger.info("Claude cancelled, cleaning up")
        _kill_process_group(proc)
        raise
    finally:
        # Always clean up child processes
        if proc.returncode is None:
            _kill_process_group(proc)
        if log_fh:
            log_fh.close()

    if result_data["permission_denials"]:
        denied_tools = {d.get("tool_name") for d in result_data["permission_denials"]}
        logger.warning("Permission denials: %s", denied_tools)

    logger.info(
        "Claude done: turns=%d cost=$%.2f duration=%ds exit=%d",
        result_data["num_turns"],
        result_data["cost_usd"],
        result_data["duration_ms"] // 1000,
        result_data["exit_code"],
    )

    return ClaudeResult(**result_data)


def _kill_process_group(proc):
    """Kill the process and all its children (prevents orphaned subprocesses)."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        # Force kill after a brief wait
        try:
            os.waitpid(-pgid, os.WNOHANG)
        except (ChildProcessError, OSError):
            os.killpg(pgid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass  # already dead
