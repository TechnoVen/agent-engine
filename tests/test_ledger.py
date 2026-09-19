"""Authoritative Execution Ledger & Trace Tests (Task R1.11).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md, docs/EXECUTION_MODEL.md, docs/ROADMAP.md (R1.11)

Validates all 15 authoritative ledger requirements:
1. test_completed_execution_produces_full_trace
2. test_failed_execution_produces_error_trace
3. test_cancelled_execution_produces_cancellation_trace
4. test_partial_execution_reconstructs_available_events
5. test_event_ordering_strictly_monotonic
6. test_requested_vs_resolved_vs_actual_model
7. test_fallback_attempts_captured
8. test_context_provenance_records_hashes
9. test_usage_provenance_accuracy
10. test_artifacts_linked_by_id
11. test_zero_transient_dependencies
12. test_cross_project_read_rejection
13. test_ledger_immutability
14. test_ledger_persists_across_reopen
15. test_trace_matches_canonical_record_and_rest_endpoints
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import pytest
from fastapi.testclient import TestClient

from core.artifacts import (
    ArtifactService,
    ArtifactType,
)
from core.execution import (
    CancellationReason,
    ExecutionCoordinator,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
    RoutingTier,
)
from core.ledger import (
    CostProvenance,
    ExecutionLedgerService,
    LedgerSecurityError,
)
from core.storage.sqlite import SQLiteBackend
from services.python.server.api import (
    app,
    set_artifact_service,
    set_execution_coordinator,
    set_ledger_service,
)


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "ledger_test.db")
    backend = SQLiteBackend(db_path=db_path)
    backend.create_project(
        {
            "id": "proj_alpha",
            "name": "Project Alpha",
            "root_directory": str(tmp_path / "proj_alpha"),
            "instructions": "Be helpful, accurate, and concise.",
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    backend.create_project(
        {
            "id": "proj_beta",
            "name": "Project Beta",
            "root_directory": str(tmp_path / "proj_beta"),
            "instructions": "Beta instructions.",
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    return backend


@pytest.fixture
def artifact_service(tmp_path, storage):
    return ArtifactService(
        storage=storage,
        base_artifacts_dir=str(tmp_path / "artifacts"),
    )


@pytest.fixture
def ledger_service(storage, artifact_service):
    return ExecutionLedgerService(
        storage=storage,
        artifact_service=artifact_service,
    )


@pytest.fixture
def mock_dispatch():
    return lambda ctx, tier, prov, model: {
        "response": f"Processed prompt with {prov}/{model}",
        "status": "ok",
    }


@pytest.fixture
def coordinator(storage, artifact_service, mock_dispatch):
    return ExecutionCoordinator(
        storage=storage,
        artifact_service=artifact_service,
        dispatch_override=mock_dispatch,
    )


def test_completed_execution_produces_full_trace(coordinator, ledger_service):
    """Test 1: Completed execution reconstructs full authoritative trace."""
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Write a Python hello world",
        model_preference="mock_model",
        target_tier=RoutingTier.MID,
    )

    async def run_exec():
        return await coordinator.execute(req)

    result = asyncio.run(run_exec())
    assert result.status == ExecutionStatus.COMPLETED

    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.execution_id == result.execution_id
    assert trace.project_id == "proj_alpha"
    assert trace.status == ExecutionStatus.COMPLETED
    assert trace.started_at is not None
    assert trace.completed_at is not None
    assert trace.duration_ms >= 0.0

    # Also lookup by req.id works
    trace_by_req = ledger_service.get_execution_trace(req.id)
    assert trace_by_req is not None
    assert trace_by_req.execution_id == result.execution_id

    # Routing truth
    assert trace.routing.requested_model == "mock_model"
    assert trace.routing.requested_tier == "mid"
    assert trace.routing.resolved_model is not None
    assert trace.routing.actual_model is not None
    assert trace.routing.actual_provider is not None

    # Context provenance
    assert trace.context.project_root is not None
    assert trace.context.project_instructions_hash is not None

    # Usage truth
    assert trace.usage.total_tokens > 0
    assert trace.usage.cost_provenance in (
        CostProvenance.CALCULATED,
        CostProvenance.PROVIDER_REPORTED,
    )

    # Verification
    assert trace.verification is not None
    assert trace.verification.passed is True

    # Events stream
    event_types = [e.event_type for e in trace.events]
    assert ExecutionEventType.STATE_CHANGE.value in event_types
    assert ExecutionEventType.ROUTING_RESOLVED.value in event_types
    terminal_events = [
        e
        for e in trace.events
        if e.event_type == ExecutionEventType.STATE_CHANGE.value
        and e.payload.get("to_status") == "completed"
    ]
    assert len(terminal_events) == 1


def test_failed_execution_produces_error_trace(storage, artifact_service, ledger_service):
    """Test 2: Failed execution records error descriptor, error_code, and failed terminal state."""

    async def failing_dispatch(ctx, tier, prov, model):
        raise RuntimeError("Provider connection failed: HTTP 503")

    failing_coord = ExecutionCoordinator(
        storage=storage,
        artifact_service=artifact_service,
        dispatch_override=failing_dispatch,
    )
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Doomed task",
        model_preference="failure_test",
        target_tier=RoutingTier.MID,
    )

    async def run_exec():
        return await failing_coord.execute(req)

    result = asyncio.run(run_exec())
    assert result.status == ExecutionStatus.FAILED

    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.status == ExecutionStatus.FAILED
    assert trace.error is not None
    assert trace.error_code is not None
    assert len(trace.events) > 0

    terminal_event = trace.events[-1]
    assert terminal_event.event_type == ExecutionEventType.STATE_CHANGE.value
    assert terminal_event.payload.get("to_status") == "failed"


@pytest.mark.anyio
async def test_cancelled_execution_produces_cancellation_trace(tmp_path):
    """Test 3: Cancelled execution records actor, reason, cancelled terminal event, and partial artifact."""
    db_path = str(tmp_path / "cancel_trace.db")
    storage = SQLiteBackend(db_path=db_path)
    storage.create_project(
        {
            "id": "proj_alpha",
            "name": "Project Alpha",
            "root_directory": str(tmp_path / "proj_alpha"),
            "instructions": "Be helpful.",
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    art_service = ArtifactService(
        storage=storage,
        base_artifacts_dir=str(tmp_path / "artifacts"),
    )
    ledger_service = ExecutionLedgerService(storage=storage, artifact_service=art_service)

    started = asyncio.Event()

    async def slow_stream(ctx, tier, prov, model):
        yield "Chunk 1: First progress... "
        started.set()
        await asyncio.sleep(0.5)
        yield "Chunk 2: Should not arrive."

    coordinator = ExecutionCoordinator(
        storage=storage,
        artifact_service=art_service,
        dispatch_override=slow_stream,
    )

    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Stream me a poem",
        inputs={"stream": True},
        target_tier=RoutingTier.MID,
    )

    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(started.wait(), timeout=2.0)

    # Cancel execution
    coordinator.cancel(req.id, reason=CancellationReason.USER_REQUEST, actor="user:nadir")
    result = await asyncio.wait_for(task, timeout=2.0)
    assert result.status == ExecutionStatus.CANCELLED

    # Trace reconstruction
    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.status == ExecutionStatus.CANCELLED
    assert trace.actor == "user:nadir"
    assert trace.error_code == "CANCELLED"

    # Verify CANCELLED event
    cancel_events = [e for e in trace.events if e.event_type == ExecutionEventType.CANCELLED.value]
    assert len(cancel_events) >= 1
    assert cancel_events[0].payload.get("actor") == "user:nadir"
    assert cancel_events[0].payload.get("reason") == "user_request"

    # Verify partial output artifact linkage
    assert len(trace.artifacts) >= 1
    partial_art = trace.artifacts[0]
    assert "partial_output" in partial_art.name
    assert partial_art.status == "partial"


def test_partial_execution_reconstructs_available_events(storage, ledger_service):
    """Test 4: In-flight / partial execution reconstructs available events without fabrication."""
    exec_id = "exec_inflight_1"
    now_iso = datetime.now(timezone.utc).isoformat()
    storage.create_execution(
        {
            "id": exec_id,
            "project_id": "proj_alpha",
            "session_id": "sess_001",
            "status": "running",
            "request_json": json.dumps({"prompt": "Hello", "task_type": "chat"}),
            "provider": "ollama",
            "model": "llama3.2",
            "routing_tier": "local",
            "input_tokens": 12,
            "output_tokens": 0,
            "total_cost_usd": 0.0,
            "is_cost_estimated": 0,
            "started_at": now_iso,
            "completed_at": None,
            "created_at": now_iso,
        }
    )

    storage.record_execution_event(
        {
            "id": "evt_1",
            "execution_id": exec_id,
            "sequence_num": 0,
            "timestamp": now_iso,
            "event_type": "state_change",
            "payload_json": json.dumps({"from_status": None, "to_status": "created"}),
        }
    )
    storage.record_execution_event(
        {
            "id": "evt_2",
            "execution_id": exec_id,
            "sequence_num": 1,
            "timestamp": now_iso,
            "event_type": "state_change",
            "payload_json": json.dumps({"from_status": "created", "to_status": "running"}),
        }
    )

    trace = ledger_service.get_execution_trace(exec_id)
    assert trace is not None
    assert trace.status == ExecutionStatus.RUNNING
    assert trace.completed_at is None
    assert trace.verification is None
    assert len(trace.events) == 2
    assert [e.sequence_num for e in trace.events] == [0, 1]


def test_event_ordering_strictly_monotonic(coordinator, ledger_service):
    """Test 5: Event ordering in trace is strictly monotonic by sequence_num."""
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Explain sorting algorithms",
    )

    result = asyncio.run(coordinator.execute(req))
    assert result.status == ExecutionStatus.COMPLETED

    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert len(trace.events) >= 3

    seqs = [e.sequence_num for e in trace.events]
    assert seqs == sorted(seqs)
    for i in range(len(seqs) - 1):
        assert seqs[i] < seqs[i + 1]


def test_requested_vs_resolved_vs_actual_model(coordinator, ledger_service):
    """Test 6: Preserves requested model/tier vs resolved model vs actual model dispatched."""
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="What is the speed of light?",
        model_preference="anthropic/claude-3-5-sonnet",
        target_tier=RoutingTier.FRONTIER,
    )

    result = asyncio.run(coordinator.execute(req))

    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.routing.requested_model == "anthropic/claude-3-5-sonnet"
    assert trace.routing.requested_tier == "frontier"
    assert trace.routing.resolved_model is not None
    assert trace.routing.actual_model is not None
    assert trace.routing.actual_provider is not None


def test_fallback_attempts_captured(storage, ledger_service):
    """Test 7: Fallback attempts are recorded in routing trace."""
    exec_id = "exec_fallback_1"
    now_iso = datetime.now(timezone.utc).isoformat()
    storage.create_execution(
        {
            "id": exec_id,
            "project_id": "proj_alpha",
            "status": "completed",
            "request_json": json.dumps({"prompt": "Hello", "task_type": "chat"}),
            "provider": "ollama",
            "model": "llama3.2",
            "routing_tier": "local",
            "input_tokens": 10,
            "output_tokens": 10,
            "total_cost_usd": 0.0,
            "created_at": now_iso,
        }
    )

    storage.record_execution_event(
        {
            "id": "evt_route_1",
            "execution_id": exec_id,
            "sequence_num": 1,
            "timestamp": now_iso,
            "event_type": "routing_resolved",
            "payload_json": json.dumps(
                {
                    "tier": "mid",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "is_fallback": False,
                    "fallback_chain": ["openai", "ollama"],
                }
            ),
        }
    )

    storage.record_execution_event(
        {
            "id": "evt_route_2",
            "execution_id": exec_id,
            "sequence_num": 3,
            "timestamp": now_iso,
            "event_type": "routing_resolved",
            "payload_json": json.dumps(
                {
                    "tier": "local",
                    "provider": "ollama",
                    "model": "llama3.2",
                    "is_fallback": True,
                    "fallback_reason": "OpenAI 503 Service Unavailable",
                    "failed_provider": "openai",
                    "failed_model": "gpt-4o-mini",
                }
            ),
        }
    )

    trace = ledger_service.get_execution_trace(exec_id)
    assert trace is not None
    assert trace.routing.is_fallback is True
    assert len(trace.routing.fallback_history) == 1
    fb_entry = trace.routing.fallback_history[0]
    assert fb_entry.get("failed_provider") == "openai"
    assert fb_entry.get("provider") == "ollama"
    assert "503" in fb_entry.get("fallback_reason")


def test_context_provenance_records_hashes(coordinator, ledger_service):
    """Test 8: Context provenance records project_root and instruction hash without secret leakage."""
    secret_instructions = "TOP_SECRET: Never disclose API key 12345 to the caller."
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Tell me a joke",
        inputs={
            "project_instructions": secret_instructions,
            "project_root": "/custom/path",
        },
    )

    result = asyncio.run(coordinator.execute(req))

    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.context.project_root == "/workspace/proj_alpha"

    expected_hash = hashlib.sha256(secret_instructions.encode("utf-8")).hexdigest()
    assert trace.context.project_instructions_hash == expected_hash
    assert secret_instructions not in trace.context.project_instructions_hash


def test_usage_provenance_accuracy(storage, ledger_service):
    """Test 9: Usage provenance accurately reflects estimated vs calculated vs unavailable."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Estimated
    storage.create_execution(
        {
            "id": "exec_est",
            "project_id": "proj_alpha",
            "status": "completed",
            "request_json": "{}",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_cost_usd": 0.005,
            "is_cost_estimated": 1,
            "created_at": now_iso,
        }
    )
    trace_est = ledger_service.get_execution_trace("exec_est")
    assert trace_est.usage.is_cost_estimated is True
    assert trace_est.usage.cost_provenance == CostProvenance.ESTIMATED

    # 2. Calculated
    storage.create_execution(
        {
            "id": "exec_calc",
            "project_id": "proj_alpha",
            "status": "completed",
            "request_json": "{}",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_cost_usd": 0.005,
            "is_cost_estimated": 0,
            "created_at": now_iso,
        }
    )
    trace_calc = ledger_service.get_execution_trace("exec_calc")
    assert trace_calc.usage.is_cost_estimated is False
    assert trace_calc.usage.cost_provenance == CostProvenance.CALCULATED

    # 3. Unavailable
    storage.create_execution(
        {
            "id": "exec_unavail",
            "project_id": "proj_alpha",
            "status": "failed",
            "request_json": "{}",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_cost_usd": 0.0,
            "is_cost_estimated": 0,
            "created_at": now_iso,
        }
    )
    trace_unavail = ledger_service.get_execution_trace("exec_unavail")
    assert trace_unavail.usage.cost_provenance == CostProvenance.UNAVAILABLE


def test_artifacts_linked_by_id(storage, artifact_service, ledger_service):
    """Test 10: Artifacts produced are linked by ID and metadata reference in trace."""
    exec_id = "exec_art_link"
    now_iso = datetime.now(timezone.utc).isoformat()
    storage.create_execution(
        {
            "id": exec_id,
            "project_id": "proj_alpha",
            "status": "completed",
            "request_json": "{}",
            "created_at": now_iso,
        }
    )

    art1 = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id=exec_id,
        name="output.csv",
        content="a,b,c\n1,2,3\n",
        type=ArtifactType.DATA,
    )
    art2 = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id=exec_id,
        name="notes.txt",
        content="Important summary.",
        type=ArtifactType.TEXT,
    )

    trace = ledger_service.get_execution_trace(exec_id)
    assert trace is not None
    assert len(trace.artifacts) == 2
    art_ids = [a.id for a in trace.artifacts]
    assert art1.id in art_ids
    assert art2.id in art_ids
    assert any(
        a.name == "output.csv" and a.sha256_hash == art1.sha256_hash for a in trace.artifacts
    )


def test_zero_transient_dependencies(coordinator, storage, artifact_service):
    """Test 11: Trace projection works with pure SQLite read without in-memory coordinator state."""
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Tell me the capital of France",
    )

    result = asyncio.run(coordinator.execute(req))

    # Clear all in-memory coordinator state
    coordinator._active_executions.clear()
    coordinator._active_tokens.clear()

    fresh_ledger_service = ExecutionLedgerService(
        storage=storage, artifact_service=artifact_service
    )
    trace = fresh_ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.execution_id == result.execution_id
    assert trace.status == ExecutionStatus.COMPLETED


def test_cross_project_read_rejection(coordinator, ledger_service):
    """Test 12: Cross-project trace read is rejected with LedgerSecurityError."""
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Alpha secret task",
    )

    result = asyncio.run(coordinator.execute(req))

    # Matching project succeeds
    trace_ok = ledger_service.get_execution_trace(result.execution_id, project_id="proj_alpha")
    assert trace_ok is not None

    # Mismatched project raises LedgerSecurityError
    with pytest.raises(LedgerSecurityError, match="Scope boundary violation"):
        ledger_service.get_execution_trace(result.execution_id, project_id="proj_beta")


def test_ledger_immutability(coordinator, storage, ledger_service):
    """Test 13: Reading trace multiple times produces identical output and never mutates database."""
    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="Determinism test",
    )

    result = asyncio.run(coordinator.execute(req))

    conn = storage._get_connection()
    count_execs_before = conn.execute("SELECT count(*) FROM executions").fetchone()[0]
    count_events_before = conn.execute("SELECT count(*) FROM execution_events").fetchone()[0]
    count_arts_before = conn.execute("SELECT count(*) FROM artifacts").fetchone()[0]
    if not storage._is_memory:
        conn.close()

    trace1 = ledger_service.get_execution_trace(result.execution_id)
    trace2 = ledger_service.get_execution_trace(result.execution_id)
    trace3 = ledger_service.get_execution_trace(result.execution_id)

    assert trace1.model_dump() == trace2.model_dump() == trace3.model_dump()

    conn = storage._get_connection()
    count_execs_after = conn.execute("SELECT count(*) FROM executions").fetchone()[0]
    count_events_after = conn.execute("SELECT count(*) FROM execution_events").fetchone()[0]
    count_arts_after = conn.execute("SELECT count(*) FROM artifacts").fetchone()[0]
    if not storage._is_memory:
        conn.close()

    assert count_execs_before == count_execs_after
    assert count_events_before == count_events_after
    assert count_arts_before == count_arts_after


def test_ledger_persists_across_reopen(tmp_path, mock_dispatch):
    """Test 14: Trace reconstruction survives closing and reopening the SQLite database file."""
    db_file = str(tmp_path / "persistent_ledger.db")
    storage1 = SQLiteBackend(db_path=db_file)
    storage1.create_project(
        {
            "id": "proj_persist",
            "name": "Persist Proj",
            "root_directory": str(tmp_path / "persist"),
            "instructions": "Persistent instructions.",
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    art_service1 = ArtifactService(
        storage=storage1,
        base_artifacts_dir=str(tmp_path / "artifacts"),
    )
    coord1 = ExecutionCoordinator(
        storage=storage1,
        artifact_service=art_service1,
        dispatch_override=mock_dispatch,
    )

    req = ExecutionRequest(
        project_id="proj_persist",
        task_type="chat",
        prompt="Write a persistence check",
    )

    res = asyncio.run(coord1.execute(req))
    assert res.status == ExecutionStatus.COMPLETED

    # Close/discard instance 1
    del coord1
    del art_service1
    del storage1

    # Reopen brand new storage backend from the same file
    storage2 = SQLiteBackend(db_path=db_file)
    art_service2 = ArtifactService(
        storage=storage2,
        base_artifacts_dir=str(tmp_path / "artifacts"),
    )
    ledger_service2 = ExecutionLedgerService(storage=storage2, artifact_service=art_service2)

    trace = ledger_service2.get_execution_trace(res.execution_id)
    assert trace is not None
    assert trace.execution_id == res.execution_id
    assert trace.project_id == "proj_persist"
    assert trace.status == ExecutionStatus.COMPLETED
    assert trace.context.project_instructions_hash is not None


def test_trace_matches_canonical_record_and_rest_endpoints(tmp_path, monkeypatch, mock_dispatch):
    """Test 15: REST endpoints /v1/executions/{id}/trace and /v1/projects/{id}/executions."""
    db_path = str(tmp_path / "rest_ledger.db")
    storage = SQLiteBackend(db_path=db_path)
    storage.create_project(
        {
            "id": "proj_alpha",
            "name": "Project Alpha",
            "root_directory": str(tmp_path / "proj_alpha"),
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    storage.create_project(
        {
            "id": "proj_beta",
            "name": "Project Beta",
            "root_directory": str(tmp_path / "proj_beta"),
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    art_service = ArtifactService(
        storage=storage,
        base_artifacts_dir=str(tmp_path / "artifacts"),
    )
    coordinator = ExecutionCoordinator(
        storage=storage,
        artifact_service=art_service,
        dispatch_override=mock_dispatch,
    )
    ledger_service = ExecutionLedgerService(storage=storage, artifact_service=art_service)

    set_execution_coordinator(coordinator)
    set_artifact_service(art_service)
    set_ledger_service(ledger_service)
    monkeypatch.setattr("services.python.server.api.get_storage_backend", lambda: storage)

    client = TestClient(app)

    req = ExecutionRequest(
        project_id="proj_alpha",
        task_type="chat",
        prompt="REST ledger verification",
    )

    res = asyncio.run(coordinator.execute(req))

    # 1. GET /v1/executions/{id}/trace
    res_trace = client.get(f"/v1/executions/{res.execution_id}/trace")
    assert res_trace.status_code == 200
    trace_data = res_trace.json()
    assert trace_data["execution_id"] == res.execution_id
    assert trace_data["project_id"] == "proj_alpha"
    assert trace_data["status"] == "completed"
    assert "routing" in trace_data
    assert "context" in trace_data
    assert "usage" in trace_data
    assert "events" in trace_data

    # 2. Cross-project trace rejection (HTTP 403)
    res_forbidden = client.get(
        f"/v1/executions/{res.execution_id}/trace",
        headers={"X-Project-ID": "proj_beta"},
    )
    assert res_forbidden.status_code == 403

    # 3. GET non-existent execution (HTTP 404)
    res_404 = client.get("/v1/executions/exec_nonexistent/trace")
    assert res_404.status_code == 404

    # 4. GET /v1/projects/{project_id}/executions
    res_proj_execs = client.get("/v1/projects/proj_alpha/executions")
    assert res_proj_execs.status_code == 200
    exec_list = res_proj_execs.json()
    assert len(exec_list) >= 1
    assert exec_list[0]["execution_id"] == res.execution_id
    assert exec_list[0]["status"] == "completed"

    # 5. GET /v1/projects/unknown/executions (HTTP 404)
    res_unknown_proj = client.get("/v1/projects/proj_unknown/executions")
    assert res_unknown_proj.status_code == 404
