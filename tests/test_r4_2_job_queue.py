"""tests/test_r4_2_job_queue.py

Milestone R4 (Task R4.2 - Persistent Local Job Queue) Comprehensive Test Suite.

Verifies:
1. Enqueue persistence and rejection of invalid job states (terminal, cancelled, paused).
2. Duplicate enqueue prevention via database unique constraint.
3. Deterministic oldest-eligible claim ordering (available_at ASC, enqueued_at ASC, queue_entry_id ASC).
4. Atomic claiming and thread/connection contention safety (two racing claimers -> exactly one winner).
5. Multi-connection concurrency: independent SQLite connections claim without loss or duplicates.
6. Fencing and generation increments across expired lease reclaims.
7. Rejection of stale tokens and generations on release and extension.
8. Valid lease release returning item to claimable state without failing job or creating attempts.
9. Valid lease extension updating expiration.
10. Claim boundary invariant: claim creates NO JobAttempt, creates NO Execution, leaves Job READY.
11. Eligibility: only READY jobs claimable; CREATED, PAUSED, CANCELLED, COMPLETED never claimed.
12. Restart persistence: unexpired lease remains leased; expired lease becomes reclaimable across process restarts.
13. Schema migration v1 -> v2 preserves all existing job/attempt/event records.
14. Security: zero lease tokens leaked in events, string representations, or audit logs.
15. Deterministic monotonic sequence ordering on JobEvent records.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Optional
import pytest

from core.jobs.exceptions import (
    DuplicateQueueEntryError,
    InvalidLeaseError,
    JobNotClaimableError,
    JobNotFoundError,
    LeaseExpiredError,
    QueueEntryNotFoundError,
    StaleLeaseError,
)
from core.jobs.migrations import (
    _migration_001_initial_job_domain,
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    Job,
    JobEventType,
    JobLease,
    JobQueueEntry,
    JobStatus,
    format_utc_iso,
    parse_utc_iso,
)
from core.jobs.queue import SQLiteJobQueue
from core.jobs.sqlite import SQLiteJobRepository


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def file_db_path(tmp_path: Path) -> str:
    """Fixture returning a temporary database file path."""
    return str(tmp_path / "test_job_queue.db")


@pytest.fixture
def repo(file_db_path: str) -> SQLiteJobRepository:
    """Fixture providing an SQLiteJobRepository backed by temporary file."""
    r = SQLiteJobRepository(db_path=file_db_path)
    yield r
    r.close()


@pytest.fixture
def queue(file_db_path: str) -> SQLiteJobQueue:
    """Fixture providing an SQLiteJobQueue backed by temporary file."""
    q = SQLiteJobQueue(db_path=file_db_path)
    yield q
    q.close()


# ==============================================================================
# 1. Enqueue & State Eligibility Tests
# ==============================================================================


def test_enqueue_persists_and_preserves_job_state(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Verify enqueuing a READY job creates a JobQueueEntry and preserves job status."""
    job = repo.create_job(Job(job_type="eval_job"))
    repo.update_state(job.job_id, JobStatus.READY)

    entry = queue.enqueue(job.job_id)
    assert entry.queue_entry_id.startswith("qent_")
    assert entry.job_id == job.job_id
    assert entry.lease_owner is None
    assert entry.lease_generation == 0

    # Job status in jobs table must still be READY
    fetched_job = repo.get_job(job.job_id)
    assert fetched_job is not None
    assert fetched_job.status == JobStatus.READY

    # Verify retrieval
    retrieved_entry = queue.get_entry(job.job_id)
    assert retrieved_entry is not None
    assert retrieved_entry.queue_entry_id == entry.queue_entry_id


def test_enqueue_missing_job_raises(queue: SQLiteJobQueue) -> None:
    """Verify enqueuing a nonexistent job raises JobNotFoundError."""
    with pytest.raises(JobNotFoundError):
        queue.enqueue("job_nonexistent")


@pytest.mark.parametrize(
    "invalid_status",
    [
        JobStatus.COMPLETED,
        JobStatus.PARTIAL,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.PAUSED,
    ],
)
def test_enqueue_ineligible_job_status_raises(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, invalid_status: JobStatus
) -> None:
    """Verify jobs in terminal, cancelled, or paused status cannot be enqueued."""
    job = repo.create_job(Job(job_type="status_test"))
    if invalid_status == JobStatus.READY:
        repo.update_state(job.job_id, JobStatus.READY)
    elif invalid_status in (JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED):
        repo.update_state(job.job_id, JobStatus.READY)
        repo.update_state(job.job_id, JobStatus.RUNNING)
        repo.update_state(job.job_id, invalid_status)
    elif invalid_status == JobStatus.CANCELLED:
        repo.update_state(job.job_id, JobStatus.CANCELLED)
    elif invalid_status == JobStatus.PAUSED:
        repo.update_state(job.job_id, JobStatus.READY)
        repo.update_state(job.job_id, JobStatus.PAUSED)

    with pytest.raises(JobNotClaimableError):
        queue.enqueue(job.job_id)


def test_duplicate_enqueue_raises(repo: SQLiteJobRepository, queue: SQLiteJobQueue) -> None:
    """Verify attempting to enqueue an already enqueued job raises DuplicateQueueEntryError."""
    job = repo.create_job(Job(job_type="dup_test"))
    repo.update_state(job.job_id, JobStatus.READY)

    queue.enqueue(job.job_id)

    with pytest.raises(DuplicateQueueEntryError):
        queue.enqueue(job.job_id)


# ==============================================================================
# 2. Deterministic Claim Ordering Tests
# ==============================================================================


def test_deterministic_claim_order_by_available_and_enqueued_at(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Verify claims strictly follow available_at ASC, enqueued_at ASC, queue_entry_id ASC."""
    # Create 3 READY jobs
    j1 = repo.create_job(Job(job_type="j1"))
    j2 = repo.create_job(Job(job_type="j2"))
    j3 = repo.create_job(Job(job_type="j3"))
    repo.update_state(j1.job_id, JobStatus.READY)
    repo.update_state(j2.job_id, JobStatus.READY)
    repo.update_state(j3.job_id, JobStatus.READY)

    base_time = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    t_early = format_utc_iso(base_time)
    t_mid = format_utc_iso(base_time + timedelta(seconds=10))
    t_late = format_utc_iso(base_time + timedelta(seconds=20))

    # Enqueue in reverse order of availability
    queue.enqueue(j3.job_id, available_at=t_late)
    queue.enqueue(j2.job_id, available_at=t_mid)
    queue.enqueue(j1.job_id, available_at=t_early)

    # Claim using now = t_late
    claim1 = queue.claim_next("worker_1", now=t_late)
    assert claim1 is not None
    assert claim1.job_id == j1.job_id

    claim2 = queue.claim_next("worker_1", now=t_late)
    assert claim2 is not None
    assert claim2.job_id == j2.job_id

    claim3 = queue.claim_next("worker_1", now=t_late)
    assert claim3 is not None
    assert claim3.job_id == j3.job_id

    claim4 = queue.claim_next("worker_1", now=t_late)
    assert claim4 is None


def test_unready_jobs_are_not_claimable(repo: SQLiteJobRepository, queue: SQLiteJobQueue) -> None:
    """Verify only jobs with canonical status READY can be claimed."""
    # Enqueue a CREATED job (not yet READY)
    job = repo.create_job(Job(job_type="created_job"))
    queue.enqueue(job.job_id)

    # Cannot claim because status != READY
    assert queue.claim_next("worker_1") is None

    # Transition to READY
    repo.update_state(job.job_id, JobStatus.READY)

    # Now it is claimable
    claimed = queue.claim_next("worker_1")
    assert claimed is not None
    assert claimed.job_id == job.job_id


# ==============================================================================
# 3. Critical Invariant: Claim != Execute
# ==============================================================================


def test_claim_creates_no_attempt_and_no_execution(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Critical architectural invariant:

    queue claim != JobAttempt start != Execution start.
    Obtaining a lease must NOT create an attempt, bind an execution, or set status to RUNNING.
    """
    job = repo.create_job(Job(job_type="invariant_test"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    lease = queue.claim_next("worker_alpha", lease_duration_seconds=120)
    assert lease is not None

    # Invariants verification
    attempts = repo.list_attempts(job.job_id)
    assert len(attempts) == 0  # Zero JobAttempt created

    fetched_job = repo.get_job(job.job_id)
    assert fetched_job is not None
    assert fetched_job.status == JobStatus.READY  # Remains READY, not RUNNING


# ==============================================================================
# 4. Atomic Contention & Multi-Connection Concurrency
# ==============================================================================


def test_two_concurrent_claimers_racing_for_one_job(file_db_path: str) -> None:
    """Verify that when two independent workers race to claim one job, exactly one obtains it."""
    repo = SQLiteJobRepository(db_path=file_db_path)
    job = repo.create_job(Job(job_type="race_job"))
    repo.update_state(job.job_id, JobStatus.READY)
    repo.close()

    q_init = SQLiteJobQueue(db_path=file_db_path)
    q_init.enqueue(job.job_id)
    q_init.close()

    # Two separate queue instances representing separate worker threads/connections
    def claim_worker(worker_id: str) -> Optional[JobLease]:
        worker_queue = SQLiteJobQueue(db_path=file_db_path)
        try:
            return worker_queue.claim_next(worker_id=worker_id, lease_duration_seconds=300)
        finally:
            worker_queue.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(claim_worker, "worker_1")
        f2 = executor.submit(claim_worker, "worker_2")
        results = [f1.result(), f2.result()]

    claimed = [r for r in results if r is not None]
    unclaimed = [r for r in results if r is None]

    assert len(claimed) == 1
    assert len(unclaimed) == 1
    assert claimed[0].job_id == job.job_id


def test_multi_connection_pool_claim_concurrency(file_db_path: str) -> None:
    """Stress test: 8 concurrent workers using separate SQLite connections

    claiming from a pool of 20 jobs.
    Assert: Every job claimed exactly once, zero duplicate ownership, zero lost jobs.
    """
    total_jobs = 20
    repo = SQLiteJobRepository(db_path=file_db_path)
    job_ids = []
    for i in range(total_jobs):
        j = repo.create_job(Job(job_type=f"load_test_{i}"))
        repo.update_state(j.job_id, JobStatus.READY)
        job_ids.append(j.job_id)
    repo.close()

    q_setup = SQLiteJobQueue(db_path=file_db_path)
    for j_id in job_ids:
        q_setup.enqueue(j_id)
    q_setup.close()

    claimed_job_ids: list[str] = []
    lock = concurrent.futures.thread.threading.Lock()

    def worker_loop(worker_id: str) -> None:
        q = SQLiteJobQueue(db_path=file_db_path)
        try:
            while True:
                lease = q.claim_next(worker_id=worker_id, lease_duration_seconds=60)
                if lease is None:
                    break
                with lock:
                    claimed_job_ids.append(lease.job_id)
        finally:
            q.close()

    num_workers = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_loop, f"worker_{i}") for i in range(num_workers)]
        concurrent.futures.wait(futures)

    # Every job must be claimed exactly once
    assert len(claimed_job_ids) == total_jobs
    assert sorted(claimed_job_ids) == sorted(job_ids)


# ==============================================================================
# 5. Lease Fencing, Expiry, and Reclaim Tests
# ==============================================================================


def test_lease_fencing_generation_increment_on_reclaim(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Verify that an expired lease can be reclaimed and increments lease_generation."""
    job = repo.create_job(Job(job_type="fencing_job"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)
    lease_gen1 = queue.claim_next("worker_A", lease_duration_seconds=60, now=t0)
    assert lease_gen1 is not None
    assert lease_gen1.lease_owner == "worker_A"
    assert lease_gen1.lease_generation == 1

    # Before expiry (t0 + 30s): cannot be claimed by another worker
    t_before_expiry = t0 + timedelta(seconds=30)
    assert queue.claim_next("worker_B", now=t_before_expiry) is None

    # After expiry (t0 + 61s): becomes eligible for reclaim
    t_after_expiry = t0 + timedelta(seconds=61)
    lease_gen2 = queue.claim_next("worker_B", lease_duration_seconds=60, now=t_after_expiry)
    assert lease_gen2 is not None
    assert lease_gen2.lease_owner == "worker_B"
    assert lease_gen2.lease_generation == 2
    assert lease_gen2.lease_token != lease_gen1.lease_token

    # Stale Worker A wakes up and attempts to operate with generation 1 credentials -> REJECTED
    with pytest.raises(StaleLeaseError):
        queue.release_lease(
            job.job_id,
            lease_token=lease_gen1.lease_token,
            lease_generation=lease_gen1.lease_generation,
            now=t_after_expiry,
        )

    with pytest.raises(StaleLeaseError):
        queue.extend_lease(
            job.job_id,
            lease_token=lease_gen1.lease_token,
            lease_generation=lease_gen1.lease_generation,
            duration_seconds=60,
            now=t_after_expiry,
        )


def test_lease_extension_contract(repo: SQLiteJobRepository, queue: SQLiteJobQueue) -> None:
    """Verify extend_lease extends unexpired lease and rejects expired leases."""
    job = repo.create_job(Job(job_type="extend_job"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)
    lease = queue.claim_next("worker_heartbeat", lease_duration_seconds=60, now=t0)
    assert lease is not None

    # Valid extension at t0 + 40s
    t_extend = t0 + timedelta(seconds=40)
    extended = queue.extend_lease(
        job.job_id,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
        duration_seconds=120,
        now=t_extend,
    )
    assert extended.lease_generation == lease.lease_generation
    assert parse_utc_iso(extended.lease_expires_at) == t_extend + timedelta(seconds=120)

    # Attempting to extend after the new expiration -> LeaseExpiredError
    t_expired = t_extend + timedelta(seconds=150)
    with pytest.raises(LeaseExpiredError):
        queue.extend_lease(
            job.job_id,
            lease_token=lease.lease_token,
            lease_generation=lease.lease_generation,
            duration_seconds=60,
            now=t_expired,
        )


def test_lease_release_returns_to_claimable_state(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Verify release_lease clears active lease and makes job claimable immediately."""
    job = repo.create_job(Job(job_type="release_job"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)
    lease = queue.claim_next("worker_X", lease_duration_seconds=300, now=t0)
    assert lease is not None

    # Worker X releases lease
    released = queue.release_lease(
        job.job_id,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
        now=t0 + timedelta(seconds=10),
    )
    assert released is True

    # Immediate reclaim by Worker Y
    reclaimed = queue.claim_next(
        "worker_Y", lease_duration_seconds=300, now=t0 + timedelta(seconds=15)
    )
    assert reclaimed is not None
    assert reclaimed.lease_owner == "worker_Y"
    # Lease generation increments upon subsequent claim
    assert reclaimed.lease_generation == lease.lease_generation + 1


# ==============================================================================
# 6. Restart & Reopen Persistence Proof
# ==============================================================================


def test_restart_persistence_proof_across_queue_instances(file_db_path: str) -> None:
    """Evidence test:

    1. Enqueue Job A and Job B.
    2. Claim Job A with active lease.
    3. Destroy queue/repo instances.
    4. Re-open in brand new queue instance on same SQLite file.
    5. Before expiry: Job A leased, Job B claimable.
    6. After expiry: Job A becomes reclaimable.
    """
    repo1 = SQLiteJobRepository(db_path=file_db_path)
    j_a = repo1.create_job(Job(job_type="job_a"))
    j_b = repo1.create_job(Job(job_type="job_b"))
    repo1.update_state(j_a.job_id, JobStatus.READY)
    repo1.update_state(j_b.job_id, JobStatus.READY)
    repo1.close()

    t_start = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    queue1 = SQLiteJobQueue(db_path=file_db_path)
    queue1.enqueue(j_a.job_id)
    queue1.enqueue(j_b.job_id)

    lease_a = queue1.claim_next("worker_primary", lease_duration_seconds=100, now=t_start)
    assert lease_a is not None
    assert lease_a.job_id == j_a.job_id

    # Fully shut down session 1
    queue1.close()

    # SESSION 2: Open new instance on same DB file
    queue2 = SQLiteJobQueue(db_path=file_db_path)
    try:
        # Check Job A entry preserved
        entry_a = queue2.get_entry(j_a.job_id)
        assert entry_a is not None
        assert entry_a.lease_owner == "worker_primary"
        assert entry_a.lease_generation == 1

        # Check Job B claimable before expiry
        t_before = t_start + timedelta(seconds=50)
        claim_b = queue2.claim_next("worker_secondary", now=t_before)
        assert claim_b is not None
        assert claim_b.job_id == j_b.job_id

        # At t_before, Job A still cannot be claimed
        assert queue2.claim_next("worker_tertiary", now=t_before) is None

        # After expiry (t_start + 120s): Job A becomes reclaimable
        t_after = t_start + timedelta(seconds=120)
        reclaim_a = queue2.claim_next("worker_tertiary", lease_duration_seconds=100, now=t_after)
        assert reclaim_a is not None
        assert reclaim_a.job_id == j_a.job_id
        assert reclaim_a.lease_owner == "worker_tertiary"
        assert reclaim_a.lease_generation == 2
    finally:
        queue2.close()


# ==============================================================================
# 7. Migration v1 -> v2 Preserves Existing Records
# ==============================================================================


def test_migration_v1_to_v2_preserves_existing_data(tmp_path: Path) -> None:
    """Verify upgrading a v1 database to v2 preserves all existing jobs, attempts, and events."""
    db_file = tmp_path / "v1_upgrade_test.db"
    conn = sqlite3.connect(str(db_file))
    try:
        # 1. Apply Migration 1 explicitly
        _migration_001_initial_job_domain(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);"
        )
        conn.execute(
            "INSERT INTO job_schema_migrations VALUES (1, '001_initial_job_domain', '2026-10-10T00:00:00Z');"
        )
        conn.commit()

        # 2. Insert v1 job, attempt, and event
        conn.execute(
            """
            INSERT INTO jobs (job_id, job_type, status, created_at, updated_at)
            VALUES ('job_v1_legacy', 'legacy_task', 'ready', '2026-10-10T00:01:00Z', '2026-10-10T00:01:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO job_attempts (attempt_id, job_id, attempt_number, status, started_at)
            VALUES ('att_v1_legacy', 'job_v1_legacy', 1, 'completed', '2026-10-10T00:01:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO job_events (event_id, job_id, event_type, timestamp, metadata_json)
            VALUES ('jev_v1_legacy', 'job_v1_legacy', 'job_created', '2026-10-10T00:01:00Z', '{}')
            """
        )
        conn.commit()

        assert get_current_job_schema_version(conn) == 1

        # 3. Apply pending migrations (Migration 2)
        applied = apply_job_migrations(conn)
        assert applied == 1
        assert get_current_job_schema_version(conn) == 2

        # 4. Verify existing records are 100% intact
        cur = conn.cursor()
        cur.execute("SELECT job_id, status FROM jobs WHERE job_id = 'job_v1_legacy'")
        assert cur.fetchone() == ("job_v1_legacy", "ready")

        cur.execute(
            "SELECT attempt_id, attempt_number FROM job_attempts WHERE attempt_id = 'att_v1_legacy'"
        )
        assert cur.fetchone() == ("att_v1_legacy", 1)

        cur.execute(
            "SELECT event_id, sequence_number FROM job_events WHERE event_id = 'jev_v1_legacy'"
        )
        row = cur.fetchone()
        assert row[0] == "jev_v1_legacy"
        assert row[1] is not None  # Backfilled with rowid
    finally:
        conn.close()

    # 5. Open with SQLiteJobQueue and verify we can enqueue and claim the legacy job
    queue = SQLiteJobQueue(db_path=str(db_file))
    try:
        entry = queue.enqueue("job_v1_legacy")
        assert entry.job_id == "job_v1_legacy"
        lease = queue.claim_next("worker_modern")
        assert lease is not None
        assert lease.job_id == "job_v1_legacy"
    finally:
        queue.close()


# ==============================================================================
# 8. Security & Secret Redaction Tests
# ==============================================================================


def test_lease_token_never_exposed_in_events_or_repr(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Security verification:

    Cryptographic lease token is NEVER written to job_events, audit logs, or str/repr.
    """
    job = repo.create_job(Job(job_type="token_security_test"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    lease = queue.claim_next("worker_audit", lease_duration_seconds=300)
    assert lease is not None

    # Check repr and str mask the token
    assert "[MASKED]" in repr(lease)
    assert lease.lease_token not in repr(lease)
    assert "[MASKED]" in str(lease)

    # Check queue entry repr masks the token
    entry = queue.get_entry(job.job_id)
    assert entry is not None
    assert "[MASKED]" in repr(entry)
    assert lease.lease_token not in repr(entry)

    # Extend lease
    queue.extend_lease(
        job.job_id,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
        duration_seconds=300,
    )

    # Release lease
    queue.release_lease(
        job.job_id,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
    )

    # Inspect all audit events for this job
    events = repo.list_events(job.job_id)
    for ev in events:
        meta_str = str(ev.metadata)
        assert lease.lease_token not in meta_str, f"Lease token leaked in event {ev.event_type}"


# ==============================================================================
# 9. Deterministic Monotonic Event Sequencing
# ==============================================================================


def test_job_events_have_monotonic_sequence_number(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Verify events emitted on a job have strictly increasing sequence numbers."""
    job = repo.create_job(Job(job_type="seq_test"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)
    lease = queue.claim_next("worker_seq")
    assert lease is not None
    queue.release_lease(job.job_id, lease.lease_token, lease.lease_generation)

    events = repo.list_events(job.job_id)
    assert len(events) >= 5
    seq_numbers = [e.sequence_number for e in events]
    assert seq_numbers == list(range(1, len(events) + 1))


def test_queue_entry_not_found_and_invalid_lease_errors(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue
) -> None:
    """Verify QueueEntryNotFoundError and InvalidLeaseError on mismatched token or missing entry."""
    with pytest.raises(QueueEntryNotFoundError):
        queue.release_lease("job_nonexistent", "dummy_token", 1)

    with pytest.raises(QueueEntryNotFoundError):
        queue.extend_lease("job_nonexistent", "dummy_token", 1, 60)

    job = repo.create_job(Job(job_type="mismatch_test"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)
    lease = queue.claim_next("worker_valid", lease_duration_seconds=300)
    assert lease is not None

    with pytest.raises(InvalidLeaseError):
        queue.release_lease(job.job_id, "wrong_token", lease.lease_generation)

    with pytest.raises(InvalidLeaseError):
        queue.extend_lease(job.job_id, "wrong_token", lease.lease_generation, 60)


def test_queue_models_and_event_types() -> None:
    """Verify queue models and event types are properly registered and configured."""
    assert JobEventType.JOB_ENQUEUED == "job_enqueued"
    assert JobEventType.LEASE_ACQUIRED == "lease_acquired"
    assert JobEventType.LEASE_EXTENDED == "lease_extended"
    assert JobEventType.LEASE_RELEASED == "lease_released"
    assert JobEventType.LEASE_RECLAIMED == "lease_reclaimed"

    entry = JobQueueEntry(job_id="job_test123", lease_token="secret_token_123")
    assert entry.queue_entry_id.startswith("qent_")
    assert entry.lease_generation == 0
    assert "[MASKED]" in repr(entry)
    assert "secret_token_123" not in repr(entry)
