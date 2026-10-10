"""tests/test_r4_4_idempotency_and_retry.py

Milestone R4 (Task R4.4 - Idempotency and Retry Model) Comprehensive Test Suite.

Verifies:
1. IdempotencyKey deterministic derivation, argument digest, normalization, and attempt independence.
2. Migration 004 (job_idempotency_records) and v3 -> v4 populated upgrade.
3. OperationIdempotencyCapability and IdempotencyRecordStatus state machine.
4. Single-winner concurrency for identical idempotency keys (SQLite transaction boundary).
5. Result reuse for SUCCEEDED idempotency records without re-executing side effects.
6. Unknown outcome on NON_IDEMPOTENT operations strictly prohibits automatic retry (NonRetryableOperationError).
7. Unknown outcome on NATURALLY_IDEMPOTENT or NATIVE_KEY operations permits safe retry.
8. Clean failure (FAILED_SAFE_TO_RETRY) permits safe retry reservation.
9. Structured RetryClassification and bounded exponential RetryPolicy.
10. Durable retry backoff using queue requeue_at and JobStatus.WAITING without sleeping workers.
11. Process restart during backoff preserves retry eligibility and delay.
12. Lease fencing rejects stale workers attempting to schedule retries (StaleLeaseError).
13. Retry exhaustion records RETRY_EXHAUSTED audit event and finalizes Job as FAILED.
14. E2E repeated delivery executes external side effect exactly once.
15. Security: zero raw auth headers, tokens, or private credentials leaked in records or events.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict
import pytest

from core.execution.coordinator import ExecutionCoordinator
from core.jobs.exceptions import (
    NonRetryableOperationError,
    OperationAlreadyInProgressError,
    StaleLeaseError,
)
from core.jobs.idempotency import (
    SQLiteIdempotencyStore,
    classify_failure,
)
from core.jobs.migrations import (
    _migration_001_initial_job_domain,
    _migration_002_persistent_job_queue,
    _migration_003_worker_attempt_ownership,
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    IdempotencyRecordStatus,
    Job,
    JobAttemptStatus,
    JobEventType,
    JobStatus,
    OperationIdempotencyCapability,
    RetryClassification,
    RetryPolicy,
    compute_idempotency_key,
    format_utc_iso,
)
from core.jobs.queue import SQLiteJobQueue
from core.jobs.sqlite import SQLiteJobRepository
from core.jobs.worker import JobWorker


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def file_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_r4_4_idempotency.db")


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
def idem_store(file_db_path: str) -> SQLiteIdempotencyStore:
    s = SQLiteIdempotencyStore(db_path=file_db_path)
    yield s
    s.close()


# ==============================================================================
# 1. Idempotency Key Derivation & Argument Digest Tests
# ==============================================================================


def test_idempotency_key_derivation_exact_arguments_and_ordering() -> None:
    """Verify deterministic idempotency key derivation with key-ordering invariance."""
    args_1 = {"user_id": 42, "amount": 100.5, "currency": "USD"}
    args_2 = {"currency": "USD", "amount": 100.5, "user_id": 42}

    key1 = compute_idempotency_key("job_123", "charge_payment", args_1)
    key2 = compute_idempotency_key("job_123", "charge_payment", args_2)

    assert key1.key == key2.key
    assert key1.argument_digest == key2.argument_digest
    assert key1.key.startswith("ik_")
    assert key1.job_id == "job_123"
    assert key1.operation_kind == "charge_payment"


def test_idempotency_key_independent_of_attempt() -> None:
    """IdempotencyKey must bind to logical job and operation, independent of attempt_id."""
    args = {"action": "sync"}
    key_for_attempt_1 = compute_idempotency_key("job_abc", "sync_data", args)
    key_for_attempt_2 = compute_idempotency_key("job_abc", "sync_data", args)

    assert key_for_attempt_1.key == key_for_attempt_2.key


def test_idempotency_key_distinct_arguments_produce_distinct_keys() -> None:
    """Different argument payloads produce distinct keys and digests."""
    args_a = {"prompt": "Write essay"}
    args_b = {"prompt": "Write poem"}

    key_a = compute_idempotency_key("job_1", "llm_generate", args_a)
    key_b = compute_idempotency_key("job_1", "llm_generate", args_b)

    assert key_a.key != key_b.key
    assert key_a.argument_digest != key_b.argument_digest


# ==============================================================================
# 2. Single-Winner Concurrency Tests
# ==============================================================================


def test_concurrent_reservation_single_winner(
    repo: SQLiteJobRepository, idem_store: SQLiteIdempotencyStore
) -> None:
    """Multiple concurrent threads racing to reserve the same IdempotencyKey produce exactly 1 winner."""
    job = repo.create_job(Job(job_type="agent_task", payload_summary={"task": "race_test"}))
    args = {"target": "resource_A"}

    num_threads = 6
    winners = []
    in_progress_exceptions = []
    barrier = threading.Barrier(num_threads)

    def racer(thread_idx: int) -> None:
        barrier.wait()
        attempt_id = f"att_racer_{thread_idx}"
        try:
            should_exec, record = idem_store.reserve_operation(
                job_id=job.job_id,
                operation_kind="lock_resource",
                args=args,
                capability=OperationIdempotencyCapability.AE_GUARDED,
                attempt_id=attempt_id,
            )
            if should_exec:
                winners.append(attempt_id)
        except OperationAlreadyInProgressError:
            in_progress_exceptions.append(attempt_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as pool:
        futures = [pool.submit(racer, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)

    assert len(winners) == 1
    assert len(in_progress_exceptions) == num_threads - 1

    key = compute_idempotency_key(job.job_id, "lock_resource", args)
    rec = idem_store.get_record(key.key)
    assert rec is not None
    assert rec.status == IdempotencyRecordStatus.RESERVED
    assert rec.claimed_by_attempt == winners[0]


# ==============================================================================
# 3. Result Reuse on SUCCEEDED
# ==============================================================================


def test_idempotency_result_reuse_on_succeeded(
    repo: SQLiteJobRepository, idem_store: SQLiteIdempotencyStore
) -> None:
    """When an operation completes successfully, subsequent reservation returns cached result."""
    job = repo.create_job(Job(job_type="agent_task", payload_summary={"task": "reuse_test"}))
    args = {"query": "weather"}

    should_exec, record = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="fetch_weather",
        args=args,
        capability=OperationIdempotencyCapability.NATIVE_KEY,
        attempt_id="att_1",
    )
    assert should_exec is True

    idem_store.record_in_progress(record.idempotency_key, attempt_id="att_1")
    cached_payload = {"temperature": 72, "city": "San Francisco"}
    idem_store.record_success(
        record.idempotency_key,
        attempt_id="att_1",
        result_payload=cached_payload,
        result_reference="ref://weather/sf",
    )

    should_exec_2, record_2 = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="fetch_weather",
        args=args,
        capability=OperationIdempotencyCapability.NATIVE_KEY,
        attempt_id="att_2",
    )
    assert should_exec_2 is False
    assert record_2.status == IdempotencyRecordStatus.SUCCEEDED
    assert record_2.result_payload == cached_payload
    assert record_2.result_reference == "ref://weather/sf"

    events = repo.list_events(job.job_id)
    reused_events = [e for e in events if e.event_type == JobEventType.IDEMPOTENCY_REUSED]
    assert len(reused_events) == 1
    assert reused_events[0].metadata["reused_from_attempt"] == "att_1"
    assert reused_events[0].metadata["reused_by_attempt"] == "att_2"


# ==============================================================================
# 4. Outcome Uncertainty & Non-Idempotent Prohibition Tests
# ==============================================================================


def test_unknown_outcome_prohibits_retry_on_non_idempotent_operation(
    repo: SQLiteJobRepository, idem_store: SQLiteIdempotencyStore
) -> None:
    """Non-idempotent operations with outcome UNKNOWN must strictly prohibit automatic retry."""
    job = repo.create_job(Job(job_type="agent_task", payload_summary={"task": "charge"}))
    args = {"charge_id": "ch_123", "amount": 500}

    _, rec = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="stripe_charge",
        args=args,
        capability=OperationIdempotencyCapability.NON_IDEMPOTENT,
        attempt_id="att_1",
    )
    idem_store.record_in_progress(rec.idempotency_key, attempt_id="att_1")
    idem_store.record_failure(rec.idempotency_key, attempt_id="att_1", outcome_unknown=True)

    with pytest.raises(NonRetryableOperationError) as exc_info:
        idem_store.reserve_operation(
            job_id=job.job_id,
            operation_kind="stripe_charge",
            args=args,
            capability=OperationIdempotencyCapability.NON_IDEMPOTENT,
            attempt_id="att_2",
        )
    assert "Automatic retry prohibited" in str(exc_info.value)

    events = repo.list_events(job.job_id)
    unknown_events = [e for e in events if e.event_type == JobEventType.IDEMPOTENCY_OUTCOME_UNKNOWN]
    assert len(unknown_events) >= 1
    assert unknown_events[-1].metadata.get("prohibited") is True


def test_unknown_outcome_permits_retry_on_natively_idempotent_operation(
    repo: SQLiteJobRepository, idem_store: SQLiteIdempotencyStore
) -> None:
    """Naturally idempotent or Native-Key operations permit retry despite unknown prior outcome."""
    job = repo.create_job(Job(job_type="agent_task", payload_summary={"task": "put_state"}))
    args = {"resource_path": "/bucket/file.txt"}

    _, rec = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="s3_put_object",
        args=args,
        capability=OperationIdempotencyCapability.NATURALLY_IDEMPOTENT,
        attempt_id="att_1",
    )
    idem_store.record_failure(rec.idempotency_key, attempt_id="att_1", outcome_unknown=True)

    should_exec, rec_2 = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="s3_put_object",
        args=args,
        capability=OperationIdempotencyCapability.NATURALLY_IDEMPOTENT,
        attempt_id="att_2",
    )
    assert should_exec is True
    assert rec_2.status == IdempotencyRecordStatus.RESERVED
    assert rec_2.claimed_by_attempt == "att_2"


def test_failed_safe_to_retry_permits_clean_retry(
    repo: SQLiteJobRepository, idem_store: SQLiteIdempotencyStore
) -> None:
    """Operations marked FAILED_SAFE_TO_RETRY can be cleanly re-reserved."""
    job = repo.create_job(Job(job_type="agent_task", payload_summary={"task": "validate"}))
    args = {"step": 1}

    _, rec = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="validate_step",
        args=args,
        capability=OperationIdempotencyCapability.NON_IDEMPOTENT,
        attempt_id="att_1",
    )
    idem_store.record_failure(rec.idempotency_key, attempt_id="att_1", safe_to_retry=True)

    should_exec, rec_2 = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="validate_step",
        args=args,
        capability=OperationIdempotencyCapability.NON_IDEMPOTENT,
        attempt_id="att_2",
    )
    assert should_exec is True
    assert rec_2.claimed_by_attempt == "att_2"


# ==============================================================================
# 5. Retry Classification & Policy Tests
# ==============================================================================


def test_retry_classification_logic() -> None:
    """Verify structured retry classification across error kinds."""
    assert (
        classify_failure(NonRetryableOperationError("prohibited"))
        == RetryClassification.NON_RETRYABLE
    )
    assert (
        classify_failure(
            RuntimeError("timeout"),
            outcome_unknown=True,
            capability=OperationIdempotencyCapability.NON_IDEMPOTENT,
        )
        == RetryClassification.NON_RETRYABLE
    )
    assert (
        classify_failure(
            RuntimeError("timeout"),
            outcome_unknown=True,
            capability=OperationIdempotencyCapability.NATURALLY_IDEMPOTENT,
        )
        == RetryClassification.OUTCOME_UNKNOWN
    )
    assert (
        classify_failure("Unauthorized", error_code="POLICY_BLOCKED")
        == RetryClassification.POLICY_BLOCKED
    )
    assert (
        classify_failure(RuntimeError("Temporary network reset")) == RetryClassification.RETRYABLE
    )


def test_retry_policy_exponential_backoff_calculation() -> None:
    """Verify bounded exponential backoff delay calculation."""
    policy = RetryPolicy(
        max_attempts=4,
        initial_delay=2.0,
        multiplier=3.0,
        max_delay=30.0,
        jitter=False,
    )

    assert policy.calculate_backoff_delay(1) == 2.0
    assert policy.calculate_backoff_delay(2) == 6.0
    assert policy.calculate_backoff_delay(3) == 18.0
    assert policy.calculate_backoff_delay(4) == 30.0


# ==============================================================================
# 6. Durable Retry Backoff Without Sleeping Worker
# ==============================================================================


def test_durable_retry_backoff_without_sleeping_worker(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify failed execution schedules retry at future available_at and exits immediately without sleeping."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    current_time = t0

    def mock_clock() -> datetime:
        return current_time

    queue_clock = SQLiteJobQueue(db_path=file_db_path, clock=mock_clock)

    job = repo.create_job(
        Job(job_type="chat", payload_summary={"prompt": "Transitory failure task"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue_clock.enqueue(job.job_id, available_at=t0)

    mock_coord = ExecutionCoordinator(
        dispatch_override=lambda ctx, tier, prov, model: (_ for _ in ()).throw(
            RuntimeError("Connection reset by peer")
        )
    )

    policy = RetryPolicy(max_attempts=3, initial_delay=10.0, multiplier=2.0)
    worker = JobWorker(
        db_path=file_db_path,
        queue=queue_clock,
        coordinator=mock_coord,
        retry_policy=policy,
        lease_ttl_seconds=30.0,
        clock=mock_clock,
    )

    start_t = time.monotonic()
    processed = worker.step(now=t0)
    elapsed = time.monotonic() - start_t
    assert processed is True
    assert elapsed < 1.0, f"Worker spent {elapsed}s in step; sleep loop detected!"

    j_after = repo.get_job(job.job_id)
    assert j_after is not None
    assert j_after.status == JobStatus.WAITING

    attempts = repo.list_attempts(job.job_id)
    assert len(attempts) == 1
    assert attempts[0].status == JobAttemptStatus.FAILED

    q_entry = queue_clock.get_entry(job.job_id)
    assert q_entry is not None
    assert q_entry.lease_owner is None
    assert q_entry.lease_token is None
    expected_avail = format_utc_iso(t0 + timedelta(seconds=10.0))
    assert q_entry.available_at == expected_avail

    events = repo.list_events(job.job_id)
    retry_events = [e for e in events if e.event_type == JobEventType.RETRY_SCHEDULED]
    assert len(retry_events) == 1
    assert retry_events[0].metadata["available_at"] == expected_avail

    worker.close()
    queue_clock.close()


# ==============================================================================
# 7. Process Restart During Backoff Preserves Retry
# ==============================================================================


def test_process_restart_during_backoff_preserves_retry(
    file_db_path: str,
) -> None:
    """Verify durable retry survives complete process/worker restart and claims when delay expires."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    current_time = t0

    def mock_clock() -> datetime:
        return current_time

    repo = SQLiteJobRepository(db_path=file_db_path)
    queue = SQLiteJobQueue(db_path=file_db_path, clock=mock_clock)

    job = repo.create_job(Job(job_type="eval", payload_summary={"task": "restart_retry_test"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    policy = RetryPolicy(max_attempts=3, initial_delay=5.0)
    mock_coord_fail = ExecutionCoordinator(
        dispatch_override=lambda c, t, p, m: (_ for _ in ()).throw(RuntimeError("Flaky service"))
    )

    worker_1 = JobWorker(
        db_path=file_db_path,
        queue=queue,
        coordinator=mock_coord_fail,
        retry_policy=policy,
        clock=mock_clock,
    )
    worker_1.step(now=t0)
    worker_1.close()
    queue.close()
    repo.close()

    current_time = t0 + timedelta(seconds=2.0)
    repo_2 = SQLiteJobRepository(db_path=file_db_path)
    queue_2 = SQLiteJobQueue(db_path=file_db_path, clock=mock_clock)

    mock_coord_success = ExecutionCoordinator(
        dispatch_override=lambda c, t, p, m: {"response": "healed"}
    )
    worker_2 = JobWorker(
        db_path=file_db_path,
        queue=queue_2,
        coordinator=mock_coord_success,
        retry_policy=policy,
        clock=mock_clock,
    )

    assert worker_2.step(now=current_time) is False

    current_time = t0 + timedelta(seconds=6.0)
    processed = worker_2.step(now=current_time)
    assert processed is True

    final_job = repo_2.get_job(job.job_id)
    assert final_job is not None
    assert final_job.status == JobStatus.COMPLETED

    attempts = repo_2.list_attempts(job.job_id)
    assert len(attempts) == 2
    assert attempts[0].attempt_number == 1
    assert attempts[0].status == JobAttemptStatus.FAILED
    assert attempts[1].attempt_number == 2
    assert attempts[1].status == JobAttemptStatus.COMPLETED

    worker_2.close()
    queue_2.close()
    repo_2.close()


# ==============================================================================
# 8. Stale Worker Cannot Schedule Retry
# ==============================================================================


def test_stale_worker_cannot_schedule_retry(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """A worker that lost its lease authority cannot schedule a retry."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="chat", payload_summary={"task": "stale_test"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    lease_w1 = queue.claim_next("wrk_1", lease_duration_seconds=10.0, now=t0)
    assert lease_w1 is not None
    assert lease_w1.lease_generation == 1

    t1 = t0 + timedelta(seconds=15.0)
    lease_w2 = queue.claim_next("wrk_2", lease_duration_seconds=10.0, now=t1)
    assert lease_w2 is not None
    assert lease_w2.lease_generation == 2

    with pytest.raises(StaleLeaseError) as exc_info:
        queue.requeue_at(
            job_id=job.job_id,
            available_at=t1 + timedelta(seconds=5.0),
            lease_token=lease_w1.lease_token,
            lease_generation=lease_w1.lease_generation,
            now=t1,
        )
    assert "stale" in str(exc_info.value).lower()


# ==============================================================================
# 9. Retry Exhaustion Finalizes Failure
# ==============================================================================


def test_retry_exhaustion_finalizes_failure(repo: SQLiteJobRepository, file_db_path: str) -> None:
    """When attempt_number reaches max_attempts, worker emits RETRY_EXHAUSTED and marks Job FAILED."""
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    current_time = t0

    def mock_clock() -> datetime:
        return current_time

    queue = SQLiteJobQueue(db_path=file_db_path, clock=mock_clock)

    job = repo.create_job(Job(job_type="summary", payload_summary={"task": "exhaust_test"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    mock_coord = ExecutionCoordinator(
        dispatch_override=lambda c, t, p, m: (_ for _ in ()).throw(
            RuntimeError("Persistent fatal outage")
        )
    )

    policy = RetryPolicy(max_attempts=2, initial_delay=2.0)
    worker = JobWorker(
        db_path=file_db_path,
        queue=queue,
        coordinator=mock_coord,
        retry_policy=policy,
        clock=mock_clock,
    )

    assert worker.step(now=current_time) is True
    assert repo.get_job(job.job_id).status == JobStatus.WAITING

    current_time = t0 + timedelta(seconds=3.0)

    assert worker.step(now=current_time) is True

    final_job = repo.get_job(job.job_id)
    assert final_job is not None
    assert final_job.status == JobStatus.FAILED

    assert queue.get_entry(job.job_id) is None

    events = repo.list_events(job.job_id)
    exhausted_events = [e for e in events if e.event_type == JobEventType.RETRY_EXHAUSTED]
    assert len(exhausted_events) == 1
    assert exhausted_events[0].metadata["attempt_number"] == 2
    assert exhausted_events[0].metadata["max_attempts"] == 2

    attempts = repo.list_attempts(job.job_id)
    assert len(attempts) == 2
    assert attempts[0].status == JobAttemptStatus.FAILED
    assert attempts[1].status == JobAttemptStatus.FAILED

    worker.close()
    queue.close()


# ==============================================================================
# 10. E2E Repeated Delivery with Side Effect Executed Exactly Once
# ==============================================================================


def test_repeated_delivery_executes_protected_effect_once(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Repeated worker delivery executes external side effect exactly once via idempotency store."""
    counter = {"calls": 0}

    def protected_side_effect() -> Dict[str, Any]:
        counter["calls"] += 1
        return {"payment_reference": f"pay_{counter['calls']}", "amount": 100}

    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    job = repo.create_job(Job(job_type="agent_task", payload_summary={"task": "charge_customer"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id, available_at=t0)

    store = SQLiteIdempotencyStore(db_path=file_db_path)

    res1 = store.execute_with_idempotency(
        job_id=job.job_id,
        operation_kind="bill_customer",
        args={"customer_id": "cust_42", "cents": 10000},
        fn=protected_side_effect,
        capability=OperationIdempotencyCapability.NATIVE_KEY,
        attempt_id="att_1",
    )
    assert counter["calls"] == 1
    assert res1["payment_reference"] == "pay_1"

    res2 = store.execute_with_idempotency(
        job_id=job.job_id,
        operation_kind="bill_customer",
        args={"customer_id": "cust_42", "cents": 10000},
        fn=protected_side_effect,
        capability=OperationIdempotencyCapability.NATIVE_KEY,
        attempt_id="att_2",
    )
    assert counter["calls"] == 1
    assert res2["payment_reference"] == "pay_1"

    store.close()


# ==============================================================================
# 11. Migration v3 to v4 Populated Database Upgrade
# ==============================================================================


def test_migration_v3_to_v4_populated_database_upgrade(tmp_path: Path) -> None:
    """Verify v3 -> v4 populated upgrade creates job_idempotency_records and preserves data."""
    db_file = tmp_path / "v3_to_v4_test.db"
    conn = sqlite3.connect(str(db_file))
    try:
        _migration_001_initial_job_domain(conn)
        _migration_002_persistent_job_queue(conn)
        _migration_003_worker_attempt_ownership(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);"
        )
        conn.execute(
            "INSERT INTO job_schema_migrations VALUES (1, '001_initial_job_domain', '2026-10-10T00:00:00Z');"
        )
        conn.execute(
            "INSERT INTO job_schema_migrations VALUES (2, '002_persistent_job_queue', '2026-10-10T00:00:00Z');"
        )
        conn.execute(
            "INSERT INTO job_schema_migrations VALUES (3, '003_worker_attempt_ownership', '2026-10-10T00:00:00Z');"
        )

        conn.execute(
            "INSERT INTO jobs (job_id, job_type, status, created_at, updated_at) VALUES ('j_v3', 'chat', 'ready', '2026-10-10T00:00:00Z', '2026-10-10T00:00:00Z');"
        )
        conn.execute(
            "INSERT INTO job_attempts (attempt_id, job_id, attempt_number, status, worker_id, lease_generation, started_at) "
            "VALUES ('att_v3', 'j_v3', 1, 'running', 'wrk_v3', 1, '2026-10-10T00:00:00Z');"
        )
        conn.commit()
    finally:
        conn.close()

    conn2 = sqlite3.connect(str(db_file))
    try:
        applied = apply_job_migrations(conn2, target_version=4)
        assert applied == 1
        assert get_current_job_schema_version(conn2) == 4

        cur = conn2.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='job_idempotency_records';"
        )
        assert cur.fetchone() is not None

        cur.execute("SELECT job_id, status FROM jobs WHERE job_id = 'j_v3'")
        assert cur.fetchone() == ("j_v3", "ready")
        cur.execute(
            "SELECT worker_id, lease_generation FROM job_attempts WHERE attempt_id = 'att_v3'"
        )
        assert cur.fetchone() == ("wrk_v3", 1)
    finally:
        conn2.close()


# ==============================================================================
# 12. Security: Zero Raw Secrets in Idempotency Records or Events
# ==============================================================================


def test_security_zero_raw_secrets_in_idempotency_records_or_events(
    repo: SQLiteJobRepository, idem_store: SQLiteIdempotencyStore, file_db_path: str
) -> None:
    """Verify raw passwords, tokens, and authorization headers are never exposed."""
    secret_token = "Bearer secret_jwt_xyz_998877"
    raw_api_key = "sk_live_very_secret_api_key_12345"

    args = {
        "operation": "deploy",
        "api_key": raw_api_key,
        "auth_header": secret_token,
        "safe_param": "target_env_staging",
    }

    job = repo.create_job(Job(job_type="agent_task", payload_summary={"task": "deploy_secure"}))

    should_exec, record = idem_store.reserve_operation(
        job_id=job.job_id,
        operation_kind="deploy_cluster",
        args=args,
        capability=OperationIdempotencyCapability.AE_GUARDED,
        attempt_id="att_sec",
    )

    idem_store.record_success(
        record.idempotency_key,
        attempt_id="att_sec",
        result_payload={"api_key": raw_api_key, "deployed": True},
    )

    conn = sqlite3.connect(file_db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT metadata_json FROM job_events WHERE job_id = ?", (job.job_id,))
        for (m_json,) in cur.fetchall():
            assert raw_api_key not in m_json
            assert secret_token not in m_json

        cur.execute(
            "SELECT argument_digest, result_payload_json FROM job_idempotency_records WHERE job_id = ?",
            (job.job_id,),
        )
        digest, result_json = cur.fetchone()
        assert raw_api_key not in digest
        assert secret_token not in digest
        assert raw_api_key not in (result_json or "")
        assert secret_token not in (result_json or "")
    finally:
        conn.close()
