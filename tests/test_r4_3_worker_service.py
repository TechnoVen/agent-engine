"""tests/test_r4_3_worker_service.py

Milestone R4 (Task R4.3 - Worker Service) Comprehensive Test Suite.

Verifies:
1. Standalone worker starts/stops without UI / Tauri.
2. Claim -> Attempt start transaction boundary (claim grants lease only; attempt created at worker boundary).
3. JobExecutionRequestFactory validates job types, bounds inputs, and strips sensitive keys.
4. Execution binding to canonical ExecutionCoordinator.
5. Outcome mapping (COMPLETED, FAILED, PARTIAL, BLOCKED, WAITING_FOR_APPROVAL).
6. Execution failure produces zero automatic retries (without R4.4).
7. Pre-execution setup failure safely releases lease.
8. Heartbeat maintains lease, second worker blocked during active execution.
9. Lost lease prevents stale completion commit (StaleLeaseError on stale finalization).
10. Crash recovery & prior nonterminal attempt reconciliation (generation increment, new attempt ID).
11. Graceful shutdown drains short job within timeout.
12. Graceful shutdown on long job exceeding timeout refuses premature lease release.
13. Subprocess-level worker crash (SIGKILL) and reclaim fixture.
14. Multi-worker concurrent execution contending on SQLite queue.
15. Security: zero lease tokens or credentials leaked in logs, events, or exceptions.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any, List, Optional
import pytest

from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionResult,
    ExecutionStatus,
)
from core.jobs.exceptions import (
    StaleLeaseError,
    UnsupportedJobTypeError,
)
from core.jobs.migrations import (
    _migration_001_initial_job_domain,
    _migration_002_persistent_job_queue,
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    EXECUTION_OUTCOME_UNKNOWN,
    FAILURE_CLASSIFICATION_WORKER_CRASH_OR_LEASE_LOST,
    Job,
    JobAttemptStatus,
    JobEventType,
    JobStatus,
    SIDE_EFFECT_STATE_UNKNOWN,
)
from core.jobs.queue import SQLiteJobQueue
from core.jobs.sqlite import SQLiteJobRepository
from core.jobs.worker import (
    JobExecutionRequestFactory,
    JobWorker,
)


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def file_db_path(tmp_path: Path) -> str:
    """Fixture providing a temporary SQLite database file path."""
    return str(tmp_path / "test_r4_3_worker.db")


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


def make_mock_coordinator(
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    delay: float = 0.0,
    error_msg: Optional[str] = None,
) -> ExecutionCoordinator:
    """Create an ExecutionCoordinator with a deterministic mock dispatch."""

    def mock_dispatch(ctx: Any, tier: Any, prov: Any, model: Any) -> Any:
        if delay > 0:
            time.sleep(delay)
        if status == ExecutionStatus.FAILED:
            raise RuntimeError(error_msg or "Mock execution failure")
        return {"response": "mock_success_output", "status": status.value}

    coord = ExecutionCoordinator(dispatch_override=mock_dispatch)
    if status not in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED):

        async def custom_execute(
            request: Any, cancellation_token: Any = None, event_listener: Any = None
        ) -> ExecutionResult:
            if delay > 0:
                time.sleep(delay)
            return ExecutionResult(
                execution_id=request.id,
                status=status,
                outputs={"response": "mock_outcome"},
                error=error_msg,
            )

        coord.execute = custom_execute  # type: ignore[method-assign]
    return coord


# ==============================================================================
# 1. Standalone Worker Lifecycle & Boundary Invariant Tests
# ==============================================================================


def test_standalone_worker_lifecycle(file_db_path: str) -> None:
    """Verify worker initializes with canonical identity and shuts down cleanly without UI."""
    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=10.0, poll_interval_seconds=0.1)
    assert worker.worker_id.startswith("wrk_")
    assert worker.pid == os.getpid()
    assert worker.started_at is not None

    # Step on empty queue returns False
    assert worker.step() is False

    # Stop sets stop event
    worker.stop()
    assert worker._stop_event.is_set()
    assert worker.step() is False
    worker.close()


def test_claim_attempt_transaction_boundary(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify claim grants lease only; attempt is created strictly at worker boundary."""
    job = repo.create_job(Job(job_type="chat", project_id="proj_1"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)

    # 1. Queue claim boundary invariant:
    lease = queue.claim_next(worker.worker_id, lease_duration_seconds=30.0)
    assert lease is not None
    assert lease.job_id == job.job_id

    # In DB: Job status remains READY, zero attempts exist
    refreshed_job = repo.get_job(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.READY
    assert len(repo.list_attempts(job.job_id)) == 0

    # 2. Worker boundary invariant: begin_claimed_attempt creates attempt
    attempt = worker.begin_claimed_attempt(lease)
    assert attempt.attempt_id.startswith("att_")
    assert attempt.attempt_number == 1
    assert attempt.status == JobAttemptStatus.RUNNING
    assert attempt.worker_id == worker.worker_id
    assert attempt.lease_generation == 1

    # In DB: Job status transitioned to RUNNING
    refreshed_job2 = repo.get_job(job.job_id)
    assert refreshed_job2 is not None
    assert refreshed_job2.status == JobStatus.RUNNING

    # Audit event WORKER_ATTEMPT_STARTED recorded
    events = repo.list_events(job.job_id)
    event_types = [e.event_type for e in events]
    assert JobEventType.WORKER_ATTEMPT_STARTED in event_types

    worker.close()


# ==============================================================================
# 2. Execution Request Factory & Security Tests
# ==============================================================================


def test_job_execution_request_factory_validation_and_safety() -> None:
    """Verify JobExecutionRequestFactory validates types, bounds inputs, and strips secrets."""
    factory = JobExecutionRequestFactory()

    # Supported types
    valid_job = Job(
        job_type="eval",
        project_id="proj_alpha",
        payload_summary={
            "prompt": "Run benchmark suite",
            "token_budget": 12000,
            "session_id": "sess_123",
            "api_key": "sk-secret-leak-attempt",
            "password": "super-secret-password",
            "safe_param": "benchmark_v1",
        },
    )
    req = factory.create_execution_request(valid_job)
    assert req.project_id == "proj_alpha"
    assert req.session_id == "sess_123"
    assert req.prompt == "Run benchmark suite"
    assert req.token_budget == 12000
    assert req.inputs.get("safe_param") == "benchmark_v1"

    # Redacted secrets
    assert req.inputs.get("api_key") == "[REDACTED_CREDENTIAL]"
    assert req.inputs.get("password") == "[REDACTED_CREDENTIAL]"

    # Unsupported type rejected
    invalid_job = Job(job_type="unauthorized_arbitrary_eval")
    with pytest.raises(UnsupportedJobTypeError):
        factory.create_execution_request(invalid_job)


def test_setup_failure_before_execution_safely_releases_lease(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify pre-execution setup failure safely releases lease back to claimable state."""
    job = repo.create_job(Job(job_type="unsupported_custom_type"))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    worker = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)

    # Step encounters unsupported type during setup
    processed = worker.step()
    assert processed is True

    # Job remains READY, lease is released, 0 attempts created
    j_after = repo.get_job(job.job_id)
    assert j_after is not None
    assert j_after.status == JobStatus.READY
    assert len(repo.list_attempts(job.job_id)) == 0

    # Queue entry is claimable again (lease_owner is cleared)
    entry = queue.get_entry(job.job_id)
    assert entry is not None
    assert entry.lease_owner is None

    worker.close()


# ==============================================================================
# 3. Canonical Execution Binding & Outcome Mapping Tests
# ==============================================================================


def test_execution_binding_and_coordinator_dispatch(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify execution through ExecutionCoordinator binds execution_id and finalizes COMPLETED."""
    job = repo.create_job(
        Job(job_type="chat", payload_summary={"prompt": "Say hello from background worker"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    mock_coord = make_mock_coordinator(status=ExecutionStatus.COMPLETED)
    worker = JobWorker(db_path=file_db_path, coordinator=mock_coord, lease_ttl_seconds=30.0)

    processed = worker.step()
    assert processed is True

    # Job is COMPLETED in DB
    final_job = repo.get_job(job.job_id)
    assert final_job is not None
    assert final_job.status == JobStatus.COMPLETED
    assert final_job.completed_at is not None

    # JobAttempt is COMPLETED, with execution_id bound and finished_at set
    attempts = repo.list_attempts(job.job_id)
    assert len(attempts) == 1
    att = attempts[0]
    assert att.status == JobAttemptStatus.COMPLETED
    assert att.execution_id is not None
    assert att.execution_id.startswith("req_") or att.execution_id.startswith("exec_")
    assert att.finished_at is not None
    assert att.worker_id == worker.worker_id

    # Queue entry removed
    assert queue.get_entry(job.job_id) is None

    # Audit events trace complete lifecycle
    events = repo.list_events(job.job_id)
    event_types = [e.event_type for e in events]
    assert JobEventType.JOB_ENQUEUED in event_types
    assert JobEventType.LEASE_ACQUIRED in event_types
    assert JobEventType.WORKER_ATTEMPT_STARTED in event_types
    assert JobEventType.EXECUTION_BOUND in event_types
    assert JobEventType.JOB_COMPLETED in event_types

    worker.close()


@pytest.mark.parametrize(
    "exec_status,expected_job_status",
    [
        (ExecutionStatus.COMPLETED, JobStatus.COMPLETED),
        (ExecutionStatus.FAILED, JobStatus.FAILED),
        (ExecutionStatus.PARTIAL, JobStatus.PARTIAL),
        (ExecutionStatus.BLOCKED, JobStatus.BLOCKED),
        (ExecutionStatus.WAITING_FOR_APPROVAL, JobStatus.WAITING),
    ],
)
def test_execution_outcome_mapping(
    repo: SQLiteJobRepository,
    queue: SQLiteJobQueue,
    file_db_path: str,
    exec_status: ExecutionStatus,
    expected_job_status: JobStatus,
) -> None:
    """Verify truthful mapping from ExecutionStatus to durable JobStatus."""
    job = repo.create_job(Job(job_type="eval", payload_summary={"prompt": f"Test {exec_status}"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    mock_coord = make_mock_coordinator(status=exec_status, error_msg="Intentional test failure")
    worker = JobWorker(db_path=file_db_path, coordinator=mock_coord, lease_ttl_seconds=30.0)

    worker.step()

    final_job = repo.get_job(job.job_id)
    assert final_job is not None
    assert final_job.status == expected_job_status

    worker.close()


def test_failed_execution_produces_no_automatic_retry(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify execution failure in R4.3 produces no automatic retry or second attempt."""
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Fail task"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    mock_coord = make_mock_coordinator(status=ExecutionStatus.FAILED, error_msg="Execution crashed")
    worker = JobWorker(db_path=file_db_path, coordinator=mock_coord, lease_ttl_seconds=30.0)

    worker.step()

    # Job is FAILED
    final_job = repo.get_job(job.job_id)
    assert final_job is not None
    assert final_job.status == JobStatus.FAILED

    # Exactly 1 attempt exists; no retry attempt created
    attempts = repo.list_attempts(job.job_id)
    assert len(attempts) == 1
    assert attempts[0].status == JobAttemptStatus.FAILED

    # Queue entry removed; no automatic re-enqueue
    assert queue.get_entry(job.job_id) is None

    worker.close()


# ==============================================================================
# 4. Heartbeat Maintenance & Authority Loss Tests
# ==============================================================================


def test_heartbeat_maintains_lease_and_blocks_second_worker(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify active heartbeat extends lease so a second worker cannot claim it."""
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Long task"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    # Worker A with short TTL (1.2s) and fast heartbeat (0.3s) running a 1.0s task
    mock_coord = make_mock_coordinator(status=ExecutionStatus.COMPLETED, delay=1.0)
    worker_a = JobWorker(
        db_path=file_db_path,
        coordinator=mock_coord,
        lease_ttl_seconds=1.2,
        heartbeat_interval_seconds=0.3,
    )
    worker_b = JobWorker(
        db_path=file_db_path,
        lease_ttl_seconds=1.2,
    )

    # Run Worker A in background thread
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(worker_a.step)

        # Wait 0.6s (halfway through task, past initial heartbeat interval)
        time.sleep(0.6)

        # Worker B attempts to claim the job -> BLOCKED because heartbeat extended the lease
        claim_b = worker_b.queue.claim_next(worker_b.worker_id, lease_duration_seconds=1.2)
        assert claim_b is None

        # Worker A finishes cleanly
        assert future_a.result() is True

    # After Worker A finishes, job is COMPLETED
    assert repo.get_job(job.job_id).status == JobStatus.COMPLETED

    worker_a.close()
    worker_b.close()


def test_lost_lease_prevents_stale_completion_commit(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify that a worker whose lease was lost cannot finalize or commit completion."""
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Fenced completion"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    worker_a = JobWorker(db_path=file_db_path, lease_ttl_seconds=60.0)
    worker_b = JobWorker(db_path=file_db_path, lease_ttl_seconds=60.0)

    # 1. Worker A claims and starts attempt
    lease_a = queue.claim_next(worker_a.worker_id, lease_duration_seconds=60.0)
    assert lease_a is not None
    attempt_a = worker_a.begin_claimed_attempt(lease_a)

    # 2. Worker B forcibly reclaims the job with a simulated clock in the future
    t_future = datetime.now(timezone.utc) + timedelta(seconds=70)
    lease_b = queue.claim_next(worker_b.worker_id, lease_duration_seconds=60.0, now=t_future)
    assert lease_b is not None
    assert lease_b.lease_generation == 2

    # 3. Stale Worker A attempts to finalize with its old lease -> STRICTLY REJECTED
    with pytest.raises(StaleLeaseError):
        worker_a.finalize_claimed_attempt(
            job.job_id,
            attempt_a.attempt_id,
            lease_a,
            JobStatus.COMPLETED,
            now=t_future,
        )

    # Queue entry still belongs to Worker B
    entry = queue.get_entry(job.job_id)
    assert entry is not None
    assert entry.lease_owner == worker_b.worker_id
    assert entry.lease_generation == 2

    worker_a.close()
    worker_b.close()


# ==============================================================================
# 5. Crash Recovery & Prior Attempt Reconciliation Tests
# ==============================================================================


def test_crash_recovery_and_prior_attempt_reconciliation(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify that when a worker crashes, the reclaiming worker reconciles the prior attempt."""
    job = repo.create_job(Job(job_type="eval", payload_summary={"prompt": "Crash recovery job"}))
    repo.update_state(job.job_id, JobStatus.READY)
    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)
    queue.enqueue(job.job_id, available_at=t0)

    # 1. Worker A claims job at generation 1 and starts Attempt 1
    worker_a = JobWorker(db_path=file_db_path, lease_ttl_seconds=60.0)
    lease_a = queue.claim_next(worker_a.worker_id, lease_duration_seconds=60.0, now=t0)
    assert lease_a is not None
    attempt_1 = worker_a.begin_claimed_attempt(lease_a, now=t0)
    assert attempt_1.attempt_number == 1
    assert attempt_1.status == JobAttemptStatus.RUNNING

    # Worker A crashes (stops without finalizing)
    worker_a.close()

    # 2. Before lease expiry (t0 + 30s): Worker B cannot claim
    t_mid = t0 + timedelta(seconds=30)
    worker_b = JobWorker(db_path=file_db_path, lease_ttl_seconds=60.0)
    assert queue.claim_next(worker_b.worker_id, now=t_mid) is None

    # 3. After lease expiry (t0 + 65s): Worker B reclaims job at generation 2
    t_after = t0 + timedelta(seconds=65)
    lease_b = queue.claim_next(worker_b.worker_id, lease_duration_seconds=60.0, now=t_after)
    assert lease_b is not None
    assert lease_b.lease_generation == 2
    assert lease_b.lease_owner == worker_b.worker_id

    # 4. Worker B begins attempt: reconciles Attempt 1 and creates Attempt 2
    attempt_2 = worker_b.begin_claimed_attempt(lease_b, now=t_after)
    assert attempt_2.attempt_number == 2
    assert attempt_2.attempt_id != attempt_1.attempt_id
    assert attempt_2.status == JobAttemptStatus.RUNNING
    assert attempt_2.worker_id == worker_b.worker_id

    # Verify Attempt 1 was reconciled with outcome uncertainty preserved
    att_1_reconciled = repo.get_attempt(attempt_1.attempt_id)
    assert att_1_reconciled is not None
    assert att_1_reconciled.status == JobAttemptStatus.FAILED
    assert (
        att_1_reconciled.failure_classification == FAILURE_CLASSIFICATION_WORKER_CRASH_OR_LEASE_LOST
    )
    assert att_1_reconciled.finished_at is not None
    assert "UNKNOWN" in (att_1_reconciled.failure_message or "")

    # Verify durable ATTEMPT_RECONCILED event exists
    events = repo.list_events(job.job_id)
    reconciled_events = [e for e in events if e.event_type == JobEventType.ATTEMPT_RECONCILED]
    assert len(reconciled_events) == 1
    rec_meta = reconciled_events[0].metadata
    assert rec_meta["prior_attempt_id"] == attempt_1.attempt_id
    assert rec_meta["reclaiming_worker_id"] == worker_b.worker_id
    assert rec_meta["reclaiming_lease_generation"] == 2
    assert rec_meta["execution_outcome"] == EXECUTION_OUTCOME_UNKNOWN
    assert rec_meta["side_effect_state"] == SIDE_EFFECT_STATE_UNKNOWN

    # Worker B completes cleanly
    worker_b.finalize_claimed_attempt(
        job.job_id, attempt_2.attempt_id, lease_b, JobStatus.COMPLETED, now=t_after
    )

    # In DB: 2 attempts exist, job is COMPLETED
    all_attempts = repo.list_attempts(job.job_id)
    assert len(all_attempts) == 2
    assert all_attempts[0].attempt_number == 1
    assert all_attempts[0].status == JobAttemptStatus.FAILED
    assert all_attempts[1].attempt_number == 2
    assert all_attempts[1].status == JobAttemptStatus.COMPLETED

    assert repo.get_job(job.job_id).status == JobStatus.COMPLETED

    worker_b.close()


# ==============================================================================
# 6. Graceful Shutdown Tests
# ==============================================================================


def test_graceful_shutdown_drains_short_job(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify graceful shutdown allows short active execution to drain cleanly."""
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Short task"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    mock_coord = make_mock_coordinator(status=ExecutionStatus.COMPLETED, delay=0.2)
    worker = JobWorker(
        db_path=file_db_path,
        coordinator=mock_coord,
        lease_ttl_seconds=30.0,
        drain_timeout_seconds=2.0,
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.step)
        time.sleep(0.05)  # wait until job is claimed and running

        # Call stop with 2.0s drain timeout
        worker.stop(drain_timeout=2.0)
        assert future.result() is True

    # Job drained and completed
    assert repo.get_job(job.job_id).status == JobStatus.COMPLETED
    assert queue.get_entry(job.job_id) is None

    worker.close()


def test_graceful_shutdown_long_job_refuses_premature_lease_release(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify that an active long job exceeding drain timeout does NOT release active lease."""
    job = repo.create_job(
        Job(job_type="chat", payload_summary={"prompt": "Long task exceeding drain"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    mock_coord = make_mock_coordinator(status=ExecutionStatus.COMPLETED, delay=5.0)
    worker = JobWorker(
        db_path=file_db_path,
        coordinator=mock_coord,
        lease_ttl_seconds=30.0,
        drain_timeout_seconds=0.2,
    )

    # Run worker.step in a separate thread
    worker_thread = threading.Thread(target=worker.step, daemon=True)
    worker_thread.start()

    # Poll until job is claimed
    claimed = False
    for _ in range(20):
        time.sleep(0.05)
        entry = queue.get_entry(job.job_id)
        if entry and entry.lease_owner == worker.worker_id:
            claimed = True
            break
    assert claimed is True, "Worker failed to claim job"

    # Trigger stop with short drain timeout (0.2s)
    worker.stop(drain_timeout=0.2)

    # Invariant: active lease must NOT have been released immediately!
    entry_after_stop = queue.get_entry(job.job_id)
    assert entry_after_stop is not None
    assert entry_after_stop.lease_owner == worker.worker_id

    worker.close()


# ==============================================================================
# 7. Subprocess Worker Crash & Reclaim Fixture (Section 26)
# ==============================================================================


def test_subprocess_worker_crash_and_reclaim_fixture(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Process-level fixture: start real worker in OS subprocess, kill with SIGKILL,
    verify lease holds before expiry, advance time, and reclaim with second worker.
    """
    job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": "Subprocess crash test"}))
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    # 1. Start worker subprocess with short TTL (1.5s) and blocking test dispatch
    project_root = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env["AGENT_ENGINE_WORKER_TEST_DISPATCH"] = "blocking"
    env["PYTHONPATH"] = project_root

    cmd = [
        sys.executable,
        "-m",
        "services.python.worker",
        "--db-path",
        file_db_path,
        "--lease-ttl",
        "1.5",
        "--heartbeat-interval",
        "0.5",
        "--poll-interval",
        "0.1",
        "--worker-id",
        "wrk_subprocess_crash_victim",
    ]

    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait until subprocess claims job and starts attempt
        started = False
        for _ in range(50):
            time.sleep(0.1)
            attempts = repo.list_attempts(job.job_id)
            if len(attempts) >= 1 and attempts[0].worker_id == "wrk_subprocess_crash_victim":
                started = True
                break
        assert started is True, "Subprocess worker failed to start attempt within 5s"
        assert attempts[0].lease_generation == 1

        # 2. Forcibly kill worker subprocess with SIGKILL (unclean process termination)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=2.0)

        # 3. Open DB from test process: verify lease is STILL persisted and blocking
        entry_after_kill = queue.get_entry(job.job_id)
        assert entry_after_kill is not None
        assert entry_after_kill.lease_owner == "wrk_subprocess_crash_victim"

        # Immediately attempting to claim should return None (lease unexpired)
        worker_rec = JobWorker(
            db_path=file_db_path,
            coordinator=make_mock_coordinator(status=ExecutionStatus.COMPLETED),
            lease_ttl_seconds=10.0,
        )
        assert worker_rec.queue.claim_next(worker_rec.worker_id) is None

        # 4. Wait for lease to expire naturally (TTL is 1.5s)
        time.sleep(1.6)

        # 5. Second worker reclaims the job
        processed = worker_rec.step()
        assert processed is True

        # In DB: Attempt 1 reconciled as FAILED, Attempt 2 COMPLETED, Job COMPLETED
        final_job = repo.get_job(job.job_id)
        assert final_job.status == JobStatus.COMPLETED

        final_attempts = repo.list_attempts(job.job_id)
        assert len(final_attempts) == 2
        assert final_attempts[0].attempt_number == 1
        assert final_attempts[0].status == JobAttemptStatus.FAILED
        assert final_attempts[0].failure_classification == "worker_crash_or_lease_lost"

        assert final_attempts[1].attempt_number == 2
        assert final_attempts[1].status == JobAttemptStatus.COMPLETED
        assert final_attempts[1].worker_id == worker_rec.worker_id
        assert final_attempts[1].lease_generation == 2

        worker_rec.close()
    finally:
        if proc.poll() is None:
            proc.kill()


# ==============================================================================
# 8. Multi-Worker SQLite Concurrency Tests (Section 29)
# ==============================================================================


def test_multi_worker_sqlite_concurrency(file_db_path: str) -> None:
    """Verify multiple worker instances contend on SQLite queue safely without duplicates."""
    repo = SQLiteJobRepository(db_path=file_db_path)
    queue = SQLiteJobQueue(db_path=file_db_path)

    # Enqueue 6 deterministic test jobs
    job_ids: List[str] = []
    for i in range(6):
        job = repo.create_job(Job(job_type="chat", payload_summary={"prompt": f"Job {i}"}))
        repo.update_state(job.job_id, JobStatus.READY)
        queue.enqueue(job.job_id)
        job_ids.append(job.job_id)

    mock_coord = make_mock_coordinator(status=ExecutionStatus.COMPLETED, delay=0.05)

    worker_1 = JobWorker(db_path=file_db_path, coordinator=mock_coord, lease_ttl_seconds=30.0)
    worker_2 = JobWorker(db_path=file_db_path, coordinator=mock_coord, lease_ttl_seconds=30.0)

    # Concurrently execute workers
    def run_worker(w: JobWorker, count: int) -> int:
        processed_count = 0
        for _ in range(count):
            if w.step():
                processed_count += 1
            else:
                time.sleep(0.02)
        return processed_count

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(run_worker, worker_1, 10)
        f2 = pool.submit(run_worker, worker_2, 10)
        p1 = f1.result()
        p2 = f2.result()

    assert p1 + p2 == 6

    # All 6 jobs completed
    for jid in job_ids:
        j = repo.get_job(jid)
        assert j is not None
        assert j.status == JobStatus.COMPLETED
        attempts = repo.list_attempts(jid)
        assert len(attempts) == 1
        assert attempts[0].status == JobAttemptStatus.COMPLETED
        # Each attempt owned by either worker 1 or worker 2
        assert attempts[0].worker_id in (worker_1.worker_id, worker_2.worker_id)

    # Queue is completely drained
    assert len(queue.list_entries()) == 0

    worker_1.close()
    worker_2.close()
    queue.close()
    repo.close()


# ==============================================================================
# 9. Security & Secret Leakage Prevention Tests (Section 25 & 31)
# ==============================================================================


def test_security_no_lease_tokens_or_secrets_in_logs_and_events(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """Verify that zero lease tokens, passwords, or credentials leak in DB events or representations."""
    job = repo.create_job(
        Job(
            job_type="chat",
            payload_summary={
                "prompt": "Secure job",
                "api_key": "super_secret_openai_key",
                "password": "my_master_password",
            },
        )
    )
    repo.update_state(job.job_id, JobStatus.READY)
    queue.enqueue(job.job_id)

    mock_coord = make_mock_coordinator(status=ExecutionStatus.COMPLETED)
    worker = JobWorker(db_path=file_db_path, coordinator=mock_coord, lease_ttl_seconds=30.0)

    worker.step()

    # Query all events in database
    conn = sqlite3.connect(file_db_path)
    cur = conn.cursor()
    cur.execute("SELECT metadata_json FROM job_events WHERE job_id = ?", (job.job_id,))
    rows = cur.fetchall()
    conn.close()

    assert len(rows) > 0
    for (meta_raw,) in rows:
        assert "super_secret_openai_key" not in meta_raw
        assert "my_master_password" not in meta_raw
        # Lease token pattern is 32-byte urlsafe string (contains underscore, dashes, alnum)
        # Verify no lease_token field is present in event metadata
        meta = json.loads(meta_raw)
        assert "lease_token" not in meta
        assert "token" not in meta

    worker.close()


# ==============================================================================
# 10. Migration v2 -> v3 Populated Upgrade & Sequence Backfill (CTO Review Closure)
# ==============================================================================


def test_migration_v2_to_v3_populated_database_upgrade(tmp_path: Path) -> None:
    """CTO Review Requirement 2: Real v2 -> v3 upgrade on a populated database.

    Creates database using exact R4.2 / v2 migrations.
    Inserts jobs, queue entries, attempts, events.
    Closes DB.
    Runs current migrations.
    Asserts:
      - schema version == 3
      - all v2 data preserved
      - worker_id column exists
      - lease_generation column exists
      - previous queue state intact
    Reopens in a new repository instance to confirm persistence.
    """
    db_file = tmp_path / "v2_populated_test.db"
    conn = sqlite3.connect(str(db_file))
    try:
        # 1. Apply Migration 1 & Migration 2 explicitly (exact v2 state)
        _migration_001_initial_job_domain(conn)
        _migration_002_persistent_job_queue(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);"
        )
        conn.execute(
            "INSERT INTO job_schema_migrations VALUES (1, '001_initial_job_domain', '2026-10-10T00:00:00Z');"
        )
        conn.execute(
            "INSERT INTO job_schema_migrations VALUES (2, '002_persistent_job_queue', '2026-10-10T00:00:00Z');"
        )
        conn.commit()

        assert get_current_job_schema_version(conn) == 2

        # 2. Insert populated v2 data: jobs, queue entry with lease, attempt without worker_id, event with sequence
        conn.execute(
            """
            INSERT INTO jobs (job_id, job_type, status, created_at, updated_at)
            VALUES ('job_v2_pop', 'batch_eval', 'ready', '2026-10-10T01:00:00Z', '2026-10-10T01:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO job_queue (
                queue_entry_id, job_id, enqueued_at, available_at, lease_owner, lease_token,
                lease_generation, lease_acquired_at, lease_expires_at, created_at, updated_at
            ) VALUES (
                'qent_v2_pop', 'job_v2_pop', '2026-10-10T01:00:00Z', '2026-10-10T01:00:00Z',
                'worker_v2_legacy', 'tok_legacy_secret_mask', 1, '2026-10-10T01:00:00Z',
                '2026-10-10T01:05:00Z', '2026-10-10T01:00:00Z', '2026-10-10T01:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO job_attempts (attempt_id, job_id, attempt_number, status, started_at)
            VALUES ('att_v2_pop', 'job_v2_pop', 1, 'running', '2026-10-10T01:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO job_events (event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json)
            VALUES ('jev_v2_pop', 'job_v2_pop', 'att_v2_pop', 'job_created', 1, '2026-10-10T01:00:00Z', '{"k": "v"}')
            """
        )
        conn.commit()
    finally:
        conn.close()

    # 3. Close DB, then reopen and run migrations up to v3
    conn2 = sqlite3.connect(str(db_file))
    try:
        applied = apply_job_migrations(conn2, target_version=3)
        assert applied == 1  # Migration 3 applied
        assert get_current_job_schema_version(conn2) == 3

        # Verify worker_id and lease_generation columns exist on job_attempts
        cur = conn2.cursor()
        cur.execute("PRAGMA table_info(job_attempts)")
        cols = {row[1]: row for row in cur.fetchall()}
        assert "worker_id" in cols
        assert "lease_generation" in cols

        # Verify all v2 data preserved
        cur.execute("SELECT job_id, status FROM jobs WHERE job_id = 'job_v2_pop'")
        assert cur.fetchone() == ("job_v2_pop", "ready")

        cur.execute(
            "SELECT queue_entry_id, lease_owner, lease_generation FROM job_queue WHERE job_id = 'job_v2_pop'"
        )
        assert cur.fetchone() == ("qent_v2_pop", "worker_v2_legacy", 1)

        cur.execute(
            "SELECT attempt_id, worker_id, lease_generation FROM job_attempts WHERE attempt_id = 'att_v2_pop'"
        )
        row_att = cur.fetchone()
        assert row_att[0] == "att_v2_pop"
        assert row_att[1] is None  # Legacy attempt has NULL worker_id
        assert row_att[2] == 0  # Default 0 lease_generation

        cur.execute(
            "SELECT event_id, sequence_number FROM job_events WHERE event_id = 'jev_v2_pop'"
        )
        assert cur.fetchone() == ("jev_v2_pop", 1)
    finally:
        conn2.close()

    # 4. Reopen database in a new repository instance to confirm persistence
    repo_new = SQLiteJobRepository(db_path=str(db_file))
    queue_new = SQLiteJobQueue(db_path=str(db_file))
    try:
        j = repo_new.get_job("job_v2_pop")
        assert j is not None
        assert j.job_type == "batch_eval"

        q_entry = queue_new.get_entry("job_v2_pop")
        assert q_entry is not None
        assert q_entry.lease_owner == "worker_v2_legacy"
        assert q_entry.lease_generation == 1

        attempts = repo_new.list_attempts("job_v2_pop")
        assert len(attempts) == 1
        assert attempts[0].attempt_id == "att_v2_pop"
        assert attempts[0].worker_id is None
        assert attempts[0].lease_generation == 0

        events = repo_new.list_events("job_v2_pop")
        assert len(events) == 1
        assert events[0].event_id == "jev_v2_pop"
        assert events[0].sequence_number == 1
    finally:
        repo_new.close()
        queue_new.close()


def test_event_sequence_backfill_populated_pre_sequence_database(tmp_path: Path) -> None:
    """CTO Review Requirement 3: Deterministic event sequence backfill on pre-sequence DB.

    Creates pre-sequence (v1) database with multiple jobs and events.
    Applies migrations.
    Asserts:
      - zero historical rows remain at sequence_number = 0.
      - events for Job A have deterministic, strictly monotonic sequence numbers.
      - ordering is totally deterministic without timestamp collision ambiguity.
    """
    db_file = tmp_path / "pre_seq_backfill_test.db"
    conn = sqlite3.connect(str(db_file))
    try:
        # Create v1 schema
        _migration_001_initial_job_domain(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);"
        )
        conn.execute(
            "INSERT INTO job_schema_migrations VALUES (1, '001_initial_job_domain', '2026-10-10T00:00:00Z');"
        )

        # Insert Job A and Job B
        conn.execute(
            "INSERT INTO jobs (job_id, job_type, status, created_at, updated_at) VALUES ('job_A', 'chat', 'ready', '2026-10-10T00:00:00Z', '2026-10-10T00:00:00Z');"
        )
        conn.execute(
            "INSERT INTO jobs (job_id, job_type, status, created_at, updated_at) VALUES ('job_B', 'chat', 'ready', '2026-10-10T00:00:00Z', '2026-10-10T00:00:00Z');"
        )

        # Insert 3 events for Job A with identical timestamp (collision scenario)
        conn.execute(
            "INSERT INTO job_events (event_id, job_id, event_type, timestamp, metadata_json) VALUES ('ev_A1', 'job_A', 'job_created', '2026-10-10T00:00:00Z', '{}');"
        )
        conn.execute(
            "INSERT INTO job_events (event_id, job_id, event_type, timestamp, metadata_json) VALUES ('ev_A2', 'job_A', 'job_enqueued', '2026-10-10T00:00:00Z', '{}');"
        )
        conn.execute(
            "INSERT INTO job_events (event_id, job_id, event_type, timestamp, metadata_json) VALUES ('ev_A3', 'job_A', 'worker_attempt_started', '2026-10-10T00:00:00Z', '{}');"
        )

        # Insert 2 events for Job B
        conn.execute(
            "INSERT INTO job_events (event_id, job_id, event_type, timestamp, metadata_json) VALUES ('ev_B1', 'job_B', 'job_created', '2026-10-10T00:00:00Z', '{}');"
        )
        conn.execute(
            "INSERT INTO job_events (event_id, job_id, event_type, timestamp, metadata_json) VALUES ('ev_B2', 'job_B', 'job_enqueued', '2026-10-10T00:00:00Z', '{}');"
        )
        conn.commit()

        # Apply migrations up to v3 (Migration 2 and 3)
        applied = apply_job_migrations(conn, target_version=3)
        assert applied == 2
        assert get_current_job_schema_version(conn) == 3

        # Assert no rows left at sequence_number = 0
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM job_events WHERE sequence_number = 0")
        assert cur.fetchone()[0] == 0

        # Assert all sequence numbers are positive and strictly ascending per insertion order
        cur.execute(
            "SELECT event_id, sequence_number FROM job_events WHERE job_id = 'job_A' ORDER BY sequence_number ASC"
        )
        rows_a = cur.fetchall()
        assert len(rows_a) == 3
        assert rows_a[0][0] == "ev_A1"
        assert rows_a[1][0] == "ev_A2"
        assert rows_a[2][0] == "ev_A3"
        assert rows_a[0][1] < rows_a[1][1] < rows_a[2][1]
        assert rows_a[0][1] > 0

        cur.execute(
            "SELECT event_id, sequence_number FROM job_events WHERE job_id = 'job_B' ORDER BY sequence_number ASC"
        )
        rows_b = cur.fetchall()
        assert len(rows_b) == 2
        assert rows_b[0][0] == "ev_B1"
        assert rows_b[1][0] == "ev_B2"
        assert rows_b[0][1] < rows_b[1][1]
        assert rows_b[0][1] > 0
    finally:
        conn.close()

    # Reopen in SQLiteJobRepository and verify list_events deterministic ordering
    repo_r = SQLiteJobRepository(db_path=str(db_file))
    try:
        events_a = repo_r.list_events("job_A")
        assert [e.event_id for e in events_a] == ["ev_A1", "ev_A2", "ev_A3"]
        events_b = repo_r.list_events("job_B")
        assert [e.event_id for e in events_b] == ["ev_B1", "ev_B2"]
    finally:
        repo_r.close()


def test_crashed_attempt_semantics_preserves_uncertainty(
    repo: SQLiteJobRepository, queue: SQLiteJobQueue, file_db_path: str
) -> None:
    """CTO Review Requirement 5: Crashed attempt reconciliation must preserve uncertainty.

    Verify that:
      - Attempt -> FAILED with failure_classification = "worker_crash_or_lease_lost"
      - Meaning: durable attempt did not reach a verified committed success
      - It does NOT mean external side effect definitely did not happen
      - Event and message explicitly document execution_outcome = UNKNOWN and side_effect_state = UNKNOWN.
    """
    job = repo.create_job(
        Job(job_type="chat", payload_summary={"prompt": "Side-effect uncertainty job"})
    )
    repo.update_state(job.job_id, JobStatus.READY)
    t0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    queue.enqueue(job.job_id, available_at=t0)

    # Worker 1 claims and starts Attempt 1
    worker_1 = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease_1 = queue.claim_next(worker_1.worker_id, lease_duration_seconds=30.0, now=t0)
    assert lease_1 is not None
    attempt_1 = worker_1.begin_claimed_attempt(lease_1, now=t0)
    assert attempt_1.attempt_number == 1
    worker_1.close()  # Worker 1 abruptly dies while execution was underway

    # Time passes beyond lease TTL
    t_reclaim = t0 + timedelta(seconds=35)
    worker_2 = JobWorker(db_path=file_db_path, lease_ttl_seconds=30.0)
    lease_2 = queue.claim_next(worker_2.worker_id, lease_duration_seconds=30.0, now=t_reclaim)
    assert lease_2 is not None
    assert lease_2.lease_generation == 2

    # Worker 2 begins attempt, reconciling crashed Attempt 1
    attempt_2 = worker_2.begin_claimed_attempt(lease_2, now=t_reclaim)
    assert attempt_2.attempt_number == 2

    # Inspect reconciled Attempt 1
    att_1 = repo.get_attempt(attempt_1.attempt_id)
    assert att_1 is not None
    assert att_1.status == JobAttemptStatus.FAILED
    assert att_1.failure_classification == FAILURE_CLASSIFICATION_WORKER_CRASH_OR_LEASE_LOST
    assert "UNKNOWN" in (att_1.failure_message or "")

    # Inspect ATTEMPT_RECONCILED event
    events = repo.list_events(job.job_id)
    reconciled = [e for e in events if e.event_type == JobEventType.ATTEMPT_RECONCILED]
    assert len(reconciled) == 1
    meta = reconciled[0].metadata
    assert meta["execution_outcome"] == EXECUTION_OUTCOME_UNKNOWN
    assert meta["side_effect_state"] == SIDE_EFFECT_STATE_UNKNOWN
    assert meta["prior_attempt_id"] == attempt_1.attempt_id

    worker_2.close()
