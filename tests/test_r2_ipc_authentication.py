"""tests/test_r2_ipc_authentication.py

Tests for Milestone R2 Foundational Security Package:
- Task R2.1: Mandatory local IPC authentication
- Task R2.2: Origin/CORS hardening
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from services.python.server.api import app
from services.python.server.dependencies import (
    get_token_manager,
    reset_token_manager,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_auth():
    """Ensure token manager is clean before and after each test."""
    reset_token_manager()
    old_env_token = os.environ.get("AGENT_ENGINE_IPC_TOKEN")
    old_enforced = os.environ.get("AGENT_ENGINE_AUTH_ENFORCED")
    yield
    reset_token_manager()
    if old_env_token is not None:
        os.environ["AGENT_ENGINE_IPC_TOKEN"] = old_env_token
    else:
        os.environ.pop("AGENT_ENGINE_IPC_TOKEN", None)
    if old_enforced is not None:
        os.environ["AGENT_ENGINE_AUTH_ENFORCED"] = old_enforced
    else:
        os.environ.pop("AGENT_ENGINE_AUTH_ENFORCED", None)


# ---------------------------------------------------------------------------
# Task R2.1: Mandatory Local IPC Authentication Tests
# ---------------------------------------------------------------------------


def test_healthz_endpoint_accessible_unauthenticated(client):
    """Verify minimal liveness endpoint /healthz remains unauthenticated (public)."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("strictly-enforced-secret-token-12345")

    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "agent-engine-sidecar"


def test_unauthenticated_request_to_privileged_api_fails_401(client):
    """Verify request to /v1 endpoint without token yields HTTP 401 Unauthorized."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("strictly-enforced-secret-token-12345")

    res = client.get("/v1/telemetry")
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("detail", "")
    assert res.headers.get("www-authenticate") == "Bearer"


def test_invalid_token_fails_401(client):
    """Verify request with forged or mismatched token yields HTTP 401 Unauthorized."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("strictly-enforced-secret-token-12345")

    # Wrong Bearer token
    res1 = client.get("/v1/telemetry", headers={"Authorization": "Bearer wrong-token"})
    assert res1.status_code == 401

    # Wrong X-IPC-Token
    res2 = client.get("/v1/telemetry", headers={"X-IPC-Token": "wrong-token"})
    assert res2.status_code == 401


def test_valid_bearer_token_succeeds(client):
    """Verify request with valid Bearer token in Authorization header succeeds."""
    manager = get_token_manager()
    manager.set_enforced(True)
    valid_token = "valid-test-ipc-token-abcdef123456"
    manager.set_token(valid_token)

    res = client.get("/v1/telemetry", headers={"Authorization": f"Bearer {valid_token}"})
    assert res.status_code == 200
    assert "cpu_usage_percent" in res.json()


def test_valid_x_ipc_token_header_succeeds(client):
    """Verify request with valid X-IPC-Token custom header succeeds."""
    manager = get_token_manager()
    manager.set_enforced(True)
    valid_token = "valid-test-ipc-token-abcdef123456"
    manager.set_token(valid_token)

    res = client.get("/v1/telemetry", headers={"X-IPC-Token": valid_token})
    assert res.status_code == 200
    assert "cpu_usage_percent" in res.json()


def test_valid_token_query_parameter_succeeds(client):
    """Verify request with valid token in query param succeeds (for SSE streams)."""
    manager = get_token_manager()
    manager.set_enforced(True)
    valid_token = "valid-test-ipc-token-abcdef123456"
    manager.set_token(valid_token)

    res = client.get(f"/v1/telemetry?token={valid_token}")
    assert res.status_code == 200
    assert "cpu_usage_percent" in res.json()


def test_per_launch_secret_generation_and_file_permissions(tmp_path, monkeypatch):
    """Verify auto-generation of 256-bit cryptographic token with 0600 file permissions."""
    os.environ.pop("AGENT_ENGINE_IPC_TOKEN", None)
    reset_token_manager()

    # Direct token file candidate to temp directory
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    manager = get_token_manager()
    token = manager.get_token()

    # Must be 256 bits = 64 hex characters
    assert len(token) == 64
    assert all(c in "0123456789abcdef" for c in token)

    # Check handshake file was written with 0600 permissions
    handshake_file = fake_home / ".agent_engine" / "ipc.token"
    assert handshake_file.exists()
    assert handshake_file.read_text() == token

    file_mode = stat.S_IMODE(handshake_file.stat().st_mode)
    assert file_mode == 0o600


# ---------------------------------------------------------------------------
# Task R2.2: Origin/CORS Hardening Tests
# ---------------------------------------------------------------------------


def test_cors_rejects_arbitrary_web_origins(client):
    """Verify requests from untrusted web origins do not receive CORS allow headers."""
    # Simple request with hostile origin
    res = client.get("/healthz", headers={"Origin": "https://malicious-website.com"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") != "https://malicious-website.com"

    # Pre-flight OPTIONS request from hostile origin
    preflight = client.options(
        "/v1/telemetry",
        headers={
            "Origin": "https://attacker.evil",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") != "https://attacker.evil"


def test_cors_allows_tauri_and_loopback_origins(client):
    """Verify trusted desktop shell and loopback origins receive CORS allow headers."""
    trusted_origins = [
        "tauri://localhost",
        "http://tauri.localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    for origin in trusted_origins:
        res = client.options(
            "/healthz",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            res.headers.get("access-control-allow-origin") == origin
        ), f"Origin {origin} was not allowed"
