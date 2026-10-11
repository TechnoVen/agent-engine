"""core/jobs/worker.py

Durable Job Worker Service (Task R4.3).
Part of Milestone R4 (Task R4.3 - Worker Service).

Governing Principles:
- Single-job concurrency per worker process; multiple processes arbitrated via SQLite leases.
- Worker is a service that owns durable delivery, attempt lifecycle, lease maintenance,
  and prior attempt crash reconciliation.
- ExecutionCoordinator remains the authoritative execution system.
  Zero direct provider calls, direct tool invocations, or direct DSPy calls.
- Claim != Begin Attempt: begin_claimed_attempt transactionally revalidates lease credentials
  and reconciles any prior orphaned/crashed attempt.
- Execution binding: attempt_id <-> execution_id is fence-guarded before dispatch.
- Heartbeat maintenance: heartbeat extends lease periodically; authority loss on heartbeat
  failure immediately stops mutations and prevents terminal commit.
- Completion fencing: finalize_claimed_attempt revalidates the current lease before committing
  completion; stale workers are strictly rejected with StaleLeaseError.
- Graceful shutdown: drains short jobs; on drain timeout, does NOT release active lease
  (leaving it to expire naturally).
- Zero lease tokens, secrets, or credential leaks in logs or audit events.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, Optional, Set, Union
import uuid

from core.execution.cancellation import CancellationReason, CancellationToken
from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    generate_request_id,
)
from core.jobs.control import JobControlService
from core.jobs.exceptions import (
    InvalidLeaseError,
    JobNotClaimableError,
    JobNotFoundError,
    LeaseExpiredError,
    StaleControlGenerationError,
    StaleLeaseError,
    UnsupportedJobTypeError,
)
from core.jobs.idempotency import (
    IdempotencyStore,
    SQLiteIdempotencyStore,
    classify_failure,
)
from core.jobs.models import (
    EXECUTION_OUTCOME_UNKNOWN,
    FAILURE_CLASSIFICATION_WORKER_CRASH_OR_LEASE_LOST,
    ControlIntent,
    IdempotencyRecordStatus,
    Job,
    JobAttempt,
    JobAttemptStatus,
    JobEventType,
    JobLease,
    JobStatus,
    OperationIdempotencyCapability,
    RetryPolicy,
    SIDE_EFFECT_STATE_UNKNOWN,
    current_timestamp_iso,
    format_utc_iso,
    parse_utc_iso,
    sanitize_bounded_dict,
)
from core.jobs.queue import PersistentJobQueue, SQLiteJobQueue
from core.jobs.repository import JobRepository
from core.jobs.sqlite import SQLiteJobRepository

logger = logging.getLogger("agent_engine.jobs.worker")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOBS_DB_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")

SUPPORTED_JOB_TYPES: Set[str] = {
    "chat",
    "eval",
    "batch_eval",
    "summary",
    "document_summary",
    "agent_task",
    "test_job",
    "workflow_step",
    "pipeline",
    "skill",
}


def generate_worker_id() -> str:
    """Generate canonical worker ID with 'wrk_' prefix."""
    return f"wrk_{uuid.uuid4().hex[:12]}"


class JobExecutionRequestFactory:
    """Constructs canonical ExecutionRequest instances from durable Job specifications.

    Validates job purpose/type, bounds inputs, preserves project context,
    and prevents deserialization or leakage of secret credentials.
    """

    def __init__(self, supported_types: Optional[Set[str]] = None):
        self.supported_types = supported_types or SUPPORTED_JOB_TYPES

    def create_execution_request(self, job: Job) -> ExecutionRequest:
        """Create a validated ExecutionRequest from a canonical Job."""
        if job.job_type not in self.supported_types:
            raise UnsupportedJobTypeError(
                f"Job type '{job.job_type}' is not supported by the worker runtime. "
                f"Supported types: {sorted(self.supported_types)}"
            )

        summary = sanitize_bounded_dict(job.payload_summary)

        # Extract prompt or construct default task prompt
        raw_prompt = summary.get("prompt") or summary.get("task")
        if isinstance(raw_prompt, str) and raw_prompt.strip():
            prompt = raw_prompt.strip()[:16384]
        else:
            prompt = f"Execute durable job {job.job_id} of type {job.job_type}"

        # Clean inputs extracting only non-sensitive bounded data
        cleaned_inputs: Dict[str, Any] = {}
        for k, v in summary.items():
            if k in ("prompt", "task", "session_id", "project_id", "token_budget"):
                continue
            cleaned_inputs[k] = v

        # Add durable job tracking metadata to inputs
        cleaned_inputs["job_id"] = job.job_id
        cleaned_inputs["job_type"] = job.job_type

        # Project and session scoping
        project_id = job.project_id or summary.get("project_id") or "default_project"
        session_id = summary.get("session_id")

        # Bounded token budget
        raw_budget = summary.get("token_budget", 8000)
        try:
            token_budget = max(100, min(int(raw_budget), 32000))
        except (ValueError, TypeError):
            token_budget = 8000

        # Map job type to ExecutionRequest task_type
        task_type = "chat"
        if job.job_type in ("eval", "batch_eval"):
            task_type = "agent_task"
        elif job.job_type in ("summary", "document_summary"):
            task_type = "chat"
        elif job.job_type == "test_job":
            task_type = "chat"
        elif job.job_type in ("workflow_step", "pipeline", "skill"):
            task_type = "agent_task"

        return ExecutionRequest(
            id=generate_request_id(),
            project_id=str(project_id),
            session_id=str(session_id) if session_id else None,
            task_type=task_type,
            prompt=prompt,
            inputs=cleaned_inputs,
            token_budget=token_budget,
            cancel_on_disconnect=False,
        )


class WorkerContext:
    """Thread-safe context tracking active job execution in a worker."""

    def __init__(self, lease: JobLease, attempt: JobAttempt, control_generation: int = 0):
        self.lease = lease
        self.attempt = attempt
        self.cancellation_token = CancellationToken(attempt.attempt_id)
        self.lease_lost = False
        self.control_generation = control_generation
        self.control_intent_observed: Optional[ControlIntent] = None
        self.timeout_observed = False
        self.execution_completed = threading.Event()
        self.execution_result: Optional[ExecutionResult] = None
        self.execution_error: Optional[Exception] = None


class JobWorker:
    """Authoritative background worker service executing durable jobs through ExecutionCoordinator."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        worker_id: Optional[str] = None,
        repo: Optional[JobRepository] = None,
        queue: Optional[PersistentJobQueue] = None,
        coordinator: Optional[ExecutionCoordinator] = None,
        request_factory: Optional[JobExecutionRequestFactory] = None,
        retry_policy: Optional[RetryPolicy] = None,
        idempotency_store: Optional[IdempotencyStore] = None,
        control_service: Optional[JobControlService] = None,
        lease_ttl_seconds: float = 60.0,
        heartbeat_interval_seconds: Optional[float] = None,
        poll_interval_seconds: float = 1.0,
        drain_timeout_seconds: float = 5.0,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.db_path = db_path or DEFAULT_JOBS_DB_PATH
        self.worker_id = worker_id or generate_worker_id()
        self.started_at = current_timestamp_iso()
        self.pid = os.getpid()

        self.repo = repo or SQLiteJobRepository(db_path=self.db_path)
        self.queue = queue or SQLiteJobQueue(db_path=self.db_path, clock=clock)
        self.retry_policy = retry_policy
        self.idempotency_store = idempotency_store or SQLiteIdempotencyStore(
            db_path=self.db_path, clock=clock
        )
        self.control_service = control_service or JobControlService(
            db_path=self.db_path, repo=self.repo, queue=self.queue, clock=clock
        )
        if coordinator is not None:
            self.coordinator = coordinator
        else:
            test_mode = os.environ.get("AGENT_ENGINE_WORKER_TEST_DISPATCH")
            if test_mode == "blocking":

                def blocking_dispatch(ctx: Any, tier: Any, prov: Any, model: Any) -> Any:
                    time.sleep(60.0)
                    return {"response": "blocked"}

                self.coordinator = ExecutionCoordinator(dispatch_override=blocking_dispatch)
            elif test_mode == "fast":

                def fast_dispatch(ctx: Any, tier: Any, prov: Any, model: Any) -> Any:
                    return {"response": "fast_ok"}

                self.coordinator = ExecutionCoordinator(dispatch_override=fast_dispatch)
            else:
                self.coordinator = ExecutionCoordinator()
        self.request_factory = request_factory or JobExecutionRequestFactory()

        self.lease_ttl_seconds = lease_ttl_seconds
        # Invariant: heartbeat interval must be comfortably below TTL (conceptually <= TTL / 3)
        self.heartbeat_interval_seconds = (
            heartbeat_interval_seconds
            if heartbeat_interval_seconds is not None
            else max(1.0, self.lease_ttl_seconds / 3.0)
        )
        if self.heartbeat_interval_seconds >= self.lease_ttl_seconds:
            raise ValueError(
                f"heartbeat_interval_seconds ({self.heartbeat_interval_seconds}) must be strictly less "
                f"than lease_ttl_seconds ({self.lease_ttl_seconds})."
            )

        self.poll_interval_seconds = poll_interval_seconds
        self.drain_timeout_seconds = drain_timeout_seconds
        self._clock = clock

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._active_context: Optional[WorkerContext] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()

        logger.info(
            "Initialized JobWorker worker_id=%s pid=%d lease_ttl=%.1fs heartbeat_interval=%.1fs",
            self.worker_id,
            self.pid,
            self.lease_ttl_seconds,
            self.heartbeat_interval_seconds,
        )

    def _now_dt(self, override: Optional[Union[datetime, str]] = None) -> datetime:
        if override is not None:
            if isinstance(override, str):
                return parse_utc_iso(override)
            if override.tzinfo is None:
                return override.replace(tzinfo=timezone.utc)
            return override.astimezone(timezone.utc)
        if self._clock is not None:
            c = self._clock()
            if c.tzinfo is None:
                return c.replace(tzinfo=timezone.utc)
            return c.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    # --------------------------------------------------------------------------
    # Fenced DB Operations
    # --------------------------------------------------------------------------

    def begin_claimed_attempt(
        self,
        lease: JobLease,
        now: Optional[Union[datetime, str]] = None,
    ) -> JobAttempt:
        """Atomically verify lease authority, reconcile any prior orphaned attempt,
        transition Job to RUNNING, and persist a new JobAttempt.

        Raises:
            StaleLeaseError: If the lease is superseded or invalid.
            LeaseExpiredError: If the lease has already expired.
            InvalidLeaseError: If owner or token does not match.
            JobNotClaimableError: If the job is in terminal or paused state.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        if not isinstance(self.queue, SQLiteJobQueue):
            raise NotImplementedError("begin_claimed_attempt currently requires SQLiteJobQueue")

        with self._lock:
            conn = self.queue._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # 1. Verify lease authority in job_queue
                cursor.execute(
                    """
                    SELECT queue_entry_id, lease_owner, lease_token, lease_generation, lease_expires_at
                    FROM job_queue WHERE job_id = ?
                    """,
                    (lease.job_id,),
                )
                q_row = cursor.fetchone()
                if not q_row:
                    conn.rollback()
                    raise InvalidLeaseError(f"No queue entry for job {lease.job_id}.")

                if q_row["lease_generation"] != lease.lease_generation:
                    conn.rollback()
                    raise StaleLeaseError(
                        f"Cannot begin attempt for job {lease.job_id}: lease generation {lease.lease_generation} "
                        f"is stale (current active generation is {q_row['lease_generation']})."
                    )

                if (
                    q_row["lease_owner"] != self.worker_id
                    or q_row["lease_token"] != lease.lease_token
                ):
                    conn.rollback()
                    raise InvalidLeaseError(
                        f"Cannot begin attempt for job {lease.job_id}: lease authority mismatch."
                    )

                if q_row["lease_expires_at"] is None or q_row["lease_expires_at"] <= now_iso:
                    conn.rollback()
                    raise LeaseExpiredError(
                        f"Cannot begin attempt for job {lease.job_id}: lease expired at {q_row['lease_expires_at']}."
                    )

                # 2. Verify Job state
                cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (lease.job_id,))
                j_row = cursor.fetchone()
                if not j_row:
                    conn.rollback()
                    raise JobNotFoundError(f"Job {lease.job_id} not found.")

                curr_status = JobStatus(j_row["status"])
                if curr_status not in (JobStatus.READY, JobStatus.RUNNING, JobStatus.WAITING):
                    conn.rollback()
                    raise JobNotClaimableError(
                        f"Job {lease.job_id} in status '{curr_status.value}' cannot start attempt."
                    )

                # 3. Crash Recovery / Reconciliation:
                # Inspect any prior non-terminal attempt from an older generation or crashed worker
                cursor.execute(
                    """
                    SELECT attempt_id, attempt_number, status, worker_id, lease_generation
                    FROM job_attempts
                    WHERE job_id = ? AND status IN ('pending', 'running')
                    ORDER BY attempt_number DESC
                    LIMIT 1
                    """,
                    (lease.job_id,),
                )
                prior_att = cursor.fetchone()
                if prior_att:
                    prior_id = prior_att["attempt_id"]
                    prior_worker = prior_att["worker_id"] or "unknown_worker"
                    prior_gen = prior_att["lease_generation"]

                    # Reconcile prior attempt
                    cursor.execute(
                        """
                        UPDATE job_attempts
                        SET status = 'failed',
                            finished_at = ?,
                            failure_classification = ?,
                            failure_message = ?
                        WHERE attempt_id = ?
                        """,
                        (
                            now_iso,
                            FAILURE_CLASSIFICATION_WORKER_CRASH_OR_LEASE_LOST,
                            f"Prior worker {prior_worker} (lease gen {prior_gen}) lost lease or crashed; "
                            f"reconciled on reclaim by worker {self.worker_id} (lease gen {lease.lease_generation}). "
                            f"Execution outcome and external side-effect state remain UNKNOWN.",
                            prior_id,
                        ),
                    )

                    # Append durable ATTEMPT_RECONCILED event
                    cursor.execute(
                        "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
                        (lease.job_id,),
                    )
                    seq_num = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO job_events (
                            event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"jev_{uuid.uuid4().hex[:12]}",
                            lease.job_id,
                            prior_id,
                            JobEventType.ATTEMPT_RECONCILED.value,
                            seq_num,
                            now_iso,
                            json.dumps(
                                {
                                    "prior_attempt_id": prior_id,
                                    "prior_worker_id": prior_worker,
                                    "prior_lease_generation": prior_gen,
                                    "reclaiming_worker_id": self.worker_id,
                                    "reclaiming_lease_generation": lease.lease_generation,
                                    "execution_outcome": EXECUTION_OUTCOME_UNKNOWN,
                                    "side_effect_state": SIDE_EFFECT_STATE_UNKNOWN,
                                }
                            ),
                        ),
                    )

                    # Reconcile any abandoned idempotency records left by prior attempt
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='job_idempotency_records'"
                    )
                    if cursor.fetchone():
                        cursor.execute(
                            """
                            SELECT idempotency_key, operation_kind, capability, status
                            FROM job_idempotency_records
                            WHERE job_id = ? AND claimed_by_attempt = ? AND status IN ('reserved', 'in_progress')
                            """,
                            (lease.job_id, prior_id),
                        )
                        for ab_row in cursor.fetchall():
                            ab_key = ab_row["idempotency_key"]
                            ab_op = ab_row["operation_kind"]
                            ab_cap = ab_row["capability"]
                            ab_status = ab_row["status"]

                            cursor.execute(
                                """
                                UPDATE job_idempotency_records
                                SET status = ?, updated_at = ?
                                WHERE idempotency_key = ?
                                """,
                                (IdempotencyRecordStatus.OUTCOME_UNKNOWN.value, now_iso, ab_key),
                            )

                            cursor.execute(
                                "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
                                (lease.job_id,),
                            )
                            ab_seq = cursor.fetchone()[0]
                            cursor.execute(
                                """
                                INSERT INTO job_events (
                                    event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    f"jev_{uuid.uuid4().hex[:12]}",
                                    lease.job_id,
                                    prior_id,
                                    JobEventType.IDEMPOTENCY_ABANDONED_RECONCILED.value,
                                    ab_seq,
                                    now_iso,
                                    json.dumps(
                                        {
                                            "idempotency_key": ab_key,
                                            "operation_kind": ab_op,
                                            "prior_attempt_id": prior_id,
                                            "prior_status": ab_status,
                                            "reconciling_worker_id": self.worker_id,
                                            "reclaiming_lease_generation": lease.lease_generation,
                                            "capability": ab_cap,
                                            "resolved_status": IdempotencyRecordStatus.OUTCOME_UNKNOWN.value,
                                        }
                                    ),
                                ),
                            )

                # 4. Calculate next monotonic attempt number
                cursor.execute(
                    "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM job_attempts WHERE job_id = ?",
                    (lease.job_id,),
                )
                next_att_num = cursor.fetchone()[0]

                attempt = JobAttempt(
                    job_id=lease.job_id,
                    attempt_number=next_att_num,
                    status=JobAttemptStatus.RUNNING,
                    worker_id=self.worker_id,
                    lease_generation=lease.lease_generation,
                    started_at=now_iso,
                )

                cursor.execute(
                    """
                    INSERT INTO job_attempts (
                        attempt_id, job_id, attempt_number, execution_id,
                        status, worker_id, lease_generation, started_at, finished_at,
                        failure_classification, failure_message
                    ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL, NULL, NULL)
                    """,
                    (
                        attempt.attempt_id,
                        attempt.job_id,
                        attempt.attempt_number,
                        attempt.status.value,
                        attempt.worker_id,
                        attempt.lease_generation,
                        attempt.started_at,
                    ),
                )

                # 5. Transition Job status to RUNNING and persist timeout deadline once at attempt 1
                cursor.execute(
                    "SELECT timeout_seconds, timeout_at, payload_summary_json FROM jobs WHERE job_id = ?",
                    (lease.job_id,),
                )
                j_ctrl_row = cursor.fetchone()
                if j_ctrl_row:
                    t_secs = j_ctrl_row["timeout_seconds"]
                    if t_secs is None and j_ctrl_row["payload_summary_json"]:
                        try:
                            summary_dict = json.loads(j_ctrl_row["payload_summary_json"])
                            if "timeout_seconds" in summary_dict:
                                t_secs = int(summary_dict["timeout_seconds"])
                        except Exception:
                            pass
                    t_at = j_ctrl_row["timeout_at"]
                    if t_secs is not None and t_at is None:
                        timeout_dt = now_dt + timedelta(seconds=t_secs)
                        timeout_iso = format_utc_iso(timeout_dt)
                        cursor.execute(
                            """
                            UPDATE jobs
                            SET status = 'running',
                                updated_at = ?,
                                timeout_seconds = COALESCE(timeout_seconds, ?),
                                timeout_at = ?
                            WHERE job_id = ?
                            """,
                            (now_iso, t_secs, timeout_iso, lease.job_id),
                        )
                    else:
                        cursor.execute(
                            "UPDATE jobs SET status = 'running', updated_at = ? WHERE job_id = ?",
                            (now_iso, lease.job_id),
                        )
                else:
                    cursor.execute(
                        "UPDATE jobs SET status = 'running', updated_at = ? WHERE job_id = ?",
                        (now_iso, lease.job_id),
                    )

                # 6. Append WORKER_ATTEMPT_STARTED event
                cursor.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
                    (lease.job_id,),
                )
                seq_num = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO job_events (
                        event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"jev_{uuid.uuid4().hex[:12]}",
                        lease.job_id,
                        attempt.attempt_id,
                        JobEventType.WORKER_ATTEMPT_STARTED.value,
                        seq_num,
                        now_iso,
                        json.dumps(
                            {
                                "worker_id": self.worker_id,
                                "attempt_id": attempt.attempt_id,
                                "lease_generation": lease.lease_generation,
                            }
                        ),
                    ),
                )

                conn.commit()

                logger.info(
                    "Worker %s began attempt %s (num=%d, gen=%d) for job %s",
                    self.worker_id,
                    attempt.attempt_id,
                    attempt.attempt_number,
                    lease.lease_generation,
                    lease.job_id,
                )
                return attempt
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self.queue._is_memory:
                    conn.close()

    def bind_execution_to_attempt(
        self,
        job_id: str,
        attempt_id: str,
        lease: JobLease,
        execution_id: str,
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Atomically bind canonical execution_id to the active attempt, verified under lease fencing."""
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        if not isinstance(self.queue, SQLiteJobQueue):
            raise NotImplementedError("bind_execution_to_attempt requires SQLiteJobQueue")

        with self._lock:
            conn = self.queue._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # Fence check
                cursor.execute(
                    """
                    SELECT lease_owner, lease_token, lease_generation, lease_expires_at
                    FROM job_queue WHERE job_id = ?
                    """,
                    (job_id,),
                )
                q_row = cursor.fetchone()
                if not q_row:
                    conn.rollback()
                    raise InvalidLeaseError(f"No queue entry for job {job_id}.")

                if (
                    q_row["lease_generation"] != lease.lease_generation
                    or q_row["lease_owner"] != self.worker_id
                    or q_row["lease_token"] != lease.lease_token
                ):
                    conn.rollback()
                    raise StaleLeaseError(
                        f"Cannot bind execution to attempt: lease authority lost for job {job_id}."
                    )

                if q_row["lease_expires_at"] is None or q_row["lease_expires_at"] <= now_iso:
                    conn.rollback()
                    raise LeaseExpiredError(
                        f"Cannot bind execution to attempt: lease expired for job {job_id}."
                    )

                # Update execution_id on attempt
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET execution_id = ?
                    WHERE attempt_id = ? AND job_id = ? AND worker_id = ?
                    """,
                    (execution_id, attempt_id, job_id, self.worker_id),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    raise InvalidLeaseError(f"Failed to bind execution_id to attempt {attempt_id}.")

                # Emit EXECUTION_BOUND event
                cursor.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
                    (job_id,),
                )
                seq_num = cursor.fetchone()[0]
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
                        JobEventType.EXECUTION_BOUND.value,
                        seq_num,
                        now_iso,
                        json.dumps(
                            {
                                "execution_id": execution_id,
                                "worker_id": self.worker_id,
                                "lease_generation": lease.lease_generation,
                            }
                        ),
                    ),
                )

                conn.commit()
                logger.info(
                    "Worker %s bound execution %s to attempt %s for job %s",
                    self.worker_id,
                    execution_id,
                    attempt_id,
                    job_id,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self.queue._is_memory:
                    conn.close()

    def finalize_claimed_attempt(
        self,
        job_id: str,
        attempt_id: str,
        lease: JobLease,
        target_status: JobStatus,
        failure_classification: Optional[str] = None,
        failure_message: Optional[str] = None,
        expected_control_generation: Optional[int] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Atomically verify lease authority and finalize both JobAttempt and Job,
        removing the job from the active delivery queue.

        Stale workers (whose lease expired or was superseded) are strictly rejected
        with StaleLeaseError to prevent stale completion commits.
        """
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        if not isinstance(self.queue, SQLiteJobQueue):
            raise NotImplementedError("finalize_claimed_attempt requires SQLiteJobQueue")

        with self._lock:
            conn = self.queue._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                # 1. Critical Fence Check: revalidate active lease
                cursor.execute(
                    """
                    SELECT lease_owner, lease_token, lease_generation, lease_expires_at
                    FROM job_queue WHERE job_id = ?
                    """,
                    (job_id,),
                )
                q_row = cursor.fetchone()
                if not q_row:
                    conn.rollback()
                    raise StaleLeaseError(
                        f"Cannot finalize job {job_id}: queue entry does not exist or was already removed."
                    )

                if q_row["lease_generation"] != lease.lease_generation:
                    conn.rollback()
                    raise StaleLeaseError(
                        f"Cannot finalize job {job_id}: lease generation {lease.lease_generation} "
                        f"is stale (current active generation is {q_row['lease_generation']})."
                    )

                if (
                    q_row["lease_owner"] != self.worker_id
                    or q_row["lease_token"] != lease.lease_token
                ):
                    conn.rollback()
                    raise InvalidLeaseError(
                        f"Cannot finalize job {job_id}: worker authority mismatch."
                    )

                if q_row["lease_expires_at"] is None or q_row["lease_expires_at"] <= now_iso:
                    conn.rollback()
                    raise LeaseExpiredError(
                        f"Cannot finalize job {job_id}: lease expired at {q_row['lease_expires_at']}."
                    )

                # 1b. Control and timeout fence check
                cursor.execute(
                    "SELECT control_intent, control_generation, timeout_at FROM jobs WHERE job_id = ?",
                    (job_id,),
                )
                j_ctrl_row = cursor.fetchone()
                if j_ctrl_row:
                    if (
                        expected_control_generation is not None
                        and j_ctrl_row["control_generation"] != expected_control_generation
                    ):
                        conn.rollback()
                        raise StaleControlGenerationError(
                            f"Cannot finalize job {job_id}: worker control generation "
                            f"{expected_control_generation} is stale (current generation is {j_ctrl_row['control_generation']})."
                        )
                    if j_ctrl_row["timeout_at"] and now_dt >= parse_utc_iso(
                        j_ctrl_row["timeout_at"]
                    ):
                        conn.rollback()
                        self.control_service.acknowledge_timeout(
                            job_id, attempt_id, self.worker_id, now=now
                        )
                        return
                    if j_ctrl_row["control_intent"] == ControlIntent.CANCEL_REQUESTED.value:
                        conn.rollback()
                        self.control_service.acknowledge_cancellation(
                            job_id,
                            attempt_id,
                            j_ctrl_row["control_generation"],
                            self.worker_id,
                            now=now,
                        )
                        return
                    if j_ctrl_row["control_intent"] == ControlIntent.PAUSE_REQUESTED.value:
                        conn.rollback()
                        self.control_service.acknowledge_pause(
                            job_id,
                            attempt_id,
                            j_ctrl_row["control_generation"],
                            self.worker_id,
                            now=now,
                        )
                        return

                # 2. Map target status to attempt status
                if target_status == JobStatus.COMPLETED:
                    att_status = JobAttemptStatus.COMPLETED
                    terminal = True
                    event_type = JobEventType.JOB_COMPLETED
                elif target_status == JobStatus.FAILED:
                    att_status = JobAttemptStatus.FAILED
                    terminal = True
                    event_type = JobEventType.JOB_FAILED
                elif target_status == JobStatus.PARTIAL:
                    att_status = JobAttemptStatus.COMPLETED
                    terminal = True
                    event_type = JobEventType.JOB_COMPLETED
                elif target_status == JobStatus.BLOCKED:
                    att_status = JobAttemptStatus.FAILED
                    terminal = False
                    event_type = JobEventType.JOB_STATE_CHANGED
                elif target_status == JobStatus.WAITING:
                    att_status = JobAttemptStatus.PENDING
                    terminal = False
                    event_type = JobEventType.JOB_STATE_CHANGED
                else:
                    att_status = JobAttemptStatus.FAILED
                    terminal = True
                    event_type = JobEventType.JOB_FAILED

                # 3. Update JobAttempt
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET status = ?,
                        finished_at = ?,
                        failure_classification = ?,
                        failure_message = ?
                    WHERE attempt_id = ? AND job_id = ? AND worker_id = ?
                    """,
                    (
                        att_status.value,
                        now_iso,
                        failure_classification,
                        failure_message,
                        attempt_id,
                        job_id,
                        self.worker_id,
                    ),
                )

                # 4. Update Job
                completed_at = now_iso if terminal else None
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = ?, control_intent = 'none', updated_at = ?, completed_at = ?
                    WHERE job_id = ?
                    """,
                    (target_status.value, now_iso, completed_at, job_id),
                )

                # 5. Remove queue entry
                cursor.execute("DELETE FROM job_queue WHERE job_id = ?", (job_id,))

                # 6. Append audit event
                cursor.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
                    (job_id,),
                )
                seq_num = cursor.fetchone()[0]
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
                        now_iso,
                        json.dumps(
                            {
                                "worker_id": self.worker_id,
                                "attempt_id": attempt_id,
                                "status": target_status.value,
                                "lease_generation": lease.lease_generation,
                            }
                        ),
                    ),
                )

                conn.commit()
                logger.info(
                    "Worker %s finalized job %s (attempt %s) to %s",
                    self.worker_id,
                    job_id,
                    attempt_id,
                    target_status.value,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self.queue._is_memory:
                    conn.close()

    # --------------------------------------------------------------------------
    # Heartbeat Management
    # --------------------------------------------------------------------------

    def _start_heartbeat(self, context: WorkerContext) -> None:
        """Start background heartbeat thread extending the lease periodically."""
        self._heartbeat_stop.clear()

        def heartbeat_worker() -> None:
            while not self._heartbeat_stop.is_set():
                # Sleep in short slices for prompt response on stop
                if self._heartbeat_stop.wait(self.heartbeat_interval_seconds):
                    break

                try:
                    self.queue.extend_lease(
                        context.lease.job_id,
                        context.lease.lease_token,
                        context.lease.lease_generation,
                        duration_seconds=self.lease_ttl_seconds,
                        record_event=False,
                    )
                    logger.debug(
                        "Worker %s extended lease for job %s (gen %d)",
                        self.worker_id,
                        context.lease.job_id,
                        context.lease.lease_generation,
                    )
                except Exception as ex:
                    # Heartbeat loss means authority loss!
                    logger.warning(
                        "Worker %s lost lease authority for job %s (gen %d): %s",
                        self.worker_id,
                        context.lease.job_id,
                        context.lease.lease_generation,
                        ex,
                    )
                    context.lease_lost = True
                    context.cancellation_token.cancel()
                    break

                # Check control intent and timeout deadline
                try:
                    conn = self.queue._get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT control_intent, control_generation, timeout_at FROM jobs WHERE job_id = ?",
                        (context.lease.job_id,),
                    )
                    ctrl_row = cursor.fetchone()
                    if not self.queue._is_memory:
                        conn.close()

                    if ctrl_row:
                        intent_val = ctrl_row["control_intent"]
                        ctrl_gen = ctrl_row["control_generation"]
                        t_at_str = ctrl_row["timeout_at"]

                        if intent_val == ControlIntent.PAUSE_REQUESTED.value:
                            logger.info(
                                "Worker %s detected PAUSE_REQUESTED for job %s (gen %d)",
                                self.worker_id,
                                context.lease.job_id,
                                ctrl_gen,
                            )
                            context.control_intent_observed = ControlIntent.PAUSE_REQUESTED
                            context.control_generation = ctrl_gen
                            context.cancellation_token.cancel(
                                reason="pause_requested", actor="operator"
                            )

                        elif intent_val == ControlIntent.CANCEL_REQUESTED.value:
                            logger.info(
                                "Worker %s detected CANCEL_REQUESTED for job %s (gen %d)",
                                self.worker_id,
                                context.lease.job_id,
                                ctrl_gen,
                            )
                            context.control_intent_observed = ControlIntent.CANCEL_REQUESTED
                            context.control_generation = ctrl_gen
                            context.cancellation_token.cancel(
                                reason=CancellationReason.USER_REQUEST, actor="operator"
                            )

                        if t_at_str:
                            deadline_dt = parse_utc_iso(t_at_str)
                            curr_dt = self._now_dt()
                            if curr_dt >= deadline_dt:
                                logger.info(
                                    "Worker %s detected deadline timeout for job %s (deadline %s)",
                                    self.worker_id,
                                    context.lease.job_id,
                                    t_at_str,
                                )
                                context.timeout_observed = True
                                context.cancellation_token.cancel(
                                    reason=CancellationReason.TIMEOUT, actor="system"
                                )
                except Exception as ctrl_ex:
                    logger.debug("Worker heartbeat control check error: %s", ctrl_ex)

        self._heartbeat_thread = threading.Thread(
            target=heartbeat_worker,
            name=f"worker-heartbeat-{context.lease.job_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        """Signal and join the background heartbeat thread."""
        self._heartbeat_stop.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
        self._heartbeat_thread = None

    def _mark_attempt_failed(
        self,
        job_id: str,
        attempt_id: str,
        classification: Optional[str] = None,
        failure_message: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Mark an attempt failed without removing the queue entry or finalizing the parent job."""
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self.queue._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET status = 'failed',
                        finished_at = ?,
                        failure_classification = ?,
                        failure_message = ?
                    WHERE attempt_id = ? AND job_id = ? AND worker_id = ?
                    """,
                    (now_iso, classification, failure_message, attempt_id, job_id, self.worker_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self.queue._is_memory:
                    conn.close()

    def _record_event(
        self,
        job_id: str,
        attempt_id: Optional[str],
        event_type: JobEventType,
        metadata: Dict[str, Any],
        now: Optional[Union[datetime, str]] = None,
    ) -> None:
        """Append an audit event with per-job monotonic sequence number."""
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self.queue._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
                    (job_id,),
                )
                seq_num = cursor.fetchone()[0]
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
                        now_iso,
                        json.dumps(sanitize_bounded_dict(metadata)),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self.queue._is_memory:
                    conn.close()

    def execute_idempotent_operation(
        self,
        job_id: str,
        operation_kind: str,
        args: Dict[str, Any],
        fn: Callable[[], Any],
        capability: OperationIdempotencyCapability = OperationIdempotencyCapability.UNKNOWN,
        attempt_id: Optional[str] = None,
        scope: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> Any:
        """Execute an operation with durable idempotency tracking under the current worker attempt."""
        att_id = attempt_id
        if att_id is None and self._active_context is not None:
            att_id = self._active_context.attempt.attempt_id

        return self.idempotency_store.execute_with_idempotency(
            job_id=job_id,
            operation_kind=operation_kind,
            args=args,
            fn=fn,
            capability=capability,
            attempt_id=att_id,
            scope=scope,
            now=now,
        )

    # --------------------------------------------------------------------------
    # Execution Lifecycle Step
    # --------------------------------------------------------------------------

    def step(self, now: Optional[Union[datetime, str]] = None) -> bool:
        """Process at most one claimed job.

        Returns:
            True if a job was claimed and processed, False if queue was empty or worker stopping.
        """
        if self._stop_event.is_set():
            return False

        # 0. Check and enforce pre-claim deadlines
        self.control_service.check_and_apply_timeouts(now=now)

        # 1. Claim next READY job
        lease = self.queue.claim_next(
            self.worker_id,
            lease_duration_seconds=self.lease_ttl_seconds,
            now=now,
        )
        if not lease:
            return False

        # 2. Retrieve Job definition
        job = self.repo.get_job(lease.job_id)
        if not job:
            logger.error("Claimed job %s not found in repository; releasing lease", lease.job_id)
            try:
                self.queue.release_lease(
                    lease.job_id, lease.lease_token, lease.lease_generation, now=now
                )
            except Exception:
                pass
            return False

        # 3. Validate job type and construct ExecutionRequest before starting execution
        try:
            exec_request = self.request_factory.create_execution_request(job)
        except UnsupportedJobTypeError as e:
            logger.error(
                "Unrecoverable unsupported job type for job %s: %s; failing attempt and job permanently",
                lease.job_id,
                e,
            )
            # Establish durable attempt required by canonical lifecycle
            attempt = self.begin_claimed_attempt(lease, now=now)
            self.finalize_claimed_attempt(
                job.job_id,
                attempt.attempt_id,
                lease,
                JobStatus.FAILED,
                failure_classification="unsupported_job_type",
                failure_message=str(e)[:1024],
                expected_control_generation=job.control_generation,
                now=now,
            )
            return True
        except (ValueError, TypeError, KeyError) as e:
            logger.error(
                "Unrecoverable permanent job payload error for job %s: %s; failing attempt and job permanently",
                lease.job_id,
                e,
            )
            attempt = self.begin_claimed_attempt(lease, now=now)
            self.finalize_claimed_attempt(
                job.job_id,
                attempt.attempt_id,
                lease,
                JobStatus.FAILED,
                failure_classification="invalid_payload",
                failure_message=str(e)[:1024],
                expected_control_generation=job.control_generation,
                now=now,
            )
            return True
        except Exception as e:
            # Preserve transient/retryable failure semantics separately
            logger.warning(
                "Transient setup failure before execution for job %s: %s; releasing lease",
                lease.job_id,
                e,
            )
            try:
                self.queue.release_lease(
                    lease.job_id, lease.lease_token, lease.lease_generation, now=now
                )
            except Exception:
                pass
            return True

        # 4. Atomically begin claimed attempt (fenced)
        try:
            attempt = self.begin_claimed_attempt(lease, now=now)
        except (StaleLeaseError, LeaseExpiredError, InvalidLeaseError) as e:
            logger.warning(
                "Lease authority rejected starting attempt for job %s: %s", lease.job_id, e
            )
            return True

        # 5. Set up active worker context and heartbeat
        job_current = self.repo.get_job(lease.job_id)
        current_ctrl_gen = job_current.control_generation if job_current else 0
        context = WorkerContext(lease=lease, attempt=attempt, control_generation=current_ctrl_gen)
        with self._lock:
            self._active_context = context

        self._start_heartbeat(context)

        try:
            # 6. Bind canonical execution_id to attempt
            self.bind_execution_to_attempt(
                job.job_id, attempt.attempt_id, lease, exec_request.id, now=now
            )

            # 7. Execute through ExecutionCoordinator
            exec_result = self._execute_coordinator_sync(exec_request, context.cancellation_token)
            context.execution_result = exec_result

            # 8. Stop heartbeat and inspect authority / control outcomes
            self._stop_heartbeat()

            if context.lease_lost:
                logger.warning(
                    "Worker %s lost lease authority during execution of job %s; aborting finalization",
                    self.worker_id,
                    job.job_id,
                )
                return True

            # Check fresh job state for control signals and deadlines
            job_fresh = self.repo.get_job(job.job_id)
            if job_fresh:
                if job_fresh.timeout_at and self._now_dt(override=now) >= parse_utc_iso(
                    job_fresh.timeout_at
                ):
                    context.timeout_observed = True
                if job_fresh.control_intent == ControlIntent.PAUSE_REQUESTED:
                    context.control_intent_observed = ControlIntent.PAUSE_REQUESTED
                    context.control_generation = job_fresh.control_generation
                elif job_fresh.control_intent == ControlIntent.CANCEL_REQUESTED:
                    context.control_intent_observed = ControlIntent.CANCEL_REQUESTED
                    context.control_generation = job_fresh.control_generation

            if context.timeout_observed:
                logger.info(
                    "Worker %s acknowledging timeout for job %s", self.worker_id, job.job_id
                )
                self.control_service.acknowledge_timeout(
                    job.job_id, attempt.attempt_id, self.worker_id, now=now
                )
                return True

            if context.control_intent_observed == ControlIntent.PAUSE_REQUESTED:
                logger.info(
                    "Worker %s acknowledging pause for job %s (gen %d)",
                    self.worker_id,
                    job.job_id,
                    context.control_generation,
                )
                self.control_service.acknowledge_pause(
                    job.job_id,
                    attempt.attempt_id,
                    context.control_generation,
                    self.worker_id,
                    now=now,
                )
                return True

            if context.control_intent_observed == ControlIntent.CANCEL_REQUESTED:
                logger.info(
                    "Worker %s acknowledging cancellation for job %s (gen %d)",
                    self.worker_id,
                    job.job_id,
                    context.control_generation,
                )
                self.control_service.acknowledge_cancellation(
                    job.job_id,
                    attempt.attempt_id,
                    context.control_generation,
                    self.worker_id,
                    now=now,
                )
                return True

            # 9. Map execution outcome to JobStatus
            target_status = self._map_execution_status(exec_result.status)
            fail_class = exec_result.error_code or (
                "execution_failed" if target_status == JobStatus.FAILED else None
            )
            fail_msg = exec_result.error

            if target_status == JobStatus.FAILED:
                # Check retry policy
                policy = self.retry_policy
                if policy is None and "retry_policy" in job.payload_summary:
                    try:
                        policy = RetryPolicy(**job.payload_summary["retry_policy"])
                    except Exception:
                        policy = None

                classification = classify_failure(
                    error=fail_msg,
                    error_code=exec_result.error_code,
                )

                if policy is not None:
                    if (
                        classification in policy.retryable_classifications
                        and attempt.attempt_number < policy.max_attempts
                    ):
                        # Check if control signal arrived before scheduling retry
                        job_check = self.repo.get_job(job.job_id)
                        if job_check and job_check.control_intent == ControlIntent.CANCEL_REQUESTED:
                            self.control_service.acknowledge_cancellation(
                                job.job_id,
                                attempt.attempt_id,
                                job_check.control_generation,
                                self.worker_id,
                                now=now,
                            )
                            return True
                        if job_check and job_check.control_intent == ControlIntent.PAUSE_REQUESTED:
                            self.control_service.acknowledge_pause(
                                job.job_id,
                                attempt.attempt_id,
                                job_check.control_generation,
                                self.worker_id,
                                now=now,
                            )
                            return True

                        # Retryable! Calculate backoff delay
                        delay = policy.calculate_backoff_delay(attempt.attempt_number)
                        now_dt = self._now_dt(override=now)
                        next_avail_dt = now_dt + timedelta(seconds=delay)
                        next_avail_iso = format_utc_iso(next_avail_dt)

                        self._mark_attempt_failed(
                            job_id=job.job_id,
                            attempt_id=attempt.attempt_id,
                            classification=classification.value,
                            failure_message=fail_msg,
                            now=now,
                        )

                        self.queue.requeue_at(
                            job_id=job.job_id,
                            available_at=next_avail_iso,
                            lease_token=lease.lease_token,
                            lease_generation=lease.lease_generation,
                            now=now,
                        )
                        logger.info(
                            "Worker %s scheduled retry for job %s (attempt %d/%d) at %s",
                            self.worker_id,
                            job.job_id,
                            attempt.attempt_number,
                            policy.max_attempts,
                            next_avail_iso,
                        )
                        return True
                    else:
                        if attempt.attempt_number >= policy.max_attempts:
                            self._record_event(
                                job_id=job.job_id,
                                attempt_id=attempt.attempt_id,
                                event_type=JobEventType.RETRY_EXHAUSTED,
                                metadata={
                                    "worker_id": self.worker_id,
                                    "attempt_id": attempt.attempt_id,
                                    "attempt_number": attempt.attempt_number,
                                    "max_attempts": policy.max_attempts,
                                    "classification": classification.value,
                                },
                                now=now,
                            )
                        fail_class = classification.value

            # 10. Atomically finalize attempt and job
            self.finalize_claimed_attempt(
                job.job_id,
                attempt.attempt_id,
                lease,
                target_status,
                failure_classification=fail_class,
                failure_message=fail_msg,
                expected_control_generation=context.control_generation,
                now=now,
            )
        except Exception as ex:
            if not context.lease_lost:
                logger.error(
                    "Execution error for job %s (attempt %s): %s",
                    job.job_id,
                    attempt.attempt_id,
                    ex,
                    exc_info=True,
                )
                policy = self.retry_policy
                if policy is None and "retry_policy" in job.payload_summary:
                    try:
                        policy = RetryPolicy(**job.payload_summary["retry_policy"])
                    except Exception:
                        policy = None

                classification = classify_failure(
                    error=ex,
                    error_code=getattr(ex, "error_code", None),
                )

                if policy is not None and (
                    classification in policy.retryable_classifications
                    and attempt.attempt_number < policy.max_attempts
                ):
                    try:
                        # Check if control signal arrived before scheduling retry
                        job_check = self.repo.get_job(job.job_id)
                        if job_check and job_check.control_intent == ControlIntent.CANCEL_REQUESTED:
                            self.control_service.acknowledge_cancellation(
                                job.job_id,
                                attempt.attempt_id,
                                job_check.control_generation,
                                self.worker_id,
                                now=now,
                            )
                            return True
                        if job_check and job_check.control_intent == ControlIntent.PAUSE_REQUESTED:
                            self.control_service.acknowledge_pause(
                                job.job_id,
                                attempt.attempt_id,
                                job_check.control_generation,
                                self.worker_id,
                                now=now,
                            )
                            return True

                        delay = policy.calculate_backoff_delay(attempt.attempt_number)
                        now_dt = self._now_dt(override=now)
                        next_avail_dt = now_dt + timedelta(seconds=delay)
                        next_avail_iso = format_utc_iso(next_avail_dt)

                        self._mark_attempt_failed(
                            job_id=job.job_id,
                            attempt_id=attempt.attempt_id,
                            classification=classification.value,
                            failure_message=str(ex)[:1024],
                            now=now,
                        )

                        self.queue.requeue_at(
                            job_id=job.job_id,
                            available_at=next_avail_iso,
                            lease_token=lease.lease_token,
                            lease_generation=lease.lease_generation,
                            now=now,
                        )
                        logger.info(
                            "Worker %s scheduled retry on exception for job %s (attempt %d/%d) at %s",
                            self.worker_id,
                            job.job_id,
                            attempt.attempt_number,
                            policy.max_attempts,
                            next_avail_iso,
                        )
                        return True
                    except Exception as retry_ex:
                        logger.warning(
                            "Failed to schedule retry for job %s: %s", job.job_id, retry_ex
                        )

                if policy is not None and attempt.attempt_number >= policy.max_attempts:
                    try:
                        self._record_event(
                            job_id=job.job_id,
                            attempt_id=attempt.attempt_id,
                            event_type=JobEventType.RETRY_EXHAUSTED,
                            metadata={
                                "worker_id": self.worker_id,
                                "attempt_id": attempt.attempt_id,
                                "attempt_number": attempt.attempt_number,
                                "max_attempts": policy.max_attempts,
                                "classification": classification.value,
                            },
                            now=now,
                        )
                    except Exception:
                        pass

                try:
                    self.finalize_claimed_attempt(
                        job.job_id,
                        attempt.attempt_id,
                        lease,
                        JobStatus.FAILED,
                        failure_classification=classification.value if policy else "runtime_error",
                        failure_message=str(ex)[:1024],
                        expected_control_generation=context.control_generation,
                        now=now,
                    )
                except Exception as final_ex:
                    logger.warning("Failed to record failure for job %s: %s", job.job_id, final_ex)
        finally:
            self._stop_heartbeat()
            context.execution_completed.set()
            with self._lock:
                self._active_context = None

        return True

    def _execute_coordinator_sync(
        self,
        request: ExecutionRequest,
        cancellation_token: CancellationToken,
    ) -> ExecutionResult:
        """Synchronously execute ExecutionCoordinator dispatch."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Nested in existing loop (e.g. tests)
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.coordinator.execute(request, cancellation_token=cancellation_token),
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.coordinator.execute(request, cancellation_token=cancellation_token)
                )
        except RuntimeError:
            return asyncio.run(
                self.coordinator.execute(request, cancellation_token=cancellation_token)
            )

    @staticmethod
    def _map_execution_status(status: ExecutionStatus) -> JobStatus:
        """Map canonical ExecutionStatus to durable JobStatus."""
        if status == ExecutionStatus.COMPLETED:
            return JobStatus.COMPLETED
        if status == ExecutionStatus.FAILED:
            return JobStatus.FAILED
        if status == ExecutionStatus.PARTIAL:
            return JobStatus.PARTIAL
        if status == ExecutionStatus.BLOCKED:
            return JobStatus.BLOCKED
        if status == ExecutionStatus.WAITING_FOR_APPROVAL:
            return JobStatus.WAITING
        if status == ExecutionStatus.CANCELLED:
            return JobStatus.CANCELLED
        return JobStatus.FAILED

    # --------------------------------------------------------------------------
    # Worker Loop & Graceful Shutdown
    # --------------------------------------------------------------------------

    def run(self) -> None:
        """Run the continuous worker claim loop until stopped."""
        logger.info("Worker %s entering main claim loop", self.worker_id)
        while not self._stop_event.is_set():
            processed = False
            try:
                processed = self.step()
            except Exception as e:
                logger.error("Unexpected error in worker claim loop: %s", e, exc_info=True)

            if not processed and not self._stop_event.is_set():
                # Empty queue: sleep until poll interval or until woken by stop()
                self._stop_event.wait(self.poll_interval_seconds)

        logger.info("Worker %s exited claim loop", self.worker_id)

    def stop(self, drain_timeout: Optional[float] = None) -> None:
        """Signal the worker to stop claiming new jobs and gracefully drain active work.

        Invariant:
        If active job exceeds drain timeout, worker stops heartbeat and exits WITHOUT
        calling release_lease(), leaving the lease to expire naturally to prevent duplicate execution.
        """
        timeout = drain_timeout if drain_timeout is not None else self.drain_timeout_seconds
        logger.info("Stopping worker %s (drain_timeout=%.1fs)", self.worker_id, timeout)
        self._stop_event.set()

        active: Optional[WorkerContext] = None
        with self._lock:
            active = self._active_context

        if active:
            logger.info("Draining active job %s for up to %.1fs", active.lease.job_id, timeout)
            finished = active.execution_completed.wait(timeout)
            if not finished:
                logger.warning(
                    "Drain timeout exceeded for active job %s; stopping heartbeat and leaving lease to expire naturally",
                    active.lease.job_id,
                )
                # Invariant: do NOT call release_lease() while execution is alive!
                self._stop_heartbeat()

    def close(self) -> None:
        """Clean up worker resources."""
        self.stop()
        if hasattr(self, "idempotency_store") and hasattr(self.idempotency_store, "close"):
            self.idempotency_store.close()
        if hasattr(self.queue, "close"):
            self.queue.close()
        if hasattr(self.repo, "close"):
            self.repo.close()
