"""core/jobs/control.py

Durable Job Control Service (Task R4.5).
Part of Milestone R4 (Task R4.5 - Timeout, Pause, Resume, and Cancellation).

Governing Principles:
- Separation of Concerns: JobControlService owns control validation, authorization/policy
  integration, bounded auditing, and atomic control transactions. SQLiteJobRepository
  and SQLiteJobQueue retain pure persistence responsibilities.
- Desired Control Intent vs Lifecycle State: ControlIntent (NONE, PAUSE_REQUESTED,
  CANCEL_REQUESTED) is tracked separately from JobStatus (READY, RUNNING, PAUSED, CANCELLED).
- Monotonic Generation Fencing: Every accepted control mutation increments control_generation.
  Workers verify control_generation during acknowledgement to strictly reject stale signals.
- Attempt-Scoped Pause: Pausing a running job cooperative aborts the active attempt, setting
  attempt status to CANCELLED (paused_by_operator) and Job to PAUSED. Resuming creates a NEW attempt.
- Retry Backoff Preservation: Pausing a job in retry backoff preserves its queue available_at.
  Resuming does NOT execute early; it restores eligible waiting/timing.
- Strict Cancellation: Non-running jobs cancel immediately and permanently leave queue.
  Running jobs cancel cooperatively at execution boundary and permanently leave queue.
- Durable Timeout: Authoritative deadline timeout_at is persisted once at first attempt start
  and survives crashes and restarts. Expired jobs are rejected before claim and aborted during execution.
- Zero Secret Leakage: Control audit events contain bounded non-sensitive metadata only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, Field

from core.jobs.exceptions import (
    JobAlreadyTerminalError,
    JobControlConflictError,
    JobNotFoundError,
    StaleControlGenerationError,
)
from core.jobs.migrations import apply_job_migrations
from core.jobs.models import (
    FAILURE_CLASSIFICATION_CANCELLED_BY_OPERATOR,
    FAILURE_CLASSIFICATION_PAUSED_BY_OPERATOR,
    FAILURE_CLASSIFICATION_TIMEOUT,
    TERMINAL_JOB_STATES,
    ControlIntent,
    JobAttemptStatus,
    JobEventType,
    JobStatus,
    format_utc_iso,
    parse_utc_iso,
    sanitize_bounded_dict,
)
from core.jobs.queue import PersistentJobQueue, SQLiteJobQueue
from core.jobs.repository import JobRepository
from core.jobs.sqlite import SQLiteJobRepository

logger = logging.getLogger("agent_engine.jobs.control")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOBS_DB_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")


class JobControlResult(BaseModel):
    """Canonical result of an execution control mutation."""

    job_id: str
    control_intent: ControlIntent
    status: JobStatus
    control_generation: int
    applied_immediately: bool = Field(
        ...,
        description="True if job status transitioned immediately; False if cooperative worker stop is awaited.",
    )
    message: str


class JobControlService:
    """Authoritative service governing durable job execution controls and deadlines."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        repo: Optional[JobRepository] = None,
        queue: Optional[PersistentJobQueue] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.db_path = db_path or DEFAULT_JOBS_DB_PATH
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._clock = clock

        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        self.repo = repo or SQLiteJobRepository(db_path=self.db_path)
        self.queue = queue or SQLiteJobQueue(db_path=self.db_path, clock=self._clock)
        self._init_schema()

    def _now_dt(self, override: Optional[Union[datetime, str]] = None) -> datetime:
        if override is not None:
            if isinstance(override, str):
                return parse_utc_iso(override)
            if override.tzinfo is None:
                return override.replace(tzinfo=timezone.utc)
            return override.astimezone(timezone.utc)
        if self._clock is not None:
            now = self._clock()
            if now.tzinfo is None:
                return now.replace(tzinfo=timezone.utc)
            return now.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

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
        """Close any cached in-memory connection."""
        with self._lock:
            if self._memory_conn is not None:
                self._memory_conn.close()
                self._memory_conn = None

    def _insert_event(
        self,
        cursor: sqlite3.Cursor,
        job_id: str,
        event_type: JobEventType,
        timestamp: str,
        metadata: Dict[str, Any],
        attempt_id: Optional[str] = None,
    ) -> None:
        """Atomically insert an audit event with per-job sequence numbering and sanitization."""
        cursor.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
            (job_id,),
        )
        seq_num = cursor.fetchone()[0]
        cleaned_meta = sanitize_bounded_dict(metadata)
        cursor.execute(
            """
            INSERT INTO job_events (
                event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"jev_{uuid.uuid4().hex[:12]}",
                job_id,
                attempt_id,
                event_type.value,
                seq_num,
                timestamp,
                json.dumps(cleaned_meta),
            ),
        )

    # --------------------------------------------------------------------------
    # Pause Control
    # --------------------------------------------------------------------------

    def pause_job(
        self,
        job_id: str,
        requested_by: str = "authority:local_user",
        reason: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> JobControlResult:
        """Request pause for a durable job.

        - If non-running (READY, WAITING, CREATED, BLOCKED): transitions immediately to PAUSED.
          Queue row is preserved (including retry backoff available_at). claim_next() will not claim PAUSED.
        - If active (RUNNING): sets control_intent = PAUSE_REQUESTED with incremented control_generation.
          Awaits cooperative worker acknowledgement at execution boundary.

        Raises:
            JobNotFoundError: If job does not exist.
            JobAlreadyTerminalError: If job has already reached a terminal state.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT status, control_intent, control_generation FROM jobs WHERE job_id = ?",
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise JobNotFoundError(f"Job {job_id} does not exist.")

                current_status = JobStatus(row["status"])
                if current_status in TERMINAL_JOB_STATES:
                    conn.rollback()
                    raise JobAlreadyTerminalError(
                        f"Cannot pause job {job_id} in terminal state '{current_status.value}'."
                    )

                current_intent = ControlIntent(row["control_intent"])
                current_gen = row["control_generation"]

                # Idempotent check: already paused
                if current_status == JobStatus.PAUSED:
                    conn.commit()
                    return JobControlResult(
                        job_id=job_id,
                        control_intent=current_intent,
                        status=JobStatus.PAUSED,
                        control_generation=current_gen,
                        applied_immediately=True,
                        message="Job is already paused.",
                    )

                new_gen = current_gen + 1
                bounded_reason = reason[:256] if reason else None

                if current_status in (
                    JobStatus.READY,
                    JobStatus.WAITING,
                    JobStatus.CREATED,
                    JobStatus.BLOCKED,
                ):
                    # Immediate pause on inactive job
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET status = ?,
                            control_intent = ?,
                            control_generation = ?,
                            prior_status_before_pause = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (
                            JobStatus.PAUSED.value,
                            ControlIntent.NONE.value,
                            new_gen,
                            current_status.value,
                            now_iso,
                            job_id,
                        ),
                    )
                    self._insert_event(
                        cursor,
                        job_id,
                        JobEventType.JOB_PAUSED,
                        now_iso,
                        {
                            "requested_by": requested_by,
                            "reason": bounded_reason,
                            "control_generation": new_gen,
                            "from_status": current_status.value,
                        },
                    )
                    conn.commit()
                    logger.info(
                        "Job %s paused immediately from %s (gen %d)",
                        job_id,
                        current_status.value,
                        new_gen,
                    )
                    return JobControlResult(
                        job_id=job_id,
                        control_intent=ControlIntent.NONE,
                        status=JobStatus.PAUSED,
                        control_generation=new_gen,
                        applied_immediately=True,
                        message=f"Job paused immediately from {current_status.value}.",
                    )

                elif current_status == JobStatus.RUNNING:
                    # Active job: cooperative pause requested
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET control_intent = ?,
                            control_generation = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (
                            ControlIntent.PAUSE_REQUESTED.value,
                            new_gen,
                            now_iso,
                            job_id,
                        ),
                    )
                    self._insert_event(
                        cursor,
                        job_id,
                        JobEventType.JOB_PAUSE_REQUESTED,
                        now_iso,
                        {
                            "requested_by": requested_by,
                            "reason": bounded_reason,
                            "control_generation": new_gen,
                        },
                    )
                    conn.commit()
                    logger.info(
                        "Job %s pause requested; awaiting worker stop (gen %d)",
                        job_id,
                        new_gen,
                    )
                    return JobControlResult(
                        job_id=job_id,
                        control_intent=ControlIntent.PAUSE_REQUESTED,
                        status=JobStatus.RUNNING,
                        control_generation=new_gen,
                        applied_immediately=False,
                        message="Pause requested; waiting for worker cooperative stop.",
                    )
                else:
                    conn.rollback()
                    raise JobControlConflictError(
                        f"Cannot pause job {job_id} in status '{current_status.value}'."
                    )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Resume Control
    # --------------------------------------------------------------------------

    def resume_job(
        self,
        job_id: str,
        requested_by: str = "authority:local_user",
        reason: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> JobControlResult:
        """Resume a PAUSED job.

        Restores the job to its appropriate eligible lifecycle state (READY or WAITING
        if paused during retry backoff) while strictly preserving durable queue available_at.
        Next worker claim will initiate a NEW JobAttempt.

        Raises:
            JobNotFoundError: If job does not exist.
            JobAlreadyTerminalError: If job is in a terminal state.
            JobControlConflictError: If job is not in PAUSED status.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT status, control_intent, control_generation, prior_status_before_pause
                    FROM jobs WHERE job_id = ?
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise JobNotFoundError(f"Job {job_id} does not exist.")

                current_status = JobStatus(row["status"])
                if current_status in TERMINAL_JOB_STATES:
                    conn.rollback()
                    raise JobAlreadyTerminalError(
                        f"Cannot resume job {job_id} in terminal state '{current_status.value}'."
                    )

                if current_status != JobStatus.PAUSED:
                    conn.rollback()
                    raise JobControlConflictError(
                        f"Cannot resume job {job_id} in status '{current_status.value}'; job is not paused."
                    )

                current_gen = row["control_generation"]
                new_gen = current_gen + 1
                prior_status_str = row["prior_status_before_pause"]

                # If prior status was WAITING (e.g. retry backoff), resume to WAITING.
                # Otherwise, default to READY.
                if prior_status_str == JobStatus.WAITING.value:
                    target_status = JobStatus.WAITING
                else:
                    target_status = JobStatus.READY

                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = ?,
                        control_intent = ?,
                        control_generation = ?,
                        prior_status_before_pause = NULL,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        target_status.value,
                        ControlIntent.NONE.value,
                        new_gen,
                        now_iso,
                        job_id,
                    ),
                )

                # Ensure queue entry exists and is active
                cursor.execute(
                    "SELECT queue_entry_id, available_at FROM job_queue WHERE job_id = ?",
                    (job_id,),
                )
                q_row = cursor.fetchone()
                if not q_row:
                    cursor.execute(
                        """
                        INSERT INTO job_queue (
                            queue_entry_id, job_id, enqueued_at, available_at,
                            lease_generation, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 0, ?, ?)
                        """,
                        (
                            f"qent_{uuid.uuid4().hex[:12]}",
                            job_id,
                            now_iso,
                            now_iso,
                            now_iso,
                            now_iso,
                        ),
                    )
                else:
                    # Clear any leftover stale lease credentials on the queue entry
                    cursor.execute(
                        """
                        UPDATE job_queue
                        SET lease_owner = NULL,
                            lease_token = NULL,
                            lease_expires_at = NULL,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (now_iso, job_id),
                    )

                bounded_reason = reason[:256] if reason else None
                self._insert_event(
                    cursor,
                    job_id,
                    JobEventType.JOB_RESUMED,
                    now_iso,
                    {
                        "requested_by": requested_by,
                        "reason": bounded_reason,
                        "control_generation": new_gen,
                        "resumed_to_status": target_status.value,
                    },
                )
                conn.commit()
                logger.info("Job %s resumed to %s (gen %d)", job_id, target_status.value, new_gen)
                return JobControlResult(
                    job_id=job_id,
                    control_intent=ControlIntent.NONE,
                    status=target_status,
                    control_generation=new_gen,
                    applied_immediately=True,
                    message=f"Job resumed to {target_status.value}.",
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Cancel Control
    # --------------------------------------------------------------------------

    def cancel_job(
        self,
        job_id: str,
        requested_by: str = "authority:local_user",
        reason: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> JobControlResult:
        """Cancel a durable job.

        - If non-running (READY, WAITING, PAUSED, CREATED, BLOCKED): transitions immediately to CANCELLED.
          Queue row is removed permanently.
        - If active (RUNNING): persists CANCEL_REQUESTED and increments control_generation.
          Awaits cooperative worker stop at execution boundary.

        Raises:
            JobNotFoundError: If job does not exist.
            JobAlreadyTerminalError: If job has reached a non-cancel terminal state (COMPLETED, FAILED).
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT status, control_intent, control_generation FROM jobs WHERE job_id = ?",
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise JobNotFoundError(f"Job {job_id} does not exist.")

                current_status = JobStatus(row["status"])
                current_gen = row["control_generation"]

                # Idempotent cancel
                if current_status == JobStatus.CANCELLED:
                    conn.commit()
                    return JobControlResult(
                        job_id=job_id,
                        control_intent=ControlIntent.NONE,
                        status=JobStatus.CANCELLED,
                        control_generation=current_gen,
                        applied_immediately=True,
                        message="Job is already cancelled.",
                    )

                if current_status in TERMINAL_JOB_STATES:
                    conn.rollback()
                    raise JobAlreadyTerminalError(
                        f"Cannot cancel job {job_id} in terminal state '{current_status.value}'."
                    )

                new_gen = current_gen + 1
                bounded_reason = reason[:256] if reason else None

                if current_status in (
                    JobStatus.READY,
                    JobStatus.WAITING,
                    JobStatus.PAUSED,
                    JobStatus.CREATED,
                    JobStatus.BLOCKED,
                ):
                    # Non-running job: cancel immediately
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET status = ?,
                            control_intent = ?,
                            control_generation = ?,
                            completed_at = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (
                            JobStatus.CANCELLED.value,
                            ControlIntent.NONE.value,
                            new_gen,
                            now_iso,
                            now_iso,
                            job_id,
                        ),
                    )
                    # Permanently unclaimable
                    cursor.execute("DELETE FROM job_queue WHERE job_id = ?", (job_id,))
                    self._insert_event(
                        cursor,
                        job_id,
                        JobEventType.JOB_CANCELLED,
                        now_iso,
                        {
                            "requested_by": requested_by,
                            "reason": bounded_reason,
                            "control_generation": new_gen,
                            "from_status": current_status.value,
                        },
                    )
                    conn.commit()
                    logger.info(
                        "Job %s cancelled immediately from %s (gen %d)",
                        job_id,
                        current_status.value,
                        new_gen,
                    )
                    return JobControlResult(
                        job_id=job_id,
                        control_intent=ControlIntent.NONE,
                        status=JobStatus.CANCELLED,
                        control_generation=new_gen,
                        applied_immediately=True,
                        message=f"Job cancelled immediately from {current_status.value}.",
                    )

                elif current_status == JobStatus.RUNNING:
                    # Running job: cooperative cancel requested
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET control_intent = ?,
                            control_generation = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (
                            ControlIntent.CANCEL_REQUESTED.value,
                            new_gen,
                            now_iso,
                            job_id,
                        ),
                    )
                    self._insert_event(
                        cursor,
                        job_id,
                        JobEventType.JOB_CANCEL_REQUESTED,
                        now_iso,
                        {
                            "requested_by": requested_by,
                            "reason": bounded_reason,
                            "control_generation": new_gen,
                        },
                    )
                    conn.commit()
                    logger.info(
                        "Job %s cancellation requested; awaiting worker stop (gen %d)",
                        job_id,
                        new_gen,
                    )
                    return JobControlResult(
                        job_id=job_id,
                        control_intent=ControlIntent.CANCEL_REQUESTED,
                        status=JobStatus.RUNNING,
                        control_generation=new_gen,
                        applied_immediately=False,
                        message="Cancel requested; waiting for worker cooperative stop.",
                    )
                else:
                    conn.rollback()
                    raise JobControlConflictError(
                        f"Cannot cancel job {job_id} in status '{current_status.value}'."
                    )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Worker Cooperative Control Acknowledgements (Fenced)
    # --------------------------------------------------------------------------

    def acknowledge_pause(
        self,
        job_id: str,
        attempt_id: str,
        expected_control_generation: int,
        worker_id: str,
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Atomically acknowledge a cooperative pause at worker execution boundary.

        Fences against stale acknowledgements: if control_generation changed (e.g. resumed
        or cancelled while worker was stopping), the acknowledgement is rejected with
        StaleControlGenerationError.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT control_generation, control_intent FROM jobs WHERE job_id = ?",
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise JobNotFoundError(f"Job {job_id} not found.")

                if row["control_generation"] != expected_control_generation:
                    conn.rollback()
                    raise StaleControlGenerationError(
                        f"Cannot acknowledge pause for job {job_id}: worker generation "
                        f"{expected_control_generation} is stale (current generation is {row['control_generation']})."
                    )

                if row["control_intent"] != ControlIntent.PAUSE_REQUESTED.value:
                    conn.rollback()
                    raise StaleControlGenerationError(
                        f"Cannot acknowledge pause for job {job_id}: expected PAUSE_REQUESTED, "
                        f"found '{row['control_intent']}'."
                    )

                # 1. Terminalize attempt
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET status = ?,
                        finished_at = ?,
                        failure_classification = ?,
                        failure_message = ?
                    WHERE attempt_id = ? AND job_id = ?
                    """,
                    (
                        JobAttemptStatus.CANCELLED.value,
                        now_iso,
                        FAILURE_CLASSIFICATION_PAUSED_BY_OPERATOR,
                        "Paused by operator",
                        attempt_id,
                        job_id,
                    ),
                )

                # 2. Transition job to PAUSED
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = ?,
                        control_intent = ?,
                        prior_status_before_pause = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        JobStatus.PAUSED.value,
                        ControlIntent.NONE.value,
                        JobStatus.READY.value,
                        now_iso,
                        job_id,
                    ),
                )

                # 3. Release active lease from queue row without deleting row
                cursor.execute(
                    """
                    UPDATE job_queue
                    SET lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now_iso, job_id),
                )

                # 4. Append audit event
                self._insert_event(
                    cursor,
                    job_id,
                    JobEventType.JOB_PAUSED,
                    now_iso,
                    {
                        "worker_id": worker_id,
                        "attempt_id": attempt_id,
                        "control_generation": expected_control_generation,
                        "status": JobStatus.PAUSED.value,
                    },
                    attempt_id=attempt_id,
                )

                conn.commit()
                logger.info(
                    "Worker %s acknowledged cooperative pause for job %s (attempt %s, gen %d)",
                    worker_id,
                    job_id,
                    attempt_id,
                    expected_control_generation,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    def acknowledge_cancellation(
        self,
        job_id: str,
        attempt_id: str,
        expected_control_generation: int,
        worker_id: str,
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Atomically acknowledge a cooperative cancellation at worker execution boundary.

        Fences against stale acknowledgements: if control_generation changed, rejects with
        StaleControlGenerationError.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT control_generation, control_intent FROM jobs WHERE job_id = ?",
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise JobNotFoundError(f"Job {job_id} not found.")

                if row["control_generation"] != expected_control_generation:
                    conn.rollback()
                    raise StaleControlGenerationError(
                        f"Cannot acknowledge cancellation for job {job_id}: worker generation "
                        f"{expected_control_generation} is stale (current generation is {row['control_generation']})."
                    )

                if row["control_intent"] != ControlIntent.CANCEL_REQUESTED.value:
                    conn.rollback()
                    raise StaleControlGenerationError(
                        f"Cannot acknowledge cancellation for job {job_id}: expected CANCEL_REQUESTED, "
                        f"found '{row['control_intent']}'."
                    )

                # 1. Terminalize attempt
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET status = ?,
                        finished_at = ?,
                        failure_classification = ?,
                        failure_message = ?
                    WHERE attempt_id = ? AND job_id = ?
                    """,
                    (
                        JobAttemptStatus.CANCELLED.value,
                        now_iso,
                        FAILURE_CLASSIFICATION_CANCELLED_BY_OPERATOR,
                        "Cancelled by operator",
                        attempt_id,
                        job_id,
                    ),
                )

                # 2. Terminalize job
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = ?,
                        control_intent = ?,
                        completed_at = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        JobStatus.CANCELLED.value,
                        ControlIntent.NONE.value,
                        now_iso,
                        now_iso,
                        job_id,
                    ),
                )

                # 3. Permanently remove queue entry
                cursor.execute("DELETE FROM job_queue WHERE job_id = ?", (job_id,))

                # 4. Append audit event
                self._insert_event(
                    cursor,
                    job_id,
                    JobEventType.JOB_CANCELLED,
                    now_iso,
                    {
                        "worker_id": worker_id,
                        "attempt_id": attempt_id,
                        "control_generation": expected_control_generation,
                        "status": JobStatus.CANCELLED.value,
                    },
                    attempt_id=attempt_id,
                )

                conn.commit()
                logger.info(
                    "Worker %s acknowledged cooperative cancellation for job %s (attempt %s, gen %d)",
                    worker_id,
                    job_id,
                    attempt_id,
                    expected_control_generation,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    def acknowledge_timeout(
        self,
        job_id: str,
        attempt_id: str,
        worker_id: str,
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Atomically finalize a job that timed out during active execution."""
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # 1. Update attempt
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET status = ?,
                        finished_at = ?,
                        failure_classification = ?,
                        failure_message = ?
                    WHERE attempt_id = ? AND job_id = ?
                    """,
                    (
                        JobAttemptStatus.TIMED_OUT.value,
                        now_iso,
                        FAILURE_CLASSIFICATION_TIMEOUT,
                        "Execution deadline exceeded",
                        attempt_id,
                        job_id,
                    ),
                )

                # 2. Update job
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = ?,
                        control_intent = ?,
                        completed_at = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        JobStatus.FAILED.value,
                        ControlIntent.NONE.value,
                        now_iso,
                        now_iso,
                        job_id,
                    ),
                )

                # 3. Remove queue entry
                cursor.execute("DELETE FROM job_queue WHERE job_id = ?", (job_id,))

                # 4. Append audit events
                self._insert_event(
                    cursor,
                    job_id,
                    JobEventType.JOB_TIMED_OUT,
                    now_iso,
                    {
                        "worker_id": worker_id,
                        "attempt_id": attempt_id,
                        "failure_classification": FAILURE_CLASSIFICATION_TIMEOUT,
                    },
                    attempt_id=attempt_id,
                )
                self._insert_event(
                    cursor,
                    job_id,
                    JobEventType.JOB_FAILED,
                    now_iso,
                    {
                        "worker_id": worker_id,
                        "attempt_id": attempt_id,
                        "failure_classification": FAILURE_CLASSIFICATION_TIMEOUT,
                        "failure_message": "Execution deadline exceeded",
                    },
                    attempt_id=attempt_id,
                )

                conn.commit()
                logger.info(
                    "Worker %s acknowledged execution timeout for job %s (attempt %s)",
                    worker_id,
                    job_id,
                    attempt_id,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Pre-Claim Timeout Enforcement
    # --------------------------------------------------------------------------

    def check_and_apply_timeouts(self, now: Optional[Union[datetime, str]] = None) -> List[str]:
        """Detect and finalize all non-running jobs whose timeout_at deadline has elapsed.

        This includes jobs waiting in queue, waiting for retry backoff, or restored from restart.
        Prevents expired jobs from ever receiving an execution lease.

        Returns:
            List of job_ids that were timed out.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT job_id, control_generation
                    FROM jobs
                    WHERE status NOT IN ('completed', 'partial', 'failed', 'cancelled')
                      AND status != 'running'
                      AND timeout_at IS NOT NULL
                      AND timeout_at <= ?
                    """,
                    (now_iso,),
                )
                rows = cursor.fetchall()
                timed_out_ids: List[str] = []

                for r in rows:
                    jid = r["job_id"]
                    new_gen = r["control_generation"] + 1

                    cursor.execute(
                        """
                        UPDATE jobs
                        SET status = ?,
                            control_intent = ?,
                            control_generation = ?,
                            completed_at = ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (
                            JobStatus.FAILED.value,
                            ControlIntent.NONE.value,
                            new_gen,
                            now_iso,
                            now_iso,
                            jid,
                        ),
                    )
                    cursor.execute("DELETE FROM job_queue WHERE job_id = ?", (jid,))

                    self._insert_event(
                        cursor,
                        jid,
                        JobEventType.JOB_TIMED_OUT,
                        now_iso,
                        {
                            "failure_classification": FAILURE_CLASSIFICATION_TIMEOUT,
                            "reason": "Execution deadline exceeded before claim",
                            "control_generation": new_gen,
                        },
                    )
                    self._insert_event(
                        cursor,
                        jid,
                        JobEventType.JOB_FAILED,
                        now_iso,
                        {
                            "failure_classification": FAILURE_CLASSIFICATION_TIMEOUT,
                            "failure_message": "Job execution deadline exceeded",
                            "control_generation": new_gen,
                        },
                    )
                    timed_out_ids.append(jid)

                conn.commit()
                if timed_out_ids:
                    logger.info(
                        "Enforced deadlines: timed out %d inactive jobs: %s",
                        len(timed_out_ids),
                        timed_out_ids,
                    )
                return timed_out_ids
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()
