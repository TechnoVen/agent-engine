"""core/safety/service.py

Canonical Security Approval & Policy Domain Service for Agent Engine 0.5.
Part of Milestone R5 (Founder Dogfood & Capability Packs) - Task R5.1 (Core Pack MVP).

Governing Invariant (ADR-016):
Exposes canonical security approval boundary, cryptographic exact-operation
authorization, and policy evaluation. The underlying PendingOperationRegistry
and SQLite tables remain internal persistence components.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.safety.pending import (
    OperationExpiredError,
    PendingOperation,
    PendingOperationRegistry,
    SecurityBoundaryViolation,
    get_pending_registry,
)
from core.safety.policy import PolicyDecision, PolicyEngine

logger = logging.getLogger("agent_engine.safety.service")


class ApprovalService:
    """Canonical service managing human-in-the-loop approvals, exact digests, and safety boundaries."""

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        pending_registry: Optional[PendingOperationRegistry] = None,
    ):
        self._policy_engine = policy_engine
        self._pending_registry = pending_registry

    @property
    def policy_engine(self) -> PolicyEngine:
        if self._policy_engine is None:
            self._policy_engine = PolicyEngine()
        return self._policy_engine

    @property
    def pending_registry(self) -> PendingOperationRegistry:
        if self._pending_registry is None:
            self._pending_registry = get_pending_registry()
        return self._pending_registry

    def evaluate_operation(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        """Evaluate an operation against declarative safety rules."""
        return self.policy_engine.evaluate(
            tool_name=tool_name,
            tool_args=tool_args,
            context=context or {},
        )

    def request_approval(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        risk_level: str = "high",
        risk_score: float = 0.85,
        session_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        reason: Optional[str] = None,
        suggestion: Optional[str] = None,
        diff: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[float] = None,
        actor: Optional[str] = "local_operator",
        capability: Optional[str] = None,
        operation_id: Optional[str] = None,
        manifest: Optional[Dict[str, Any]] = None,
        expected_digest: Optional[str] = None,
    ) -> PendingOperation:
        """Register a consequential operation requiring human operator approval."""
        return self.pending_registry.register_operation(
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=risk_level,
            risk_score=risk_score,
            session_id=session_id,
            execution_id=execution_id,
            reason=reason,
            suggestion=suggestion,
            diff=diff,
            ttl_seconds=ttl_seconds,
            actor=actor,
            capability=capability,
            operation_id=operation_id,
        )

    def list_pending_operations(
        self,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[PendingOperation]:
        """List registered operations filtered by status or session."""
        return self.pending_registry.list_operations(status=status, session_id=session_id)

    def get_operation(self, operation_id: str) -> Optional[PendingOperation]:
        """Retrieve a pending operation by its primary key."""
        return self.pending_registry.get_operation(operation_id)

    def approve_operation(
        self,
        operation_id: str,
        operator_identity: str = "local_operator",
        notes: Optional[str] = None,
        expected_digest: Optional[str] = None,
    ) -> PendingOperation:
        """Approve an exact operation by operator identity and manifest digest."""
        if expected_digest:
            op = self.pending_registry.get_operation(operation_id)
            if op and op.digest and op.digest != expected_digest:
                raise SecurityBoundaryViolation(
                    f"Digest mismatch on approval: expected {expected_digest}, got {op.digest}"
                )
        op, _token = self.pending_registry.approve_operation(
            operation_id=operation_id,
            actor=operator_identity,
        )
        if notes:
            op.decision_reason = notes
        return op

    def reject_operation(
        self,
        operation_id: str,
        operator_identity: str = "local_operator",
        notes: Optional[str] = None,
    ) -> PendingOperation:
        """Reject an operation, preventing execution."""
        return self.pending_registry.reject_operation(
            operation_id=operation_id,
            actor=operator_identity,
            reason=notes or "Operator rejected",
        )

    def consume_exact_approval(
        self,
        approval_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        execution_id: Optional[str] = None,
        actor: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> bool:
        """Atomically consume an exact approval via central CAS."""
        try:
            op = self.pending_registry.consume_exact_approval(
                approval_id=approval_id,
                tool_name=tool_name,
                tool_args=tool_args,
                execution_id=execution_id,
                actor=actor,
                capability=capability,
            )
            return op.status == "consumed"
        except (SecurityBoundaryViolation, OperationExpiredError, ValueError):
            return False


_global_approval_service: Optional[ApprovalService] = None


def get_approval_service(
    policy_engine: Optional[PolicyEngine] = None,
    pending_registry: Optional[PendingOperationRegistry] = None,
) -> ApprovalService:
    """Retrieve or initialize the singleton ApprovalService."""
    global _global_approval_service
    if _global_approval_service is None or pending_registry is not None:
        _global_approval_service = ApprovalService(
            policy_engine=policy_engine,
            pending_registry=pending_registry,
        )
    return _global_approval_service
