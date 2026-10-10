"""core/jobs/queue.py

Persistent Local Job Queue for Durable Jobs (Task R4.2).
Part of Milestone R4 (Task R4.2 - Persistent Local Job Queue).

Governing Principles:
- Queue state represents delivery and claim state, NOT job lifecycle state.
- Canonical JobStatus in jobs table remains the single lifecycle truth.
- Claiming a job != Executing a job: claim_next obtains a lease only;
  it creates no JobAttempt, creates no Execution, and leaves the Job READY.
- Atomic claims across threads and independent SQLite connections via BEGIN IMMEDIATE.
- Deterministic claim ordering: available_at ASC, enqueued_at ASC, queue_entry_id ASC.
- Expiring leases with monotonic lease_generation fencing and cryptographic tokens.
- Opaque lease tokens are strictly treated as internal authority material and NEVER logged.
- Injectable clock support for deterministic, fast expiry and reclaim testing without sleep.
- Strictly NO worker loop, daemon thread, or background runner in R4.2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Callable, List, Optional, Union
import uuid

from core.jobs.exceptions import (
    DuplicateQueueEntryError,
    InvalidLeaseError,
    JobNotClaimableError,
    JobNotFoundError,
    LeaseExpiredError,
    QueueEntryNotFoundError,
    StaleLeaseError,
)
from core.jobs.migrations import apply_job_migrations
from core.jobs.models import (
    TERMINAL_JOB_STATES,
    JobEvent,
    JobEventType,
    JobLease,
    JobQueueEntry,
    JobStatus,
    format_utc_iso,
    normalize_utc_iso,
    parse_utc_iso,
    sanitize_bounded_dict,
)

logger = logging.getLogger("agent_engine.jobs.queue")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOBS_DB_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")

MAX_LEASE_DURATION_SECONDS = 86400.0  # 24 hours upper bound


class PersistentJobQueue(ABC):
    """Abstract interface defining the persistent local job queue contract."""

    @abstractmethod
    def enqueue(
        self,
        job_id: str,
        available_at: Optional[Union[str, datetime]] = None,
    ) -> JobQueueEntry:
        """Enqueue an existing job for delivery.

        Raises:
            JobNotFoundError: If job_id does not exist.
            JobNotClaimableError: If job is in terminal, cancelled, or paused status.
            DuplicateQueueEntryError: If an active queue entry already exists for job_id.
        """
        raise NotImplementedError

    @abstractmethod
    def claim_next(
        self,
        worker_id: str,
        lease_duration_seconds: float = 300.0,
        now: Optional[Union[datetime, str]] = None,
    ) -> Optional[JobLease]:
        """Atomically claim the next eligible READY job and grant an opaque lease.

        Deterministic order: available_at ASC, enqueued_at ASC, queue_entry_id ASC.
        Increments lease_generation on reclaim of expired leases.

        Returns:
            JobLease if an eligible job was claimed, None otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def release_lease(
        self,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        now: Optional[Union[datetime, str]] = None,
    ) -> bool:
        """Release an active lease without executing the job, returning it to claimable state.

        Raises:
            QueueEntryNotFoundError: If no queue entry exists for job_id.
            InvalidLeaseError: If lease token or generation does not match current active lease.
        """
        raise NotImplementedError

    @abstractmethod
    def extend_lease(
        self,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        duration_seconds: float,
        now: Optional[Union[datetime, str]] = None,
        record_event: bool = True,
    ) -> JobLease:
        """Extend the expiration time of an active, unexpired lease.

        Raises:
            QueueEntryNotFoundError: If no queue entry exists for job_id.
            InvalidLeaseError: If lease token or generation does not match current active lease.
            LeaseExpiredError: If the lease has already expired.
        """
        raise NotImplementedError

    @abstractmethod
    def requeue_at(
        self,
        job_id: str,
        available_at: Union[datetime, str],
        lease_token: str,
        lease_generation: int,
        now: Optional[Union[datetime, str]] = None,
    ) -> JobQueueEntry:
        """Schedule durable retry by clearing active lease and setting future available_at.

        Transitions job status to WAITING and emits RETRY_SCHEDULED event.

        Raises:
            QueueEntryNotFoundError: If no queue entry exists for job_id.
            InvalidLeaseError: If lease token or generation does not match active lease.
            StaleLeaseError: If lease generation is stale.
            LeaseExpiredError: If lease has expired.
        """
        raise NotImplementedError

    @abstractmethod
    def get_entry(self, job_id: str) -> Optional[JobQueueEntry]:
        """Retrieve queue delivery entry for a given job."""
        raise NotImplementedError

    @abstractmethod
    def remove_entry(self, job_id: str) -> bool:
        """Remove a queue entry when job reaches completion or cancellation."""
        raise NotImplementedError

    @abstractmethod
    def list_entries(self, limit: int = 100, offset: int = 0) -> List[JobQueueEntry]:
        """List queue entries ordered by available_at ASC, enqueued_at ASC, queue_entry_id ASC."""
        raise NotImplementedError

    @abstractmethod
    def count_claimable(self, now: Optional[Union[datetime, str]] = None) -> int:
        """Count jobs currently eligible for claim."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close any open connections."""
        raise NotImplementedError


class SQLiteJobQueue(PersistentJobQueue):
    """Thread-safe and process-safe SQLite implementation of PersistentJobQueue.

    Guarantees:
    - Atomic claims across independent SQLite connections using BEGIN IMMEDIATE.
    - Deterministic oldest-eligible selection.
    - Zero leaks of cryptographic lease tokens to logs or events.
    - Complete persistence across restarts and connection re-openings.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.db_path = db_path or DEFAULT_JOBS_DB_PATH
        self._clock = clock
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        self._init_schema()

    def _now_dt(self, override: Optional[Union[datetime, str]] = None) -> datetime:
        """Resolve current UTC datetime using override, injected clock, or system clock."""
        if override is not None:
            if isinstance(override, str):
                return parse_utc_iso(override)
            if override.tzinfo is None:
                return override.replace(tzinfo=timezone.utc)
            return override.astimezone(timezone.utc)
        if self._clock is not None:
            c_val = self._clock()
            if c_val.tzinfo is None:
                return c_val.replace(tzinfo=timezone.utc)
            return c_val.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(
                    ":memory:", timeout=10.0, check_same_thread=False
                )
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON;")
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
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

    def _insert_event(self, cursor: sqlite3.Cursor, event: JobEvent) -> JobEvent:
        """Atomically insert an audit event with monotonic per-job sequence numbering."""
        cursor.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
            (event.job_id,),
        )
        event.sequence_number = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO job_events (
                event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.job_id,
                event.attempt_id,
                event.event_type.value,
                event.sequence_number,
                event.timestamp,
                json.dumps(sanitize_bounded_dict(event.metadata)),
            ),
        )
        return event

    # --------------------------------------------------------------------------
    # Enqueue
    # --------------------------------------------------------------------------

    def enqueue(
        self,
        job_id: str,
        available_at: Optional[Union[str, datetime]] = None,
    ) -> JobQueueEntry:
        now_dt = self._now_dt()
        now_iso = format_utc_iso(now_dt)

        if available_at is not None:
            avail_iso = normalize_utc_iso(available_at)
        else:
            avail_iso = now_iso

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # 1. Verify Job existence and status eligibility
                cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise JobNotFoundError(f"Job {job_id} does not exist.")

                status = JobStatus(row["status"])
                if status in TERMINAL_JOB_STATES:
                    conn.rollback()
                    raise JobNotClaimableError(
                        f"Cannot enqueue job {job_id}: status '{status.value}' is terminal."
                    )
                if status == JobStatus.CANCELLED:
                    conn.rollback()
                    raise JobNotClaimableError(
                        f"Cannot enqueue job {job_id}: status '{status.value}' is cancelled."
                    )
                if status == JobStatus.PAUSED:
                    conn.rollback()
                    raise JobNotClaimableError(
                        f"Cannot enqueue job {job_id}: status '{status.value}' is paused."
                    )

                # 2. Check duplicate active queue entry
                cursor.execute("SELECT queue_entry_id FROM job_queue WHERE job_id = ?", (job_id,))
                if cursor.fetchone():
                    conn.rollback()
                    raise DuplicateQueueEntryError(
                        f"Job {job_id} already has an active queue entry."
                    )

                # 3. Insert into job_queue
                entry = JobQueueEntry(
                    job_id=job_id,
                    enqueued_at=now_iso,
                    available_at=avail_iso,
                    lease_owner=None,
                    lease_token=None,
                    lease_generation=0,
                    lease_acquired_at=None,
                    lease_expires_at=None,
                    created_at=now_iso,
                    updated_at=now_iso,
                )

                cursor.execute(
                    """
                    INSERT INTO job_queue (
                        queue_entry_id, job_id, enqueued_at, available_at,
                        lease_owner, lease_token, lease_generation,
                        lease_acquired_at, lease_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, NULL, NULL, 0, NULL, NULL, ?, ?)
                    """,
                    (
                        entry.queue_entry_id,
                        entry.job_id,
                        entry.enqueued_at,
                        entry.available_at,
                        entry.created_at,
                        entry.updated_at,
                    ),
                )

                # 4. Append audit event (strictly no lease token)
                enq_event = JobEvent(
                    job_id=job_id,
                    event_type=JobEventType.JOB_ENQUEUED,
                    timestamp=now_iso,
                    metadata={
                        "queue_entry_id": entry.queue_entry_id,
                        "available_at": entry.available_at,
                    },
                )
                self._insert_event(cursor, enq_event)

                conn.commit()
                return entry
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Atomic Claim
    # --------------------------------------------------------------------------

    def claim_next(
        self,
        worker_id: str,
        lease_duration_seconds: float = 300.0,
        now: Optional[Union[datetime, str]] = None,
    ) -> Optional[JobLease]:
        if not worker_id:
            raise ValueError("worker_id must be a non-empty string.")
        if lease_duration_seconds <= 0 or lease_duration_seconds > MAX_LEASE_DURATION_SECONDS:
            raise ValueError(
                f"lease_duration_seconds must be between 1 and {MAX_LEASE_DURATION_SECONDS}."
            )

        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)
        expires_at_dt = now_dt + timedelta(seconds=lease_duration_seconds)
        expires_at_iso = format_utc_iso(expires_at_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # Select highest-priority eligible claimable job:
                # - Job status must be READY
                # - available_at <= now_iso
                # - unleased OR expired lease (lease_expires_at <= now_iso)
                # - Deterministic order: available_at ASC, enqueued_at ASC, queue_entry_id ASC
                cursor.execute(
                    """
                    SELECT q.queue_entry_id, q.job_id, q.lease_generation, q.lease_expires_at
                    FROM job_queue q
                    JOIN jobs j ON q.job_id = j.job_id
                    WHERE (j.status IN ('ready', 'waiting') OR (j.status = 'running' AND q.lease_expires_at IS NOT NULL AND q.lease_expires_at <= ?))
                      AND q.available_at <= ?
                      AND (q.lease_expires_at IS NULL OR q.lease_expires_at <= ?)
                      AND (j.timeout_at IS NULL OR j.timeout_at > ?)
                    ORDER BY q.available_at ASC, q.enqueued_at ASC, q.queue_entry_id ASC
                    LIMIT 1
                    """,
                    (now_iso, now_iso, now_iso, now_iso),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    return None

                queue_entry_id = row["queue_entry_id"]
                job_id = row["job_id"]
                old_generation = row["lease_generation"]
                old_expires_at = row["lease_expires_at"]

                is_reclaim = old_expires_at is not None
                new_generation = old_generation + 1
                lease_token = secrets.token_urlsafe(32)

                # Conditional atomic update ensuring generation didn't change
                cursor.execute(
                    """
                    UPDATE job_queue
                    SET lease_owner = ?,
                        lease_token = ?,
                        lease_generation = ?,
                        lease_acquired_at = ?,
                        lease_expires_at = ?,
                        updated_at = ?
                    WHERE queue_entry_id = ?
                      AND lease_generation = ?
                    """,
                    (
                        worker_id,
                        lease_token,
                        new_generation,
                        now_iso,
                        expires_at_iso,
                        now_iso,
                        queue_entry_id,
                        old_generation,
                    ),
                )

                if cursor.rowcount != 1:
                    conn.rollback()
                    return None

                # Append audit event: strictly NO lease token in metadata
                event_type = (
                    JobEventType.LEASE_RECLAIMED if is_reclaim else JobEventType.LEASE_ACQUIRED
                )
                audit_metadata = {
                    "worker_id": worker_id,
                    "lease_generation": new_generation,
                    "lease_expires_at": expires_at_iso,
                }
                if is_reclaim:
                    audit_metadata["previous_generation"] = old_generation

                claim_event = JobEvent(
                    job_id=job_id,
                    event_type=event_type,
                    timestamp=now_iso,
                    metadata=audit_metadata,
                )
                self._insert_event(cursor, claim_event)

                conn.commit()

                # INVARIANT: JobAttempt is NOT created, Execution is NOT bound,
                # ExecutionCoordinator is NOT called, Job status remains READY.
                return JobLease(
                    job_id=job_id,
                    queue_entry_id=queue_entry_id,
                    lease_owner=worker_id,
                    lease_token=lease_token,
                    lease_generation=new_generation,
                    lease_acquired_at=now_iso,
                    lease_expires_at=expires_at_iso,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Release Lease
    # --------------------------------------------------------------------------

    def release_lease(
        self,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        now: Optional[Union[datetime, str]] = None,
    ) -> bool:
        if not lease_token:
            raise ValueError("lease_token must be provided.")

        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT queue_entry_id, lease_owner, lease_token, lease_generation
                    FROM job_queue WHERE job_id = ?
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise QueueEntryNotFoundError(f"No queue entry found for job {job_id}.")

                current_token = row["lease_token"]
                current_gen = row["lease_generation"]
                lease_owner = row["lease_owner"] or "unknown_worker"

                # Check generation and token match
                if current_gen != lease_generation:
                    conn.rollback()
                    raise StaleLeaseError(
                        f"Cannot release lease for job {job_id}: lease generation {lease_generation} "
                        f"is stale (current active generation is {current_gen})."
                    )
                if current_token != lease_token:
                    conn.rollback()
                    raise InvalidLeaseError(
                        f"Cannot release lease for job {job_id}: lease token authority mismatch."
                    )

                # Clear active lease, preserving generation count for future increment
                cursor.execute(
                    """
                    UPDATE job_queue
                    SET lease_owner = NULL,
                        lease_token = NULL,
                        lease_acquired_at = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE job_id = ? AND lease_token = ? AND lease_generation = ?
                    """,
                    (now_iso, job_id, lease_token, lease_generation),
                )

                if cursor.rowcount != 1:
                    conn.rollback()
                    raise InvalidLeaseError(f"Failed to clear lease for job {job_id}.")

                # Append audit event: strictly NO token in metadata
                rel_event = JobEvent(
                    job_id=job_id,
                    event_type=JobEventType.LEASE_RELEASED,
                    timestamp=now_iso,
                    metadata={
                        "worker_id": lease_owner,
                        "lease_generation": lease_generation,
                    },
                )
                self._insert_event(cursor, rel_event)

                conn.commit()
                # Job remains in its current state (e.g. READY), zero retry created, zero attempt created
                return True
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Extend Lease
    # --------------------------------------------------------------------------

    def extend_lease(
        self,
        job_id: str,
        lease_token: str,
        lease_generation: int,
        duration_seconds: float,
        now: Optional[Union[datetime, str]] = None,
        record_event: bool = True,
    ) -> JobLease:
        if not lease_token:
            raise ValueError("lease_token must be provided.")
        if duration_seconds <= 0 or duration_seconds > MAX_LEASE_DURATION_SECONDS:
            raise ValueError(
                f"duration_seconds must be between 1 and {MAX_LEASE_DURATION_SECONDS}."
            )

        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)
        new_expires_dt = now_dt + timedelta(seconds=duration_seconds)
        new_expires_iso = format_utc_iso(new_expires_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT queue_entry_id, lease_owner, lease_token, lease_generation,
                           lease_acquired_at, lease_expires_at
                    FROM job_queue WHERE job_id = ?
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise QueueEntryNotFoundError(f"No queue entry found for job {job_id}.")

                current_token = row["lease_token"]
                current_gen = row["lease_generation"]
                current_expires = row["lease_expires_at"]
                lease_owner = row["lease_owner"] or "unknown_worker"
                queue_entry_id = row["queue_entry_id"]
                lease_acquired_at = row["lease_acquired_at"] or now_iso

                # Check generation and token match
                if current_gen != lease_generation:
                    conn.rollback()
                    raise StaleLeaseError(
                        f"Cannot extend lease for job {job_id}: lease generation {lease_generation} "
                        f"is stale (current active generation is {current_gen})."
                    )
                if current_token != lease_token:
                    conn.rollback()
                    raise InvalidLeaseError(
                        f"Cannot extend lease for job {job_id}: lease token authority mismatch."
                    )

                # Check expiration: cannot extend an already expired lease
                if current_expires is None or current_expires <= now_iso:
                    conn.rollback()
                    raise LeaseExpiredError(
                        f"Cannot extend expired lease for job {job_id} (expired at {current_expires})."
                    )

                # Update expiration
                cursor.execute(
                    """
                    UPDATE job_queue
                    SET lease_expires_at = ?, updated_at = ?
                    WHERE job_id = ? AND lease_token = ? AND lease_generation = ?
                    """,
                    (new_expires_iso, now_iso, job_id, lease_token, lease_generation),
                )

                if cursor.rowcount != 1:
                    conn.rollback()
                    raise InvalidLeaseError(f"Failed to extend lease for job {job_id}.")

                # Append audit event: strictly NO token in metadata (if requested)
                if record_event:
                    ext_event = JobEvent(
                        job_id=job_id,
                        event_type=JobEventType.LEASE_EXTENDED,
                        timestamp=now_iso,
                        metadata={
                            "worker_id": lease_owner,
                            "lease_generation": lease_generation,
                            "new_lease_expires_at": new_expires_iso,
                        },
                    )
                    self._insert_event(cursor, ext_event)

                conn.commit()
                return JobLease(
                    job_id=job_id,
                    queue_entry_id=queue_entry_id,
                    lease_owner=lease_owner,
                    lease_token=lease_token,
                    lease_generation=lease_generation,
                    lease_acquired_at=lease_acquired_at,
                    lease_expires_at=new_expires_iso,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Durable Retry Requeue
    # --------------------------------------------------------------------------

    def requeue_at(
        self,
        job_id: str,
        available_at: Union[datetime, str],
        lease_token: str,
        lease_generation: int,
        now: Optional[Union[datetime, str]] = None,
    ) -> JobQueueEntry:
        """Schedule durable retry by clearing active lease and setting future available_at.

        Transitions job status to WAITING and emits RETRY_SCHEDULED event.

        Raises:
            QueueEntryNotFoundError: If no queue entry exists for job_id.
            InvalidLeaseError: If lease token or generation does not match active lease.
            StaleLeaseError: If lease generation is stale.
            LeaseExpiredError: If lease has expired.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        if isinstance(available_at, str):
            avail_iso = normalize_utc_iso(available_at)
        else:
            avail_iso = format_utc_iso(available_at)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # Verify entry and lease authority
                cursor.execute(
                    """
                    SELECT queue_entry_id, lease_owner, lease_token, lease_generation,
                           lease_expires_at, enqueued_at, created_at
                    FROM job_queue WHERE job_id = ?
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise QueueEntryNotFoundError(f"No queue entry found for job {job_id}.")

                current_gen = row["lease_generation"]
                current_tok = row["lease_token"]
                lease_expires = row["lease_expires_at"]

                if current_gen != lease_generation:
                    conn.rollback()
                    raise StaleLeaseError(
                        f"Cannot requeue job {job_id}: lease generation {lease_generation} is stale (active is {current_gen})."
                    )

                if current_tok != lease_token:
                    conn.rollback()
                    raise InvalidLeaseError(f"Cannot requeue job {job_id}: lease token mismatch.")

                if lease_expires is not None and lease_expires <= now_iso:
                    conn.rollback()
                    raise LeaseExpiredError(
                        f"Cannot requeue job {job_id}: lease expired at {lease_expires}."
                    )

                # Clear lease and set available_at
                cursor.execute(
                    """
                    UPDATE job_queue
                    SET available_at = ?,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_acquired_at = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE job_id = ? AND lease_generation = ?
                    """,
                    (avail_iso, now_iso, job_id, lease_generation),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    raise InvalidLeaseError(f"Failed to requeue job {job_id}.")

                # Transition Job state to WAITING
                cursor.execute(
                    "UPDATE jobs SET status = 'waiting', updated_at = ? WHERE job_id = ?",
                    (now_iso, job_id),
                )

                # Append RETRY_SCHEDULED audit event
                cursor.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
                    (job_id,),
                )
                seq_num = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO job_events (
                        event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        f"jev_{uuid.uuid4().hex[:12]}",
                        job_id,
                        JobEventType.RETRY_SCHEDULED.value,
                        seq_num,
                        now_iso,
                        json.dumps(
                            {
                                "available_at": avail_iso,
                                "lease_generation": lease_generation,
                            }
                        ),
                    ),
                )

                conn.commit()
                cursor.execute(
                    """
                    SELECT queue_entry_id, job_id, enqueued_at, available_at,
                           lease_owner, lease_token, lease_generation,
                           lease_acquired_at, lease_expires_at, created_at, updated_at
                    FROM job_queue WHERE job_id = ?
                    """,
                    (job_id,),
                )
                entry_row = cursor.fetchone()
                return self._row_to_entry(entry_row)
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Retrieval and Maintenance
    # --------------------------------------------------------------------------

    def get_entry(self, job_id: str) -> Optional[JobQueueEntry]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT queue_entry_id, job_id, enqueued_at, available_at,
                           lease_owner, lease_token, lease_generation,
                           lease_acquired_at, lease_expires_at, created_at, updated_at
                    FROM job_queue WHERE job_id = ?
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_entry(row)
            finally:
                if not self._is_memory:
                    conn.close()

    def remove_entry(self, job_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM job_queue WHERE job_id = ?", (job_id,))
                    return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def list_entries(self, limit: int = 100, offset: int = 0) -> List[JobQueueEntry]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT queue_entry_id, job_id, enqueued_at, available_at,
                           lease_owner, lease_token, lease_generation,
                           lease_acquired_at, lease_expires_at, created_at, updated_at
                    FROM job_queue
                    ORDER BY available_at ASC, enqueued_at ASC, queue_entry_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )
                return [self._row_to_entry(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    def count_claimable(self, now: Optional[Union[datetime, str]] = None) -> int:
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM job_queue q
                    JOIN jobs j ON q.job_id = j.job_id
                    WHERE (j.status IN ('ready', 'waiting') OR (j.status = 'running' AND q.lease_expires_at IS NOT NULL AND q.lease_expires_at <= ?))
                      AND q.available_at <= ?
                      AND (q.lease_expires_at IS NULL OR q.lease_expires_at <= ?)
                    """,
                    (now_iso, now_iso, now_iso),
                )
                return cursor.fetchone()[0]
            finally:
                if not self._is_memory:
                    conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> JobQueueEntry:
        return JobQueueEntry(
            queue_entry_id=row["queue_entry_id"],
            job_id=row["job_id"],
            enqueued_at=row["enqueued_at"],
            available_at=row["available_at"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_generation=row["lease_generation"],
            lease_acquired_at=row["lease_acquired_at"],
            lease_expires_at=row["lease_expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
