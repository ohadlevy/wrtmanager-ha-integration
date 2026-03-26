"""Tests for the pipeline engine state machine."""

import asyncio

import pytest

from dev.pipeline.engine import Pipeline, RunConfig, RunState


@pytest.fixture
def config():
    return RunConfig(issue_number=42)


@pytest.fixture
def pipeline(config):
    return Pipeline(config)


class TestRunState:
    def test_states_are_strings(self):
        assert RunState.CREATED == "created"
        assert RunState.PASSED == "passed"

    def test_terminal_states(self):
        terminal = {RunState.PASSED, RunState.FAILED, RunState.ERROR, RunState.CANCELLED}
        for s in terminal:
            assert s in RunState.__members__.values()


class TestPipelineTransitions:
    def test_valid_transition(self, pipeline):
        pipeline._transition(RunState.SETTING_UP)
        assert pipeline.state == RunState.SETTING_UP

    def test_invalid_transition_raises(self, pipeline):
        with pytest.raises(ValueError, match="Invalid transition"):
            pipeline._transition(RunState.EXECUTING)

    def test_error_always_valid(self, pipeline):
        """ERROR is reachable from any state."""
        pipeline._transition(RunState.ERROR)
        assert pipeline.state == RunState.ERROR

    def test_cancelled_always_valid(self, pipeline):
        pipeline._transition(RunState.CANCELLED)
        assert pipeline.state == RunState.CANCELLED

    def test_transition_notifies_listeners(self, pipeline):
        transitions = []
        pipeline.on_transition(lambda old, new: transitions.append((old, new)))
        pipeline._transition(RunState.SETTING_UP)
        assert transitions == [(RunState.CREATED, RunState.SETTING_UP)]

    def test_listener_error_doesnt_break_pipeline(self, pipeline):
        def bad_listener(old, new):
            raise RuntimeError("boom")

        pipeline.on_transition(bad_listener)
        pipeline._transition(RunState.SETTING_UP)  # should not raise
        assert pipeline.state == RunState.SETTING_UP


class TestPipelineRun:
    @pytest.mark.asyncio
    async def test_simple_pass(self, pipeline):
        """Pipeline goes through all steps and reaches PASSED."""

        async def setup(cfg, ctx):
            return RunState.STARTING_ENV

        async def start_env(cfg, ctx):
            return RunState.EXECUTING

        async def execute(cfg, ctx):
            return RunState.CODE_REVIEW

        async def code_review(cfg, ctx):
            return RunState.RESTARTING_HA

        async def restart_ha(cfg, ctx):
            return RunState.WAITING_ENTITIES

        async def wait_entities(cfg, ctx):
            return RunState.TAKING_SCREENSHOTS

        async def screenshots(cfg, ctx):
            return RunState.VISUAL_REVIEW

        async def visual_review(cfg, ctx):
            return RunState.CREATING_PR

        async def create_pr(cfg, ctx):
            return RunState.PASSED

        pipeline.register_step(RunState.CREATED, setup)
        pipeline.register_step(RunState.SETTING_UP, start_env)
        pipeline.register_step(RunState.STARTING_ENV, execute)
        pipeline.register_step(RunState.EXECUTING, code_review)
        pipeline.register_step(RunState.CODE_REVIEW, restart_ha)
        pipeline.register_step(RunState.RESTARTING_HA, wait_entities)
        pipeline.register_step(RunState.WAITING_ENTITIES, screenshots)
        pipeline.register_step(RunState.TAKING_SCREENSHOTS, visual_review)
        pipeline.register_step(RunState.VISUAL_REVIEW, create_pr)
        pipeline.register_step(
            RunState.CREATING_PR, lambda c, x: asyncio.coroutine(lambda: RunState.PASSED)()
        )

        # Simpler: just register through CREATING_PR
        p = Pipeline(pipeline.config)
        steps = [
            (RunState.CREATED, RunState.SETTING_UP),
            (RunState.SETTING_UP, RunState.STARTING_ENV),
            (RunState.STARTING_ENV, RunState.EXECUTING),
            (RunState.EXECUTING, RunState.CODE_REVIEW),
            (RunState.CODE_REVIEW, RunState.RESTARTING_HA),
            (RunState.RESTARTING_HA, RunState.WAITING_ENTITIES),
            (RunState.WAITING_ENTITIES, RunState.TAKING_SCREENSHOTS),
            (RunState.TAKING_SCREENSHOTS, RunState.VISUAL_REVIEW),
            (RunState.VISUAL_REVIEW, RunState.CREATING_PR),
            (RunState.CREATING_PR, RunState.PASSED),
        ]
        for current, next_state in steps:

            async def step(cfg, ctx, ns=next_state):
                return ns

            p.register_step(current, step)

        result = await p.run()
        assert result == RunState.PASSED

    @pytest.mark.asyncio
    async def test_fix_loop(self, pipeline):
        """Pipeline goes through fix round and back to review."""
        call_count = {"visual_review": 0}

        async def noop(cfg, ctx):
            state_map = {
                RunState.CREATED: RunState.STARTING_ENV,
                RunState.STARTING_ENV: RunState.EXECUTING,
                RunState.EXECUTING: RunState.CODE_REVIEW,
                RunState.CODE_REVIEW: RunState.RESTARTING_HA,
                RunState.RESTARTING_HA: RunState.WAITING_ENTITIES,
                RunState.WAITING_ENTITIES: RunState.TAKING_SCREENSHOTS,
                RunState.TAKING_SCREENSHOTS: RunState.VISUAL_REVIEW,
            }
            return state_map.get(pipeline.state, RunState.ERROR)

        async def visual_review(cfg, ctx):
            call_count["visual_review"] += 1
            if call_count["visual_review"] == 1:
                return RunState.FIXING  # first round: FAIL
            return RunState.CREATING_PR  # second round: PASS

        async def fix(cfg, ctx):
            return RunState.RESTARTING_HA

        async def create_pr(cfg, ctx):
            return RunState.PASSED

        for state in [
            RunState.CREATED,
            RunState.STARTING_ENV,
            RunState.EXECUTING,
            RunState.CODE_REVIEW,
            RunState.RESTARTING_HA,
            RunState.WAITING_ENTITIES,
            RunState.TAKING_SCREENSHOTS,
        ]:
            pipeline.register_step(state, noop)

        pipeline.register_step(RunState.VISUAL_REVIEW, visual_review)
        pipeline.register_step(RunState.FIXING, fix)
        pipeline.register_step(RunState.CREATING_PR, create_pr)

        result = await pipeline.run()
        assert result == RunState.PASSED
        assert call_count["visual_review"] == 2

    @pytest.mark.asyncio
    async def test_step_error_transitions_to_error(self, pipeline):
        async def bad_step(cfg, ctx):
            raise RuntimeError("something broke")

        pipeline.register_step(RunState.CREATED, bad_step)
        result = await pipeline.run()
        assert result == RunState.ERROR
        assert "something broke" in pipeline.ctx.error

    @pytest.mark.asyncio
    async def test_step_timeout(self, config):
        config.claude_timeout = 1  # 1 second

        p = Pipeline(config)

        async def slow_step(cfg, ctx):
            await asyncio.sleep(10)
            return RunState.SETTING_UP

        # Use EXECUTING state which has claude_timeout
        async def to_exec(cfg, ctx):
            return RunState.STARTING_ENV

        async def to_exec2(cfg, ctx):
            return RunState.EXECUTING

        p.register_step(RunState.CREATED, to_exec)
        p.register_step(RunState.SETTING_UP, to_exec2)
        p.register_step(RunState.STARTING_ENV, to_exec2)
        p.register_step(RunState.EXECUTING, slow_step)

        # Need to get to EXECUTING first
        p2 = Pipeline(config)

        async def fast_setup(cfg, ctx):
            return RunState.STARTING_ENV

        async def fast_env(cfg, ctx):
            return RunState.EXECUTING

        p2.register_step(RunState.CREATED, fast_setup)
        p2.register_step(RunState.SETTING_UP, fast_env)
        p2.register_step(RunState.STARTING_ENV, fast_env)
        p2.register_step(RunState.EXECUTING, slow_step)

        result = await p2.run()
        assert result == RunState.ERROR
        assert "Timeout" in p2.ctx.error

    @pytest.mark.asyncio
    async def test_missing_handler(self, pipeline):
        async def setup(cfg, ctx):
            return RunState.SETTING_UP

        pipeline.register_step(RunState.CREATED, setup)
        # No handler for SETTING_UP

        result = await pipeline.run()
        assert result == RunState.ERROR
        assert "No handler" in pipeline.ctx.error

    @pytest.mark.asyncio
    async def test_plan_pending_stops(self, pipeline):
        """PLAN_PENDING is a terminal state (waits for human)."""

        async def setup(cfg, ctx):
            return RunState.SETTING_UP

        async def to_planning(cfg, ctx):
            return RunState.PLANNING

        async def plan(cfg, ctx):
            return RunState.PLAN_PENDING

        pipeline.register_step(RunState.CREATED, setup)
        pipeline.register_step(RunState.SETTING_UP, to_planning)
        pipeline.register_step(RunState.PLANNING, plan)

        result = await pipeline.run()
        assert result == RunState.PLAN_PENDING

    @pytest.mark.asyncio
    async def test_max_review_rounds(self, pipeline):
        """Pipeline fails after max review rounds."""
        pipeline.config.max_review_rounds = 2

        async def to_review(cfg, ctx):
            state_map = {
                RunState.CREATED: RunState.STARTING_ENV,
                RunState.STARTING_ENV: RunState.EXECUTING,
                RunState.EXECUTING: RunState.CODE_REVIEW,
                RunState.CODE_REVIEW: RunState.RESTARTING_HA,
                RunState.RESTARTING_HA: RunState.WAITING_ENTITIES,
                RunState.WAITING_ENTITIES: RunState.TAKING_SCREENSHOTS,
                RunState.TAKING_SCREENSHOTS: RunState.VISUAL_REVIEW,
            }
            return state_map.get(pipeline.state, RunState.ERROR)

        async def always_fail_review(cfg, ctx):
            ctx.review_round += 1
            if ctx.review_round >= cfg.max_review_rounds:
                return RunState.FAILED
            return RunState.FIXING

        async def fix(cfg, ctx):
            return RunState.RESTARTING_HA

        for state in [
            RunState.CREATED,
            RunState.STARTING_ENV,
            RunState.EXECUTING,
            RunState.CODE_REVIEW,
            RunState.RESTARTING_HA,
            RunState.WAITING_ENTITIES,
            RunState.TAKING_SCREENSHOTS,
        ]:
            pipeline.register_step(state, to_review)

        pipeline.register_step(RunState.VISUAL_REVIEW, always_fail_review)
        pipeline.register_step(RunState.FIXING, fix)

        result = await pipeline.run()
        assert result == RunState.FAILED
        assert pipeline.ctx.review_round == 2
