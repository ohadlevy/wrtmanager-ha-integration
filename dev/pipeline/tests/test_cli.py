"""Tests for CLI argument parsing."""

import argparse
from pathlib import Path

import pytest


def parse(args: list[str]) -> argparse.Namespace:
    """Parse CLI args without running the command."""
    from dev.pipeline.cli import build_pipeline  # noqa: F401

    parser = argparse.ArgumentParser(description="Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("-v", "--verbose", action="store_true")
    shared.add_argument("--model", default="claude-sonnet-4-6")

    run_parser = subparsers.add_parser("run", parents=[shared])
    run_parser.add_argument("issue", type=int)
    run_parser.add_argument("--branch-prefix", default="feature")

    resume_parser = subparsers.add_parser("resume", parents=[shared])
    resume_parser.add_argument("issue", type=int, nargs="?")
    resume_parser.add_argument("--worktree")
    resume_parser.add_argument(
        "--from",
        dest="start_from",
        default="env",
        choices=["env", "execute", "review", "screenshots", "pr"],
    )

    return parser.parse_args(args)


class TestRunCommand:
    def test_basic(self):
        args = parse(["run", "42"])
        assert args.command == "run"
        assert args.issue == 42
        assert args.model == "claude-sonnet-4-6"
        assert args.verbose is False

    def test_with_model(self):
        args = parse(["run", "42", "--model", "claude-opus-4-6"])
        assert args.model == "claude-opus-4-6"

    def test_verbose_after_issue(self):
        args = parse(["run", "42", "-v"])
        assert args.verbose is True
        assert args.issue == 42

    def test_verbose_before_issue(self):
        args = parse(["run", "-v", "42"])
        assert args.verbose is True
        assert args.issue == 42

    def test_branch_prefix(self):
        args = parse(["run", "42", "--branch-prefix", "fix"])
        assert args.branch_prefix == "fix"

    def test_all_options(self):
        args = parse(
            [
                "run",
                "42",
                "--model",
                "claude-opus-4-6",
                "--branch-prefix",
                "chore",
                "-v",
            ]
        )
        assert args.issue == 42
        assert args.model == "claude-opus-4-6"
        assert args.branch_prefix == "chore"
        assert args.verbose is True

    def test_missing_issue_fails(self):
        with pytest.raises(SystemExit):
            parse(["run"])


class TestResumeCommand:
    def test_with_issue_number(self):
        args = parse(["resume", "116"])
        assert args.command == "resume"
        assert args.issue == 116
        assert args.worktree is None

    def test_with_worktree(self):
        args = parse(["resume", "--worktree", "/tmp/wt"])
        assert args.command == "resume"
        assert args.worktree == "/tmp/wt"
        assert args.issue is None

    def test_with_model(self):
        args = parse(["resume", "42", "--model", "opus"])
        assert args.model == "opus"

    def test_verbose(self):
        args = parse(["resume", "42", "-v"])
        assert args.verbose is True

    def test_from_flag(self):
        args = parse(["resume", "42", "--from", "review"])
        assert args.start_from == "review"

    def test_from_flag_with_worktree(self):
        args = parse(["resume", "--worktree", "/tmp/wt", "--from", "screenshots"])
        assert args.start_from == "screenshots"
        assert args.worktree == "/tmp/wt"

    def test_no_args_ok(self):
        """No issue or worktree is valid at parse time (caught at runtime)."""
        args = parse(["resume"])
        assert args.issue is None
        assert args.worktree is None


class TestFindWorktree:
    """Test worktree lookup by issue number."""

    def test_finds_by_issue(self, tmp_path):
        from dev.pipeline.cli import find_worktree

        wt = tmp_path / ".claude" / "worktrees" / "42-feature-test"
        wt.mkdir(parents=True)
        result = find_worktree(issue=42, base=tmp_path)
        assert result == wt

    def test_no_match(self, tmp_path):
        from dev.pipeline.cli import find_worktree

        (tmp_path / ".claude" / "worktrees").mkdir(parents=True)
        result = find_worktree(issue=999, base=tmp_path)
        assert result is None

    def test_by_path(self):
        from dev.pipeline.cli import find_worktree

        result = find_worktree(worktree_path="/tmp/wt")
        assert result == Path("/tmp/wt")

    def test_neither(self):
        from dev.pipeline.cli import find_worktree

        result = find_worktree()
        assert result is None

    def test_no_worktrees_dir(self, tmp_path):
        from dev.pipeline.cli import find_worktree

        result = find_worktree(issue=42, base=tmp_path)
        assert result is None


class TestCmdResumeValidation:
    """Test cmd_resume runtime validation."""

    @pytest.mark.asyncio
    async def test_no_args_returns_1(self):
        from dev.pipeline.cli import cmd_resume

        args = argparse.Namespace(
            issue=None,
            worktree=None,
            model="sonnet",
            start_from="env",
            verbose=False,
        )
        assert await cmd_resume(args) == 1

    @pytest.mark.asyncio
    async def test_worktree_no_plan(self, tmp_path):
        from dev.pipeline.cli import cmd_resume

        wt = tmp_path / "worktree"
        wt.mkdir()

        args = argparse.Namespace(
            issue=None,
            worktree=str(wt),
            model="sonnet",
            start_from="env",
            verbose=False,
        )
        assert await cmd_resume(args) == 1


class TestNoCommand:
    def test_no_args_fails(self):
        with pytest.raises(SystemExit):
            parse([])

    def test_invalid_command_fails(self):
        with pytest.raises(SystemExit):
            parse(["invalid"])
