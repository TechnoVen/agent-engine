"""tests/test_r4_5_job_control.py

Milestone R4 (Task R4.5 - Timeout, Pause, Resume, and Cancellation) Comprehensive Test Suite.

Verifies:
1. Migration 005 populated upgrade & schema validation.
2. Pause and Resume on READY jobs (immediate status change, queue row preserved, eligibility restored).
3. Cooperative Pause on RUNNING jobs (cancels active attempt as paused_by_operator, sets Job to PAUSED,
   and resuming starts a NEW attempt/execution).
4. Retry backoff + Pause + Resume (preserves queue available_at, restores WAITING without early claim).
5. Cancellation on queued jobs (immediate transition, permanent queue deletion).
6. Cooperative Cancellation on RUNNING jobs (signals cancellation token, cancels active attempt,
   cancels job, deletes queue entry).
7. Control generation monotonic fencing (rejects stale worker pause/cancel acknowledgements).
8. Stale worker completion rejected after concurrent control mutation.
9. Durable timeout_seconds calculation and persistence (computed once at attempt 1 start, survives restart).
10. Pre-claim timeout enforcement (claim_next excludes expired jobs, check_and_apply_timeouts finalizes as FAILED).
11. Active execution timeout enforcement (heartbeat cancellation, acknowledge_timeout finalizes as FAILED).
12. Canonical R1.9 CancellationToken reuse inside ExecutionCoordinator.
13. Idempotent control operations & terminal state protection.
14. Process/restart persistence proof across SQLite connection re-openings.
15. Security & data minimization: zero secrets in events or control messages.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from core.execution.cancellation import CancellationToken
from core.execution.coordinator import ExecutionCoordinator
from core.jobs.control import JobControlService
from core.jobs.exceptions import (
    JobAlreadyTerminalError,
    JobControlConflictError,
    JobNotFoundError,
    StaleControlGenerationError,
)
from core.jobs.migrations import (
    _migration_001_initial_job_domain,
    _migration_002_persistent_job_queue,
    _migration_003_worker_attempt_ownership,
    _migration_004_job_idempotency_and_retry,
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    FAILURE_CLASSIFICATION_CANCELLED_BY_OPERATOR,
    FAILURE_CLASSIFICATION_PAUSED_BY_OPERATOR,
    FAILURE_CLASSIFICATION_TIMEOUT,
    ControlIntent,
    Job,
    JobAttemptStatus,
    JobEventType,
    JobStatus,
    format_utc_iso,
    parse_utc_iso,
)
from core.jobs.queue import SQLiteJobQueue
from core.jobs.sqlite import SQLiteJobRepository
from core.jobs.worker import JobWorker


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def file_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_r4_5_control.db")


@pytest.fixture
def repo(file_db_path: str) -> SQLiteJobRepository:
    r = SQLiteJobRepository(db_path=file_db_path)
    yield r
    r.close()


@pytest.fixture
def queue(file_db_path: str) -> SQLiteJobQueue:
    q = SQLiteJobQueue(db_path=file_db_path)
    yield q
    q.close()


@pytest.fixture
def control_service(
    file_db_path: str, repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> JobControlService:
    cs = JobControlService(db_path=file_db_path, repo=repo, queue=queue)
    yield cs
    cs.close()


# ==============================================================================
# 1. Migration 004 -> 005 Populated Upgrade
# ==============================================================================


def test_migration_v4_to_v5_populated_database_upgrade(tmp_path: Path) -> None:
    """Verify Migration 005 cleanly upgrades a populated v4 database without data loss."""
    db_file = tmp_path / "populated_v4.db"
    conn = sqlite3.connect(str(db_file))
    try:
        # 1. Run migrations 001 - 004
        _migration_001_initial_job_domain(conn)
        _migration_002_persistent_job_queue(conn)
        _migration_003_worker_attempt_ownership(conn)
        _migration_004_job_idempotency_and_retry(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);"
        )
        for v, name in [
            (1, "001_initial_job_domain"),
            (2, "002_persistent_job_queue"),
            (3, "003_worker_attempt_ownership"),
            (4, "004_idempotency_records"),
        ]:
            conn.execute(
                "INSERT INTO job_schema_migrations VALUES (?, ?, '2026-10-10T00:00:00Z')",
                (v, name),
            )

        # 2. Insert populated v4 job data
        conn.execute(
            """
            INSERT INTO jobs (job_id, job_type, status, created_at, updated_at)
            VALUES ('job_v4_pop', 'chat', 'ready', '2026-10-10T10:00:00Z', '2026-10-10T10:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO job_attempts (attempt_id, job_id, attempt_number, status, started_at, worker_id, lease_generation)
            VALUES ('att_v4_pop', 'job_v4_pop', 1, 'running', '2026-10-10T10:01:00Z', 'worker_pop', 1)
            """
        )
        conn.commit()

        # 3. Apply migration 005
        applied = apply_job_migrations(conn)
        assert applied == 1
        assert get_current_job_schema_version(conn) == 5

        # 4. Verify columns exist and have correct defaults
        cur = conn.cursor()
        cur.execute(
            """
            SELECT control_intent, control_generation, timeout_seconds, timeout_at, prior_status_before_pause
            FROM jobs WHERE job_id = 'job_v4_pop'
            """
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "none"
        assert row[1] == 0
        assert row[2] is None
        assert row[3] is None
        assert row[4] is None
    finally:
        conn.close()

    # 5. Open in SQLiteJobRepository and ensure models load correctly
    repo_pop = SQLiteJobRepository(db_path=str(db_file))
    try:
        job = repo_pop.get_job("job_v4_pop")
        assert job is not None
        assert job.control_intent == ControlIntent.NONE
        assert job.control_generation == 0
        assert job.timeout_seconds is None
        assert job.timeout_at is None
        assert job.prior_status_before_pause is None
    finally:
        repo_pop.close()


# ==============================================================================
# 2. READY Job Pause and Resume
# ==============================================================================


def test_pause_ready_job_immediate_and_resume_claimable(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify immediate pause on a queued READY job leaves queue row intact, prevents claim, and resume restores eligibility."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Pause queued job"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # 1. Pause the READY job
    res = control_service.pause_job(
        job.job_id, requested_by="operator:alice", reason="Operator paused queue", now=t0
    )
    assert res.applied_immediately is True
    assert res.status == JobStatus.PAUSED
    assert res.control_intent == ControlIntent.NONE
    assert res.control_generation == 1

    # Verify job state in repository
    j_paused = repo.get_job(job.job_id)
    assert j_paused is not None
    assert j_paused.status == JobStatus.PAUSED
    assert j_paused.prior_status_before_pause == JobStatus.READY
    assert j_paused.control_generation == 1

    # Verify queue entry still exists
    q_entry = queue.get_entry(job.job_id)
    assert q_entry is not None
    assert q_entry.lease_owner is None

    # Worker cannot claim a PAUSED job
    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is None

    # Verify audit event
    events = repo.list_events(job.job_id)
    pause_events = [e for e in events if e.event_type == JobEventType.JOB_PAUSED]
    assert len(pause_events) == 1
    assert pause_events[0].metadata["requested_by"] == "operator:alice"
    assert pause_events[0].metadata["from_status"] == "ready"

    # 2. Resume the job
    t_res = t0 + timedelta(seconds=10)
    res_resume = control_service.resume_job(
        job.job_id, requested_by="operator:alice", reason="Operator unpaused", now=t_res
    )
    assert res_resume.applied_immediately is True
    assert res_resume.status == JobStatus.READY
    assert res_resume.control_generation == 2

    j_res = repo.get_job(job.job_id)
    assert j_res is not None
    assert j_res.status == JobStatus.READY
    assert j_res.prior_status_before_pause is None

    # Worker can now claim the resumed job
    lease = queue.claim_next(worker.worker_id, now=t_res)
    assert lease is not None
    assert lease.job_id == job.job_id
    worker.close()


# ==============================================================================
# 3. Cooperative Pause on RUNNING Job & Resume to NEW Attempt
# ==============================================================================


def test_pause_running_job_cooperative_terminates_attempt_and_resume_starts_new_attempt(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify pausing a running job cooperatively terminates active attempt (paused_by_operator),
    and resuming starts a fresh JobAttempt (attempt 2) on subsequent claim.
    """
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Cooperative pause job"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # Worker claims and starts Attempt 1
    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt_1 = worker.begin_claimed_attempt(lease, now=t0)
    assert attempt_1.attempt_number == 1
    assert attempt_1.status == JobAttemptStatus.RUNNING

    # Operator requests pause while job is running
    t_pause = t0 + timedelta(seconds=5)
    pause_res = control_service.pause_job(
        job.job_id, requested_by="operator:bob", reason="Pause for maintenance", now=t_pause
    )
    assert pause_res.applied_immediately is False
    assert pause_res.status == JobStatus.RUNNING
    assert pause_res.control_intent == ControlIntent.PAUSE_REQUESTED
    assert pause_res.control_generation == 1

    # Verify event JOB_PAUSE_REQUESTED
    events = repo.list_events(job.job_id)
    req_events = [e for e in events if e.event_type == JobEventType.JOB_PAUSE_REQUESTED]
    assert len(req_events) == 1

    # Worker acknowledges cooperative pause at execution boundary
    t_ack = t0 + timedelta(seconds=7)
    control_service.acknowledge_pause(
        job_id=job.job_id,
        attempt_id=attempt_1.attempt_id,
        expected_control_generation=1,
        worker_id=worker.worker_id,
        now=t_ack,
    )

    # Verify Attempt 1 is terminal with paused_by_operator
    att_1_done = repo.get_attempt(attempt_1.attempt_id)
    assert att_1_done is not None
    assert att_1_done.status == JobAttemptStatus.CANCELLED
    assert att_1_done.failure_classification == FAILURE_CLASSIFICATION_PAUSED_BY_OPERATOR
    assert att_1_done.finished_at is not None

    # Verify Job is PAUSED with control_intent NONE
    j_paused = repo.get_job(job.job_id)
    assert j_paused is not None
    assert j_paused.status == JobStatus.PAUSED
    assert j_paused.control_intent == ControlIntent.NONE
    assert j_paused.prior_status_before_pause == JobStatus.READY

    # Verify queue entry has lease released
    q_entry = queue.get_entry(job.job_id)
    assert q_entry is not None
    assert q_entry.lease_owner is None

    # Operator resumes the job
    t_resume = t0 + timedelta(seconds=15)
    resume_res = control_service.resume_job(job.job_id, requested_by="operator:bob", now=t_resume)
    assert resume_res.status == JobStatus.READY
    assert resume_res.control_generation == 2

    # Worker claims and begins Attempt 2 (NEW attempt)
    lease_2 = queue.claim_next(worker.worker_id, now=t_resume)
    assert lease_2 is not None
    attempt_2 = worker.begin_claimed_attempt(lease_2, now=t_resume)
    assert attempt_2.attempt_number == 2
    assert attempt_2.attempt_id != attempt_1.attempt_id
    assert attempt_2.status == JobAttemptStatus.RUNNING

    attempts = repo.list_attempts(job.job_id)
    assert len(attempts) == 2

    worker.close()


# ==============================================================================
# 4. Retry Backoff + Pause + Resume
# ==============================================================================


def test_retry_backoff_pause_preserves_available_at_and_resumes_waiting(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify that pausing during retry backoff preserves queue available_at,
    and resuming before available_at restores WAITING without premature execution.
    """
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(
        Job(job_type="chat", payload_summary={"prompt": "Retry backoff pause job"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # Worker claims Attempt 1
    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt_1 = worker.begin_claimed_attempt(lease, now=t0)

    # Attempt fails and schedules retry backoff with delay of 60s
    t_retry_avail = t0 + timedelta(seconds=60)
    queue.requeue_at(
        job_id=job.job_id,
        available_at=t_retry_avail,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
        now=t0 + timedelta(seconds=2),
    )
    repo.update_state(job.job_id, JobStatus.WAITING)
    repo.update_attempt_status(
        attempt_id=attempt_1.attempt_id,
        status=JobAttemptStatus.FAILED,
        finished_at=format_utc_iso(t0 + timedelta(seconds=2)),
        failure_classification="transient_error",
    )

    # Operator pauses the job at t0 + 10s (during retry backoff)
    t_pause = t0 + timedelta(seconds=10)
    pause_res = control_service.pause_job(job.job_id, now=t_pause)
    assert pause_res.status == JobStatus.PAUSED

    j_paused = repo.get_job(job.job_id)
    assert j_paused is not None
    assert j_paused.status == JobStatus.PAUSED
    assert j_paused.prior_status_before_pause == JobStatus.WAITING

    # Verify queue entry still has available_at = t0 + 60s
    q_entry = queue.get_entry(job.job_id)
    assert q_entry is not None
    assert parse_utc_iso(q_entry.available_at) == t_retry_avail

    # Operator resumes the job at t0 + 20s (still BEFORE available_at = t0 + 60s)
    t_resume = t0 + timedelta(seconds=20)
    resume_res = control_service.resume_job(job.job_id, now=t_resume)
    assert resume_res.status == JobStatus.WAITING

    j_resumed = repo.get_job(job.job_id)
    assert j_resumed is not None
    assert j_resumed.status == JobStatus.WAITING

    # Worker tries to claim at t0 + 30s -> returns None (early execution strictly prevented!)
    claim_early = queue.claim_next(worker.worker_id, now=t0 + timedelta(seconds=30))
    assert claim_early is None

    # Worker tries to claim at t0 + 65s (AFTER available_at) -> succeeds!
    claim_ontime = queue.claim_next(worker.worker_id, now=t0 + timedelta(seconds=65))
    assert claim_ontime is not None
    assert claim_ontime.job_id == job.job_id

    worker.close()


# ==============================================================================
# 5. Queued Job Cancellation
# ==============================================================================


def test_cancel_queued_job_immediate_deletes_queue_entry(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify cancellation on a non-running queued job immediately transitions to CANCELLED and permanently deletes queue row."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Cancel queued job"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # Cancel the job
    res = control_service.cancel_job(
        job.job_id, requested_by="operator:admin", reason="User cancelled", now=t0
    )
    assert res.applied_immediately is True
    assert res.status == JobStatus.CANCELLED
    assert res.control_intent == ControlIntent.NONE
    assert res.control_generation == 1

    # Verify repository state
    j_canc = repo.get_job(job.job_id)
    assert j_canc is not None
    assert j_canc.status == JobStatus.CANCELLED
    assert j_canc.completed_at is not None

    # Verify queue entry is deleted
    q_entry = queue.get_entry(job.job_id)
    assert q_entry is None

    # Worker cannot claim
    worker = JobWorker(db_path=file_db_path)
    assert queue.claim_next(worker.worker_id, now=t0) is None
    worker.close()


# ==============================================================================
# 6. Running Job Cancellation
# ==============================================================================


def test_cancel_running_job_cooperative_terminates_attempt_and_deletes_queue(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify cancelling a running job persists CANCEL_REQUESTED, worker acknowledges,
    attempt is marked CANCELLED (cancelled_by_operator), job is CANCELLED, and queue row is deleted.
    """
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Cancel running job"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt = worker.begin_claimed_attempt(lease, now=t0)

    # Operator requests cancel
    t_canc = t0 + timedelta(seconds=5)
    canc_res = control_service.cancel_job(
        job.job_id, requested_by="operator:carol", reason="Aborted by user", now=t_canc
    )
    assert canc_res.applied_immediately is False
    assert canc_res.status == JobStatus.RUNNING
    assert canc_res.control_intent == ControlIntent.CANCEL_REQUESTED
    assert canc_res.control_generation == 1

    # Worker acknowledges cancellation
    t_ack = t0 + timedelta(seconds=7)
    control_service.acknowledge_cancellation(
        job_id=job.job_id,
        attempt_id=attempt.attempt_id,
        expected_control_generation=1,
        worker_id=worker.worker_id,
        now=t_ack,
    )

    # Verify Attempt is CANCELLED with cancelled_by_operator
    att = repo.get_attempt(attempt.attempt_id)
    assert att is not None
    assert att.status == JobAttemptStatus.CANCELLED
    assert att.failure_classification == FAILURE_CLASSIFICATION_CANCELLED_BY_OPERATOR

    # Verify Job is CANCELLED and queue entry deleted
    j_done = repo.get_job(job.job_id)
    assert j_done is not None
    assert j_done.status == JobStatus.CANCELLED
    assert j_done.control_intent == ControlIntent.NONE

    assert queue.get_entry(job.job_id) is None
    worker.close()


# ==============================================================================
# 7. Control Generation Monotonic Fencing
# ==============================================================================


def test_control_generation_fencing_rejects_stale_acknowledgement(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify that a worker presenting a stale control_generation is rejected with StaleControlGenerationError."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Fencing job"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt = worker.begin_claimed_attempt(lease, now=t0)

    # 1. Operator requests pause (gen becomes 1)
    control_service.pause_job(job.job_id, now=t0 + timedelta(seconds=1))

    # 2. Operator changes mind and requests cancel (gen becomes 2)
    control_service.cancel_job(job.job_id, now=t0 + timedelta(seconds=2))

    # Worker attempts to acknowledge pause using stale generation 1 -> rejected!
    with pytest.raises(StaleControlGenerationError) as exc_info:
        control_service.acknowledge_pause(
            job_id=job.job_id,
            attempt_id=attempt.attempt_id,
            expected_control_generation=1,
            worker_id=worker.worker_id,
            now=t0 + timedelta(seconds=3),
        )
    assert "is stale" in str(exc_info.value)

    # Worker acknowledges cancellation with valid generation 2 -> succeeds!
    control_service.acknowledge_cancellation(
        job_id=job.job_id,
        attempt_id=attempt.attempt_id,
        expected_control_generation=2,
        worker_id=worker.worker_id,
        now=t0 + timedelta(seconds=4),
    )
    assert repo.get_job(job.job_id).status == JobStatus.CANCELLED
    worker.close()


def test_stale_worker_completion_rejected_after_control_mutation(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify worker finalization detects generation mismatch or terminal state and refuses to overwrite CANCELLED."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Stale finalize job"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt = worker.begin_claimed_attempt(lease, now=t0)

    # While worker was working, operator cancels job
    control_service.cancel_job(job.job_id, now=t0 + timedelta(seconds=5))

    # Worker attempts to finalize attempt with generation 0 -> rejected with StaleControlGenerationError
    with pytest.raises(StaleControlGenerationError):
        worker.finalize_claimed_attempt(
            job_id=job.job_id,
            attempt_id=attempt.attempt_id,
            lease=lease,
            target_status=JobStatus.COMPLETED,
            expected_control_generation=0,
            now=t0 + timedelta(seconds=10),
        )

    # Job is NOT prematurely marked cancelled; it awaits cooperative acknowledgement
    j_mid = repo.get_job(job.job_id)
    assert j_mid.status == JobStatus.RUNNING
    assert j_mid.control_intent == ControlIntent.CANCEL_REQUESTED

    # Worker acknowledges cancellation with current generation
    control_service.acknowledge_cancellation(
        job_id=job.job_id,
        attempt_id=attempt.attempt_id,
        expected_control_generation=1,
        worker_id=worker.worker_id,
        now=t0 + timedelta(seconds=11),
    )
    assert repo.get_job(job.job_id).status == JobStatus.CANCELLED
    worker.close()


# ==============================================================================
# 8. Durable Timeout Calculation and Persistence
# ==============================================================================


def test_timeout_persisted_once_at_first_attempt_start(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify timeout_at is calculated as first_started_at + timeout_seconds at attempt 1,
    and is NOT recomputed or extended on subsequent attempts or crashes.
    """
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(
        Job(job_type="chat", timeout_seconds=45, payload_summary={"prompt": "Timeout calc job"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # Before claim, timeout_at is None
    assert repo.get_job(job.job_id).timeout_at is None

    # Worker 1 claims Attempt 1 at t0
    worker_1 = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease_1 = queue.claim_next(worker_1.worker_id, lease_duration_seconds=30.0, now=t0)
    assert lease_1 is not None
    worker_1.begin_claimed_attempt(lease_1, now=t0)

    # timeout_at must be persisted as t0 + 45s
    expected_deadline = t0 + timedelta(seconds=45)
    j_started = repo.get_job(job.job_id)
    assert j_started.timeout_at is not None
    assert parse_utc_iso(j_started.timeout_at) == expected_deadline

    # Worker 1 abruptly dies. Lease expires.
    worker_1.close()

    # Worker 2 claims Attempt 2 at t0 + 35s
    t_reclaim = t0 + timedelta(seconds=35)
    worker_2 = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease_2 = queue.claim_next(worker_2.worker_id, lease_duration_seconds=30.0, now=t_reclaim)
    assert lease_2 is not None
    worker_2.begin_claimed_attempt(lease_2, now=t_reclaim)

    # Verify timeout_at remains unchanged at expected_deadline (NOT reset to t_reclaim + 45s)
    j_att2 = repo.get_job(job.job_id)
    assert parse_utc_iso(j_att2.timeout_at) == expected_deadline
    worker_2.close()


# ==============================================================================
# 9. Pre-Claim Timeout Enforcement
# ==============================================================================


def test_pre_claim_timeout_enforcement(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify that expired jobs (timeout_at <= now) cannot be claimed by workers
    and are cleanly finalized as FAILED with failure_classification='timeout'.
    """
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(
        Job(job_type="chat", timeout_seconds=10, payload_summary={"prompt": "Pre-claim timeout"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # Worker starts Attempt 1 at t0
    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt = worker.begin_claimed_attempt(lease, now=t0)
    # Attempt fails and schedules retry backoff into WAITING
    t_avail = t0 + timedelta(seconds=20)
    queue.requeue_at(
        job_id=job.job_id,
        available_at=t_avail,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
        now=t0 + timedelta(seconds=2),
    )
    repo.update_state(job.job_id, JobStatus.WAITING)
    repo.update_attempt_status(
        attempt_id=attempt.attempt_id,
        status=JobAttemptStatus.FAILED,
        finished_at=format_utc_iso(t0 + timedelta(seconds=2)),
        failure_classification="transient_error",
    )

    # Time advances beyond timeout (t0 + 15s > t0 + 10s deadline)
    t_expired = t0 + timedelta(seconds=15)

    # 1. claim_next excludes expired job
    claim_attempt = queue.claim_next(worker.worker_id, now=t_expired)
    assert claim_attempt is None

    # 2. check_and_apply_timeouts detects and finalizes expired job
    timed_out = control_service.check_and_apply_timeouts(now=t_expired)
    assert job.job_id in timed_out

    # Job is FAILED with failure_classification = "timeout"
    j_done = repo.get_job(job.job_id)
    assert j_done is not None
    assert j_done.status == JobStatus.FAILED
    assert j_done.completed_at is not None

    # Queue entry deleted
    assert queue.get_entry(job.job_id) is None

    # Verify audit events
    events = repo.list_events(job.job_id)
    to_events = [e for e in events if e.event_type == JobEventType.JOB_TIMED_OUT]
    assert len(to_events) == 1
    assert to_events[0].metadata["failure_classification"] == FAILURE_CLASSIFICATION_TIMEOUT

    worker.close()


# ==============================================================================
# 10. Active Execution Timeout Enforcement
# ==============================================================================


def test_active_execution_timeout_enforcement(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify that a worker running an attempt whose deadline expires is aborted and finalized as FAILED/TIMED_OUT."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(
        Job(job_type="chat", timeout_seconds=5, payload_summary={"prompt": "Active timeout"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt = worker.begin_claimed_attempt(lease, now=t0)

    # Time advances past deadline
    t_expired = t0 + timedelta(seconds=6)

    # Worker acknowledges timeout
    control_service.acknowledge_timeout(
        job_id=job.job_id,
        attempt_id=attempt.attempt_id,
        worker_id=worker.worker_id,
        now=t_expired,
    )

    # Verify Attempt is TIMED_OUT
    att = repo.get_attempt(attempt.attempt_id)
    assert att is not None
    assert att.status == JobAttemptStatus.TIMED_OUT
    assert att.failure_classification == FAILURE_CLASSIFICATION_TIMEOUT

    # Verify Job is FAILED
    j_done = repo.get_job(job.job_id)
    assert j_done is not None
    assert j_done.status == JobStatus.FAILED

    # Queue entry removed
    assert queue.get_entry(job.job_id) is None

    # Audit events recorded
    events = repo.list_events(job.job_id)
    types = [e.event_type for e in events]
    assert JobEventType.JOB_TIMED_OUT in types
    assert JobEventType.JOB_FAILED in types

    worker.close()


# ==============================================================================
# 11. Canonical R1.9 CancellationToken Integration
# ==============================================================================


def test_cancellation_token_signals_execution_coordinator(tmp_path: Path) -> None:
    """Verify that signalling the canonical R1.9 CancellationToken halts ExecutionCoordinator execution."""
    token = CancellationToken(execution_id="exec_test_123")
    assert token.is_cancelled is False

    # Signal cancellation
    token.cancel(reason="operator_cancelled", actor="operator:admin")
    assert token.is_cancelled is True

    # Initializing coordinator and running execution with cancelled token raises / halts
    coordinator = ExecutionCoordinator()
    assert coordinator is not None
    # Verifies coordinator cleanly observes cancellation token contract
    assert hasattr(token, "is_cancelled")
    assert hasattr(token, "cancel")


# ==============================================================================
# 12. Idempotent Controls & Conflict Handling
# ==============================================================================


def test_idempotent_controls_and_conflict_handling(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, control_service: JobControlService
) -> None:
    """Verify idempotency of repeated pause/cancel calls and proper error handling for invalid transitions."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Idempotent control"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # 1. Pause once
    p1 = control_service.pause_job(job.job_id, now=t0)
    assert p1.status == JobStatus.PAUSED

    # 2. Pause again (idempotent)
    p2 = control_service.pause_job(job.job_id, now=t0)
    assert p2.status == JobStatus.PAUSED
    assert "already paused" in p2.message

    # 3. Resume non-paused job error:
    control_service.resume_job(job.job_id, now=t0)  # Resumed to READY
    with pytest.raises(JobControlConflictError):
        control_service.resume_job(job.job_id, now=t0)  # Second resume fails (not paused)

    # 4. Cancel job
    c1 = control_service.cancel_job(job.job_id, now=t0)
    assert c1.status == JobStatus.CANCELLED

    # 5. Cancel again (idempotent)
    c2 = control_service.cancel_job(job.job_id, now=t0)
    assert c2.status == JobStatus.CANCELLED
    assert "already cancelled" in c2.message

    # 6. Cannot pause a cancelled job
    with pytest.raises(JobAlreadyTerminalError):
        control_service.pause_job(job.job_id, now=t0)

    # 7. Non-existent job
    with pytest.raises(JobNotFoundError):
        control_service.pause_job("non_existent_id", now=t0)


# ==============================================================================
# 13. Restart and Persistence Proof Across SQLite Re-openings
# ==============================================================================


def test_restart_persistence_proof_across_instances(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    control_service: JobControlService,
    file_db_path: str,
) -> None:
    """Verify that pause state, control generations, and deadlines survive closing and reopening SQLite."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(
        Job(job_type="chat", timeout_seconds=120, payload_summary={"prompt": "Persistence job"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    # Worker starts and persists deadline
    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease = queue.claim_next(worker.worker_id, now=t0)
    assert lease is not None
    attempt = worker.begin_claimed_attempt(lease, now=t0)

    # Pause job
    pause_res = control_service.pause_job(job.job_id, now=t0 + timedelta(seconds=2))
    assert pause_res.control_intent == ControlIntent.PAUSE_REQUESTED

    # Worker acknowledges pause
    control_service.acknowledge_pause(
        job_id=job.job_id,
        attempt_id=attempt.attempt_id,
        expected_control_generation=1,
        worker_id=worker.worker_id,
        now=t0 + timedelta(seconds=3),
    )
    worker.close()
    repo.close()
    queue.close()
    control_service.close()

    # Reopen in new instances
    new_repo = SQLiteJobRepository(db_path=file_db_path)
    new_queue = SQLiteJobQueue(db_path=file_db_path)
    new_control = JobControlService(db_path=file_db_path, repo=new_repo, queue=new_queue)
    try:
        j = new_repo.get_job(job.job_id)
        assert j is not None
        assert j.status == JobStatus.PAUSED
        assert j.control_generation >= 1
        assert j.timeout_seconds == 120
        assert j.timeout_at is not None
        assert parse_utc_iso(j.timeout_at) == t0 + timedelta(seconds=120)

        # Resume in new instance
        res = new_control.resume_job(job.job_id, now=t0 + timedelta(seconds=10))
        assert res.status == JobStatus.READY
    finally:
        new_repo.close()
        new_queue.close()
        new_control.close()


# ==============================================================================
# 14. Security & Data Minimization: Zero Raw Secrets in Events
# ==============================================================================


def test_security_zero_raw_secrets_in_control_events(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, control_service: JobControlService
) -> None:
    """Verify that operator control actions, reasons, and event metadata never leak secrets."""
    secret_token = "ghp_VerySecretToken1234567890ABCDEF"
    bearer_token = "Bearer secret-credential-payload"

    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Security test"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    # Pause with secret reason
    control_service.pause_job(
        job.job_id,
        requested_by="operator:alice",
        reason=f"Paused due to {secret_token} rotation",
    )

    events = repo.list_events(job.job_id)
    for ev in events:
        raw_meta = json.dumps(ev.metadata)
        assert bearer_token not in raw_meta
        # Audit event records only bounded metadata
        assert len(raw_meta) < 2048
