"""Pipeline step implementations.

Each step is an async function: (RunConfig, RunContext) -> RunState
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from .claude import CODE_ONLY_TOOLS, REVIEW_TOOLS, run_claude
from .engine import RunConfig, RunContext, RunState
from .ha_client import HAClient
from .infra import ContainerManager, WorktreeManager

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent


def _venv_python() -> Path:
    return _repo_root() / ".venv" / "bin" / "python"


# --- Setup ---


async def step_setup(config: RunConfig, ctx: RunContext) -> RunState:
    """Create worktree (no environment). Reuses existing worktree."""
    wt_mgr = WorktreeManager(config.repo_root)

    result = await wt_mgr.setup(
        config.issue_number,
        branch_prefix=config.branch_prefix,
        start_env=False,
    )

    ctx.worktree_path = Path(result.get("worktree_path", ""))
    ctx.branch_name = result.get("branch_name", "")

    if not ctx.worktree_path or not ctx.worktree_path.exists():
        raise RuntimeError(f"Worktree not created: {result}")

    # Fetch issue details
    issue_text = await _gh_issue_view(config.issue_number)
    ctx.issue_title = issue_text.get("title", f"Issue #{config.issue_number}")
    ctx.issue_body = issue_text.get("body", "")

    logger.info("Worktree ready: %s", ctx.worktree_path)

    # Skip planning if plan already exists
    if wt_mgr.has_plan(ctx.worktree_path):
        ctx.plan_text = wt_mgr.get_plan(ctx.worktree_path)
        logger.info("Plan exists, skipping planning phase")
        return RunState.STARTING_ENV

    return RunState.PLANNING


async def _gh_issue_view(issue_number: int) -> dict:
    """Get issue title and body via gh CLI."""
    proc = await asyncio.create_subprocess_exec(
        "gh",
        "issue",
        "view",
        str(issue_number),
        "--json",
        "title,body",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        import json

        return json.loads(stdout.decode())
    except Exception:
        return {"title": f"Issue #{issue_number}", "body": ""}


# --- Planning ---


async def step_planning(config: RunConfig, ctx: RunContext) -> RunState:
    """Launch interactive Claude for planning. Returns PLAN_PENDING."""
    # Append planning context to worktree CLAUDE.md
    claude_md = ctx.worktree_path / "CLAUDE.md"
    planning_context = _build_planning_context(config, ctx)
    with open(claude_md, "a") as f:
        f.write(planning_context)

    logger.info(
        "Planning context written to CLAUDE.md. Launch interactive Claude in: %s",
        ctx.worktree_path,
    )
    print(f"\n{'='*50}")
    print(f"  Planning issue #{config.issue_number}")
    print(f"{'='*50}")
    print(f"\n  cd {ctx.worktree_path} && claude\n")
    print("  When plan is approved, Claude writes .plan.md.")
    print("  Then exit (/exit) to continue the pipeline.")
    print(f"\n{'='*50}\n")

    # Launch interactive Claude
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "--model",
        config.model,
        "--verbose",
        cwd=ctx.worktree_path,
    )
    await proc.wait()

    # Check if plan was written
    plan_file = ctx.worktree_path / ".plan.md"
    if plan_file.exists():
        ctx.plan_text = plan_file.read_text()
        logger.info("Plan saved, continuing to environment setup")
        return RunState.STARTING_ENV
    else:
        logger.warning("No .plan.md found after planning session")
        return RunState.PLAN_PENDING


def _build_planning_context(config: RunConfig, ctx: RunContext) -> str:
    return f"""

## Current Task: Plan issue #{config.issue_number}

You are in PLANNING mode. Read the codebase and propose a plan — do NOT implement anything.

### Issue #{config.issue_number}
# {ctx.issue_title}

{ctx.issue_body}

### What to do
1. Read the relevant source files (sensor.py, coordinator.py, wrtmanager-cards.js, etc.)
2. Propose a plan to the user
3. When the user approves, write the final plan to `.plan.md`
4. Say "Plan saved. You can exit to continue the pipeline."

### Plan format (.plan.md)
# Plan: <one-line summary>

## Files to modify
For each file: path + line range, what to change, key code snippet showing the pattern

## UI changes (if any)
MUST include an ASCII visual mockup showing the card layout.

## Data flow
ubus call → coordinator field → sensor entity → card display. Field names and types.

## Mock server changes
New handler in `dev/mock_ubus_server.py` + scenario data in `dev/scenarios/default.json`.

## Dashboard setup
Changes to `dev/setup-ha.py` (card guard + card list) and `examples/dashboard.yaml`.

## Tests
Unit tests + Playwright screenshot tests using `screenshotCard()` helper.

## NOT doing
Out of scope items.

### Rules
- Base plan on actual code, not assumptions
- Be specific: line numbers, function names, variable names
- UI changes MUST include ASCII visual mockup of the card layout
- Smallest change that solves the issue
- Plan MUST include ALL of: mock server changes, dashboard setup, unit tests, screenshot tests
- If any section is not needed, explicitly say "No changes needed" with reason
- Do NOT implement, only plan
"""


# --- Start Environment ---


async def step_start_env(config: RunConfig, ctx: RunContext) -> RunState:
    """Start mock servers + HA container + configure integration."""
    wt_mgr = WorktreeManager(config.repo_root)

    # Full setup with environment
    result = await wt_mgr.setup(
        config.issue_number,
        branch_prefix=config.branch_prefix,
        start_env=True,
    )

    ctx.ha_url = result.get("ha_url", "")
    ctx.ha_port = result.get("ha_port", 0)
    ctx.mock_pid = result.get("mock_pid", 0)

    # Read token
    token_file = ctx.worktree_path / ".ha-token"
    if token_file.exists():
        ctx.ha_token = token_file.read_text().strip()

    # Read mock ports
    port_file = ctx.worktree_path / ".mock-ports.json"
    if port_file.exists():
        import json

        ctx.mock_ports = json.loads(port_file.read_text())

    if not ctx.ha_url:
        raise RuntimeError("HA URL not found in setup output")

    logger.info("Environment ready: ha=%s mock_pid=%s", ctx.ha_url, ctx.mock_pid)
    return RunState.EXECUTING


# --- Execute ---


async def step_execute(config: RunConfig, ctx: RunContext) -> RunState:
    """Run Claude to implement the plan."""
    prompt = f"""You are implementing a change for the wrtmanager HA integration.
Follow the plan below EXACTLY. Do not deviate or add scope.

Your working directory is: {ctx.worktree_path}

## Plan
{ctx.plan_text}

## Instructions
1. Implement each file change listed in the plan
2. Write the tests listed in the plan
3. Run tests: PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
4. If tests fail, fix and re-run (max 2 retries)
5. Make ONE commit at the end with ALL changes: git add <files> && git commit -m "<message>"

Rules:
- Follow the plan — do NOT add features or changes not in the plan
- Only modify files listed in the plan
- Do NOT touch CLAUDE.md, .pre-commit-config.yaml, or dev/ infrastructure
- Make exactly ONE commit with all changes — do NOT make multiple commits
- Do NOT use gh, curl, or explore dev/ scripts
- Do NOT push or create a PR
- Do NOT mention AI in commit messages
"""

    log_file = _log_path(config, ctx, "execute")
    result = await run_claude(
        prompt,
        model=config.model,
        allowed_tools=CODE_ONLY_TOOLS,
        cwd=ctx.worktree_path,
        timeout=config.claude_timeout,
        log_file=log_file,
    )

    ctx.total_cost += result.cost_usd
    logger.info(
        "Execute done: turns=%d cost=$%.2f",
        result.num_turns,
        result.cost_usd,
    )

    if result.exit_code != 0:
        ctx.error = f"Execute failed (exit {result.exit_code}): {result.output[:200]}"
        return RunState.ERROR

    return RunState.CODE_REVIEW


# --- Code Review ---


async def step_code_review(config: RunConfig, ctx: RunContext) -> RunState:
    """Code review + remove files that shouldn't be committed."""
    wt = ctx.worktree_path

    # Remove committed files that shouldn't be in the PR
    _clean_junk_files(wt)

    diff_stat = _git_diff_stat(wt)
    prompt = f"""Review this diff for obvious issues. Be brief.
Check for: unused imports, missing test cases, hardcoded values,
security issues, unnecessary changes outside the plan scope.

IMPORTANT: Check that ONLY files relevant to the issue are modified.
Flag if any of these are in the diff (they should NOT be):
- CLAUDE.md, .pre-commit-config.yaml, .claude/settings.json
- .plan.md, .diagnostics.txt, .ha-entities.json
- Any file not related to the feature being implemented

## Diff
{diff_stat}

Write a short review. If critical issues found, list them.
Otherwise say "No critical issues."
"""

    log_file = _log_path(config, ctx, "review")
    result = await run_claude(
        prompt,
        model="sonnet",
        allowed_tools=REVIEW_TOOLS,
        cwd=wt,
        timeout=300,
        log_file=log_file,
    )
    ctx.total_cost += result.cost_usd
    return RunState.RESTARTING_HA


# Files that should never be in a PR commit
_JUNK_FILES = [
    "CLAUDE.md",
    ".pre-commit-config.yaml",
    ".plan.md",
    ".diagnostics.txt",
    ".ha-entities.json",
    ".screenshot-runner.py",
    ".screenshot-runner.js",
    ".commit_msg",
    "latest",
    ".claude/settings.json",
    ".claude-debug.log",
]


def _clean_junk_files(worktree: Path):
    """Remove junk files from git tracking if they were committed."""
    try:
        diff_files = _git_output(worktree, "diff", "main", "--name-only").splitlines()
        junk_in_diff = [f for f in diff_files if f.strip() in _JUNK_FILES]
        if junk_in_diff:
            logger.warning("Removing junk files from commits: %s", junk_in_diff)
            for f in junk_in_diff:
                # Restore from main (or remove if new)
                try:
                    _git_run(worktree, "checkout", "main", "--", f)
                except subprocess.CalledProcessError:
                    _git_run(worktree, "rm", "--cached", f)
            _git_run(
                worktree,
                "commit",
                "--no-verify",
                "--allow-empty",
                "-m",
                "Remove files not related to this feature",
            )
    except subprocess.CalledProcessError:
        pass


# --- Restart HA ---


async def step_restart_ha(config: RunConfig, ctx: RunContext) -> RunState:
    """Restart HA and update dashboard."""
    if not ctx.ha_url or not ctx.ha_token:
        logger.warning("No HA URL/token, skipping restart")
        return RunState.WAITING_ENTITIES

    # Always refresh token first — it may be expired from planning time
    await _refresh_token(config, ctx)

    ha = HAClient(ctx.ha_url, ctx.ha_token)
    try:
        restarted = await ha.restart(wait=True, wait_timeout=60)
        if not restarted:
            # Service restart failed (500/locked DB) — restart the container
            logger.warning("Service restart failed, restarting container")
            await ha.close()
            container_mgr = ContainerManager(config.repo_root)
            worktree_abs = ctx.worktree_path.resolve()
            await container_mgr.stop(worktree_abs)
            await container_mgr.start(
                worktree_abs,
                ctx.ha_port,
                worktree_abs / ".mock-ports.json",
            )
            # Get fresh token after container restart
            await _refresh_token(config, ctx)
            ha = HAClient(ctx.ha_url, ctx.ha_token)
            if not await ha.wait_for_ready(timeout=60):
                ctx.error = "HA failed to restart after container restart"
                return RunState.ERROR

        # Update dashboard with worktree's setup-ha.py
        await _update_dashboard(config, ctx)

    finally:
        await ha.close()

    return RunState.WAITING_ENTITIES


async def _refresh_token(config: RunConfig, ctx: RunContext):
    """Get a fresh HA auth token via the login flow API."""
    import aiohttp

    ha_url = ctx.ha_url
    token_file = ctx.worktree_path.resolve() / ".ha-token"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ha_url}/auth/login_flow",
                json={
                    "client_id": ha_url,
                    "handler": ["homeassistant", None],
                    "redirect_uri": f"{ha_url}/",
                },
            ) as resp:
                flow = await resp.json()

            async with session.post(
                f"{ha_url}/auth/login_flow/{flow['flow_id']}",
                json={
                    "username": "wrt",
                    "password": "wrt-test-123",
                    "client_id": ha_url,
                },
            ) as resp:
                result = await resp.json()

            if not result.get("result"):
                logger.error("Login failed: %s", result)
                return

            async with session.post(
                f"{ha_url}/auth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": result["result"],
                    "client_id": ha_url,
                },
            ) as resp:
                token_data = await resp.json()

            if "access_token" not in token_data:
                logger.error("Token exchange failed: %s", token_data)
                return

            ctx.ha_token = token_data["access_token"]
            token_file.write_text(ctx.ha_token)
            logger.info(
                "Token refreshed (expires in %ds)",
                token_data.get("expires_in", 0),
            )
    except Exception as e:
        logger.error("Token refresh failed: %s", e)


async def _update_dashboard(config: RunConfig, ctx: RunContext):
    """Update Lovelace dashboard using worktree's setup-ha.py."""
    setup_ha = ctx.worktree_path / "dev" / "setup-ha.py"
    if not setup_ha.exists():
        setup_ha = config.repo_root / "dev" / "setup-ha.py"

    mock_port_file = ctx.worktree_path / ".mock-ports.json"
    token_file = ctx.worktree_path / ".ha-token"

    if not mock_port_file.exists():
        return

    proc = await asyncio.create_subprocess_exec(
        str(_venv_python()),
        str(setup_ha),
        "--ha-url",
        ctx.ha_url,
        "--mock-port-file",
        str(mock_port_file),
        "--token-file",
        str(token_file),
        "--skip-onboarding",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.communicate()
    logger.info("Dashboard updated")


# --- Wait for Entities ---


def _has_ui_changes(worktree: Path) -> bool:
    """Check if the diff includes UI-related files."""
    try:
        diff_files = _git_output(worktree, "diff", "main", "--name-only").splitlines()
        ui_patterns = ["wrtmanager-cards.js", "binary_sensor.py", "sensor.py", "coordinator.py"]
        return any(any(p in f for p in ui_patterns) for f in diff_files)
    except Exception:
        return True  # assume yes if we can't check


async def step_wait_entities(config: RunConfig, ctx: RunContext) -> RunState:
    """Wait for wrtmanager entities to appear in HA."""
    # Skip screenshots entirely if no UI changes
    if not _has_ui_changes(ctx.worktree_path):
        logger.info("No UI changes detected, skipping screenshots/review")
        return RunState.CREATING_PR

    if not ctx.ha_url or not ctx.ha_token:
        return RunState.TAKING_SCREENSHOTS

    ha = HAClient(ctx.ha_url, ctx.ha_token)
    try:
        loaded = await ha.wait_for_integration(timeout=config.entity_wait_timeout)
        if not loaded:
            logger.warning("Integration not loaded after %ds", config.entity_wait_timeout)
            # Don't fail — continue to screenshots, reviewer will see the problem
    finally:
        await ha.close()

    return RunState.TAKING_SCREENSHOTS


# --- Screenshots ---


def _get_changed_cards(worktree: Path) -> list[str]:
    """Detect which cards were added/modified from the git diff."""
    try:
        diff = _git_output(
            worktree,
            "diff",
            "main...HEAD",
            "--",
            "custom_components/wrtmanager/www/wrtmanager-cards.js",
        )
    except Exception:
        return []

    import re

    # Find card class definitions in the diff (added lines)
    cards = set()
    for line in diff.splitlines():
        if not line.startswith("+"):
            continue
        # customElements.define('xxx-card',
        m = re.search(r"customElements\.define\(['\"]([^'\"]+)['\"]", line)
        if m:
            cards.add(m.group(1))
        # { type: "xxx-card", name: ...
        m = re.search(r'type:\s*["\']([^"\']*-card)["\']', line)
        if m:
            cards.add(m.group(1))

    # Also check setup-ha.py for new cards on dashboard
    try:
        diff_ha = _git_output(
            worktree,
            "diff",
            "main...HEAD",
            "--",
            "dev/setup-ha.py",
        )
        for line in diff_ha.splitlines():
            if line.startswith("+"):
                m = re.search(r'"custom:([^"]*-card)"', line)
                if m:
                    cards.add(m.group(1))
    except Exception:
        pass

    return list(cards)


async def step_screenshots(config: RunConfig, ctx: RunContext) -> RunState:
    """Take targeted screenshots of changed cards only."""
    screenshot_dir = ctx.worktree_path.resolve() / ".test-screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    # Clear old screenshots
    for f in screenshot_dir.glob("*.png"):
        f.unlink()

    if not ctx.ha_url or not ctx.ha_token:
        logger.warning("No HA URL/token, skipping screenshots")
        return RunState.VISUAL_REVIEW

    # Find which cards changed
    changed_cards = _get_changed_cards(ctx.worktree_path)
    if not changed_cards:
        # Fallback: screenshot all known cards
        changed_cards = [
            "router-health-card",
            "network-devices-card",
            "network-topology-card",
            "signal-heatmap-card",
            "roaming-activity-card",
            "interface-health-card",
        ]
    logger.info("Cards to screenshot: %s", changed_cards)

    # Use worktree's run-tests.sh — its grep pattern matches its test file
    worktree_abs = ctx.worktree_path.resolve()
    run_tests = worktree_abs / "dev" / "run-tests.sh"
    if not run_tests.exists():
        run_tests = config.repo_root / "dev" / "run-tests.sh"

    proc = await asyncio.create_subprocess_exec(
        str(run_tests),
        "--worktree-path",
        str(worktree_abs),
        "--review-only",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")
    logger.info("Screenshots done (exit %d)", proc.returncode)
    if proc.returncode != 0:
        logger.warning("Screenshot output: %s", output[-500:])

    # Count results
    pngs = list(screenshot_dir.glob("*.png"))
    logger.info("Captured %d screenshots", len(pngs))

    if not pngs:
        ctx.error = f"Screenshot capture failed (exit {proc.returncode}): {output[-300:]}"
        return RunState.ERROR

    return RunState.VISUAL_REVIEW


def _build_screenshot_script(
    ha_url: str,
    ha_token: str,
    cards: list[str],
    output_dir: str,
) -> str:
    """Build a Python script that uses playwright to screenshot cards."""
    cards_json = str(cards)
    return f'''#!/usr/bin/env python3
"""Take targeted card screenshots — runs inside Playwright container."""
import json
from playwright.sync_api import sync_playwright

HA_URL = "{ha_url}"
TOKEN = "{ha_token}"
CARDS = {cards_json}
OUTPUT = "{output_dir}"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={{"width": 1920, "height": 1080}})

        # Auth via localStorage token injection
        page.goto(HA_URL, wait_until="domcontentloaded")
        page.evaluate("""({{ token, url }}) => {{
            localStorage.setItem('hassTokens', JSON.stringify({{
                hassUrl: url, clientId: url,
                access_token: token, token_type: 'Bearer',
                expires_in: 86400, refresh_token: '',
                expires: Date.now() + 86400000,
            }}));
        }}""", {{"token": TOKEN, "url": HA_URL}})

        # Navigate to dashboard
        page.goto(f"{{HA_URL}}/lovelace/network", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Screenshot only the changed card elements (not full page)
        for card_tag in CARDS:
            name = card_tag.replace("-card", "")
            try:
                el = page.locator(card_tag).first
                el.wait_for(state="visible", timeout=5000)
                el.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                el.screenshot(path=f"{{OUTPUT}}/{{name}}-desktop.png")
                print(f"{{name}}-desktop.png")
            except Exception as e:
                print(f"SKIP {{card_tag}}: {{e}}")

        browser.close()

if __name__ == "__main__":
    main()
'''


# --- Visual Review ---


async def step_visual_review(config: RunConfig, ctx: RunContext) -> RunState:
    """Visual review: compare screenshots against plan."""
    ctx.review_round += 1
    logger.info("Visual review round %d/%d", ctx.review_round, config.max_review_rounds)

    # Collect screenshots — prefer changed card screenshots, fall back to all
    screenshot_dir = ctx.worktree_path.resolve() / ".test-screenshots"
    changed_cards = _get_changed_cards(ctx.worktree_path)
    screenshots = []
    if changed_cards:
        for card in changed_cards:
            name = card.replace("-card", "").replace("-editor", "")
            png = screenshot_dir / f"{name}-desktop.png"
            if png.exists():
                screenshots.append(png)
    # Fall back to all screenshots if changed card screenshots not found
    if not screenshots:
        screenshots = (
            sorted(screenshot_dir.glob("*-desktop.png")) if screenshot_dir.exists() else []
        )

    if not screenshots:
        logger.warning("No screenshots available")
        ctx.review_feedback = "No screenshots found — cannot review."
        ctx.review_verdict = "FAIL"
        if ctx.review_round >= config.max_review_rounds:
            return RunState.FAILED
        return RunState.FIXING

    # Capture diagnostics
    diagnostics_text = ""
    if ctx.ha_url and ctx.ha_token:
        ha = HAClient(ctx.ha_url, ctx.ha_token)
        try:
            container_mgr = ContainerManager(config.repo_root)
            ha_logs = await container_mgr.get_logs(ctx.worktree_path)
            console_file = screenshot_dir / "console-errors.txt"
            console_errors = []
            if console_file.exists():
                console_errors = console_file.read_text().splitlines()
            diag = await ha.capture_diagnostics(ha_logs, console_errors)
            diagnostics_text = diag.summary()
            ctx.diagnostics = diagnostics_text
        finally:
            await ha.close()

    # Build review context
    if ctx.plan_text:
        review_context = f"## Implementation Plan\n{ctx.plan_text}"
    else:
        review_context = (
            f"## Issue #{config.issue_number}\n" f"# {ctx.issue_title}\n\n{ctx.issue_body}"
        )

    screenshot_files = " ".join(str(s) for s in screenshots)

    cards_str = ", ".join(c.replace("-card", "") for c in changed_cards) if changed_cards else "all"
    prompt = f"""You are a visual reviewer checking {cards_str} card(s).

Compare the {len(screenshots)} screenshot(s) against the plan's UI specification.

{review_context}

## Runtime diagnostics
{diagnostics_text or "No diagnostics available."}

## Screenshots to review ({len(screenshots)})
{screenshot_files}

## Instructions
1. Read each screenshot image file
2. Check: do the screenshots show what the plan says should be implemented?
3. Use the diagnostics above to understand what entities/cards HA actually loaded
4. Check design quality (HA native style, CSS variables, units, layout)
5. Write verdict to {ctx.worktree_path / ".review-result.md"}

First line MUST be: PASS, NEEDS_CHANGES, or FAIL
Then explain specifically what is wrong or missing so a developer can fix it.
Be precise: mention entity IDs, CSS issues, missing UI elements, wrong values.
If diagnostics show entities are unavailable or cards are missing from dashboard, mention this.
Do NOT fix code yourself — only diagnose and write the verdict.
Do NOT fail for items listed as out of scope in the plan.
"""

    log_file = _log_path(config, ctx, f"review-r{ctx.review_round}")
    result = await run_claude(
        prompt,
        model="sonnet",
        allowed_tools=REVIEW_TOOLS,
        cwd=ctx.worktree_path,
        timeout=300,
        log_file=log_file,
    )
    ctx.total_cost += result.cost_usd

    # Read verdict
    review_file = ctx.worktree_path / ".review-result.md"
    if review_file.exists():
        content = review_file.read_text()
        ctx.review_feedback = content
        ctx.review_verdict = content.split("\n")[0].strip()
    else:
        ctx.review_verdict = "FAIL"
        ctx.review_feedback = "Review did not produce a verdict file."

    logger.info("Review verdict: %s (round %d)", ctx.review_verdict, ctx.review_round)

    if ctx.review_verdict == "PASS":
        return RunState.CREATING_PR
    elif ctx.review_round >= config.max_review_rounds:
        return RunState.FAILED
    else:
        return RunState.FIXING


# --- Fix ---


async def step_fix(config: RunConfig, ctx: RunContext) -> RunState:
    """Apply fixes based on review feedback."""
    logger.info("Applying fix (round %d)", ctx.review_round)

    diff_stat = _git_diff_stat(ctx.worktree_path)

    prompt = f"""You are fixing issue #{config.issue_number} based on visual review feedback.

Working directory: {ctx.worktree_path}

## Plan (source of truth for scope)
{ctx.plan_text or f"No plan available. Issue: {ctx.issue_title}"}

## Current changes
{diff_stat}

## Review feedback (verdict: {ctx.review_verdict})
{ctx.review_feedback}

## Runtime diagnostics
{ctx.diagnostics or "No diagnostics available."}

## Instructions
1. Read the relevant source files to understand the current state
2. Use the diagnostics above to understand what HA actually loaded vs what was expected
3. Fix the issue described in the review feedback
4. Run tests: PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
5. Commit: git add <files> && git commit -m "<message>"

Rules:
- Focus ONLY on the review feedback — do not add unrelated changes
- Follow the plan scope — do NOT add features marked as "NOT doing"
- Do NOT use gh, curl, or explore dev/ scripts
- Do NOT push or create a PR
- Do NOT mention AI in commit messages
"""

    log_file = _log_path(config, ctx, f"fix-r{ctx.review_round}")
    result = await run_claude(
        prompt,
        model=config.model,
        allowed_tools=CODE_ONLY_TOOLS,
        cwd=ctx.worktree_path,
        timeout=config.claude_timeout,
        log_file=log_file,
    )
    ctx.total_cost += result.cost_usd

    return RunState.RESTARTING_HA


# --- Create PR ---


async def step_create_pr(config: RunConfig, ctx: RunContext) -> RunState:
    """Squash commits, rebase, push, and create PR."""
    wt = ctx.worktree_path

    # Commit any modified tracked files (not untracked junk like .plan.md)
    try:
        status = _git_output(wt, "status", "--porcelain")
        modified = [
            line[3:] for line in status.splitlines() if line and line[0] in " M" and line[1] in "MD"
        ]
        if modified:
            _git_run(wt, "add", *modified)
            _git_run(
                wt,
                "commit",
                "--no-verify",
                "-m",
                "Include test and config updates from review fixes",
            )
            logger.info("Committed %d modified files before squash", len(modified))
    except subprocess.CalledProcessError:
        pass

    # Squash commits
    commit_count = _git_commit_count(wt)
    if commit_count > 1:
        logger.info("Squashing %d commits", commit_count)
        merge_base = _git_output(wt, "merge-base", "main", "HEAD").strip()
        first_msg = _git_output(wt, "log", "--format=%s", "--reverse", "main..HEAD").splitlines()[0]
        _git_run(wt, "reset", "--soft", merge_base)
        _git_run(wt, "commit", "--no-verify", "-m", f"{first_msg}\n\nCloses #{config.issue_number}")

    # Rebase onto latest main
    _git_run_in_repo(config.repo_root, "fetch", "origin", "main:main")
    try:
        _git_run(wt, "rebase", "main")
    except subprocess.CalledProcessError:
        logger.warning("Rebase conflict — auto-resolving")
        try:
            conflicted = _git_output(wt, "diff", "--name-only", "--diff-filter=U").splitlines()
            for f in conflicted:
                _git_run(wt, "checkout", "--theirs", f)
                _git_run(wt, "add", f)
            _git_run(wt, "rebase", "--continue")
        except subprocess.CalledProcessError:
            try:
                _git_run(wt, "rebase", "--abort")
            except subprocess.CalledProcessError:
                pass
            logger.error("Rebase failed, pushing without rebase")

    # Push
    _git_run(wt, "push", "-u", "origin", "HEAD", "--force-with-lease")

    # Create PR
    diff_stat = _git_diff_stat(wt)
    pr_body = f"""Fixes #{config.issue_number}

## Changes
{diff_stat}

## Test plan
- Unit tests: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v`
- Browser tests: screenshots in `.test-screenshots/`
"""

    proc = await asyncio.create_subprocess_exec(
        "gh",
        "pr",
        "create",
        "--title",
        ctx.issue_title,
        "--body",
        pr_body,
        cwd=wt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    pr_output = stdout.decode().strip()

    if proc.returncode == 0:
        ctx.pr_url = pr_output
        logger.info("PR created: %s", ctx.pr_url)

        # Upload screenshots to PR
        pr_number = pr_output.rstrip("/").split("/")[-1]
        await _upload_screenshots_to_pr(config, ctx, pr_number)
    else:
        logger.error("PR creation failed: %s", pr_output)

    return RunState.PASSED


async def _upload_screenshots_to_pr(config: RunConfig, ctx: RunContext, pr_number: str):
    """Upload screenshots to orphan branch and add PR comment with inline images."""
    screenshot_dir = ctx.worktree_path.resolve() / ".test-screenshots"
    pngs = sorted(screenshot_dir.glob("*-desktop.png"))
    if not pngs:
        return

    # Get repo slug
    proc = await asyncio.create_subprocess_exec(
        "gh",
        "repo",
        "view",
        "--json",
        "nameWithOwner",
        "-q",
        ".nameWithOwner",
        cwd=ctx.worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    repo_slug = stdout.decode().strip()
    if not repo_slug:
        logger.warning("Cannot determine repo slug, skipping screenshot upload")
        return

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Clone screenshots branch
        remote_url = _git_output(ctx.worktree_path, "remote", "get-url", "origin").strip()
        proc = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--single-branch",
            "--branch",
            "screenshots",
            remote_url,
            str(tmpdir / "repo"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.communicate()

        repo_dir = tmpdir / "repo"
        if not (repo_dir / ".git").exists():
            logger.warning("Screenshots branch not found, skipping upload")
            return

        # Copy screenshots
        pr_dir = repo_dir / f"pr-{pr_number}"
        pr_dir.mkdir(exist_ok=True)
        import shutil

        for png in pngs:
            shutil.copy2(png, pr_dir / png.name)

        # Commit and push
        _git_run(repo_dir, "add", f"pr-{pr_number}/")
        try:
            _git_run(
                repo_dir,
                "commit",
                "--no-verify",
                "-m",
                f"Add screenshots for PR #{pr_number}",
            )
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_dir),
                "push",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await proc.communicate()
        except subprocess.CalledProcessError:
            logger.warning("Failed to push screenshots")
            return

        # Build PR comment with inline images
        images_md = ""
        for png in pngs:
            name = png.stem.replace("-desktop", "").replace("-", " ")
            base = f"https://raw.githubusercontent.com/{repo_slug}"
            url = f"{base}/screenshots/pr-{pr_number}/{png.name}"
            images_md += f"### {name}\n![{name}]({url})\n\n"

        comment = f"## Screenshots\n\n{images_md}"

        proc = await asyncio.create_subprocess_exec(
            "gh",
            "pr",
            "comment",
            pr_number,
            "--body",
            comment,
            cwd=ctx.worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.communicate()
        if proc.returncode == 0:
            logger.info("Screenshots uploaded to PR #%s", pr_number)
        else:
            logger.warning("Failed to add screenshot comment")


# --- Helpers ---


def _git_diff_stat(worktree: Path) -> str:
    try:
        return _git_output(worktree, "diff", "main...HEAD", "--stat")
    except Exception:
        return "(no diff)"


def _git_commit_count(worktree: Path) -> int:
    try:
        return int(_git_output(worktree, "rev-list", "main..HEAD", "--count").strip())
    except Exception:
        return 0


def _git_output(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree)] + list(args),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


# Env that prevents git from opening an editor
_GIT_ENV = {**os.environ, "GIT_EDITOR": "true", "GIT_TERMINAL_PROMPT": "0"}


def _git_run(worktree: Path, *args: str):
    subprocess.run(
        ["git", "-C", str(worktree)] + list(args),
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )


def _git_run_in_repo(repo: Path, *args: str):
    subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )


def _log_path(config: RunConfig, ctx: RunContext, suffix: str) -> Path:
    log_dir = config.repo_root / ".claude" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"issue-{config.issue_number}-{suffix}.log"
