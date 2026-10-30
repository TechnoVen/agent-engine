"""core/jobs/service.py

Canonical Durable Job & Task Domain Service for Agent Engine 0.5.
Part of Milestone R5 (Founder Dogfood & Capability Packs) - Task R5.1 (Core Pack MVP).

Governing Invariant:
Exposes durable job submission, querying, cancellation, pause, and resume.
The underlying job queue, worker threads, and low-level lease locks remain
internal infrastructure components.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from core.jobs.control import JobControlService
from core.jobs.models import (
    Job,
    JobEvent,
    JobStatus,
    generate_job_id,
)
from core.jobs.queue import PersistentJobQueue, SQLiteJobQueue
from core.jobs.repository import JobRepository
from core.jobs.sqlite import SQLiteJobRepository
from core.storage import get_storage_backend
from core.storage.sqlite import DEFAULT_SQLITE_PATH

logger = logging.getLogger("agent_engine.jobs.service")


class JobService:
    """Canonical service managing durable asynchronous background jobs and tasks."""

    def __init__(
        self,
        repository: Optional[JobRepository] = None,
        queue: Optional[PersistentJobQueue] = None,
        control: Optional[JobControlService] = None,
        db_path: Optional[str] = None,
    ):
        self._db_path = db_path
        self._repository = repository
        self._queue = queue
        self._control = control

    @property
    def repository(self) -> JobRepository:
        if self._repository is None:
            db_path = (
                self._db_path
                or getattr(get_storage_backend(), "db_path", None)
                or os.getenv("SQLITE_DB_PATH")
                or DEFAULT_SQLITE_PATH
            )
            self._repository = SQLiteJobRepository(db_path=db_path)
        return self._repository

    @property
    def queue(self) -> PersistentJobQueue:
        if self._queue is None:
            db_path = (
                self._db_path
                or getattr(get_storage_backend(), "db_path", None)
                or os.getenv("SQLITE_DB_PATH")
                or DEFAULT_SQLITE_PATH
            )
            self._queue = SQLiteJobQueue(db_path=db_path)
        return self._queue

    @property
    def control(self) -> JobControlService:
        if self._control is None:
            db_path = (
                self._db_path
                or getattr(get_storage_backend(), "db_path", None)
                or os.getenv("SQLITE_DB_PATH")
                or DEFAULT_SQLITE_PATH
            )
            self._control = JobControlService(
                repository=self.repository,
                queue=self.queue,
                db_path=db_path,
            )
        return self._control

    def submit_job(
        self,
        job_type: str,
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
        priority: int = 0,
        job_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Job:
        """Submit and enqueue a new durable job."""
        jid = job_id or generate_job_id()
        job = Job(
            job_id=jid,
            job_type=job_type,
            project_id=session_id,
            status=JobStatus.READY,
            payload_summary=payload,
            timeout_seconds=timeout_seconds,
        )
        self.repository.create_job(job)
        self.queue.enqueue(jid)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a durable job by its ID."""
        return self.repository.get_job(job_id)

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Job]:
        """List durable jobs filtered by optional status."""
        return self.repository.list_jobs(status=status, limit=limit, offset=offset)

    def cancel_job(self, job_id: str, reason: str = "Operator cancelled") -> bool:
        """Cancel a pending or running durable job."""
        try:
            res = self.control.request_cancellation(
                job_id=job_id,
                reason=reason,
                operator_identity="operator",
            )
            return res.success
        except Exception as e:
            logger.error("Failed to cancel job %s: %s", job_id, e)
            return False

    def pause_job(self, job_id: str, reason: str = "Operator paused") -> bool:
        """Pause a pending or running durable job."""
        try:
            res = self.control.request_pause(
                job_id=job_id,
                reason=reason,
                operator_identity="operator",
            )
            return res.success
        except Exception as e:
            logger.error("Failed to pause job %s: %s", job_id, e)
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused durable job."""
        try:
            res = self.control.resume_job(
                job_id=job_id,
                operator_identity="operator",
            )
            return res.success
        except Exception as e:
            logger.error("Failed to resume job %s: %s", job_id, e)
            return False

    def get_job_events(self, job_id: str) -> List[JobEvent]:
        """Retrieve immutable audit events for a job."""
        return self.repository.get_job_events(job_id)


_global_job_service: Optional[JobService] = None


def get_job_service(
    repository: Optional[JobRepository] = None,
    queue: Optional[PersistentJobQueue] = None,
    control: Optional[JobControlService] = None,
) -> JobService:
    """Retrieve or initialize the singleton JobService."""
    global _global_job_service
    if _global_job_service is None or repository is not None:
        _global_job_service = JobService(
            repository=repository,
            queue=queue,
            control=control,
        )
    return _global_job_service
