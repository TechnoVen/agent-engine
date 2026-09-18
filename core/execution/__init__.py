"""Canonical Execution Domain Package.

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Provides the unified execution kernel models, state machine, and coordinator
for Agent Engine.
"""

from core.execution.coordinator import ExecutionBlockedError, ExecutionCoordinator
from core.execution.models import (
    Execution,
    ExecutionContext,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    RoutingTier,
    VerificationResult,
    current_timestamp_iso,
    generate_event_id,
    generate_execution_id,
    generate_request_id,
)
from core.execution.state import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    ExecutionStateError,
    ExecutionStateMachine,
    InvalidStateTransitionError,
    VerificationRequiredError,
)

__all__ = [
    # Models & Enums
    "Execution",
    "ExecutionContext",
    "ExecutionEvent",
    "ExecutionEventType",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "RoutingTier",
    "VerificationResult",
    "current_timestamp_iso",
    "generate_event_id",
    "generate_execution_id",
    "generate_request_id",
    # State Machine
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATES",
    "ExecutionStateError",
    "ExecutionStateMachine",
    "InvalidStateTransitionError",
    "VerificationRequiredError",
    # Coordinator
    "ExecutionBlockedError",
    "ExecutionCoordinator",
]
