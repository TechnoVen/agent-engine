"""tests/test_channel_adapters.py

Unit and integration tests for Native Team Collaboration Channel Adapters (Phase 5C - Milestone M4).
Strictly adheres to ADR-013 (Zero Switch Dependency).
Covers:
- Task 5C.1: Slack Adapter (Socket Mode, Events API, Block Kit, mention stripping, envelope acks)
"""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from core.adapters.base import (
    AdapterCapability,
    AdapterExecutionRequest,
    AdapterHealthStatus,
)
from core.adapters.registry import get_adapter_registry
from core.adapters.slack import SlackAdapter
from services.python.server.api import app

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_slack_adapter_lifecycle_and_health(monkeypatch):
    """Verify SlackAdapter initialization, capabilities, and health check states."""
    # 1. Unconfigured / simulation mode
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)

    adapter = SlackAdapter()
    assert adapter.adapter_id == "slack"
    assert adapter.protocol == "slack-socket-mode"
    assert AdapterCapability.STREAMING in adapter.capabilities
    assert AdapterCapability.TOOLS in adapter.capabilities

    assert adapter.initialize() is True
    health = adapter.health_check()
    assert health.status == AdapterHealthStatus.DEGRADED
    assert health.details["configured"] is False

    # 2. Configured mode
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-mock-slack-token")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-mock-app-token")
    configured_adapter = SlackAdapter()
    configured_adapter.initialize()
    health_conf = configured_adapter.health_check()
    assert health_conf.status == AdapterHealthStatus.HEALTHY
    assert health_conf.details["has_bot_token"] is True
    assert health_conf.details["has_app_token"] is True


def test_slack_adapter_normalize_inbound():
    """Verify normalization of Socket Mode events, app mentions, and slash commands."""
    adapter = SlackAdapter()

    # 1. Socket Mode Events API envelope with mention
    socket_payload = {
        "envelope_id": "env_socket_12345",
        "type": "events_api",
        "payload": {
            "event": {
                "type": "app_mention",
                "user": "U12345678",
                "text": "<@U99887766> deploy latest build to staging",
                "channel": "C98765432",
                "ts": "1710681111.000200",
                "thread_ts": "1710680000.000100",
            }
        },
    }

    norm = adapter.normalize_inbound(socket_payload)
    assert norm["channel"] == "slack"
    assert norm["channel_id"] == "C98765432"
    assert norm["user_id"] == "U12345678"
    assert norm["text"] == "deploy latest build to staging"
    assert norm["thread_ts"] == "1710680000.000100"
    assert norm["envelope_id"] == "env_socket_12345"
    assert norm["event_type"] == "app_mention"

    # 2. Slash command format (/agent <prompt>)
    slash_payload = {
        "command": "/agent",
        "text": "run security audit",
        "channel_id": "C_DEV",
        "user_id": "U_ALICE",
        "user_name": "alice",
    }
    slash_norm = adapter.normalize_inbound(slash_payload)
    assert slash_norm["event_type"] == "slash_command"
    assert slash_norm["text"] == "run security audit"
    assert slash_norm["channel_id"] == "C_DEV"
    assert slash_norm["user_id"] == "U_ALICE"


def test_slack_adapter_format_outbound_and_envelope_ack():
    """Verify Block Kit message formatting and Socket Mode envelope acknowledgment."""
    adapter = SlackAdapter()

    # Outbound with thread
    outbound = adapter.format_outbound(
        content="Incident resolved in commit abc1234",
        channel_id="C_OPS",
        thread_ts="1710680000.000100",
    )
    assert outbound["channel"] == "C_OPS"
    assert outbound["thread_ts"] == "1710680000.000100"
    assert len(outbound["blocks"]) == 1
    assert outbound["blocks"][0]["type"] == "section"
    assert "Incident resolved" in outbound["blocks"][0]["text"]["text"]

    # Envelope acknowledgment
    ack = adapter.handle_socket_mode_envelope({"envelope_id": "env_xyz_789"})
    assert ack == {"envelope_id": "env_xyz_789"}


@pytest.mark.anyio
async def test_slack_adapter_execution_and_streaming():
    """Verify execution with Law 1/2 token budgeting and token streaming."""
    adapter = SlackAdapter()
    adapter.initialize()

    req = AdapterExecutionRequest(
        prompt="Synthesize weekly project milestones",
        session_id="slack_sess_1",
        context={"thread_ts": "1710680000.000100"},
    )

    # 1. Execute
    resp = await adapter.execute(req)
    assert resp.adapter_id == "slack"
    assert "Echo [slack]: Synthesize weekly project milestones" in resp.content
    assert resp.usage["total_tokens"] > 0
    assert resp.metadata["channel"] == "slack"
    assert resp.metadata["thread_ts"] == "1710680000.000100"

    # 2. Stream
    chunks = []
    async for chunk in adapter.stream(req):
        chunks.append(chunk)

    assert any(c.chunk_type == "token" for c in chunks)
    assert any(c.chunk_type == "done" for c in chunks)


def test_slack_webhook_api_integration():
    """Verify FastAPI /v1/channels/slack/events webhook endpoint."""
    client = TestClient(app)

    # 1. URL verification challenge
    challenge_payload = {
        "type": "url_verification",
        "token": "slack_token_xyz",
        "challenge": "challenge_string_998877",
    }
    res = client.post("/v1/channels/slack/events", json=challenge_payload)
    assert res.status_code == 200
    assert res.json() == {"challenge": "challenge_string_998877"}

    # 2. Events API message handling
    event_payload = {
        "type": "events_api",
        "envelope_id": "env_api_test",
        "payload": {
            "event": {
                "type": "app_mention",
                "text": "<@U12345> check deployment status",
                "user": "U_BOB",
                "channel": "C_PROD",
                "ts": "1710682222.000300",
            }
        },
    }
    res = client.post("/v1/channels/slack/events", json=event_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "received"
    assert data["normalized"]["text"] == "check deployment status"
    assert data["normalized"]["channel_id"] == "C_PROD"
    assert data["envelope_ack"] == {"envelope_id": "env_api_test"}

    # 3. Global Adapter Registry verification
    reg = get_adapter_registry()
    slack_in_reg = reg.get("slack")
    assert slack_in_reg is not None
    assert slack_in_reg.adapter_id == "slack"
