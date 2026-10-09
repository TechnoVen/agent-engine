"""core/jobs/repository.py

Repository Interface for Canonical Job Domain (Task R4.1).
Part of Milestone R4 (Task R4.1 - Canonical Job Domain).

Governing Principles:
- Pure persistence and retrieval abstraction.
- Strict isolation from runtime queue/worker logic (no lease/claim/heartbeat).
- Thread-safe and atomic operations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.jobs.models import (
    Job,
    JobArtifact,
    JobAttempt,
    JobAttemptStatus,
    JobDependency,
    JobEvent,
    JobSchedule,
    JobStatus,
)


class JobRepository(ABC):
    """Abstract interface defining the durable persistence contract for jobs."""

    @abstractmethod
    def create_job(self, job: Job) -> Job:
        """Persist a new job record and append an initial JOB_CREATED event.

        Raises:
            JobDomainError: If validation or persistence fails.
        """
        raise NotImplementedError

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by its unique identifier."""
        raise NotImplementedError

    @abstractmethod
    def update_state(
        self,
        job_id: str,
        new_status: JobStatus,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """Atomically validate and update a job's status, appending a JOB_STATE_CHANGED event.

        Raises:
            JobNotFoundError: If job_id does not exist.
            InvalidStateTransitionError: If the transition is illegal.
        """
        raise NotImplementedError

    @abstractmethod
    def list_jobs(
        self,
        project_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Job]:
        """List jobs matching optional project and status filters, ordered by created_at DESC."""
        raise NotImplementedError

    @abstractmethod
    def create_attempt(
        self,
        job_id: str,
        execution_id: Optional[str] = None,
    ) -> JobAttempt:
        """Atomically create a new execution attempt with an incremented attempt_number.

        Appends an ATTEMPT_CREATED event, and if execution_id is provided, an EXECUTION_BOUND event.

        Raises:
            JobNotFoundError: If job_id does not exist.
        """
        raise NotImplementedError

    @abstractmethod
    def get_attempt(self, attempt_id: str) -> Optional[JobAttempt]:
        """Retrieve a specific attempt by its unique identifier."""
        raise NotImplementedError

    @abstractmethod
    def update_attempt_status(
        self,
        attempt_id: str,
        status: JobAttemptStatus,
        finished_at: Optional[str] = None,
        failure_classification: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> JobAttempt:
        """Update the lifecycle status and completion metadata of an attempt."""
        raise NotImplementedError

    @abstractmethod
    def list_attempts(self, job_id: str) -> List[JobAttempt]:
        """List all attempts for a given job in ascending attempt_number order."""
        raise NotImplementedError

    @abstractmethod
    def append_event(self, event: JobEvent) -> JobEvent:
        """Append an audit event for a job."""
        raise NotImplementedError

    @abstractmethod
    def list_events(
        self,
        job_id: str,
        attempt_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[JobEvent]:
        """List audit events for a job, optionally filtered by attempt_id, ordered by timestamp ASC."""
        raise NotImplementedError

    @abstractmethod
    def add_dependency(self, dependency: JobDependency) -> JobDependency:
        """Register a durable dependency constraint between two jobs.

        Validates against self-dependencies, duplicate dependencies, and circular cycles.

        Raises:
            SelfDependencyError: If job depends on itself.
            DuplicateDependencyError: If dependency already exists.
            DependencyCycleError: If dependency would create a cycle.
            JobNotFoundError: If either job does not exist.
        """
        raise NotImplementedError

    @abstractmethod
    def list_dependencies(self, job_id: str) -> List[JobDependency]:
        """List all dependency constraints for which job_id is the dependent job."""
        raise NotImplementedError

    @abstractmethod
    def attach_artifact(self, artifact: JobArtifact) -> JobArtifact:
        """Associate a canonical R1 artifact with a job, appending an ARTIFACT_ATTACHED event.

        Raises:
            JobNotFoundError: If job_id does not exist.
        """
        raise NotImplementedError

    @abstractmethod
    def list_artifacts(self, job_id: str) -> List[JobArtifact]:
        """List all canonical artifact associations for a job."""
        raise NotImplementedError

    @abstractmethod
    def create_schedule(self, schedule: JobSchedule) -> JobSchedule:
        """Persist a new job schedule definition."""
        raise NotImplementedError

    @abstractmethod
    def get_schedule(self, schedule_id: str) -> Optional[JobSchedule]:
        """Retrieve a schedule by its unique identifier."""
        raise NotImplementedError

    @abstractmethod
    def list_schedules(self, enabled_only: bool = False) -> List[JobSchedule]:
        """List schedule definitions, optionally filtered by enabled status."""
        raise NotImplementedError
