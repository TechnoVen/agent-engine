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
