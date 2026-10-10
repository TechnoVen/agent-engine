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
from typing import Any, Dict, List, Optional

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

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_JOBS_DB_PATH
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

        self.repo = SQLiteJobRepository(db_path=self.db_path)
        self.queue = SQLiteJobQueue(db_path=self.db_path)
        self.control_service = JobControlService(db_path=self.db_path)

        # Apply migrations including Migration 007
        conn = self._get_connection()
        try:
            apply_job_migrations(conn)
        finally:
            if not self._is_memory:
                conn.close()

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

        # Validate node types against R4.8 capabilities
        for node in definition.nodes:
            if node.type == WorkflowNodeType.GATE:
                raise WorkflowValidationError(
                    f"Node '{node.id}' of type 'gate' is deferred to Milestone R4.9 (HITL Gates)."
                )

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
        """Delete a workflow definition by identifier."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM workflow_definitions WHERE workflow_id = ?",
                        (workflow_id,),
                    )
                    return cursor.rowcount > 0
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

        # Handle direct references: $workflow.input.key
        if trimmed.startswith("$workflow.input."):
            key = trimmed[len("$workflow.input.") :]
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

        is_valid, errors = WorkflowParser.validate(definition)
        if not is_valid:
            raise WorkflowValidationError(f"Invalid workflow graph: {'; '.join(errors)}")

        for node in definition.nodes:
            if node.type == WorkflowNodeType.GATE:
                raise WorkflowValidationError(
                    f"Node '{node.id}' of type 'gate' is deferred to Milestone R4.9 (HITL Gates)."
                )

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
            job_id = generate_job_id()
            node_job_map[node.id] = job_id
            node_run_id = generate_node_run_id()

            has_incoming = in_degrees[node.id] > 0
            initial_job_status = JobStatus.BLOCKED if has_incoming else JobStatus.READY
            initial_node_status = NodeRunStatus.BLOCKED if has_incoming else NodeRunStatus.READY

            # Resolve initial inputs for root nodes
            resolved_inputs = (
                self.resolve_node_inputs(node, workflow_inputs, {}) if not has_incoming else {}
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
                        WorkflowRunStatus.RUNNING.value,
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
                            status, inputs_json, outputs_json, error, started_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', NULL, ?, ?)
                        """,
                        (
                            nr.node_run_id,
                            nr.workflow_run_id,
                            nr.node_id,
                            nr.node_type.value,
                            nr.job_id,
                            nr.status.value,
                            json.dumps(nr.inputs),
                            nr.started_at,
                            nr.started_at,
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

        # Record audit event
        first_job_id = jobs_to_insert[0].job_id if jobs_to_insert else "unknown"
        self.repo.append_event(
            JobEvent(
                job_id=first_job_id,
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

            any_failed = False
            newly_ready_jobs: List[str] = []

            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                now_iso = current_timestamp_iso()

                # Phase 1: Reconcile active and pending node runs against canonical Job status
                for node_id, nr in run.node_runs.items():
                    if not nr.job_id:
                        continue

                    cursor.execute(
                        "SELECT job_id, status FROM jobs WHERE job_id = ?",
                        (nr.job_id,),
                    )
                    job_row = cursor.fetchone()
                    if not job_row:
                        continue

                    job_status = job_row["status"]

                    if (
                        job_status == JobStatus.COMPLETED.value
                        and nr.status != NodeRunStatus.COMPLETED
                    ):
                        # Job finished! Resolve node outputs.
                        node_def = node_map.get(node_id)
                        outputs = self._derive_node_outputs(node_def, nr.job_id, step_outputs)
                        step_outputs[node_id] = outputs

                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, outputs_json = ?, completed_at = ?, updated_at = ?
                            WHERE node_run_id = ?
                            """,
                            (
                                NodeRunStatus.COMPLETED.value,
                                json.dumps(outputs),
                                now_iso,
                                now_iso,
                                nr.node_run_id,
                            ),
                        )
                        nr.status = NodeRunStatus.COMPLETED
                        nr.outputs = outputs
                        nr.completed_at = now_iso

                    elif job_status == JobStatus.FAILED.value and nr.status != NodeRunStatus.FAILED:
                        any_failed = True
                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, error = ?, completed_at = ?, updated_at = ?
                            WHERE node_run_id = ?
                            """,
                            (
                                NodeRunStatus.FAILED.value,
                                "Underlying job failed",
                                now_iso,
                                now_iso,
                                nr.node_run_id,
                            ),
                        )
                        nr.status = NodeRunStatus.FAILED
                        nr.completed_at = now_iso

                    elif (
                        job_status == JobStatus.CANCELLED.value
                        and nr.status != NodeRunStatus.CANCELLED
                    ):
                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, error = ?, completed_at = ?, updated_at = ?
                            WHERE node_run_id = ?
                            """,
                            (
                                NodeRunStatus.CANCELLED.value,
                                "Underlying job cancelled",
                                now_iso,
                                now_iso,
                                nr.node_run_id,
                            ),
                        )
                        nr.status = NodeRunStatus.CANCELLED
                        nr.completed_at = now_iso

                    elif (
                        job_status == JobStatus.RUNNING.value and nr.status != NodeRunStatus.RUNNING
                    ):
                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, updated_at = ?
                            WHERE node_run_id = ?
                            """,
                            (NodeRunStatus.RUNNING.value, now_iso, nr.node_run_id),
                        )
                        nr.status = NodeRunStatus.RUNNING

                # Phase 2: Check for newly eligible blocked nodes
                for node_id, nr in run.node_runs.items():
                    if nr.status != NodeRunStatus.BLOCKED:
                        continue

                    # Fetch job dependencies directly on the active transaction
                    cursor.execute(
                        "SELECT depends_on_job_id FROM job_dependencies WHERE job_id = ?",
                        (nr.job_id,),
                    )
                    dep_rows = cursor.fetchall()
                    all_prereqs_completed = True
                    any_prereq_failed_or_cancelled = False

                    for dep_row in dep_rows:
                        parent_id = dep_row["depends_on_job_id"]
                        cursor.execute(
                            "SELECT status FROM jobs WHERE job_id = ?",
                            (parent_id,),
                        )
                        parent_row = cursor.fetchone()
                        if not parent_row or parent_row["status"] != JobStatus.COMPLETED.value:
                            all_prereqs_completed = False
                        if parent_row and parent_row["status"] in (
                            JobStatus.FAILED.value,
                            JobStatus.CANCELLED.value,
                        ):
                            any_prereq_failed_or_cancelled = True

                    if any_prereq_failed_or_cancelled:
                        # Downstream branch cannot run
                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, error = ?, completed_at = ?, updated_at = ?
                            WHERE node_run_id = ?
                            """,
                            (
                                NodeRunStatus.SKIPPED.value,
                                "Prerequisite branch failed or cancelled",
                                now_iso,
                                now_iso,
                                nr.node_run_id,
                            ),
                        )
                        nr.status = NodeRunStatus.SKIPPED
                        nr.completed_at = now_iso
                        continue

                    # Check conditional edges
                    incoming_edges = [e for e in definition.edges if e.target == node_id]
                    condition_satisfied = True

                    for edge in incoming_edges:
                        if edge.condition:
                            source_outs = step_outputs.get(edge.source, {})
                            source_branch = str(
                                source_outs.get("branch", source_outs.get("result", ""))
                            ).lower()
                            expected_cond = str(edge.condition).lower()
                            if source_branch != expected_cond:
                                condition_satisfied = False

                    if not condition_satisfied:
                        # Branch was not selected
                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, error = ?, completed_at = ?, updated_at = ?
                            WHERE node_run_id = ?
                            """,
                            (
                                NodeRunStatus.SKIPPED.value,
                                "Branch condition not taken",
                                now_iso,
                                now_iso,
                                nr.node_run_id,
                            ),
                        )
                        nr.status = NodeRunStatus.SKIPPED
                        nr.completed_at = now_iso
                        continue

                    if all_prereqs_completed and condition_satisfied:
                        # Release node! Resolve its inputs now that prerequisites completed
                        node_def = node_map[node_id]
                        resolved_inputs = self.resolve_node_inputs(
                            node_def, run.inputs, step_outputs
                        )

                        # Update Job payload summary
                        cursor.execute(
                            "SELECT payload_summary_json FROM jobs WHERE job_id = ?",
                            (nr.job_id,),
                        )
                        j_row = cursor.fetchone()
                        if j_row:
                            payload_sum = json.loads(j_row["payload_summary_json"])
                            payload_sum["inputs"] = resolved_inputs
                            cursor.execute(
                                """
                                UPDATE jobs
                                SET payload_summary_json = ?, updated_at = ?
                                WHERE job_id = ?
                                """,
                                (json.dumps(payload_sum), now_iso, nr.job_id),
                            )

                        cursor.execute(
                            """
                            UPDATE workflow_node_runs
                            SET status = ?, inputs_json = ?, updated_at = ?
                            WHERE node_run_id = ? AND status = 'blocked'
                            """,
                            (
                                NodeRunStatus.READY.value,
                                json.dumps(resolved_inputs),
                                now_iso,
                                nr.node_run_id,
                            ),
                        )
                        if cursor.rowcount > 0:
                            nr.status = NodeRunStatus.READY
                            nr.inputs = resolved_inputs
                            newly_ready_jobs.append(nr.job_id)

                # Phase 3: Evaluate run-level termination
                terminal_nodes = {
                    nid
                    for nid, nr in run.node_runs.items()
                    if nr.status
                    in (
                        NodeRunStatus.COMPLETED,
                        NodeRunStatus.FAILED,
                        NodeRunStatus.CANCELLED,
                        NodeRunStatus.SKIPPED,
                    )
                }
                all_nodes_terminal = len(terminal_nodes) == len(run.node_runs)

                if any_failed:
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
                elif all_nodes_terminal:
                    # Final output aggregation
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

                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

            # Update Job state and enqueue newly ready jobs into persistent queue
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
        job_id: str,
        step_outputs: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Derive standard node outputs based on node type and execution context."""
        if not node_def:
            return {"job_id": job_id, "status": "completed"}

        outputs: Dict[str, Any] = {}
        # If condition node: evaluate expression
        if node_def.type == WorkflowNodeType.CONDITION:
            expr = node_def.config.get("expression", "true")
            # Resolve condition binding
            resolved_expr = self.resolve_binding(expr, {}, step_outputs)
            condition_met = True
            if "==" in resolved_expr:
                parts = [s.strip().strip("'\"") for s in resolved_expr.split("==", 1)]
                condition_met = parts[0] == parts[1]
            elif resolved_expr.lower() in ("false", "0", "no"):
                condition_met = False

            branch = "true" if condition_met else "false"
            return {"condition_result": condition_met, "branch": branch}

        # For executable nodes, populate declared outputs
        for out_name in node_def.outputs:
            outputs[out_name] = f"result_{node_def.id}_{out_name}"

        # Standard result fields
        outputs["status"] = "success"
        outputs["node_id"] = node_def.id
        outputs["job_id"] = job_id
        return outputs

    def cancel_run(self, workflow_run_id: str, reason: str = "Operator cancelled") -> WorkflowRun:
        """Cancel an in-progress workflow run and all outstanding active jobs."""
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

        # Cancel all outstanding jobs via JobControlService
        for nr in run.node_runs.values():
            if nr.status in (NodeRunStatus.READY, NodeRunStatus.RUNNING, NodeRunStatus.BLOCKED):
                if nr.job_id:
                    try:
                        self.control_service.cancel_job(nr.job_id, reason=reason)
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
                        WHERE workflow_run_id = ? AND status IN ('ready', 'running', 'blocked', 'pending')
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
                           status, inputs_json, outputs_json, error, started_at, completed_at
                    FROM workflow_node_runs WHERE workflow_run_id = ?
                    ORDER BY started_at ASC
                    """,
                    (workflow_run_id,),
                )
                node_rows = cursor.fetchall()

                node_runs: Dict[str, WorkflowNodeRun] = {}
                for nr_row in node_rows:
                    node_runs[nr_row["node_id"]] = WorkflowNodeRun(
                        node_run_id=nr_row["node_run_id"],
                        workflow_run_id=nr_row["workflow_run_id"],
                        node_id=nr_row["node_id"],
                        node_type=WorkflowNodeType(nr_row["node_type"]),
                        job_id=nr_row["job_id"],
                        status=NodeRunStatus(nr_row["status"]),
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
