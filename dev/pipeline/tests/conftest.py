"""Shared fixtures for pipeline tests."""

import pytest


@pytest.fixture
def tmp_worktree(tmp_path):
    """Create a minimal worktree structure for testing."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    (wt / "dev").mkdir()
    (wt / "dev" / "scenarios").mkdir()
    (wt / ".claude").mkdir()
    return wt


@pytest.fixture
def mock_plan(tmp_worktree):
    """Create a sample .plan.md in the worktree."""
    plan = tmp_worktree / ".plan.md"
    plan.write_text("# Plan: Test feature\n\n## Files to modify\nNone\n")
    return plan
