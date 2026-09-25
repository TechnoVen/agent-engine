"""services/python/server/routers/policies.py

Policies API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import io
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

# Core domain imports
from core.safety import (
    OperationExpiredError,
    SecurityBoundaryViolation,
    get_pending_registry,
    get_policy_engine,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.dependencies import verify_ipc_token
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.policies")
router = APIRouter(tags=["policies"])


@router.post("/safety/evaluate", response_model=SafetyEvaluationResponse)
async def evaluate_safety(req: SafetyEvaluationRequest):
    """Evaluate a prospective tool call against active safety policies and risk scoring.
    Fails closed on any exception, returning 'deny'."""
    engine = get_policy_engine()
    try:
        decision = engine.evaluate(
            tool_name=req.tool_name,
            tool_args=req.tool_args,
            context={
                "session_id": req.session_id,
                "allow_high_risk": req.allow_high_risk,
                "auto_apply": req.auto_apply,
            },
        )
    except Exception as e:
        # F06: Fail closed on evaluation error
        return SafetyEvaluationResponse(
            decision="deny",
            risk_score=1.0,
            risk_level="critical",
            violating_rules=[],
            suggestion="Execution blocked by safety boundary",
            reason=f"Safety evaluation failed (fail-closed): {e}",
            audit_id=None,
            operation_id=None,
        )

    # Auto-register into PendingOperationRegistry if decision is block/deny/stage or high/critical risk
    operation_id = None
    if decision.decision in ("deny", "block", "stage") or decision.risk_level in (
        "high",
        "critical",
    ):
        registry = get_pending_registry()
        op = registry.register_operation(
            tool_name=req.tool_name,
            tool_args=req.tool_args,
            risk_level=decision.risk_level,
            risk_score=decision.risk_score,
            session_id=req.session_id,
            reason=decision.reason,
            suggestion=decision.suggestion,
        )
        operation_id = op.operation_id

    return SafetyEvaluationResponse(
        decision=decision.decision,
        risk_score=decision.risk_score,
        risk_level=decision.risk_level,
        violating_rules=[SafetyPolicyRuleInfo(**r.to_dict()) for r in decision.violating_rules],
        suggestion=decision.suggestion,
        reason=decision.reason,
        audit_id=decision.audit_id,
        operation_id=operation_id,
    )


@router.get("/safety/operations", response_model=List[PendingOperationInfo])
async def list_pending_operations(
    status: Optional[str] = Query(
        None, description="Filter by status (pending, approved, rejected, expired, consumed)"
    ),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
):
    """List pending high-risk operations awaiting operator approval."""
    registry = get_pending_registry()
    ops = registry.list_operations(status=status, session_id=session_id)
    return [PendingOperationInfo(**op.to_dict()) for op in ops]


@router.post("/safety/operations", response_model=PendingOperationInfo)
async def register_pending_operation(req: RegisterOperationRequest):
    """Register a new pending tool operation into the approval queue with a 60s TTL."""
    registry = get_pending_registry()
    op = registry.register_operation(
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        risk_level=req.risk_level or "high",
        risk_score=req.risk_score or 0.85,
        session_id=req.session_id,
        reason=req.reason,
        suggestion=req.suggestion,
        diff=req.diff,
        ttl_seconds=req.ttl_seconds,
    )
    return PendingOperationInfo(**op.to_dict())


@router.get("/safety/operations/{operation_id}", response_model=PendingOperationInfo)
async def get_pending_operation(operation_id: str):
    """Retrieve details and status of a pending operation by ID."""
    registry = get_pending_registry()
    op = registry.get_operation(operation_id)
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operation '{operation_id}' not found",
        )
    return PendingOperationInfo(**op.to_dict())


@router.post("/safety/operations/{operation_id}/approve", response_model=PendingOperationInfo)
async def approve_pending_operation(
    operation_id: str,
    req: ApproveOperationRequest,
    request: Request,
):
    """Approve a pending operation, generate a single-use execution token, and audit the approval."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    try:
        op, token = registry.approve_operation(
            operation_id=operation_id,
            actor=req.actor or "operator",
            modified_args=req.modified_args,
        )
        engine = get_policy_engine()
        engine.audit_logger.log_evaluation(
            tool_name=op.tool_name,
            tool_args=op.tool_args,
            decision="operator_approved",
            risk_level=op.risk_level,
            risk_score=op.risk_score,
            policy_id="approval_queue",
            reason=f"Approved by {req.actor or 'operator'}",
            session_id=op.session_id,
        )
        data = op.to_dict()
        data["approval_token"] = token
        return PendingOperationInfo(**data)
    except OperationExpiredError as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/safety/operations/{operation_id}/reject", response_model=PendingOperationInfo)
async def reject_pending_operation(
    operation_id: str,
    req: RejectOperationRequest,
    request: Request,
):
    """Reject a pending operation with an explicit reason returned to the waiting agent."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    try:
        op = registry.reject_operation(
            operation_id=operation_id,
            actor=req.actor or "operator",
            reason=req.reason or "Rejected by operator",
        )
        engine = get_policy_engine()
        engine.audit_logger.log_evaluation(
            tool_name=op.tool_name,
            tool_args=op.tool_args,
            decision="operator_rejected",
            risk_level=op.risk_level,
            risk_score=op.risk_score,
            policy_id="approval_queue",
            reason=req.reason or "Rejected by operator",
            session_id=op.session_id,
        )
        return PendingOperationInfo(**op.to_dict())
    except OperationExpiredError as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/safety/operations/batch", response_model=List[PendingOperationInfo])
async def batch_operations(req: BatchOperationRequest, request: Request):
    """Batch approve or reject multiple pending operations."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    engine = get_policy_engine()
    results = []
    for op_id in req.operation_ids:
        try:
            if req.action == "approve":
                op, token = registry.approve_operation(op_id, actor=req.actor or "operator")
                engine.audit_logger.log_evaluation(
                    tool_name=op.tool_name,
                    tool_args=op.tool_args,
                    decision="operator_approved_batch",
                    risk_level=op.risk_level,
                    risk_score=op.risk_score,
                    policy_id="approval_queue_batch",
                    reason=f"Batch approved by {req.actor or 'operator'}",
                    session_id=op.session_id,
                )
                data = op.to_dict()
                data["approval_token"] = token
                results.append(data)
            elif req.action == "reject":
                op = registry.reject_operation(
                    op_id,
                    actor=req.actor or "operator",
                    reason=req.reason or "Batch rejected by operator",
                )
                engine.audit_logger.log_evaluation(
                    tool_name=op.tool_name,
                    tool_args=op.tool_args,
                    decision="operator_rejected_batch",
                    risk_level=op.risk_level,
                    risk_score=op.risk_score,
                    policy_id="approval_queue_batch",
                    reason=req.reason or "Batch rejected by operator",
                    session_id=op.session_id,
                )
                results.append(op.to_dict())
        except Exception:
            continue
    return [PendingOperationInfo(**d) for d in results]


@router.post("/safety/verify-execution", response_model=VerifyExecutionResponse)
async def verify_execution(req: VerifyExecutionRequest, request: Request):
    """Verify single-use execution token and burn it upon verification (fail-closed boundary)."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    try:
        op = registry.consume_token(
            approval_token=req.approval_token,
            tool_name=req.tool_name,
            tool_args=req.tool_args,
        )
        return VerifyExecutionResponse(
            authorized=True,
            operation_id=op.operation_id,
            tool_name=op.tool_name,
            actor=op.actor or "operator",
            message="Approval token successfully validated and burned.",
        )
    except SecurityBoundaryViolation as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Security boundary violation: {e}",
        )


@router.get("/safety/policies", response_model=List[SafetyPolicyRuleInfo])
async def list_safety_policies():
    """List all active guardrail rules loaded in the safety policy engine."""
    engine = get_policy_engine()
    return [SafetyPolicyRuleInfo(**r.to_dict()) for r in engine.list_rules()]


@router.get("/safety/audit", response_model=List[AuditLogInfo])
async def get_safety_audit_logs(
    limit: int = Query(50, ge=1, le=500, description="Max logs to return"),
    decision: Optional[str] = Query(None, description="Filter by decision (allow, block, stage)"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
):
    """Retrieve persistent safety audit log entries."""
    engine = get_policy_engine()
    logs = engine.audit_logger.list_logs(limit=limit, decision=decision, session_id=session_id)
    return [AuditLogInfo(**log) for log in logs]


@router.post("/safety/approval", response_model=AuditLogInfo)
async def submit_safety_approval(req: ApprovalDecisionRequest, request: Request):
    """Submit human operator approval, rejection, or edit decision for a high-risk tool call."""
    verify_ipc_token(request)
    engine = get_policy_engine()
    final_args = (
        req.modified_args if req.decision == "edit" and req.modified_args else req.tool_args
    )
    decision_str = f"operator_{req.decision}"
    reason_str = req.reason or f"Operator decision: {req.decision}"
    if req.operator:
        reason_str += f" (by {req.operator})"

    record_id = engine.audit_logger.log_evaluation(
        tool_name=req.tool_name,
        tool_args=final_args,
        decision=decision_str,
        risk_level=req.risk_level,
        risk_score=req.risk_score,
        policy_id="operator_gate",
        reason=reason_str,
        suggestion="Approved with modified args" if req.decision == "edit" else None,
        session_id=req.session_id,
    )
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    return AuditLogInfo(
        id=record_id if record_id > 0 else int(datetime.now(timezone.utc).timestamp()),
        timestamp=now_iso,
        tool_name=req.tool_name,
        tool_args=final_args,
        decision=decision_str,
        risk_level=req.risk_level,
        risk_score=req.risk_score,
        policy_id="operator_gate",
        reason=reason_str,
        suggestion="Approved with modified args" if req.decision == "edit" else None,
        session_id=req.session_id,
    )


@router.get("/safety/policies/yaml", response_model=PolicyYamlResponse)
async def get_safety_policy_yaml():
    """Retrieve raw safety policy YAML for inspection or editing."""
    engine = get_policy_engine()
    content = engine.get_yaml_content()
    return PolicyYamlResponse(yaml_content=content, rules_count=len(engine.list_rules()))


@router.post("/safety/policies/yaml")
async def update_safety_policy_yaml(req: PolicyYamlUpdateRequest, request: Request):
    """Validate, persist, and hot-reload safety guardrail policies from YAML content."""
    verify_ipc_token(request)
    engine = get_policy_engine()
    try:
        res = engine.update_yaml_content(req.yaml_content)
        return res
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/safety/policies/dry-run", response_model=SafetyEvaluationResponse)
async def dry_run_safety_policy(req: DryRunRequest):
    """Simulate and dry-run safety policy evaluation without logging to audit trail."""
    engine = get_policy_engine()
    decision = engine.evaluate(
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        context=req.context,
        dry_run=True,
    )
    return SafetyEvaluationResponse(**decision.to_dict())


@router.get("/safety/audit-logs", response_model=PaginatedAuditLogsResponse)
async def list_safety_audit_logs_paginated(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    decision: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    tool_name: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
):
    """Paginated query of safety audit logs with risk and tool name filters."""
    engine = get_policy_engine()
    total = engine.audit_logger.count_logs(
        decision=decision,
        risk_level=risk_level,
        tool_name=tool_name,
        session_id=session_id,
    )
    logs = engine.audit_logger.list_logs(
        limit=limit,
        offset=offset,
        decision=decision,
        risk_level=risk_level,
        tool_name=tool_name,
        session_id=session_id,
    )
    return PaginatedAuditLogsResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[AuditLogInfo(**log) for log in logs],
    )


@router.get("/safety/audit-logs/export")
async def export_safety_audit_logs(
    format: str = Query("csv", pattern="^(csv|json)$"),
    decision: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    tool_name: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
):
    """Export safety audit logs as CSV or JSON."""
    engine = get_policy_engine()
    logs = engine.audit_logger.list_logs(
        limit=limit,
        offset=0,
        decision=decision,
        risk_level=risk_level,
        tool_name=tool_name,
    )
    if format == "json":
        return logs

    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "timestamp",
            "tool_name",
            "tool_args",
            "decision",
            "risk_level",
            "risk_score",
            "policy_id",
            "reason",
            "suggestion",
            "session_id",
        ]
    )
    for log in logs:
        writer.writerow(
            [
                log.get("id"),
                log.get("timestamp"),
                log.get("tool_name"),
                json.dumps(log.get("tool_args", {})),
                log.get("decision"),
                log.get("risk_level"),
                log.get("risk_score"),
                log.get("policy_id"),
                log.get("reason"),
                log.get("suggestion"),
                log.get("session_id"),
            ]
        )
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=safety_audit_logs.csv"},
    )
