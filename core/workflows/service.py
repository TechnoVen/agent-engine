"""core/workflows/service.py

Canonical Workflow Service for Agent Engine (Task R4.8).
Part of Milestone R4 (Task R4.8 - Absorb Legacy Phase 7 Runtime).

Architecture & Guarantees:
- One Workflow Authority: WorkflowDefinition -> WorkflowRun -> canonical Jobs
  -> R4 Queue/Worker -> ExecutionCoordinator.
- Separation of Concerns: WorkflowService compiles DAGs, manages state, and observes
  durable job transitions. It NEVER directly executes model or tool calls.
- Durable Dependency Progression: Node jobs become READY only when all required upstream
  dependencies complete. Progression is restart-safe and multi-process race-free.
- R4.4 & R4.5 Reuse: Node retries reuse R4.4 durable backoff; node cancellation reuses R4.5 controls.
- Zero Secret Leakage: Inputs and outputs are bounded and sanitized.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from core.jobs.control import JobControlService
from core.jobs.exceptions import DuplicateQueueEntryError
from core.jobs.migrations import apply_job_migrations
from core.jobs.models import (
    Job,
    JobDependency,
    JobDependencyType,
    JobEvent,
    JobEventType,
    JobStatus,
    current_timestamp_iso,
    generate_job_id,
    sanitize_bounded_dict,
)

from core.jobs.queue import SQLiteJobQueue
from core.jobs.sqlite import SQLiteJobRepository
from core.safety.pending import (
    PendingOperationRegistry,
    compute_canonical_operation_digest,
)
from core.storage.sqlite import SQLiteBackend
from core.workflows.exceptions import (
    WorkflowNotFoundError,
    WorkflowRunNotFoundError,
    WorkflowValidationError,
)
from core.workflows.models import (
    NodeRunStatus,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowNodeType,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
    generate_node_run_id,
    generate_workflow_run_id,
)
from core.workflows.parser import WorkflowParser

logger = logging.getLogger("agent_engine.workflows.service")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOBS_DB_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")


class WorkflowService:
    """Authoritative service for canonical workflow definitions and DAG runs."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        storage: Optional[Any] = None,
        approval_registry: Optional[PendingOperationRegistry] = None,
        policy_engine: Optional[Any] = None,
    ):
        self.db_path = db_path or DEFAULT_JOBS_DB_PATH
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

        self.repo = SQLiteJobRepository(db_path=self.db_path)
        self.queue = SQLiteJobQueue(db_path=self.db_path)
        self.control_service = JobControlService(db_path=self.db_path)
        self.storage = storage or SQLiteBackend(db_path=self.db_path)
        self.approval_registry = approval_registry or PendingOperationRegistry(storage=self.storage)
        self.policy_engine = policy_engine

        # Apply migrations including Migration 009
        conn = self._get_connection()
        try:
            apply_job_migrations(conn)
        finally:
            if not self._is_memory:
                conn.close()

    def _is_policy_denied(
        self,
        node: Optional[WorkflowNode],
        inputs: Dict[str, Any],
        workflow_run_id: str,
    ) -> Tuple[bool, Optional[str]]:
        """Check if a gate node is authoritatively blocked or denied by safety policy."""
        if not node:
            return False, None

        # 1. Declarative node configuration denial
        if node.config.get("policy_denied") is True:
            return True, node.config.get("policy_reason", "Denied by workflow policy configuration")
        if str(node.config.get("policy_decision", "")).lower() in ("deny", "block"):
            return True, node.config.get("policy_reason", "Denied by workflow policy decision")
        if node.config.get("policy_block") is True:
            return True, node.config.get(
                "policy_reason", "Blocked by workflow policy configuration"
            )

        # 2. Central Guardrail PolicyEngine evaluation if configured
        if self.policy_engine:
            tool_name = f"workflow_gate:{node.id}"
            capability = node.config.get("capability", f"workflow_gate:{node.id}")
            try:
                decision = self.policy_engine.evaluate(
                    tool_name=tool_name,
                    tool_args=inputs,
                    context={
                        "session_id": workflow_run_id,
                        "execution_id": workflow_run_id,
                        "capability": capability,
                    },
                )
                if getattr(decision, "is_denied", False):
                    return True, getattr(decision, "reason", None) or "Denied by guardrail policy"
                if str(getattr(decision, "decision", "")).lower() in ("deny", "block"):
                    return True, getattr(decision, "reason", None) or "Denied by guardrail policy"
            except Exception as e:
                logger.warning("Policy evaluation error for gate '%s': %s", node.id, e)

        return False, None

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON;")
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn

    # --------------------------------------------------------------------------
    # Workflow Definition CRUD
    # --------------------------------------------------------------------------

    def create_definition(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        """Validate, store, and index a reusable workflow definition."""
        is_valid, errors = WorkflowParser.validate(definition)
        if not is_valid:
            raise WorkflowValidationError(f"Invalid workflow definition: {'; '.join(errors)}")

        definition_hash = definition.compute_definition_hash()
        now_iso = current_timestamp_iso()

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO workflow_definitions (
                            workflow_id, name, description, version, status,
                            definition_json, definition_hash, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(workflow_id) DO UPDATE SET
                            name = excluded.name,
                            description = excluded.description,
                            version = excluded.version,
                            status = excluded.status,
                            definition_json = excluded.definition_json,
                            definition_hash = excluded.definition_hash,
                            updated_at = excluded.updated_at
                        """,
                        (
                            definition.id,
                            definition.name,
                            definition.description,
                            definition.version,
                            definition.status.value,
                            json.dumps(definition.to_dict()),
                            definition_hash,
                            now_iso,
                            now_iso,
                        ),
                    )
                return definition
            finally:
                if not self._is_memory:
                    conn.close()

    def get_definition(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """Retrieve a stored workflow definition by identifier."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT definition_json FROM workflow_definitions WHERE workflow_id = ?",
                    (workflow_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = json.loads(row["definition_json"])
                return WorkflowDefinition.model_validate(data)
            finally:
                if not self._is_memory:
                    conn.close()

    def list_definitions(self, status: Optional[WorkflowStatus] = None) -> List[WorkflowDefinition]:
        """List stored workflow definitions optionally filtered by status."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if status is not None:
                    cursor.execute(
                        "SELECT definition_json FROM workflow_definitions WHERE status = ? ORDER BY created_at DESC",
                        (status.value,),
                    )
                else:
                    cursor.execute(
                        "SELECT definition_json FROM workflow_definitions ORDER BY created_at DESC"
                    )
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    data = json.loads(row["definition_json"])
                    result.append(WorkflowDefinition.model_validate(data))
                return result
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_definition(self, workflow_id: str) -> bool:
        """Delete a workflow definition by identifier.

        Hard-delete is ONLY permitted if no historical workflow runs exist.
        If runs exist, raises WorkflowValidationError to preserve audit and provenance history.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM workflow_runs WHERE workflow_id = ?",
                        (workflow_id,),
                    )
                    run_count = cursor.fetchone()[0]
                    if run_count > 0:
                        raise WorkflowValidationError(
                            f"Cannot delete workflow definition '{workflow_id}': "
                            f"{run_count} historical run(s) exist. Archive the definition instead."
                        )
                    cursor.execute(
                        "DELETE FROM workflow_definitions WHERE workflow_id = ?",
                        (workflow_id,),
                    )
                    return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def archive_definition(self, workflow_id: str) -> WorkflowDefinition:
        """Archive a workflow definition.

        Archived workflows remain queryable for audit provenance,
        but cannot be used to spawn new workflow runs.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT definition_json FROM workflow_definitions WHERE workflow_id = ?",
                        (workflow_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        raise WorkflowNotFoundError(
                            f"Workflow definition '{workflow_id}' not found."
                        )

                    data = json.loads(row["definition_json"])
                    data["status"] = WorkflowStatus.ARCHIVED.value
                    now_iso = current_timestamp_iso()

                    cursor.execute(
                        """
                        UPDATE workflow_definitions
                        SET status = ?, definition_json = ?, updated_at = ?
                        WHERE workflow_id = ?
                        """,
                        (WorkflowStatus.ARCHIVED.value, json.dumps(data), now_iso, workflow_id),
                    )
                    return WorkflowDefinition.model_validate(data)
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Template Binding & Resolution Utilities
    # --------------------------------------------------------------------------

    @staticmethod
    def resolve_binding(
        val: Any,
        workflow_inputs: Dict[str, Any],
        step_outputs: Dict[str, Dict[str, Any]],
    ) -> Any:
        """Resolve a variable reference or template expression from runtime context."""
        if not isinstance(val, str):
            return val

        trimmed = val.strip()

        # Handle direct references: $workflow.input.key, $inputs.key, ${inputs.key}, etc.
        if trimmed.startswith("$workflow.input."):
            key = trimmed[len("$workflow.input.") :]
            return workflow_inputs.get(key, val)
        if trimmed.startswith("$inputs."):
            key = trimmed[len("$inputs.") :]
            return workflow_inputs.get(key, val)
        if trimmed.startswith("${inputs.") and trimmed.endswith("}"):
            key = trimmed[len("${inputs.") : -1].strip()
            return workflow_inputs.get(key, val)
        if trimmed.startswith("${workflow.input.") and trimmed.endswith("}"):
            key = trimmed[len("${workflow.input.") : -1].strip()
            return workflow_inputs.get(key, val)

        import re

        pattern = r"\{\{\s*([^}]+)\s*\}\}"
        matches = re.findall(pattern, trimmed)
        if not matches:
            return val

        # If string is entirely one template expression, return raw typed value
        if len(matches) == 1 and trimmed == f"{{{{{matches[0]}}}}}":
            expr = matches[0].strip()
            if expr.startswith("$workflow.input."):
                return workflow_inputs.get(expr[len("$workflow.input.") :], "")
            if expr.startswith("$inputs."):
                return workflow_inputs.get(expr[len("$inputs.") :], "")
            if expr.startswith("inputs."):
                return workflow_inputs.get(expr[len("inputs.") :], "")
            parts = expr.split(".", 1)
            if len(parts) == 2 and parts[0] in step_outputs:
                return step_outputs[parts[0]].get(parts[1], "")

        # String substitution for mixed strings
        result = trimmed
        for expr in matches:
            clean_expr = expr.strip()
            replacement = ""
            if clean_expr.startswith("$workflow.input."):
                replacement = str(workflow_inputs.get(clean_expr[len("$workflow.input.") :], ""))
            elif clean_expr.startswith("$inputs."):
                replacement = str(workflow_inputs.get(clean_expr[len("$inputs.") :], ""))
            elif clean_expr.startswith("inputs."):
                replacement = str(workflow_inputs.get(clean_expr[len("inputs.") :], ""))
            else:
                parts = clean_expr.split(".", 1)
                if len(parts) == 2 and parts[0] in step_outputs:
                    replacement = str(step_outputs[parts[0]].get(parts[1], ""))
            result = result.replace(f"{{{{{expr}}}}}", replacement)

        return result

    def resolve_node_inputs(
        self,
        node: WorkflowNode,
        workflow_inputs: Dict[str, Any],
        step_outputs: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Resolve declared node inputs using available context."""
        resolved: Dict[str, Any] = {}
        for key, val in node.inputs.items():
            resolved[key] = self.resolve_binding(val, workflow_inputs, step_outputs)
        return resolved

    # --------------------------------------------------------------------------
    # Workflow Execution & DAG Coordination
    # --------------------------------------------------------------------------

    def start_run(
        self,
        workflow_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> WorkflowRun:
        """Compile workflow DAG into canonical Jobs and launch execution."""
        definition = self.get_definition(workflow_id)
        if not definition:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found.")
        if definition.status == WorkflowStatus.ARCHIVED:
            raise WorkflowValidationError(
                f"Cannot start run: Workflow '{workflow_id}' is archived."
            )

        is_valid, errors = WorkflowParser.validate(definition)
        if not is_valid:
            raise WorkflowValidationError(f"Invalid workflow graph: {'; '.join(errors)}")

        definition_hash = definition.compute_definition_hash()
        run_id = run_id or generate_workflow_run_id()
        workflow_inputs = sanitize_bounded_dict(inputs or {})
        now_iso = current_timestamp_iso()

        # Compute graph in-degrees
        in_degrees: Dict[str, int] = {n.id: 0 for n in definition.nodes}
        for edge in definition.edges:
            if edge.target in in_degrees:
                in_degrees[edge.target] += 1

        node_job_map: Dict[str, str] = {}
        node_runs_map: Dict[str, WorkflowNodeRun] = {}
        jobs_to_insert: List[Job] = []
        dependencies_to_insert: List[JobDependency] = []
        root_job_ids_to_enqueue: List[str] = []

        # Prepare Jobs and NodeRuns for all nodes
        for node in definition.nodes:
            has_incoming = in_degrees[node.id] > 0
            node_run_id = generate_node_run_id()

            if node.type == WorkflowNodeType.GATE:
                # GATE is control-plane state, NOT an execution Job!
                job_id = None
                if has_incoming:
                    initial_node_status = NodeRunStatus.BLOCKED
                    resolved_inputs = {}
                    approval_id = None
                    operation_digest = None
                    suspended_at = None
                    node_error = None
                else:
                    resolved_inputs = sanitize_bounded_dict(
                        self.resolve_node_inputs(node, workflow_inputs, {})
                    )
                    is_denied, reason = self._is_policy_denied(node, resolved_inputs, run_id)
                    if is_denied:
                        initial_node_status = NodeRunStatus.FAILED
                        approval_id = None
                        operation_digest = None
                        suspended_at = None
                        node_error = reason or "Policy denied gate execution"
                    else:
                        initial_node_status = NodeRunStatus.WAITING_APPROVAL
                        tool_name = f"workflow_gate:{workflow_id}:{node.id}"
                        capability = node.config.get("capability", f"workflow_gate:{node.id}")
                        actor = node.config.get("actor", "local_operator")
                        operation_digest = compute_canonical_operation_digest(
                            tool_name=tool_name,
                            tool_args=resolved_inputs,
                            capability=capability,
                            execution_id=run_id,
                            actor=actor,
                        )
                        ttl = float(node.config.get("ttl_seconds", 3600.0))
                        pending_op = self.approval_registry.register_operation(
                            tool_name=tool_name,
                            tool_args=resolved_inputs,
                            risk_level=node.config.get("risk_level", "high"),
                            risk_score=float(node.config.get("risk_score", 0.9)),
                            session_id=run_id,
                            execution_id=run_id,
                            reason=node.config.get(
                                "reason", f"Approval required for gate '{node.name}'"
                            ),
                            suggestion=node.config.get("suggestion"),
                            diff=node.config.get("diff"),
                            ttl_seconds=ttl,
                            actor=actor,
                            capability=capability,
                        )
                        approval_id = pending_op.operation_id
                        suspended_at = now_iso
                        node_error = None

                node_run = WorkflowNodeRun(
                    node_run_id=node_run_id,
                    workflow_run_id=run_id,
                    node_id=node.id,
                    node_type=node.type,
                    job_id=None,
                    status=initial_node_status,
                    approval_id=approval_id,
                    operation_digest=operation_digest,
                    suspended_at=suspended_at,
                    inputs=resolved_inputs,
                    outputs={},
                    error=node_error,
                    started_at=now_iso,
                )
                node_runs_map[node.id] = node_run
            else:
                job_id = generate_job_id()
                node_job_map[node.id] = job_id
                initial_job_status = JobStatus.BLOCKED if has_incoming else JobStatus.READY
                initial_node_status = NodeRunStatus.BLOCKED if has_incoming else NodeRunStatus.READY

                resolved_inputs = (
                    sanitize_bounded_dict(self.resolve_node_inputs(node, workflow_inputs, {}))
                    if not has_incoming
                    else {}
                )

                job = Job(
                    job_id=job_id,
                    job_type="workflow_step",
                    status=initial_job_status,
                    payload_summary={
                        "workflow_id": workflow_id,
                        "workflow_run_id": run_id,
                        "node_id": node.id,
                        "node_run_id": node_run_id,
                        "node_name": node.name,
                        "node_type": node.type.value,
                        "config": node.config,
                        "inputs": resolved_inputs,
                        "outputs": node.outputs,
                    },
                    project_id=definition.metadata.get("project_id"),
                    created_by="authority:workflow_service",
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                jobs_to_insert.append(job)

                node_run = WorkflowNodeRun(
                    node_run_id=node_run_id,
                    workflow_run_id=run_id,
                    node_id=node.id,
                    node_type=node.type,
                    job_id=job_id,
                    status=initial_node_status,
                    inputs=resolved_inputs,
                    outputs={},
                    started_at=now_iso,
                )
                node_runs_map[node.id] = node_run

                if not has_incoming:
                    root_job_ids_to_enqueue.append(job_id)

        # Prepare dependencies for all edges
        for edge in definition.edges:
            source_job = node_job_map.get(edge.source)
            target_job = node_job_map.get(edge.target)
            if source_job and target_job:
                dependencies_to_insert.append(
                    JobDependency(
                        job_id=target_job,
                        depends_on_job_id=source_job,
                        dependency_type=JobDependencyType.COMPLETION,
                        created_at=now_iso,
                    )
                )

        # 1. Insert jobs and dependencies into JobRepository so foreign key job_id is satisfied
        for job in jobs_to_insert:
            self.repo.create_job(job)

        for dep in dependencies_to_insert:
            self.repo.add_dependency(dep)

        # 2. Execute durable transactional compilation of workflow run and node runs
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # Determine initial workflow run status
                if any(nr.status == NodeRunStatus.FAILED for nr in node_runs_map.values()):
                    initial_run_status = WorkflowRunStatus.FAILED.value
                elif any(
                    nr.status == NodeRunStatus.WAITING_APPROVAL for nr in node_runs_map.values()
                ):
                    initial_run_status = WorkflowRunStatus.WAITING_APPROVAL.value
                else:
                    initial_run_status = WorkflowRunStatus.RUNNING.value

                # Insert workflow run
                cursor.execute(
                    """
                    INSERT INTO workflow_runs (
                        workflow_run_id, workflow_id, definition_hash, definition_snapshot_json,
                        status, inputs_json, outputs_json, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '{}', NULL, ?, ?)
                    """,
                    (
                        run_id,
                        workflow_id,
                        definition_hash,
                        json.dumps(definition.to_dict()),
                        initial_run_status,
                        json.dumps(workflow_inputs),
                        now_iso,
                        now_iso,
                    ),
                )

                # Insert node runs
                for nr in node_runs_map.values():
                    cursor.execute(
                        """
                        INSERT INTO workflow_node_runs (
                            node_run_id, workflow_run_id, node_id, node_type, job_id,
                            status, inputs_json, outputs_json, error, started_at, updated_at,
                            approval_id, operation_digest, suspended_at, resolved_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            nr.node_run_id,
                            nr.workflow_run_id,
                            nr.node_id,
                            nr.node_type.value,
                            nr.job_id,
                            nr.status.value,
                            json.dumps(nr.inputs),
                            nr.error,
                            nr.started_at,
                            nr.started_at,
                            nr.approval_id,
                            nr.operation_digest,
                            nr.suspended_at,
                            nr.resolved_at,
                        ),
                    )

                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

        # 3. Enqueue ready root jobs into persistent local queue
        for r_job_id in root_job_ids_to_enqueue:
            try:
                self.queue.enqueue(r_job_id)
            except DuplicateQueueEntryError:
                pass

        # Record audit event if jobs exist
        if jobs_to_insert:
            self.repo.append_event(
                JobEvent(
                    job_id=jobs_to_insert[0].job_id,
                    event_type=JobEventType.WORKFLOW_RUN_CREATED,
                    metadata={
                        "workflow_run_id": run_id,
                        "workflow_id": workflow_id,
                        "nodes_count": len(definition.nodes),
                        "edges_count": len(definition.edges),
                    },
                )
            )

        logger.info("Launched workflow run '%s' for workflow '%s'", run_id, workflow_id)
        return self.get_run(run_id)

    def reconcile_run(self, workflow_run_id: str) -> WorkflowRun:
        """Observe durable job outcomes, release ready dependencies, and advance workflow."""
        with self._lock:
            run = self.get_run(workflow_run_id)
            if not run:
                raise WorkflowRunNotFoundError(f"Workflow run '{workflow_run_id}' not found.")

            if run.status in (
                WorkflowRunStatus.COMPLETED,
                WorkflowRunStatus.FAILED,
                WorkflowRunStatus.CANCELLED,
            ):
                return run

            definition = WorkflowDefinition.model_validate(run.definition_snapshot)
            node_map = {n.id: n for n in definition.nodes}

            # Step outputs collector
            step_outputs: Dict[str, Dict[str, Any]] = {
                nid: nr.outputs for nid, nr in run.node_runs.items() if nr.outputs
            }

            now_iso = current_timestamp_iso()
            any_failed = False
            newly_ready_jobs: List[str] = []

            # Stage 1: Check active job outcomes
            completed_job_nodes: Dict[str, Dict[str, Any]] = {}
            failed_job_nodes: List[str] = []
            cancelled_job_nodes: List[str] = []
            running_job_nodes: List[str] = []

            for node_id, nr in run.node_runs.items():
                if not nr.job_id:
                    continue
                job = self.repo.get_job(nr.job_id)
                if not job:
                    continue
                if job.status == JobStatus.COMPLETED and nr.status != NodeRunStatus.COMPLETED:
                    node_def = node_map.get(node_id)
                    outs = self._derive_node_outputs(node_def, nr.job_id, step_outputs)
                    step_outputs[node_id] = outs
                    completed_job_nodes[node_id] = outs
                elif job.status == JobStatus.FAILED and nr.status != NodeRunStatus.FAILED:
                    failed_job_nodes.append(node_id)
                    any_failed = True
                elif job.status == JobStatus.CANCELLED and nr.status != NodeRunStatus.CANCELLED:
                    cancelled_job_nodes.append(node_id)
                elif job.status == JobStatus.RUNNING and nr.status != NodeRunStatus.RUNNING:
                    running_job_nodes.append(node_id)

            # Stage 2: Evaluate WAITING_APPROVAL GATE nodes (without holding DB lock)
            gate_failed: Dict[str, str] = {}
            gate_invalidated_regs: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
            gate_cas_consume: List[str] = []

            for node_id, nr in run.node_runs.items():
                if (
                    nr.node_type != WorkflowNodeType.GATE
                    or nr.status != NodeRunStatus.WAITING_APPROVAL
                ):
                    continue
                node_def = node_map.get(node_id)
                if not node_def:
                    continue

                # Policy denial check
                is_denied, reason = self._is_policy_denied(node_def, nr.inputs, workflow_run_id)
                if is_denied:
                    gate_failed[node_id] = reason or "Policy denied gate execution"
                    any_failed = True
                    continue

                # Input invalidation check
                curr_inputs = sanitize_bounded_dict(
                    self.resolve_node_inputs(node_def, run.inputs, step_outputs)
                )
                tool_name = f"workflow_gate:{run.workflow_id}:{node_def.id}"
                capability = node_def.config.get("capability", f"workflow_gate:{node_def.id}")
                actor = node_def.config.get("actor", "local_operator")
                expected_digest = compute_canonical_operation_digest(
                    tool_name=tool_name,
                    tool_args=curr_inputs,
                    capability=capability,
                    execution_id=workflow_run_id,
                    actor=actor,
                )

                if nr.operation_digest and nr.operation_digest != expected_digest:
                    if nr.approval_id:
                        try:
                            self.approval_registry.reject_operation(
                                nr.approval_id, actor="system", reason="Invalidated: inputs changed"
                            )
                        except Exception:
                            pass
                    ttl = float(node_def.config.get("ttl_seconds", 3600.0))
                    new_op = self.approval_registry.register_operation(
                        tool_name=tool_name,
                        tool_args=curr_inputs,
                        risk_level=node_def.config.get("risk_level", "high"),
                        risk_score=float(node_def.config.get("risk_score", 0.9)),
                        session_id=workflow_run_id,
                        execution_id=workflow_run_id,
                        reason=node_def.config.get(
                            "reason", f"Approval required for gate '{node_def.name}'"
                        ),
                        suggestion=node_def.config.get("suggestion"),
                        diff=node_def.config.get("diff"),
                        ttl_seconds=ttl,
                        actor=actor,
                        capability=capability,
                    )
                    gate_invalidated_regs[node_id] = (
                        new_op.operation_id,
                        expected_digest,
                        curr_inputs,
                    )
                    continue

                # Check approval status
                if not nr.approval_id:
                    continue
                op = self.approval_registry.get_operation(nr.approval_id)
                if not op:
                    continue
                if op.status == "rejected":
                    gate_failed[node_id] = op.decision_reason or "Gate rejected by operator"
                    any_failed = True
                elif op.status == "approved":
                    gate_cas_consume.append(node_id)

            # Stage 3: Check BLOCKED nodes (without holding DB lock)
            projected_status: Dict[str, NodeRunStatus] = {
                nid: nr.status for nid, nr in run.node_runs.items()
            }
            for nid in completed_job_nodes:
                projected_status[nid] = NodeRunStatus.COMPLETED
            for nid in failed_job_nodes:
                projected_status[nid] = NodeRunStatus.FAILED
            for nid in cancelled_job_nodes:
                projected_status[nid] = NodeRunStatus.CANCELLED
            for nid in gate_failed:
                projected_status[nid] = NodeRunStatus.FAILED
            for nid in gate_cas_consume:
                projected_status[nid] = NodeRunStatus.COMPLETED

            blocked_skipped: Dict[str, str] = {}
            blocked_gate_waiting: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
            blocked_job_ready: Dict[str, Dict[str, Any]] = {}

            for node_id, nr in run.node_runs.items():
                if nr.status != NodeRunStatus.BLOCKED:
                    continue
                node_def = node_map.get(node_id)
                if not node_def:
                    continue

                incoming_edges = [e for e in definition.edges if e.target == node_id]
                all_prereqs_completed = True
                any_prereq_failed_or_cancelled = False
                condition_satisfied = True

                for edge in incoming_edges:
                    p_status = projected_status.get(edge.source)
                    if p_status != NodeRunStatus.COMPLETED:
                        all_prereqs_completed = False
                    if p_status in (
                        NodeRunStatus.FAILED,
                        NodeRunStatus.CANCELLED,
                        NodeRunStatus.SKIPPED,
                    ):
                        any_prereq_failed_or_cancelled = True
                    if edge.condition:
                        source_outs = step_outputs.get(edge.source, {})
                        source_branch = str(
                            source_outs.get("branch", source_outs.get("result", ""))
                        ).lower()
                        if source_branch != str(edge.condition).lower():
                            condition_satisfied = False

                if any_prereq_failed_or_cancelled:
                    blocked_skipped[node_id] = "Prerequisite branch failed or cancelled"
                    projected_status[node_id] = NodeRunStatus.SKIPPED
                    continue
                if not condition_satisfied:
                    blocked_skipped[node_id] = "Branch condition not taken"
                    projected_status[node_id] = NodeRunStatus.SKIPPED
                    continue
                if all_prereqs_completed and condition_satisfied:
                    resolved_inputs = sanitize_bounded_dict(
                        self.resolve_node_inputs(node_def, run.inputs, step_outputs)
                    )
                    if node_def.type == WorkflowNodeType.GATE:
                        is_denied, reason = self._is_policy_denied(
                            node_def, resolved_inputs, workflow_run_id
                        )
                        if is_denied:
                            blocked_skipped[node_id] = reason or "Policy denied gate execution"
                            gate_failed[node_id] = reason or "Policy denied gate execution"
                            projected_status[node_id] = NodeRunStatus.FAILED
                            any_failed = True
                        else:
                            tool_name = f"workflow_gate:{run.workflow_id}:{node_def.id}"
                            capability = node_def.config.get(
                                "capability", f"workflow_gate:{node_def.id}"
                            )
                            actor = node_def.config.get("actor", "local_operator")
                            op_digest = compute_canonical_operation_digest(
                                tool_name=tool_name,
                                tool_args=resolved_inputs,
                                capability=capability,
                                execution_id=workflow_run_id,
                                actor=actor,
                            )
                            ttl = float(node_def.config.get("ttl_seconds", 3600.0))
                            pending_op = self.approval_registry.register_operation(
                                tool_name=tool_name,
                                tool_args=resolved_inputs,
                                risk_level=node_def.config.get("risk_level", "high"),
                                risk_score=float(node_def.config.get("risk_score", 0.9)),
                                session_id=workflow_run_id,
                                execution_id=workflow_run_id,
                                reason=node_def.config.get(
                                    "reason", f"Approval required for gate '{node_def.name}'"
                                ),
                                suggestion=node_def.config.get("suggestion"),
                                diff=node_def.config.get("diff"),
                                ttl_seconds=ttl,
                                actor=actor,
                                capability=capability,
                            )
                            blocked_gate_waiting[node_id] = (
                                pending_op.operation_id,
                                op_digest,
                                resolved_inputs,
                            )
                            projected_status[node_id] = NodeRunStatus.WAITING_APPROVAL
                    else:
                        blocked_job_ready[node_id] = resolved_inputs
                        projected_status[node_id] = NodeRunStatus.READY

            # Stage 4: Apply mutations atomically in SQLite
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                for nid, outs in completed_job_nodes.items():
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, outputs_json = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (
                            NodeRunStatus.COMPLETED.value,
                            json.dumps(outs),
                            now_iso,
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )

                for nid in failed_job_nodes:
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, error = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (
                            NodeRunStatus.FAILED.value,
                            "Underlying job failed",
                            now_iso,
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )

                for nid in cancelled_job_nodes:
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, error = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (
                            NodeRunStatus.CANCELLED.value,
                            "Underlying job cancelled",
                            now_iso,
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )

                for nid in running_job_nodes:
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (NodeRunStatus.RUNNING.value, now_iso, workflow_run_id, nid),
                    )

                for nid, reason in gate_failed.items():
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, error = ?, resolved_at = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (
                            NodeRunStatus.FAILED.value,
                            reason,
                            now_iso,
                            now_iso,
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )

                for nid, (app_id, digest, inputs) in gate_invalidated_regs.items():
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET approval_id = ?, operation_digest = ?, inputs_json = ?, suspended_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (
                            app_id,
                            digest,
                            json.dumps(inputs),
                            now_iso,
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )

                for nid in gate_cas_consume:
                    nr = run.node_runs[nid]
                    node_def = node_map.get(nid)
                    now_time = time.time()
                    cursor.execute(
                        """
                        UPDATE approvals
                        SET status = 'consumed', consumed_at = ?
                        WHERE approval_id = ? AND status = 'approved' AND expires_at > ?
                        """,
                        (now_time, nr.approval_id, now_time),
                    )
                    if cursor.rowcount == 1:
                        if nr.approval_id in self.approval_registry._operations:
                            self.approval_registry._operations[nr.approval_id].status = "consumed"
                            self.approval_registry._operations[
                                nr.approval_id
                            ].consumed_at = now_time
                        outs = self._derive_node_outputs(node_def, None, step_outputs)
                        step_outputs[nid] = outs
                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, outputs_json = ?, resolved_at = ?, completed_at = ?, updated_at = ?
                            WHERE workflow_run_id = ? AND node_id = ?
                            """,
                            (
                                NodeRunStatus.COMPLETED.value,
                                json.dumps(outs),
                                now_iso,
                                now_iso,
                                now_iso,
                                workflow_run_id,
                                nid,
                            ),
                        )
                    else:
                        projected_status[nid] = NodeRunStatus.WAITING_APPROVAL

                for nid, reason in blocked_skipped.items():
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, error = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (
                            NodeRunStatus.SKIPPED.value,
                            reason,
                            now_iso,
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )

                for nid, (app_id, digest, inputs) in blocked_gate_waiting.items():
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, approval_id = ?, operation_digest = ?, inputs_json = ?, suspended_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ?
                        """,
                        (
                            NodeRunStatus.WAITING_APPROVAL.value,
                            app_id,
                            digest,
                            json.dumps(inputs),
                            now_iso,
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )

                for nid, inputs in blocked_job_ready.items():
                    nr = run.node_runs[nid]
                    if nr.job_id:
                        cursor.execute(
                            "SELECT payload_summary_json FROM jobs WHERE job_id = ?",
                            (nr.job_id,),
                        )
                        j_row = cursor.fetchone()
                        if j_row:
                            payload_sum = json.loads(j_row["payload_summary_json"])
                            payload_sum["inputs"] = inputs
                            cursor.execute(
                                "UPDATE jobs SET payload_summary_json = ?, updated_at = ? WHERE job_id = ?",
                                (json.dumps(payload_sum), now_iso, nr.job_id),
                            )
                    cursor.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, inputs_json = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND node_id = ? AND status = 'blocked'
                        """,
                        (
                            NodeRunStatus.READY.value,
                            json.dumps(inputs),
                            now_iso,
                            workflow_run_id,
                            nid,
                        ),
                    )
                    if cursor.rowcount > 0 and nr.job_id:
                        newly_ready_jobs.append(nr.job_id)

                has_failed = any_failed or any(
                    status == NodeRunStatus.FAILED for status in projected_status.values()
                )
                has_waiting = any(
                    status == NodeRunStatus.WAITING_APPROVAL for status in projected_status.values()
                )
                all_terminal = all(
                    status
                    in (
                        NodeRunStatus.COMPLETED,
                        NodeRunStatus.FAILED,
                        NodeRunStatus.CANCELLED,
                        NodeRunStatus.SKIPPED,
                    )
                    for status in projected_status.values()
                )

                if has_failed:
                    cursor.execute(
                        """
                        UPDATE workflow_runs
                        SET status = ?, error = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ?
                        """,
                        (
                            WorkflowRunStatus.FAILED.value,
                            "One or more nodes failed",
                            now_iso,
                            now_iso,
                            workflow_run_id,
                        ),
                    )
                elif all_terminal:
                    final_outputs: Dict[str, Any] = {}
                    for nid, outs in step_outputs.items():
                        final_outputs[nid] = outs
                        for k, v in outs.items():
                            if k not in final_outputs:
                                final_outputs[k] = v
                    cursor.execute(
                        """
                        UPDATE workflow_runs
                        SET status = ?, outputs_json = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ?
                        """,
                        (
                            WorkflowRunStatus.COMPLETED.value,
                            json.dumps(final_outputs),
                            now_iso,
                            now_iso,
                            workflow_run_id,
                        ),
                    )
                elif has_waiting:
                    cursor.execute(
                        "UPDATE workflow_runs SET status = ?, updated_at = ? WHERE workflow_run_id = ?",
                        (WorkflowRunStatus.WAITING_APPROVAL.value, now_iso, workflow_run_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE workflow_runs SET status = ?, updated_at = ? WHERE workflow_run_id = ?",
                        (WorkflowRunStatus.RUNNING.value, now_iso, workflow_run_id),
                    )

                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

            # Enqueue newly ready jobs
            for r_job_id in newly_ready_jobs:
                self.repo.update_state(r_job_id, JobStatus.READY)
                try:
                    self.queue.enqueue(r_job_id)
                except DuplicateQueueEntryError:
                    pass
                self.repo.append_event(
                    JobEvent(
                        job_id=r_job_id,
                        event_type=JobEventType.WORKFLOW_NODE_RELEASED,
                        metadata={"workflow_run_id": workflow_run_id},
                    )
                )

            return self.get_run(workflow_run_id)

    def _derive_node_outputs(
        self,
        node_def: Optional[WorkflowNode],
        job_id: Optional[str],
        step_outputs: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Derive standard node outputs based on node type and execution context."""
        if not node_def:
            return {"job_id": job_id, "status": "completed"}

        outputs: Dict[str, Any] = {}
        if node_def.type == WorkflowNodeType.GATE:
            outputs = {
                "status": "approved",
                "node_id": node_def.id,
                "approved": True,
            }
            for out_name in node_def.outputs:
                outputs[out_name] = f"approved_{node_def.id}_{out_name}"
            return sanitize_bounded_dict(outputs)

        if node_def.type == WorkflowNodeType.CONDITION:
            expr = node_def.config.get("expression", "true")
            resolved_expr = self.resolve_binding(expr, {}, step_outputs)
            condition_met = True
            if "==" in resolved_expr:
                parts = [s.strip().strip("'\"") for s in resolved_expr.split("==", 1)]
                condition_met = parts[0] == parts[1]
            elif resolved_expr.lower() in ("false", "0", "no"):
                condition_met = False

            branch = "true" if condition_met else "false"
            return {"condition_result": condition_met, "branch": branch}

        for out_name in node_def.outputs:
            outputs[out_name] = f"result_{node_def.id}_{out_name}"

        outputs["status"] = "success"
        outputs["node_id"] = node_def.id
        if job_id:
            outputs["job_id"] = job_id
        return sanitize_bounded_dict(outputs)

    def cancel_run(self, workflow_run_id: str, reason: str = "Operator cancelled") -> WorkflowRun:
        """Cancel an in-progress workflow run and all outstanding active jobs/approvals."""
        run = self.get_run(workflow_run_id)
        if not run:
            raise WorkflowRunNotFoundError(f"Workflow run '{workflow_run_id}' not found.")

        if run.status in (
            WorkflowRunStatus.COMPLETED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
        ):
            return run

        now_iso = current_timestamp_iso()

        # Cancel all outstanding jobs and reject waiting approvals
        for nr in run.node_runs.values():
            if nr.status in (
                NodeRunStatus.READY,
                NodeRunStatus.RUNNING,
                NodeRunStatus.BLOCKED,
                NodeRunStatus.WAITING_APPROVAL,
            ):
                if nr.job_id:
                    try:
                        self.control_service.cancel_job(nr.job_id, reason=reason)
                    except Exception:
                        pass
                if nr.approval_id:
                    try:
                        self.approval_registry.reject_operation(
                            nr.approval_id, actor="system:workflow_service", reason=reason
                        )
                    except Exception:
                        pass

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        UPDATE workflow_runs
                        SET status = ?, error = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ?
                        """,
                        (
                            WorkflowRunStatus.CANCELLED.value,
                            reason,
                            now_iso,
                            now_iso,
                            workflow_run_id,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE workflow_node_runs
                        SET status = ?, error = ?, completed_at = ?, updated_at = ?
                        WHERE workflow_run_id = ? AND status IN ('ready', 'running', 'blocked', 'pending', 'waiting_approval')
                        """,
                        (
                            NodeRunStatus.CANCELLED.value,
                            reason,
                            now_iso,
                            now_iso,
                            workflow_run_id,
                        ),
                    )
            finally:
                if not self._is_memory:
                    conn.close()

        logger.info("Cancelled workflow run '%s' (reason: %s)", workflow_run_id, reason)
        return self.get_run(workflow_run_id)

    def approve_gate(
        self,
        workflow_run_id: str,
        node_id: str,
        actor: str = "local_operator",
    ) -> WorkflowRun:
        """Authoritatively approve a waiting HITL gate node and advance DAG progression."""
        with self._lock:
            run = self.get_run(workflow_run_id)
            if not run:
                raise WorkflowRunNotFoundError(f"Workflow run '{workflow_run_id}' not found.")

            nr = run.node_runs.get(node_id)
            if not nr:
                raise WorkflowValidationError(
                    f"Node '{node_id}' not found in run '{workflow_run_id}'."
                )

            if nr.node_type != WorkflowNodeType.GATE:
                raise WorkflowValidationError(
                    f"Node '{node_id}' is of type '{nr.node_type}', not a GATE."
                )

            definition = WorkflowDefinition.model_validate(run.definition_snapshot)
            node_map = {n.id: n for n in definition.nodes}
            node_def = node_map.get(node_id)
            if not node_def:
                raise WorkflowValidationError(f"Definition for node '{node_id}' not found.")

            # Policy denial cannot be overridden by human approval!
            is_denied, reason = self._is_policy_denied(node_def, nr.inputs, workflow_run_id)
            if is_denied:
                raise WorkflowValidationError(
                    f"Policy denial cannot be overridden by human approval: {reason}"
                )

            if nr.status != NodeRunStatus.WAITING_APPROVAL:
                raise WorkflowValidationError(
                    f"Gate '{node_id}' is in status '{nr.status}', not waiting for approval."
                )

            if not nr.approval_id:
                raise WorkflowValidationError(f"Gate '{node_id}' has no associated approval_id.")

            # Approve via central approval registry
            self.approval_registry.approve_operation(
                operation_id=nr.approval_id,
                actor=actor,
                execution_id=workflow_run_id,
            )

        # Reconcile workflow run to advance gate and release dependents
        return self.reconcile_run(workflow_run_id)

    def reject_gate(
        self,
        workflow_run_id: str,
        node_id: str,
        actor: str = "local_operator",
        reason: str = "Rejected by operator",
    ) -> WorkflowRun:
        """Authoritatively reject a waiting HITL gate node and terminate branch."""
        with self._lock:
            run = self.get_run(workflow_run_id)
            if not run:
                raise WorkflowRunNotFoundError(f"Workflow run '{workflow_run_id}' not found.")

            nr = run.node_runs.get(node_id)
            if not nr:
                raise WorkflowValidationError(
                    f"Node '{node_id}' not found in run '{workflow_run_id}'."
                )

            if nr.node_type != WorkflowNodeType.GATE:
                raise WorkflowValidationError(
                    f"Node '{node_id}' is of type '{nr.node_type}', not a GATE."
                )

            if nr.status != NodeRunStatus.WAITING_APPROVAL:
                raise WorkflowValidationError(
                    f"Gate '{node_id}' is in status '{nr.status}', not waiting for approval."
                )

            if not nr.approval_id:
                raise WorkflowValidationError(f"Gate '{node_id}' has no associated approval_id.")

            self.approval_registry.reject_operation(
                operation_id=nr.approval_id,
                actor=actor,
                reason=reason,
            )

        return self.reconcile_run(workflow_run_id)

    def get_run(self, workflow_run_id: str) -> Optional[WorkflowRun]:
        """Retrieve complete state of a workflow run including all node run details."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT workflow_run_id, workflow_id, definition_hash, definition_snapshot_json,
                           status, inputs_json, outputs_json, error, created_at, completed_at
                    FROM workflow_runs WHERE workflow_run_id = ?
                    """,
                    (workflow_run_id,),
                )
                run_row = cursor.fetchone()
                if not run_row:
                    return None

                cursor.execute(
                    """
                    SELECT node_run_id, workflow_run_id, node_id, node_type, job_id,
                           status, inputs_json, outputs_json, error, started_at, completed_at,
                           approval_id, operation_digest, suspended_at, resolved_at
                    FROM workflow_node_runs WHERE workflow_run_id = ?
                    ORDER BY started_at ASC
                    """,
                    (workflow_run_id,),
                )
                node_rows = cursor.fetchall()

                node_runs: Dict[str, WorkflowNodeRun] = {}
                for nr_row in node_rows:
                    row_keys = nr_row.keys() if hasattr(nr_row, "keys") else []
                    node_runs[nr_row["node_id"]] = WorkflowNodeRun(
                        node_run_id=nr_row["node_run_id"],
                        workflow_run_id=nr_row["workflow_run_id"],
                        node_id=nr_row["node_id"],
                        node_type=WorkflowNodeType(nr_row["node_type"]),
                        job_id=nr_row["job_id"],
                        status=NodeRunStatus(nr_row["status"]),
                        approval_id=nr_row["approval_id"] if "approval_id" in row_keys else None,
                        operation_digest=(
                            nr_row["operation_digest"] if "operation_digest" in row_keys else None
                        ),
                        suspended_at=nr_row["suspended_at"] if "suspended_at" in row_keys else None,
                        resolved_at=nr_row["resolved_at"] if "resolved_at" in row_keys else None,
                        inputs=json.loads(nr_row["inputs_json"]),
                        outputs=json.loads(nr_row["outputs_json"]),
                        error=nr_row["error"],
                        started_at=nr_row["started_at"],
                        completed_at=nr_row["completed_at"],
                    )

                return WorkflowRun(
                    run_id=run_row["workflow_run_id"],
                    workflow_id=run_row["workflow_id"],
                    definition_hash=run_row["definition_hash"],
                    definition_snapshot=json.loads(run_row["definition_snapshot_json"]),
                    status=WorkflowRunStatus(run_row["status"]),
                    inputs=json.loads(run_row["inputs_json"]),
                    outputs=json.loads(run_row["outputs_json"]),
                    error=run_row["error"],
                    node_runs=node_runs,
                    created_at=run_row["created_at"],
                    completed_at=run_row["completed_at"],
                )
            finally:
                if not self._is_memory:
                    conn.close()

    def list_runs(self, workflow_id: Optional[str] = None, limit: int = 100) -> List[WorkflowRun]:
        """List workflow runs optionally filtered by workflow definition ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if workflow_id:
                    cursor.execute(
                        """
                        SELECT workflow_run_id FROM workflow_runs
                        WHERE workflow_id = ? ORDER BY created_at DESC LIMIT ?
                        """,
                        (workflow_id, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT workflow_run_id FROM workflow_runs
                        ORDER BY created_at DESC LIMIT ?
                        """,
                        (limit,),
                    )
                rows = cursor.fetchall()
                runs = []
                for row in rows:
                    r = self.get_run(row["workflow_run_id"])
                    if r:
                        runs.append(r)
                return runs
            finally:
                if not self._is_memory:
                    conn.close()
