"""core/jobs/models.py

Canonical Domain Models for Durable Jobs (Task R4.1).
Part of Milestone R4 (Task R4.1 - Canonical Job Domain).

Governing Principles:
- Job != Execution: A Job represents requested/background durable work.
- JobAttempt may reference a canonical Execution (execution_id).
- ExecutionCoordinator remains the authoritative execution system.
- Jobs and related records persist independently of UI and runtime workers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, Optional, Set
import uuid

from pydantic import BaseModel, ConfigDict, Field

from core.jobs.exceptions import InvalidStateTransitionError


def generate_job_id() -> str:
    """Generate canonical job ID with 'job_' prefix."""
    return f"job_{uuid.uuid4().hex[:12]}"


def generate_attempt_id() -> str:
    """Generate canonical attempt ID with 'att_' prefix."""
    return f"att_{uuid.uuid4().hex[:12]}"


def generate_event_id() -> str:
    """Generate canonical event ID with 'jev_' prefix."""
    return f"jev_{uuid.uuid4().hex[:12]}"


def generate_dependency_id() -> str:
    """Generate canonical dependency ID with 'jdp_' prefix."""
    return f"jdp_{uuid.uuid4().hex[:12]}"


def generate_job_artifact_id() -> str:
    """Generate canonical job artifact association ID with 'jar_' prefix."""
    return f"jar_{uuid.uuid4().hex[:12]}"


def generate_schedule_id() -> str:
    """Generate canonical job schedule ID with 'sch_' prefix."""
    return f"sch_{uuid.uuid4().hex[:12]}"


def current_timestamp_iso() -> str:
    """Return UTC ISO 8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


SENSITIVE_KEY_PATTERN = re.compile(
    r"(secret|password|token|api[_-]?key|bearer|auth|credential|private[_-]?key)",
    re.IGNORECASE,
)


def sanitize_bounded_dict(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Sanitize and bound dictionary to prevent secret leakage or unbounded payload bloat."""
    if not data:
        return {}
    cleaned: Dict[str, Any] = {}
    for k, v in data.items():
        if SENSITIVE_KEY_PATTERN.search(k):
            cleaned[k] = "[REDACTED_CREDENTIAL]"
        elif isinstance(v, dict):
            cleaned[k] = sanitize_bounded_dict(v)
        elif isinstance(v, str) and len(v) > 2048:
            cleaned[k] = v[:2048] + "... [TRUNCATED]"
        else:
            cleaned[k] = v
    return cleaned


class JobStatus(str, Enum):
    """Lifecycle statuses for canonical durable jobs."""

    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# Explicit valid transitions matrix for the Job state machine
VALID_JOB_TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
    JobStatus.CREATED: {JobStatus.READY, JobStatus.BLOCKED, JobStatus.CANCELLED},
    JobStatus.READY: {
        JobStatus.RUNNING,
        JobStatus.WAITING,
        JobStatus.PAUSED,
        JobStatus.BLOCKED,
        JobStatus.CANCELLED,
    },
    JobStatus.RUNNING: {
        JobStatus.WAITING,
        JobStatus.PAUSED,
        JobStatus.COMPLETED,
        JobStatus.PARTIAL,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.WAITING: {
        JobStatus.READY,
        JobStatus.RUNNING,
        JobStatus.PAUSED,
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    },
    JobStatus.PAUSED: {
        JobStatus.READY,
        JobStatus.RUNNING,
        JobStatus.CANCELLED,
    },
    JobStatus.BLOCKED: {
        JobStatus.READY,
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    },
    # Terminal states have no valid subsequent transitions
    JobStatus.COMPLETED: set(),
    JobStatus.PARTIAL: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}

TERMINAL_JOB_STATES: Set[JobStatus] = {
    JobStatus.COMPLETED,
    JobStatus.PARTIAL,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


def validate_job_state_transition(current: JobStatus, target: JobStatus) -> None:
    """Validate that transitioning a Job from current to target status is strictly legal.

    Raises:
        InvalidStateTransitionError: If the transition violates the state machine.
    """
    if current == target:
        return
    valid_targets = VALID_JOB_TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise InvalidStateTransitionError(
            f"Illegal job state transition from {current.value} to {target.value}. "
            f"Allowed transitions from {current.value}: {[s.value for s in valid_targets]}"
        )


class JobAttemptStatus(str, Enum):
    """Lifecycle status of a single execution attempt of a durable job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class JobEventType(str, Enum):
    """Event types emitted during job lifecycle changes."""

    JOB_CREATED = "job_created"
    JOB_STATE_CHANGED = "job_state_changed"
    ATTEMPT_CREATED = "attempt_created"
    EXECUTION_BOUND = "execution_bound"
    ARTIFACT_ATTACHED = "artifact_attached"
    DEPENDENCY_ADDED = "dependency_added"
    SCHEDULE_LINKED = "schedule_linked"


class JobDependencyType(str, Enum):
    """Constraint types for durable job dependencies."""

    COMPLETION = "completion"  # Dependent job must reach COMPLETED
    SUCCESS_OR_PARTIAL = "success_or_partial"  # Must reach COMPLETED or PARTIAL
    TERMINAL = "terminal"  # Must reach any terminal state (COMPLETED, FAILED, CANCELLED)


class Job(BaseModel):
    """Durable job domain model representing asynchronous/background work."""

    job_id: str = Field(default_factory=generate_job_id)
    job_type: str = Field(
        ..., description="Job purpose/type classification, e.g. batch_eval, document_summary"
    )
    status: JobStatus = Field(default=JobStatus.CREATED)
    payload_reference: Optional[str] = Field(
        None, description="URI or path reference to input payload"
    )
    payload_summary: Dict[str, Any] = Field(
        default_factory=dict, description="Bounded non-sensitive parameter summary"
    )
    created_by: str = Field(
        default="authority:local_user", description="Originating authority or user identifier"
    )
    project_id: Optional[str] = Field(None, description="Optional associated project scope")
    schedule_id: Optional[str] = Field(None, description="Optional originating schedule reference")
    policy_context_id: Optional[str] = Field(
        None, description="Optional zero-trust policy evaluation context"
    )
    created_at: str = Field(default_factory=current_timestamp_iso)
    updated_at: str = Field(default_factory=current_timestamp_iso)
    completed_at: Optional[str] = Field(
        None, description="Timestamp when job reached a terminal state"
    )

    model_config = ConfigDict(extra="ignore")


class JobAttempt(BaseModel):
    """A discrete execution attempt of a durable job."""

    attempt_id: str = Field(default_factory=generate_attempt_id)
    job_id: str = Field(..., description="Parent job identifier")
    attempt_number: int = Field(..., ge=1, description="1-indexed monotonic attempt number")
    execution_id: Optional[str] = Field(
        None, description="Reference to canonical R1 Execution instance"
    )
    status: JobAttemptStatus = Field(default=JobAttemptStatus.PENDING)
    started_at: str = Field(default_factory=current_timestamp_iso)
    finished_at: Optional[str] = None
    failure_classification: Optional[str] = None
    failure_message: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class JobEvent(BaseModel):
    """Append-oriented audit event for job lifecycle changes."""

    event_id: str = Field(default_factory=generate_event_id)
    job_id: str = Field(..., description="Target job identifier")
    attempt_id: Optional[str] = Field(None, description="Optional attempt context")
    event_type: JobEventType = Field(..., description="Lifecycle event classification")
    timestamp: str = Field(default_factory=current_timestamp_iso)
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Bounded non-sensitive event parameters"
    )

    model_config = ConfigDict(extra="ignore")


class JobDependency(BaseModel):
    """Durable dependency constraint between two jobs."""

    dependency_id: str = Field(default_factory=generate_dependency_id)
    job_id: str = Field(..., description="Dependent job identifier")
    depends_on_job_id: str = Field(..., description="Prerequisite job identifier")
    dependency_type: JobDependencyType = Field(default=JobDependencyType.COMPLETION)
    created_at: str = Field(default_factory=current_timestamp_iso)

    model_config = ConfigDict(extra="ignore")


class JobArtifact(BaseModel):
    """Association between a job and a canonical R1 Artifact."""

    job_artifact_id: str = Field(default_factory=generate_job_artifact_id)
    job_id: str = Field(..., description="Source job identifier")
    artifact_id: str = Field(..., description="Reference to canonical R1 artifact (art_...)")
    role: str = Field(
        default="output", description="Artifact role: output, checkpoint, report, log"
    )
    created_at: str = Field(default_factory=current_timestamp_iso)

    model_config = ConfigDict(extra="ignore")


class JobSchedule(BaseModel):
    """Durable schedule specification for recurring or scheduled job creation."""

    schedule_id: str = Field(default_factory=generate_schedule_id)
    job_template_id: Optional[str] = Field(None, description="Optional template reference")
    job_type: str = Field(..., description="Target job type to spawn")
    cron_expression: str = Field(..., description="Cron syntax expression, e.g. 0 2 * * *")
    timezone: str = Field(
        default="UTC", description="Timezone name for evaluation (e.g. UTC, America/New_York)"
    )
    enabled: bool = Field(default=True)
    payload_reference: Optional[str] = None
    created_at: str = Field(default_factory=current_timestamp_iso)
    updated_at: str = Field(default_factory=current_timestamp_iso)

    model_config = ConfigDict(extra="ignore")
