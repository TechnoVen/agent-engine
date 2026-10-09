"""core/jobs/sqlite.py

SQLite Implementation of the Canonical JobRepository (Task R4.1).
Part of Milestone R4 (Task R4.1 - Canonical Job Domain).

Provides robust ACID persistence for Jobs, Attempts, Events, Dependencies,
Artifact associations, and Schedules with zero dependencies outside the standard library.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Set

from core.jobs.exceptions import (
    DependencyCycleError,
    DuplicateDependencyError,
    JobNotFoundError,
    SelfDependencyError,
)
from core.jobs.migrations import apply_job_migrations
from core.jobs.models import (
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
    TERMINAL_JOB_STATES,
    current_timestamp_iso,
    sanitize_bounded_dict,
    validate_job_state_transition,
)
from core.jobs.repository import JobRepository

logger = logging.getLogger("agent_engine.jobs.sqlite")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOBS_DB_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")


class SQLiteJobRepository(JobRepository):
    """Thread-safe SQLite repository implementing the canonical JobRepository contract."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_JOBS_DB_PATH
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON;")
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_connection()
            apply_job_migrations(conn)
            if not self._is_memory:
                conn.close()

    def close(self) -> None:
        """Close any cached memory or file connections."""
        with self._lock:
            if self._memory_conn is not None:
                self._memory_conn.close()
                self._memory_conn = None

    # --------------------------------------------------------------------------
    # Job CRUD
    # --------------------------------------------------------------------------

    def create_job(self, job: Job) -> Job:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Sanitize summary metadata to guarantee secret prevention
                    clean_summary = sanitize_bounded_dict(job.payload_summary)
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            job_id, job_type, status, payload_reference,
                            payload_summary_json, created_by, project_id,
                            schedule_id, policy_context_id, created_at,
                            updated_at, completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job.job_id,
                            job.job_type,
                            job.status.value,
                            job.payload_reference,
                            json.dumps(clean_summary),
                            job.created_by,
                            job.project_id,
                            job.schedule_id,
                            job.policy_context_id,
                            job.created_at,
                            job.updated_at,
                            job.completed_at,
                        ),
                    )

                    # Append initial lifecycle event in same atomic transaction
                    init_event = JobEvent(
                        job_id=job.job_id,
                        event_type=JobEventType.JOB_CREATED,
                        timestamp=job.created_at,
                        metadata={
                            "job_type": job.job_type,
                            "created_by": job.created_by,
                            "initial_status": job.status.value,
                        },
                    )
                    conn.execute(
                        """
                        INSERT INTO job_events (
                            event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            init_event.event_id,
                            init_event.job_id,
                            init_event.attempt_id,
                            init_event.event_type.value,
                            init_event.timestamp,
                            json.dumps(sanitize_bounded_dict(init_event.metadata)),
                        ),
                    )
                return job
            finally:
                if not self._is_memory:
                    conn.close()

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT job_id, job_type, status, payload_reference,
                           payload_summary_json, created_by, project_id,
                           schedule_id, policy_context_id, created_at,
                           updated_at, completed_at
                    FROM jobs WHERE job_id = ?
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_job(row)
            finally:
                if not self._is_memory:
                    conn.close()

    def update_state(
        self,
        job_id: str,
        new_status: JobStatus,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Job:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
                    row = cursor.fetchone()
                    if not row:
                        raise JobNotFoundError(f"Job {job_id} does not exist.")

                    current_status = JobStatus(row["status"])
                    validate_job_state_transition(current_status, new_status)

                    now_iso = current_timestamp_iso()
                    completed_at = now_iso if new_status in TERMINAL_JOB_STATES else None

                    cursor.execute(
                        """
                        UPDATE jobs
                        SET status = ?, updated_at = ?, completed_at = COALESCE(completed_at, ?)
                        WHERE job_id = ?
                        """,
                        (new_status.value, now_iso, completed_at, job_id),
                    )

                    # Append event in the same atomic transaction
                    event_meta = {
                        "from_status": current_status.value,
                        "to_status": new_status.value,
                    }
                    if metadata:
                        event_meta.update(metadata)

                    state_event = JobEvent(
                        job_id=job_id,
                        event_type=JobEventType.JOB_STATE_CHANGED,
                        timestamp=now_iso,
                        metadata=event_meta,
                    )
                    cursor.execute(
                        """
                        INSERT INTO job_events (
                            event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state_event.event_id,
                            state_event.job_id,
                            state_event.attempt_id,
                            state_event.event_type.value,
                            state_event.timestamp,
                            json.dumps(sanitize_bounded_dict(state_event.metadata)),
                        ),
                    )

                return self.get_job(job_id)  # type: ignore[return-value]
            finally:
                if not self._is_memory:
                    conn.close()

    def list_jobs(
        self,
        project_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Job]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = """
                    SELECT job_id, job_type, status, payload_reference,
                           payload_summary_json, created_by, project_id,
                           schedule_id, policy_context_id, created_at,
                           updated_at, completed_at
                    FROM jobs
                    WHERE 1=1
                """
                params: List[Any] = []
                if project_id is not None:
                    query += " AND project_id = ?"
                    params.append(project_id)
                if status is not None:
                    query += " AND status = ?"
                    params.append(status.value)

                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(query, params)
                return [self._row_to_job(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Job Attempts
    # --------------------------------------------------------------------------

    def create_attempt(
        self,
        job_id: str,
        execution_id: Optional[str] = None,
    ) -> JobAttempt:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
                    if not cursor.fetchone():
                        raise JobNotFoundError(f"Job {job_id} not found.")

                    # Calculate next monotonic attempt number atomically within transaction
                    cursor.execute(
                        "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM job_attempts WHERE job_id = ?",
                        (job_id,),
                    )
                    next_attempt_number = cursor.fetchone()[0]

                    attempt = JobAttempt(
                        job_id=job_id,
                        attempt_number=next_attempt_number,
                        execution_id=execution_id,
                        status=JobAttemptStatus.PENDING,
                        started_at=current_timestamp_iso(),
                    )

                    cursor.execute(
                        """
                        INSERT INTO job_attempts (
                            attempt_id, job_id, attempt_number, execution_id,
                            status, started_at, finished_at, failure_classification, failure_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            attempt.attempt_id,
                            attempt.job_id,
                            attempt.attempt_number,
                            attempt.execution_id,
                            attempt.status.value,
                            attempt.started_at,
                            attempt.finished_at,
                            attempt.failure_classification,
                            attempt.failure_message,
                        ),
                    )

                    # Append attempt event
                    attempt_event = JobEvent(
                        job_id=job_id,
                        attempt_id=attempt.attempt_id,
                        event_type=JobEventType.ATTEMPT_CREATED,
                        timestamp=attempt.started_at,
                        metadata={
                            "attempt_number": attempt.attempt_number,
                            "execution_id": attempt.execution_id,
                        },
                    )
                    cursor.execute(
                        """
                        INSERT INTO job_events (
                            event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            attempt_event.event_id,
                            attempt_event.job_id,
                            attempt_event.attempt_id,
                            attempt_event.event_type.value,
                            attempt_event.timestamp,
                            json.dumps(sanitize_bounded_dict(attempt_event.metadata)),
                        ),
                    )

                    # If execution_id was bound, emit explicit event
                    if execution_id:
                        exec_event = JobEvent(
                            job_id=job_id,
                            attempt_id=attempt.attempt_id,
                            event_type=JobEventType.EXECUTION_BOUND,
                            timestamp=attempt.started_at,
                            metadata={"execution_id": execution_id},
                        )
                        cursor.execute(
                            """
                            INSERT INTO job_events (
                                event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                exec_event.event_id,
                                exec_event.job_id,
                                exec_event.attempt_id,
                                exec_event.event_type.value,
                                exec_event.timestamp,
                                json.dumps(sanitize_bounded_dict(exec_event.metadata)),
                            ),
                        )

                return attempt
            finally:
                if not self._is_memory:
                    conn.close()

    def get_attempt(self, attempt_id: str) -> Optional[JobAttempt]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT attempt_id, job_id, attempt_number, execution_id,
                           status, started_at, finished_at, failure_classification, failure_message
                    FROM job_attempts WHERE attempt_id = ?
                    """,
                    (attempt_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_attempt(row)
            finally:
                if not self._is_memory:
                    conn.close()

    def update_attempt_status(
        self,
        attempt_id: str,
        status: JobAttemptStatus,
        finished_at: Optional[str] = None,
        failure_classification: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> JobAttempt:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT attempt_id FROM job_attempts WHERE attempt_id = ?", (attempt_id,)
                    )
                    if not cursor.fetchone():
                        raise JobNotFoundError(f"Attempt {attempt_id} does not exist.")

                    cursor.execute(
                        """
                        UPDATE job_attempts
                        SET status = ?, finished_at = ?, failure_classification = ?, failure_message = ?
                        WHERE attempt_id = ?
                        """,
                        (
                            status.value,
                            finished_at,
                            failure_classification,
                            failure_message,
                            attempt_id,
                        ),
                    )
                return self.get_attempt(attempt_id)  # type: ignore[return-value]
            finally:
                if not self._is_memory:
                    conn.close()

    def list_attempts(self, job_id: str) -> List[JobAttempt]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT attempt_id, job_id, attempt_number, execution_id,
                           status, started_at, finished_at, failure_classification, failure_message
                    FROM job_attempts WHERE job_id = ?
                    ORDER BY attempt_number ASC
                    """,
                    (job_id,),
                )
                return [self._row_to_attempt(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Job Events
    # --------------------------------------------------------------------------

    def append_event(self, event: JobEvent) -> JobEvent:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT job_id FROM jobs WHERE job_id = ?", (event.job_id,))
                    if not cursor.fetchone():
                        raise JobNotFoundError(f"Job {event.job_id} does not exist.")

                    clean_meta = sanitize_bounded_dict(event.metadata)
                    cursor.execute(
                        """
                        INSERT INTO job_events (
                            event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            event.job_id,
                            event.attempt_id,
                            event.event_type.value,
                            event.timestamp,
                            json.dumps(clean_meta),
                        ),
                    )
                return event
            finally:
                if not self._is_memory:
                    conn.close()

    def list_events(
        self,
        job_id: str,
        attempt_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[JobEvent]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = """
                    SELECT event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                    FROM job_events WHERE job_id = ?
                """
                params: List[Any] = [job_id]
                if attempt_id is not None:
                    query += " AND attempt_id = ?"
                    params.append(attempt_id)
                query += " ORDER BY timestamp ASC, event_id ASC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                return [self._row_to_event(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Job Dependencies
    # --------------------------------------------------------------------------

    def add_dependency(self, dependency: JobDependency) -> JobDependency:
        if dependency.job_id == dependency.depends_on_job_id:
            raise SelfDependencyError(f"Job {dependency.job_id} cannot depend on itself.")

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    # Verify both jobs exist
                    cursor.execute("SELECT job_id FROM jobs WHERE job_id = ?", (dependency.job_id,))
                    if not cursor.fetchone():
                        raise JobNotFoundError(f"Job {dependency.job_id} does not exist.")
                    cursor.execute(
                        "SELECT job_id FROM jobs WHERE job_id = ?", (dependency.depends_on_job_id,)
                    )
                    if not cursor.fetchone():
                        raise JobNotFoundError(
                            f"Prerequisite job {dependency.depends_on_job_id} does not exist."
                        )

                    # Check for duplicate
                    cursor.execute(
                        "SELECT dependency_id FROM job_dependencies WHERE job_id = ? AND depends_on_job_id = ?",
                        (dependency.job_id, dependency.depends_on_job_id),
                    )
                    if cursor.fetchone():
                        raise DuplicateDependencyError(
                            f"Dependency from {dependency.job_id} to {dependency.depends_on_job_id} already exists."
                        )

                    # Cycle Detection via Depth-First Search on existing graph:
                    # If depends_on_job_id can reach job_id, adding job_id -> depends_on_job_id creates a cycle!
                    if self._check_path_exists(
                        cursor, start_id=dependency.depends_on_job_id, target_id=dependency.job_id
                    ):
                        raise DependencyCycleError(
                            f"Adding dependency from {dependency.job_id} to {dependency.depends_on_job_id} creates a cycle."
                        )

                    cursor.execute(
                        """
                        INSERT INTO job_dependencies (
                            dependency_id, job_id, depends_on_job_id, dependency_type, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            dependency.dependency_id,
                            dependency.job_id,
                            dependency.depends_on_job_id,
                            dependency.dependency_type.value,
                            dependency.created_at,
                        ),
                    )

                    # Append audit event in same transaction
                    dep_event = JobEvent(
                        job_id=dependency.job_id,
                        event_type=JobEventType.DEPENDENCY_ADDED,
                        timestamp=dependency.created_at,
                        metadata={
                            "depends_on_job_id": dependency.depends_on_job_id,
                            "dependency_type": dependency.dependency_type.value,
                        },
                    )
                    cursor.execute(
                        """
                        INSERT INTO job_events (
                            event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            dep_event.event_id,
                            dep_event.job_id,
                            dep_event.attempt_id,
                            dep_event.event_type.value,
                            dep_event.timestamp,
                            json.dumps(dep_event.metadata),
                        ),
                    )

                return dependency
            finally:
                if not self._is_memory:
                    conn.close()

    def _check_path_exists(self, cursor: sqlite3.Cursor, start_id: str, target_id: str) -> bool:
        """Perform DFS to check if start_id can reach target_id through existing dependencies."""
        visited: Set[str] = set()
        stack: List[str] = [start_id]

        while stack:
            current = stack.pop()
            if current == target_id:
                return True
            if current in visited:
                continue
            visited.add(current)

            cursor.execute(
                "SELECT depends_on_job_id FROM job_dependencies WHERE job_id = ?", (current,)
            )
            for (neighbor,) in cursor.fetchall():
                if neighbor not in visited:
                    stack.append(neighbor)

        return False

    def list_dependencies(self, job_id: str) -> List[JobDependency]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT dependency_id, job_id, depends_on_job_id, dependency_type, created_at
                    FROM job_dependencies WHERE job_id = ?
                    ORDER BY created_at ASC
                    """,
                    (job_id,),
                )
                return [self._row_to_dependency(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Job Artifacts
    # --------------------------------------------------------------------------

    def attach_artifact(self, artifact: JobArtifact) -> JobArtifact:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT job_id FROM jobs WHERE job_id = ?", (artifact.job_id,))
                    if not cursor.fetchone():
                        raise JobNotFoundError(f"Job {artifact.job_id} does not exist.")

                    cursor.execute(
                        """
                        INSERT INTO job_artifacts (
                            job_artifact_id, job_id, artifact_id, role, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            artifact.job_artifact_id,
                            artifact.job_id,
                            artifact.artifact_id,
                            artifact.role,
                            artifact.created_at,
                        ),
                    )

                    art_event = JobEvent(
                        job_id=artifact.job_id,
                        event_type=JobEventType.ARTIFACT_ATTACHED,
                        timestamp=artifact.created_at,
                        metadata={
                            "artifact_id": artifact.artifact_id,
                            "role": artifact.role,
                        },
                    )
                    cursor.execute(
                        """
                        INSERT INTO job_events (
                            event_id, job_id, attempt_id, event_type, timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            art_event.event_id,
                            art_event.job_id,
                            art_event.attempt_id,
                            art_event.event_type.value,
                            art_event.timestamp,
                            json.dumps(art_event.metadata),
                        ),
                    )
                return artifact
            finally:
                if not self._is_memory:
                    conn.close()

    def list_artifacts(self, job_id: str) -> List[JobArtifact]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT job_artifact_id, job_id, artifact_id, role, created_at
                    FROM job_artifacts WHERE job_id = ?
                    ORDER BY created_at ASC
                    """,
                    (job_id,),
                )
                return [self._row_to_artifact(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Job Schedules
    # --------------------------------------------------------------------------

    def create_schedule(self, schedule: JobSchedule) -> JobSchedule:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO job_schedules (
                            schedule_id, job_template_id, job_type, cron_expression,
                            timezone, enabled, payload_reference, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            schedule.schedule_id,
                            schedule.job_template_id,
                            schedule.job_type,
                            schedule.cron_expression,
                            schedule.timezone,
                            1 if schedule.enabled else 0,
                            schedule.payload_reference,
                            schedule.created_at,
                            schedule.updated_at,
                        ),
                    )
                return schedule
            finally:
                if not self._is_memory:
                    conn.close()

    def get_schedule(self, schedule_id: str) -> Optional[JobSchedule]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT schedule_id, job_template_id, job_type, cron_expression,
                           timezone, enabled, payload_reference, created_at, updated_at
                    FROM job_schedules WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_schedule(row)
            finally:
                if not self._is_memory:
                    conn.close()

    def list_schedules(self, enabled_only: bool = False) -> List[JobSchedule]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = """
                    SELECT schedule_id, job_template_id, job_type, cron_expression,
                           timezone, enabled, payload_reference, created_at, updated_at
                    FROM job_schedules
                """
                params: List[Any] = []
                if enabled_only:
                    query += " WHERE enabled = 1"
                query += " ORDER BY created_at DESC"
                cursor.execute(query, params)
                return [self._row_to_schedule(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Row Mappers
    # --------------------------------------------------------------------------

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        summary_raw = row["payload_summary_json"]
        summary = json.loads(summary_raw) if summary_raw else {}
        return Job(
            job_id=row["job_id"],
            job_type=row["job_type"],
            status=JobStatus(row["status"]),
            payload_reference=row["payload_reference"],
            payload_summary=summary,
            created_by=row["created_by"],
            project_id=row["project_id"],
            schedule_id=row["schedule_id"],
            policy_context_id=row["policy_context_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _row_to_attempt(row: sqlite3.Row) -> JobAttempt:
        return JobAttempt(
            attempt_id=row["attempt_id"],
            job_id=row["job_id"],
            attempt_number=row["attempt_number"],
            execution_id=row["execution_id"],
            status=JobAttemptStatus(row["status"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            failure_classification=row["failure_classification"],
            failure_message=row["failure_message"],
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> JobEvent:
        meta_raw = row["metadata_json"]
        meta = json.loads(meta_raw) if meta_raw else {}
        return JobEvent(
            event_id=row["event_id"],
            job_id=row["job_id"],
            attempt_id=row["attempt_id"],
            event_type=JobEventType(row["event_type"]),
            timestamp=row["timestamp"],
            metadata=meta,
        )

    @staticmethod
    def _row_to_dependency(row: sqlite3.Row) -> JobDependency:
        return JobDependency(
            dependency_id=row["dependency_id"],
            job_id=row["job_id"],
            depends_on_job_id=row["depends_on_job_id"],
            dependency_type=JobDependencyType(row["dependency_type"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> JobArtifact:
        return JobArtifact(
            job_artifact_id=row["job_artifact_id"],
            job_id=row["job_id"],
            artifact_id=row["artifact_id"],
            role=row["role"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_schedule(row: sqlite3.Row) -> JobSchedule:
        return JobSchedule(
            schedule_id=row["schedule_id"],
            job_template_id=row["job_template_id"],
            job_type=row["job_type"],
            cron_expression=row["cron_expression"],
            timezone=row["timezone"],
            enabled=bool(row["enabled"]),
            payload_reference=row["payload_reference"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
