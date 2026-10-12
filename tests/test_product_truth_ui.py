"""Test Product Truth & Dogfood UI Gate across Desktop Shell and Core Substrates.

Validates:
1. Zero default demo projects and cross-surface project consistency.
2. Zero synthetic scheduled tasks; real persistence and JobService dispatch.
3. Zero default fake cloud economics rows in Data screen; real telemetry queries.
4. Stale R4 preview banners absent from user-facing headings.
5. Persisted workflows and canonical execution via WorkflowService.
6. Developer execution list reflects real ExecutionLedger, adapters, and providers.
7. Local-first system status: unconfigured cloud does not force global Degraded.
8. Button truth: tasks/workflows execute real backend jobs, no synthetic success.
"""

from pathlib import Path
import uuid
import pytest
from fastapi.testclient import TestClient

from core.storage.sqlite import SQLiteBackend
from services.python.server.dependencies import get_token_manager
from services.python.server.api import app

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERER_ROOT = REPO_ROOT / "apps" / "desktop" / "src" / "renderer"


@pytest.fixture
def api_client(monkeypatch):
    token = "test_truth_ipc_token_xyz"
    monkeypatch.setenv("AGENT_ENGINE_IPC_TOKEN", token)
    mgr = get_token_manager()
    mgr.set_token(token)
    yield TestClient(app, headers={"X-IPC-Token": token})
    mgr.set_token(None)


def test_zero_default_demo_projects_and_consistency(tmp_path: Path):
    """Verify zero hardcoded demo projects exist and cross-surface consistency holds."""
    projects_screen = (RENDERER_ROOT / "screens" / "Projects.tsx").read_text(encoding="utf-8")
    project_detail_screen = (RENDERER_ROOT / "screens" / "ProjectDetail.tsx").read_text(
        encoding="utf-8"
    )
    sidebar_component = (RENDERER_ROOT / "shell" / "Sidebar.tsx").read_text(encoding="utf-8")

    # Banned demo strings in standard mode
    banned_demo_projects = [
        "Organiser Workspace",
        "Client Website",
        "Security Audit & Compliance",
    ]
    for banned in banned_demo_projects:
        assert (
            banned not in projects_screen
        ), f"Found banned demo project '{banned}' in Projects.tsx"
        assert (
            banned not in project_detail_screen
        ), f"Found banned demo project '{banned}' in ProjectDetail.tsx"
        assert (
            banned not in sidebar_component
        ), f"Found banned demo project '{banned}' in Sidebar.tsx"

    # SQLite storage fresh state has zero demo projects (at most canonical Default Project)
    db_path = str(tmp_path / "truth_test.db")
    storage = SQLiteBackend(db_path=db_path)
    projects = storage.list_projects()
    assert len(projects) <= 1
    if projects:
        assert projects[0]["name"] == "Default Project"


def test_zero_synthetic_scheduled_tasks_and_real_dispatch(tmp_path: Path, api_client: TestClient):
    """Verify zero synthetic scheduled tasks are auto-seeded, and trigger invokes JobService."""
    client_ts = (RENDERER_ROOT / "api" / "client.ts").read_text(encoding="utf-8")

    # Verify banned synthetic tasks are not default seeded in frontend
    assert (
        "DEFAULT_SCHEDULED_TASKS: ScheduledTask[] = [];" in client_ts
    ), "DEFAULT_SCHEDULED_TASKS must be empty array"

    # Verify SQLiteBackend scheduled tasks schema
    db_path = str(tmp_path / "tasks_truth.db")
    storage = SQLiteBackend(db_path=db_path)
    tasks = storage.list_scheduled_tasks()
    assert all("id" in t and "cron" in t for t in tasks)

    # Verify task trigger route enqueues a canonical job via JobService
    task_payload = {
        "name": "Truth Test Task",
        "cron": "0 12 * * *",
        "agent_persona": "Executive Drafter",
        "model": "instant",
        "prompt": "Verify truth",
    }
    create_resp = api_client.post("/v1/tasks", json=task_payload)
    assert create_resp.status_code == 200
    task_id = create_resp.json()["id"]

    try:
        # Test /tasks/{id}/run route with canonical dispatch
        resp = api_client.post(f"/v1/tasks/{task_id}/run?canonical=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("enqueued", "triggered", "dispatched")
        assert "job_id" in data
        assert data["job_id"].startswith("job_")
    finally:
        api_client.delete(f"/v1/tasks/{task_id}")


def test_zero_default_fake_cloud_economics_rows_in_data_screen(api_client: TestClient):
    """Verify Data screen does not display synthetic model cost rows by default."""
    data_screen = (RENDERER_ROOT / "screens" / "Data.tsx").read_text(encoding="utf-8")

    # Verify DEFAULT_ROWS is empty
    assert "DEFAULT_ROWS: DataRow[] = [];" in data_screen

    # Verify banned sample dataset names are not unconditionally rendered
    assert "Execution Economics Sample" not in data_screen

    # Verify formula runtime badge does not leak internal R5 milestone
    assert "Formula Runtime: R5" not in data_screen
    assert "Formula Runtime: Planned" in data_screen or "Formula engine unavailable" in data_screen

    # Verify telemetry endpoint returns valid schema
    resp = api_client.get("/v1/telemetry/cost?period=day")
    assert resp.status_code == 200
    telemetry = resp.json()
    assert "total_cost_usd" in telemetry or "current_cost_usd" in telemetry or "series" in telemetry


def test_stale_r4_preview_labels_absent_from_user_facing_headings():
    """Verify user-facing screen headings do not claim runtime is unavailable."""
    tasks_screen = (RENDERER_ROOT / "screens" / "Tasks.tsx").read_text(encoding="utf-8")
    workflows_screen = (RENDERER_ROOT / "screens" / "Workflows.tsx").read_text(encoding="utf-8")
    research_screen = (RENDERER_ROOT / "screens" / "Research.tsx").read_text(encoding="utf-8")
    skills_screen = (RENDERER_ROOT / "screens" / "Skills.tsx").read_text(encoding="utf-8")
    knowledge_screen = (RENDERER_ROOT / "screens" / "Knowledge.tsx").read_text(encoding="utf-8")

    # Tasks header description should reflect current execution capability
    assert (
        "Recurring schedules, cron automation, and background JobService execution queue"
        in tasks_screen
    )
    assert "Coming in R4" not in tasks_screen

    # Workflows header description should reflect current DAG execution capability
    assert (
        "Visual pipeline DAG designer. Author, validate, and execute durable multi-agent workflows"
        in workflows_screen
    )
    assert "Coming in R4" not in workflows_screen
    assert "ADR-012" not in workflows_screen

    # Research screen uses product language, zero internal milestone numbers
    assert "R5.3" not in research_screen
    assert "Research Pack not installed" in research_screen
    assert "Web research is not available yet" in research_screen

    # Skills screen uses Local-First, empty state supported, no ADR-013
    assert "ADR-013" not in skills_screen
    assert "Local-First" in skills_screen
    assert "No skills installed" in skills_screen

    # Knowledge screen has no internal milestone R6
    assert "Planned for R6" not in knowledge_screen
    assert "scheduled for R6" not in knowledge_screen


def test_persisted_workflows_and_canonical_execution(api_client: TestClient):
    """Verify workflows can be persisted and executed via canonical WorkflowService."""
    wf_id = f"wf_truth_{uuid.uuid4().hex[:8]}"
    wf_payload = {
        "id": wf_id,
        "name": "Product Truth Pipeline",
        "description": "Validation pipeline for product truth gate",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "step_init",
                "name": "Initialize State",
                "type": "agent",
                "inputs": {"prompt": "echo: State initialized"},
            }
        ],
        "edges": [],
    }

    # Save workflow
    save_resp = api_client.post("/v1/workflows", json=wf_payload)
    assert save_resp.status_code == 200

    # Retrieve workflow
    get_resp = api_client.get(f"/v1/workflows/{wf_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Product Truth Pipeline"

    # Run workflow with canonical runtime flag
    run_resp = api_client.post(
        f"/v1/workflows/{wf_id}/run?canonical=true",
        json={"input_text": "testing canonical dispatch"},
        headers={"X-Canonical-Runtime": "true"},
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert "run_id" in run_data
    assert run_data["status"] in ("COMPLETED", "RUNNING", "completed", "running")


def test_developer_execution_list_reflects_ledger_and_providers(api_client: TestClient):
    """Verify Developer screen endpoints reflect real execution ledger, adapters, and providers."""
    # 1. Executions ledger endpoint
    exec_resp = api_client.get("/v1/executions")
    assert exec_resp.status_code == 200
    executions = exec_resp.json()
    assert isinstance(executions, list)

    # 2. Registered adapters endpoint
    adapt_resp = api_client.get("/v1/adapters")
    assert adapt_resp.status_code == 200
    adapters = adapt_resp.json()
    assert isinstance(adapters, list)

    # 3. Providers catalog endpoint
    prov_resp = api_client.get("/v1/providers")
    assert prov_resp.status_code == 200
    providers = prov_resp.json()
    assert isinstance(providers, list)
    assert len(providers) >= 1
    provider_ids = [p.get("provider_id") or p.get("provider") or p.get("name") for p in providers]
    assert any(pid for pid in provider_ids)


def test_optional_unconfigured_cloud_does_not_force_global_degraded(api_client: TestClient):
    """Verify local-first status: unconfigured cloud providers leave system status healthy."""
    health_resp = api_client.get("/v1/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] == "healthy"

    # TopBar System Status Popover implementation checks
    topbar_file = RENDERER_ROOT / "shell" / "TopBar.tsx"
    topbar_content = topbar_file.read_text(encoding="utf-8")
    assert "Not configured" in topbar_content
    assert "Execution service" in topbar_content
    assert "Worker" in topbar_content
    assert "Scheduler" in topbar_content
    assert "Database" in topbar_content
    assert "Offline" in topbar_content
    assert "Stopped" in topbar_content
    assert "Sidecar 8000" not in topbar_content


def test_button_truth_and_no_synthetic_success():
    """Verify button actions connect to functional client handlers rather than mock no-ops."""
    writing_file = RENDERER_ROOT / "screens" / "Writing.tsx"
    writing_content = writing_file.read_text(encoding="utf-8")

    # Run Full Pipeline connects to real sidecar client
    assert "sidecarClient.runFullWritingWorkflow" in writing_content
    assert "sidecarClient.createWritingWorkflow" in writing_content

    # Tasks trigger connects to real sidecar client
    tasks_file = RENDERER_ROOT / "screens" / "Tasks.tsx"
    tasks_content = tasks_file.read_text(encoding="utf-8")
    assert "sidecarClient.triggerScheduledTask" in tasks_content


# ==============================================================================
# Execution Projection & Product Truth Regression Tests
# ==============================================================================


def test_provider_failure_produces_failed_execution_status(api_client: TestClient):
    """Verify provider failure produces canonical FAILED status on backend and in SSE error events."""
    # 1. Non-streaming failure
    resp = api_client.post(
        "/v1/chat/completions",
        json={"prompt": "TRIGGER_PROVIDER_FAILURE", "stream": False},
    )
    assert resp.status_code == 502
    assert "failed" in resp.json()["detail"].lower()

    # 2. Streaming failure
    resp_stream = api_client.post(
        "/v1/chat/completions",
        json={"prompt": "TRIGGER_PROVIDER_FAILURE", "stream": True},
    )
    assert resp_stream.status_code == 200
    stream_text = resp_stream.text
    assert '"event": "error"' in stream_text
    assert '"failure_classification": "DISPATCH_FAILED"' in stream_text
    assert '"failure_stage": "provider_dispatch"' in stream_text
    assert '"execution_id"' in stream_text


def test_failed_stream_cannot_render_completed_in_ui():
    """Verify streaming completion callbacks and Message component never infer Completed on failure."""
    client_ts = (RENDERER_ROOT / "api" / "client.ts").read_text(encoding="utf-8")
    home_tsx = (RENDERER_ROOT / "screens" / "Home.tsx").read_text(encoding="utf-8")
    message_tsx = (RENDERER_ROOT / "components" / "Message.tsx").read_text(encoding="utf-8")

    # client.ts must guard onDone so it never fires after onError
    assert "if (!hasError && !hasDone)" in client_ts
    assert "hasError = true;" in client_ts

    # Home.tsx onDone must NEVER overwrite failed status to completed
    assert "m.metadata?.execution?.status === 'failed' || m.metadata?.isError" in home_tsx
    assert "return { ...m, isStreaming: false };" in home_tsx

    # Home.tsx standard UI copy must be restrained, reserving raw exception strings
    assert r"Execution failed\nUnable to complete this request." in home_tsx

    # Message.tsx must not default to COMPLETED when isError is true
    assert "status: message.metadata?.isError ? 'FAILED' : 'COMPLETED'" in message_tsx


def test_failed_execution_does_not_synthesize_local_cloud_provenance_or_zero_cost():
    """Verify ExecutionInspector truthfully projects Failed without synthetic local/cloud or $0.00 cost."""
    inspector_tsx = (RENDERER_ROOT / "components" / "ExecutionInspector.tsx").read_text(
        encoding="utf-8"
    )

    # Must classify failed status and use rose dot
    assert "isFailed ? 'Failed'" in inspector_tsx
    assert "isFailed" in inspector_tsx
    assert "bg-rose-500" in inspector_tsx

    # Cost display must be Unavailable on failure (never synthetic $0.00)
    assert "if (isFailed) {\n    costDisplay = 'Provider charge: Unavailable';" in inspector_tsx

    # Must not contain hardcoded latency fallback 342ms or token fallback 185
    assert "342ms" not in inspector_tsx
    assert ": 185" not in inspector_tsx

    # Expanded inspector must show failure details section
    assert "Execution Failure Details" in inspector_tsx
    assert "provenance.failureClassification" in inspector_tsx
    assert "provenance.failureStage" in inspector_tsx


def test_successful_local_execution_renders_completed_local_model():
    """Verify successful local execution projects Completed · Local model and truthful local compute note."""
    inspector_tsx = (RENDERER_ROOT / "components" / "ExecutionInspector.tsx").read_text(
        encoding="utf-8"
    )

    assert "isLocal ? 'Local model' : 'Cloud model'" in inspector_tsx
    assert "Local compute cost: Unavailable (hardware/electricity unmeasured)" in inspector_tsx
    assert "bg-emerald-400" in inspector_tsx


def test_successful_cloud_execution_renders_truthful_provenance():
    """Verify successful cloud execution projects real provider, model, and cost provenance."""
    inspector_tsx = (RENDERER_ROOT / "components" / "ExecutionInspector.tsx").read_text(
        encoding="utf-8"
    )

    assert "Provider charge: $${cost.toFixed(4)} (Actual)" in inspector_tsx
    assert "Provider charge: $${cost.toFixed(4)} (Estimated)" in inspector_tsx


def test_default_project_truthful_empty_unconfigured_states():
    """Verify project screens project truthful empty/unconfigured states rather than fake defaults."""
    projects_tsx = (RENDERER_ROOT / "screens" / "Projects.tsx").read_text(encoding="utf-8")
    project_detail_tsx = (RENDERER_ROOT / "screens" / "ProjectDetail.tsx").read_text(
        encoding="utf-8"
    )

    # Must not hardcode fake defaults on mapped project
    assert "scopedPolicy: 'Strict Zero-Trust'" not in projects_tsx
    assert "activeAgents: ['Senior Architect']" not in projects_tsx
    assert "budgetCeilingUsd: bp.settings?.budget_ceiling_usd || 50.0" not in projects_tsx

    # Must not hardcode fake defaults in detail screen
    assert "project.budgetCeilingUsd || 15.0" not in project_detail_tsx
    assert "project.monthlySpendUsd || 1.42" not in project_detail_tsx

    # Must render Unscoped / Uncapped when not set
    assert "Unscoped" in projects_tsx
    assert "Uncapped" in projects_tsx


def test_database_isolation_prevents_test_fixtures_in_dogfood_db():
    """Verify automated tests run against isolated temporary database, keeping dogfood db clean."""
    conftest_py = (REPO_ROOT / "conftest.py").read_text(encoding="utf-8")

    # conftest.py must configure SQLITE_DB_PATH isolation
    assert "_TEST_DB_PATH" in conftest_py
    assert 'os.environ["SQLITE_DB_PATH"]' in conftest_py
    assert "reset_storage_backend" in conftest_py
    assert "reset_session_store" in conftest_py

    # Dogfood database must contain zero test fixture sessions
    import sqlite3

    dogfood_db = REPO_ROOT / "data" / "agent_engine.db"
    if dogfood_db.exists():
        conn = sqlite3.connect(str(dogfood_db))
        c = conn.cursor()
        c.execute("SELECT count(*) FROM sessions WHERE title LIKE '%TRIGGER%'")
        assert (
            c.fetchone()[0] == 0
        ), "Dogfood database must not contain TRIGGER_PROVIDER_FAILURE sessions"
        c.execute("SELECT count(*) FROM sessions WHERE title LIKE '%What is 2+2%'")
        assert c.fetchone()[0] == 0, "Dogfood database must not contain test math sessions"
        conn.close()
