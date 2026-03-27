"""Pipeline engine — state machine for autonomous issue resolution."""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)


class RunState(str, Enum):
    """Pipeline run states."""

    CREATED = "created"
    SETTING_UP = "setting_up"
    PLANNING = "planning"
    PLAN_PENDING = "plan_pending"  # waiting for human approval
    STARTING_ENV = "starting_env"
    EXECUTING = "executing"
    CODE_REVIEW = "code_review"
    RESTARTING_HA = "restarting_ha"
    WAITING_ENTITIES = "waiting_entities"
    TAKING_SCREENSHOTS = "taking_screenshots"
    VISUAL_REVIEW = "visual_review"
    FIXING = "fixing"
    CREATING_PR = "creating_pr"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"


# Valid transitions
TRANSITIONS = {
    RunState.CREATED: [RunState.SETTING_UP, RunState.STARTING_ENV, RunState.PLANNING],
    RunState.SETTING_UP: [RunState.PLANNING, RunState.STARTING_ENV, RunState.ERROR],
    RunState.PLANNING: [RunState.PLAN_PENDING, RunState.ERROR],
    RunState.PLAN_PENDING: [
        RunState.STARTING_ENV,
        RunState.EXECUTING,
        RunState.RESTARTING_HA,
        RunState.TAKING_SCREENSHOTS,
        RunState.CREATING_PR,
        RunState.CANCELLED,
    ],
    RunState.STARTING_ENV: [RunState.EXECUTING, RunState.ERROR],
    RunState.EXECUTING: [RunState.CODE_REVIEW, RunState.ERROR],
    RunState.CODE_REVIEW: [RunState.RESTARTING_HA, RunState.ERROR],
    RunState.RESTARTING_HA: [RunState.WAITING_ENTITIES, RunState.ERROR],
    RunState.WAITING_ENTITIES: [RunState.TAKING_SCREENSHOTS, RunState.CREATING_PR, RunState.ERROR],
    RunState.TAKING_SCREENSHOTS: [RunState.VISUAL_REVIEW, RunState.ERROR],
    RunState.VISUAL_REVIEW: [
        RunState.CREATING_PR,  # PASS
        RunState.FIXING,  # FAIL/NEEDS_CHANGES
        RunState.FAILED,  # max rounds
        RunState.ERROR,
    ],
    RunState.FIXING: [RunState.RESTARTING_HA, RunState.FAILED, RunState.ERROR],
    RunState.CREATING_PR: [RunState.PASSED, RunState.ERROR],
}


@dataclass
class RunConfig:
    """Configuration for a pipeline run."""

    issue_number: int
    model: str = "claude-sonnet-4-6"
    branch_prefix: str = "feature"
    max_review_rounds: int = 3
    entity_wait_timeout: int = 60
    claude_timeout: int = 1800  # 30 min max per claude session
    repo_root: Path = field(default_factory=lambda: Path.cwd())


@dataclass
class RunContext:
    """Mutable state for a pipeline run."""

    run_id: Optional[int] = None
    worktree_path: Optional[Path] = None
    branch_name: Optional[str] = None
    ha_url: Optional[str] = None
    ha_port: Optional[int] = None
    ha_token: Optional[str] = None
    mock_pid: Optional[int] = None
    mock_ports: Optional[dict] = None
    plan_text: Optional[str] = None
    issue_title: Optional[str] = None
    issue_body: Optional[str] = None
    review_round: int = 0
    review_verdict: Optional[str] = None
    review_feedback: Optional[str] = None
    diagnostics: Optional[str] = None
    total_cost: float = 0.0
    error: Optional[str] = None
    pr_url: Optional[str] = None


StepFn = Callable[[RunConfig, RunContext], Coroutine[Any, Any, RunState]]


class Pipeline:
    """Pipeline state machine that drives a run through steps."""

    def __init__(self, config: RunConfig):
        self.config = config
        self.ctx = RunContext()
        self.state = RunState.CREATED
        self._steps: dict[RunState, StepFn] = {}
        self._listeners: list[Callable[[RunState, RunState], None]] = []

    def register_step(self, state: RunState, fn: StepFn):
        """Register a function to handle a pipeline state."""
        self._steps[state] = fn

    def on_transition(self, callback: Callable[[RunState, RunState], None]):
        """Register a callback for state transitions."""
        self._listeners.append(callback)

    def _transition(self, new_state: RunState):
        """Transition to a new state with validation."""
        valid = TRANSITIONS.get(self.state, [])
        if new_state not in valid and new_state not in (
            RunState.ERROR,
            RunState.CANCELLED,
        ):
            raise ValueError(f"Invalid transition: {self.state} → {new_state}. " f"Valid: {valid}")
        old_state = self.state
        self.state = new_state
        logger.info("State: %s → %s", old_state, new_state)
        for cb in self._listeners:
            try:
                cb(old_state, new_state)
            except Exception:
                logger.exception("Listener error on %s → %s", old_state, new_state)

    async def run(self) -> RunState:
        """Run the pipeline to completion."""
        terminal_states = {
            RunState.PASSED,
            RunState.FAILED,
            RunState.ERROR,
            RunState.CANCELLED,
            RunState.PLAN_PENDING,
        }

        while self.state not in terminal_states:
            step_fn = self._steps.get(self.state)
            if step_fn is None:
                logger.error("No handler for state %s", self.state)
                self._transition(RunState.ERROR)
                self.ctx.error = f"No handler registered for state {self.state}"
                break

            try:
                next_state = await asyncio.wait_for(
                    step_fn(self.config, self.ctx),
                    timeout=self._timeout_for_state(self.state),
                )
                self._transition(next_state)
            except asyncio.TimeoutError:
                logger.error("Timeout in state %s", self.state)
                self.ctx.error = f"Timeout in {self.state}"
                self._transition(RunState.ERROR)
            except asyncio.CancelledError:
                logger.info("Pipeline cancelled in state %s", self.state)
                self._transition(RunState.CANCELLED)
            except Exception as e:
                logger.exception("Error in state %s: %s", self.state, e)
                self.ctx.error = str(e)
                self._transition(RunState.ERROR)

        return self.state

    def _timeout_for_state(self, state: RunState) -> Optional[float]:
        """Per-state timeout in seconds."""
        timeouts = {
            RunState.SETTING_UP: 120,
            RunState.STARTING_ENV: 120,
            RunState.EXECUTING: self.config.claude_timeout,
            RunState.CODE_REVIEW: 300,
            RunState.RESTARTING_HA: 120,
            RunState.WAITING_ENTITIES: self.config.entity_wait_timeout + 10,
            RunState.TAKING_SCREENSHOTS: 300,
            RunState.VISUAL_REVIEW: 600,
            RunState.FIXING: self.config.claude_timeout,
            RunState.CREATING_PR: 60,
        }
        return timeouts.get(state)
