"""Comprehensive unit and integration tests for Unified Session Store (Task 1.6).

Covers:
- Domain model serialization & metrics (UnifiedSession, UnifiedMessage, AgentParticipant, ToolCall)
- Format converters (OpenAI, Anthropic, DSPy, Markdown, JSONL)
- Storage backend & high-level UnifiedSessionStore operations
- Multi-agent turn appending, token/cost attribution, participant discovery
- Session branching & forking at specific message points
- Cross-session full-text search
- FastAPI REST endpoints via TestClient
- Backwards compatibility with existing StorageBackend calls
"""

import json
import pytest
from fastapi.testclient import TestClient

from core.session import (
    AgentParticipant,
    ToolCall,
    UnifiedMessage,
    UnifiedSession,
    UnifiedSessionStore,
    from_openai_messages,
    get_session_store,
    reset_session_store,
    to_anthropic_messages,
    to_dspy_history,
    to_jsonl,
    to_markdown,
    to_openai_messages,
)
from core.storage import SQLiteBackend, reset_storage_backend
from services.python.server.api import app


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    """Reset global storage backend and session store before/after each test."""
    reset_session_store()
    reset_storage_backend()
    yield
    reset_session_store()
    reset_storage_backend()


@pytest.fixture
def memory_store():
    """Create an isolated in-memory UnifiedSessionStore."""
    backend = SQLiteBackend(db_path=":memory:")
    return UnifiedSessionStore(backend=backend)


@pytest.fixture
def api_client(tmp_path):
    """Create a TestClient with a fresh isolated SQLite database."""
    test_db = str(tmp_path / "test_api_sessions.db")
    backend = SQLiteBackend(db_path=test_db)
    get_session_store(backend=backend, force_new=True)
    return TestClient(app)


# ==============================================================================
# 1. DOMAIN MODEL & METRICS TESTS
# ==============================================================================


def test_tool_call_serialization():
    tc = ToolCall(
        call_id="call_calc_1",
        tool_name="calculator",
        arguments={"expression": "12 * 8"},
        result="96",
        status="success",
        latency_ms=12.5,
    )
    d = tc.to_dict()
    assert d["call_id"] == "call_calc_1"
    assert d["tool_name"] == "calculator"
    assert d["arguments"]["expression"] == "12 * 8"
    assert d["result"] == "96"

    reconstituted = ToolCall.from_dict(d)
    assert reconstituted.call_id == tc.call_id
    assert reconstituted.arguments == tc.arguments
    assert reconstituted.latency_ms == 12.5


def test_agent_participant_serialization():
    part = AgentParticipant(
        agent_id="code_sentry",
        agent_name="Code Sentry",
        role="reviewer",
        model="claude-3-5-sonnet",
        metadata={"permission": "read_write"},
    )
    d = part.to_dict()
    assert d["agent_id"] == "code_sentry"
    assert d["role"] == "reviewer"

    reconstituted = AgentParticipant.from_dict(d)
    assert reconstituted.agent_id == part.agent_id
    assert reconstituted.model == "claude-3-5-sonnet"


def test_unified_message_and_session_metrics():
    session = UnifiedSession(
        session_id="sess_test_101",
        title="Architecture Discussion",
        user_id="alice",
        channel="slack",
    )

    tc = ToolCall(call_id="c1", tool_name="system_info", result="Linux x86_64")
    m1 = UnifiedMessage(
        message_id="msg_1",
        session_id="sess_test_101",
        role="user",
        content="What is system load?",
        sender_id="alice",
    )
    m2 = UnifiedMessage(
        message_id="msg_2",
        session_id="sess_test_101",
        role="assistant",
        content="System details checked.",
        sender_id="sentry_agent",
        agent_id="sentry_agent",
        sender_name="Sentry Agent",
        model="llama3.1",
        tokens={"prompt": 40, "completion": 60, "total": 100},
        cost_usd=0.0002,
        tool_calls=[tc],
    )

    session.append_message(m1)
    session.append_message(m2)

    assert session.total_messages == 2
    assert session.total_tokens == 100
    assert abs(session.total_cost_usd - 0.0002) < 1e-6

    # Verify sender was auto-registered as participant
    part = session.get_participant("sentry_agent")
    assert part is not None
    assert part.agent_name == "Sentry Agent"
    assert part.model == "llama3.1"

    # Test serialization roundtrip
    s_dict = session.to_dict()
    assert s_dict["total_messages"] == 2
    assert s_dict["total_tokens"] == 100
    assert len(s_dict["participants"]) == 1

    restored = UnifiedSession.from_dict(s_dict)
    assert restored.session_id == session.session_id
    assert len(restored.messages) == 2
    assert restored.get_message("msg_2").tool_calls[0].tool_name == "system_info"


# ==============================================================================
# 2. FORMAT CONVERTER TESTS
# ==============================================================================


def test_openai_format_converters():
    session = UnifiedSession(session_id="sess_oai", title="OpenAI Conv")
    session.append_message(
        UnifiedMessage(role="user", content="Calculate 5+5", sender_id="usr_bob")
    )
    session.append_message(
        UnifiedMessage(
            role="assistant",
            content="Running calculation...",
            tool_calls=[ToolCall(call_id="call_99", tool_name="calc", arguments={"exp": "5+5"})],
        )
    )
    session.append_message(
        UnifiedMessage(
            role="tool",
            content="10",
            metadata={"tool_call_id": "call_99"},
        )
    )

    oai_msgs = to_openai_messages(session)
    assert len(oai_msgs) == 3
    assert oai_msgs[0]["role"] == "user"
    assert oai_msgs[1]["role"] == "assistant"
    assert len(oai_msgs[1]["tool_calls"]) == 1
    assert oai_msgs[1]["tool_calls"][0]["id"] == "call_99"
    assert oai_msgs[2]["role"] == "tool"
    assert oai_msgs[2]["tool_call_id"] == "call_99"

    # Ingest back from OpenAI messages
    restored = from_openai_messages(oai_msgs, title="Re-imported")
    assert restored.title == "Re-imported"
    assert len(restored.messages) == 3
    assert restored.messages[1].tool_calls[0].tool_name == "calc"


def test_anthropic_and_dspy_converters():
    session = UnifiedSession(session_id="sess_ant", title="Anthropic Conv")
    session.append_message(
        UnifiedMessage(role="system", content="You are a senior python engineer.")
    )
    session.append_message(UnifiedMessage(role="user", content="Explain GIL"))
    session.append_message(
        UnifiedMessage(
            role="assistant",
            content="The GIL is the Global Interpreter Lock...",
            agent_id="explainer_agent",
            model="gpt-4o",
        )
    )

    sys_prompt, anthropic_msgs = to_anthropic_messages(session)
    assert sys_prompt == "You are a senior python engineer."
    assert len(anthropic_msgs) == 2
    assert anthropic_msgs[0]["role"] == "user"
    assert anthropic_msgs[1]["role"] == "assistant"

    # Test DSPy history converter
    turns = to_dspy_history(session)
    assert len(turns) == 1
    assert turns[0]["input"] == "Explain GIL"
    assert "Global Interpreter Lock" in turns[0]["response"]


def test_markdown_and_jsonl_export():
    session = UnifiedSession(session_id="sess_exp", title="Export Showcase")
    session.append_message(UnifiedMessage(role="user", content="Deploy v1.2", sender_id="dev1"))
    session.append_message(
        UnifiedMessage(
            role="assistant",
            content="Deployment started",
            tool_calls=[ToolCall(call_id="c_dep", tool_name="deployer", arguments={"env": "prod"})],
            tokens={"total": 85},
            cost_usd=0.001,
        )
    )

    md = to_markdown(session)
    assert "# Session: Export Showcase" in md
    assert "Tool Call: <code>deployer</code>" in md
    assert "Tokens: 85" in md

    jsonl_str = to_jsonl(session)
    lines = jsonl_str.strip().split("\n")
    assert len(lines) == 2
    parsed_l1 = json.loads(lines[0])
    assert parsed_l1["content"] == "Deploy v1.2"


# ==============================================================================
# 3. UNIFIED SESSION STORE CORE OPERATIONS
# ==============================================================================


def test_session_store_crud_lifecycle(memory_store):
    # 1. Create session
    sess = memory_store.create_session(
        title="Incident Response",
        user_id="usr_charlie",
        channel="whatsapp",
        participants=[
            AgentParticipant(agent_id="pager_agent", agent_name="Pager Agent", role="primary")
        ],
        metadata={"severity": "P1"},
    )
    assert sess.session_id.startswith("sess_")
    assert sess.title == "Incident Response"
    assert sess.channel == "whatsapp"
    assert len(sess.participants) == 1

    # 2. Get session
    fetched = memory_store.get_session(sess.session_id)
    assert fetched is not None
    assert fetched.session_id == sess.session_id
    assert fetched.metadata["severity"] == "P1"

    # 3. Update session
    updated = memory_store.update_session(
        session_id=sess.session_id,
        title="Resolved Incident P1",
        status="closed",
        summary="Server was restarted and traffic normalized.",
    )
    assert updated.title == "Resolved Incident P1"
    assert updated.status == "closed"
    assert updated.summary == "Server was restarted and traffic normalized."

    # 4. List sessions
    listed = memory_store.list_sessions(channel="whatsapp")
    assert len(listed) == 1
    assert listed[0].session_id == sess.session_id

    # Filter by non-matching channel
    assert len(memory_store.list_sessions(channel="desktop")) == 0

    # 5. Delete session
    assert memory_store.delete_session(sess.session_id) is True
    assert memory_store.get_session(sess.session_id) is None


def test_session_store_append_and_multiagent(memory_store):
    sess = memory_store.create_session(title="Collaborative Design", channel="teams")

    # User message
    msg1 = memory_store.append_message(
        session_id=sess.session_id,
        role="user",
        content="Design cache architecture",
        sender_id="dev_user",
        sender_name="Alice Dev",
    )
    assert msg1.session_id == sess.session_id

    # Agent 1 turn
    memory_store.append_message(
        session_id=sess.session_id,
        role="assistant",
        content="I propose Chroma-backed semantic cache.",
        sender_id="agent_arch",
        sender_name="Architect Agent",
        agent_id="agent_arch",
        model="gpt-4o",
        tokens={"prompt": 100, "completion": 80, "total": 180},
        cost_usd=0.0018,
    )

    # Agent 2 review turn
    memory_store.append_message(
        session_id=sess.session_id,
        role="assistant",
        content="Agreed, with 0.95 cosine threshold.",
        sender_id="agent_critic",
        sender_name="Reviewer Agent",
        agent_id="agent_critic",
        model="claude-3-5-sonnet",
        tokens={"prompt": 180, "completion": 40, "total": 220},
        cost_usd=0.0022,
    )

    reloaded = memory_store.get_session(sess.session_id)
    assert reloaded.total_messages == 3
    assert reloaded.total_tokens == 400
    assert abs(reloaded.total_cost_usd - 0.004) < 1e-6
    assert len(reloaded.participants) == 2


def test_session_forking_and_branching(memory_store):
    sess = memory_store.create_session(title="Main Branch Pipeline")

    memory_store.append_message(sess.session_id, role="user", content="Step 1: Ingest data")
    m2 = memory_store.append_message(
        sess.session_id, role="assistant", content="Data ingested: 500 records"
    )
    memory_store.append_message(sess.session_id, role="user", content="Step 2: Train Model A")
    memory_store.append_message(sess.session_id, role="assistant", content="Model A accuracy: 88%")

    # Fork at m2 (branching to try Model B instead)
    forked = memory_store.fork_session(
        session_id=sess.session_id,
        fork_point_message_id=m2.message_id,
        new_title="Branch: Try Model B",
    )

    assert forked.session_id != sess.session_id
    assert forked.title == "Branch: Try Model B"
    assert forked.parent_session_id == sess.session_id
    assert forked.fork_point_message_id == m2.message_id
    assert forked.total_messages == 2
    assert forked.messages[0].content == "Step 1: Ingest data"
    assert forked.messages[1].content == "Data ingested: 500 records"

    # Original session remains untouched
    original = memory_store.get_session(sess.session_id)
    assert original.total_messages == 4


def test_session_search_and_export(memory_store):
    sess1 = memory_store.create_session(title="Postgres Connection Leak Investigation")
    memory_store.append_message(
        sess1.session_id, role="user", content="Check pgpool health metrics"
    )

    sess2 = memory_store.create_session(title="Frontend Styling")
    memory_store.append_message(
        sess2.session_id, role="user", content="Update CSS palette for dark mode"
    )

    # Search for "pgpool"
    results = memory_store.search_sessions(query="pgpool")
    assert len(results) == 1
    assert results[0]["session_id"] == sess1.session_id

    # Export formats
    md = memory_store.export_session(sess1.session_id, format="markdown")
    assert "pgpool health metrics" in md

    json_str = memory_store.export_session(sess1.session_id, format="json")
    parsed = json.loads(json_str)
    assert parsed["session_id"] == sess1.session_id


# ==============================================================================
# 4. FASTAPI REST ENDPOINTS INTEGRATION TESTS
# ==============================================================================


def test_api_session_lifecycle(api_client):
    # 1. POST /v1/sessions
    resp = api_client.post(
        "/v1/sessions",
        json={
            "title": "API Test Session",
            "user_id": "api_tester",
            "channel": "desktop",
            "participants": [
                {"agent_id": "tester_bot", "agent_name": "Tester Bot", "role": "primary"}
            ],
            "metadata": {"test_env": "pytest"},
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    sid = created["session_id"]
    assert created["title"] == "API Test Session"
    assert created["channel"] == "desktop"
    assert len(created["participants"]) == 1

    # 2. GET /v1/sessions
    resp = api_client.get("/v1/sessions?channel=desktop")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # 3. GET /v1/sessions/{session_id}
    resp = api_client.get(f"/v1/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == sid

    # 4. POST /v1/sessions/{session_id}/messages
    resp = api_client.post(
        f"/v1/sessions/{sid}/messages",
        json={
            "role": "user",
            "content": "Hello from API client",
            "sender_id": "api_tester",
        },
    )
    assert resp.status_code == 201
    msg1 = resp.json()
    assert msg1["content"] == "Hello from API client"

    # Append assistant message with tool call
    resp = api_client.post(
        f"/v1/sessions/{sid}/messages",
        json={
            "role": "assistant",
            "content": "Running test diagnostic...",
            "agent_id": "tester_bot",
            "sender_name": "Tester Bot",
            "model": "gpt-4o",
            "tokens": {"prompt": 20, "completion": 30, "total": 50},
            "cost_usd": 0.0005,
            "tool_calls": [
                {"call_id": "c_diag", "tool_name": "diagnostic_tool", "arguments": {"ping": True}}
            ],
        },
    )
    assert resp.status_code == 201
    assert len(resp.json()["tool_calls"]) == 1

    # Verify session metrics updated
    resp = api_client.get(f"/v1/sessions/{sid}")
    assert resp.json()["total_messages"] == 2
    assert resp.json()["total_tokens"] == 50

    # 5. POST /v1/sessions/{session_id}/fork
    resp = api_client.post(
        f"/v1/sessions/{sid}/fork",
        json={
            "fork_point_message_id": msg1["message_id"],
            "new_title": "Forked API Branch",
        },
    )
    assert resp.status_code == 201
    forked = resp.json()
    assert forked["parent_session_id"] == sid
    assert forked["total_messages"] == 1

    # 6. GET /v1/sessions/{session_id}/export
    resp = api_client.get(f"/v1/sessions/{sid}/export?format=markdown")
    assert resp.status_code == 200
    assert "Hello from API client" in resp.json()["content"]

    # 7. GET /v1/sessions/search
    resp = api_client.get("/v1/sessions/search?q=diagnostic")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    assert resp.json()[0]["session_id"] == sid

    # 8. PATCH /v1/sessions/{session_id}
    resp = api_client.patch(
        f"/v1/sessions/{sid}",
        json={"title": "Updated API Title", "status": "archived"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated API Title"
    assert resp.json()["status"] == "archived"

    # 9. DELETE /v1/sessions/{session_id}
    resp = api_client.delete(f"/v1/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Verify 404
    resp = api_client.get(f"/v1/sessions/{sid}")
    assert resp.status_code == 404


# ==============================================================================
# 5. BACKWARDS COMPATIBILITY WITH EXISTING STORAGE CALLS
# ==============================================================================


def test_storage_backend_backwards_compatibility():
    backend = SQLiteBackend(db_path=":memory:")

    # Old-style create_session
    s = backend.create_session("sess_old", user_id="u_legacy", metadata={"source": "legacy_call"})
    assert s["session_id"] == "sess_old"
    assert s["user_id"] == "u_legacy"
    assert s["title"] == "Untitled Session"
    assert s["channel"] == "web"
    assert s["status"] == "active"

    # Old-style update_session
    assert backend.update_session("sess_old", messages=[{"role": "user", "content": "hi"}]) is True

    # Old-style list_sessions
    listed = backend.list_sessions(user_id="u_legacy")
    assert len(listed) == 1
    assert listed[0]["session_id"] == "sess_old"

    # Enhanced search_sessions on backend
    search_res = backend.search_sessions("hi")
    assert len(search_res) == 1
    assert search_res[0]["session_id"] == "sess_old"

    # Enhanced fork_session on backend
    fork_res = backend.fork_session(
        "sess_old", new_session_id="sess_old_fork", title="Forked Legacy"
    )
    assert fork_res is not None
    assert fork_res["session_id"] == "sess_old_fork"
    assert fork_res["parent_session_id"] == "sess_old"
    assert len(fork_res["messages"]) == 1
