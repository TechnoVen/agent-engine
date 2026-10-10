"""core/workflows/storage.py

SQLite persistence layer for Workflow Definitions and Workflow Runs.
Part of Phase 7 (Task 7.2 - Milestone M5).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from core.workflows.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
)
from core.workflows.parser import WorkflowParser

logger = logging.getLogger("agent_engine.workflows.storage")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")


class WorkflowStorage:
    """Thread-safe SQLite storage for workflows and historical execution traces."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_SQLITE_PATH
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.executescript("""
                    CREATE TABLE IF NOT EXISTS workflows (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        version TEXT NOT NULL,
                        status TEXT NOT NULL,
                        definition_yaml TEXT,
                        definition_json TEXT NOT NULL,
                        tags TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);

                    CREATE TABLE IF NOT EXISTS workflow_runs (
                        run_id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        inputs TEXT NOT NULL,
                        outputs TEXT NOT NULL,
                        step_results TEXT NOT NULL,
                        current_node_id TEXT,
                        pending_gate TEXT,
                        total_cost_usd REAL DEFAULT 0.0,
                        created_at TEXT NOT NULL,
                        completed_at TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);
                    CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);
                """)
                cursor.execute("SELECT COUNT(*) as count FROM workflows")
                row = cursor.fetchone()
                if row and row["count"] == 0:
                    default_wf = WorkflowDefinition(
                        id="wf_code_audit_and_fix",
                        name="Automated Code Audit & Remediation",
                        description="Audits changed files with Code Sentry and generates staged patches.",
                        version="1.0.0",
                        status=WorkflowStatus.ACTIVE,
                        nodes=[
                            WorkflowNode(
                                id="scan_code",
                                type=WorkflowNodeType.PIPELINE,
                                name="Scan Code",
                                config={"pipeline_name": "code_sentry"},
                            ),
                            WorkflowNode(
                                id="evaluate_risk",
                                type=WorkflowNodeType.CONDITION,
                                name="Evaluate Risk",
                                config={"expression": "True"},
                            ),
                            WorkflowNode(
                                id="stage_review",
                                type=WorkflowNodeType.GATE,
                                name="Stage Review",
                                config={"timeout_seconds": 3600},
                            ),
                            WorkflowNode(
                                id="generate_patch",
                                type=WorkflowNodeType.PIPELINE,
                                name="Generate Patch",
                                config={"pipeline_name": "patch_generation"},
                            ),
                        ],
                        edges=[
                            WorkflowEdge(id="e1", source="scan_code", target="evaluate_risk"),
                            WorkflowEdge(
                                id="e2",
                                source="evaluate_risk",
                                target="stage_review",
                                condition="true",
                            ),
                            WorkflowEdge(
                                id="e3",
                                source="stage_review",
                                target="generate_patch",
                                condition="approved",
                            ),
                        ],
                        tags=["audit", "remediation", "safety"],
                    )
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    cursor.execute(
                        """
                        INSERT INTO workflows (
                            id, name, description, version, status, definition_yaml, definition_json, tags, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            default_wf.id,
                            default_wf.name,
                            default_wf.description,
                            default_wf.version,
                            default_wf.status.value,
                            WorkflowParser.to_yaml(default_wf),
                            json.dumps(default_wf.to_dict()),
                            json.dumps(default_wf.tags),
                            now,
                            now,
                        ),
                    )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

    def save_workflow(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        """Create or update a workflow definition."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        workflow_dict = workflow.to_dict()
        definition_json = json.dumps(workflow_dict)
        try:
            definition_yaml = WorkflowParser.to_yaml(workflow)
        except Exception:
            definition_yaml = ""
        tags_json = json.dumps(workflow.tags)

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO workflows (
                        id, name, description, version, status, definition_yaml, definition_json, tags, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        version = excluded.version,
                        status = excluded.status,
                        definition_yaml = excluded.definition_yaml,
                        definition_json = excluded.definition_json,
                        tags = excluded.tags,
                        updated_at = excluded.updated_at
                    """,
                    (
                        workflow.id,
                        workflow.name,
                        workflow.description,
                        workflow.version,
                        workflow.status.value,
                        definition_yaml,
                        definition_json,
                        tags_json,
                        workflow.created_at or now,
                        now,
                    ),
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """Fetch a workflow definition by its ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT definition_json FROM workflows WHERE id = ?",
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

    def list_workflows(
        self,
        status: Optional[WorkflowStatus] = None,
        tag: Optional[str] = None,
    ) -> List[WorkflowDefinition]:
        """List workflows optionally filtered by status or tag."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT definition_json, tags FROM workflows"
                params: List[Any] = []
                if status:
                    query += " WHERE status = ?"
                    params.append(status.value)
                query += " ORDER BY updated_at DESC"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                results: List[WorkflowDefinition] = []
                for row in rows:
                    if tag:
                        tags = json.loads(row["tags"] or "[]")
                        if tag not in tags:
                            continue
                    data = json.loads(row["definition_json"])
                    results.append(WorkflowDefinition.model_validate(data))
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow and its runs from SQLite."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM workflow_runs WHERE workflow_id = ?", (workflow_id,))
                cursor.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def save_run(self, run: WorkflowRun) -> WorkflowRun:
        """Save or update an execution run trace."""
        run_dict = run.to_dict()
        inputs_json = json.dumps(run.inputs)
        outputs_json = json.dumps(run.outputs)
        step_results_json = json.dumps(run_dict.get("step_results", {}))
        pending_gate_json = json.dumps(run.pending_gate) if run.pending_gate else None

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO workflow_runs (
                        run_id, workflow_id, status, inputs, outputs, step_results,
                        current_node_id, pending_gate, total_cost_usd, created_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        status = excluded.status,
                        inputs = excluded.inputs,
                        outputs = excluded.outputs,
                        step_results = excluded.step_results,
                        current_node_id = excluded.current_node_id,
                        pending_gate = excluded.pending_gate,
                        total_cost_usd = excluded.total_cost_usd,
                        completed_at = excluded.completed_at
                    """,
                    (
                        run.run_id,
                        run.workflow_id,
                        run.status.value,
                        inputs_json,
                        outputs_json,
                        step_results_json,
                        run.current_node_id,
                        pending_gate_json,
                        run.total_cost_usd,
                        run.created_at,
                        run.completed_at,
                    ),
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

        return run

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """Fetch a specific execution run by run_id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT run_id, workflow_id, status, inputs, outputs, step_results,
                           current_node_id, pending_gate, total_cost_usd, created_at, completed_at
                    FROM workflow_runs WHERE run_id = ?
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_run(row)
            finally:
                if not self._is_memory:
                    conn.close()

    def list_runs(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[WorkflowRun]:
        """List execution runs, optionally filtered by workflow_id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT * FROM workflow_runs"
                params: List[Any] = []
                if workflow_id:
                    query += " WHERE workflow_id = ?"
                    params.append(workflow_id)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [self._row_to_run(r) for r in rows]
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_run(self, run_id: str) -> bool:
        """Delete a run from SQLite."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM workflow_runs WHERE run_id = ?", (run_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> WorkflowRun:
        keys = row.keys()
        run_id = row["run_id"] if "run_id" in keys else row["workflow_run_id"]
        inputs_val = (
            row["inputs"]
            if "inputs" in keys
            else (row["inputs_json"] if "inputs_json" in keys else "{}")
        )
        outputs_val = (
            row["outputs"]
            if "outputs" in keys
            else (row["outputs_json"] if "outputs_json" in keys else "{}")
        )
        step_results_val = row["step_results"] if "step_results" in keys else "{}"
        current_node_id_val = row["current_node_id"] if "current_node_id" in keys else None
        pending_gate_val = row["pending_gate"] if "pending_gate" in keys else None
        total_cost_val = row["total_cost_usd"] if "total_cost_usd" in keys else 0.0

        data: Dict[str, Any] = {
            "run_id": run_id,
            "workflow_id": row["workflow_id"],
            "status": WorkflowRunStatus(row["status"]),
            "inputs": json.loads(inputs_val or "{}"),
            "outputs": json.loads(outputs_val or "{}"),
            "step_results": json.loads(step_results_val or "{}"),
            "current_node_id": current_node_id_val,
            "pending_gate": json.loads(pending_gate_val) if pending_gate_val else None,
            "total_cost_usd": float(total_cost_val or 0.0),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"] if "completed_at" in keys else None,
        }
        return WorkflowRun.model_validate(data)
