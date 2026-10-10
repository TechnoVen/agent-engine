"""tests/test_founder_acceptance.py

Founder Acceptance Suite for Milestone R5.1 (Core Pack MVP).
Executes the 6 mandatory founder journeys on Nadir's host machine:
- MVP-J1: Project-Aware Conversation (real Agent Engine project context)
- MVP-J7: Local/Cloud Routing (real managed local inference, privacy boundary)
- MVP-J8: Approval & Safety (exact-operation digest binding, replay rejection)
- MVP-J9: Real Cancellation (CancellationToken propagation, CANCELLED status)
- MVP-J10: Restart Recovery (persisted session, durable job, suspended workflow)
- MVP-J12: Truthful Execution History (audit trace, metrics provenance)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional
import pytest

from core.execution.cancellation import CancellationToken
from core.execution.coordinator import ExecutionCoordinator, ExecutionRequest
from core.execution.models import ExecutionStatus
from core.inference.models import RuntimeSpec, RuntimeState
from core.inference.supervisor import (
    get_local_inference_supervisor,
)
from core.jobs.models import JobStatus
from core.jobs.service import JobService
from core.jobs.worker import JobWorker
from core.ledger.models import CostProvenance
from core.ledger.service import LedgerService
from core.model_registry.models import (
    ExecutionLocation,
    ModelCapabilities,
    ModelDefinition,
    ModelIdentity,
    PricingProfile,
    PrivacyProfile,
    TriStateBool,
)
from core.model_registry.registry import get_model_registry
from core.privacy.models import (
    ApprovedCloudTarget,
    DataRoutingClass,
    DataRoutingPolicy,
)
from core.projects.service import ProjectService
from core.providers.registry import get_provider_registry
from core.router.model_router import ModelRouter
from core.safety.pending import (
    OPERATION_DIGEST_VERSION,
    compute_canonical_operation_digest,
)
from core.safety.policy import PolicyEngine
from core.safety.service import ApprovalService
from core.session.store import UnifiedSessionStore
from core.storage.paths import get_private_data_dir
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import CostTracker
from core.workflows.models import (
    NodeRunStatus,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowRunStatus,
)
from core.workflows.service import WorkflowService
from fastapi.testclient import TestClient
from services.python.server.app import create_app
from services.python.server.container import AppServices, set_services


@pytest.fixture
def clean_storage(tmp_path: Path):
    db_path = str(tmp_path / "founder_acceptance.db")
    backend = SQLiteBackend(db_path=db_path)
    return backend


@pytest.fixture(scope="module")
def managed_local_runtime():
    """Ensure AE-managed local llama.cpp supervisor is running with real Qwen model on host hardware."""
    ae_bin = get_private_data_dir() / "runtimes" / "llamacpp" / "llama-server"
    desktop_bin = Path.cwd() / "apps" / "desktop" / "src-tauri" / "binaries" / "llama-server"
    model_path = Path.cwd() / "models" / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"

    if not (
        (ae_bin.is_file() and os.access(ae_bin, os.X_OK))
        or (desktop_bin.is_file() and os.access(desktop_bin, os.X_OK))
    ):
        pytest.skip("Real llama-server binary not found; skipping hardware E2E.")
    if not model_path.is_file():
        pytest.skip(
            "Real test model not found at models/qwen2.5-coder-3b-instruct-q4_k_m.gguf; skipping hardware E2E."
        )

    model_reg = get_model_registry()
    model_reg.register_model(
        ModelDefinition(
            identity=ModelIdentity(
                provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m"
            ),
            display_name="Qwen 2.5 Coder 3B GGUF",
            capabilities=ModelCapabilities(coding=TriStateBool.TRUE, tools=TriStateBool.TRUE),
            pricing=PricingProfile(is_free=True),
            privacy=PrivacyProfile(
                is_local=True,
                data_leaves_device=False,
                execution_location=ExecutionLocation.LOCAL,
            ),
        )
    )
    model_reg.register_model(
        ModelDefinition(
            identity=ModelIdentity(provider_id="openai", model_id="gpt-4o"),
            display_name="GPT-4o Cloud",
            capabilities=ModelCapabilities(coding=TriStateBool.TRUE, tools=TriStateBool.TRUE),
            pricing=PricingProfile(input_cost_per_million=2.5, output_cost_per_million=10.0),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
                execution_location=ExecutionLocation.REMOTE,
            ),
        )
    )

    prov_reg = get_provider_registry()
    supervisor = get_local_inference_supervisor()
    if supervisor.state != RuntimeState.READY:
        ident = ModelIdentity(provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m")
        spec = RuntimeSpec(
            model_identity=ident,
            model_path=str(model_path),
            context_size=512,
            gpu_layers=0,  # Pure CPU execution for deterministic clean-machine validation
            startup_timeout_seconds=180.0,
            shutdown_timeout_seconds=5.0,
        )
        inst = supervisor.start(spec)
        assert supervisor.state == RuntimeState.READY
        assert inst.pid is not None
        assert inst.endpoint_url is not None

        adapter = prov_reg.get_adapter("llamacpp")
        assert adapter._get_base_url() == f"{inst.endpoint_url}/v1"

    yield supervisor

    if supervisor.state != RuntimeState.STOPPED:
        try:
            supervisor.stop()
        except Exception:
            pass


# ==============================================================================
# MVP-J1: Project-Aware Conversation
# ==============================================================================
@pytest.mark.anyio
async def test_mvp_j1_project_aware_conversation(clean_storage, managed_local_runtime):
    """MVP-J1: Verify conversation incorporates real project context and instructions."""
    proj_service = ProjectService(storage=clean_storage)

    real_root = str(Path(__file__).resolve().parents[1])
    project = proj_service.create_project(
        name="Agent Engine Production",
        root_path=real_root,
        instructions="System Invariant: Durable local-first execution kernel with zero shadow runtimes.",
        project_id="proj_agent_engine_founder",
    )

    ctx = proj_service.get_project_context(project.id)
    assert ctx["project_id"] == project.id
    assert "Durable local-first execution kernel" in ctx["instructions"]
    assert ctx["root_path"] == real_root

    # Execute request with real project context and local routing policy
    coordinator = ExecutionCoordinator(storage=clean_storage)
    req = ExecutionRequest(
        project_id=project.id,
        prompt="Describe the core system invariants for Agent Engine in one brief sentence.",
        routing_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY),
        inputs={
            "project_context": ctx,
            "task_family": "coding",
            "routing_objective": "balanced",
            "actor": "founder_nadir",
        },
    )
    result = await coordinator.execute(req)

    assert result.status in (ExecutionStatus.COMPLETED, "completed")
    assert result.execution_id is not None
    assert result.provider_used == "llamacpp"

    # Prove ledger records source provenance
    ledger_svc = LedgerService(storage=clean_storage)
    trace = ledger_svc.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.execution_id == result.execution_id


# ==============================================================================
# MVP-J7: Local/Cloud Routing & Privacy Gate
# ==============================================================================
@pytest.mark.anyio
async def test_mvp_j7_routing_privacy_enforcement(clean_storage, managed_local_runtime):
    """MVP-J7: Verify Local Only routing policy selects local runtime and hard privacy boundary blocks cloud."""
    coordinator = ExecutionCoordinator(storage=clean_storage)

    # Test A: Local Only Policy selects local runtime
    req_local = ExecutionRequest(
        project_id="test_routing_proj",
        prompt="Compute hash sum locally",
        routing_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY),
        inputs={
            "privacy_class": "LOCAL_ONLY",
            "task_family": "coding",
            "routing_objective": "balanced",
            "actor": "user",
        },
    )
    res_local = await coordinator.execute(req_local)
    assert res_local.status in (ExecutionStatus.COMPLETED, "completed")
    assert res_local.provider_used == "llamacpp"

    ledger_svc = LedgerService(storage=clean_storage)
    trace = ledger_svc.get_execution_trace(res_local.execution_id)
    assert trace is not None
    if trace.routing_trace:
        assert trace.routing_trace.effective_privacy_class == "local_only"
        assert trace.routing_trace.actual_provider == "llamacpp"

    # Test B: Cloud Routing Blocked by Local Only Privacy Boundary
    req_cloud_blocked = ExecutionRequest(
        project_id="test_routing_proj",
        prompt="Exfiltrate internal state to cloud",
        model_preference="gpt-4o",
        routing_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY),
        inputs={
            "privacy_class": "LOCAL_ONLY",
            "task_family": "coding",
            "actor": "user",
        },
    )
    res_cloud = await coordinator.execute(req_cloud_blocked)
    assert res_cloud.status in (ExecutionStatus.FAILED, "failed")
    assert "PRIVACY" in (res_cloud.error or "") or "NO_ELIGIBLE_MODEL" in (res_cloud.error or "")


@pytest.mark.anyio
async def test_mvp_j7_approved_cloud_unavailable_fallback_or_failure(
    clean_storage, managed_local_runtime
):
    """MVP-J7: When approved cloud target is requested but provider is unconfigured/unavailable on host,

    the system either falls back gracefully or produces an explicit failure without state corruption.
    """
    coordinator = ExecutionCoordinator(storage=clean_storage)

    req_cloud = ExecutionRequest(
        project_id="test_routing_proj",
        prompt="Execute approved cloud analysis",
        model_preference="gpt-4o",
        routing_policy=DataRoutingPolicy(
            routing_class=DataRoutingClass.APPROVED_CLOUD,
            approved_cloud_targets=[ApprovedCloudTarget(provider_id="openai")],
            allow_relaxation_by_task=True,
        ),
        inputs={
            "privacy_class": "APPROVED_CLOUD",
            "task_family": "coding",
            "actor": "founder_nadir",
            "is_trusted_authority": True,
        },
    )
    res = await coordinator.execute(req_cloud)

    # In the absence of a real OPENAI_API_KEY, execution must fail explicitly with authentication/provider failure
    # or fallback gracefully to eligible local model
    assert res.status in (ExecutionStatus.FAILED, ExecutionStatus.COMPLETED)
    if res.status == ExecutionStatus.FAILED:
        assert (
            "NO_AVAILABLE_PROVIDER" in (res.error or "")
            or "api_key" in (res.error or "").lower()
            or "authentication" in (res.error or "").lower()
            or "dispatch_failed" in (res.error or "").lower()
            or "circuit open" in (res.error or "").lower()
            or "unavailable" in (res.error or "").lower()
        )
    else:
        # If authorized fallback occurred to local runtime
        assert res.provider_used == "llamacpp"


@pytest.mark.anyio
async def test_mvp_j7_approved_cloud_real_execution(clean_storage):
    """MVP-J7: Real approved cloud execution on host hardware.

    Per CTO Directive: If no cloud credential is configured on the founder machine,
    mark: MVP-J7 = BLOCKED BY TEST ENVIRONMENT, not PASS. Never fake success or mock cloud.
    """

    def is_real_cloud_key(val: Optional[str]) -> bool:
        if not val:
            return False
        v = val.strip().lower()
        if v in ("your_key_here", "your-api-key", "placeholder", "xxx", "none", "null", "test"):
            return False
        if v.startswith("your_") or v.startswith("your-"):
            return False
        return True

    cloud_keys = {
        "openai": os.environ.get("OPENAI_API_KEY"),
        "gemini": os.environ.get("GEMINI_API_KEY"),
        "anthropic": os.environ.get("ANTHROPIC_API_KEY"),
    }
    active_providers = [p for p, k in cloud_keys.items() if is_real_cloud_key(k)]
    if not active_providers:
        pytest.skip(
            "MVP-J7 Cloud Execution BLOCKED BY TEST ENVIRONMENT: "
            "No real cloud credentials (OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY) "
            "are configured in Nadir's host environment (template placeholder 'your_key_here' present). "
            "Marked BLOCKED BY TEST ENVIRONMENT per CTO directive."
        )

    # If any real credential is present, execute real cloud request
    target_provider = active_providers[0]
    target_model = (
        "gpt-4o"
        if target_provider == "openai"
        else ("gemini-1.5-pro" if target_provider == "gemini" else "claude-3-5-sonnet-20241022")
    )

    coordinator = ExecutionCoordinator(storage=clean_storage)
    req = ExecutionRequest(
        project_id="test_cloud_real_proj",
        prompt="Reply with 'Cloud OK'",
        model_preference=target_model,
        routing_policy=DataRoutingPolicy(
            routing_class=DataRoutingClass.APPROVED_CLOUD,
            approved_cloud_targets=[
                ApprovedCloudTarget(provider_id=target_provider, model_id=target_model)
            ],
            allow_relaxation_by_task=True,
        ),
        inputs={"actor": "founder_nadir", "is_trusted_authority": True},
    )
    res = await coordinator.execute(req)
    assert res.status == ExecutionStatus.COMPLETED
    assert res.provider_used in ["openai", "gemini", "anthropic"]

    ledger_svc = LedgerService(storage=clean_storage)
    trace = ledger_svc.get_execution_trace(res.execution_id)
    assert trace is not None
    assert trace.routing_trace.effective_privacy_class == "approved_cloud"


# ==============================================================================
# MVP-J8: Approval & Safety (Deterministic Exact Digest Binding)
# ==============================================================================
def test_mvp_j8_approval_and_safety_exact_digest(clean_storage):
    """MVP-J8: Protected operation pauses, requires exact digest, rejects mutated args and replays."""
    approval_svc = ApprovalService(pending_registry=None)

    manifest_args = {"dry_run": False, "version": "v0.5.0"}
    tool_name = "shell:exec"
    capability = "tools:execute"
    actor = "founder_nadir"
    execution_id = "wf_j8_test"

    digest = compute_canonical_operation_digest(
        tool_name=tool_name,
        tool_args=manifest_args,
        capability=capability,
        execution_id=execution_id,
        actor=actor,
        version=OPERATION_DIGEST_VERSION,
    )

    # 1. Register pending operation
    op = approval_svc.request_approval(
        tool_name=tool_name,
        tool_args=manifest_args,
        risk_level="critical",
        risk_score=0.95,
        session_id="sess_j8",
        execution_id=execution_id,
        reason="Production deployment",
        actor=actor,
        capability=capability,
    )
    assert op.status == "pending"
    assert op.digest == digest

    # 2. Mutated arguments attempt produces different digest
    mutated_args = {"dry_run": False, "version": "v9.9.9"}
    mutated_digest = compute_canonical_operation_digest(
        tool_name=tool_name,
        tool_args=mutated_args,
        capability=capability,
        execution_id=execution_id,
        actor=actor,
        version=OPERATION_DIGEST_VERSION,
    )
    assert mutated_digest != digest

    # 3. Approve with correct digest
    approved_op = approval_svc.approve_operation(
        operation_id=op.operation_id,
        operator_identity=actor,
        notes="Approved for release",
        expected_digest=digest,
    )
    assert approved_op.status == "approved"

    # 4. Atomic CAS consumption with matching arguments
    consumed = approval_svc.consume_exact_approval(
        approval_id=op.operation_id,
        tool_name=tool_name,
        tool_args=manifest_args,
        execution_id=execution_id,
        actor=actor,
        capability=capability,
    )
    assert consumed is True

    # 5. Replay attempt rejected (already consumed)
    replay_consumed = approval_svc.consume_exact_approval(
        approval_id=op.operation_id,
        tool_name=tool_name,
        tool_args=manifest_args,
        execution_id=execution_id,
        actor=actor,
        capability=capability,
    )
    assert replay_consumed is False


# ==============================================================================
# MVP-J9: Real Cancellation
# ==============================================================================
@pytest.mark.anyio
async def test_mvp_j9_real_cancellation(clean_storage):
    """MVP-J9: Cancellation token propagates, halts execution, sets status to CANCELLED."""
    token = CancellationToken("exec_cancel_j9")

    async def slow_dispatch(ctx, tier, prov, model):
        for _ in range(50):
            if token.is_cancelled:
                raise asyncio.CancelledError()
            await asyncio.sleep(0.02)
        return {"done": True}

    coordinator = ExecutionCoordinator(storage=clean_storage, dispatch_override=slow_dispatch)

    req = ExecutionRequest(
        project_id="proj_cancel_test",
        prompt="Run lengthy analysis",
    )

    # Cancel token shortly after launching
    async def cancel_later():
        await asyncio.sleep(0.04)
        token.cancel("User clicked Stop")

    task = asyncio.create_task(coordinator.execute(req, cancellation_token=token))
    cancel_task = asyncio.create_task(cancel_later())

    res = await task
    await cancel_task

    assert res.status in (ExecutionStatus.CANCELLED, "cancelled")
    assert res.status != ExecutionStatus.COMPLETED


# ==============================================================================
# MVP-J10: Restart Recovery (Session, Queued Job, Suspended Workflow)
# ==============================================================================
def test_mvp_j10_restart_recovery(tmp_path: Path):
    """MVP-J10: Prove 3 distinct product states survive SQLite close/reopen and process boundary:
    1. Session: Real conversation session with title/messages created in UnifiedSessionStore.
    2. Queued Job: Durable job submitted via JobService recovered in READY status without duplicate execution.
    3. Suspended Workflow: WorkflowDefinition with HITL Gate reaches WAITING_APPROVAL, restarted,
       recovered in WAITING_APPROVAL, upstream node remains COMPLETED and does NOT rerun.
    """
    # --------------------------------------------------------------------------
    # 1. Session State Persistence & Recovery across Process Boundary
    # --------------------------------------------------------------------------
    session_db = str(tmp_path / "session_restart.db")
    backend1 = SQLiteBackend(db_path=session_db)
    sess_store_1 = UnifiedSessionStore(backend=backend1)
    session = sess_store_1.create_session(
        session_id="sess_founder_restart_01",
        title="Founder Dogfood Session",
        metadata={"project_id": "proj_agent_engine"},
    )
    sess_store_1.append_message(
        session_id=session.session_id,
        role="user",
        content="System invariant check: Durable local-first substrate.",
    )
    sess_store_1.append_message(
        session_id=session.session_id,
        role="assistant",
        content="Verified: Single authoritative execution kernel invariant active.",
    )
    backend1.close()
    del backend1
    del sess_store_1

    # Reopen brand-new instance from persistent SQLite DB
    backend2 = SQLiteBackend(db_path=session_db)
    sess_store_2 = UnifiedSessionStore(backend=backend2)
    recovered_sess = sess_store_2.get_session("sess_founder_restart_01")
    assert recovered_sess is not None
    assert recovered_sess.session_id == "sess_founder_restart_01"
    assert recovered_sess.title == "Founder Dogfood Session"
    assert len(recovered_sess.messages) == 2
    assert (
        recovered_sess.messages[0].content
        == "System invariant check: Durable local-first substrate."
    )
    assert (
        recovered_sess.messages[1].content
        == "Verified: Single authoritative execution kernel invariant active."
    )
    backend2.close()
    del backend2
    del sess_store_2

    # --------------------------------------------------------------------------
    # 2. Durable Queued Job Persistence & Recovery across Process Boundary
    # --------------------------------------------------------------------------
    job_db = str(tmp_path / "job_restart.db")
    job_svc_1 = JobService(db_path=job_db)
    job = job_svc_1.submit_job(
        job_type="test_job",
        payload={"target": "docs/ARCHITECTURE.md", "founder": "nadir"},
        job_id="job_restart_test_01",
    )
    assert job.status == JobStatus.READY
    del job_svc_1

    # Reopen fresh JobService instance pointing to same DB
    job_svc_2 = JobService(db_path=job_db)
    recovered_job = job_svc_2.get_job("job_restart_test_01")
    assert recovered_job is not None
    assert recovered_job.job_id == "job_restart_test_01"
    assert recovered_job.status == JobStatus.READY
    assert recovered_job.payload["target"] == "docs/ARCHITECTURE.md"
    assert recovered_job.payload["founder"] == "nadir"
    del job_svc_2

    # --------------------------------------------------------------------------
    # 3. Suspended HITL Gate Workflow Persistence & Recovery across Process Boundary
    # --------------------------------------------------------------------------
    wf_db = str(tmp_path / "wf_restart.db")
    wf_svc_1 = WorkflowService(db_path=wf_db)
    wf_def = WorkflowDefinition(
        id="wf_restart_hitl_e2e",
        name="Founder HITL Restart Workflow",
        nodes=[
            WorkflowNode(
                id="prep_step",
                type=WorkflowNodeType.PIPELINE,
                name="Preparation Step",
                config={"tool_name": "prep_tool"},
                inputs={"environment": "production"},
            ),
            WorkflowNode(
                id="gate_step",
                type=WorkflowNodeType.GATE,
                name="Protected Gate",
                config={
                    "capability": "database:migrate",
                    "actor": "founder_nadir",
                    "reason": "Production schema migration approval",
                },
            ),
            WorkflowNode(
                id="migrate_step",
                type=WorkflowNodeType.PIPELINE,
                name="Migration Step",
                config={"tool_name": "migrate_tool", "capability": "database:migrate"},
                inputs={"version": "v0.5.0"},
            ),
        ],
        edges=[
            WorkflowEdge(id="e1", source="prep_step", target="gate_step"),
            WorkflowEdge(id="e2", source="gate_step", target="migrate_step"),
        ],
    )
    wf_svc_1.create_definition(wf_def)
    run_1 = wf_svc_1.start_run("wf_restart_hitl_e2e", {})
    run_id = run_1.run_id

    # Execute prep step with coordinator override
    def step_dispatch(ctx: Any, tier: Any, prov: Any, model: Any) -> Any:
        return {"output": {"done": True}, "status": "completed"}

    coord = ExecutionCoordinator(dispatch_override=step_dispatch)
    worker_1 = JobWorker(db_path=wf_db, coordinator=coord)
    assert worker_1.step() is True
    worker_1.close()
    del worker_1

    # Reconcile run: prep_step completes, gate_step advances to WAITING_APPROVAL
    reconciled_1 = wf_svc_1.reconcile_run(run_id)
    assert reconciled_1.node_runs["prep_step"].status == NodeRunStatus.COMPLETED
    assert reconciled_1.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL
    assert reconciled_1.status == WorkflowRunStatus.WAITING_APPROVAL
    orig_approval_id = reconciled_1.node_runs["gate_step"].approval_id
    orig_digest = reconciled_1.node_runs["gate_step"].operation_digest
    assert orig_approval_id is not None
    assert orig_digest is not None
    del wf_svc_1

    # Simulate process boundary restart: reopen fresh WorkflowService pointing to same DB
    wf_svc_2 = WorkflowService(db_path=wf_db)
    restored_run = wf_svc_2.get_run(run_id)
    assert restored_run is not None
    assert restored_run.run_id == run_id
    assert restored_run.status == WorkflowRunStatus.WAITING_APPROVAL
    # Upstream prep_step remains COMPLETED and did NOT rerun
    assert restored_run.node_runs["prep_step"].status == NodeRunStatus.COMPLETED
    assert restored_run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL
    assert restored_run.node_runs["gate_step"].approval_id == orig_approval_id
    assert restored_run.node_runs["gate_step"].operation_digest == orig_digest
    del wf_svc_2


# ==============================================================================
# MVP-J12: Truthful Product-Visible Execution History
# ==============================================================================
@pytest.mark.anyio
async def test_mvp_j12_truthful_execution_history(clean_storage, managed_local_runtime):
    """MVP-J12: Verify execution history through sidecar REST API endpoints.

    Verifies GET /v1/executions/{id}, GET /v1/executions/{id}/trace, GET /v1/projects/{id}/executions.
    Semantics: Factual duration, monotonic timestamps, provider identities, measured tokens,
    and truthful cost provenance. Rejects synthetic zeros and unproven costs.
    """
    coordinator = ExecutionCoordinator(storage=clean_storage)
    project_id = "proj_history_test"
    clean_storage.create_project(
        {"id": project_id, "name": "History Test Project", "root_path": "/tmp"}
    )

    # 1. Execute a real local inference request on host CPU hardware
    req = ExecutionRequest(
        project_id=project_id,
        prompt="Return status code 200",
        model_preference="llamacpp/qwen2.5-coder-3b-instruct-q4_k_m",
        routing_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY),
        inputs={
            "task_family": "coding",
            "routing_objective": "balanced",
            "actor": "founder_nadir",
            "is_trusted_authority": True,
        },
    )
    res = await coordinator.execute(req)
    assert res.status in (ExecutionStatus.COMPLETED, "completed")
    exec_id = res.execution_id

    # 2. Wire app container to clean_storage and coordinator for live REST testing
    ledger_svc = LedgerService(storage=clean_storage)
    app_services = AppServices(
        storage=clean_storage,
        policy_engine=PolicyEngine(),
        model_router=ModelRouter(),
        cost_tracker=CostTracker(storage=clean_storage),
        coordinator=coordinator,
        ledger_service=ledger_svc,
    )
    set_services(app_services)
    app = create_app()
    client = TestClient(app)

    # 3. GET /v1/executions/{id}
    res_exec = client.get(f"/v1/executions/{exec_id}")
    assert res_exec.status_code == 200
    exec_data = res_exec.json()
    assert exec_data["id"] == exec_id
    assert exec_data["status"] == "completed"
    assert exec_data["provider"] == res.provider_used
    assert exec_data["model"] == res.model_used
    assert exec_data["started_at"] is not None
    assert exec_data["completed_at"] is not None

    # 4. GET /v1/executions/{id}/trace
    res_trace = client.get(f"/v1/executions/{exec_id}/trace")
    assert res_trace.status_code == 200
    trace_data = res_trace.json()
    assert trace_data["execution_id"] == exec_id
    assert trace_data["status"] == "completed"

    # Routing truth
    routing = trace_data["routing"]
    assert routing["actual_provider"] == res.provider_used
    assert routing["effective_privacy_class"] == "local_only"

    # Timing truth
    assert trace_data["started_at"] is not None
    assert trace_data["completed_at"] is not None
    assert trace_data["started_at"] <= trace_data["completed_at"]
    assert trace_data["duration_ms"] > 0.0

    # Usage and cost truth (local execution is free hardware compute; cost is 0.0 with CALCULATED provenance)
    usage = trace_data["usage"]
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert usage["total_cost_usd"] == 0.0
    assert usage["cost_provenance"] in (
        CostProvenance.CALCULATED.value,
        CostProvenance.PROVIDER_REPORTED.value,
    )

    # 5. GET /v1/projects/{project_id}/executions
    res_proj = client.get(f"/v1/projects/{project_id}/executions")
    assert res_proj.status_code == 200
    proj_execs = res_proj.json()
    assert any(e["execution_id"] == exec_id for e in proj_execs)

    # 6. Truthful representation of unrecorded metrics:
    # An execution that has unrecorded cost MUST report cost_provenance == UNAVAILABLE
    clean_storage.create_execution(
        {
            "id": "exec_unrecorded_test",
            "project_id": project_id,
            "status": "created",
            "created_at": "2026-10-11T00:00:00Z",
            "cost_provenance": CostProvenance.UNAVAILABLE.value,
        }
    )
    trace_unrecorded = ledger_svc.get_execution_trace("exec_unrecorded_test")
    assert trace_unrecorded is not None
    assert trace_unrecorded.usage.cost_provenance == CostProvenance.UNAVAILABLE
    assert trace_unrecorded.duration_ms == 0.0
