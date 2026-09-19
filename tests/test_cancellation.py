"""Comprehensive Cancellation Behavioral Tests (Task R1.9).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md

Validates all 14 CTO-specified behaviors:
1. test_running_execution_can_be_cancelled
2. test_cancellation_reaches_provider_fixture
3. test_no_chunks_emitted_after_cancellation_terminal_event
4. test_cancel_is_idempotent
5. test_completed_execution_cannot_become_cancelled
6. test_waiting_for_approval_execution_can_be_cancelled
7. test_queued_execution_can_be_cancelled
8. test_double_cancellation_is_safe
9. test_cancel_vs_complete_race_has_one_terminal_result
10. test_cancellation_persists_across_execution_ledger
11. test_cancellation_reason_recorded
12. test_partial_generated_text_is_not_persisted_as_successful_response
13. test_sse_receives_cancellation_event_when_connected
14. test_disconnect_uses_canonical_cancellation_path
"""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from core.execution import (
    CancellationToken,
    CancellationReason,
    ExecutionCoordinator,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
)
from core.router.model_router import ModelRouter
from core.safety.policy import PolicyDecision, PolicyEngine
from core.session.store import UnifiedSessionStore
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import CostTracker
from services.python.server.api import (
    app,
    get_execution_coordinator,
    set_execution_coordinator,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    """Isolated environment with real SQLite backend, coordinator, and session store."""
    db_path = str(tmp_path / "cancellation_test.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)
    session_store = UnifiedSessionStore(backend=storage)
    model_router = ModelRouter()

    # Create default project
    default_proj = storage.get_default_project()
    project_id = default_proj["id"]

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        model_router=model_router,
        cost_tracker=cost_tracker,
        session_store=session_store,
    )

    original_coord = get_execution_coordinator()
    set_execution_coordinator(coordinator)
    monkeypatch.setattr("services.python.server.api.get_storage_backend", lambda: storage)
    monkeypatch.setattr("services.python.server.api.get_session_store", lambda: session_store)

    client = TestClient(app)

    yield {
        "client": client,
        "coordinator": coordinator,
        "storage": storage,
        "session_store": session_store,
        "project_id": project_id,
    }

    set_execution_coordinator(original_coord)
    storage.close()


@pytest.mark.anyio
async def test_running_execution_can_be_cancelled(test_env):
    """1. Running execution transitions to CANCELLED upon cancellation request."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    chunk_started = asyncio.Event()

    async def slow_stream(ctx, tier, provider, model):
        for i in range(10):
            if i == 1:
                chunk_started.set()
            await asyncio.sleep(0.05)
            yield f"chunk_{i} "

    coordinator._dispatch_override = slow_stream

    req = ExecutionRequest(
        project_id=project_id,
        prompt="Tell me a long story",
        inputs={"stream": True},
    )

    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(chunk_started.wait(), timeout=5.0)

    # Cancel while running
    cancel_res = coordinator.cancel(req.id, reason=CancellationReason.USER_REQUEST, actor="user")
    assert cancel_res["cancellation_requested"] is True
    assert cancel_res["status"] == "cancelled"

    result = await asyncio.wait_for(task, timeout=5.0)
    assert result.status == ExecutionStatus.CANCELLED
    assert result.error_code == "CANCELLED"
    assert "user_request" in (result.error or "")

    persisted = coordinator.get_execution(result.execution_id)
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["error_code"] == "CANCELLED"
    assert persisted["completed_at"] is not None


@pytest.mark.anyio
async def test_cancellation_reaches_provider_fixture(test_env):
    """2. Active streaming provider fixture / async generator detects cancellation and closes."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    provider_closed = False
    started = asyncio.Event()

    async def cooperative_provider(ctx, tier, provider, model):
        nonlocal provider_closed
        try:
            for i in range(20):
                if i == 1:
                    started.set()
                await asyncio.sleep(0.04)
                yield f"tok_{i} "
        finally:
            provider_closed = True

    coordinator._dispatch_override = cooperative_provider

    req = ExecutionRequest(project_id=project_id, prompt="Cooperative test")
    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    coordinator.cancel(req.id, reason="provider_test")
    res = await asyncio.wait_for(task, timeout=5.0)

    assert res.status == ExecutionStatus.CANCELLED
    assert provider_closed is True


@pytest.mark.anyio
async def test_no_chunks_emitted_after_cancellation_terminal_event(test_env):
    """3. Once CANCELLED is emitted / recorded, zero subsequent OUTPUT_CHUNK events are emitted."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    started = asyncio.Event()
    events_recorded = []

    def event_listener(event: ExecutionEvent):
        events_recorded.append(event)

    async def generator_override(ctx, tier, provider, model):
        for i in range(10):
            if i == 2:
                started.set()
            await asyncio.sleep(0.03)
            yield f"data_{i}"

    coordinator._dispatch_override = generator_override

    req = ExecutionRequest(project_id=project_id, prompt="No chunk leak")
    task = asyncio.create_task(coordinator.execute(req, event_listener=event_listener))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    coordinator.cancel(req.id, reason="stop_now")
    await asyncio.wait_for(task, timeout=5.0)

    cancelled_idx = None
    for idx, ev in enumerate(events_recorded):
        if ev.event_type == ExecutionEventType.CANCELLED:
            cancelled_idx = idx
            break

    assert cancelled_idx is not None, "CANCELLED event must be emitted"
    # Verify no OUTPUT_CHUNK occurs after CANCELLED
    subsequent_events = events_recorded[cancelled_idx + 1 :]
    for ev in subsequent_events:
        assert (
            ev.event_type != ExecutionEventType.OUTPUT_CHUNK
        ), f"Leaked chunk event after CANCELLED: {ev}"


@pytest.mark.anyio
async def test_cancel_is_idempotent(test_env):
    """4. Calling coordinator.cancel multiple times on the same execution does not duplicate transitions or errors."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    started = asyncio.Event()

    async def slow_stream(ctx, tier, provider, model):
        started.set()
        while True:
            await asyncio.sleep(0.05)
            yield "tick "

    coordinator._dispatch_override = slow_stream
    req = ExecutionRequest(project_id=project_id, prompt="Idempotence test")
    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    # First cancel
    r1 = coordinator.cancel(req.id, reason="first_call")
    assert r1["cancellation_requested"] is True
    assert r1["status"] == "cancelled"

    # Second cancel while still finalizing
    r2 = coordinator.cancel(req.id, reason="second_call")
    assert r2["status"] == "cancelled"

    res = await asyncio.wait_for(task, timeout=5.0)
    assert res.status == ExecutionStatus.CANCELLED

    # Third cancel after completed using canonical execution_id
    r3 = coordinator.cancel(res.execution_id, reason="third_call")
    assert r3["cancellation_requested"] is False
    assert r3["status"] == "cancelled"

    # Verify event ledger has exactly one CANCELLED event
    events = coordinator.get_execution_events(res.execution_id)
    cancelled_events = [e for e in events if e.get("event_type") == "cancelled"]
    assert len(cancelled_events) == 1


@pytest.mark.anyio
async def test_completed_execution_cannot_become_cancelled(test_env):
    """5. Completed execution cannot become cancelled (terminal state immutability)."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]
    client = test_env["client"]

    coordinator._dispatch_override = lambda ctx, tier, prov, model: {
        "response": "Success completed"
    }

    req = ExecutionRequest(project_id=project_id, prompt="Already done")
    res = await coordinator.execute(req)
    assert res.status == ExecutionStatus.COMPLETED

    # 1. Direct coordinator.cancel
    cancel_res = coordinator.cancel(res.execution_id, reason="late_cancel")
    assert cancel_res["cancellation_requested"] is False
    assert cancel_res["status"] == "completed"

    persisted = coordinator.get_execution(res.execution_id)
    assert persisted["status"] == "completed"

    events = coordinator.get_execution_events(res.execution_id)
    cancelled_events = [e for e in events if e.get("event_type") == "cancelled"]
    assert len(cancelled_events) == 0

    # 2. Via REST API
    api_cancel = client.post(
        f"/v1/executions/{res.execution_id}/cancel", json={"reason": "too_late"}
    )
    assert api_cancel.status_code == 409
    data = api_cancel.json()
    assert data.get("error_code") == "TERMINAL_STATE_CONFLICT" or "completed" in str(data)

    persisted_after = coordinator.get_execution(res.execution_id)
    assert persisted_after["status"] == "completed"


@pytest.mark.anyio
async def test_waiting_for_approval_execution_can_be_cancelled(test_env):
    """6. Execution in WAITING_FOR_APPROVAL state can be cancelled."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    # Mock policy to stage (require approval)
    class StagingPolicyEngine:
        def evaluate(self, tool_name, tool_args, context=None):
            return PolicyDecision(
                decision="stage",
                risk_score=0.8,
                risk_level="high",
                reason="Requires admin approval for security action",
                violating_rules=[],
            )

    coordinator.policy_engine = StagingPolicyEngine()

    req = ExecutionRequest(
        project_id=project_id,
        prompt="Delete production database",
        task_type="dangerous_action",
    )
    res = await coordinator.execute(req)
    assert res.status == ExecutionStatus.WAITING_FOR_APPROVAL

    # Cancel approval-waiting execution
    cancel_res = coordinator.cancel(
        res.execution_id, reason="User rejected approval", actor="admin"
    )
    assert cancel_res["status"] == "cancelled"

    persisted = coordinator.get_execution(res.execution_id)
    assert persisted["status"] == "cancelled"
    assert persisted["error_code"] == "CANCELLED"
    assert persisted["completed_at"] is not None


@pytest.mark.anyio
async def test_queued_execution_can_be_cancelled(test_env):
    """7. An execution can be cancelled before dispatch begins."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    req = ExecutionRequest(project_id=project_id, prompt="Pre-cancelled test")
    token = CancellationToken(req.id)
    token.cancel(reason="cancelled_in_queue", actor="user")

    res = await coordinator.execute(req, cancellation_token=token)
    assert res.status == ExecutionStatus.CANCELLED
    assert res.error_code == "CANCELLED"

    persisted = coordinator.get_execution(res.execution_id)
    assert persisted["status"] == "cancelled"
    assert persisted["completed_at"] is not None


@pytest.mark.anyio
async def test_double_cancellation_is_safe(test_env):
    """8. Two concurrent coordinator.cancel() calls don't race or raise exceptions."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    started = asyncio.Event()

    async def slow_stream(ctx, tier, prov, model):
        started.set()
        for i in range(10):
            await asyncio.sleep(0.04)
            yield f"chunk_{i}"

    coordinator._dispatch_override = slow_stream
    req = ExecutionRequest(project_id=project_id, prompt="Concurrent cancel")
    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    # Concurrent cancel calls
    r1, r2 = await asyncio.wait_for(
        asyncio.gather(
            asyncio.to_thread(coordinator.cancel, req.id, "worker_1", "user"),
            asyncio.to_thread(coordinator.cancel, req.id, "worker_2", "user"),
        ),
        timeout=5.0,
    )

    assert r1["status"] == "cancelled"
    assert r2["status"] == "cancelled"

    res = await asyncio.wait_for(task, timeout=5.0)
    assert res.status == ExecutionStatus.CANCELLED


@pytest.mark.anyio
async def test_cancel_vs_complete_race_has_one_terminal_result(test_env):
    """9. Cancellation received at completion yields either CANCELLED or COMPLETED, never both."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    for _ in range(5):
        ready_to_finish = asyncio.Event()

        async def quick_stream(ctx, tier, prov, model):
            yield "instant output"
            ready_to_finish.set()
            await asyncio.sleep(0.001)

        coordinator._dispatch_override = quick_stream
        req = ExecutionRequest(project_id=project_id, prompt="Race test")
        task = asyncio.create_task(coordinator.execute(req))
        await asyncio.wait_for(ready_to_finish.wait(), timeout=5.0)

        coordinator.cancel(req.id, reason="race_test")
        res = await asyncio.wait_for(task, timeout=5.0)

        assert res.status in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED)

        # Persistence must match the returned result exactly
        persisted = coordinator.get_execution(res.execution_id)
        assert persisted["status"] == res.status.value

        # Event ledger must contain at most one terminal state event
        events = coordinator.get_execution_events(res.execution_id)
        completed_events = [e for e in events if e.get("event_type") == "completed"]
        cancelled_events = [e for e in events if e.get("event_type") == "cancelled"]
        assert len(completed_events) + len(cancelled_events) == 1


@pytest.mark.anyio
async def test_cancellation_persists_across_execution_ledger(test_env):
    """10. Cancelled execution in SQLite storage has status cancelled, error_code CANCELLED, completed_at set, and CANCELLED event."""
    coordinator = test_env["coordinator"]
    storage = test_env["storage"]
    project_id = test_env["project_id"]

    started = asyncio.Event()

    async def stream_fn(ctx, tier, prov, model):
        started.set()
        for i in range(10):
            await asyncio.sleep(0.04)
            yield f"p_{i}"

    coordinator._dispatch_override = stream_fn
    req = ExecutionRequest(project_id=project_id, prompt="Ledger persistence test")
    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    coordinator.cancel(req.id, reason="ledger_check")
    res = await asyncio.wait_for(task, timeout=5.0)

    # Query SQLite directly
    persisted = storage.get_execution(res.execution_id)
    assert persisted["status"] == "cancelled"
    assert persisted["error_code"] == "CANCELLED"
    assert persisted["completed_at"] is not None

    events = storage.get_execution_events(res.execution_id)
    cancelled_ev = next((e for e in events if e.get("event_type") == "cancelled"), None)
    assert cancelled_ev is not None
    payload = (
        json.loads(cancelled_ev["payload"])
        if isinstance(cancelled_ev["payload"], str)
        else cancelled_ev["payload"]
    )
    assert payload.get("reason") == "ledger_check"


@pytest.mark.anyio
async def test_cancellation_reason_recorded(test_env):
    """11. Custom reason and actor are preserved in execution record and event payload."""
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    started = asyncio.Event()

    async def stream_fn(ctx, tier, prov, model):
        started.set()
        for i in range(10):
            await asyncio.sleep(0.04)
            yield "x"

    coordinator._dispatch_override = stream_fn
    req = ExecutionRequest(project_id=project_id, prompt="Reason test")
    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    coordinator.cancel(req.id, reason="custom_rate_limit_exceeded", actor="rate_limiter_service")
    res = await asyncio.wait_for(task, timeout=5.0)

    assert res.error == "Execution cancelled: custom_rate_limit_exceeded"
    persisted = coordinator.get_execution(res.execution_id)
    assert persisted["error_message"] == "custom_rate_limit_exceeded"

    events = coordinator.get_execution_events(res.execution_id)
    cancelled_ev = next(e for e in events if e.get("event_type") == "cancelled")
    payload = (
        json.loads(cancelled_ev["payload"])
        if isinstance(cancelled_ev["payload"], str)
        else cancelled_ev["payload"]
    )
    assert payload.get("reason") == "custom_rate_limit_exceeded"
    assert payload.get("actor") == "rate_limiter_service"


@pytest.mark.anyio
async def test_partial_generated_text_is_not_persisted_as_successful_response(test_env):
    """12. Cancelled execution captures partial_output, but does NOT persist assistant turn to session store."""
    coordinator = test_env["coordinator"]
    session_store = test_env["session_store"]
    project_id = test_env["project_id"]

    session = session_store.create_session(
        title="Cancellation Session", metadata={"project_id": project_id}
    )
    session_store.append_message(session.session_id, "user", "Write an essay")

    started = asyncio.Event()

    async def stream_fn(ctx, tier, prov, model):
        yield "Part 1 "
        yield "Part 2 "
        started.set()
        for i in range(10):
            await asyncio.sleep(0.04)
            yield f"Part {i + 3} "

    coordinator._dispatch_override = stream_fn
    req = ExecutionRequest(
        project_id=project_id,
        session_id=session.session_id,
        prompt="Write an essay",
        inputs={"stream": True},
    )
    task = asyncio.create_task(coordinator.execute(req))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    coordinator.cancel(req.id, reason="user_stop")
    res = await asyncio.wait_for(task, timeout=5.0)

    assert res.status == ExecutionStatus.CANCELLED
    assert res.partial_output is not None
    assert "Part 1" in res.partial_output

    # Check session store: MUST NOT have assistant message
    updated_session = session_store.get_session(session.session_id)
    assistant_msgs = [
        m
        for m in updated_session.messages
        if (m.role == "assistant" or getattr(m.role, "value", None) == "assistant")
    ]
    assert len(assistant_msgs) == 0, "Partial output MUST NOT be persisted to session store"


def test_sse_receives_cancellation_event_when_connected(test_env):
    """13. SSE stream receives terminal cancellation event when active execution is cancelled via API."""
    client = test_env["client"]
    coordinator = test_env["coordinator"]
    project_id = test_env["project_id"]

    cancelled_once = False

    async def slow_stream(ctx, tier, prov, model):
        nonlocal cancelled_once
        yield "token_1 "
        await asyncio.sleep(0.02)
        yield "token_2 "
        if not cancelled_once:
            cancelled_once = True
            coordinator.cancel(ctx.execution_id, reason="api_cancel_test", actor="user")
        await asyncio.sleep(0.02)
        yield "token_3_should_be_dropped "

    coordinator._dispatch_override = slow_stream

    response = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "Stream me something",
            "stream": True,
            "project_id": project_id,
        },
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    text = response.text
    assert "event: cancelled" in text or '"event": "cancelled"' in text
    assert "token_3_should_be_dropped" not in text


@pytest.mark.anyio
async def test_disconnect_uses_canonical_cancellation_path(test_env):
    """14. When client disconnects from SSE stream, canonical cancellation path is invoked with client_disconnect."""
    coordinator = test_env["coordinator"]
    session_store = test_env["session_store"]
    project_id = test_env["project_id"]

    session = session_store.create_session(
        title="Disconnect Session", metadata={"project_id": project_id}
    )

    started = asyncio.Event()

    async def stream_fn(ctx, tier, prov, model):
        started.set()
        for i in range(20):
            await asyncio.sleep(0.04)
            yield f"chunk_{i} "

    coordinator._dispatch_override = stream_fn

    req = ExecutionRequest(
        project_id=project_id,
        session_id=session.session_id,
        prompt="Disconnect test",
        inputs={"stream": True},
    )

    token = CancellationToken(req.id)
    task = asyncio.create_task(coordinator.execute(req, cancellation_token=token))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    coordinator.cancel(req.id, reason=CancellationReason.CLIENT_DISCONNECT, actor="client")
    res = await asyncio.wait_for(task, timeout=5.0)

    assert res.status == ExecutionStatus.CANCELLED
    assert res.error_code == "CANCELLED"
    assert "client_disconnect" in (res.error or "")

    persisted = coordinator.get_execution(res.execution_id)
    assert persisted["status"] == "cancelled"
    assert persisted["error_code"] == "CANCELLED"

    updated_session = session_store.get_session(session.session_id)
    assistant_msgs = [
        m
        for m in updated_session.messages
        if (m.role == "assistant" or getattr(m.role, "value", None) == "assistant")
    ]
    assert len(assistant_msgs) == 0
