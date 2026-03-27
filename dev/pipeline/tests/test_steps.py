"""Tests for pipeline steps — validates the logic that caused bash pipeline bugs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dev.pipeline.engine import RunConfig, RunContext, RunState
from dev.pipeline.steps import (
    _build_planning_context,
    step_setup,
    step_visual_review,
    step_wait_entities,
)


@pytest.fixture
def config(tmp_path):
    return RunConfig(issue_number=42, repo_root=tmp_path)


@pytest.fixture
def ctx(tmp_path):
    wt = tmp_path / "worktree"
    wt.mkdir(parents=True)
    c = RunContext()
    c.worktree_path = wt
    c.ha_url = "http://localhost:18400"
    c.ha_token = "test-token"
    c.plan_text = "# Plan: test\n## Files to modify\nNone"
    c.issue_title = "Test Issue"
    c.issue_body = "Fix the thing"
    return c


class TestPlanPreservation:
    """Test that existing plans are reused (bug: run 15 wiped plan)."""

    @pytest.mark.asyncio
    async def test_skips_planning_when_plan_exists(self, config, tmp_path):
        """If .plan.md exists, go straight to STARTING_ENV."""
        wt = tmp_path / "worktree"
        wt.mkdir(parents=True)
        plan_file = wt / ".plan.md"
        plan_file.write_text("# Plan: existing\n")

        with patch("dev.pipeline.steps.WorktreeManager") as MockWM:
            mock_wt_mgr = MockWM.return_value
            mock_wt_mgr.setup = AsyncMock(
                return_value={
                    "worktree_path": str(wt),
                    "branch_name": "feature/42-test",
                }
            )
            mock_wt_mgr.has_plan.return_value = True
            mock_wt_mgr.get_plan.return_value = "# Plan: existing\n"

            with patch("dev.pipeline.steps._gh_issue_view", new_callable=AsyncMock) as mock_gh:
                mock_gh.return_value = {"title": "Test", "body": "body"}
                result = await step_setup(config, RunContext())

        assert result == RunState.STARTING_ENV

    @pytest.mark.asyncio
    async def test_goes_to_planning_when_no_plan(self, config, tmp_path):
        """If no .plan.md, go to PLANNING."""
        wt = tmp_path / "worktree"
        wt.mkdir(parents=True)

        with patch("dev.pipeline.steps.WorktreeManager") as MockWM:
            mock_wt_mgr = MockWM.return_value
            mock_wt_mgr.setup = AsyncMock(
                return_value={
                    "worktree_path": str(wt),
                    "branch_name": "feature/42-test",
                }
            )
            mock_wt_mgr.has_plan.return_value = False

            with patch("dev.pipeline.steps._gh_issue_view", new_callable=AsyncMock) as mock_gh:
                mock_gh.return_value = {"title": "Test", "body": "body"}
                result = await step_setup(config, RunContext())

        assert result == RunState.PLANNING


class TestWorktreeScripts:
    """Test that worktree scripts are preferred over main (bug: runs 16, 19)."""

    def test_planning_context_includes_required_sections(self, config, ctx):
        context = _build_planning_context(config, ctx)
        assert "Mock server changes" in context
        assert "Dashboard setup" in context
        assert "Tests" in context
        assert "ASCII visual mockup" in context
        assert "examples/dashboard.yaml" in context

    def test_planning_context_includes_issue(self, config, ctx):
        context = _build_planning_context(config, ctx)
        assert "Test Issue" in context
        assert "Fix the thing" in context


class TestVisualReview:
    """Test review step — diagnostics inclusion and verdict handling."""

    @pytest.mark.asyncio
    async def test_no_screenshots_fails(self, config, ctx):
        """No screenshots → FAIL (not hang)."""
        ss_dir = ctx.worktree_path / ".test-screenshots"
        ss_dir.mkdir()
        # No .png files

        result = await step_visual_review(config, ctx)
        assert result in (RunState.FIXING, RunState.FAILED)
        assert ctx.review_verdict == "FAIL"

    @pytest.mark.asyncio
    async def test_max_rounds_fails(self, config, ctx):
        """After max review rounds, return FAILED."""
        config.max_review_rounds = 2
        ctx.review_round = 2  # already at max

        ss_dir = ctx.worktree_path / ".test-screenshots"
        ss_dir.mkdir()
        # No screenshots → triggers FAIL path
        result = await step_visual_review(config, ctx)
        assert result == RunState.FAILED

    @pytest.mark.asyncio
    async def test_review_includes_diagnostics(self, config, ctx):
        """Diagnostics should be captured and included in review."""
        ss_dir = ctx.worktree_path / ".test-screenshots"
        ss_dir.mkdir()
        (ss_dir / "router-health-desktop.png").write_bytes(b"fake png")

        # Mock the review claude call and HA client
        with patch("dev.pipeline.steps.run_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = MagicMock(
                exit_code=0,
                num_turns=5,
                cost_usd=0.10,
                duration_ms=5000,
                output="",
                permission_denials=[],
            )
            # Create a verdict file (simulating what review Claude writes)
            (ctx.worktree_path / ".review-result.md").write_text("PASS\nLooks good.")

            with patch("dev.pipeline.steps.HAClient") as MockHA:
                mock_ha = MockHA.return_value
                mock_ha.capture_diagnostics = AsyncMock(
                    return_value=MagicMock(
                        summary=lambda: "Entities: 10 total, 0 unavailable",
                    )
                )
                mock_ha.close = AsyncMock()

                with patch("dev.pipeline.steps.ContainerManager") as MockCM:
                    MockCM.return_value.get_logs = AsyncMock(return_value=[])

                    result = await step_visual_review(config, ctx)

            # Check that diagnostics were passed to the claude prompt
            prompt = mock_claude.call_args[0][0]
            assert "diagnostics" in prompt.lower()

        assert result == RunState.CREATING_PR


class TestWaitEntities:
    """Test entity wait (bug: 5s sleep → stale diagnostics)."""

    @pytest.mark.asyncio
    async def test_continues_even_without_entities(self, config, ctx):
        """Don't fail — continue to screenshots, reviewer will see the problem."""
        with patch("dev.pipeline.steps.HAClient") as MockHA:
            mock_ha = MockHA.return_value
            mock_ha.wait_for_integration = AsyncMock(return_value=False)
            mock_ha.close = AsyncMock()

            config.entity_wait_timeout = 2
            result = await step_wait_entities(config, ctx)

        assert result == RunState.TAKING_SCREENSHOTS

    @pytest.mark.asyncio
    async def test_skips_when_no_ha(self, config, ctx):
        """No HA URL → skip straight to screenshots."""
        ctx.ha_url = None
        result = await step_wait_entities(config, ctx)
        assert result == RunState.TAKING_SCREENSHOTS


class TestSkipScreenshots:
    """Skip screenshots when no UI changes."""

    def test_has_ui_changes_with_cards_js(self, tmp_path):
        from dev.pipeline.steps import _has_ui_changes

        with patch("dev.pipeline.steps._git_output") as mock:
            mock.return_value = "custom_components/wrtmanager/www/wrtmanager-cards.js\n"
            assert _has_ui_changes(tmp_path) is True

    def test_has_ui_changes_with_sensor(self, tmp_path):
        from dev.pipeline.steps import _has_ui_changes

        with patch("dev.pipeline.steps._git_output") as mock:
            mock.return_value = "custom_components/wrtmanager/sensor.py\n"
            assert _has_ui_changes(tmp_path) is True

    def test_no_ui_changes_script_only(self, tmp_path):
        from dev.pipeline.steps import _has_ui_changes

        with patch("dev.pipeline.steps._git_output") as mock:
            mock.return_value = "scripts/setup_openwrt_ha_integration.sh\ntests/test_acl.py\n"
            assert _has_ui_changes(tmp_path) is False

    def test_no_ui_changes_docs_only(self, tmp_path):
        from dev.pipeline.steps import _has_ui_changes

        with patch("dev.pipeline.steps._git_output") as mock:
            mock.return_value = "docs/readme.md\nexamples/dashboard.yaml\n"
            assert _has_ui_changes(tmp_path) is False


class TestCodeOnlyTools:
    """Verify fix/execute steps use restricted tools (bug: run 15 hung)."""

    @pytest.mark.asyncio
    async def test_fix_uses_code_only_tools(self, config, ctx):
        """Fix step must use CODE_ONLY_TOOLS, not infrastructure tools."""
        from dev.pipeline.steps import step_fix

        with patch("dev.pipeline.steps.run_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = MagicMock(
                exit_code=0,
                num_turns=5,
                cost_usd=0.50,
                duration_ms=30000,
                output="Fixed",
                permission_denials=[],
            )
            await step_fix(config, ctx)

            # Check allowed_tools passed to run_claude
            call_kwargs = mock_claude.call_args[1]
            tools = call_kwargs.get("allowed_tools", "")
            assert "mock_ubus" not in tools
            assert "setup-ha" not in tools
            assert "podman" not in tools
            assert "curl" not in tools
            assert "pytest" in tools

    @pytest.mark.asyncio
    async def test_execute_uses_code_only_tools(self, config, ctx):
        """Execute step must also use CODE_ONLY_TOOLS."""
        from dev.pipeline.steps import step_execute

        with patch("dev.pipeline.steps.run_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = MagicMock(
                exit_code=0,
                num_turns=10,
                cost_usd=1.00,
                duration_ms=60000,
                output="Done",
                permission_denials=[],
            )
            await step_execute(config, ctx)

            call_kwargs = mock_claude.call_args[1]
            tools = call_kwargs.get("allowed_tools", "")
            assert "mock_ubus" not in tools
            assert "podman" not in tools


class TestJunkFileCleanup:
    """Test that junk files are detected and removed."""

    def test_junk_files_list_complete(self):
        """All known junk files should be in the list."""
        from dev.pipeline.steps import _JUNK_FILES

        expected = [
            "CLAUDE.md",
            ".pre-commit-config.yaml",
            ".plan.md",
            ".diagnostics.txt",
            ".ha-entities.json",
            ".screenshot-runner.py",
            ".commit_msg",
            "latest",
            ".claude/settings.json",
        ]
        for f in expected:
            assert f in _JUNK_FILES, f"{f} missing from _JUNK_FILES"

    def test_clean_junk_detects_files(self):
        """_clean_junk_files should detect junk in the diff."""
        from dev.pipeline.steps import _JUNK_FILES

        # Simulate a diff that includes junk
        diff_output = "CLAUDE.md\ncustom_components/wrtmanager/sensor.py\n.plan.md\n"
        junk = [f for f in diff_output.splitlines() if f.strip() in _JUNK_FILES]
        assert "CLAUDE.md" in junk
        assert ".plan.md" in junk
        assert "custom_components/wrtmanager/sensor.py" not in junk
