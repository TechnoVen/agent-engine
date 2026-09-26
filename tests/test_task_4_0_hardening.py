"""Test suite for Task 4.0 — Foundation Hardening, Security, and Contract Alignment.

Remediates findings from docs/PROJECT_REVIEW_2026-09-14.md:
- F01: Sidecar endpoint authentication, CORS, and plaintext secret protection
- F02: Supervisor lock-order and non-blocking health check
- F04: API contract alignment (/v1/health, /v1/memory/ingest, flexible envelopes)
- F05: Stale patch overwrite protection with disk content verification
- F09: Scheduled tasks SQLite persistence and CRUD API
- F12: Verification and lint exit code enforcement
"""

from fastapi.testclient import TestClient
import pytest

from core.storage.sqlite import SQLiteBackend
from services.python.server.api import app


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# F04: Health Check and Contract Alignment
# ---------------------------------------------------------------------------


def test_v1_health_canonical_endpoint(client):
    """Verify GET /v1/health conforms to SidecarHealth expected by desktop client."""
    res = client.get("/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert data["engine"] == "Agent Engine"
    assert "uptime_seconds" in data
    assert "timestamp" in data
    assert data["uptime_seconds"] >= 0


def test_healthz_liveness_probe(client):
    """Verify GET /healthz retains backward compatibility for supervisor probe."""
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "agent-engine-sidecar"
    assert "uptime_seconds" in data


def test_v1_memory_ingest_alias(client):
    """Verify POST /v1/memory/ingest exists and works identically to /v1/memory."""
    payload = {
        "content": "Test document for vector memory ingestion.",
        "source": "contract_test.txt",
    }
    res = client.post("/v1/memory/ingest", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "document_id" in data
    assert data["count"] >= 1


# ---------------------------------------------------------------------------
# F09: Scheduled Tasks Persistence and CRUD
# ---------------------------------------------------------------------------


def test_scheduled_tasks_crud_lifecycle(client, monkeypatch):
    """Verify full CRUD lifecycle and SQLite persistence for scheduled tasks."""
    # Ensure no auth required for initial list
    monkeypatch.delenv("AGENT_ENGINE_IPC_TOKEN", raising=False)

    # 1. List initial tasks (auto-seeded)
    list_res = client.get("/v1/tasks")
    assert list_res.status_code == 200
    tasks = list_res.json()["tasks"]
    assert len(tasks) >= 3
    task1 = tasks[0]
    assert "id" in task1
    assert "name" in task1
    assert "cron" in task1
    assert "status" in task1

    # 2. Create a new custom task
    create_payload = {
        "name": "Nightly Database Vacuum",
        "description": "Performs off-peak SQLite VACUUM and index optimization",
        "cron": "0 3 * * *",
        "cron_human": "Every day at 3:00 AM (Off-peak)",
        "agent_persona": "Security Auditor",
        "model": "instant",
        "is_off_peak": True,
        "notification_channel": "slack",
        "prompt": "Optimize all database indices and clean stale wal logs.",
    }
    create_res = client.post("/v1/tasks", json=create_payload)
    assert create_res.status_code == 200
    created_task = create_res.json()
    task_id = created_task["id"]
    assert created_task["name"] == create_payload["name"]
    assert created_task["status"] == "active"

    # 3. Toggle task status (active -> paused)
    toggle_res = client.post(f"/v1/tasks/{task_id}/toggle", json={"status": "paused"})
    assert toggle_res.status_code == 200
    assert toggle_res.json()["status"] == "paused"

    # 4. Trigger task execution (deferred runtime returns 501)
    run_res = client.post(f"/v1/tasks/{task_id}/run")
    assert run_res.status_code == 501
    assert run_res.json()["error_code"] == "RUNTIME_NOT_AVAILABLE"
    assert run_res.json()["target_milestone"] == "R4"

    # 5. Delete task
    del_res = client.delete(f"/v1/tasks/{task_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify task is gone
    toggle_after_del = client.post(f"/v1/tasks/{task_id}/toggle", json={"status": "active"})
    assert toggle_after_del.status_code == 404


# ---------------------------------------------------------------------------
# F01: IPC Token Authentication & Secret Protection
# ---------------------------------------------------------------------------


def test_ipc_token_authentication_enforcement(client, monkeypatch):
    """Verify privileged mutation and reveal endpoints require IPC token when configured."""
    secret_token = "ae_secret_ipc_test_token_98765"
    monkeypatch.setenv("AGENT_ENGINE_IPC_TOKEN", secret_token)

    # 1. Unauthenticated request to /v1/tasks creation should fail with 401
    task_payload = {
        "name": "Unauthorized Task",
        "cron": "0 0 * * *",
        "prompt": "Do unauthorized work",
    }
    res_unauth = client.post("/v1/tasks", json=task_payload)
    assert res_unauth.status_code == 401

    # 2. Request with invalid token should fail with 401
    res_bad = client.post(
        "/v1/tasks",
        json=task_payload,
        headers={"Authorization": "Bearer wrong_token"},
    )
    assert res_bad.status_code == 401

    # 3. Request with valid Bearer token should succeed
    res_auth = client.post(
        "/v1/tasks",
        json=task_payload,
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    assert res_auth.status_code == 200
    created_id = res_auth.json()["id"]

    # 4. Clean up created task with X-IPC-Token header
    del_res = client.delete(
        f"/v1/tasks/{created_id}",
        headers={"X-IPC-Token": secret_token},
    )
    assert del_res.status_code == 200


def test_credential_reveal_protection(client, monkeypatch):
    """Verify plaintext secret reveals are blocked for unauthenticated callers."""
    secret_token = "ae_secret_ipc_test_token_reveal"
    monkeypatch.setenv("AGENT_ENGINE_IPC_TOKEN", secret_token)

    # First store a credential using valid token
    store_res = client.post(
        "/v1/credentials",
        json={"service": "openai", "key": "api_key", "value": "sk-real-secret-12345"},
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    assert store_res.status_code == 201

    # Masked read with valid token should succeed
    masked_res = client.get(
        "/v1/credentials/openai/api_key",
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    assert masked_res.status_code == 200
    data = masked_res.json()
    assert data["value"] is None
    assert data["revealed"] is False
    assert data["masked_value"] != "sk-real-secret-12345"

    # Unauthenticated plaintext reveal should fail with 401
    unauth_reveal = client.get("/v1/credentials/openai/api_key?reveal=true")
    assert unauth_reveal.status_code == 401

    # Plaintext reveal is permanently eliminated in R2.6 and returns 403 Forbidden
    auth_reveal = client.get(
        "/v1/credentials/openai/api_key?reveal=true",
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    assert auth_reveal.status_code == 403
    assert "disabled" in auth_reveal.json()["detail"].lower()


# ---------------------------------------------------------------------------
# F05: Stale Patch Overwrite Protection
# ---------------------------------------------------------------------------


def test_stale_patch_overwrite_protection(tmp_path):
    """Verify backend rejects applying a staged patch if the target file was edited in between."""
    db_file = str(tmp_path / "test_storage.db")
    backend = SQLiteBackend(db_path=db_file)

    target_file = tmp_path / "main.py"
    original_code = "def hello():\n    return 'initial'\n"
    target_file.write_text(original_code, encoding="utf-8")

    # Stage patch based on original_code
    patched_code = "def hello():\n    return 'patched_improvement'\n"
    patch_id = backend.stage_patch(
        file_path=str(target_file),
        patch_type="refactor",
        risk_level="Low",
        report="Update return message",
        original_code=original_code,
        patched_code=patched_code,
    )
    assert patch_id > 0

    # User continues editing target_file on disk before applying patch
    intervening_user_edit = "def hello():\n    return 'user_newer_edit_do_not_destroy'\n"
    target_file.write_text(intervening_user_edit, encoding="utf-8")

    # Attempt to apply patch: MUST FAIL because file on disk has changed
    applied = backend.apply_patch(patch_id)
    assert applied is False, "Stale patch application must be rejected!"

    # Target file must remain intact with the user's intervening edit
    assert target_file.read_text(encoding="utf-8") == intervening_user_edit

    # If the file is restored to original_code, the patch should apply cleanly
    target_file.write_text(original_code, encoding="utf-8")
    applied_clean = backend.apply_patch(patch_id)
    assert applied_clean is True
    assert target_file.read_text(encoding="utf-8") == patched_code
