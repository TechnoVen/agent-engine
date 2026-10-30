"""Tests for Canonical Execution Domain Models (Task R1.1)."""

import pytest
from pydantic import ValidationError

from core.execution.models import (
    Execution,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
    RoutingTier,
    VerificationResult,
    generate_event_id,
    generate_execution_id,
    generate_request_id,
)


def test_unique_prefixed_identifiers():
    """Verify generated IDs have correct prefixes and are unique."""
    exec_id_1 = generate_execution_id()
    exec_id_2 = generate_execution_id()
    assert exec_id_1.startswith("exec_")
    assert exec_id_2.startswith("exec_")
    assert exec_id_1 != exec_id_2

    req_id_1 = generate_request_id()
    req_id_2 = generate_request_id()
    assert req_id_1.startswith("req_")
    assert req_id_2.startswith("req_")
    assert req_id_1 != req_id_2

    evt_id_1 = generate_event_id()
    evt_id_2 = generate_event_id()
    assert evt_id_1.startswith("evt_")
    assert evt_id_2.startswith("evt_")
    assert evt_id_1 != evt_id_2


def test_execution_request_immutability():
    """Verify ExecutionRequest is frozen and rejects field mutation."""
    req = ExecutionRequest(
        project_id="proj_test",
        prompt="Solve problem",
        task_type="chat",
    )
    assert req.project_id == "proj_test"
    assert req.prompt == "Solve problem"
    assert req.id.startswith("req_")

    with pytest.raises(ValidationError):
        req.prompt = "Modified prompt"


def test_execution_status_enum_values():
    """Verify ExecutionStatus enum covers all required lifecycle phases."""
    expected = {
        "created",
        "context_building",
        "routing",
        "policy_check",
        "budget_check",
        "planning",
        "ready",
        "queued",
        "running",
        "waiting_for_approval",
        "paused",
        "verifying",
        "completed",
        "partial",
        "blocked",
        "failed",
        "timed_out",
        "cancelled",
    }
    actual = {s.value for s in ExecutionStatus}
    assert expected == actual


def test_routing_tier_enum_values():
    """Verify RoutingTier covers code, cache, local, mid, frontier, human."""
    expected = {"code", "cache", "local", "mid", "frontier", "human"}
    actual = {t.value for t in RoutingTier}
    assert expected == actual


def test_execution_event_serialization():
    """Verify ExecutionEvent round-trip serialization."""
    event = ExecutionEvent(
        execution_id="exec_123",
        sequence_num=0,
        event_type=ExecutionEventType.STATE_CHANGE,
        payload={"from_status": "created", "to_status": "context_building"},
    )
    data = event.model_dump()
    assert data["execution_id"] == "exec_123"
    assert data["sequence_num"] == 0
    assert data["event_type"] == "state_change"
    assert data["payload"]["to_status"] == "context_building"

    restored = ExecutionEvent.model_validate(data)
    assert restored.id == event.id
    assert restored.execution_id == event.execution_id


def test_execution_entity_defaults_and_validation():
    """Verify Execution entity fields, defaults, and json round-trip."""
    req = ExecutionRequest(project_id="proj_alpha", prompt="Test")
    execution = Execution(
        project_id="proj_alpha",
        request=req,
    )
    assert execution.id.startswith("exec_")
    assert execution.status == ExecutionStatus.CREATED
    assert execution.input_tokens == 0
    assert execution.output_tokens == 0
    assert execution.total_cost_usd == 0.0

    dumped = execution.model_dump()
    restored = Execution.model_validate(dumped)
    assert restored.id == execution.id
    assert restored.request.prompt == "Test"


def test_verification_result_passed_and_failed():
    """Verify VerificationResult model integrity."""
    v_pass = VerificationResult(
        passed=True, strategy="schema", checks=[{"name": "check1", "passed": True}]
    )
    assert v_pass.passed is True
    assert v_pass.error is None

    v_fail = VerificationResult(
        passed=False,
        strategy="assertion",
        checks=[{"name": "check1", "passed": False}],
        error="Output assertion failed",
    )
    assert v_fail.passed is False
    assert v_fail.error == "Output assertion failed"
