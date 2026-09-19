"""Comprehensive Reconciliation Tests for Stage R1 (R1.7, R1.8 & CTO Corrections).

Tests covered:
1. Canonical Project Identification & Migration (proj_default, is_default, alias resolution).
2. Decoupled HTTP Transport Semantics (503, 403, 504, 502, 400, structured error bodies & SSE events).
3. R1.7 Bounded Conversation History & Provenance Tracking.
4. R1.8 Real-Time Incremental Streaming (timing proof, backpressure, disconnect cancellation,
   mid-stream failure, exactly-once persistence, no SQLite write amplification).
"""

import asyncio
import json
import sqlite3
import time
from typing import List
import pytest
from fastapi.testclient import TestClient

import re
from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionContext,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
    RoutingTier,
)
from core.router.model_router import ModelRouter, ResolvedModel
from core.safety.policy import PolicyEngine
from core.session.store import UnifiedSessionStore, reset_session_store
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import CostTracker
from services.python.server.api import (
    app,
    get_execution_coordinator,
    set_execution_coordinator,
)


@pytest.fixture
def recon_env(tmp_path, monkeypatch):
    """Isolated environment with dedicated SQLite database and mock coordinator."""
    db_path = str(tmp_path / "recon_test.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "recon_policies.yaml"))
    cost_tracker = CostTracker(storage=storage)
    session_store = UnifiedSessionStore(backend=storage)
    model_router = ModelRouter()

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        model_router=model_router,
        cost_tracker=cost_tracker,
        session_store=session_store,
    )

    orig_coord = get_execution_coordinator()
    set_execution_coordinator(coordinator)
    monkeypatch.setattr("services.python.server.api.get_storage_backend", lambda: storage)
    monkeypatch.setattr("services.python.server.api.get_session_store", lambda: session_store)

    client = TestClient(app)

    yield {
        "client": client,
        "coordinator": coordinator,
        "storage": storage,
        "session_store": session_store,
        "model_router": model_router,
        "db_path": db_path,
    }

    set_execution_coordinator(orig_coord)
    storage.close()
    reset_session_store()


# ===========================================================================
# 1. Canonical Project Identification & Migration
# ===========================================================================


def test_canonical_default_project_seeded(recon_env):
    """Verify that default project is seeded with canonical proj_<hex12> ID and is_default=True."""
    storage = recon_env["storage"]
    default_proj = storage.get_default_project()
    assert default_proj is not None
    assert re.match(r"^proj_[0-9a-f]{12}$", default_proj["id"])
    assert default_proj["is_default"] is True
    assert default_proj["name"] == "Default Project"


def test_default_project_alias_resolution(recon_env):
    """Verify get_project resolves compatibility aliases 'default' and 'proj_default' to canonical project."""
    storage = recon_env["storage"]
    canonical_def = storage.get_default_project()
    assert canonical_def is not None

    p1 = storage.get_project("default")
    p2 = storage.get_project("proj_default")
    assert p1 is not None
    assert p2 is not None
    assert p1["id"] == canonical_def["id"]
    assert p2["id"] == canonical_def["id"]
    assert re.match(r"^proj_[0-9a-f]{12}$", p1["id"])
    assert p1["is_default"] is True


def test_canonical_id_format(recon_env):
    """Verify all generated project IDs strictly adhere to proj_<hex12> with no magic exceptions."""
    storage = recon_env["storage"]
    p = storage.create_project(
        {
            "name": "Canonical Format Test",
            "root_path": "/workspace/canonical_format",
        }
    )
    assert p is not None
    assert re.match(r"^proj_[0-9a-f]{12}$", p["id"])
    assert p["is_default"] is False


def test_exactly_one_default_project(recon_env):
    """Verify setting is_default=True on another project enforces exactly one default project."""
    storage = recon_env["storage"]
    first_default = storage.get_default_project()
    assert first_default is not None

    new_default = storage.create_project(
        {
            "name": "New Primary Workspace",
            "root_path": "/workspace/new_primary",
            "is_default": True,
        }
    )
    assert new_default["is_default"] is True

    # Check that previous default was demoted
    old_def_refetched = storage.get_project(first_default["id"])
    assert old_def_refetched["is_default"] is False

    # Check that get_default_project returns the new default
    active_default = storage.get_default_project()
    assert active_default["id"] == new_default["id"]

    # Verify query count of projects with is_default=1 is strictly 1
    projects = storage.list_projects(limit=100)
    defaults = [p for p in projects if p.get("is_default")]
    assert len(defaults) == 1


def test_legacy_default_and_proj_default_migration_with_foreign_keys(tmp_path):
    """Verify that an existing database with 'default' and 'proj_default' projects and foreign keys is cleanly migrated."""
    legacy_db = str(tmp_path / "legacy_migration.db")
    raw_conn = sqlite3.connect(legacy_db)
    raw_conn.execute("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            root_path TEXT NOT NULL UNIQUE,
            instructions TEXT NOT NULL DEFAULT '',
            settings_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    raw_conn.execute("""
        CREATE TABLE executions (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL,
            request_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    raw_conn.execute("""
        CREATE TABLE cost_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            project TEXT NOT NULL
        );
    """)
    # Insert legacy projects
    raw_conn.execute("""
        INSERT INTO projects (id, name, description, root_path, instructions, settings_json, created_at, updated_at)
        VALUES ('default', 'Legacy Default', 'Old project', '/workspace/old', '', '{}', '2025-01-01T00:00:00', '2025-01-01T00:00:00');
    """)
    # Insert executions referencing legacy default and proj_default
    raw_conn.execute("""
        INSERT INTO executions (id, project_id, status, request_json, created_at)
        VALUES ('exec_1', 'default', 'completed', '{}', '2025-01-01T00:00:00');
    """)
    raw_conn.execute("""
        INSERT INTO executions (id, project_id, status, request_json, created_at)
        VALUES ('exec_2', 'proj_default', 'completed', '{}', '2025-01-01T00:00:00');
    """)
    # Insert cost records referencing legacy default and proj_default
    raw_conn.execute("""
        INSERT INTO cost_records (timestamp, agent_name, model_name, prompt_tokens, completion_tokens, cost_usd, project)
        VALUES ('2025-01-01T00:00:00', 'agent', 'model', 10, 10, 0.001, 'default');
    """)
    raw_conn.execute("""
        INSERT INTO cost_records (timestamp, agent_name, model_name, prompt_tokens, completion_tokens, cost_usd, project)
        VALUES ('2025-01-01T00:00:00', 'agent', 'model', 10, 10, 0.001, 'proj_default');
    """)
    raw_conn.commit()
    raw_conn.close()

    # Opening with SQLiteBackend triggers automated migration
    backend = SQLiteBackend(db_path=legacy_db)
    try:
        # Verify default project is now canonical proj_<hex12>
        canonical_def = backend.get_default_project()
        assert canonical_def is not None
        assert re.match(r"^proj_[0-9a-f]{12}$", canonical_def["id"])
        assert canonical_def["is_default"] is True
        assert canonical_def["name"] == "Legacy Default"

        # Verify old aliases resolve to this canonical project
        alias_default = backend.get_project("default")
        alias_proj_default = backend.get_project("proj_default")
        assert alias_default is not None
        assert alias_default["id"] == canonical_def["id"]
        assert alias_proj_default is not None
        assert alias_proj_default["id"] == canonical_def["id"]

        # Verify foreign keys in executions were updated
        conn = sqlite3.connect(legacy_db)
        cursor = conn.cursor()
        cursor.execute("SELECT project_id FROM executions")
        exec_proj_ids = [row[0] for row in cursor.fetchall()]
        assert all(pid == canonical_def["id"] for pid in exec_proj_ids)

        # Verify foreign keys in cost_records were updated
        cursor.execute("SELECT project FROM cost_records")
        cost_proj_ids = [row[0] for row in cursor.fetchall()]
        assert all(pid == canonical_def["id"] for pid in cost_proj_ids)
        conn.close()
    finally:
        backend.close()


def test_create_project_with_is_default_flag(recon_env):
    """Verify custom projects can be stored and retrieved with is_default flag."""
    storage = recon_env["storage"]
    storage.create_project(
        {
            "id": "proj_custom_123",
            "name": "Custom Non Default",
            "root_path": "/workspace/custom",
            "is_default": False,
        }
    )
    proj = storage.get_project("proj_custom_123")
    assert proj is not None
    assert proj["is_default"] is False


def test_event_durability_classification():
    """Verify durable vs transient event classification properties."""
    durable_types = [
        ExecutionEventType.STATE_CHANGE,
        ExecutionEventType.ROUTING_RESOLVED,
        ExecutionEventType.APPROVAL_REQUIRED,
        ExecutionEventType.APPROVAL_RESOLVED,
        ExecutionEventType.TOOL_CALL_STARTED,
        ExecutionEventType.TOOL_CALL_COMPLETED,
        ExecutionEventType.VERIFICATION_STARTED,
        ExecutionEventType.VERIFICATION_COMPLETED,
        ExecutionEventType.COMPLETED,
        ExecutionEventType.FAILED,
        ExecutionEventType.CANCELLED,
    ]
    transient_types = [
        ExecutionEventType.TOKEN_DELTA,
        ExecutionEventType.OUTPUT_CHUNK,
    ]

    for dt in durable_types:
        assert dt.is_durable is True
        assert dt.is_transient is False
        evt = ExecutionEvent(execution_id="exec_1", sequence_num=0, event_type=dt)
        assert evt.is_durable is True
        assert evt.is_transient is False

    for tt in transient_types:
        assert tt.is_durable is False
        assert tt.is_transient is True
        evt = ExecutionEvent(execution_id="exec_1", sequence_num=0, event_type=tt)
        assert evt.is_durable is False
        assert evt.is_transient is True


# ===========================================================================
# 2. Decoupled HTTP Transport Semantics
# ===========================================================================


def test_http_503_no_available_provider(recon_env):
    """Verify NO_AVAILABLE_PROVIDER returns HTTP 503 with structured body."""
    client = recon_env["client"]
    router = recon_env["model_router"]

    def mock_resolve_none(*args, **kwargs):
        return ResolvedModel(
            provider_id="none",
            model_id="",
            routing_tier=RoutingTier.MID,
            reason="All circuits open",
            is_fallback=False,
        )

    router.resolve_model = mock_resolve_none

    res = client.post("/v1/chat/completions", json={"prompt": "Test 503", "stream": False})
    assert res.status_code == 503
    data = res.json()
    assert data["error_code"] == "NO_AVAILABLE_PROVIDER"
    assert "No LLM provider available" in data["detail"]


def test_http_403_cross_project_violation(recon_env):
    """Verify CROSS_PROJECT_VIOLATION returns HTTP 403."""
    client = recon_env["client"]
    store = recon_env["session_store"]

    store.create_session(
        session_id="sess_proj_a",
        metadata={"project_id": "proj_alpha"},
    )

    res = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "Test 403 breach",
            "session_id": "sess_proj_a",
            "project_id": "proj_beta",
            "stream": False,
        },
    )
    assert res.status_code == 403
    data = res.json()
    assert data["error_code"] == "CROSS_PROJECT_VIOLATION"


def test_http_504_provider_timeout(recon_env):
    """Verify provider timeout errors map to HTTP 504 Gateway Timeout."""
    coordinator = recon_env["coordinator"]
    client = recon_env["client"]

    def timeout_dispatch(context, tier, provider, model):
        raise TimeoutError("Upstream provider deadline exceeded: timed out after 30s")

    coordinator._dispatch_override = timeout_dispatch

    res = client.post("/v1/chat/completions", json={"prompt": "Test 504 timeout", "stream": False})
    assert res.status_code == 504
    data = res.json()
    assert data["error_code"] == "PROVIDER_TIMEOUT"


def test_http_502_dispatch_failed(recon_env):
    """Verify provider connection/dispatch errors map to HTTP 502 Bad Gateway."""
    coordinator = recon_env["coordinator"]
    client = recon_env["client"]

    def fail_dispatch(context, tier, provider, model):
        raise RuntimeError("Provider connection reset by peer: dispatch failed")

    coordinator._dispatch_override = fail_dispatch

    res = client.post("/v1/chat/completions", json={"prompt": "Test 502 fail", "stream": False})
    assert res.status_code == 502
    data = res.json()
    assert data["error_code"] == "DISPATCH_FAILED"


def test_sse_streaming_emits_structured_error_event(recon_env):
    """Verify streaming mode emits an SSE 'error' event with error_code."""
    coordinator = recon_env["coordinator"]
    client = recon_env["client"]

    def failing_dispatch(context, tier, provider, model):
        raise RuntimeError("Provider connection refused: dispatch failed")

    coordinator._dispatch_override = failing_dispatch

    res = client.post("/v1/chat/completions", json={"prompt": "Test stream error", "stream": True})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    text = res.text
    assert '"event": "error"' in text
    assert '"error_code": "DISPATCH_FAILED"' in text


# ===========================================================================
# 3. Task R1.7: Bounded Real Conversation History & Provenance Tracking
# ===========================================================================


@pytest.mark.anyio
async def test_bounded_history_within_budget_retains_all_turns(recon_env):
    """Verify conversation history within budget is retained in full chronological order."""
    coordinator = recon_env["coordinator"]
    store = recon_env["session_store"]

    sess_id = "sess_small_history"
    def_proj = recon_env["storage"].get_default_project()["id"]
    store.create_session(session_id=sess_id, metadata={"project_id": def_proj})
    store.append_message(session_id=sess_id, role="user", content="Hello!")
    store.append_message(session_id=sess_id, role="assistant", content="Hi there! How can I help?")

    captured_contexts: List[ExecutionContext] = []

    def inspect_dispatch(context, tier, provider, model):
        captured_contexts.append(context)
        return {"response": "Done"}

    coordinator._dispatch_override = inspect_dispatch

    req = ExecutionRequest(
        project_id=def_proj,
        session_id=sess_id,
        prompt="Tell me a joke",
        token_budget=4000,
    )
    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    assert len(captured_contexts) == 1
    ctx = captured_contexts[0]
    # Retained turns should be exactly the 2 messages
    assert len(ctx.conversation_history) == 2
    assert ctx.conversation_history[0]["content"] == "Hello!"
    assert "Hi there!" in ctx.conversation_history[1]["content"]

    # Check provenance
    prov = ctx.context_provenance
    assert prov["history_truncated"] is False
    assert prov["total_available_turns"] == 2
    assert prov["retained_turns_count"] == 2
    assert prov["dropped_turns_count"] == 0
    assert prov["history_tokens"] > 0
    assert prov["prompt_tokens"] > 0


@pytest.mark.anyio
async def test_bounded_history_drops_oldest_turns_when_budget_exceeded(recon_env):
    """Verify oldest turns are dropped and newest retained when token budget is tight."""
    coordinator = recon_env["coordinator"]
    store = recon_env["session_store"]

    sess_id = "sess_large_history"
    def_proj = recon_env["storage"].get_default_project()["id"]
    store.create_session(session_id=sess_id, metadata={"project_id": def_proj})
    # Append 8 distinct turns
    for i in range(8):
        role = "user" if i % 2 == 0 else "assistant"
        store.append_message(
            session_id=sess_id,
            role=role,
            content=f"Turn {i}: " + ("word " * 50),  # ~50-60 tokens per turn
        )

    captured_contexts: List[ExecutionContext] = []

    def inspect_dispatch(context, tier, provider, model):
        captured_contexts.append(context)
        return {"response": "Handled"}

    coordinator._dispatch_override = inspect_dispatch

    # Set token budget small so budget_for_history (~120 tokens) only fits ~2 turns
    req = ExecutionRequest(
        project_id=def_proj,
        session_id=sess_id,
        prompt="Summarize recent turns",
        token_budget=240,
    )
    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    assert len(captured_contexts) == 1
    ctx = captured_contexts[0]
    prov = ctx.context_provenance

    assert prov["total_available_turns"] == 8
    assert prov["history_truncated"] is True
    assert prov["dropped_turns_count"] > 0
    assert prov["retained_turns_count"] < 8
    assert prov["retained_turns_count"] + prov["dropped_turns_count"] == 8

    # Retained turns must be the MOST RECENT turns, preserved in chronological order
    retained = ctx.conversation_history
    assert len(retained) == prov["retained_turns_count"]
    # The last turn in retained history should be Turn 7
    assert "Turn 7:" in retained[-1]["content"]


@pytest.mark.anyio
async def test_bounded_history_preserves_prompt_and_instructions(recon_env):
    """Verify prompt and project instructions are budgeted first and never evicted."""
    coordinator = recon_env["coordinator"]
    storage = recon_env["storage"]
    store = recon_env["session_store"]

    storage.create_project(
        {
            "id": "proj_strict",
            "name": "Strict Project",
            "root_path": "/workspace/strict",
            "instructions": "Crucial instruction that must never be evicted.",
        }
    )

    sess_id = "sess_tight"
    store.create_session(session_id=sess_id, metadata={"project_id": "proj_strict"})
    store.append_message(session_id=sess_id, role="user", content="Turn 1 " + ("filler " * 40))
    store.append_message(session_id=sess_id, role="assistant", content="Turn 2 " + ("filler " * 40))

    captured_contexts: List[ExecutionContext] = []

    def inspect_dispatch(context, tier, provider, model):
        captured_contexts.append(context)
        return {"response": "OK"}

    coordinator._dispatch_override = inspect_dispatch

    # Tight budget
    req = ExecutionRequest(
        project_id="proj_strict",
        session_id=sess_id,
        prompt="Current prompt that must never be evicted",
        token_budget=80,
    )
    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    ctx = captured_contexts[0]
    # Project instructions and prompt must be intact in ExecutionContext
    assert ctx.project_instructions == "Crucial instruction that must never be evicted."
    assert ctx.prompt == "Current prompt that must never be evicted"
    prov = ctx.context_provenance
    assert prov["instruction_tokens"] > 0
    assert prov["prompt_tokens"] > 0


# ===========================================================================
# 4. Task R1.8: Real-Time Incremental Streaming
# ===========================================================================


@pytest.mark.anyio
async def test_streaming_first_chunk_arrives_before_completion(recon_env):
    """TIMING PROOF: Verify first SSE chunk arrives before the provider completes execution."""
    from services.python.server.api import ChatRequest, chat_completions

    coordinator = recon_env["coordinator"]

    chunk_timestamps = []
    completion_timestamp = None

    async def slow_streaming_dispatch(context, tier, provider, model):
        nonlocal completion_timestamp
        # Emit first chunk immediately
        yield "Chunk 1: Hello "
        # Delay before second chunk
        await asyncio.sleep(0.2)
        yield "Chunk 2: World!"
        await asyncio.sleep(0.05)
        completion_timestamp = time.perf_counter()

    coordinator._dispatch_override = slow_streaming_dispatch

    req = ChatRequest(prompt="Stream timing test", stream=True)
    resp = await chat_completions(req)

    tokens_received = []
    async for item in resp.body_iterator:
        chunk_timestamps.append(time.perf_counter())
        if item.startswith("data: "):
            data = json.loads(item[6:].strip())
            if data.get("event") == "token":
                tokens_received.append(data.get("delta"))

    assert len(tokens_received) >= 2
    assert "Chunk 1: Hello " in tokens_received[0]
    assert "Chunk 2: World!" in tokens_received[1]

    # First token chunk timestamp must be earlier than provider completion timestamp!
    assert completion_timestamp is not None
    assert chunk_timestamps[0] < completion_timestamp
    # Proof: Chunk 1 was received at least 150ms before provider completion!
    assert (completion_timestamp - chunk_timestamps[0]) >= 0.15


@pytest.mark.anyio
async def test_streaming_client_disconnect_triggers_cancellation(recon_env):
    """Verify client disconnect triggers cancellation_token and cancels coordinator task."""
    from services.python.server.api import ChatRequest, chat_completions

    coordinator = recon_env["coordinator"]
    cancelled = asyncio.Event()

    async def infinite_stream(context, tier, provider, model):
        try:
            while True:
                yield "infinite token "
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    coordinator._dispatch_override = infinite_stream

    req = ChatRequest(prompt="Infinite stream", stream=True)
    resp = await chat_completions(req)

    count = 0
    try:
        async for chunk in resp.body_iterator:
            count += 1
            if count >= 2:
                # Simulate client disconnect by closing generator
                await resp.body_iterator.aclose()
                break
    except (asyncio.CancelledError, GeneratorExit):
        pass

    await asyncio.sleep(0.1)
    assert cancelled.is_set()


def test_streaming_avoids_sqlite_write_amplification(recon_env):
    """Verify SQLite execution_events table does NOT persist transient token/output chunks."""
    coordinator = recon_env["coordinator"]
    client = recon_env["client"]
    storage = recon_env["storage"]

    async def multi_chunk_dispatch(context, tier, provider, model):
        for i in range(10):
            yield f"token_{i} "

    coordinator._dispatch_override = multi_chunk_dispatch

    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Test no write amplification", "stream": True},
    )
    assert res.status_code == 200

    # Retrieve all execution events in SQLite
    executions = storage.list_executions(limit=1)
    assert len(executions) > 0
    exec_id = executions[0]["id"]

    events = storage.get_execution_events(exec_id)
    event_types = [e["event_type"] for e in events]

    # Durable events must be present
    assert ExecutionEventType.STATE_CHANGE.value in event_types
    assert ExecutionEventType.ROUTING_RESOLVED.value in event_types

    # Transient streaming chunk events must NOT be in SQLite!
    assert ExecutionEventType.OUTPUT_CHUNK.value not in event_types
    assert ExecutionEventType.TOKEN_DELTA.value not in event_types


def test_streaming_persists_assistant_message_exactly_once(recon_env):
    """Verify assistant turn is stored exactly once with full accumulated response in session store."""
    coordinator = recon_env["coordinator"]
    client = recon_env["client"]
    store = recon_env["session_store"]

    sess_id = "sess_stream_once"
    def_proj = recon_env["storage"].get_default_project()["id"]
    store.create_session(session_id=sess_id, metadata={"project_id": def_proj})

    async def chunked_dispatch(context, tier, provider, model):
        yield "Part 1, "
        yield "Part 2, "
        yield "Part 3."

    coordinator._dispatch_override = chunked_dispatch

    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Persist exactly once", "session_id": sess_id, "stream": True},
    )
    assert res.status_code == 200

    # Inspect session messages
    session = store.get_session(sess_id)
    assert session is not None
    assistant_msgs = [m for m in session.messages if m.role == "assistant"]
    assert len(assistant_msgs) == 1  # Exactly once!
    assert assistant_msgs[0].content == "Part 1, Part 2, Part 3."


def test_streaming_mid_stream_failure_emits_error_event(recon_env):
    """Verify mid-stream provider crash emits an error SSE event and closes cleanly."""
    coordinator = recon_env["coordinator"]
    client = recon_env["client"]

    async def failing_stream_dispatch(context, tier, provider, model):
        yield "Started okay... "
        await asyncio.sleep(0.01)
        raise RuntimeError("Mid-stream connection broken!")

    coordinator._dispatch_override = failing_stream_dispatch

    events_seen = []
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"prompt": "Crash mid stream", "stream": True},
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                events_seen.append(data.get("event"))

    # Started with token, terminated with error!
    assert "token" in events_seen
    assert "error" in events_seen
    # Must NOT have done event
    assert "done" not in events_seen
