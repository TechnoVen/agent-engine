"""Execution Ledger Service (Task R1.11).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md, docs/EXECUTION_MODEL.md, docs/ROADMAP.md (R1.11)

Provides authoritative read-side projection over executions, durable events,
artifacts, and cost records without creating duplicate write-side tables.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from core.artifacts.service import ArtifactService
from core.execution.models import (
    ExecutionEventType,
    ExecutionStatus,
    VerificationResult,
)
from core.ledger.models import (
    ApprovalRecord,
    ArtifactSummaryRecord,
    ContextProvenance,
    CostProvenance,
    ExecutionEventRecord,
    ExecutionSummary,
    ExecutionTrace,
    ModelRoutingTrace,
    ToolInvocationRecord,
    UsageAndCostTrace,
)
from core.storage.base import StorageBackend

logger = logging.getLogger("agent_engine.ledger")


class LedgerSecurityError(Exception):
    """Raised when a caller attempts cross-project ledger access."""


class ExecutionLedgerService:
    """Authoritative projection service for execution ledger and history."""

    def __init__(
        self,
        storage: StorageBackend,
        artifact_service: Optional[ArtifactService] = None,
    ):
        self.storage = storage
        self.artifact_service = artifact_service

    def get_execution_trace(
        self, execution_id: str, project_id: Optional[str] = None
    ) -> Optional[ExecutionTrace]:
        """Project the authoritative execution trace for an execution.

        Enforces project-scope integrity when project_id is provided.
        """
        raw_exec = self.storage.get_execution(execution_id)
        if not raw_exec:
            # Check if execution_id matches a request_id in recent executions
            try:
                candidates = self.storage.list_executions(limit=200)
                for cand in candidates:
                    r_info = cand.get("request") or {}
                    if isinstance(r_info, str):
                        try:
                            r_info = json.loads(r_info)
                        except Exception:
                            r_info = {}
                    if r_info.get("id") == execution_id:
                        raw_exec = cand
                        execution_id = cand["id"]
                        break
            except Exception:
                pass

        if not raw_exec:
            return None

        # Project-scope integrity check
        exec_proj_id = raw_exec.get("project_id")
        if project_id and exec_proj_id and exec_proj_id != project_id:
            raise LedgerSecurityError(
                f"Scope boundary violation: Execution '{execution_id}' belongs to project '{exec_proj_id}', "
                f"not authorized for project '{project_id}'"
            )

        # 1. Fetch durable events strictly ordered by sequence_num
        raw_events = self.storage.get_execution_events(execution_id)
        raw_events.sort(key=lambda ev: ev.get("sequence_num", 0))

        # 2. Fetch linked artifacts
        raw_artifacts = self.storage.list_artifacts_by_execution(execution_id, include_deleted=True)

        # 3. Parse request
        req = raw_exec.get("request") or {}
        if isinstance(req, str):
            try:
                req = json.loads(req)
            except Exception:
                req = {}

        # 4. Extract actor
        actor = req.get("created_by")
        for ev in raw_events:
            if ev.get("event_type") == ExecutionEventType.CANCELLED.value:
                payload = ev.get("payload") or {}
                if payload.get("actor"):
                    actor = payload["actor"]
                    break

        # 5. Extract status, timestamps, duration
        status_val = raw_exec.get("status", "created")
        try:
            status = ExecutionStatus(status_val)
        except Exception:
            status = ExecutionStatus.CREATED

        created_at = raw_exec.get("created_at") or ""
        started_at = raw_exec.get("started_at")
        completed_at = raw_exec.get("completed_at")

        # Duration calculation
        duration_ms = 0.0
        if started_at and completed_at:
            try:
                t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                duration_ms = max(0.0, (t1 - t0).total_seconds() * 1000.0)
            except Exception:
                pass

        # 6. Reconstruct Model & Routing Truth
        requested_tier = req.get("target_tier")
        requested_model = req.get("model_preference")
        resolved_tier = None
        resolved_model = None
        actual_model = raw_exec.get("model")
        actual_provider = raw_exec.get("provider")
        is_fallback = False
        fallback_chain: List[str] = []
        fallback_history: List[Dict[str, Any]] = []

        for ev in raw_events:
            ev_type = ev.get("event_type")
            payload = ev.get("payload") or {}
            if ev_type == ExecutionEventType.ROUTING_RESOLVED.value:
                if resolved_model is None:
                    resolved_tier = payload.get("tier")
                    resolved_model = payload.get("model")
                    if not actual_provider:
                        actual_provider = payload.get("provider")
                    is_fallback = bool(payload.get("is_fallback", False))
                    fallback_chain = payload.get("fallback_chain", [])
                    if payload.get("fallback_history"):
                        fallback_history.extend(payload["fallback_history"])
                else:
                    # Subsequent routing resolution is a runtime fallback
                    is_fallback = True
                    fallback_history.append(payload)
                    actual_model = payload.get("model", actual_model)
                    actual_provider = payload.get("provider", actual_provider)

        routing_trace = ModelRoutingTrace(
            requested_tier=requested_tier,
            resolved_tier=resolved_tier,
            requested_model=requested_model,
            resolved_model=resolved_model,
            actual_model=actual_model,
            actual_provider=actual_provider,
            is_fallback=is_fallback,
            fallback_chain=fallback_chain,
            fallback_history=fallback_history,
        )

        # 7. Reconstruct Context Provenance
        context_prov_dict: Dict[str, Any] = {}
        for ev in raw_events:
            payload = ev.get("payload") or {}
            if "context_provenance" in payload:
                context_prov_dict.update(payload["context_provenance"])

        req_inputs = req.get("inputs") or {}
        project_root = context_prov_dict.get("project_root") or req_inputs.get("project_root")
        if not project_root and exec_proj_id:
            try:
                proj = self.storage.get_project(exec_proj_id)
                if proj:
                    project_root = proj.get("root_path")
            except Exception:
                pass

        instructions_hash = context_prov_dict.get("project_instructions_hash")
        if not instructions_hash:
            inst = req_inputs.get("project_instructions")
            if not inst and exec_proj_id:
                try:
                    proj = self.storage.get_project(exec_proj_id)
                    if proj:
                        inst = proj.get("instructions")
                except Exception:
                    pass
            if inst:
                instructions_hash = hashlib.sha256(inst.encode("utf-8")).hexdigest()

        context_trace = ContextProvenance(
            project_root=project_root,
            project_instructions_hash=instructions_hash,
            session_turns_available=context_prov_dict.get("session_turns_available", 0),
            session_turns_retained=context_prov_dict.get("session_turns_retained", 0),
            session_turns_dropped=context_prov_dict.get("session_turns_dropped", 0),
            history_truncated=context_prov_dict.get("history_truncated", False),
            prompt_tokens_estimated=context_prov_dict.get("prompt_tokens_estimated", 0),
            instruction_tokens_estimated=context_prov_dict.get("instruction_tokens_estimated", 0),
            context_tokens_estimated=context_prov_dict.get("context_tokens_estimated", 0),
        )

        # 8. Reconstruct Tools & Approvals
        tools_map: Dict[str, ToolInvocationRecord] = {}
        approvals_list: List[ApprovalRecord] = []

        for ev in raw_events:
            ev_type = ev.get("event_type")
            payload = ev.get("payload") or {}
            if ev_type == ExecutionEventType.TOOL_CALL_STARTED.value:
                inv_id = payload.get("invocation_id") or ev.get("id")
                tools_map[inv_id] = ToolInvocationRecord(
                    invocation_id=inv_id,
                    tool_id=payload.get("tool_id") or payload.get("tool_name", "unknown"),
                    status="started",
                    approval_id=payload.get("approval_id"),
                    requested_args_redacted=payload.get("args"),
                )
            elif ev_type == ExecutionEventType.TOOL_CALL_COMPLETED.value:
                inv_id = payload.get("invocation_id") or ev.get("id")
                if inv_id in tools_map:
                    tools_map[inv_id].status = (
                        "completed" if payload.get("success", True) else "failed"
                    )
                    tools_map[inv_id].duration_ms = payload.get("duration_ms")
                    tools_map[inv_id].output = payload.get("output")
                    tools_map[inv_id].error = payload.get("error")
                else:
                    tools_map[inv_id] = ToolInvocationRecord(
                        invocation_id=inv_id,
                        tool_id=payload.get("tool_id", "unknown"),
                        status="completed" if payload.get("success", True) else "failed",
                        duration_ms=payload.get("duration_ms"),
                        output=payload.get("output"),
                        error=payload.get("error"),
                    )
            elif ev_type == ExecutionEventType.APPROVAL_REQUIRED.value:
                approvals_list.append(
                    ApprovalRecord(
                        approval_id=payload.get("approval_id") or ev.get("id"),
                        policy_id=payload.get("policy_id"),
                        reason=payload.get("reason"),
                        suggestion=payload.get("suggestion"),
                        status="required",
                        timestamp=ev.get("timestamp", ""),
                    )
                )
            elif ev_type == ExecutionEventType.APPROVAL_RESOLVED.value:
                appr_id = payload.get("approval_id")
                for appr in approvals_list:
                    if appr.approval_id == appr_id:
                        appr.status = payload.get("decision", "approved")
                        appr.decided_by = payload.get("actor")

        # 9. Reconstruct Artifact References
        artifacts_list = [
            ArtifactSummaryRecord(
                id=a["id"],
                name=a["name"],
                type=a["type"],
                size_bytes=a["size_bytes"],
                sha256_hash=a["sha256_hash"],
                status=a["status"],
                mime_type=a.get("mime_type"),
            )
            for a in raw_artifacts
        ]

        # 10. Reconstruct Usage & Cost Provenance
        input_tokens = raw_exec.get("input_tokens") or 0
        output_tokens = raw_exec.get("output_tokens") or 0
        total_tokens = input_tokens + output_tokens
        total_cost_usd = raw_exec.get("total_cost_usd") or 0.0
        is_cost_estimated = bool(raw_exec.get("is_cost_estimated", False))

        if is_cost_estimated:
            cost_prov = CostProvenance.ESTIMATED
        elif total_tokens > 0 or total_cost_usd > 0:
            # If provider reported exact tokens or if calculated from pricing
            cost_prov = CostProvenance.CALCULATED
        else:
            cost_prov = CostProvenance.UNAVAILABLE

        usage_trace = UsageAndCostTrace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            is_cost_estimated=is_cost_estimated,
            cost_provenance=cost_prov,
        )

        # 11. Reconstruct Verification
        verification = None
        for ev in raw_events:
            ev_type = ev.get("event_type")
            payload = ev.get("payload") or {}
            if ev_type == ExecutionEventType.VERIFICATION_COMPLETED.value:
                try:
                    verification = VerificationResult.model_validate(payload)
                except Exception:
                    pass
            elif ev_type == ExecutionEventType.STATE_CHANGE.value and "verification" in payload:
                try:
                    verification = VerificationResult.model_validate(payload["verification"])
                except Exception:
                    pass

        # 12. Reconstruct Events
        events_list = [
            ExecutionEventRecord(
                id=ev["id"],
                sequence_num=ev["sequence_num"],
                timestamp=ev["timestamp"],
                event_type=ev["event_type"],
                payload=ev.get("payload") or {},
            )
            for ev in raw_events
        ]

        return ExecutionTrace(
            execution_id=execution_id,
            project_id=exec_proj_id,
            session_id=raw_exec.get("session_id"),
            actor=actor,
            status=status,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            error=raw_exec.get("error_message"),
            error_code=raw_exec.get("error_code"),
            routing=routing_trace,
            context=context_trace,
            tools=list(tools_map.values()),
            approvals=approvals_list,
            artifacts=artifacts_list,
            usage=usage_trace,
            verification=verification,
            events=events_list,
        )

    def list_project_executions(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> List[ExecutionSummary]:
        """List execution summaries for a project with pagination."""
        records = self.storage.list_executions(project_id=project_id, limit=limit, offset=offset)
        summaries = []
        for r in records:
            exec_id = r["id"]
            arts = self.storage.list_artifacts_by_execution(exec_id, include_deleted=False)
            status_val = r.get("status", "created")
            try:
                status = ExecutionStatus(status_val)
            except Exception:
                status = ExecutionStatus.CREATED

            duration_ms = 0.0
            if r.get("started_at") and r.get("completed_at"):
                try:
                    t0 = datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(r["completed_at"].replace("Z", "+00:00"))
                    duration_ms = max(0.0, (t1 - t0).total_seconds() * 1000.0)
                except Exception:
                    pass

            summaries.append(
                ExecutionSummary(
                    execution_id=exec_id,
                    project_id=r["project_id"],
                    session_id=r.get("session_id"),
                    status=status,
                    model=r.get("model"),
                    provider=r.get("provider"),
                    routing_tier=r.get("routing_tier"),
                    duration_ms=duration_ms,
                    total_cost_usd=r.get("total_cost_usd") or 0.0,
                    total_tokens=(r.get("input_tokens") or 0) + (r.get("output_tokens") or 0),
                    created_at=r.get("created_at") or "",
                    completed_at=r.get("completed_at"),
                    error_code=r.get("error_code"),
                    artifacts_count=len(arts),
                )
            )
        return summaries
