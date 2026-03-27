#!/usr/bin/env python3
"""Pipeline CLI — replaces sessions.sh for pipeline management."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .engine import Pipeline, RunConfig, RunState
from .steps import (
    step_code_review,
    step_create_pr,
    step_execute,
    step_fix,
    step_planning,
    step_restart_ha,
    step_screenshots,
    step_setup,
    step_start_env,
    step_visual_review,
    step_wait_entities,
)

logger = logging.getLogger(__name__)


def build_pipeline(config: RunConfig) -> Pipeline:
    """Wire up all pipeline steps."""
    p = Pipeline(config)

    p.register_step(RunState.CREATED, step_setup)
    p.register_step(RunState.PLANNING, step_planning)
    # PLAN_PENDING is terminal — pipeline stops for human approval
    p.register_step(RunState.STARTING_ENV, step_start_env)
    p.register_step(RunState.EXECUTING, step_execute)
    p.register_step(RunState.CODE_REVIEW, step_code_review)
    p.register_step(RunState.RESTARTING_HA, step_restart_ha)
    p.register_step(RunState.WAITING_ENTITIES, step_wait_entities)
    p.register_step(RunState.TAKING_SCREENSHOTS, step_screenshots)
    p.register_step(RunState.VISUAL_REVIEW, step_visual_review)
    p.register_step(RunState.FIXING, step_fix)
    p.register_step(RunState.CREATING_PR, step_create_pr)

    # Log transitions
    def on_transition(old: RunState, new: RunState):
        print(f"  [{old.value}] → [{new.value}]")

    p.on_transition(on_transition)

    return p


async def cmd_run(args):
    """Start a new pipeline run."""
    config = RunConfig(
        issue_number=args.issue,
        model=args.model,
        branch_prefix=args.branch_prefix,
        repo_root=Path.cwd(),
    )

    pipeline = build_pipeline(config)
    print(f"\nStarting pipeline for issue #{args.issue}")
    print(f"Model: {config.model}")
    print()

    result = await pipeline.run()

    ctx = pipeline.ctx
    print(f"\n{'='*50}")
    print(f"  Result: {result.value}")
    print(f"  Cost: ${ctx.total_cost:.2f}")
    if ctx.pr_url:
        print(f"  PR: {ctx.pr_url}")
    if ctx.error:
        print(f"  Error: {ctx.error}")
    if ctx.ha_url:
        print(f"  HA: {ctx.ha_url}")
    print(f"{'='*50}\n")

    if result == RunState.PLAN_PENDING:
        print("No plan was created. To plan interactively:")
        print(f"  cd {ctx.worktree_path} && claude")
        print(f"Then: dev/pipeline.sh resume {config.issue_number} -v")
        return 0

    return 0 if result == RunState.PASSED else 1


def find_worktree(issue: int = None, worktree_path: str = None, base: Path = None):
    """Find worktree by issue number or path. Returns Path or None."""
    if issue:
        wt_base = (base or Path.cwd()) / ".claude" / "worktrees"
        matches = [
            d
            for d in (wt_base.iterdir() if wt_base.exists() else [])
            if d.is_dir() and d.name.startswith(f"{issue}-")
        ]
        return matches[0] if matches else None
    elif worktree_path:
        return Path(worktree_path)
    return None


async def cmd_resume(args):
    """Resume a pipeline from after planning (has .plan.md)."""
    issue = getattr(args, "issue", None)
    worktree = find_worktree(issue, getattr(args, "worktree", None))

    if worktree is None:
        print("Provide an issue number or --worktree path")
        return 1

    if not worktree.exists():
        print(f"Worktree not found: {worktree}")
        return 1

    plan_file = worktree / ".plan.md"
    if not plan_file.exists():
        print(f"No .plan.md found in {worktree}")
        return 1

    # Extract issue number from worktree name if not provided
    if not issue:
        name = worktree.name
        issue = int(name.split("-")[0]) if name[0].isdigit() else 0
        if issue == 0:
            print(f"Cannot determine issue number from: {name}")
            return 1

    config = RunConfig(
        issue_number=issue,
        model=args.model,
        repo_root=Path.cwd(),
    )

    pipeline = build_pipeline(config)
    pipeline.ctx.worktree_path = worktree
    pipeline.ctx.branch_name = _git_branch(worktree)
    pipeline.ctx.plan_text = plan_file.read_text()

    # Fetch issue details
    from .steps import _gh_issue_view

    issue_text = await _gh_issue_view(issue)
    pipeline.ctx.issue_title = issue_text.get("title", f"Issue #{issue}")
    pipeline.ctx.issue_body = issue_text.get("body", "")

    # Determine start state
    start_from = getattr(args, "start_from", None) or "env"
    state_map = {
        "env": RunState.STARTING_ENV,
        "execute": RunState.EXECUTING,
        "code_review": RunState.CODE_REVIEW,
        "review": RunState.RESTARTING_HA,
        "screenshots": RunState.TAKING_SCREENSHOTS,
        "pr": RunState.CREATING_PR,
    }
    target = state_map.get(start_from, RunState.STARTING_ENV)

    # Ensure environment is running when skipping env setup
    if target != RunState.STARTING_ENV:
        import json

        from .infra import WorktreeManager

        state_file = worktree / ".dev-env-state.json"
        env_running = False
        if state_file.exists():
            env_data = json.loads(state_file.read_text())
            mock_pid = env_data.get("mock_pid", 0)
            # Check if mock server is actually running
            if mock_pid:
                try:
                    import os

                    os.kill(mock_pid, 0)
                    env_running = True
                except (OSError, ProcessLookupError):
                    pass

        if not env_running:
            print("Environment not running, starting it...")
            wt_mgr = WorktreeManager(Path.cwd())
            await wt_mgr.setup(issue, branch_prefix="feature", start_env=True)
            state_file = worktree / ".dev-env-state.json"

        if state_file.exists():
            env_data = json.loads(state_file.read_text())
            pipeline.ctx.ha_url = env_data.get("ha_url", "")
            pipeline.ctx.ha_port = env_data.get("ha_port", 0)
            pipeline.ctx.mock_pid = env_data.get("mock_pid", 0)
        token_file = worktree / ".ha-token"
        if token_file.exists():
            pipeline.ctx.ha_token = token_file.read_text().strip()

    # Transition to target state
    pipeline.state = RunState.PLAN_PENDING
    pipeline._transition(target)

    print(f"\nResuming pipeline for issue #{issue} (from {start_from})")
    print(f"Worktree: {worktree}")
    print(f"Model: {config.model}")
    print()

    result = await pipeline.run()

    ctx = pipeline.ctx
    print(f"\n{'='*50}")
    print(f"  Result: {result.value}")
    print(f"  Cost: ${ctx.total_cost:.2f}")
    if ctx.pr_url:
        print(f"  PR: {ctx.pr_url}")
    if ctx.error:
        print(f"  Error: {ctx.error}")
    print(f"{'='*50}\n")

    return 0 if result == RunState.PASSED else 1


def _git_branch(worktree: Path) -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def main():
    parser = argparse.ArgumentParser(description="Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared args added to each subparser so -v works anywhere
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    shared.add_argument("--model", default="claude-sonnet-4-6", help="Claude model")

    # run
    run_parser = subparsers.add_parser("run", help="Start pipeline for an issue", parents=[shared])
    run_parser.add_argument("issue", type=int, help="GitHub issue number")
    run_parser.add_argument("--branch-prefix", default="feature", help="Branch prefix")

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume after planning", parents=[shared])
    resume_parser.add_argument("issue", type=int, nargs="?", help="GitHub issue number")
    resume_parser.add_argument("--worktree", help="Worktree path (alternative to issue number)")
    resume_parser.add_argument(
        "--from",
        dest="start_from",
        default="env",
        choices=["env", "execute", "code_review", "review", "screenshots", "pr"],
        help="Start from: env, execute, code_review, review, screenshots, pr",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "run":
        sys.exit(asyncio.run(cmd_run(args)))
    elif args.command == "resume":
        sys.exit(asyncio.run(cmd_resume(args)))


if __name__ == "__main__":
    main()
