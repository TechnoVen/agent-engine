"""tests/test_r2_ipc_authentication.py

Tests for Milestone R2 Foundational Security Package:
- Task R2.1: Mandatory local IPC authentication
- Task R2.2: Origin/CORS hardening
Hardened according to CTO Review (header-only auth, rotation, cross-platform file security,
production/dev CORS split, minimal /healthz, leak redaction).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from services.python.server.app import create_app
from services.python.server.dependencies import (
    get_token_manager,
    redact_sensitive_headers,
    reset_token_manager,
)


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_auth():
    """Ensure token manager and environment are clean before and after each test."""
    reset_token_manager()
    old_env_token = os.environ.get("AGENT_ENGINE_IPC_TOKEN")
    old_enforced = os.environ.get("AGENT_ENGINE_AUTH_ENFORCED")
    old_env = os.environ.get("AGENT_ENGINE_ENV")
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
    if old_env is not None:
        os.environ["AGENT_ENGINE_ENV"] = old_env
    else:
        os.environ.pop("AGENT_ENGINE_ENV", None)


# ---------------------------------------------------------------------------
# Task R2.1: Mandatory Local IPC Authentication Tests
# ---------------------------------------------------------------------------


def test_1_unauthenticated_request_to_privileged_api_fails_401(client):
    """1. Unauthenticated request to /v1 yields HTTP 401 Unauthorized."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("strictly-enforced-secret-token-12345")

    res = client.get("/v1/telemetry")
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("detail", "")
    assert res.headers.get("www-authenticate") == "Bearer"


def test_2_wrong_token_fails_401(client):
    """2. Request with forged or mismatched token yields HTTP 401 Unauthorized."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("strictly-enforced-secret-token-12345")

    # Wrong Bearer token
    res1 = client.get("/v1/telemetry", headers={"Authorization": "Bearer wrong-token"})
    assert res1.status_code == 401

    # Wrong X-IPC-Token
    res2 = client.get("/v1/telemetry", headers={"X-IPC-Token": "wrong-token"})
    assert res2.status_code == 401


def test_3_valid_header_tokens_succeed(client):
    """3. Valid Bearer or X-IPC-Token header succeeds with 200."""
    manager = get_token_manager()
    manager.set_enforced(True)
    valid_token = "valid-test-ipc-token-abcdef123456"
    manager.set_token(valid_token)

    # Valid Bearer token
    res_bearer = client.get("/v1/telemetry", headers={"Authorization": f"Bearer {valid_token}"})
    assert res_bearer.status_code == 200
    assert "cpu_usage_percent" in res_bearer.json()

    # Valid X-IPC-Token
    res_ipc = client.get("/v1/telemetry", headers={"X-IPC-Token": valid_token})
    assert res_ipc.status_code == 200
    assert "cpu_usage_percent" in res_ipc.json()


def test_4_query_master_token_is_rejected(client):
    """4. Master IPC secret in query parameters (?token=...) MUST BE REJECTED with 401."""
    manager = get_token_manager()
    manager.set_enforced(True)
    valid_token = "valid-test-ipc-token-abcdef123456"
    manager.set_token(valid_token)

    # Attempting to supply master token in URL query parameter without headers fails closed
    res = client.get(f"/v1/telemetry?token={valid_token}")
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("detail", "")


def test_5_old_launch_token_after_rotation_fails(client):
    """5. Launch A token valid during Launch A, but invalid after rotation to Launch B."""
    manager = get_token_manager()
    manager.set_enforced(True)

    # Launch A
    launch_a_token = manager.rotate_token()
    assert len(launch_a_token) == 64

    # Launch A token succeeds
    res_a = client.get("/v1/telemetry", headers={"Authorization": f"Bearer {launch_a_token}"})
    assert res_a.status_code == 200

    # Restart / Launch B rotation
    launch_b_token = manager.rotate_token()
    assert launch_b_token != launch_a_token

    # Launch A token now fails with 401
    res_old = client.get("/v1/telemetry", headers={"Authorization": f"Bearer {launch_a_token}"})
    assert res_old.status_code == 401

    # Launch B token succeeds
    res_new = client.get("/v1/telemetry", headers={"Authorization": f"Bearer {launch_b_token}"})
    assert res_new.status_code == 200


def test_6_healthz_endpoint_accessible_unauthenticated(client):
    """6. Minimal liveness endpoint /healthz remains accessible unauthenticated."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("strictly-enforced-secret-token-12345")

    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "agent-engine-sidecar"
    assert "uptime_seconds" in data


def test_7_healthz_exposes_no_sensitive_details(client):
    """7. GET /healthz must NEVER reveal provider names, models, paths, credentials, or secrets."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("strictly-enforced-secret-token-12345")

    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()

    forbidden_keys = {
        "providers",
        "models",
        "inventory",
        "paths",
        "root",
        "credentials",
        "token",
        "secret",
        "projects",
        "user",
        "identity",
        "keys",
    }
    for key in forbidden_keys:
        assert key not in data, f"Sensitive key '{key}' must not be exposed in /healthz"


def test_8_malformed_and_empty_credentials_fail_closed(client):
    """Verify malformed, blank, or whitespace-only headers fail closed with 401."""
    manager = get_token_manager()
    manager.set_enforced(True)
    manager.set_token("valid-test-token-123")

    malformed_headers = [
        {"Authorization": ""},
        {"Authorization": "   "},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer    "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"X-IPC-Token": ""},
        {"X-IPC-Token": "   "},
    ]

    for headers in malformed_headers:
        res = client.get("/v1/telemetry", headers=headers)
        assert res.status_code == 401, f"Header {headers} must fail with 401"


def test_9_secret_file_protection_and_single_authoritative_path(tmp_path, monkeypatch):
    """Verify single authoritative path ~/.agent_engine/ipc.token with 0600 POSIX mode."""
    os.environ.pop("AGENT_ENGINE_IPC_TOKEN", None)
    reset_token_manager()

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    manager = get_token_manager()
    token = manager.get_token()

    # Must be 256-bit = 64 hex characters
    assert len(token) == 64

    # Must reside at single authoritative path
    handshake_file = fake_home / ".agent_engine" / "ipc.token"
    assert handshake_file.exists()
    assert handshake_file.read_text() == token

    # Must not create a secondary data/ipc.token copy
    assert not Path("data/ipc.token").exists()

    # POSIX permissions verification
    if os.name != "nt":
        file_mode = stat.S_IMODE(handshake_file.stat().st_mode)
        assert file_mode == 0o600, f"Expected 0600 permissions, got {oct(file_mode)}"

    # Clean shutdown removes handshake file
    manager.cleanup_handshake_file()
    assert not handshake_file.exists()


# ---------------------------------------------------------------------------
# Task R2.2: Origin/CORS Hardening Tests
# ---------------------------------------------------------------------------


def test_10_production_cors_allows_tauri_origins():
    """10. Production mode allows official Tauri desktop origins."""
    os.environ["AGENT_ENGINE_ENV"] = "production"
    prod_app = create_app()
    prod_client = TestClient(prod_app)

    tauri_origins = [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]
    for origin in tauri_origins:
        res = prod_client.options(
            "/healthz",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert res.headers.get("access-control-allow-origin") == origin


def test_11_production_cors_rejects_arbitrary_localhost_ports():
    """11. Production mode strictly rejects arbitrary localhost ports (e.g. 8080, 9999)."""
    os.environ["AGENT_ENGINE_ENV"] = "production"
    prod_app = create_app()
    prod_client = TestClient(prod_app)

    unauthorized_localhosts = [
        "http://localhost:8080",
        "http://localhost:9999",
        "http://127.0.0.1:8080",
        "http://localhost:4000",
    ]
    for origin in unauthorized_localhosts:
        res = prod_client.options(
            "/healthz",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert (
            res.headers.get("access-control-allow-origin") is None
        ), f"Production CORS should not allow arbitrary port {origin}"


def test_12_development_cors_allows_configured_dev_origins():
    """12. Development mode allows configured Vite/Tauri development server ports."""
    os.environ["AGENT_ENGINE_ENV"] = "development"
    dev_app = create_app()
    dev_client = TestClient(dev_app)

    dev_origins = [
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]
    for origin in dev_origins:
        res = dev_client.options(
            "/healthz",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert (
            res.headers.get("access-control-allow-origin") == origin
        ), f"Dev CORS should allow dev server origin {origin}"


def test_13_hostile_web_origins_rejected_in_both_modes():
    """13. Hostile web origins (e.g. malicious-website.com) are rejected in all modes."""
    hostile_origins = [
        "https://malicious-website.com",
        "http://evil-attacker.org",
        "https://phishing.site",
    ]

    for env_mode in ("production", "development"):
        os.environ["AGENT_ENGINE_ENV"] = env_mode
        test_app = create_app()
        test_client = TestClient(test_app)

        for origin in hostile_origins:
            res = test_client.options(
                "/healthz",
                headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
            )
            assert (
                res.headers.get("access-control-allow-origin") is None
            ), f"Hostile origin {origin} must be rejected in {env_mode} mode"


def test_14_token_redaction_utility():
    """14. Header redaction utility masks sensitive authentication headers."""
    raw_headers = {
        "Authorization": "Bearer secret_token_xyz",
        "X-IPC-Token": "secret_ipc_token_123",
        "Content-Type": "application/json",
        "X-Custom-Header": "regular_value",
    }
    redacted = redact_sensitive_headers(raw_headers)
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["X-IPC-Token"] == "[REDACTED]"
    assert redacted["Content-Type"] == "application/json"
    assert redacted["X-Custom-Header"] == "regular_value"
