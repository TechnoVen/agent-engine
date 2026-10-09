"""core/jobs/__init__.py

Canonical Job Domain (Task R4.1).
Part of Milestone R4 (Canonical Job Domain).

Governing Principles:
- Job != Execution: A Job represents requested/background durable work.
- JobAttempt may reference a canonical Execution (execution_id).
- ExecutionCoordinator remains the authoritative execution system.
- Jobs and related records persist independently of UI and runtime workers.
"""

from __future__ import annotations

from core.jobs.exceptions import (
    DependencyCycleError,
    DuplicateDependencyError,
    InvalidAttemptNumberError,
    InvalidStateTransitionError,
    JobDomainError,
    JobNotFoundError,
    ScheduleNotFoundError,
    SecurityRedactionError,
    SelfDependencyError,
)
from core.jobs.migrations import (
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    TERMINAL_JOB_STATES,
    VALID_JOB_TRANSITIONS,
    Job,
    JobArtifact,
    JobAttempt,
    JobAttemptStatus,
    JobDependency,
    JobDependencyType,
    JobEvent,
    JobEventType,
    JobSchedule,
    JobStatus,
    generate_attempt_id,
    generate_dependency_id,
    generate_event_id,
    generate_job_artifact_id,
    generate_job_id,
    generate_schedule_id,
    sanitize_bounded_dict,
    validate_job_state_transition,
)
from core.jobs.repository import JobRepository
from core.jobs.sqlite import SQLiteJobRepository

__all__ = [
    # Domain Models
    "Job",
    "JobAttempt",
    "JobEvent",
    "JobDependency",
    "JobArtifact",
    "JobSchedule",
    # Enums & Constants
    "JobStatus",
    "JobAttemptStatus",
    "JobEventType",
    "JobDependencyType",
    "VALID_JOB_TRANSITIONS",
    "TERMINAL_JOB_STATES",
    # Exceptions
    "JobDomainError",
    "JobNotFoundError",
    "InvalidStateTransitionError",
    "InvalidAttemptNumberError",
    "DuplicateDependencyError",
    "SelfDependencyError",
    "DependencyCycleError",
    "ScheduleNotFoundError",
    "SecurityRedactionError",
    # Repository Interfaces & Impls
    "JobRepository",
    "SQLiteJobRepository",
    # Migrations
    "apply_job_migrations",
    "get_current_job_schema_version",
    # Helpers
    "validate_job_state_transition",
    "sanitize_bounded_dict",
    "generate_job_id",
    "generate_attempt_id",
    "generate_event_id",
    "generate_dependency_id",
    "generate_job_artifact_id",
    "generate_schedule_id",
]
