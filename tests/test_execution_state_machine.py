"""Tests for Execution State Machine (Task R1.2)."""

import pytest

from core.execution.models import (
    Execution,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
    VerificationResult,
)
from core.execution.state import (
    ExecutionStateMachine,
    InvalidStateTransitionError,
    VerificationRequiredError,
)


@pytest.fixture
def base_execution():
    req = ExecutionRequest(project_id="proj_state_test", prompt="Analyze repo")
    return Execution(project_id="proj_state_test", request=req)


def test_standard_lifecycle_to_completion(base_execution):
    """Verify happy path transition sequence from CREATED to COMPLETED."""
    events = []
    sm = ExecutionStateMachine(base_execution, event_sink=events.append)

    assert sm.status == ExecutionStatus.CREATED
    assert base_execution.started_at is None
    assert base_execution.completed_at is None

    # Step 1: Context building
    sm.transition(ExecutionStatus.CONTEXT_BUILDING)
    assert sm.status == ExecutionStatus.CONTEXT_BUILDING

    # Step 2: Routing
    sm.transition(ExecutionStatus.ROUTING)
    assert sm.status == ExecutionStatus.ROUTING

    # Step 3: Policy check
    sm.transition(ExecutionStatus.POLICY_CHECK)
    assert sm.status == ExecutionStatus.POLICY_CHECK

    # Step 4: Budget check
    sm.transition(ExecutionStatus.BUDGET_CHECK)
    assert sm.status == ExecutionStatus.BUDGET_CHECK

    # Step 5: Ready
    sm.transition(ExecutionStatus.READY)
    assert sm.status == ExecutionStatus.READY

    # Step 6: Running (should set started_at)
    sm.transition(ExecutionStatus.RUNNING)
    assert sm.status == ExecutionStatus.RUNNING
    assert base_execution.started_at is not None

    # Step 7: Verifying
    sm.transition(ExecutionStatus.VERIFYING)
    assert sm.status == ExecutionStatus.VERIFYING

    # Step 8: Completed with passing verification
    verification = VerificationResult(passed=True, strategy="test")
    sm.transition(ExecutionStatus.COMPLETED, verification=verification)
    assert sm.status == ExecutionStatus.COMPLETED
    assert base_execution.completed_at is not None
    assert sm.is_terminal is True

    # Events sequence monotonicity
    assert len(events) == 8
    for i, evt in enumerate(events):
        assert evt.sequence_num == i
        assert evt.event_type == ExecutionEventType.STATE_CHANGE


def test_completed_requires_passing_verification(base_execution):
    """Verify acceptance criterion: COMPLETED strictly requires a passing verification result."""
    sm = ExecutionStateMachine(base_execution)
    sm.transition(ExecutionStatus.CONTEXT_BUILDING)
    sm.transition(ExecutionStatus.ROUTING)
    sm.transition(ExecutionStatus.POLICY_CHECK)
    sm.transition(ExecutionStatus.BUDGET_CHECK)
    sm.transition(ExecutionStatus.READY)
    sm.transition(ExecutionStatus.RUNNING)
    sm.transition(ExecutionStatus.VERIFYING)

    # 1. Attempt COMPLETED without verification
    with pytest.raises(VerificationRequiredError, match="requires a VerificationResult"):
        sm.transition(ExecutionStatus.COMPLETED)

    # 2. Attempt COMPLETED with failed verification
    failing_v = VerificationResult(passed=False, error="Schema error")
    with pytest.raises(VerificationRequiredError, match="verification failed"):
        sm.transition(ExecutionStatus.COMPLETED, verification=failing_v)

    # State remains VERIFYING
    assert sm.status == ExecutionStatus.VERIFYING

    # Transitioning to FAILED is valid on verification failure
    sm.transition(ExecutionStatus.FAILED, error_code="VERIFY_ERR", error_message="Schema error")
    assert sm.status == ExecutionStatus.FAILED
    assert sm.is_terminal is True


def test_illegal_state_transition_rejection(base_execution):
    """Verify illegal transitions raise InvalidStateTransitionError."""
    sm = ExecutionStateMachine(base_execution)

    # Cannot skip directly from CREATED to COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(ExecutionStatus.COMPLETED, verification=VerificationResult(passed=True))

    # Cannot skip directly from CREATED to RUNNING
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(ExecutionStatus.RUNNING)


def test_terminal_states_are_immutable(base_execution):
    """Verify that once terminal, no further transitions are allowed."""
    sm = ExecutionStateMachine(base_execution)
    sm.transition(ExecutionStatus.CANCELLED, reason="User cancelled early")
    assert sm.status == ExecutionStatus.CANCELLED
    assert sm.is_terminal is True

    # Attempt any transition from CANCELLED
    for target in ExecutionStatus:
        with pytest.raises(InvalidStateTransitionError, match="already in terminal state"):
            sm.transition(target)


def test_cancellation_from_running(base_execution):
    """Verify cancelling from RUNNING records completed_at and sets CANCELLED."""
    sm = ExecutionStateMachine(base_execution)
    sm.transition(ExecutionStatus.ROUTING)
    sm.transition(ExecutionStatus.POLICY_CHECK)
    sm.transition(ExecutionStatus.BUDGET_CHECK)
    sm.transition(ExecutionStatus.READY)
    sm.transition(ExecutionStatus.RUNNING)
    assert base_execution.started_at is not None

    sm.transition(ExecutionStatus.CANCELLED, reason="Stop requested by Nadir")
    assert sm.status == ExecutionStatus.CANCELLED
    assert base_execution.completed_at is not None


def advance_to_approval(sm: ExecutionStateMachine) -> None:
    sm.transition(ExecutionStatus.CONTEXT_BUILDING)
    sm.transition(ExecutionStatus.ROUTING)
    sm.transition(ExecutionStatus.POLICY_CHECK)
    sm.transition(ExecutionStatus.WAITING_FOR_APPROVAL)


def advance_to_paused(sm: ExecutionStateMachine) -> None:
    sm.transition(ExecutionStatus.CONTEXT_BUILDING)
    sm.transition(ExecutionStatus.ROUTING)
    sm.transition(ExecutionStatus.POLICY_CHECK)
    sm.transition(ExecutionStatus.BUDGET_CHECK)
    sm.transition(ExecutionStatus.READY)
    sm.transition(ExecutionStatus.RUNNING)
    sm.transition(ExecutionStatus.PAUSED)


def test_waiting_for_approval_and_resumption(base_execution):
    """Verify approval gate flow: POLICY_CHECK -> WAITING_FOR_APPROVAL -> all resume and abort targets."""
    # 1. WAITING_FOR_APPROVAL -> RUNNING
    sm1 = ExecutionStateMachine(base_execution)
    advance_to_approval(sm1)
    sm1.transition(ExecutionStatus.RUNNING)
    assert sm1.status == ExecutionStatus.RUNNING

    # 2. WAITING_FOR_APPROVAL -> READY
    req2 = ExecutionRequest(project_id="p2", prompt="test")
    sm2 = ExecutionStateMachine(Execution(project_id="p2", request=req2))
    advance_to_approval(sm2)
    sm2.transition(ExecutionStatus.READY)
    assert sm2.status == ExecutionStatus.READY

    # 3. WAITING_FOR_APPROVAL -> QUEUED
    req3 = ExecutionRequest(project_id="p3", prompt="test")
    sm3 = ExecutionStateMachine(Execution(project_id="p3", request=req3))
    advance_to_approval(sm3)
    sm3.transition(ExecutionStatus.QUEUED)
    assert sm3.status == ExecutionStatus.QUEUED

    # 4. WAITING_FOR_APPROVAL -> BLOCKED (rejected by operator)
    req4 = ExecutionRequest(project_id="p4", prompt="test")
    sm4 = ExecutionStateMachine(Execution(project_id="p4", request=req4))
    advance_to_approval(sm4)
    sm4.transition(ExecutionStatus.BLOCKED, reason="Rejected by operator")
    assert sm4.status == ExecutionStatus.BLOCKED

    # 5. WAITING_FOR_APPROVAL -> CANCELLED
    req5 = ExecutionRequest(project_id="p5", prompt="test")
    sm5 = ExecutionStateMachine(Execution(project_id="p5", request=req5))
    advance_to_approval(sm5)
    sm5.transition(ExecutionStatus.CANCELLED)
    assert sm5.status == ExecutionStatus.CANCELLED

    # 6. WAITING_FOR_APPROVAL -> FAILED
    req6 = ExecutionRequest(project_id="p6", prompt="test")
    sm6 = ExecutionStateMachine(Execution(project_id="p6", request=req6))
    advance_to_approval(sm6)
    sm6.transition(ExecutionStatus.FAILED, error_message="Expired")
    assert sm6.status == ExecutionStatus.FAILED


def test_paused_resumption_and_abort_paths(base_execution):
    """Verify PAUSED state supports resume (READY, QUEUED, RUNNING) and abort (CANCELLED, FAILED)."""
    # 1. PAUSED -> RUNNING
    sm1 = ExecutionStateMachine(base_execution)
    advance_to_paused(sm1)
    sm1.transition(ExecutionStatus.RUNNING)
    assert sm1.status == ExecutionStatus.RUNNING

    # 2. PAUSED -> READY
    req2 = ExecutionRequest(project_id="p2", prompt="test")
    sm2 = ExecutionStateMachine(Execution(project_id="p2", request=req2))
    advance_to_paused(sm2)
    sm2.transition(ExecutionStatus.READY)
    assert sm2.status == ExecutionStatus.READY

    # 3. PAUSED -> QUEUED
    req3 = ExecutionRequest(project_id="p3", prompt="test")
    sm3 = ExecutionStateMachine(Execution(project_id="p3", request=req3))
    advance_to_paused(sm3)
    sm3.transition(ExecutionStatus.QUEUED)
    assert sm3.status == ExecutionStatus.QUEUED

    # 4. PAUSED -> CANCELLED
    req4 = ExecutionRequest(project_id="p4", prompt="test")
    sm4 = ExecutionStateMachine(Execution(project_id="p4", request=req4))
    advance_to_paused(sm4)
    sm4.transition(ExecutionStatus.CANCELLED)
    assert sm4.status == ExecutionStatus.CANCELLED

    # 5. PAUSED -> FAILED
    req5 = ExecutionRequest(project_id="p5", prompt="test")
    sm5 = ExecutionStateMachine(Execution(project_id="p5", request=req5))
    advance_to_paused(sm5)
    sm5.transition(ExecutionStatus.FAILED, error_message="Worker timeout while paused")
    assert sm5.status == ExecutionStatus.FAILED
