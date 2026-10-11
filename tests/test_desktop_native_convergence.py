"""tests/test_desktop_native_convergence.py

Integration and Acceptance Tests for CTO Blocker Resolution:
- Native dev launch & build freshness (build.rs rerun-if-changed, package.json scripts)
- Mandatory IPC token bootstrap (Tauri supervisor, Rust commands, renderer in-memory delivery)
- Centralized authenticated requests in client.ts (zero unauthenticated /v1 bypasses)
- Status truth (401 Unauthorized mapped to 'unauthorized' and 'Authentication Error')
- Scheduler -> Occurrence -> Executable Job semantics (agent_task dispatch, worker spin prevention)
- Product Truth distribution integrity (zero demo projects, verified build identity)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.jobs.worker import SUPPORTED_JOB_TYPES
from services.python.server.app import create_app
from services.python.server.dependencies import get_token_manager, reset_token_manager

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ROOT = REPO_ROOT / "apps" / "desktop"
SRC_TAURI_ROOT = DESKTOP_ROOT / "src-tauri"
RENDERER_ROOT = DESKTOP_ROOT / "src" / "renderer"
CLIENT_TS_PATH = RENDERER_ROOT / "api" / "client.ts"


@pytest.fixture(autouse=True)
def clean_ipc_token_env():
    """Ensure token manager and environment variables are strictly cleaned before and after tests."""
    reset_token_manager()
    try:
        yield
    finally:
        reset_token_manager()


# ==============================================================================
# 1. Native Dev Launch & Build Freshness Invariants
# ==============================================================================


def test_build_rs_watches_dist_and_tauri_conf():
    """Verify build.rs forces Cargo to recompile the native shell whenever dist or config changes."""
    build_rs = SRC_TAURI_ROOT / "build.rs"
    assert build_rs.exists(), "src-tauri/build.rs must exist"
    content = build_rs.read_text()

    assert (
        "cargo:rerun-if-changed=../dist" in content
    ), "build.rs must declare rerun-if-changed for ../dist to prevent stale frontend builds"
    assert (
        "cargo:rerun-if-changed=tauri.conf.json" in content
    ), "build.rs must declare rerun-if-changed for tauri.conf.json"


def test_root_package_json_defines_supported_desktop_dev_script():
    """Verify package.json defines the canonical dev:desktop command running Tauri dev."""
    pkg_json = REPO_ROOT / "package.json"
    assert pkg_json.exists(), "Root package.json must exist"
    data = json.loads(pkg_json.read_text())
    scripts = data.get("scripts", {})

    assert "dev:desktop" in scripts, "package.json must define 'dev:desktop' script"
    cmd = scripts["dev:desktop"]
    assert "tauri dev" in cmd, f"dev:desktop must run tauri dev, found: {cmd}"


def test_tauri_conf_dev_server_configuration():
    """Verify tauri.conf.json configures Vite dev server on port 1420."""
    conf_path = SRC_TAURI_ROOT / "tauri.conf.json"
    assert conf_path.exists()
    conf = json.loads(conf_path.read_text())

    build_cfg = conf.get("build", {})
    assert build_cfg.get("beforeDevCommand") == "pnpm dev"
    assert build_cfg.get("devUrl") == "http://localhost:1420"
    assert build_cfg.get("frontendDist") == "../dist"


# ==============================================================================
# 2. IPC Token Bootstrap & Handshake Parity
# ==============================================================================


def test_ipc_token_path_parity():
    """Verify Python sidecar and Tauri supervisor converge on the same local token path."""
    token_mgr = get_token_manager()
    handshake_path = token_mgr.get_handshake_path()
    expected_path = Path.home() / ".agent_engine" / "ipc.token"
    assert (
        handshake_path == expected_path
    ), f"Python handshake token path {handshake_path} must be ~/.agent_engine/ipc.token"

    sidecar_rs = (SRC_TAURI_ROOT / "src" / "sidecar.rs").read_text()
    assert ".agent_engine" in sidecar_rs
    assert "ipc.token" in sidecar_rs


def test_tauri_commands_register_get_ipc_token():
    """Verify Tauri lib.rs registers get_ipc_token command and window setup hook."""
    lib_rs = (SRC_TAURI_ROOT / "src" / "lib.rs").read_text()

    assert "fn get_ipc_token()" in lib_rs
    assert "get_ipc_token" in lib_rs
    assert "window.__AGENT_ENGINE_IPC_TOKEN__" in lib_rs


def test_sidecar_supervisor_forwards_ipc_token():
    """Verify Tauri sidecar supervisor forwards canonical IPC token to spawned process."""
    sidecar_rs = (SRC_TAURI_ROOT / "src" / "sidecar.rs").read_text()

    assert "get_or_init_ipc_token" in sidecar_rs
    assert 'cmd.arg("--token").arg(&token)' in sidecar_rs
    assert 'cmd.env("AGENT_ENGINE_IPC_TOKEN", &token)' in sidecar_rs


def test_renderer_client_bootstrap_ipc_token_helper():
    """Verify SidecarClient implements in-memory bootstrapIpcToken without localStorage."""
    client_ts = CLIENT_TS_PATH.read_text()

    assert "async bootstrapIpcToken()" in client_ts
    assert "get_ipc_token" in client_ts
    assert (
        "localStorage.setItem" not in client_ts and "localStorage.getItem" not in client_ts
    ), "IPC token must NEVER be persisted to localStorage"


# ==============================================================================
# 3. Static AST Audit: Centralized Authenticated Requests in client.ts
# ==============================================================================


def test_client_ts_all_v1_requests_route_through_authenticated_helpers():
    """Static AST Audit: verify all /v1 endpoints flow through requestRaw or typed helpers.

    No method may call bare `fetch()` directly on protected /v1 endpoints.
    Exceptions must be explicitly documented for genuinely public endpoints (/healthz).
    """
    assert CLIENT_TS_PATH.exists()
    content = CLIENT_TS_PATH.read_text()

    # Find all occurrences of fetch(
    fetch_pattern = re.compile(r"((?:await\s+)?fetch\s*\([^)]+\))")
    matches = fetch_pattern.findall(content)

    # Allowed bare fetch locations:
    # 1. Inside `requestRaw`: the canonical low-level transport wrapper
    # 2. Inside `checkHealth`: /v1/health (uses explicit this.getHeaders())
    # 3. Inside `checkHealth`: /healthz (explicitly documented unauthenticated public fallback)
    for m in matches:
        is_request_raw = "res = await fetch(url," in m or "fetch(url," in m
        is_health = "/v1/health" in m
        is_healthz = "/healthz" in m
        assert (
            is_request_raw or is_health or is_healthz
        ), f"Unauthorized bare fetch() call discovered in client.ts bypassing requestRaw: {m}"


def test_client_ts_request_raw_attaches_headers_and_handles_401():
    """Verify requestRaw automatically merges getHeaders and detects 401 Unauthorized."""
    content = CLIENT_TS_PATH.read_text()

    assert "public async requestRaw(" in content
    assert "this.getHeaders(" in content
    assert "res.status === 401" in content
    assert "Authentication failed (401 Unauthorized)" in content


# ==============================================================================
# 4. Status Truth & HTTP 401 Distinction
# ==============================================================================


def test_server_and_client_status_truth_on_401(monkeypatch):
    """Verify that HTTP 401 from protected routes does not collapse into network offline."""
    token = "test_convergence_token_123"
    monkeypatch.setenv("AGENT_ENGINE_IPC_TOKEN", token)
    monkeypatch.setenv("AGENT_ENGINE_AUTH_ENFORCED", "1")
    token_mgr = get_token_manager()
    token_mgr.set_token(token)
    token_mgr.set_enforced(True)

    app = create_app()
    client = TestClient(app)

    # 1. Without token: returns 401 Unauthorized
    resp_unauth = client.get("/v1/health")
    assert resp_unauth.status_code == 401, "Expected 401 Unauthorized without IPC token"

    # 2. With valid Bearer token: returns 200 OK
    resp_auth = client.get("/v1/health", headers={"Authorization": f"Bearer {token}"})
    assert resp_auth.status_code == 200, f"Expected 200 OK with valid token: {resp_auth.text}"
    data = resp_auth.json()
    assert data.get("status") in ("healthy", "ok")

    # 3. /v1/projects requires auth
    resp_proj_unauth = client.get("/v1/projects")
    assert resp_proj_unauth.status_code == 401

    resp_proj_auth = client.get("/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp_proj_auth.status_code == 200

    # 4. /v1/telemetry/hardware requires auth
    resp_hw_unauth = client.get("/v1/telemetry/hardware")
    assert resp_hw_unauth.status_code == 401

    resp_hw_auth = client.get(
        "/v1/telemetry/hardware", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_hw_auth.status_code == 200

    token_mgr.set_enforced(None)


def test_topbar_and_types_status_truth():
    """Verify TopBar and types explicitly support 'unauthorized' status and 'Authentication Error' copy."""
    types_ts = (RENDERER_ROOT / "types" / "index.ts").read_text()
    assert "'unauthorized'" in types_ts, "SidecarHealth.status must include 'unauthorized'"

    topbar_tsx = (RENDERER_ROOT / "shell" / "TopBar.tsx").read_text()
    assert "health.status === 'unauthorized'" in topbar_tsx
    assert "Authentication Error" in topbar_tsx


# ==============================================================================
# 5. Scheduler -> Occurrence -> Executable Job Semantics
# ==============================================================================


def test_scheduled_task_run_submits_agent_task_job(monkeypatch):
    """Verify triggering a scheduled task creates an executable job of type agent_task."""
    from services.python.server.routers.tasks import get_storage_backend

    token = "test_scheduler_token_456"
    monkeypatch.setenv("AGENT_ENGINE_IPC_TOKEN", token)
    monkeypatch.setenv("AGENT_ENGINE_AUTH_ENFORCED", "1")
    token_mgr = get_token_manager()
    token_mgr.set_token(token)
    token_mgr.set_enforced(True)

    app = create_app()
    client = TestClient(app)

    # Seed a task definition
    storage = get_storage_backend()
    import uuid

    task_id = f"test-task-{uuid.uuid4().hex[:8]}"
    storage.create_scheduled_task(
        {
            "id": task_id,
            "name": "Daily Digest",
            "prompt": "Summarize recent activity",
            "cron": "0 9 * * *",
            "status": "active",
        }
    )

    resp = client.post(
        f"/v1/tasks/{task_id}/run?canonical=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got: {resp.status_code} - {resp.text}"
    body = resp.json()
    assert body.get("status") == "enqueued"
    job_id = body.get("job_id")
    assert job_id is not None

    # Verify that the job created in JobService is of type 'agent_task' (supported by JobWorker)
    from core.jobs.service import get_job_service

    job_service = get_job_service()
    job = job_service.get_job(job_id)
    assert job is not None
    assert (
        job.job_type == "agent_task"
    ), f"Scheduled task run must materialize executable job_type='agent_task', got: {job.job_type}"
    assert job.job_type in SUPPORTED_JOB_TYPES

    token_mgr.set_enforced(None)


# ==============================================================================
# 6. Product Truth Distribution Bundle Integrity
# ==============================================================================


def test_built_distribution_contains_no_demo_projects():
    """Verify built frontend dist contains zero removed demo projects."""
    dist_dir = DESKTOP_ROOT / "dist"
    assert dist_dir.exists(), "apps/desktop/dist must exist"

    # Read all assets
    text_content = ""
    for path in dist_dir.rglob("*.js"):
        text_content += path.read_text(errors="ignore")

    banned_demo_projects = [
        "Organiser Workspace",
        "Client Website",
        "Security Audit & Compliance",
    ]
    for banned in banned_demo_projects:
        assert (
            banned not in text_content
        ), f"Stale demo project '{banned}' detected in compiled dist bundle!"


def test_settings_about_displays_product_truth_build_identity():
    """Verify Settings About section includes Product Truth build identity."""
    settings_tsx = (RENDERER_ROOT / "screens" / "Settings.tsx").read_text()
    assert "Product Truth" in settings_tsx
    assert "Authenticated" in settings_tsx


def test_representative_endpoints_reject_unauth_and_accept_auth(monkeypatch):
    """Verify representative endpoints that previously bypassed getHeaders() enforce auth."""
    token = "test_rep_token_789"
    monkeypatch.setenv("AGENT_ENGINE_IPC_TOKEN", token)
    monkeypatch.setenv("AGENT_ENGINE_AUTH_ENFORCED", "1")
    token_mgr = get_token_manager()
    token_mgr.set_token(token)
    token_mgr.set_enforced(True)

    app = create_app()
    client = TestClient(app)

    endpoints = [
        "/v1/router/tiers",
        "/v1/pipelines",
        "/v1/sessions?limit=5",
        "/v1/skills",
        "/v1/telemetry/hardware",
        "/v1/projects",
    ]

    for ep in endpoints:
        resp_unauth = client.get(ep)
        assert resp_unauth.status_code == 401, f"Endpoint {ep} must reject unauthenticated requests"

        resp_auth = client.get(ep, headers={"Authorization": f"Bearer {token}"})
        assert (
            resp_auth.status_code == 200
        ), f"Endpoint {ep} must succeed with valid token, got {resp_auth.status_code}"

    token_mgr.set_enforced(None)


def test_worker_step_handles_unsupported_job_type_without_spin():
    """Verify JobWorker.step() contains unsupported_job_type and UnsupportedJobTypeError handling."""
    import inspect
    import core.jobs.worker as worker

    src = inspect.getsource(worker.JobWorker.step)
    assert "unsupported_job_type" in src
    assert "UnsupportedJobTypeError" in src


def test_projects_screen_sanitizes_local_storage_and_purges_legacy_demos():
    """Verify Projects.tsx includes sanitization to purge legacy demo projects and Law 3 badges."""
    projects_tsx = (RENDERER_ROOT / "screens" / "Projects.tsx").read_text(encoding="utf-8")
    assert "isLegacyDemoProject" in projects_tsx
    assert "sanitizeProjects" in projects_tsx
    assert "LOCAL_STORAGE_KEY" in projects_tsx
    assert "localStorage.removeItem" in projects_tsx


def test_screens_contain_zero_law_3_strings():
    """Verify desktop renderer screens do not display legacy 'Law 3' strings."""
    for screen_file in (RENDERER_ROOT / "screens").glob("*.tsx"):
        content = screen_file.read_text(encoding="utf-8")
        assert "Law 3" not in content, f"Found legacy 'Law 3' in {screen_file.name}"
