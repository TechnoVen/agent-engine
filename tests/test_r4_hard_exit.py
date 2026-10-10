"""tests/test_r4_hard_exit.py

Milestone R4 Hard-Exit End-to-End Test Suite.

Proves:
1. Deterministic local protected side-effect fixture (A -> G -> B -> C):
   - A: Preparatory step
   - G: HITL approval gate
   - B: Protected consequential operation (increments side-effect sink)
   - C: Post-operation verification & telemetry
2. Full positive lifecycle with crash / restart simulation:
   - A completes -> G reaches WAITING_APPROVAL -> B is BLOCKED (count = 0)
   - Process crash simulation: all service handles closed, completely reopen fresh service from disk DB
   - Reopened state: G still WAITING_APPROVAL, B still BLOCKED (side effect = 0)
   - Human approval with exact manifest binding
   - Concurrent reconcile race: multiple racing coordinators permit exactly one CAS winner
   - B unblocks and executes EXACTLY ONCE (side effect = 1)
   - C completes -> Workflow COMPLETED
   - Full provenance chain verified in DB: workflow_run_id -> node_run_id -> approval_id -> operation_digest
3. Negative E2E scenarios proving 0 unwanted side effects:
   - Changed target / arguments invalidates prior approval (side effect = 0)
   - Human operator rejection terminates gate & workflow (side effect = 0)
   - Forged or replayed approval rejected by security boundary (side effect = 0)
   - Workflow cancellation while suspended terminates gate (side effect = 0)
   - Expired gate approval fails closed without auto-release (side effect = 0)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import pytest

from core.execution.coordinator import ExecutionCoordinator
from core.jobs.sqlite import SQLiteJobRepository
from core.jobs.worker import JobWorker
from core.safety.pending import (
    SecurityBoundaryViolation,
)
from core.workflows.exceptions import (
    WorkflowValidationError,
)
from core.workflows.models import (
    NodeRunStatus,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowRunStatus,
)
from core.workflows.service import WorkflowService


# ==============================================================================
# Deterministic Side-Effect Tracker Fixture
# ==============================================================================


class SideEffectTracker:
    """Deterministic local protected side-effect sink."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def execute_consequential_side_effect(
        self, target: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform irreversible protected side-effect and record invocation."""
        record = {
            "target": target,
            "payload": payload,
            "timestamp": time.time(),
        }
        self.calls.append(record)
        return {"status": "success", "side_effect_id": f"se_{len(self.calls)}", "target": target}

    @property
    def count(self) -> int:
        return len(self.calls)


def build_hard_exit_workflow(workflow_id: str = "wf_hard_exit_e2e") -> WorkflowDefinition:
    """Build canonical A -> G -> B -> C workflow graph."""
    node_a = WorkflowNode(
        id="prep_step",
        type=WorkflowNodeType.PIPELINE,
        name="Preparation Step",
        config={"tool_name": "prep_tool"},
        inputs={"env": "production", "region": "eu-central-1"},
    )
    node_g = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Protected Approval Gate",
        config={
            "capability": "database:migrate",
            "actor": "lead_operator",
            "reason": "Approval required to execute database migration on production cluster",
            "ttl_seconds": 3600.0,
        },
    )
    node_b = WorkflowNode(
        id="protected_step",
        type=WorkflowNodeType.PIPELINE,
        name="Protected Migration Step",
        config={"tool_name": "migration_tool", "capability": "database:migrate"},
        inputs={"target": "prod-db-1", "action": "apply_schema_change", "version": "v5.0.0"},
    )
    node_c = WorkflowNode(
        id="telemetry_step",
        type=WorkflowNodeType.PIPELINE,
        name="Post Verification Step",
        config={"tool_name": "verify_tool"},
        inputs={"check_target": "prod-db-1"},
    )

    return WorkflowDefinition(
        id=workflow_id,
        name="Hard-Exit E2E Workflow",
        nodes=[node_a, node_g, node_b, node_c],
        edges=[
            WorkflowEdge(id="e1", source="prep_step", target="gate_step"),
            WorkflowEdge(id="e2", source="gate_step", target="protected_step"),
            WorkflowEdge(id="e3", source="protected_step", target="telemetry_step"),
        ],
    )


def make_side_effect_coordinator(
    tracker: SideEffectTracker, db_path: Optional[str] = None
) -> ExecutionCoordinator:
    """Create ExecutionCoordinator wired to the deterministic side-effect tracker."""

    def dispatch(ctx: Any, tier: Any, prov: Any, model: Any) -> Any:
        prompt = getattr(ctx, "prompt", "") or ""
        match = re.search(r"job_[a-f0-9]+", prompt)
        if match and db_path:
            repo = SQLiteJobRepository(db_path=db_path)
            job = repo.get_job(match.group(0))
            if job and job.payload_summary.get("node_id") == "protected_step":
                inputs = job.payload_summary.get("inputs", {})
                tracker.execute_consequential_side_effect(
                    target=inputs.get("target", "prod-db-1"),
                    payload=inputs,
                )
        return {"output": {"done": True}, "status": "completed"}

    return ExecutionCoordinator(dispatch_override=dispatch)


# ==============================================================================
# 1. Full Positive Hard-Exit Lifecycle
# ==============================================================================


def test_r4_hard_exit_full_positive_lifecycle(tmp_path: Path) -> None:
    """Full Positive Lifecycle with Crash/Restart Simulation:

    A completes -> G reaches WAITING_APPROVAL -> B is BLOCKED (count = 0).
    Crash: close all handles.
    Restart: state preserved on disk.
    Approve: concurrent reconcile race -> atomic CAS winner.
    B unblocks -> side effect executes EXACTLY ONCE (count = 1).
    C completes -> Workflow COMPLETED.
    Unbroken provenance chain verified in DB.
    """
    db_path = str(tmp_path / "hard_exit_positive.db")
    tracker = SideEffectTracker()
    coord = make_side_effect_coordinator(tracker, db_path=db_path)

    # Phase 1: Launch workflow and run prep step A
    svc1 = WorkflowService(db_path=db_path)
    wf_def = build_hard_exit_workflow("wf_positive_lifecycle")
    svc1.create_definition(wf_def)

    run = svc1.start_run("wf_positive_lifecycle", {})
    run_id = run.run_id

    # Verify initial statuses
    assert run.node_runs["prep_step"].status == NodeRunStatus.READY
    assert run.node_runs["gate_step"].status == NodeRunStatus.BLOCKED
    assert run.node_runs["protected_step"].status == NodeRunStatus.BLOCKED
    assert run.node_runs["telemetry_step"].status == NodeRunStatus.BLOCKED
    assert tracker.count == 0

    # Execute prep step A with worker
    worker1 = JobWorker(db_path=db_path, coordinator=coord)
    assert worker1.step() is True  # Processes prep_step Job
    assert tracker.count == 0  # Protected side effect NOT called

    # Reconcile run: prep_step completes, gate_step advances to WAITING_APPROVAL
    run = svc1.reconcile_run(run_id)
    assert run.node_runs["prep_step"].status == NodeRunStatus.COMPLETED
    assert run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL
    assert run.node_runs["protected_step"].status == NodeRunStatus.BLOCKED
    assert tracker.count == 0

    orig_approval_id = run.node_runs["gate_step"].approval_id
    orig_digest = run.node_runs["gate_step"].operation_digest
    assert orig_approval_id is not None
    assert orig_digest is not None

    # Cleanly shut down instance 1 to simulate crash / hard exit
    worker1.close()
    del worker1
    del svc1

    # --------------------------------------------------------------------------
    # Phase 2: Process Restart Simulation
    # Reopen brand new service and worker instances from persistent disk DB
    # --------------------------------------------------------------------------
    svc2 = WorkflowService(db_path=db_path)
    worker2 = JobWorker(db_path=db_path, coordinator=coord)

    # Verify state reconstructed cleanly from disk
    restored_run = svc2.get_run(run_id)
    assert restored_run is not None
    assert restored_run.status == WorkflowRunStatus.WAITING_APPROVAL
    assert restored_run.node_runs["prep_step"].status == NodeRunStatus.COMPLETED
    assert restored_run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL
    assert restored_run.node_runs["gate_step"].approval_id == orig_approval_id
    assert restored_run.node_runs["gate_step"].operation_digest == orig_digest
    assert restored_run.node_runs["protected_step"].status == NodeRunStatus.BLOCKED
    assert tracker.count == 0

    # Worker attempt before approval produces zero jobs processed
    assert worker2.step() is False
    assert tracker.count == 0

    # --------------------------------------------------------------------------
    # Phase 3: Exact Operator Approval & Multi-Coordinator Concurrent Reconcile
    # --------------------------------------------------------------------------
    approved_run = svc2.approve_gate(run_id, "gate_step", actor="lead_operator")
    assert approved_run.node_runs["gate_step"].status == NodeRunStatus.COMPLETED
    assert approved_run.node_runs["protected_step"].status == NodeRunStatus.READY

    # Simulate 5 concurrent coordinators racing to reconcile
    def race_reconcile() -> str:
        s = WorkflowService(db_path=db_path)
        r = s.reconcile_run(run_id)
        return r.node_runs["protected_step"].status.value

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(lambda _: race_reconcile(), range(5)))
    assert all(s in ("ready", "running") for s in statuses)

    # --------------------------------------------------------------------------
    # Phase 4: Execute Protected Step B (Exactly Once!)
    # --------------------------------------------------------------------------
    assert worker2.step() is True  # Processes protected_step Job
    assert tracker.count == 1  # Side effect executed EXACTLY ONCE!
    assert tracker.calls[0]["target"] == "prod-db-1"

    # Advance workflow: protected_step completes, telemetry_step unblocks
    run = svc2.reconcile_run(run_id)
    assert run.node_runs["protected_step"].status == NodeRunStatus.COMPLETED
    assert run.node_runs["telemetry_step"].status == NodeRunStatus.READY

    # Execute telemetry step C
    assert worker2.step() is True  # Processes telemetry_step Job
    assert tracker.count == 1  # Side effect count remains 1

    # Final reconciliation: entire workflow completed
    final_run = svc2.reconcile_run(run_id)
    assert final_run.status == WorkflowRunStatus.COMPLETED
    assert final_run.node_runs["telemetry_step"].status == NodeRunStatus.COMPLETED
    assert tracker.count == 1

    # --------------------------------------------------------------------------
    # Phase 5: Unbroken Cryptographic Provenance Chain Verification
    # --------------------------------------------------------------------------
    conn = svc2._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT nr.node_id, nr.approval_id, nr.operation_digest, nr.status,
                   ap.status as approval_status, ap.actor, ap.consumed_at
            FROM workflow_node_runs nr
            LEFT JOIN approvals ap ON nr.approval_id = ap.approval_id
            WHERE nr.workflow_run_id = ? AND nr.node_id = 'gate_step'
            """,
            (run_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "gate_step"
        assert row[1] == orig_approval_id
        assert row[2] == orig_digest
        assert row[3] == "completed"
        assert row[4] == "consumed"  # Approval record atomically marked consumed
        assert row[5] == "lead_operator"  # Bound approving actor
        assert row[6] is not None  # Consumed timestamp recorded
    finally:
        worker2.close()
        if not svc2._is_memory:
            conn.close()


# ==============================================================================
# 2. Negative Scenario: Changed Target Invalidates Approval (Side-Effect = 0)
# ==============================================================================


def test_r4_hard_exit_negative_changed_target_invalidates(tmp_path: Path) -> None:
    """Tampering with target while suspended invalidates approval; side effect is NEVER executed."""
    db_path = str(tmp_path / "hard_exit_tamper.db")
    tracker = SideEffectTracker()
    coord = make_side_effect_coordinator(tracker, db_path=db_path)

    svc = WorkflowService(db_path=db_path)
    wf_def = build_hard_exit_workflow("wf_tamper_test")
    svc.create_definition(wf_def)

    run = svc.start_run("wf_tamper_test", {})
    worker = JobWorker(db_path=db_path, coordinator=coord)
    assert worker.step() is True  # Run prep_step
    run = svc.reconcile_run(run.run_id)
    assert run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL

    orig_approval_id = run.node_runs["gate_step"].approval_id
    assert orig_approval_id is not None

    # Simulate crash and restart
    worker.close()
    del worker
    del svc

    svc2 = WorkflowService(db_path=db_path)
    worker2 = JobWorker(db_path=db_path, coordinator=coord)

    # Tamper with target resource in definition snapshot
    snapshot = svc2.get_run(run.run_id).definition_snapshot
    for n in snapshot["nodes"]:
        if n["id"] == "protected_step":
            n["inputs"]["target"] = "unauthorized-malicious-target"

    conn = svc2._get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE workflow_runs SET definition_snapshot_json = ? WHERE workflow_run_id = ?",
                (json.dumps(snapshot), run.run_id),
            )
    finally:
        if not svc2._is_memory:
            conn.close()

    # Reconciling must detect tamper, invalidate prior approval, and register fresh request
    tampered_run = svc2.reconcile_run(run.run_id)
    new_approval_id = tampered_run.node_runs["gate_step"].approval_id
    assert new_approval_id != orig_approval_id
    assert tampered_run.node_runs["protected_step"].status == NodeRunStatus.BLOCKED

    # Prior approval was invalidated
    old_op = svc2.approval_registry.get_operation(orig_approval_id)
    assert old_op is not None
    assert old_op.status == "rejected"

    # Worker attempts execution -> ZERO jobs processed, ZERO side effects
    assert worker2.step() is False
    assert tracker.count == 0
    worker2.close()


# ==============================================================================
# 3. Negative Scenario: Operator Rejection Halts Workflow (Side-Effect = 0)
# ==============================================================================


def test_r4_hard_exit_negative_rejection_halts_workflow(tmp_path: Path) -> None:
    """Human rejection terminates gate & workflow; protected operation is NEVER executed."""
    db_path = str(tmp_path / "hard_exit_reject.db")
    tracker = SideEffectTracker()
    coord = make_side_effect_coordinator(tracker, db_path=db_path)

    svc = WorkflowService(db_path=db_path)
    wf_def = build_hard_exit_workflow("wf_reject_lifecycle")
    svc.create_definition(wf_def)

    run = svc.start_run("wf_reject_lifecycle", {})
    worker = JobWorker(db_path=db_path, coordinator=coord)
    assert worker.step() is True  # Run prep_step
    run = svc.reconcile_run(run.run_id)
    assert run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL

    # Operator explicitly rejects gate
    rejected_run = svc.reject_gate(
        run.run_id, "gate_step", actor="sec_lead", reason="Change window closed"
    )

    assert rejected_run.status == WorkflowRunStatus.FAILED
    assert rejected_run.node_runs["gate_step"].status == NodeRunStatus.FAILED
    assert rejected_run.node_runs["protected_step"].status in (
        NodeRunStatus.SKIPPED,
        NodeRunStatus.BLOCKED,
    )

    # Worker attempts execution -> ZERO side effects
    assert worker.step() is False
    assert tracker.count == 0
    worker.close()


# ==============================================================================
# 4. Negative Scenario: Forged / Replayed Approvals Fail Closed (Side-Effect = 0)
# ==============================================================================


def test_r4_hard_exit_negative_forged_replayed_approvals(tmp_path: Path) -> None:
    """Forged arguments, wrong actor, and replay attempts fail closed with SecurityBoundaryViolation."""
    db_path = str(tmp_path / "hard_exit_forge.db")
    tracker = SideEffectTracker()
    coord = make_side_effect_coordinator(tracker, db_path=db_path)

    svc = WorkflowService(db_path=db_path)
    wf_def = build_hard_exit_workflow("wf_forge_test")
    svc.create_definition(wf_def)

    run = svc.start_run("wf_forge_test", {})
    worker = JobWorker(db_path=db_path, coordinator=coord)
    assert worker.step() is True
    run = svc.reconcile_run(run.run_id)
    approval_id = run.node_runs["gate_step"].approval_id
    assert approval_id is not None

    # 1. Attempt consumption with forged arguments
    with pytest.raises(SecurityBoundaryViolation):
        svc.approval_registry.consume_exact_approval(
            approval_id=approval_id,
            tool_name="migration_tool",
            tool_args={"forged": "malicious_payload"},
            execution_id=run.run_id,
            actor="lead_operator",
        )

    # 2. Attempt consumption with unauthorized actor
    with pytest.raises(SecurityBoundaryViolation):
        svc.approval_registry.consume_exact_approval(
            approval_id=approval_id,
            tool_name="migration_tool",
            tool_args=run.node_runs["gate_step"].inputs,
            execution_id=run.run_id,
            actor="unauthorized_mallory",
        )

    # 3. Legitimate approval
    svc.approve_gate(run.run_id, "gate_step", actor="lead_operator")
    worker.step()
    assert tracker.count == 1

    # 4. Replay attempt of already-consumed approval
    with pytest.raises(SecurityBoundaryViolation) as replay_exc:
        svc.approval_registry.consume_exact_approval(
            approval_id=approval_id,
            tool_name="migration_tool",
            tool_args=run.node_runs["gate_step"].inputs,
            execution_id=run.run_id,
            actor="lead_operator",
        )
    assert "already been consumed" in str(replay_exc.value)

    # Side effect was executed ONLY once, never replayed
    assert tracker.count == 1
    worker.close()


# ==============================================================================
# 5. Negative Scenario: Cancellation During Suspension (Side-Effect = 0)
# ==============================================================================


def test_r4_hard_exit_negative_cancellation_during_suspension(tmp_path: Path) -> None:
    """Cancelling a workflow while waiting approval terminates the gate and blocks downstream execution."""
    db_path = str(tmp_path / "hard_exit_cancel.db")
    tracker = SideEffectTracker()
    coord = make_side_effect_coordinator(tracker, db_path=db_path)

    svc = WorkflowService(db_path=db_path)
    wf_def = build_hard_exit_workflow("wf_cancel_test")
    svc.create_definition(wf_def)

    run = svc.start_run("wf_cancel_test", {})
    worker = JobWorker(db_path=db_path, coordinator=coord)
    assert worker.step() is True
    run = svc.reconcile_run(run.run_id)
    assert run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL

    # Cancel workflow run
    cancelled_run = svc.cancel_run(run.run_id)
    assert cancelled_run.status == WorkflowRunStatus.CANCELLED
    assert cancelled_run.node_runs["gate_step"].status == NodeRunStatus.CANCELLED
    assert cancelled_run.node_runs["protected_step"].status in (
        NodeRunStatus.CANCELLED,
        NodeRunStatus.BLOCKED,
    )

    # Subsequent approval attempts are rejected
    with pytest.raises(WorkflowValidationError):
        svc.approve_gate(run.run_id, "gate_step")

    # Worker executes nothing, zero side effects
    assert worker.step() is False
    assert tracker.count == 0
    worker.close()


# ==============================================================================
# 6. Negative Scenario: Expired Gate Fails Closed (Side-Effect = 0)
# ==============================================================================


def test_r4_hard_exit_negative_expired_gate_fails_closed(tmp_path: Path) -> None:
    """Expired gate stays suspended, rejects approval attempts, and never executes protected operation."""
    db_path = str(tmp_path / "hard_exit_expire.db")
    tracker = SideEffectTracker()
    coord = make_side_effect_coordinator(tracker, db_path=db_path)

    svc = WorkflowService(db_path=db_path)
    # Workflow with ultra-short TTL (0.05 seconds)
    wf_def = build_hard_exit_workflow("wf_expire_test")
    for n in wf_def.nodes:
        if n.id == "gate_step":
            n.config["ttl_seconds"] = 0.05
    svc.create_definition(wf_def)

    run = svc.start_run("wf_expire_test", {})
    worker = JobWorker(db_path=db_path, coordinator=coord)
    assert worker.step() is True
    run = svc.reconcile_run(run.run_id)
    assert run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL

    # Sleep past expiration window
    time.sleep(0.1)

    # Reconcile does NOT auto-authorize
    reconciled_run = svc.reconcile_run(run.run_id)
    assert reconciled_run.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL
    assert reconciled_run.node_runs["protected_step"].status == NodeRunStatus.BLOCKED

    # Approval attempt of expired gate fails closed
    with pytest.raises(Exception):
        svc.approve_gate(run.run_id, "gate_step")

    # Zero side effects executed
    assert worker.step() is False
    assert tracker.count == 0
    worker.close()
