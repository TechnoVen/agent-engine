"""Tests for ExecutionCoordinator Service (Task R1.3)."""

import asyncio
import pytest

from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
    RoutingTier,
)
from core.safety.policy import PolicyEngine, PolicyRule
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import BudgetConfig, CostTracker


@pytest.fixture
def coordinator_env(tmp_path):
    """Provide an isolated ExecutionCoordinator environment."""
    db_path = str(tmp_path / "coordinator_test.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)
    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
    )
    return coordinator, storage, policy_engine, cost_tracker


@pytest.mark.anyio
async def test_coordinator_full_happy_path(coordinator_env):
    """Verify standard execution passes through all 10 phases to COMPLETED."""
    coordinator, storage, _, _ = coordinator_env

    events = []
    req = ExecutionRequest(
        project_id="proj_coord_test",
        session_id="sess_1",
        prompt="Explain quantum computing in simple terms",
        target_tier=RoutingTier.MID,
    )

    result = await coordinator.execute(req, event_listener=events.append)

    assert result.status == ExecutionStatus.COMPLETED
    assert result.outputs is not None
    assert "response" in result.outputs
    assert result.total_tokens > 0
    assert result.total_cost_usd >= 0.0
    assert result.verification is not None
    assert result.verification.passed is True

    # Verify execution is persisted in storage
    stored = storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["total_cost_usd"] == result.total_cost_usd

    # Verify events stream is persisted
    stored_events = storage.get_execution_events(result.execution_id)
    assert len(stored_events) > 0

    # Verify event types observed
    event_types = [e.event_type for e in events]
    assert ExecutionEventType.STATE_CHANGE in event_types
    assert ExecutionEventType.ROUTING_RESOLVED in event_types
    assert ExecutionEventType.OUTPUT_CHUNK in event_types
    assert ExecutionEventType.VERIFICATION_STARTED in event_types
    assert ExecutionEventType.VERIFICATION_COMPLETED in event_types


@pytest.mark.anyio
async def test_coordinator_policy_preflight_blocking(coordinator_env):
    """Verify that dangerous operations are blocked at Policy Pre-Flight phase."""
    coordinator, storage, policy_engine, _ = coordinator_env

    # Add blocking rule
    rule = PolicyRule(
        id="block_rm_rf",
        name="Block destructive remove",
        description="Prevent rm -rf commands",
        match_type="keyword",
        pattern="rm -rf /",
        action="block",
        reason="Catastrophic command detected",
    )
    policy_engine.add_rule(rule)

    req = ExecutionRequest(
        project_id="proj_blocked",
        prompt="Run cleanup: rm -rf /",
        inputs={"tool_name": "bash", "tool_args": {"command": "rm -rf /"}},
    )

    result = await coordinator.execute(req)

    assert result.status == ExecutionStatus.BLOCKED
    assert "Catastrophic command detected" in (result.error or "")

    stored = storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["status"] == "blocked"
    assert stored["error_code"] == "POLICY_BLOCKED"


@pytest.mark.anyio
async def test_coordinator_budget_check_blocking(coordinator_env):
    """Verify that exceeding project budget ceiling halts execution."""
    coordinator, storage, _, cost_tracker = coordinator_env

    # Set project budget to $1.00
    budget = BudgetConfig(project="proj_budget_test", monthly_budget_usd=1.0)
    cost_tracker.set_budget(budget)

    # Record past spend of $1.50 (150% threshold)
    storage.record_cost(
        agent_name="tester",
        model_name="gpt-4o",
        prompt_tokens=100000,
        completion_tokens=100000,
        cost_usd=1.50,
        project="proj_budget_test",
    )

    req = ExecutionRequest(
        project_id="proj_budget_test",
        prompt="Analyze data",
    )

    result = await coordinator.execute(req)

    assert result.status == ExecutionStatus.BLOCKED
    assert "Monthly budget limit reached" in (result.error or "")


@pytest.mark.anyio
async def test_coordinator_human_approval_staging(coordinator_env):
    """Verify that staged operations transition to WAITING_FOR_APPROVAL."""
    coordinator, storage, policy_engine, _ = coordinator_env

    # Add staging rule
    rule = PolicyRule(
        id="stage_git_push",
        name="Stage Git Push",
        description="Require confirmation before push",
        match_type="keyword",
        pattern="git push",
        action="stage",
        reason="Remote repository modification requires approval",
    )
    policy_engine.add_rule(rule)

    req = ExecutionRequest(
        project_id="proj_stage_test",
        prompt="Push branch to origin",
        inputs={"tool_name": "bash", "tool_args": {"command": "git push origin main"}},
    )

    result = await coordinator.execute(req)

    assert result.status == ExecutionStatus.WAITING_FOR_APPROVAL
    assert result.outputs.get("approval_required") is True

    stored = storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["status"] == "waiting_for_approval"


@pytest.mark.anyio
async def test_coordinator_verification_failure_halts_to_failed(coordinator_env):
    """Verify that failed output verification transitions execution to FAILED."""
    coordinator, storage, _, _ = coordinator_env

    # Supply a dispatch override that yields empty output (fails verification)
    coordinator._dispatch_override = lambda ctx, tier, prov, model: {}

    req = ExecutionRequest(
        project_id="proj_empty_test",
        prompt="Produce data",
    )

    result = await coordinator.execute(req)

    assert result.status == ExecutionStatus.FAILED
    assert "empty outputs" in (result.error or "")

    stored = storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["status"] == "failed"
    assert stored["error_code"] == "VERIFICATION_FAILED"


@pytest.mark.anyio
async def test_coordinator_cancellation_token(coordinator_env):
    """Verify in-flight cancellation terminates execution as CANCELLED."""
    coordinator, storage, _, _ = coordinator_env

    cancel_event = asyncio.Event()
    cancel_event.set()  # Cancel immediately

    req = ExecutionRequest(
        project_id="proj_cancel",
        prompt="Long running generation",
    )

    result = await coordinator.execute(req, cancellation_token=cancel_event)

    assert result.status == ExecutionStatus.CANCELLED

    stored = storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["status"] == "cancelled"
