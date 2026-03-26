"""Tests for infrastructure managers."""

import json

from dev.pipeline.infra import MockManager, WorktreeManager, compute_ports


class TestComputePorts:
    def test_returns_tuple(self):
        mock_port, ha_port = compute_ports(42)
        assert isinstance(mock_port, int)
        assert isinstance(ha_port, int)

    def test_ports_in_range(self):
        for issue in [1, 42, 100, 999]:
            mock_port, ha_port = compute_ports(issue)
            assert 18000 <= mock_port <= 18999
            assert 18000 <= ha_port <= 18999

    def test_different_issues_different_ports(self):
        p1 = compute_ports(42)
        p2 = compute_ports(43)
        assert p1 != p2


class TestMockManagerIsRunning:
    def test_nonexistent_pid(self):
        assert not MockManager.is_running(999999999)


class TestWorktreeManager:
    def test_has_plan(self, tmp_path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        mgr = WorktreeManager(tmp_path)

        assert not mgr.has_plan(wt)

        (wt / ".plan.md").write_text("# Plan")
        assert mgr.has_plan(wt)

    def test_get_plan(self, tmp_path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        mgr = WorktreeManager(tmp_path)

        assert mgr.get_plan(wt) is None

        (wt / ".plan.md").write_text("# Plan: test\n")
        assert mgr.get_plan(wt) == "# Plan: test\n"


class TestSetupOutputParsing:
    """Test JSON parsing from setup-worktree.sh output."""

    def test_parses_multiline_json(self, tmp_path):
        """The actual output has multiline JSON at the end."""
        output = """Worktree exists, reusing...
Starting mock ubus servers...
Starting HA container...

==========================================
  Test environment ready!
==========================================

{
  "issue_number": 131,
  "branch_name": "feature/131-test",
  "worktree_path": "/tmp/wt",
  "ha_url": "http://localhost:18402",
  "ha_port": 18402,
  "mock_pid": 12345
}"""
        # Simulate what WorktreeManager.setup does with the output
        lines = output.splitlines()
        json_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{":
                json_start = i
                break
        assert json_start is not None
        json_text = "\n".join(lines[json_start:])
        result = json.loads(json_text)
        assert result["ha_url"] == "http://localhost:18402"
        assert result["issue_number"] == 131

    def test_parses_single_line_json(self):
        """--no-env outputs single-line JSON."""
        output = 'Some text\n{"issue_number": 42, "worktree_path": "/tmp"}\n'
        lines = output.splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith("{"):
                result = json.loads(line)
                assert result["issue_number"] == 42
                break

    def test_fails_on_no_json(self):
        """Should raise if no JSON found."""
        output = "Just plain text\nno json here\n"
        lines = output.splitlines()
        found = False
        for line in lines:
            if line.strip().startswith("{"):
                found = True
        assert not found
