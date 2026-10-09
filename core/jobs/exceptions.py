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
