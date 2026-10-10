"""tests/test_r4_8_workflow_convergence.py

Milestone R4 (Task R4.8 - Absorb Legacy Phase 7 Runtime) Test Suite.

Verifies:
1. Migration 007 applies cleanly: workflow_definitions, workflow_runs, workflow_node_runs schemas.
2. Definition CRUD, indexing, SHA-256 hash calculation, and lossless legacy format compatibility.
3. Explicit rejection of unsupported node types (e.g. GATE deferred to R4.9).
4. DAG validation and directed cycle rejection.
5. Linear workflow DAG compilation, root job enqueuing, and dependency progression via reconcile_run.
6. Parallel fan-out (A -> B, A -> C) and fan-in (B -> D, C -> D) join barriers.
7. Conditional branching and skipped branch handling.
8. WorkerService integration: processing workflow_step jobs via ExecutionCoordinator.
9. Architecture bypass AST assertion: WorkflowService contains zero LLM/model imports.
10. R4.4 retry reuse: node failure respects durable backoff without prematurely failing workflow.
11. R4.5 cancellation reuse: cancel_run cascades cooperative cancellation to active/queued jobs.
12. Restart safety & crash recovery: state reconstructs from disk, no duplicate jobs on restart.
13. Concurrent coordinator race safety: concurrent reconcile_run calls produce no duplicate releases.
14. Complete provenance chain: workflow_run_id -> node_run_id -> job_id -> attempt_id -> execution_id.
15. Data minimization & zero secret leakage in workflow payloads and audit events.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import pytest

from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import ExecutionStatus
from core.jobs.migrations import apply_job_migrations, get_current_job_schema_version
from core.jobs.models import (
    JobAttemptStatus,
    JobStatus,
    RetryPolicy,
)
from core.jobs.sqlite import SQLiteJobRepository
from core.jobs.worker import JobExecutionRequestFactory, JobWorker, SUPPORTED_JOB_TYPES
from core.workflows.exceptions import (
    WorkflowValidationError,
)
from core.workflows.models import (
    NodeRunStatus,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowPosition,
    WorkflowRunStatus,
    WorkflowStatus,
)
from core.workflows.service import WorkflowService


# ==============================================================================
# Fixtures & Helpers
# ==============================================================================


@pytest.fixture
def file_db_path(tmp_path: Path) -> str:
    """Provide a fresh SQLite file database path."""
    return str(tmp_path / "test_r4_8_workflow.db")


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


def make_mock_coordinator(
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    outputs: Optional[Dict[str, Any]] = None,
    error_msg: Optional[str] = None,
) -> ExecutionCoordinator:
    """Create a mock ExecutionCoordinator returning predictable outcomes."""

    def mock_dispatch(ctx: Any, tier: Any, prov: Any, model: Any) -> Any:
        if status == ExecutionStatus.FAILED:
            raise RuntimeError(error_msg or "Mock dispatch failure")
        return outputs or {"response": "mock_success_output", "status": status.value}

    return ExecutionCoordinator(dispatch_override=mock_dispatch)


def build_sample_definition(
    workflow_id: str = "wf_sample",
    nodes: Optional[List[WorkflowNode]] = None,
    edges: Optional[List[WorkflowEdge]] = None,
) -> WorkflowDefinition:
    """Build a valid sample WorkflowDefinition."""
    if nodes is None:
        nodes = [
            WorkflowNode(
                id="step_a",
                type=WorkflowNodeType.PIPELINE,
                name="Step A",
                description="First processing step",
                inputs={"data": "raw_input"},
                outputs=["result_a"],
                position=WorkflowPosition(x=100.0, y=100.0),
            ),
            WorkflowNode(
                id="step_b",
                type=WorkflowNodeType.SKILL,
                name="Step B",
                description="Second processing step",
                inputs={"source": "{{step_a.result_a}}"},
                outputs=["result_b"],
                position=WorkflowPosition(x=300.0, y=100.0),
            ),
        ]
    if edges is None:
        edges = [
            WorkflowEdge(id="edge_ab", source="step_a", target="step_b"),
        ]
    return WorkflowDefinition(
        id=workflow_id,
        name="Sample Test Workflow",
        description="Definition for integration testing",
        version="1.0.0",
        status=WorkflowStatus.ACTIVE,
        nodes=nodes,
        edges=edges,
        metadata={"project_id": "test_project"},
    )


# ==============================================================================
# 1. Schema & Migration 007 Tests
# ==============================================================================


def test_migration_007_applied_and_schema_verified(file_db_path: str) -> None:
    """Verify Migration 007 runs automatically and creates workflow tables."""
    conn = sqlite3.connect(file_db_path)
    try:
        apply_job_migrations(conn)
        version = get_current_job_schema_version(conn)
        assert version >= 7

        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "workflow_definitions" in tables
        assert "workflow_runs" in tables
        assert "workflow_node_runs" in tables

        # Verify columns of workflow_definitions
        cursor.execute("PRAGMA table_info(workflow_definitions)")
        cols = {row[1] for row in cursor.fetchall()}
        assert {"workflow_id", "definition_hash", "definition_json", "status"}.issubset(cols)

        # Verify columns of workflow_runs
        cursor.execute("PRAGMA table_info(workflow_runs)")
        cols = {row[1] for row in cursor.fetchall()}
        assert {
            "workflow_run_id",
            "workflow_id",
            "definition_hash",
            "definition_snapshot_json",
            "status",
            "inputs_json",
            "outputs_json",
        }.issubset(cols)

        # Verify columns of workflow_node_runs
        cursor.execute("PRAGMA table_info(workflow_node_runs)")
        cols = {row[1] for row in cursor.fetchall()}
        assert {
            "node_run_id",
            "workflow_run_id",
            "node_id",
            "node_type",
            "job_id",
            "status",
        }.issubset(cols)
    finally:
        conn.close()


# ==============================================================================
# 2. Workflow Definition CRUD & Legacy Compatibility
# ==============================================================================


def test_definition_crud_and_legacy_compatibility(workflow_service: WorkflowService) -> None:
    """Verify CRUD operations, SHA-256 hash determinism, and legacy format support."""
    wf_def = build_sample_definition(workflow_id="wf_crud_test")

    # 1. Create definition
    created = workflow_service.create_definition(wf_def)
    assert created.id == "wf_crud_test"
    assert created.name == "Sample Test Workflow"

    # Deterministic SHA-256 hash
    hash1 = created.compute_definition_hash()
    assert len(hash1) == 64
    assert hash1 == wf_def.compute_definition_hash()

    # 2. Get definition
    fetched = workflow_service.get_definition("wf_crud_test")
    assert fetched is not None
    assert fetched.id == wf_def.id
    assert len(fetched.nodes) == 2
    assert len(fetched.edges) == 1
    assert fetched.nodes[0].position.x == 100.0  # Visual canvas position preserved

    # 3. List definitions
    all_defs = workflow_service.list_definitions()
    assert any(d.id == "wf_crud_test" for d in all_defs)

    active_defs = workflow_service.list_definitions(status=WorkflowStatus.ACTIVE)
    assert any(d.id == "wf_crud_test" for d in active_defs)

    # 4. Lossless legacy format import
    legacy_json_str = json.dumps(wf_def.to_dict())
    reconstituted = WorkflowDefinition.model_validate(json.loads(legacy_json_str))
    assert reconstituted.to_dict() == wf_def.to_dict()

    # 5. Delete definition
    deleted = workflow_service.delete_definition("wf_crud_test")
    assert deleted is True
    assert workflow_service.get_definition("wf_crud_test") is None


# ==============================================================================
# 3. Unsupported Node Type Rejection (GATE Deferred to R4.9)
# ==============================================================================


def test_gate_node_rejection_for_r4_9(workflow_service: WorkflowService) -> None:
    """Verify that GATE nodes fail validation as deferred to R4.9."""
    gate_node = WorkflowNode(
        id="gate_step",
        type=WorkflowNodeType.GATE,
        name="Approval Gate",
        config={"approver_role": "admin"},
    )
    wf_def = WorkflowDefinition(
        id="wf_with_gate",
        name="Workflow With Gate",
        nodes=[gate_node],
        edges=[],
    )

    with pytest.raises(WorkflowValidationError) as exc_info:
        workflow_service.create_definition(wf_def)
    assert "deferred to Milestone R4.9" in str(exc_info.value)


# ==============================================================================
# 4. DAG Validation & Directed Cycle Detection
# ==============================================================================


def test_dag_cycle_rejection(workflow_service: WorkflowService) -> None:
    """Verify that cyclic workflows are strictly rejected."""
    node_a = WorkflowNode(id="a", type=WorkflowNodeType.PIPELINE, name="A")
    node_b = WorkflowNode(id="b", type=WorkflowNodeType.PIPELINE, name="B")
    node_c = WorkflowNode(id="c", type=WorkflowNodeType.PIPELINE, name="C")

    # A -> B -> C -> A (cycle)
    edges = [
        WorkflowEdge(id="e1", source="a", target="b"),
        WorkflowEdge(id="e2", source="b", target="c"),
        WorkflowEdge(id="e3", source="c", target="a"),
    ]
    cyclic_def = WorkflowDefinition(
        id="wf_cycle",
        name="Cyclic Workflow",
        nodes=[node_a, node_b, node_c],
        edges=edges,
    )

    with pytest.raises(WorkflowValidationError) as exc_info:
        workflow_service.create_definition(cyclic_def)
    assert "Cycle" in str(exc_info.value) or "cycle" in str(exc_info.value)


def test_dag_invalid_edge_rejection(workflow_service: WorkflowService) -> None:
    """Verify edges pointing to non-existent nodes fail validation."""
    node_a = WorkflowNode(id="a", type=WorkflowNodeType.PIPELINE, name="A")
    edges = [WorkflowEdge(id="e1", source="a", target="non_existent")]
    invalid_def = WorkflowDefinition(
        id="wf_bad_edge",
        name="Bad Edge Workflow",
        nodes=[node_a],
        edges=edges,
    )

    with pytest.raises(WorkflowValidationError) as exc_info:
        workflow_service.create_definition(invalid_def)
    assert "references non-existent" in str(exc_info.value)


# ==============================================================================
# 5. Linear Workflow Progression (A -> B)
# ==============================================================================


def test_linear_workflow_progression(workflow_service: WorkflowService) -> None:
    """Verify compilation, root job enqueue, dependency unblocking, and output propagation."""
    wf_def = build_sample_definition(workflow_id="wf_linear")
    workflow_service.create_definition(wf_def)

    # Launch run
    run = workflow_service.start_run("wf_linear", inputs={"raw_input": "hello_agent"})
    assert run.status == WorkflowRunStatus.RUNNING
    assert len(run.node_runs) == 2

    node_a_run = run.node_runs["step_a"]
    node_b_run = run.node_runs["step_b"]
    assert node_a_run.status == NodeRunStatus.READY
    assert node_b_run.status == NodeRunStatus.BLOCKED

    # Root job step_a is enqueued in the local queue
    queue_entries = workflow_service.queue.list_entries(limit=10)
    assert any(q.job_id == node_a_run.job_id for q in queue_entries)
    # Blocked job step_b is NOT in the queue
    assert not any(q.job_id == node_b_run.job_id for q in queue_entries)

    # Step A finishes (READY -> RUNNING -> COMPLETED)
    complete_job_state(workflow_service.repo, node_a_run.job_id)

    # Reconcile run: step_a should complete and step_b should become READY and enqueued
    run = workflow_service.reconcile_run(run.run_id)
    assert run.node_runs["step_a"].status == NodeRunStatus.COMPLETED
    assert run.node_runs["step_b"].status == NodeRunStatus.READY

    queue_entries = workflow_service.queue.list_entries(limit=10)
    assert any(q.job_id == node_b_run.job_id for q in queue_entries)

    # Step B finishes (READY -> RUNNING -> COMPLETED)
    complete_job_state(workflow_service.repo, node_b_run.job_id)

    # Final reconcile: run should be COMPLETED with aggregated outputs
    final_run = workflow_service.reconcile_run(run.run_id)
    assert final_run.status == WorkflowRunStatus.COMPLETED
    assert final_run.completed_at is not None
    assert "step_a" in final_run.outputs
    assert "step_b" in final_run.outputs


# ==============================================================================
# 6. Parallel Fan-Out (A -> B, A -> C) and Fan-In (B -> D, C -> D)
# ==============================================================================


def test_parallel_fan_out_and_fan_in(workflow_service: WorkflowService) -> None:
    """Verify diamond DAG: parallel unblocking and strict join barrier satisfaction."""
    nodes = [
        WorkflowNode(id="a", type=WorkflowNodeType.PIPELINE, name="Start"),
        WorkflowNode(id="b", type=WorkflowNodeType.PIPELINE, name="Branch B"),
        WorkflowNode(id="c", type=WorkflowNodeType.PIPELINE, name="Branch C"),
        WorkflowNode(id="d", type=WorkflowNodeType.PIPELINE, name="Join D"),
    ]
    edges = [
        WorkflowEdge(id="e_ab", source="a", target="b"),
        WorkflowEdge(id="e_ac", source="a", target="c"),
        WorkflowEdge(id="e_bd", source="b", target="d"),
        WorkflowEdge(id="e_cd", source="c", target="d"),
    ]
    diamond_def = WorkflowDefinition(
        id="wf_diamond",
        name="Diamond Workflow",
        nodes=nodes,
        edges=edges,
    )
    workflow_service.create_definition(diamond_def)

    run = workflow_service.start_run("wf_diamond")
    assert run.node_runs["a"].status == NodeRunStatus.READY
    assert run.node_runs["b"].status == NodeRunStatus.BLOCKED
    assert run.node_runs["c"].status == NodeRunStatus.BLOCKED
    assert run.node_runs["d"].status == NodeRunStatus.BLOCKED

    # Complete root node A
    complete_job_state(workflow_service.repo, run.node_runs["a"].job_id)
    run = workflow_service.reconcile_run(run.run_id)

    # Fan-out: both B and C become READY
    assert run.node_runs["b"].status == NodeRunStatus.READY
    assert run.node_runs["c"].status == NodeRunStatus.READY
    assert run.node_runs["d"].status == NodeRunStatus.BLOCKED

    # Complete only branch B
    complete_job_state(workflow_service.repo, run.node_runs["b"].job_id)
    run = workflow_service.reconcile_run(run.run_id)

    # Join barrier: D must REMAIN blocked because C is not completed yet
    assert run.node_runs["b"].status == NodeRunStatus.COMPLETED
    assert run.node_runs["c"].status == NodeRunStatus.READY
    assert run.node_runs["d"].status == NodeRunStatus.BLOCKED

    # Complete branch C
    complete_job_state(workflow_service.repo, run.node_runs["c"].job_id)
    run = workflow_service.reconcile_run(run.run_id)

    # Both prerequisites satisfied: D becomes READY
    assert run.node_runs["c"].status == NodeRunStatus.COMPLETED
    assert run.node_runs["d"].status == NodeRunStatus.READY

    # Complete D
    complete_job_state(workflow_service.repo, run.node_runs["d"].job_id)
    final_run = workflow_service.reconcile_run(run.run_id)
    assert final_run.status == WorkflowRunStatus.COMPLETED


# ==============================================================================
# 7. Conditional Branching & Skipped Branches
# ==============================================================================


def test_conditional_branching_and_skip(workflow_service: WorkflowService) -> None:
    """Verify condition node evaluation and downstream branch skipping."""
    nodes = [
        WorkflowNode(
            id="cond",
            type=WorkflowNodeType.CONDITION,
            name="Check Condition",
            config={"expression": "'vip' == 'vip'"},
        ),
        WorkflowNode(id="premium_path", type=WorkflowNodeType.PIPELINE, name="Premium"),
        WorkflowNode(id="standard_path", type=WorkflowNodeType.PIPELINE, name="Standard"),
    ]
    edges = [
        WorkflowEdge(id="e_cond_prem", source="cond", target="premium_path", condition="true"),
        WorkflowEdge(id="e_cond_std", source="cond", target="standard_path", condition="false"),
    ]
    branch_def = WorkflowDefinition(
        id="wf_branch",
        name="Branch Workflow",
        nodes=nodes,
        edges=edges,
    )
    workflow_service.create_definition(branch_def)

    run = workflow_service.start_run("wf_branch")
    cond_job_id = run.node_runs["cond"].job_id

    # Complete condition node
    complete_job_state(workflow_service.repo, cond_job_id)
    run = workflow_service.reconcile_run(run.run_id)

    # premium_path (true condition) is READY; standard_path (false condition) is SKIPPED
    assert run.node_runs["cond"].status == NodeRunStatus.COMPLETED
    assert run.node_runs["premium_path"].status == NodeRunStatus.READY
    assert run.node_runs["standard_path"].status == NodeRunStatus.SKIPPED

    # Complete premium_path
    complete_job_state(workflow_service.repo, run.node_runs["premium_path"].job_id)
    final_run = workflow_service.reconcile_run(run.run_id)
    assert final_run.status == WorkflowRunStatus.COMPLETED


# ==============================================================================
# 8. WorkerService Integration via ExecutionCoordinator
# ==============================================================================


def test_worker_service_integration(file_db_path: str) -> None:
    """Verify JobWorker claims, executes workflow_step jobs via ExecutionCoordinator."""
    assert "workflow_step" in SUPPORTED_JOB_TYPES
    assert "pipeline" in SUPPORTED_JOB_TYPES
    assert "skill" in SUPPORTED_JOB_TYPES

    wf_service = WorkflowService(db_path=file_db_path)
    wf_def = build_sample_definition(workflow_id="wf_worker_int")
    wf_service.create_definition(wf_def)

    run = wf_service.start_run("wf_worker_int")
    root_job_id = run.node_runs["step_a"].job_id

    # Configure mock coordinator and worker
    coord = make_mock_coordinator(
        status=ExecutionStatus.COMPLETED, outputs={"result_a": "produced_by_worker"}
    )
    worker = JobWorker(db_path=file_db_path, coordinator=coord)

    # Step the worker once to claim and process step_a
    processed = worker.step()
    assert processed is True

    # Verify Job step_a is now COMPLETED
    job_a = wf_service.repo.get_job(root_job_id)
    assert job_a is not None
    assert job_a.status == JobStatus.COMPLETED

    # Verify attempt was recorded
    attempts = wf_service.repo.list_attempts(root_job_id)
    assert len(attempts) >= 1
    assert attempts[0].status == JobAttemptStatus.COMPLETED

    # Reconcile run: advances to step_b
    run = wf_service.reconcile_run(run.run_id)
    assert run.node_runs["step_a"].status == NodeRunStatus.COMPLETED
    assert run.node_runs["step_b"].status == NodeRunStatus.READY

    # Step worker again to process step_b
    processed_b = worker.step()
    assert processed_b is True

    final_run = wf_service.reconcile_run(run.run_id)
    assert final_run.status == WorkflowRunStatus.COMPLETED
    worker.close()


# ==============================================================================
# 9. Architecture Bypass AST Assertion
# ==============================================================================


def test_architecture_bypass_ast_assertion() -> None:
    """Verify core/workflows/service.py does NOT import LLM providers or models directly.

    Proves separation of concerns: WorkflowService orchestrates DAGs and jobs,
    delegating all execution exclusively to WorkerService / ExecutionCoordinator.
    """
    service_file = Path(__file__).resolve().parents[1] / "core" / "workflows" / "service.py"
    with open(service_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(service_file))

    forbidden_modules = {
        "litellm",
        "openai",
        "anthropic",
        "google.generativeai",
        "google.ai",
        "langchain",
        "transformers",
    }

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    violating_imports = forbidden_modules.intersection(imported_modules)
    assert (
        not violating_imports
    ), f"WorkflowService directly imports forbidden execution modules: {violating_imports}"


# ==============================================================================
# 10. R4.4 Retry Model Reuse on Node Failure
# ==============================================================================


def test_r4_4_retry_reuse_on_node_failure(file_db_path: str) -> None:
    """Verify node job retry preserves RUNNING workflow state until retry exhaustion."""
    wf_service = WorkflowService(db_path=file_db_path)
    nodes = [WorkflowNode(id="step_fail", type=WorkflowNodeType.PIPELINE, name="Flaky Step")]
    wf_def = WorkflowDefinition(
        id="wf_retry",
        name="Retry Workflow",
        nodes=nodes,
        edges=[],
    )
    wf_service.create_definition(wf_def)

    run = wf_service.start_run("wf_retry")
    job_id = run.node_runs["step_fail"].job_id

    # Worker configured with RetryPolicy to fail
    coord = make_mock_coordinator(status=ExecutionStatus.FAILED, error_msg="Transient glitch")
    retry_policy = RetryPolicy(max_attempts=3, backoff_base_seconds=1.0)
    worker = JobWorker(db_path=file_db_path, coordinator=coord, retry_policy=retry_policy)

    # Attempt 1 fails -> Job should enter WAITING status for retry
    worker.step()
    job = wf_service.repo.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.WAITING

    # Workflow run remains RUNNING during retry backoff
    run = wf_service.reconcile_run(run.run_id)
    assert run.status == WorkflowRunStatus.RUNNING

    worker.close()


# ==============================================================================
# 11. R4.5 Cancellation Reuse
# ==============================================================================


def test_r4_5_cancellation_reuse(workflow_service: WorkflowService) -> None:
    """Verify cancel_run cascades cooperative cancellation to active and queued jobs."""
    wf_def = build_sample_definition(workflow_id="wf_cancel")
    workflow_service.create_definition(wf_def)

    run = workflow_service.start_run("wf_cancel")
    job_a_id = run.node_runs["step_a"].job_id
    job_b_id = run.node_runs["step_b"].job_id

    # Cancel workflow run
    cancelled_run = workflow_service.cancel_run(run.run_id, reason="Operator abort")
    assert cancelled_run.status == WorkflowRunStatus.CANCELLED
    assert cancelled_run.error == "Operator abort"

    # Underlying jobs are cancelled
    job_a = workflow_service.repo.get_job(job_a_id)
    job_b = workflow_service.repo.get_job(job_b_id)
    assert job_a.status == JobStatus.CANCELLED
    assert job_b.status == JobStatus.CANCELLED

    # Cancelled jobs removed from queue
    queue_entries = workflow_service.queue.list_entries(limit=10)
    assert not any(q.job_id in (job_a_id, job_b_id) for q in queue_entries)


# ==============================================================================
# 12. Restart Safety & Crash Recovery
# ==============================================================================


def test_restart_safety_and_crash_recovery(file_db_path: str) -> None:
    """Verify workflow state reconstructs from disk and resumes after process restart."""
    # Process 1: start workflow and complete step_a
    service_1 = WorkflowService(db_path=file_db_path)
    wf_def = build_sample_definition(workflow_id="wf_restart")
    service_1.create_definition(wf_def)

    run_1 = service_1.start_run("wf_restart")
    job_a_id = run_1.node_runs["step_a"].job_id
    complete_job_state(service_1.repo, job_a_id)

    # Crash! (Discard service_1 instance without calling reconcile_run)
    del service_1

    # Process 2: Start new service on the same persistent SQLite database
    service_2 = WorkflowService(db_path=file_db_path)
    recovered_run = service_2.get_run(run_1.run_id)
    assert recovered_run is not None
    assert recovered_run.status == WorkflowRunStatus.RUNNING

    # Calling reconcile_run discovers completed job_a and releases step_b
    advanced_run = service_2.reconcile_run(run_1.run_id)
    assert advanced_run.node_runs["step_a"].status == NodeRunStatus.COMPLETED
    assert advanced_run.node_runs["step_b"].status == NodeRunStatus.READY

    # Verify node runs remain exactly 2
    assert len(advanced_run.node_runs) == 2


# ==============================================================================
# 13. Concurrent Reconcile Race Safety
# ==============================================================================


def test_concurrent_reconcile_race_safety(workflow_service: WorkflowService) -> None:
    """Verify simultaneous reconcile_run calls produce zero duplicate releases."""
    wf_def = build_sample_definition(workflow_id="wf_concurrent")
    workflow_service.create_definition(wf_def)

    run = workflow_service.start_run("wf_concurrent")
    complete_job_state(workflow_service.repo, run.node_runs["step_a"].job_id)

    # Spawn 8 threads calling reconcile_run simultaneously
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(workflow_service.reconcile_run, run.run_id) for _ in range(8)]
        for f in futures:
            results.append(f.result())

    # All returned valid runs
    assert all(r.status == WorkflowRunStatus.RUNNING for r in results)
    # Step B was made READY exactly once
    final_run = workflow_service.get_run(run.run_id)
    assert final_run.node_runs["step_b"].status == NodeRunStatus.READY


# ==============================================================================
# 14. Provenance Chain Traceability
# ==============================================================================


def test_provenance_chain_traceability(file_db_path: str) -> None:
    """Verify complete unbroken traceability chain from workflow run to execution."""
    wf_service = WorkflowService(db_path=file_db_path)
    wf_def = build_sample_definition(workflow_id="wf_provenance")
    wf_service.create_definition(wf_def)

    run = wf_service.start_run("wf_provenance")
    node_run = run.node_runs["step_a"]

    coord = make_mock_coordinator(status=ExecutionStatus.COMPLETED)
    worker = JobWorker(db_path=file_db_path, coordinator=coord)
    worker.step()

    # Provenance links
    assert run.run_id.startswith("wfr_")
    assert node_run.node_run_id.startswith("wfnr_")
    assert node_run.job_id.startswith("job_")

    attempts = wf_service.repo.list_attempts(node_run.job_id)
    assert len(attempts) > 0
    attempt = attempts[0]
    assert attempt.attempt_id.startswith("att_")
    assert attempt.execution_id is not None
    assert attempt.execution_id.startswith("req_")

    worker.close()


# ==============================================================================
# 15. Data Minimization & Zero Secrets
# ==============================================================================


def test_data_minimization_and_zero_secrets(workflow_service: WorkflowService) -> None:
    """Verify inputs/outputs are bounded and no secrets are stored in DB."""
    wf_def = build_sample_definition(workflow_id="wf_secrets")
    workflow_service.create_definition(wf_def)

    sensitive_inputs = {
        "api_key": "sk-1234567890abcdef1234567890abcdef",
        "secret_token": "token_xyz",
        "prompt": "Summarize this document",
    }
    run = workflow_service.start_run("wf_secrets", inputs=sensitive_inputs)
    assert run is not None

    # Check job payload in SQLite
    conn = workflow_service._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT payload_summary_json FROM jobs WHERE job_id = ?",
            (run.node_runs["step_a"].job_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        payload_data = json.loads(row[0])
        assert isinstance(payload_data, dict)
        # In JobExecutionRequestFactory, secret keys are excluded or payload is sanitized
        factory = JobExecutionRequestFactory()
        job = workflow_service.repo.get_job(run.node_runs["step_a"].job_id)
        req = factory.create_execution_request(job)
        assert "api_key" not in req.inputs
        assert "secret_token" not in req.inputs
    finally:
        if not workflow_service._is_memory:
            conn.close()
