"""core/workflows/gates.py

Human-in-the-Loop Approval Gates and Pending Review Registry for Workflows.
Part of Phase 7 (Task 7.3 - Milestone M5).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.safety.pending import PendingOperationRegistry
from core.workflows.engine import WorkflowEngine
from core.workflows.models import (
    WorkflowRun,
    WorkflowRunStatus,
)
from core.workflows.storage import WorkflowStorage

logger = logging.getLogger("agent_engine.workflows.gates")


class WorkflowGateManager:
    """Coordinates interactive human review gates across active workflow DAG runs."""

    def __init__(
        self,
        storage: Optional[WorkflowStorage] = None,
        engine: Optional[WorkflowEngine] = None,
        pending_registry: Optional[PendingOperationRegistry] = None,
    ):
        self.storage = storage or WorkflowStorage()
        self.engine = engine or WorkflowEngine(storage=self.storage)
        self.pending_registry = pending_registry

    def list_pending_gates(self) -> List[Dict[str, Any]]:
        """Query and return all active workflow runs paused at a human approval gate."""
        runs = self.storage.list_runs(limit=200)
        pending: List[Dict[str, Any]] = []

        for run in runs:
            if run.status == WorkflowRunStatus.WAITING_APPROVAL:
                wf = self.storage.get_workflow(run.workflow_id)
                gate_meta = run.pending_gate or {}
                pending.append(
                    {
                        "run_id": run.run_id,
                        "workflow_id": run.workflow_id,
                        "workflow_name": wf.name if wf else run.workflow_id,
                        "node_id": run.current_node_id,
                        "gate_name": gate_meta.get("name") or run.current_node_id,
                        "inputs": gate_meta.get("inputs", {}),
                        "timeout_seconds": gate_meta.get("timeout_seconds", 3600),
                        "created_at": run.created_at,
                    }
                )

        return pending

    def approve_gate(
        self,
        workflow_id: str,
        run_id: str,
        reviewer: str = "operator",
        input_overrides: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        """Approve a paused human review gate and resume DAG execution downstream."""
        wf = self.storage.get_workflow(workflow_id)
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        run = self.storage.get_run(run_id)
        if not run or run.workflow_id != workflow_id:
            raise ValueError(f"Run '{run_id}' not found for workflow '{workflow_id}'.")

        if run.status != WorkflowRunStatus.WAITING_APPROVAL:
            raise ValueError(
                f"Run '{run_id}' is not waiting for approval (current status: {run.status.value})."
            )

        logger.info(
            "Approving gate '%s' on run '%s' by reviewer '%s'",
            run.current_node_id,
            run_id,
            reviewer,
        )
        return self.engine.resume_gate(
            workflow=wf,
            run=run,
            approve=True,
            reviewer=reviewer,
            input_overrides=input_overrides,
        )

    def reject_gate(
        self,
        workflow_id: str,
        run_id: str,
        reviewer: str = "operator",
        reason: Optional[str] = None,
    ) -> WorkflowRun:
        """Reject a paused human review gate and either route to rejection branch or cancel."""
        wf = self.storage.get_workflow(workflow_id)
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        run = self.storage.get_run(run_id)
        if not run or run.workflow_id != workflow_id:
            raise ValueError(f"Run '{run_id}' not found for workflow '{workflow_id}'.")

        if run.status != WorkflowRunStatus.WAITING_APPROVAL:
            raise ValueError(
                f"Run '{run_id}' is not waiting for approval (current status: {run.status.value})."
            )

        logger.info(
            "Rejecting gate '%s' on run '%s' by reviewer '%s' (reason: %s)",
            run.current_node_id,
            run_id,
            reviewer,
            reason,
        )
        return self.engine.resume_gate(
            workflow=wf,
            run=run,
            approve=False,
            reviewer=reviewer,
        )

    def redirect_gate(
        self,
        workflow_id: str,
        run_id: str,
        target_node_id: str,
        reviewer: str = "operator",
        input_overrides: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        """Redirect execution of a paused run to an alternate target node."""
        wf = self.storage.get_workflow(workflow_id)
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        run = self.storage.get_run(run_id)
        if not run or run.workflow_id != workflow_id:
            raise ValueError(f"Run '{run_id}' not found for workflow '{workflow_id}'.")

        if run.status != WorkflowRunStatus.WAITING_APPROVAL:
            raise ValueError(
                f"Run '{run_id}' is not waiting for approval (current status: {run.status.value})."
            )

        logger.info(
            "Redirecting gate '%s' on run '%s' to target node '%s' by reviewer '%s'",
            run.current_node_id,
            run_id,
            target_node_id,
            reviewer,
        )
        return self.engine.resume_gate(
            workflow=wf,
            run=run,
            approve=True,
            reviewer=reviewer,
            redirect_to=target_node_id,
            input_overrides=input_overrides,
        )
