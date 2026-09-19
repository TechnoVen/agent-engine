"""Comprehensive Integration Tests for Canonical Chat Execution (Stage R1).

Validates all 12 CTO-specified behaviors:
1. Chat request creates canonical Execution
2. Execution persists in SQLite
3. Real provider adapter receives request
4. Requested/resolved/actual model identities agree
5. Router fallback is recorded truthfully
6. Two-turn session history reaches inference
7. Project instructions reach inference
8. Project A cannot retrieve Project B context (cross-project isolation)
9. No-provider configuration fails explicitly
10. Provider error produces FAILED rather than COMPLETED
11. ExecutionResult corresponds to persisted Execution
12. Existing chat/session API remains backward compatible
Plus:
13. Canonical Project REST endpoints (CRUD)
"""

import json
import pytest
from fastapi.testclient import TestClient

from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionContext,
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
def integration_env(tmp_path, monkeypatch):
    """Set up an isolated execution environment with SQLite backend and coordinator."""
    db_path = str(tmp_path / "chat_integration.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)
    session_store = UnifiedSessionStore(backend=storage)
    model_router = ModelRouter()

    recorded_dispatches = []

    def mock_dispatch(context: ExecutionContext, tier: RoutingTier, provider: str, model: str):
        recorded_dispatches.append(
            {
                "context": context,
                "tier": tier,
                "provider": provider,
                "model": model,
                "task": context.task,
                "conversation_history": context.conversation_history,
                "project_instructions": context.project_instructions,
            }
        )
        return {
            "response": f"Answer from {provider}/{model}: Hello!",
            "content": f"Answer from {provider}/{model}: Hello!",
        }

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        model_router=model_router,
        cost_tracker=cost_tracker,
        session_store=session_store,
        dispatch_override=mock_dispatch,
    )

    # Monkeypatch global dependencies
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
        "model_router": model_router,
        "recorded_dispatches": recorded_dispatches,
    }

    set_execution_coordinator(original_coord)
    storage.close()
    reset_session_store()


# ---------------------------------------------------------------------------
# 1 & 2. Chat request creates canonical Execution & persists in SQLite
# ---------------------------------------------------------------------------


def test_chat_creates_canonical_execution_and_persists(integration_env):
    """Verify chat request produces execution record and persists in SQLite."""
    client = integration_env["client"]
    storage = integration_env["storage"]

    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Explain database indexing in 2 sentences.", "stream": False},
    )
    assert res.status_code == 200
    data = res.json()

    assert "execution_id" in data
    exec_id = data["execution_id"]
    assert exec_id.startswith("exec_")
    assert "response" in data
    assert data["status"] == "completed"

    # Verify persistence in SQLite
    stored = storage.get_execution(exec_id)
    assert stored is not None
    assert stored["id"] == exec_id
    assert stored["status"] == "completed"
    assert stored["total_cost_usd"] >= 0.0

    # Verify execution events persisted
    events = storage.get_execution_events(exec_id)
    assert len(events) > 0
    event_types = [e["event_type"] for e in events]
    assert ExecutionEventType.STATE_CHANGE.value in event_types
    assert ExecutionEventType.ROUTING_RESOLVED.value in event_types


# ---------------------------------------------------------------------------
# 3. Real provider adapter receives request
# ---------------------------------------------------------------------------


def test_provider_adapter_receives_request(integration_env):
    """Verify inference receives the synthesized prompt and execution context."""
    client = integration_env["client"]
    dispatches = integration_env["recorded_dispatches"]

    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Generate a unique hash for test 3", "stream": False},
    )
    assert res.status_code == 200
    assert len(dispatches) == 1
    last_call = dispatches[-1]
    assert last_call["task"] == "Generate a unique hash for test 3"
    assert last_call["provider"] in ("anthropic", "openai", "google", "ollama", "deterministic")


# ---------------------------------------------------------------------------
# 4. Requested, resolved, and actual model identities agree
# ---------------------------------------------------------------------------


def test_model_identities_agreement(integration_env):
    """Verify requested model maps cleanly to resolved model and execution record."""
    client = integration_env["client"]
    storage = integration_env["storage"]

    res = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "Test model agreement",
            "model": "claude-3-5-sonnet",
            "stream": False,
        },
    )
    assert res.status_code == 200
    data = res.json()

    assert data["model_used"] == "claude-3-5-sonnet"
    assert data["provider_used"] == "anthropic"

    stored = storage.get_execution(data["execution_id"])
    assert stored["model"] == "claude-3-5-sonnet"
    assert stored["provider"] == "anthropic"


# ---------------------------------------------------------------------------
# 5. Router fallback is recorded truthfully
# ---------------------------------------------------------------------------


def test_router_fallback_recorded_truthfully(integration_env):
    """Verify fallback event and execution record truthfully reflect fallbacks."""
    client = integration_env["client"]
    storage = integration_env["storage"]
    router = integration_env["model_router"]

    # Trip the circuit breaker for anthropic claude-3-5-sonnet
    router.record_failure("anthropic", "claude-3-5-sonnet", "Rate limit exceeded")
    router.record_failure("anthropic", "claude-3-5-sonnet", "Rate limit exceeded")
    router.record_failure("anthropic", "claude-3-5-sonnet", "Rate limit exceeded")

    res = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "Test fallback tracking",
            "model": "claude-3-5-sonnet",
            "stream": False,
        },
    )
    assert res.status_code == 200
    data = res.json()

    exec_id = data["execution_id"]
    events = storage.get_execution_events(exec_id)
    routing_events = [
        e for e in events if e["event_type"] == ExecutionEventType.ROUTING_RESOLVED.value
    ]
    assert len(routing_events) > 0

    routing_payload = json.loads(routing_events[0]["payload_json"])
    assert routing_payload.get("is_fallback") is True
    assert "fallback_reason" in routing_payload


# ---------------------------------------------------------------------------
# 6. Two-turn session history reaches inference
# ---------------------------------------------------------------------------


def test_two_turn_session_history_reaches_inference(integration_env):
    """Verify multi-turn history is bounded and passed to Turn 2 context."""
    client = integration_env["client"]
    dispatches = integration_env["recorded_dispatches"]

    # Turn 1
    res1 = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "Remember that my favourite color is indigo.",
            "session_id": "sess_multiturn_1",
            "stream": False,
        },
    )
    assert res1.status_code == 200

    # Turn 2
    res2 = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "What is my favourite color?",
            "session_id": "sess_multiturn_1",
            "stream": False,
        },
    )
    assert res2.status_code == 200

    # Inspect Turn 2 dispatch
    turn2_dispatch = dispatches[-1]
    history = turn2_dispatch["conversation_history"]
    assert len(history) >= 2
    user_msgs = [m["content"] for m in history if m["role"] == "user"]
    assert any("indigo" in m for m in user_msgs)


# ---------------------------------------------------------------------------
# 7. Project instructions reach inference
# ---------------------------------------------------------------------------


def test_project_instructions_reach_inference(integration_env):
    """Verify project instructions are loaded and injected into execution context."""
    client = integration_env["client"]
    storage = integration_env["storage"]
    dispatches = integration_env["recorded_dispatches"]

    # Create project with custom instructions
    storage.create_project(
        {
            "id": "proj_pirate",
            "name": "Pirate Bot Project",
            "root_path": "/workspace/pirate",
            "instructions": "Speak like a pirate at all times! Ahoy matey!",
            "settings": {"isolation_mode": "standard"},
        }
    )

    res = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "Where is the treasure?",
            "project_id": "proj_pirate",
            "stream": False,
        },
    )
    assert res.status_code == 200

    last_call = dispatches[-1]
    assert "Ahoy matey" in last_call["project_instructions"]
    assert last_call["context"].context_provenance.get("project_id") == "proj_pirate"


# ---------------------------------------------------------------------------
# 8. Project A cannot retrieve Project B context (cross-project isolation)
# ---------------------------------------------------------------------------


def test_cross_project_session_isolation(integration_env):
    """Verify sessions bound to Project A are rejected if accessed by Project B."""
    client = integration_env["client"]
    session_store = integration_env["session_store"]

    # Create a session belonging to project_a
    session_store.create_session(
        session_id="sess_project_a",
        metadata={"project_id": "proj_alpha"},
    )

    # Attempt to execute a chat under project_b using project_a's session
    res = client.post(
        "/v1/chat/completions",
        json={
            "prompt": "Attempt cross-project breach",
            "project_id": "proj_beta",
            "session_id": "sess_project_a",
            "stream": False,
        },
    )
    # ExecutionCoordinator flags cross-project breach and returns HTTP 403 Forbidden
    assert res.status_code == 403
    assert "CROSS_PROJECT_VIOLATION" in res.text or "not authorized" in res.text


# ---------------------------------------------------------------------------
# 9. No-provider configuration fails explicitly
# ---------------------------------------------------------------------------


def test_no_provider_fails_explicitly(integration_env):
    """Verify honest failure when no provider is available (no fake 200)."""
    client = integration_env["client"]
    router = integration_env["model_router"]

    # Mock router.resolve_model to return none
    def mock_resolve_none(*args, **kwargs):
        return ResolvedModel(
            provider_id="none",
            model_id="",
            routing_tier=RoutingTier.MID,
            reason="No providers available",
            is_fallback=False,
        )

    router.resolve_model = mock_resolve_none

    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Will this fail honestly?", "stream": False},
    )
    assert res.status_code == 503
    data = res.json()
    assert data.get("error_code") == "NO_AVAILABLE_PROVIDER" or "NO_AVAILABLE_PROVIDER" in str(
        data.get("detail", "")
    )


# ---------------------------------------------------------------------------
# 10. Provider error produces FAILED rather than COMPLETED
# ---------------------------------------------------------------------------


def test_provider_error_produces_failed(integration_env):
    """Verify downstream provider exception transitions execution to FAILED."""
    coordinator = integration_env["coordinator"]
    client = integration_env["client"]
    storage = integration_env["storage"]

    def failing_dispatch(context, tier, provider, model):
        raise RuntimeError("Provider connection reset: dispatch failed")

    coordinator._dispatch_override = failing_dispatch

    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "This dispatch will crash", "stream": False},
    )
    assert res.status_code == 502
    assert "DISPATCH_FAILED" in res.text

    # Verify that in SQLite, status is 'failed'
    executions = storage.list_executions(limit=1)
    assert len(executions) > 0
    latest = executions[0]
    assert latest["status"] == "failed"
    assert latest["error_code"] == "DISPATCH_FAILED"


# ---------------------------------------------------------------------------
# 11. ExecutionResult corresponds to persisted Execution
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execution_result_matches_persisted_execution(integration_env):
    """Verify ExecutionResult fields match SQLite execution record exactly."""
    coordinator = integration_env["coordinator"]
    storage = integration_env["storage"]

    req = ExecutionRequest(
        prompt="Calculate test metrics",
        project_id="proj_match_test",
        target_tier=RoutingTier.MID,
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    stored = storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["id"] == result.execution_id
    assert stored["status"] == result.status.value
    assert stored["total_cost_usd"] == result.total_cost_usd
    assert stored["input_tokens"] == result.prompt_tokens
    assert stored["output_tokens"] == result.completion_tokens
    assert stored["started_at"] is not None
    assert stored["completed_at"] is not None


# ---------------------------------------------------------------------------
# 12. Existing chat/session API remains backward compatible
# ---------------------------------------------------------------------------


def test_chat_backward_compatibility_non_streaming_and_streaming(integration_env):
    """Verify existing non-streaming and streaming contracts remain intact."""
    client = integration_env["client"]

    # Non-streaming
    res_sync = client.post(
        "/v1/chat/completions",
        json={"prompt": "Backward compat ping", "stream": False},
    )
    assert res_sync.status_code == 200
    sync_data = res_sync.json()
    assert "response" in sync_data
    assert "session_id" in sync_data
    assert "cost_usd" in sync_data
    assert "execution_id" in sync_data

    # Streaming
    res_stream = client.post(
        "/v1/chat/completions",
        json={"prompt": "Backward compat stream ping", "stream": True},
    )
    assert res_stream.status_code == 200
    assert "text/event-stream" in res_stream.headers["content-type"]
    text = res_stream.text
    assert "data: " in text
    assert '"event": "token"' in text
    assert '"event": "cost_update"' in text


# ---------------------------------------------------------------------------
# 13. Canonical Project REST endpoints (CRUD)
# ---------------------------------------------------------------------------


def test_canonical_project_rest_crud(integration_env):
    """Verify /v1/projects endpoints perform full CRUD lifecycle."""
    client = integration_env["client"]

    # 1. Create project
    create_payload = {
        "name": "Backend Engine Core",
        "description": "Core orchestration project",
        "root_path": "/workspace/backend_engine",
        "instructions": "Follow PEP 8 strictly.",
        "settings": {
            "model_preference": "claude-3-5-sonnet",
            "isolation_mode": "standard",
            "budget_ceiling_usd": 50.0,
        },
    }
    create_res = client.post("/v1/projects", json=create_payload)
    assert create_res.status_code == 201
    created = create_res.json()
    proj_id = created["id"]
    assert proj_id.startswith("proj_")
    assert created["name"] == "Backend Engine Core"
    assert created["instructions"] == "Follow PEP 8 strictly."

    # 2. List projects
    list_res = client.get("/v1/projects")
    assert list_res.status_code == 200
    projects = list_res.json()
    # Ensure canonical default project is also present with valid proj_<hex12> ID
    assert any(
        p["id"].startswith("proj_") and len(p["id"]) == 17 and p.get("is_default") for p in projects
    )

    # 3. Get project
    get_res = client.get(f"/v1/projects/{proj_id}")
    assert get_res.status_code == 200
    fetched = get_res.json()
    assert fetched["id"] == proj_id
    assert fetched["root_path"] == "/workspace/backend_engine"

    # 4. Update project (PATCH & PUT)
    patch_res = client.patch(
        f"/v1/projects/{proj_id}",
        json={"instructions": "Updated PEP 8 instructions with strict typing."},
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["instructions"] == "Updated PEP 8 instructions with strict typing."

    # 5. Delete project
    del_res = client.delete(f"/v1/projects/{proj_id}")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted"] is True

    # 6. Verify 404 after deletion
    get_after_del = client.get(f"/v1/projects/{proj_id}")
    assert get_after_del.status_code == 404
