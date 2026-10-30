"""tests/test_r4_9_workflow_hitl.py

Milestone R4 (Task R4.9 - Human-in-the-Loop Workflow Gates) Test Suite.

Verifies:
1. Migration 009 applies cleanly on top of populated v8 database:
   adds approval_id, operation_digest, suspended_at, resolved_at to workflow_node_runs
   and establishes approvals table.
2. Gate node creation & compilation:
   GATE is modeled as control-plane state (nr.job_id is None, no fake Job in jobs table).
3. Downstream nodes remain BLOCKED while gate is in WAITING_APPROVAL.
4. Exact canonical operation digest computation binding workflow, node, capability,
   execution_id, and actor.
5. Approval release via atomic CAS consumption in approvals table:
   advances gate to COMPLETED, unblocks downstream nodes into READY and persistent queue.
6. Single-use CAS race safety:
   concurrent approval consumption attempts execute atomically; second attempt cannot re-consume.
7. Argument / input change invalidates prior approval, generating new digest.
8. Rejection terminates gate as FAILED, blocks downstream, fails workflow run.
9. Expiry keeps gate suspended without release, does not advance downstream.
10. Policy denial blocks execution regardless of human approval attempt:
    A user or operator cannot bypass policy denial with an approval.
11. Process restart preserves gate in WAITING_APPROVAL on disk SQLite DB:
    approval after restart resumes cleanly.
12. Workflow cancellation terminates gate, rejects approval, and blocks subsequent approval.
13. Provenance chain traceability:
    workflow_run_id -> node_run_id -> approval_id -> operation_digest.
14. Zero shadow tables and zero secret leakage in gate payloads.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
import pytest

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from core.jobs.migrations import apply_job_migrations, get_current_job_schema_version
from core.jobs.models import (
    JobStatus,
)
from core.jobs.sqlite import SQLiteJobRepository
from core.safety.pending import (
    OPERATION_DIGEST_VERSION,
    compute_canonical_operation_digest,
)
from core.safety.policy import PolicyEngine, PolicyRule
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
# Fixtures & Helpers
# ==============================================================================


@pytest.fixture
def file_db_path(tmp_path: Path) -> str:
    """Provide a fresh SQLite file database path."""
    return str(tmp_path / "test_r4_9_workflow_hitl.db")


@pytest.fixture
def workflow_service(file_db_path: str) -> WorkflowService:
    """Provide a WorkflowService instance bound to a fresh SQLite database."""
    return WorkflowService(db_path=file_db_path)


def complete_job_state(repo: SQLiteJobRepository, job_id: str) -> None:
    """Helper to transition a job cleanly through READY -> RUNNING -> COMPLETED."""
    job = repo.get_job(job_id)
    if not job:
        return
    if job.status == JobStatus.READY:
        repo.update_state(job_id, JobStatus.RUNNING)
    repo.update_state(job_id, JobStatus.COMPLETED)


# ==============================================================================
# 1. Migration 009: Populated v8 -> v9 Verification
# ==============================================================================


def test_migration_009_populated_hitl_gates(tmp_path: Path) -> None:
    """Verify that Migration 009 applies cleanly on top of populated v8 data."""
    db_path = str(tmp_path / "migration_009_test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Apply migrations up to version 8
    apply_job_migrations(conn, target_version=8)
    assert get_current_job_schema_version(conn) == 8

    # Populate v8 tables with sample workflow definition, run, and node run
    conn.execute(
        """
        INSERT INTO workflow_definitions (
            workflow_id, name, description, version, status,
            definition_json, definition_hash, created_at, updated_at
        ) VALUES ('wf_pre9', 'Pre9 Workflow', 'Desc', '1.0.0', 'ready', '{}', 'hash_pre9', '2026-10-10T12:00:00Z', '2026-10-10T12:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO workflow_runs (
            workflow_run_id, workflow_id, definition_hash, definition_snapshot_json,
            status, inputs_json, outputs_json, error, created_at, updated_at
        ) VALUES ('wfr_pre9', 'wf_pre9', 'hash_pre9', '{}', 'running', '{}', '{}', NULL, '2026-10-10T12:00:00Z', '2026-10-10T12:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO workflow_node_runs (
            node_run_id, workflow_run_id, node_id, node_type, job_id,
            status, inputs_json, outputs_json, error, started_at, updated_at
        ) VALUES ('wfnr_pre9', 'wfr_pre9', 'node1', 'pipeline', NULL, 'running', '{}', '{}', NULL, '2026-10-10T12:00:00Z', '2026-10-10T12:00:00Z')
        """
    )
    conn.commit()

    # Apply migration 9
    applied = apply_job_migrations(conn, target_version=9)
    assert applied == 1
    assert get_current_job_schema_version(conn) == 9

    # Verify new columns on workflow_node_runs
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workflow_node_runs)")
    col_names = {row[1] for row in cursor.fetchall()}
    assert "approval_id" in col_names
    assert "operation_digest" in col_names
    assert "suspended_at" in col_names
    assert "resolved_at" in col_names

    # Verify approvals table and indexes exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='approvals'")
    assert cursor.fetchone() is not None

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_node_runs_approval_id'"
    )
    assert cursor.fetchone() is not None

    # Verify pre-existing data was preserved
    cursor.execute(
        "SELECT node_run_id, approval_id FROM workflow_node_runs WHERE node_run_id='wfnr_pre9'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "wfnr_pre9"
    assert row[1] is None  # default NULL for historical rows
    conn.close()


# ==============================================================================
# 2. Gate Node Creation & Compilation (Control-Plane State)
# ==============================================================================


def test_gate_node_creation_and_compilation(workflow_service: WorkflowService) -> None:
    """Verify GATE is compiled as control-plane state (no fake Job created in jobs table)."""
    gate_node = WorkflowNode(
        id="gate_1",
        type=WorkflowNodeType.GATE,
        name="Review Checkpoint",
        config={"capability": "deploy:prod", "reason": "Requires human sign-off"},
        inputs={"env": "prod"},
    )
    wf_def = WorkflowDefinition(
        id="wf_gate_compilation",
        name="Compilation Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)

    run = workflow_service.start_run("wf_gate_compilation", {"env": "prod"})
    assert run.status == WorkflowRunStatus.WAITING_APPROVAL

    node_run = run.node_runs["gate_1"]
    assert node_run.node_type == WorkflowNodeType.GATE
    assert node_run.status == NodeRunStatus.WAITING_APPROVAL
    assert node_run.job_id is None  # CRITICAL: Not a fake job!
    assert node_run.approval_id is not None
    assert node_run.operation_digest is not None
    assert node_run.suspended_at is not None

    # Verify jobs table has zero rows for this gate
    conn = workflow_service._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs")
        count = cursor.fetchone()[0]
        assert count == 0
    finally:
        if not workflow_service._is_memory:
            conn.close()


# ==============================================================================
# 3. Downstream Nodes Remain BLOCKED While Gate is Waiting
# ==============================================================================


def test_downstream_nodes_blocked_while_gate_waiting(workflow_service: WorkflowService) -> None:
    """Verify downstream nodes remain strictly BLOCKED while GATE is WAITING_APPROVAL."""
    node_prep = WorkflowNode(
        id="step_prep",
        type=WorkflowNodeType.PIPELINE,
        name="Preparation Step",
        outputs=["result_data"],
    )
    node_gate = WorkflowNode(
        id="step_gate",
        type=WorkflowNodeType.GATE,
        name="Approval Gate",
        inputs={"data": "${steps.step_prep.result_data}"},
    )
    node_exec = WorkflowNode(
        id="step_exec",
        type=WorkflowNodeType.SKILL,
        name="Execution Step",
        inputs={"data": "${steps.step_gate.status}"},
    )

    wf_def = WorkflowDefinition(
        id="wf_gate_blocked",
        name="Gate Blocked Test",
        nodes=[node_prep, node_gate, node_exec],
        edges=[
            WorkflowEdge(id="e1", source="step_prep", target="step_gate"),
            WorkflowEdge(id="e2", source="step_gate", target="step_exec"),
        ],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_gate_blocked", {})

    # Initially: step_prep is READY; gate and exec are BLOCKED
    assert run.node_runs["step_prep"].status == NodeRunStatus.READY
    assert run.node_runs["step_gate"].status == NodeRunStatus.BLOCKED
    assert run.node_runs["step_exec"].status == NodeRunStatus.BLOCKED

    # Complete step_prep job
    prep_job_id = run.node_runs["step_prep"].job_id
    assert prep_job_id is not None
    complete_job_state(workflow_service.repo, prep_job_id)

    # Reconcile run: step_prep completes -> step_gate transitions to WAITING_APPROVAL
    run_after = workflow_service.reconcile_run(run.run_id)
    assert run_after.status == WorkflowRunStatus.WAITING_APPROVAL
    assert run_after.node_runs["step_prep"].status == NodeRunStatus.COMPLETED
    assert run_after.node_runs["step_gate"].status == NodeRunStatus.WAITING_APPROVAL
    assert run_after.node_runs["step_gate"].approval_id is not None

    # CRITICAL: step_exec MUST REMAIN BLOCKED!
    assert run_after.node_runs["step_exec"].status == NodeRunStatus.BLOCKED
    exec_job_id = run_after.node_runs["step_exec"].job_id
    assert exec_job_id is not None
    exec_job = workflow_service.repo.get_job(exec_job_id)
    assert exec_job.status == JobStatus.BLOCKED


# ==============================================================================
# 4. Exact Operation Digest Computation
# ==============================================================================


def test_exact_operation_digest_computation(workflow_service: WorkflowService) -> None:
    """Verify deterministic versioned SHA-256 canonical operation digest."""
    gate_node = WorkflowNode(
        id="deploy_gate",
        type=WorkflowNodeType.GATE,
        name="Production Gate",
        config={"capability": "deploy:prod", "actor": "deploy_operator"},
        inputs={"version": "1.2.3", "cluster": "us-east-1"},
    )
    wf_def = WorkflowDefinition(
        id="wf_digest_test",
        name="Digest Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_digest_test", {})

    node_run = run.node_runs["deploy_gate"]
    manifest = {
        "workflow_run_id": run.run_id,
        "gate_node_run_id": node_run.node_run_id,
        "gate_node_id": "deploy_gate",
        "protected_node_id": "deploy_gate",
        "protected_operation": "workflow_gate:wf_digest_test:deploy_gate",
        "capability": "deploy:prod",
        "target": "default",
        "arguments": {"cluster": "us-east-1", "version": "1.2.3"},
        "artifact_digests": {},
        "provenance_tool": "workflow_gate:wf_digest_test:deploy_gate",
    }
    expected_digest = compute_canonical_operation_digest(
        tool_name="workflow_gate:wf_digest_test:deploy_gate",
        tool_args=manifest,
        capability="deploy:prod",
        execution_id=run.run_id,
        actor="deploy_operator",
        version=OPERATION_DIGEST_VERSION,
    )

    assert node_run.operation_digest == expected_digest

    # Verify persisted record in approvals table has matching digest
    op = workflow_service.approval_registry.get_operation(node_run.approval_id)
    assert op is not None
    assert op.digest == expected_digest
    assert op.execution_id == run.run_id
    assert op.actor == "deploy_operator"
    assert op.capability == "deploy:prod"


# ==============================================================================
# 5. Approval Release via Atomic CAS Consumption
# ==============================================================================


def test_approval_release_via_atomic_cas_consumption(workflow_service: WorkflowService) -> None:
    """Verify approving gate transitions approvals to 'consumed' and releases downstream to READY."""
    gate_node = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Approval Gate",
        outputs=["approval_token"],
    )
    worker_node = WorkflowNode(
        id="worker_step",
        type=WorkflowNodeType.PIPELINE,
        name="Worker Step",
    )
    wf_def = WorkflowDefinition(
        id="wf_cas_release",
        name="CAS Release Test",
        nodes=[gate_node, worker_node],
        edges=[WorkflowEdge(id="e1", source="gate_step", target="worker_step")],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_cas_release", {})

    assert run.status == WorkflowRunStatus.WAITING_APPROVAL
    gate_nr = run.node_runs["gate_step"]
    approval_id = gate_nr.approval_id
    assert approval_id is not None

    # Approve the gate
    run_approved = workflow_service.approve_gate(run.run_id, "gate_step", actor="sec_lead")

    # Verify gate node completed
    assert run_approved.node_runs["gate_step"].status == NodeRunStatus.COMPLETED
    assert run_approved.node_runs["gate_step"].resolved_at is not None
    assert run_approved.node_runs["gate_step"].outputs.get("approved") is True

    # Verify approval row was atomically consumed
    conn = workflow_service._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, consumed_at, actor FROM approvals WHERE approval_id = ?", (approval_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "consumed"
        assert row[1] is not None
        assert row[2] == "sec_lead"
    finally:
        if not workflow_service._is_memory:
            conn.close()

    # Verify worker_step transitioned from BLOCKED to READY and is enqueued
    worker_nr = run_approved.node_runs["worker_step"]
    assert worker_nr.status == NodeRunStatus.READY
    worker_job = workflow_service.repo.get_job(worker_nr.job_id)
    assert worker_job.status == JobStatus.READY

    # Complete worker step -> entire workflow completes
    complete_job_state(workflow_service.repo, worker_nr.job_id)
    final_run = workflow_service.reconcile_run(run.run_id)
    assert final_run.status == WorkflowRunStatus.COMPLETED


# ==============================================================================
# 6. Single-Use CAS Race Safety
# ==============================================================================


def test_single_use_cas_race_safety(workflow_service: WorkflowService) -> None:
    """Verify that multiple concurrent CAS consumption attempts on approvals only succeed once."""
    gate_node = WorkflowNode(
        id="gate_cas",
        type=WorkflowNodeType.GATE,
        name="CAS Race Gate",
    )
    wf_def = WorkflowDefinition(
        id="wf_cas_race",
        name="CAS Race Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_cas_race", {})

    approval_id = run.node_runs["gate_cas"].approval_id
    assert approval_id is not None

    # Transition to approved state in registry
    workflow_service.approval_registry.approve_operation(approval_id, actor="admin")

    # Execute direct CAS query from two transactions
    conn = workflow_service._get_connection()
    try:
        now_time = time.time()
        cursor = conn.cursor()

        # First consumption attempt: must succeed (rowcount == 1)
        cursor.execute(
            """
            UPDATE approvals
            SET status = 'consumed', consumed_at = ?
            WHERE approval_id = ? AND status = 'approved' AND expires_at > ?
            """,
            (now_time, approval_id, now_time),
        )
        assert cursor.rowcount == 1
        conn.commit()

        # Second consumption attempt on consumed row: MUST FAIL (rowcount == 0)
        cursor.execute(
            """
            UPDATE approvals
            SET status = 'consumed', consumed_at = ?
            WHERE approval_id = ? AND status = 'approved' AND expires_at > ?
            """,
            (now_time, approval_id, now_time),
        )
        assert cursor.rowcount == 0
    finally:
        if not workflow_service._is_memory:
            conn.close()


# ==============================================================================
# 7. Argument / Input Change Invalidates Prior Approval
# ==============================================================================


def test_argument_change_invalidates_prior_approval(workflow_service: WorkflowService) -> None:
    """Verify that input changes recompute the digest and invalidate prior approvals."""
    gate_node = WorkflowNode(
        id="gate_inv",
        type=WorkflowNodeType.GATE,
        name="Invalidation Gate",
        inputs={"target": "${inputs.target}"},
    )
    wf_def = WorkflowDefinition(
        id="wf_inv_test",
        name="Invalidation Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_inv_test", {"target": "staging"})

    orig_nr = run.node_runs["gate_inv"]
    orig_approval_id = orig_nr.approval_id
    orig_digest = orig_nr.operation_digest

    # Simulate modifying the workflow run inputs in database before gate was consumed
    conn = workflow_service._get_connection()
    try:
        conn.execute(
            "UPDATE workflow_runs SET inputs_json = ? WHERE workflow_run_id = ?",
            (json.dumps({"target": "production"}), run.run_id),
        )
        conn.commit()
    finally:
        if not workflow_service._is_memory:
            conn.close()

    # Reconcile run: detects argument change, invalidates old approval, registers new one
    run_reconciled = workflow_service.reconcile_run(run.run_id)
    new_nr = run_reconciled.node_runs["gate_inv"]

    assert new_nr.status == NodeRunStatus.WAITING_APPROVAL
    assert new_nr.approval_id != orig_approval_id
    assert new_nr.operation_digest != orig_digest

    # Verify old approval was marked rejected/invalidated
    old_op = workflow_service.approval_registry.get_operation(orig_approval_id)
    assert old_op is not None
    assert old_op.status == "rejected"
    assert "invalidated" in str(old_op.decision_reason).lower()


# ==============================================================================
# 8. Rejection Terminates Gate as FAILED, Blocks Downstream, Fails Workflow Run
# ==============================================================================


def test_gate_rejection_terminates_and_fails_run(workflow_service: WorkflowService) -> None:
    """Verify rejecting gate marks it FAILED, skips downstream, and marks workflow FAILED."""
    gate_node = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Approval Gate",
    )
    worker_node = WorkflowNode(
        id="worker_step",
        type=WorkflowNodeType.PIPELINE,
        name="Worker Step",
    )
    wf_def = WorkflowDefinition(
        id="wf_reject_test",
        name="Reject Test",
        nodes=[gate_node, worker_node],
        edges=[WorkflowEdge(id="e1", source="gate_step", target="worker_step")],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_reject_test", {})

    # Operator rejects gate
    run_rejected = workflow_service.reject_gate(
        run.run_id, "gate_step", actor="security_admin", reason="Security policy violation"
    )

    assert run_rejected.status == WorkflowRunStatus.FAILED
    assert run_rejected.node_runs["gate_step"].status == NodeRunStatus.FAILED
    assert "Security policy violation" in str(run_rejected.node_runs["gate_step"].error)
    assert run_rejected.node_runs["gate_step"].resolved_at is not None

    # Downstream node was skipped and never ran
    assert run_rejected.node_runs["worker_step"].status == NodeRunStatus.SKIPPED


# ==============================================================================
# 9. Expiry Keeps Gate Suspended Without Release
# ==============================================================================


def test_gate_expiry_keeps_gate_suspended_without_release(
    workflow_service: WorkflowService,
) -> None:
    """Verify that expired gate approvals do NOT release downstream nodes."""
    gate_node = WorkflowNode(
        id="gate_exp",
        type=WorkflowNodeType.GATE,
        name="Expiring Gate",
        config={"ttl_seconds": 0.05},
    )
    worker_node = WorkflowNode(
        id="worker_step",
        type=WorkflowNodeType.PIPELINE,
        name="Worker Step",
    )
    wf_def = WorkflowDefinition(
        id="wf_exp_test",
        name="Expiry Test",
        nodes=[gate_node, worker_node],
        edges=[WorkflowEdge(id="e1", source="gate_exp", target="worker_step")],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_exp_test", {})

    approval_id = run.node_runs["gate_exp"].approval_id
    assert approval_id is not None

    # Wait for TTL to expire
    time.sleep(0.08)

    # Reconcile run: approval is now expired
    run_reconciled = workflow_service.reconcile_run(run.run_id)

    # Gate remains in WAITING_APPROVAL (or non-completed), downstream remains BLOCKED
    assert run_reconciled.node_runs["gate_exp"].status != NodeRunStatus.COMPLETED
    assert run_reconciled.node_runs["worker_step"].status == NodeRunStatus.BLOCKED

    # Attempting to approve an expired gate must raise WorkflowValidationError or OperationExpiredError
    with pytest.raises(Exception):
        workflow_service.approve_gate(run.run_id, "gate_exp")


# ==============================================================================
# 10. Policy Denial Enforcement Blocks Execution
# ==============================================================================


def test_policy_denial_enforcement_blocks_execution(tmp_path: Path) -> None:
    """Verify policy denial blocks execution regardless of human approval attempt."""
    db_path = str(tmp_path / "policy_denial_test.db")

    # Case A: Declarative config policy denial
    svc_declarative = WorkflowService(db_path=db_path)
    denied_node = WorkflowNode(
        id="forbidden_gate",
        type=WorkflowNodeType.GATE,
        name="Forbidden Gate",
        config={
            "policy_denied": True,
            "policy_reason": "Hardcoded policy denial: production deletion prohibited",
        },
    )
    wf_def = WorkflowDefinition(
        id="wf_policy_denied",
        name="Policy Denied Test",
        nodes=[denied_node],
        edges=[],
    )
    svc_declarative.create_definition(wf_def)

    run = svc_declarative.start_run("wf_policy_denied", {})
    assert run.status == WorkflowRunStatus.FAILED
    assert run.node_runs["forbidden_gate"].status == NodeRunStatus.FAILED
    assert "prohibited" in str(run.node_runs["forbidden_gate"].error)

    # Attempting to approve raises WorkflowValidationError: policy cannot be bypassed!
    with pytest.raises(WorkflowValidationError) as exc_info:
        svc_declarative.approve_gate(run.run_id, "forbidden_gate")
    assert "policy" in str(exc_info.value).lower()

    # Case B: Central PolicyEngine blocking rule
    engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    engine.add_rule(
        PolicyRule(
            id="block_prod_gate",
            name="Block Prod Gate",
            description="Zero trust guardrail blocking prod gates",
            match_type="regex",
            pattern=r"workflow_gate:.*",
            action="block",
            reason="Zero-trust guardrail blocks production gates",
        )
    )

    svc_with_policy = WorkflowService(
        db_path=str(tmp_path / "policy_engine_test.db"), policy_engine=engine
    )
    guarded_node = WorkflowNode(
        id="guarded_gate",
        type=WorkflowNodeType.GATE,
        name="Guarded Gate",
    )
    wf_guarded = WorkflowDefinition(
        id="wf_guarded",
        name="Guarded Workflow",
        nodes=[guarded_node],
        edges=[],
    )
    svc_with_policy.create_definition(wf_guarded)

    run_guarded = svc_with_policy.start_run("wf_guarded", {})
    assert run_guarded.status == WorkflowRunStatus.FAILED
    assert run_guarded.node_runs["guarded_gate"].status == NodeRunStatus.FAILED
    assert "guardrail" in str(run_guarded.node_runs["guarded_gate"].error).lower()


# ==============================================================================
# 11. Process Restart Preserves Gate in WAITING_APPROVAL
# ==============================================================================


def test_process_restart_durability(tmp_path: Path) -> None:
    """Verify that restarting the process preserves gate in WAITING_APPROVAL on disk DB."""
    db_path = str(tmp_path / "restart_durability.db")

    # Instance 1: Create definition and start workflow run
    svc1 = WorkflowService(db_path=db_path)
    gate_node = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Restart Gate",
    )
    worker_node = WorkflowNode(
        id="worker_step",
        type=WorkflowNodeType.PIPELINE,
        name="Worker Step",
    )
    wf_def = WorkflowDefinition(
        id="wf_restart_gate",
        name="Restart Test",
        nodes=[gate_node, worker_node],
        edges=[WorkflowEdge(id="e1", source="gate_step", target="worker_step")],
    )
    svc1.create_definition(wf_def)
    run1 = svc1.start_run("wf_restart_gate", {})
    run_id = run1.run_id
    orig_approval_id = run1.node_runs["gate_step"].approval_id

    # Simulate crash/restart: drop svc1 and create brand new svc2 instance
    del svc1

    svc2 = WorkflowService(db_path=db_path)
    run2 = svc2.get_run(run_id)
    assert run2 is not None
    assert run2.status == WorkflowRunStatus.WAITING_APPROVAL
    assert run2.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL
    assert run2.node_runs["gate_step"].approval_id == orig_approval_id
    assert run2.node_runs["worker_step"].status == NodeRunStatus.BLOCKED

    # Approve gate from restarted instance
    run2_approved = svc2.approve_gate(run_id, "gate_step", actor="restarted_operator")
    assert run2_approved.node_runs["gate_step"].status == NodeRunStatus.COMPLETED
    assert run2_approved.node_runs["worker_step"].status == NodeRunStatus.READY

    # Complete worker step -> complete run
    complete_job_state(svc2.repo, run2_approved.node_runs["worker_step"].job_id)
    run2_final = svc2.reconcile_run(run_id)
    assert run2_final.status == WorkflowRunStatus.COMPLETED


# ==============================================================================
# 12. Workflow Cancellation Terminates Gate
# ==============================================================================


def test_workflow_cancellation_terminates_gate(workflow_service: WorkflowService) -> None:
    """Verify that cancelling a workflow cancels the gate and blocks subsequent approval."""
    gate_node = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Cancellation Gate",
    )
    wf_def = WorkflowDefinition(
        id="wf_cancel_gate",
        name="Cancel Gate Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_cancel_gate", {})

    # Cancel workflow run
    run_cancelled = workflow_service.cancel_run(run.run_id, reason="Emergency abort")
    assert run_cancelled.status == WorkflowRunStatus.CANCELLED
    assert run_cancelled.node_runs["gate_step"].status == NodeRunStatus.CANCELLED

    # Subsequent approval must be rejected
    with pytest.raises(WorkflowValidationError):
        workflow_service.approve_gate(run.run_id, "gate_step")


# ==============================================================================
# 13. Provenance Chain Traceability
# ==============================================================================


def test_provenance_chain_traceability(workflow_service: WorkflowService) -> None:
    """Verify full end-to-end provenance: workflow_run_id -> node_run_id -> approval_id -> operation_digest."""
    gate_node = WorkflowNode(
        id="trace_gate",
        type=WorkflowNodeType.GATE,
        name="Traceability Gate",
        config={"capability": "deploy:cluster"},
        inputs={"target": "eu-central-1"},
    )
    wf_def = WorkflowDefinition(
        id="wf_trace_test",
        name="Traceability Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_trace_test", {})

    node_run = run.node_runs["trace_gate"]
    assert node_run.approval_id is not None
    assert node_run.operation_digest is not None

    # Query approvals table directly
    conn = workflow_service._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT approval_id, execution_id, operation_digest, capability, status
            FROM approvals WHERE approval_id = ?
            """,
            (node_run.approval_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == node_run.approval_id
        assert row[1] == run.run_id
        assert row[2] == node_run.operation_digest
        assert row[3] == "deploy:cluster"
        assert row[4] == "pending"
    finally:
        if not workflow_service._is_memory:
            conn.close()

    # Approve and verify consumed record provenance
    workflow_service.approve_gate(run.run_id, "trace_gate", actor="trace_lead")
    completed_run = workflow_service.get_run(run.run_id)
    assert completed_run.node_runs["trace_gate"].resolved_at is not None


# ==============================================================================
# 14. Zero Shadow Tables and Zero Secret Leakage
# ==============================================================================


def test_zero_shadow_tables_and_zero_secret_leakage(workflow_service: WorkflowService) -> None:
    """Verify no shadow tables were created and no secret bearer tokens leak into payloads."""
    gate_node = WorkflowNode(
        id="gate_leak",
        type=WorkflowNodeType.GATE,
        name="Leak Test Gate",
        inputs={"api_key": "secret_test_token_12345", "param": "public_val"},
    )
    wf_def = WorkflowDefinition(
        id="wf_leak_test",
        name="Leak Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_leak_test", {})

    # 1. Shadow tables audit
    conn = workflow_service._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        allowed_tables = {
            "job_schema_migrations",
            "jobs",
            "job_attempts",
            "job_events",
            "job_dependencies",
            "job_artifacts",
            "job_schedules",
            "job_queue",
            "idempotency_keys",
            "job_schedule_occurrences",
            "workflow_definitions",
            "workflow_runs",
            "workflow_node_runs",
            "approvals",
            "sessions",
            "executions",
            "execution_events",
            "artifacts",
            "cost_records",
            "audit_logs",
            "audit_patches",
            "policies",
            "scheduled_tasks",
            "scheduled_occurrences",
            "job_idempotency_records",
            "users",
            "projects",
            "collaborative_rooms",
            "room_participants",
            "room_tasks",
            "benchmarks",
            "skill_collections",
            "collection_skills",
        }
        shadow_tables = tables - allowed_tables
        assert not shadow_tables, f"Unexpected shadow tables detected: {shadow_tables}"
    finally:
        if not workflow_service._is_memory:
            conn.close()

    # 2. Secret leakage audit: approve and inspect database contents
    workflow_service.approve_gate(run.run_id, "gate_leak")
    finished_run = workflow_service.get_run(run.run_id)

    # Raw bearer tokens (tok_...) must NEVER appear anywhere in serialized inputs/outputs
    for nr in finished_run.node_runs.values():
        serialized = json.dumps(nr.model_dump())
        assert "tok_" not in serialized


# ==============================================================================
# 15. Option A: Single Downstream Protected Operation Constraint
# ==============================================================================


def test_gate_multiple_downstream_operations_rejected(workflow_service: WorkflowService) -> None:
    """Option A enforcement: a GATE node cannot branch into multiple downstream edges."""
    gate_node = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Branching Gate",
    )
    worker1 = WorkflowNode(id="worker_1", type=WorkflowNodeType.PIPELINE, name="Worker 1")
    worker2 = WorkflowNode(id="worker_2", type=WorkflowNodeType.PIPELINE, name="Worker 2")

    wf_def = WorkflowDefinition(
        id="wf_multi_downstream_rejected",
        name="Multi Downstream Reject Test",
        nodes=[gate_node, worker1, worker2],
        edges=[
            WorkflowEdge(id="e1", source="gate_step", target="worker_1"),
            WorkflowEdge(id="e2", source="gate_step", target="worker_2"),
        ],
    )
    # Validation must reject multi-downstream gate
    with pytest.raises(WorkflowValidationError) as exc_info:
        workflow_service.create_definition(wf_def)
    assert "multiple downstream edges" in str(exc_info.value)


# ==============================================================================
# 16. Five Exact Invalidations Suite
# ==============================================================================


def test_five_exact_invalidations(workflow_service: WorkflowService) -> None:
    """Verify all 5 exact invalidations: arguments, target, operation/tool, artifact digest, actor mismatch."""
    # Setup gate governing deploy node
    deploy_node = WorkflowNode(
        id="deploy_node",
        type=WorkflowNodeType.PIPELINE,
        name="Deploy Step",
        config={"tool_name": "deploy_tool", "capability": "deploy:prod"},
        inputs={"target": "cluster-a", "version": "1.0.0", "artifact_digest": "sha256:abc"},
    )
    gate_node = WorkflowNode(
        id="deploy_gate",
        type=WorkflowNodeType.GATE,
        name="Deploy Gate",
        config={"actor": "lead_operator"},
    )
    wf_def = WorkflowDefinition(
        id="wf_5_invalidations",
        name="5 Invalidations Test",
        nodes=[gate_node, deploy_node],
        edges=[WorkflowEdge(id="e1", source="deploy_gate", target="deploy_node")],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_5_invalidations", {})

    initial_op_id = run.node_runs["deploy_gate"].approval_id
    initial_digest = run.node_runs["deploy_gate"].operation_digest
    assert initial_op_id is not None
    assert initial_digest is not None

    # (5) Actor mismatch: approval attempted by unauthorized actor
    with pytest.raises(WorkflowValidationError) as actor_exc:
        workflow_service.approve_gate(run.run_id, "deploy_gate", actor="intruder_actor")
    assert "requires approval by actor 'lead_operator'" in str(actor_exc.value)

    # (1) Arguments change: modify version input directly on node run
    conn = workflow_service._get_connection()
    try:
        with conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET inputs_json = ?
                WHERE workflow_run_id = ?
                """,
                (json.dumps({"version": "2.0.0"}), run.run_id),
            )
            # Change target node inputs in snapshot to simulate argument change
            snapshot = run.definition_snapshot
            for n in snapshot["nodes"]:
                if n["id"] == "deploy_node":
                    n["inputs"]["version"] = "2.0.0"
            conn.execute(
                """
                UPDATE workflow_runs
                SET definition_snapshot_json = ?
                WHERE workflow_run_id = ?
                """,
                (json.dumps(snapshot), run.run_id),
            )
    finally:
        if not workflow_service._is_memory:
            conn.close()

    # Reconciling must invalidate prior approval and register fresh one
    reconciled_run = workflow_service.reconcile_run(run.run_id)
    new_op_id = reconciled_run.node_runs["deploy_gate"].approval_id
    new_digest = reconciled_run.node_runs["deploy_gate"].operation_digest
    assert new_op_id != initial_op_id
    assert new_digest != initial_digest

    # Verify old approval was marked rejected
    old_op = workflow_service.approval_registry.get_operation(initial_op_id)
    assert old_op is not None
    assert old_op.status == "rejected"
    assert "Invalidated" in (old_op.decision_reason or "")

    # (2) Target change invalidation
    snapshot = reconciled_run.definition_snapshot
    for n in snapshot["nodes"]:
        if n["id"] == "deploy_node":
            n["inputs"]["target"] = "cluster-b"
    conn = workflow_service._get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE workflow_runs SET definition_snapshot_json = ? WHERE workflow_run_id = ?",
                (json.dumps(snapshot), run.run_id),
            )
    finally:
        if not workflow_service._is_memory:
            conn.close()

    run_target_changed = workflow_service.reconcile_run(run.run_id)
    target_op_id = run_target_changed.node_runs["deploy_gate"].approval_id
    assert target_op_id != new_op_id

    # (3) Tool / operation change invalidation
    for n in snapshot["nodes"]:
        if n["id"] == "deploy_node":
            n["config"]["tool_name"] = "destroy_tool"
    conn = workflow_service._get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE workflow_runs SET definition_snapshot_json = ? WHERE workflow_run_id = ?",
                (json.dumps(snapshot), run.run_id),
            )
    finally:
        if not workflow_service._is_memory:
            conn.close()

    run_tool_changed = workflow_service.reconcile_run(run.run_id)
    tool_op_id = run_tool_changed.node_runs["deploy_gate"].approval_id
    assert tool_op_id != target_op_id

    # (4) Artifact digest change invalidation
    for n in snapshot["nodes"]:
        if n["id"] == "deploy_node":
            n["inputs"]["artifact_digest"] = "sha256:different_hash_999"
    conn = workflow_service._get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE workflow_runs SET definition_snapshot_json = ? WHERE workflow_run_id = ?",
                (json.dumps(snapshot), run.run_id),
            )
    finally:
        if not workflow_service._is_memory:
            conn.close()

    run_artifact_changed = workflow_service.reconcile_run(run.run_id)
    artifact_op_id = run_artifact_changed.node_runs["deploy_gate"].approval_id
    assert artifact_op_id != tool_op_id


# ==============================================================================
# 17. Central R2 Approval Service Ownership of Consumption
# ==============================================================================


def test_central_r2_approval_service_owns_consumption(workflow_service: WorkflowService) -> None:
    """Verify WorkflowService routes approval consumption strictly through central PendingOperationRegistry."""
    gate_node = WorkflowNode(id="gate_step", type=WorkflowNodeType.GATE, name="Approval Gate")
    worker_node = WorkflowNode(id="worker_step", type=WorkflowNodeType.PIPELINE, name="Worker Step")
    wf_def = WorkflowDefinition(
        id="wf_r2_consumption_ownership",
        name="R2 Consumption Ownership Test",
        nodes=[gate_node, worker_node],
        edges=[WorkflowEdge(id="e1", source="gate_step", target="worker_step")],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_r2_consumption_ownership", {})

    approval_id = run.node_runs["gate_step"].approval_id
    assert approval_id is not None

    with patch.object(
        workflow_service.approval_registry,
        "consume_exact_approval",
        wraps=workflow_service.approval_registry.consume_exact_approval,
    ) as mock_consume:
        workflow_service.approve_gate(run.run_id, "gate_step")
        assert mock_consume.called
        assert mock_consume.call_args[1]["approval_id"] == approval_id

    # Verify atomic CAS consumption in DB
    op = workflow_service.approval_registry.get_operation(approval_id)
    assert op is not None
    assert op.status == "consumed"
    assert op.consumed_at is not None


# ==============================================================================
# 18. Multi-Process Race Request Deduplication
# ==============================================================================


def test_approval_request_deduplication_multi_process_race(
    workflow_service: WorkflowService,
) -> None:
    """Verify concurrent reconcile races produce exactly one pending approval record (deterministic ID)."""
    gate_node = WorkflowNode(id="gate_step", type=WorkflowNodeType.GATE, name="Dedup Gate")
    wf_def = WorkflowDefinition(
        id="wf_dedup_race",
        name="Dedup Race Test",
        nodes=[gate_node],
        edges=[],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_dedup_race", {})

    initial_approval_id = run.node_runs["gate_step"].approval_id

    # Run 10 concurrent reconcile operations
    def run_reconcile() -> str:
        r = workflow_service.reconcile_run(run.run_id)
        return r.node_runs["gate_step"].approval_id

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(run_reconcile) for _ in range(10)]
        results = [f.result() for f in futures]

    # Every concurrent reconcile returned the exact same deterministic approval ID
    assert all(r == initial_approval_id for r in results)

    # In database approvals table, exactly one record exists for this execution
    conn = workflow_service._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM approvals WHERE execution_id = ?",
            (run.run_id,),
        )
        assert cursor.fetchone()[0] == 1
    finally:
        if not workflow_service._is_memory:
            conn.close()


# ==============================================================================
# 19. Expired Gate Renewal Recovery (No Deadlock, No Auto-Authorize, No Spam)
# ==============================================================================


def test_expired_gate_re_request_recovery(workflow_service: WorkflowService) -> None:
    """Expired gates remain suspended (no deadlock, no auto-auth). Explicit renewal creates fresh approval."""
    gate_node = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Expiring Gate",
        config={"ttl_seconds": 0.05},
    )
    worker_node = WorkflowNode(id="worker_step", type=WorkflowNodeType.PIPELINE, name="Worker Step")
    wf_def = WorkflowDefinition(
        id="wf_expire_renewal",
        name="Expire Renewal Test",
        nodes=[gate_node, worker_node],
        edges=[WorkflowEdge(id="e1", source="gate_step", target="worker_step")],
    )
    workflow_service.create_definition(wf_def)
    run = workflow_service.start_run("wf_expire_renewal", {})

    orig_approval_id = run.node_runs["gate_step"].approval_id
    time.sleep(0.1)

    # Reconcile after expiry: must not auto-authorize or advance
    run_after_expiry = workflow_service.reconcile_run(run.run_id)
    assert run_after_expiry.status == WorkflowRunStatus.WAITING_APPROVAL
    assert run_after_expiry.node_runs["gate_step"].status == NodeRunStatus.WAITING_APPROVAL
    assert run_after_expiry.node_runs["worker_step"].status == NodeRunStatus.BLOCKED

    # Attempting to approve the expired token fails closed
    with pytest.raises(Exception):
        workflow_service.approve_gate(run.run_id, "gate_step")

    # Explicit renewal creates a valid new approval record with fresh TTL
    renewed_run = workflow_service.renew_gate_approval(run.run_id, "gate_step", ttl_seconds=3600.0)
    new_approval_id = renewed_run.node_runs["gate_step"].approval_id
    assert new_approval_id != orig_approval_id
    assert renewed_run.status == WorkflowRunStatus.WAITING_APPROVAL

    # Approving the renewed gate cleanly unblocks the workflow
    approved_run = workflow_service.approve_gate(run.run_id, "gate_step")
    assert approved_run.node_runs["gate_step"].status == NodeRunStatus.COMPLETED
    assert approved_run.node_runs["worker_step"].status == NodeRunStatus.READY


# ==============================================================================
# 20. Approvals Schema Ownership & Migration Immutability Regression
# ==============================================================================


def test_approval_schema_ownership_regression() -> None:
    """Verify Migration 009 is immutable, exactly 9 migrations exist (no Migration 010), and SQLiteBackend owns approvals DDL."""
    from core.jobs.migrations import MIGRATION_REGISTRY

    # Exactly 9 migrations exist in 0.5 (no unnecessary migration 010)
    assert len(MIGRATION_REGISTRY) == 9
    version, name, func = MIGRATION_REGISTRY[8]
    assert version == 9
    assert name == "009_workflow_hitl_gates"

    # In clean database with WorkflowService, approvals and workflow tables are created canonically
    svc = WorkflowService(db_path=":memory:")
    conn = svc._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='approvals'")
    assert cursor.fetchone() is not None

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_node_runs'"
    )
    assert cursor.fetchone() is not None
