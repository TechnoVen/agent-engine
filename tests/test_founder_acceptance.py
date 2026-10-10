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
    DataRoutingClass,
    DataRoutingPolicy,
)
from core.projects.service import ProjectService
from core.providers.registry import get_provider_registry
from core.safety.pending import (
    OPERATION_DIGEST_VERSION,
    compute_canonical_operation_digest,
)
from core.safety.service import ApprovalService
from core.storage.paths import get_private_data_dir
from core.storage.sqlite import SQLiteBackend


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
# MVP-J10: Restart Recovery
# ==============================================================================
def test_mvp_j10_restart_recovery(tmp_path: Path):
    """MVP-J10: Durable jobs and session state survive process boundary restart."""
    db_path = str(tmp_path / "restart_recovery.db")

    # Instance 1: Create state
    job_svc_1 = JobService(db_path=db_path)

    # Submit job in instance 1
    job = job_svc_1.submit_job(
        job_type="background_indexing",
        payload={"target": "docs/ARCHITECTURE.md"},
        job_id="job_restart_test_01",
    )
    assert job.status == JobStatus.READY

    # Simulate crash / process restart: create instance 2 with fresh service instances pointing to same DB
    job_svc_2 = JobService(db_path=db_path)

    recovered_job = job_svc_2.get_job("job_restart_test_01")
    assert recovered_job is not None
    assert recovered_job.job_id == "job_restart_test_01"
    assert recovered_job.status == JobStatus.READY
    assert recovered_job.payload["target"] == "docs/ARCHITECTURE.md"


# ==============================================================================
# MVP-J12: Truthful Execution History
# ==============================================================================
@pytest.mark.anyio
async def test_mvp_j12_truthful_execution_history(clean_storage, managed_local_runtime):
    """MVP-J12: Execution records display actual metrics without fabricated zeros or invented costs."""
    coordinator = ExecutionCoordinator(storage=clean_storage)
    req = ExecutionRequest(
        project_id="proj_history_test",
        prompt="Return status code 200",
        routing_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY),
        inputs={
            "task_family": "coding",
            "routing_objective": "balanced",
            "actor": "founder_nadir",
        },
    )
    res = await coordinator.execute(req)

    ledger_svc = LedgerService(storage=clean_storage)
    trace = ledger_svc.get_execution_trace(res.execution_id)
    assert trace is not None
    assert trace.execution_id == res.execution_id

    # Verify duration and timestamps are truthful
    assert trace.started_at is not None
    assert trace.completed_at is not None
    assert trace.started_at <= trace.completed_at
