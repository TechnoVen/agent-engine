"""core/jobs/__init__.py

Canonical Job Domain & Persistent Local Queue (Tasks R4.1 & R4.2).
Part of Milestone R4 (Task R4.1 Canonical Job Domain, Task R4.2 Persistent Local Job Queue).

Governing Principles:
- Job != Execution: A Job represents requested/background durable work.
- JobAttempt may reference a canonical Execution (execution_id).
- ExecutionCoordinator remains the authoritative execution system.
- Jobs and queue records persist independently of UI and runtime workers.
- Queue claim != JobAttempt start != Execution start.
"""

from __future__ import annotations

from core.jobs.exceptions import (
    DependencyCycleError,
    DuplicateDependencyError,
    DuplicateQueueEntryError,
    IdempotencyConflictError,
    IdempotencyError,
    InvalidAttemptNumberError,
    InvalidLeaseError,
    InvalidStateTransitionError,
    JobDomainError,
    JobNotClaimableError,
    JobNotFoundError,
    JobQueueError,
    LeaseExpiredError,
    NonRetryableOperationError,
    OperationAlreadyInProgressError,
    QueueEntryNotFoundError,
    RetryExhaustedError,
    ScheduleNotFoundError,
    DuplicateOccurrenceError,
    InvalidScheduleExpressionError,
    InvalidTimezoneError,
    ScheduleDisabledError,
    SchedulerError,
    StaleScheduleGenerationError,
    SecurityRedactionError,
    SelfDependencyError,
    StaleLeaseError,
    UnsupportedJobTypeError,
    WorkerLeaseLostError,
)
from core.jobs.idempotency import (
    IdempotencyStore,
    SQLiteIdempotencyStore,
    classify_failure,
)
from core.jobs.migrations import (
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    EXECUTION_OUTCOME_UNKNOWN,
    FAILURE_CLASSIFICATION_WORKER_CRASH_OR_LEASE_LOST,
    SIDE_EFFECT_STATE_UNKNOWN,
    TERMINAL_JOB_STATES,
    VALID_JOB_TRANSITIONS,
    IdempotencyKey,
    IdempotencyRecord,
    IdempotencyRecordStatus,
    Job,
    JobArtifact,
    JobAttempt,
    JobAttemptStatus,
    JobDependency,
    JobDependencyType,
    JobEvent,
    JobEventType,
    JobLease,
    JobQueueEntry,
    JobSchedule,
    MissedRunPolicy,
    OccurrenceStatus,
    ScheduledOccurrence,
    generate_occurrence_id,
    JobStatus,
    OperationIdempotencyCapability,
    RetryClassification,
    RetryPolicy,
    compute_argument_digest,
    compute_idempotency_key,
    format_utc_iso,
    generate_attempt_id,
    generate_dependency_id,
    generate_event_id,
    generate_job_artifact_id,
    generate_job_id,
    generate_queue_entry_id,
    generate_schedule_id,
    normalize_utc_iso,
    parse_utc_iso,
    sanitize_bounded_dict,
    validate_job_state_transition,
)
from core.jobs.queue import (
    PersistentJobQueue,
    SQLiteJobQueue,
)
from core.jobs.repository import JobRepository
from core.jobs.sqlite import SQLiteJobRepository
from core.jobs.cron import (
    get_missed_occurrences,
    get_next_occurrence,
    validate_cron_expression,
    validate_iana_timezone,
)
from core.jobs.scheduler import SchedulerService
from core.jobs.worker import (
    JobExecutionRequestFactory,
    JobWorker,
    WorkerContext,
    generate_worker_id,
)
from core.jobs.service import (
    JobService,
    get_job_service,
)

__all__ = [
    # Domain Models
    "Job",
    "JobAttempt",
    "JobEvent",
    "JobDependency",
    "JobArtifact",
    "JobSchedule",
    "ScheduledOccurrence",
    "MissedRunPolicy",
    "OccurrenceStatus",
    "JobLease",
    "JobQueueEntry",
    "IdempotencyKey",
    "IdempotencyRecord",
    "RetryPolicy",
    # Enums & Constants
    "JobStatus",
    "JobAttemptStatus",
    "JobEventType",
    "JobDependencyType",
    "OperationIdempotencyCapability",
    "IdempotencyRecordStatus",
    "RetryClassification",
    "VALID_JOB_TRANSITIONS",
    "TERMINAL_JOB_STATES",
    "FAILURE_CLASSIFICATION_WORKER_CRASH_OR_LEASE_LOST",
    "EXECUTION_OUTCOME_UNKNOWN",
    "SIDE_EFFECT_STATE_UNKNOWN",
    # Exceptions
    "JobDomainError",
    "JobNotFoundError",
    "InvalidStateTransitionError",
    "InvalidAttemptNumberError",
    "DuplicateDependencyError",
    "SelfDependencyError",
    "DependencyCycleError",
    "ScheduleNotFoundError",
    "SchedulerError",
    "InvalidScheduleExpressionError",
    "InvalidTimezoneError",
    "ScheduleDisabledError",
    "StaleScheduleGenerationError",
    "DuplicateOccurrenceError",
    "SecurityRedactionError",
    "JobQueueError",
    "QueueEntryNotFoundError",
    "DuplicateQueueEntryError",
    "JobNotClaimableError",
    "InvalidLeaseError",
    "LeaseExpiredError",
    "StaleLeaseError",
    "UnsupportedJobTypeError",
    "WorkerLeaseLostError",
    "IdempotencyError",
    "IdempotencyConflictError",
    "OperationAlreadyInProgressError",
    "NonRetryableOperationError",
    "RetryExhaustedError",
    # Idempotency & Retry
    "IdempotencyStore",
    "SQLiteIdempotencyStore",
    "classify_failure",
    "compute_argument_digest",
    "compute_idempotency_key",
    # Repository & Queue Interfaces & Impls
    "JobRepository",
    "SQLiteJobRepository",
    "PersistentJobQueue",
    "SQLiteJobQueue",
    # Scheduler Service
    "SchedulerService",
    "get_missed_occurrences",
    "get_next_occurrence",
    "validate_cron_expression",
    "validate_iana_timezone",
    "generate_occurrence_id",
    # Worker Service
    "JobWorker",
    "JobExecutionRequestFactory",
    "WorkerContext",
    "generate_worker_id",
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
    "generate_queue_entry_id",
    "format_utc_iso",
    "parse_utc_iso",
    "normalize_utc_iso",
    # Canonical Job Service
    "JobService",
    "get_job_service",
]
