"""core/jobs/exceptions.py

Exceptions for the Canonical Job Domain (Task R4.1).
Part of Milestone R4 (Task R4.1 - Canonical Job Domain).
"""

from __future__ import annotations


class JobDomainError(Exception):
    """Base domain exception for job-related errors."""


class JobNotFoundError(JobDomainError):
    """Raised when a requested job does not exist."""


class InvalidStateTransitionError(JobDomainError):
    """Raised when attempting an invalid or illegal state transition on a job."""


class InvalidAttemptNumberError(JobDomainError):
    """Raised when an attempt number is invalid or non-sequential."""


class DuplicateDependencyError(JobDomainError):
    """Raised when attempting to add an already registered dependency."""


class SelfDependencyError(JobDomainError):
    """Raised when a job is configured to depend on itself."""


class DependencyCycleError(JobDomainError):
    """Raised when adding a dependency would introduce a cycle in the job dependency graph."""


class ScheduleNotFoundError(JobDomainError):
    """Raised when a referenced schedule does not exist."""


class SecurityRedactionError(JobDomainError):
    """Raised when sensitive credentials or secret material are detected in job payloads."""


class JobQueueError(JobDomainError):
    """Base exception for job queue and delivery operations."""


class QueueEntryNotFoundError(JobQueueError):
    """Raised when a referenced queue entry does not exist."""


class DuplicateQueueEntryError(JobQueueError):
    """Raised when attempting to enqueue a job that already has an active queue entry."""


class JobNotClaimableError(JobQueueError):
    """Raised when attempting to enqueue or claim a job that is not in an eligible state."""


class InvalidLeaseError(JobQueueError):
    """Raised when a lease operation is rejected due to token mismatch, expired lease, or invalid owner."""


class LeaseExpiredError(InvalidLeaseError):
    """Raised when attempting to operate on or extend a lease that has already expired."""


class StaleLeaseError(InvalidLeaseError):
    """Raised when an operation references a superseded lease generation or token."""


class UnsupportedJobTypeError(JobDomainError):
    """Raised when a job type is not recognized or supported by the worker runtime."""


class WorkerLeaseLostError(JobQueueError):
    """Raised when a worker loses its lease during execution and can no longer mutate state."""


class IdempotencyError(JobDomainError):
    """Base exception for idempotency tracking errors."""


class IdempotencyConflictError(IdempotencyError):
    """Raised when an operation with the same key was already attempted with conflicting parameters."""


class OperationAlreadyInProgressError(IdempotencyError):
    """Raised when another attempt/worker is actively executing an operation with the same key."""


class NonRetryableOperationError(JobDomainError):
    """Raised when an automatic retry is prohibited (e.g. non-idempotent operation with unknown outcome)."""


class RetryExhaustedError(JobDomainError):
    """Raised when a job has exceeded its maximum configured retry attempts."""


class JobControlError(JobDomainError):
    """Base exception for job execution control operations."""


class JobControlConflictError(JobControlError):
    """Raised when a control mutation conflicts with current job lifecycle state."""


class JobAlreadyTerminalError(JobControlConflictError):
    """Raised when attempting to pause or cancel a job that has already reached a terminal state."""


class StaleControlGenerationError(JobControlError):
    """Raised when an operation or worker acknowledgement references a superseded control generation."""


class JobTimeoutError(JobDomainError):
    """Raised when a job's authoritative execution deadline has elapsed."""
