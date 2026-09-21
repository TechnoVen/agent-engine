"""Canonical Execution State Machine (Task R1.2).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Set
from core.execution.models import (
    Execution,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionStatus,
    VerificationResult,
    current_timestamp_iso,
)

logger = logging.getLogger("agent_engine.execution.state")


class ExecutionStateError(Exception):
    """Base exception for execution state violations."""

    pass


class InvalidStateTransitionError(ExecutionStateError):
    """Raised when an illegal transition is attempted on an execution."""

    def __init__(self, from_status: ExecutionStatus, to_status: ExecutionStatus, reason: str = ""):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        msg = f"Invalid state transition from '{from_status.value}' to '{to_status.value}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class VerificationRequiredError(ExecutionStateError):
    """Raised when attempting to transition to COMPLETED without passing verification."""

    def __init__(
        self, message: str = "Transition to COMPLETED requires a passing VerificationResult"
    ):
        super().__init__(message)


# Terminal states from which no further transitions are permitted
TERMINAL_STATES: Set[ExecutionStatus] = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.PARTIAL,
    ExecutionStatus.BLOCKED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.CANCELLED,
}

# Allowed standard transitions between states
ALLOWED_TRANSITIONS: Dict[ExecutionStatus, Set[ExecutionStatus]] = {
    ExecutionStatus.CREATED: {
        ExecutionStatus.CONTEXT_BUILDING,
        ExecutionStatus.ROUTING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.CONTEXT_BUILDING: {
        ExecutionStatus.ROUTING,
        ExecutionStatus.BLOCKED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.ROUTING: {
        ExecutionStatus.POLICY_CHECK,
        ExecutionStatus.BLOCKED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.POLICY_CHECK: {
        ExecutionStatus.BUDGET_CHECK,
        ExecutionStatus.WAITING_FOR_APPROVAL,
        ExecutionStatus.BLOCKED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.BUDGET_CHECK: {
        ExecutionStatus.PLANNING,
        ExecutionStatus.READY,
        ExecutionStatus.WAITING_FOR_APPROVAL,
        ExecutionStatus.BLOCKED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.PLANNING: {
        ExecutionStatus.READY,
        ExecutionStatus.BLOCKED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.READY: {
        ExecutionStatus.QUEUED,
        ExecutionStatus.RUNNING,
        ExecutionStatus.WAITING_FOR_APPROVAL,
        ExecutionStatus.BLOCKED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.QUEUED: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
        ExecutionStatus.TIMED_OUT,
    },
    ExecutionStatus.RUNNING: {
        ExecutionStatus.WAITING_FOR_APPROVAL,
        ExecutionStatus.PAUSED,
        ExecutionStatus.VERIFYING,
        ExecutionStatus.PARTIAL,
        ExecutionStatus.FAILED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.WAITING_FOR_APPROVAL: {
        ExecutionStatus.READY,
        ExecutionStatus.QUEUED,
        ExecutionStatus.RUNNING,
        ExecutionStatus.BLOCKED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.PAUSED: {
        ExecutionStatus.READY,
        ExecutionStatus.QUEUED,
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.VERIFYING: {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.PARTIAL,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    # Terminal states
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.PARTIAL: set(),
    ExecutionStatus.BLOCKED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.TIMED_OUT: set(),
    ExecutionStatus.CANCELLED: set(),
}


class ExecutionStateMachine:
    """
    Deterministic state machine governing the lifecycle of an Execution entity.
    Guarantees:
    - Monotonically incrementing sequence numbers for state change events.
    - Strict validation of allowed transitions.
    - Verification gate: COMPLETED strictly requires a passing VerificationResult.
    - Inviolability of terminal states.
    - Automatic timestamp capture (started_at on RUNNING, completed_at on terminal).
    """

    def __init__(
        self,
        execution: Execution,
        initial_sequence_num: int = 0,
        event_sink: Optional[Callable[[ExecutionEvent], None]] = None,
    ):
        self.execution = execution
        self.current_sequence_num = initial_sequence_num
        self.event_sink = event_sink
        self._history: List[ExecutionEvent] = []

    @property
    def status(self) -> ExecutionStatus:
        return self.execution.status

    @property
    def is_terminal(self) -> bool:
        return self.execution.status in TERMINAL_STATES

    def can_transition_to(self, target_status: ExecutionStatus) -> bool:
        """Check if transition to target_status is permitted without raising."""
        allowed = ALLOWED_TRANSITIONS.get(self.execution.status, set())
        return target_status in allowed

    def transition(
        self,
        target_status: ExecutionStatus,
        verification: Optional[VerificationResult] = None,
        reason: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> ExecutionEvent:
        """
        Attempt a state transition on the execution.
        Raises:
            InvalidStateTransitionError: If target_status is not a valid successor.
            VerificationRequiredError: If transitioning to COMPLETED without verification.passed == True.
        """
        current_status = self.execution.status

        # 1. Reject transitions out of terminal states
        if current_status in TERMINAL_STATES:
            err = InvalidStateTransitionError(
                current_status,
                target_status,
                f"Execution '{self.execution.id}' is already in terminal state '{current_status.value}'",
            )
            logger.warning("Rejected terminal state transition: %s", err)
            raise err

        # 2. Check if transition is defined in transition graph
        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            err = InvalidStateTransitionError(
                current_status,
                target_status,
                f"No transition permitted from '{current_status.value}' to '{target_status.value}'",
            )
            logger.warning("Rejected illegal state transition: %s", err)
            raise err

        # 3. Guard: COMPLETED requires passing verification result
        if target_status == ExecutionStatus.COMPLETED:
            if verification is None:
                raise VerificationRequiredError(
                    f"Transition to COMPLETED for execution '{self.execution.id}' requires a VerificationResult"
                )
            if not verification.passed:
                raise VerificationRequiredError(
                    f"Cannot transition to COMPLETED: verification failed ({verification.error or 'check failed'})"
                )

        now_iso = current_timestamp_iso()

        # 4. Update timestamps
        if target_status == ExecutionStatus.RUNNING and not self.execution.started_at:
            self.execution.started_at = now_iso

        if target_status in TERMINAL_STATES and not self.execution.completed_at:
            self.execution.completed_at = now_iso

        # 5. Capture error descriptors if transitioning to error terminal state
        if error_code:
            self.execution.error_code = error_code
        if error_message:
            self.execution.error_message = error_message

        # 6. Apply state change
        previous_status = self.execution.status
        self.execution.status = target_status

        # 7. Create state change event
        event_payload: Dict[str, Any] = {
            "from_status": previous_status.value,
            "to_status": target_status.value,
        }
        if reason:
            event_payload["reason"] = reason
        if error_code:
            event_payload["error_code"] = error_code
        if error_message:
            event_payload["error_message"] = error_message
        if verification:
            event_payload["verification"] = verification.model_dump()
        if payload:
            event_payload.update(payload)

        event = ExecutionEvent(
            execution_id=self.execution.id,
            sequence_num=self.current_sequence_num,
            timestamp=now_iso,
            event_type=ExecutionEventType.STATE_CHANGE,
            payload=event_payload,
        )
        self.current_sequence_num += 1
        self._history.append(event)

        if self.event_sink:
            try:
                self.event_sink(event)
            except Exception as e:
                logger.error("Failed to forward state change event to sink: %s", e)

        logger.info(
            "Execution '%s' transitioned: %s -> %s (seq=%d)",
            self.execution.id,
            previous_status.value,
            target_status.value,
            event.sequence_num,
        )
        return event

    def get_history(self) -> List[ExecutionEvent]:
        """Return history of state change events recorded by this state machine."""
        return list(self._history)
