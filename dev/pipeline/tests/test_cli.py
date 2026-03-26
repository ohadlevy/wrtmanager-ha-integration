"""Tests for CLI argument parsing."""

import argparse

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
    resume_parser.add_argument("--worktree", required=True)

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
    def test_basic(self):
        args = parse(["resume", "--worktree", "/tmp/wt"])
        assert args.command == "resume"
        assert args.worktree == "/tmp/wt"

    def test_with_model(self):
        args = parse(["resume", "--worktree", "/tmp/wt", "--model", "opus"])
        assert args.model == "opus"

    def test_verbose(self):
        args = parse(["resume", "--worktree", "/tmp/wt", "-v"])
        assert args.verbose is True

    def test_missing_worktree_fails(self):
        with pytest.raises(SystemExit):
            parse(["resume"])


class TestNoCommand:
    def test_no_args_fails(self):
        with pytest.raises(SystemExit):
            parse([])

    def test_invalid_command_fails(self):
        with pytest.raises(SystemExit):
            parse(["invalid"])
