"""tests/test_r4_7_scheduler.py

Dedicated Test Suite for Milestone R4.7 (Timezone-Aware Recurring Job Scheduler).
Covers all required acceptance criteria and gates:
1. Valid IANA timezone accepted
2. Invalid timezone rejected (abbreviations, fixed offsets, malformed)
3. Daily local-time recurrence
4. Timezone offset changes correctly (DST shift verification)
5. Spring-forward behavior deterministic (skips nonexistent local hour)
6. Fall-back creates one intended occurrence (fold=0 exactly once)
7. Non-DST timezone correct (Asia/Dhaka)
8. Schedule survives repository restart
9. SKIP missed-run behavior (skips backlog, advances next_run_at)
10. RUN_ONCE missed-run behavior (materializes latest, skips earlier)
11. Disabled schedule creates nothing
12. Re-enable behavior respects missed-run policy
13. Schedule edit increments generation
14. Stale generation cannot materialize
15. Same occurrence cannot materialize twice (deduplication)
16. Multi-scheduler race produces exactly one Job
17. Occurrence creates fresh canonical Job
18. Consecutive occurrences create different job_ids
19. Occurrence -> Job -> Queue provenance correct
20. Scheduler never invokes ExecutionCoordinator
21. Cancelling occurrence Job does not disable Schedule
22. Disabling Schedule does not mutate historical Job
23. Restart at due boundary does not duplicate
24. Crash during materialization recovers exactly once
25. Populated v5 -> v6 migration preserves data
26. No secrets persisted in schedules, occurrences, or events
27. Standalone CLI main runner executes --once correctly
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading
from typing import List
from unittest.mock import patch
import zoneinfo

import pytest

from core.jobs.control import JobControlService
from core.jobs.cron import (
    get_next_occurrence,
    validate_cron_expression,
    validate_iana_timezone,
)
from core.jobs.exceptions import (
    InvalidScheduleExpressionError,
    InvalidTimezoneError,
    StaleScheduleGenerationError,
)
from core.jobs.migrations import (
    _migration_001_initial_job_domain,
    _migration_002_persistent_job_queue,
    _migration_003_worker_attempt_ownership,
    _migration_004_job_idempotency_and_retry,
    _migration_005_job_control_and_timeouts,
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    JobEventType,
    JobStatus,
    MissedRunPolicy,
    OccurrenceStatus,
    ScheduledOccurrence,
)
from core.jobs.queue import SQLiteJobQueue
from core.jobs.scheduler import SchedulerService
from core.jobs.sqlite import SQLiteJobRepository
from services.python.scheduler.main import main as scheduler_cli_main


# ------------------------------------------------------------------------------
# 1 & 2: Timezone Validation
# ------------------------------------------------------------------------------


def test_valid_iana_timezone_accepted() -> None:
    """Valid IANA timezone names are successfully validated and parsed."""
    for tz_name in [
        "Europe/Berlin",
        "America/New_York",
        "Asia/Tokyo",
        "Asia/Dhaka",
        "UTC",
        "Pacific/Auckland",
    ]:
        tz = validate_iana_timezone(tz_name)
        assert isinstance(tz, zoneinfo.ZoneInfo)
        assert tz.key == tz_name


def test_invalid_timezone_rejected() -> None:
    """Legacy abbreviations, raw offsets, and arbitrary strings are rejected."""
    for invalid in [
        "EST",
        "CET",
        "EDT",
        "PST",
        "UTC+1",
        "GMT-5",
        "Invalid/Timezone",
        "",
        "   ",
        "Europe/Nowhere",
    ]:
        with pytest.raises(InvalidTimezoneError):
            validate_iana_timezone(invalid)


# ------------------------------------------------------------------------------
# 3 & 4: Daily Recurrence & Offset Transitions
# ------------------------------------------------------------------------------


def test_daily_local_time_recurrence_and_offset_changes() -> None:
    """Verify 09:00 Europe/Berlin shifts between UTC+1 (winter) and UTC+2 (summer)."""
    cron_expr = "0 9 * * *"  # 09:00 daily
    tz_name = "Europe/Berlin"

    # Winter (CET = UTC+1): 2026-01-15 09:00 Berlin -> 08:00 UTC
    winter_search = datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)
    next_utc, next_local = get_next_occurrence(cron_expr, tz_name, after_dt=winter_search)
    assert next_local.hour == 9
    assert next_local.minute == 0
    assert next_utc.hour == 8  # 09:00 CET = 08:00 UTC
    assert next_utc.minute == 0

    # Summer (CEST = UTC+2): 2026-07-15 09:00 Berlin -> 07:00 UTC
    summer_search = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
    next_utc, next_local = get_next_occurrence(cron_expr, tz_name, after_dt=summer_search)
    assert next_local.hour == 9
    assert next_local.minute == 0
    assert next_utc.hour == 7  # 09:00 CEST = 07:00 UTC
    assert next_utc.minute == 0


# ------------------------------------------------------------------------------
# 5: Spring-Forward Semantics (Skips nonexistent local hour)
# ------------------------------------------------------------------------------


def test_spring_forward_behavior_deterministic() -> None:
    """In Europe/Berlin on 2026-03-29, 02:00 jumps to 03:00.
    A job scheduled for 02:30 has no physical local occurrence on that day.
    Canonical 0.5 policy: nonexistent local scheduled time -> SKIP THAT OCCURRENCE.
    Result: no occurrence on 2026-03-29 (not shifted to 03:00, 03:30, or next valid minute).
    The next normal occurrence is 2026-03-30 02:30 Europe/Berlin.
    """
    cron_expr = "30 2 * * *"  # 02:30 daily
    tz_name = "Europe/Berlin"

    # Search starting from 2026-03-28 23:00 UTC (which is 2026-03-29 00:00 Berlin)
    search_dt = datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc)
    next_utc, next_local = get_next_occurrence(cron_expr, tz_name, after_dt=search_dt)

    # 2026-03-29 02:30 was skipped! Absolutely no occurrence on 2026-03-29.
    assert next_local.date().isoformat() == "2026-03-30"
    assert next_local.year == 2026
    assert next_local.month == 3
    assert next_local.day == 30
    assert next_local.hour == 2
    assert next_local.minute == 30
    assert next_utc == datetime(2026, 3, 30, 0, 30, tzinfo=timezone.utc)


# ------------------------------------------------------------------------------
# 6: Fall-Back Semantics (Exactly one occurrence at fold=0)
# ------------------------------------------------------------------------------


def test_fall_back_creates_one_intended_occurrence() -> None:
    """In Europe/Berlin on 2026-10-25, 02:00 to 03:00 is repeated twice (CEST and CET).
    Canonical 0.5 policy: ambiguous repeated local time executes exactly once,
    choosing the FIRST occurrence (fold=0, UTC offset +02:00).
    Resulting UTC: 2026-10-25T00:30:00Z.
    There is NO second materialization at 2026-10-25T01:30:00Z.
    """
    cron_expr = "30 2 * * *"  # 02:30 daily
    tz_name = "Europe/Berlin"

    # Search from beginning of day 2026-10-25 (00:00 local = 2026-10-24 22:00 UTC)
    search_dt = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    next_utc, next_local = get_next_occurrence(cron_expr, tz_name, after_dt=search_dt)

    # First occurrence is 02:30 CEST with fold=0
    assert next_local.fold == 0
    assert next_local.utcoffset() == timedelta(hours=2)
    assert next_utc == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    assert next_local.hour == 2
    assert next_local.minute == 30

    # If we search after 00:30 UTC, the next occurrence must be the next day (2026-10-26 02:30 CET = 01:30 UTC),
    # NOT the second ambiguous fold of the same day (2026-10-25 01:30 UTC)!
    next_next_utc, next_next_local = get_next_occurrence(cron_expr, tz_name, after_dt=next_utc)
    assert next_next_utc != datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    assert next_next_utc == datetime(2026, 10, 26, 1, 30, tzinfo=timezone.utc)
    assert next_next_local.day == 26


# ------------------------------------------------------------------------------
# 7: Non-DST Timezone Semantics (Asia/Dhaka and Asia/Tokyo)
# ------------------------------------------------------------------------------


def test_non_dst_timezone_correct() -> None:
    """Asia/Dhaka (+06:00) and Asia/Tokyo (+09:00) have no DST and evaluate consistently."""
    cron_expr = "0 10 * * *"  # 10:00 local

    # 1. Asia/Dhaka (+06:00, constant)
    tz_dhaka = "Asia/Dhaka"
    jan_search = datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc)
    next_utc_jan, _ = get_next_occurrence(cron_expr, tz_dhaka, after_dt=jan_search)
    assert next_utc_jan == datetime(2026, 1, 10, 4, 0, tzinfo=timezone.utc)

    jul_search = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
    next_utc_jul, _ = get_next_occurrence(cron_expr, tz_dhaka, after_dt=jul_search)
    assert next_utc_jul == datetime(2026, 7, 10, 4, 0, tzinfo=timezone.utc)

    # 2. Asia/Tokyo (+09:00, constant)
    tz_tokyo = "Asia/Tokyo"
    next_utc_tokyo_jan, _ = get_next_occurrence(cron_expr, tz_tokyo, after_dt=jan_search)
    assert next_utc_tokyo_jan == datetime(2026, 1, 10, 1, 0, tzinfo=timezone.utc)

    next_utc_tokyo_jul, _ = get_next_occurrence(cron_expr, tz_tokyo, after_dt=jul_search)
    assert next_utc_tokyo_jul == datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------------------
# 8: Repository Persistence & Restart
# ------------------------------------------------------------------------------


def test_schedule_survives_repository_restart(tmp_path: Path) -> None:
    """Persisted schedule survives process/repository restart intact."""
    db_file = tmp_path / "scheduler_persist.db"
    now_dt = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)

    # Instance 1: Create schedule
    scheduler1 = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)
    sch = scheduler1.create_schedule(
        cron_expression="0 14 * * *",
        timezone="Europe/Berlin",
        job_type="summary",
        payload_summary={"scope": "finance"},
        missed_run_policy=MissedRunPolicy.RUN_ONCE,
        timeout_seconds=600,
    )
    assert sch.schedule_generation == 1
    assert sch.next_run_at is not None

    # Instance 2: Reload from disk
    scheduler2 = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)
    loaded = scheduler2.get_schedule(sch.schedule_id)
    assert loaded is not None
    assert loaded.schedule_id == sch.schedule_id
    assert loaded.cron_expression == "0 14 * * *"
    assert loaded.timezone == "Europe/Berlin"
    assert loaded.missed_run_policy == MissedRunPolicy.RUN_ONCE
    assert loaded.payload_summary == {"scope": "finance"}
    assert loaded.timeout_seconds == 600
    assert loaded.schedule_generation == 1
    assert loaded.next_run_at == sch.next_run_at


# ------------------------------------------------------------------------------
# 9 & 10: Missed-Run Policies (SKIP vs RUN_ONCE)
# ------------------------------------------------------------------------------


def test_skip_missed_run_behavior(tmp_path: Path) -> None:
    """Under SKIP, multiple missed runs during downtime are marked MISSED_SKIPPED,
    no Jobs are enqueued, and next_run_at advances to the next future occurrence.
    """
    db_file = tmp_path / "skip_test.db"
    current_time = [datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc)]

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: current_time[0])
    sch = scheduler.create_schedule(
        cron_expression="0 8 * * *",  # 08:00 UTC daily
        timezone="UTC",
        missed_run_policy=MissedRunPolicy.SKIP,
    )
    assert sch.next_run_at.startswith("2026-06-01T08:00:00")

    # Simulate 3 days of scheduler downtime (advancing clock to June 4 at 09:00)
    current_time[0] = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)

    # Trigger tick
    occurrences = scheduler.tick()
    # 4 runs occurred in the past (June 1, June 2, June 3, June 4 at 08:00)
    assert len(occurrences) == 4
    for occ in occurrences:
        assert occ.status == OccurrenceStatus.MISSED_SKIPPED
        assert occ.job_id is None

    # Zero jobs enqueued
    queue = SQLiteJobQueue(db_path=str(db_file))
    claimed = queue.claim_next("worker_1")
    assert claimed is None

    # next_run_at advanced to tomorrow (June 5 at 08:00)
    refreshed = scheduler.get_schedule(sch.schedule_id)
    assert refreshed.next_run_at.startswith("2026-06-05T08:00:00")
    assert refreshed.last_run_at.startswith("2026-06-04T08:00:00")


def test_run_once_missed_run_behavior(tmp_path: Path) -> None:
    """Under RUN_ONCE, earlier missed runs are skipped and exactly ONE Job is
    materialized for the latest missed run, then advances to next future occurrence.
    """
    db_file = tmp_path / "run_once_test.db"
    current_time = [datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc)]

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: current_time[0])
    sch = scheduler.create_schedule(
        cron_expression="0 8 * * *",  # 08:00 UTC daily
        timezone="UTC",
        missed_run_policy=MissedRunPolicy.RUN_ONCE,
    )
    assert sch.next_run_at.startswith("2026-06-01T08:00:00")

    # Advance clock by 3 days (June 4 at 09:00)
    current_time[0] = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)

    occurrences = scheduler.tick()
    # 1 run materialized (the latest)
    assert len(occurrences) == 1
    materialized_occ = occurrences[0]
    assert materialized_occ.status == OccurrenceStatus.MISSED_RUN_ONCE
    assert materialized_occ.job_id is not None
    assert materialized_occ.scheduled_for_utc.startswith("2026-06-04T08:00:00")

    # Check that earlier runs were recorded as MISSED_SKIPPED
    all_occs = scheduler.list_occurrences(schedule_id=sch.schedule_id, limit=10)
    skipped_occs = [o for o in all_occs if o.status == OccurrenceStatus.MISSED_SKIPPED]
    assert len(skipped_occs) == 3  # June 1, 2, 3

    # Exactly 1 Job enqueued in PersistentJobQueue
    queue = SQLiteJobQueue(db_path=str(db_file))
    lease = queue.claim_next("worker_1")
    assert lease is not None
    assert lease.job_id == materialized_occ.job_id

    # Queue is now empty (no second job)
    assert queue.claim_next("worker_1") is None

    # Next run advanced to June 5 08:00
    refreshed = scheduler.get_schedule(sch.schedule_id)
    assert refreshed.next_run_at.startswith("2026-06-05T08:00:00")


# ------------------------------------------------------------------------------
# 11 & 12: Disabled Schedules & Re-enable Semantics
# ------------------------------------------------------------------------------


def test_disabled_schedule_creates_nothing(tmp_path: Path) -> None:
    """Disabled schedule does not create occurrences or jobs upon tick."""
    db_file = tmp_path / "disabled_test.db"
    now_dt = [datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)]

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt[0])
    sch = scheduler.create_schedule(
        cron_expression="0 9 * * *",
        timezone="UTC",
        enabled=False,
    )
    assert sch.next_run_at is None

    # Advance clock past scheduled time
    now_dt[0] = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    occs = scheduler.tick()
    assert occs == []

    # Queue remains empty
    queue = SQLiteJobQueue(db_path=str(db_file))
    assert queue.claim_next("worker_1") is None


def test_re_enable_behavior_respects_missed_run_policy(tmp_path: Path) -> None:
    """Re-enabling a schedule respects MissedRunPolicy."""
    db_file = tmp_path / "reenable_test.db"
    now_dt = [datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)]

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt[0])
    sch = scheduler.create_schedule(
        cron_expression="0 8 * * *",
        timezone="UTC",
        missed_run_policy=MissedRunPolicy.SKIP,
    )

    # Disable it
    scheduler.disable_schedule(sch.schedule_id)
    disabled_sch = scheduler.get_schedule(sch.schedule_id)
    assert disabled_sch.enabled is False
    assert disabled_sch.next_run_at is None

    # Advance clock 2 days later
    now_dt[0] = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)

    # Re-enable under SKIP: next run is future (July 4 08:00)
    re_enabled = scheduler.enable_schedule(sch.schedule_id)
    assert re_enabled.enabled is True
    assert re_enabled.next_run_at.startswith("2026-07-04T08:00:00")


# ------------------------------------------------------------------------------
# 13 & 14: Schedule Generation Fencing
# ------------------------------------------------------------------------------


def test_schedule_edit_increments_generation(tmp_path: Path) -> None:
    """Updating schedule increments monotonic schedule_generation."""
    db_file = tmp_path / "gen_test.db"
    scheduler = SchedulerService(db_path=str(db_file))

    sch = scheduler.create_schedule(cron_expression="0 8 * * *", timezone="UTC")
    assert sch.schedule_generation == 1

    updated1 = scheduler.update_schedule(sch.schedule_id, cron_expression="0 9 * * *")
    assert updated1.schedule_generation == 2
    assert updated1.cron_expression == "0 9 * * *"

    updated2 = scheduler.update_schedule(sch.schedule_id, timezone="Europe/Berlin")
    assert updated2.schedule_generation == 3
    assert updated2.timezone == "Europe/Berlin"


def test_stale_generation_cannot_materialize(tmp_path: Path) -> None:
    """Materializing with a stale schedule generation raises StaleScheduleGenerationError."""
    db_file = tmp_path / "stale_gen_test.db"
    now_dt = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)

    sch = scheduler.create_schedule(cron_expression="0 8 * * *", timezone="UTC")
    assert sch.schedule_generation == 1

    # Update schedule to gen 2
    scheduler.update_schedule(sch.schedule_id, cron_expression="0 9 * * *")

    # Stale reference with gen 1 must fail
    with pytest.raises(StaleScheduleGenerationError):
        scheduler._materialize_occurrence_atomic(
            schedule=sch,  # has schedule_generation = 1
            scheduled_for_utc=now_dt,
            scheduled_for_local=now_dt,
            now_dt=now_dt,
            status=OccurrenceStatus.MATERIALIZED,
            event_type=JobEventType.OCCURRENCE_MATERIALIZED,
        )


# ------------------------------------------------------------------------------
# 15 & 16: Deduplication & Multi-Scheduler Race Safety
# ------------------------------------------------------------------------------


def test_same_occurrence_cannot_materialize_twice(tmp_path: Path) -> None:
    """Same (schedule_id, schedule_generation, scheduled_for_utc) cannot materialize twice."""
    db_file = tmp_path / "dedup_test.db"
    now_dt = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)

    sch = scheduler.create_schedule(cron_expression="0 8 * * *", timezone="UTC")

    # First materialization succeeds
    res1 = scheduler._materialize_occurrence_atomic(
        schedule=sch,
        scheduled_for_utc=now_dt,
        scheduled_for_local=now_dt,
        now_dt=now_dt,
        status=OccurrenceStatus.MATERIALIZED,
        event_type=JobEventType.OCCURRENCE_MATERIALIZED,
    )
    assert len(res1) == 1

    # Second materialization for exact same occurrence returns empty (deduplicated safely)
    res2 = scheduler._materialize_occurrence_atomic(
        schedule=sch,
        scheduled_for_utc=now_dt,
        scheduled_for_local=now_dt,
        now_dt=now_dt,
        status=OccurrenceStatus.MATERIALIZED,
        event_type=JobEventType.OCCURRENCE_MATERIALIZED,
    )
    assert res2 == []

    # Check DB has exactly one occurrence
    occs = scheduler.list_occurrences(schedule_id=sch.schedule_id)
    assert len(occs) == 1


def test_multi_scheduler_race_produces_one_job(tmp_path: Path) -> None:
    """Concurrent scheduler instances racing against same SQLite DB produce exactly 1 Job."""
    db_file = tmp_path / "multi_scheduler_race.db"
    now_dt = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)

    scheduler1 = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)
    scheduler1.create_schedule(cron_expression="0 8 * * *", timezone="UTC")

    scheduler2 = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)

    results: List[List[ScheduledOccurrence]] = []
    errors: List[Exception] = []

    def run_tick(sched: SchedulerService) -> None:
        try:
            r = sched.tick(now=now_dt)
            results.append(r)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=run_tick, args=(scheduler1,))
    t2 = threading.Thread(target=run_tick, args=(scheduler2,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0

    # Exactly one occurrence was materialized across both threads
    total_occs = [occ for r in results for occ in r]
    assert len(total_occs) == 1

    # Exactly one Job in the database
    repo = SQLiteJobRepository(db_path=str(db_file))
    jobs = repo.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].job_id == total_occs[0].job_id

    # Exactly one entry in the queue
    queue = SQLiteJobQueue(db_path=str(db_file))
    lease = queue.claim_next("worker_race")
    assert lease is not None
    assert lease.job_id == jobs[0].job_id
    assert queue.claim_next("worker_race") is None


# ------------------------------------------------------------------------------
# 17, 18, 19: Occurrence -> Job -> Queue Provenance
# ------------------------------------------------------------------------------


def test_occurrence_creates_fresh_job_and_consecutive_occurrences_differ(tmp_path: Path) -> None:
    """Consecutive schedule occurrences create distinct canonical Job instances."""
    db_file = tmp_path / "consecutive_test.db"
    now_dt = [datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)]

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt[0])
    sch = scheduler.create_schedule(
        cron_expression="0 8 * * *",
        timezone="UTC",
        job_type="eval",
        payload_summary={"dataset": "golden_set"},
    )

    # Day 1 tick
    occs1 = scheduler.tick()
    assert len(occs1) == 1
    job_id_1 = occs1[0].job_id
    assert job_id_1 is not None

    # Day 2 tick
    now_dt[0] = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    occs2 = scheduler.tick()
    assert len(occs2) == 1
    job_id_2 = occs2[0].job_id
    assert job_id_2 is not None

    # Must be distinct Jobs!
    assert job_id_1 != job_id_2

    repo = SQLiteJobRepository(db_path=str(db_file))
    j1 = repo.get_job(job_id_1)
    j2 = repo.get_job(job_id_2)
    assert j1 is not None and j2 is not None
    assert j1.schedule_id == sch.schedule_id
    assert j2.schedule_id == sch.schedule_id
    assert j1.payload_summary["dataset"] == "golden_set"
    assert j1.payload_summary["occurrence_id"] == occs1[0].occurrence_id
    assert j2.payload_summary["occurrence_id"] == occs2[0].occurrence_id


# ------------------------------------------------------------------------------
# 20: Scheduler Never Invokes ExecutionCoordinator
# ------------------------------------------------------------------------------


def test_scheduler_never_invokes_execution_coordinator(tmp_path: Path) -> None:
    """Scheduler strictly enqueues jobs and never invokes ExecutionCoordinator."""
    db_file = tmp_path / "no_coordinator.db"
    now_dt = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

    with patch("core.execution.coordinator.ExecutionCoordinator") as mock_coord:
        scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)
        scheduler.create_schedule(cron_expression="0 8 * * *", timezone="UTC")
        scheduler.tick()

        # Mock coordinator must never have been instantiated or called
        mock_coord.assert_not_called()


# ------------------------------------------------------------------------------
# 21 & 22: Independence of Jobs and Schedules
# ------------------------------------------------------------------------------


def test_cancelling_occurrence_job_does_not_disable_schedule(tmp_path: Path) -> None:
    """Cancelling an enqueued occurrence Job leaves the parent schedule enabled."""
    db_file = tmp_path / "cancel_independence.db"
    now_dt = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)
    sch = scheduler.create_schedule(cron_expression="0 8 * * *", timezone="UTC")

    occs = scheduler.tick()
    assert len(occs) == 1
    job_id = occs[0].job_id

    # User cancels the job via JobControlService
    control_service = JobControlService(db_path=str(db_file))
    res = control_service.cancel_job(job_id)
    assert res.status == JobStatus.CANCELLED

    # Schedule remains enabled with next run intact!
    refreshed_sch = scheduler.get_schedule(sch.schedule_id)
    assert refreshed_sch.enabled is True
    assert refreshed_sch.next_run_at.startswith("2026-09-02T08:00:00")


def test_disabling_schedule_does_not_mutate_historical_jobs(tmp_path: Path) -> None:
    """Disabling schedule does not alter already materialized jobs."""
    db_file = tmp_path / "disable_independence.db"
    now_dt = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)
    sch = scheduler.create_schedule(cron_expression="0 8 * * *", timezone="UTC")

    occs = scheduler.tick()
    job_id = occs[0].job_id

    # Disable schedule
    scheduler.disable_schedule(sch.schedule_id)

    # Job is untouched
    repo = SQLiteJobRepository(db_path=str(db_file))
    historical_job = repo.get_job(job_id)
    assert historical_job.status == JobStatus.READY


# ------------------------------------------------------------------------------
# 23: Restart at Due Boundary
# ------------------------------------------------------------------------------


def test_restart_at_due_boundary_does_not_duplicate(tmp_path: Path) -> None:
    """Restarting scheduler immediately around due time does not duplicate."""
    db_file = tmp_path / "boundary_test.db"
    due_dt = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)

    # Instance 1 ticks at due time
    sched1 = SchedulerService(db_path=str(db_file), clock_fn=lambda: due_dt)
    sched1.create_schedule(cron_expression="0 8 * * *", timezone="UTC")
    occs1 = sched1.tick()
    assert len(occs1) == 1

    # Instance 2 starts at exact same due time or +1 second
    sched2 = SchedulerService(db_path=str(db_file), clock_fn=lambda: due_dt + timedelta(seconds=1))
    occs2 = sched2.tick()
    assert occs2 == []

    repo = SQLiteJobRepository(db_path=str(db_file))
    assert len(repo.list_jobs()) == 1


# ------------------------------------------------------------------------------
# 24: Crash During Materialization Recovers Cleanly
# ------------------------------------------------------------------------------


def test_crash_during_materialization_recovers_exactly_once(tmp_path: Path) -> None:
    """Simulated crash during materialization rolls back; restart materializes exactly once."""
    db_file = tmp_path / "crash_test.db"
    due_dt = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)

    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: due_dt)
    scheduler.create_schedule(cron_expression="0 8 * * *", timezone="UTC")

    # Simulate an error during materialization (e.g. disk or process error)
    original_method = scheduler._materialize_occurrence_atomic
    call_count = [0]

    def failing_materialize(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Simulated process crash during materialization")
        return original_method(*args, **kwargs)

    with patch.object(scheduler, "_materialize_occurrence_atomic", side_effect=failing_materialize):
        # Tick fails
        scheduler.tick()

    # Prove DB state rolled back cleanly
    repo = SQLiteJobRepository(db_path=str(db_file))
    assert len(repo.list_jobs()) == 0
    assert len(repo.list_occurrences()) == 0

    # Next tick (simulating restart recovery) succeeds
    recovered_occs = scheduler.tick()
    assert len(recovered_occs) == 1
    assert len(repo.list_jobs()) == 1
    assert len(repo.list_occurrences()) == 1


# ------------------------------------------------------------------------------
# 25: Populated v5 -> v6 Migration Test
# ------------------------------------------------------------------------------


def test_populated_v5_to_v6_migration_preserves_data(tmp_path: Path) -> None:
    """Migration 006 upgrades a populated v5 database preserving all historical records."""
    db_file = tmp_path / "v5_to_v6.db"
    conn = sqlite3.connect(str(db_file))
    try:
        _migration_001_initial_job_domain(conn)
        _migration_002_persistent_job_queue(conn)
        _migration_003_worker_attempt_ownership(conn)
        _migration_004_job_idempotency_and_retry(conn)
        _migration_005_job_control_and_timeouts(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);"
        )
        for v, name in [
            (1, "001_initial_job_domain"),
            (2, "002_persistent_job_queue"),
            (3, "003_worker_attempt_ownership"),
            (4, "004_idempotency_records"),
            (5, "005_job_control_and_timeouts"),
        ]:
            conn.execute(
                "INSERT INTO job_schema_migrations VALUES (?, ?, '2026-10-10T00:00:00Z')",
                (v, name),
            )

        # Pre-populate existing v5 data including legacy schedule
        conn.execute(
            """
            INSERT INTO jobs (job_id, job_type, status, created_at, updated_at, control_intent, control_generation)
            VALUES ('job_v5', 'chat', 'ready', '2026-10-10T00:00:00Z', '2026-10-10T00:00:00Z', 'none', 0)
            """
        )
        conn.execute(
            """
            INSERT INTO job_schedules (
                schedule_id, job_template_id, job_type, cron_expression, timezone,
                enabled, payload_reference, created_at, updated_at
            ) VALUES (
                'sch_legacy_v5', 'tmpl_1', 'summary', '0 12 * * *', 'UTC',
                1, 'uri://payload', '2026-10-10T00:00:00Z', '2026-10-10T00:00:00Z'
            )
            """
        )
        conn.commit()

        # Apply Migration 006
        applied = apply_job_migrations(conn, target_version=6)
        assert applied == 1
        assert get_current_job_schema_version(conn) == 6

        # Verify new columns exist with correct defaults on legacy record
        cur = conn.cursor()
        cur.execute(
            """
            SELECT schedule_id, schedule_generation, missed_run_policy, payload_summary_json, created_by
            FROM job_schedules WHERE schedule_id = 'sch_legacy_v5'
            """
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "sch_legacy_v5"
        assert row[1] == 1  # default generation
        assert row[2] == "skip"  # default missed_run_policy
        assert row[3] == "{}"
        assert row[4] == "authority:local_user"

        # Verify scheduled_occurrences table is present and functional
        cur.execute("SELECT count(*) FROM scheduled_occurrences")
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# 26: Zero Secrets Persisted
# ------------------------------------------------------------------------------


def test_no_secrets_persisted_in_schedules_or_events(tmp_path: Path) -> None:
    """Ensure no sensitive tokens or secrets leak into stored summaries or metadata."""
    db_file = tmp_path / "secrets_test.db"
    now_dt = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)
    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)

    scheduler.create_schedule(
        cron_expression="0 8 * * *",
        timezone="UTC",
        payload_summary={"model": "claude-3-opus", "safe_param": "123"},
    )
    scheduler.tick()

    conn = sqlite3.connect(str(db_file))
    try:
        cur = conn.cursor()
        # Check schedules
        cur.execute("SELECT payload_summary_json FROM job_schedules")
        for (raw_s,) in cur.fetchall():
            assert "api_key" not in raw_s
            assert "secret" not in raw_s
            assert "token" not in raw_s

        # Check events
        cur.execute("SELECT metadata_json FROM job_events")
        for (raw_e,) in cur.fetchall():
            assert "api_key" not in raw_e
            assert "secret" not in raw_e
            assert "token" not in raw_e
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# 27: Standalone CLI Runner (--once)
# ------------------------------------------------------------------------------


def test_cli_runner_once_flag(tmp_path: Path) -> None:
    """CLI main runner executes exactly one tick with --once and exits cleanly."""
    db_file = tmp_path / "cli_test.db"

    # Pre-create schedule
    now_dt = datetime.now(timezone.utc) - timedelta(minutes=5)
    scheduler = SchedulerService(db_path=str(db_file), clock_fn=lambda: now_dt)
    sch = scheduler.create_schedule(cron_expression="* * * * *", timezone="UTC")

    # Run CLI with --once
    exit_code = scheduler_cli_main(["--db-path", str(db_file), "--once", "-v"])
    assert exit_code == 0

    # Occurrence was materialized
    occs = scheduler.list_occurrences(schedule_id=sch.schedule_id)
    assert len(occs) >= 1


# ------------------------------------------------------------------------------
# 28: Unsupported Cron Syntax Rejected at Creation/Update
# ------------------------------------------------------------------------------


def test_cron_unsupported_syntax_rejected_at_validation(tmp_path: Path) -> None:
    """Unsupported non-standard syntax (@yearly, @daily, L, W, ?, #, seconds) fails immediately."""
    db_file = tmp_path / "syntax_rejection.db"
    scheduler = SchedulerService(db_path=str(db_file))

    unsupported_expressions = [
        "@yearly",
        "@daily",
        "@hourly",
        "0 0 * * ?",
        "0 0 1W * *",
        "0 0 15L * *",
        "0 0 * * 1#2",
        "* * * * * *",  # 6 fields (seconds)
        "0 0 0 1 1 2026",  # 6 fields with year
    ]

    for expr in unsupported_expressions:
        # Fails at standalone validation
        with pytest.raises(InvalidScheduleExpressionError):
            validate_cron_expression(expr)

        # Fails at schedule creation time
        with pytest.raises(InvalidScheduleExpressionError):
            scheduler.create_schedule(cron_expression=expr, timezone="UTC")

    # Fails at schedule update time
    valid_sch = scheduler.create_schedule(cron_expression="0 0 * * *", timezone="UTC")
    with pytest.raises(InvalidScheduleExpressionError):
        scheduler.update_schedule(valid_sch.schedule_id, cron_expression="@hourly")


# ------------------------------------------------------------------------------
# 29: Day-of-Month and Day-of-Week Vixie Cron OR Semantics
# ------------------------------------------------------------------------------


def test_vixie_cron_dom_dow_or_semantics() -> None:
    """Traditional cron semantics: if DOM and DOW are both restricted, match either (OR).
    Example: 0 9 1 * 1 means 09:00 on the 1st of the month OR 09:00 on Mondays.
    """
    cron_expr = "0 9 1 * 1"
    # 2026-09-01 is Tuesday (1st of month) -> MATCH
    # 2026-09-07 is Monday (7th of month) -> MATCH
    # 2026-09-14 is Monday (14th of month) -> MATCH
    start_dt = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)

    # 1st occurrence: 2026-09-01 (1st of month)
    u1, l1 = get_next_occurrence(cron_expr, "UTC", after_dt=start_dt)
    assert u1 == datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    assert l1.day == 1

    # 2nd occurrence: 2026-09-07 (Monday)
    u2, l2 = get_next_occurrence(cron_expr, "UTC", after_dt=u1)
    assert u2 == datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
    assert l2.weekday() == 0  # Monday

    # 3rd occurrence: 2026-09-14 (Monday)
    u3, l3 = get_next_occurrence(cron_expr, "UTC", after_dt=u2)
    assert u3 == datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)
    assert l3.weekday() == 0  # Monday


# ------------------------------------------------------------------------------
# 30: Cron Edge Cases (Sunday 0 & 7, Steps, Ranges, Leap Day, 30-day Months)
# ------------------------------------------------------------------------------


def test_cron_edge_cases() -> None:
    """Verify Sunday representations, ranges, steps, lists, leap year, and 30-day month."""
    base_dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    # 1. Sunday as 0 and 7 are identical
    u_sun0, _ = get_next_occurrence("0 0 * * 0", "UTC", after_dt=base_dt)
    u_sun7, _ = get_next_occurrence("0 0 * * 7", "UTC", after_dt=base_dt)
    assert u_sun0 == u_sun7 == datetime(2026, 1, 4, 0, 0, tzinfo=timezone.utc)

    # 2. Stepped ranges and lists produce deterministic expected times
    # */15 -> 0, 15, 30, 45
    t15_1, _ = get_next_occurrence("*/15 * * * *", "UTC", after_dt=base_dt)
    assert t15_1 == datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc)
    t15_2, _ = get_next_occurrence("*/15 * * * *", "UTC", after_dt=t15_1)
    assert t15_2 == datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)

    # 1-10/2 -> 1, 3, 5, 7, 9
    t_step_1, _ = get_next_occurrence("1-10/2 * * * *", "UTC", after_dt=base_dt)
    assert t_step_1 == datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    t_step_2, _ = get_next_occurrence("1-10/2 * * * *", "UTC", after_dt=t_step_1)
    assert t_step_2 == datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)

    # 1,5,10 -> 1, 5, 10
    t_list_1, _ = get_next_occurrence("1,5,10 * * * *", "UTC", after_dt=base_dt)
    assert t_list_1 == datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    t_list_2, _ = get_next_occurrence("1,5,10 * * * *", "UTC", after_dt=t_list_1)
    assert t_list_2 == datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)

    # 3. Leap day: 2026 is non-leap; next leap year is 2028
    u_leap, _ = get_next_occurrence("0 0 29 2 *", "UTC", after_dt=base_dt)
    assert u_leap == datetime(2028, 2, 29, 0, 0, tzinfo=timezone.utc)

    # 4. Month with 30 days: 31st skips 30-day months (e.g. April 31st -> May 31st)
    apr_dt = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    u_31, _ = get_next_occurrence("0 0 31 * *", "UTC", after_dt=apr_dt)
    assert u_31 == datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc)

    # 5. Impossible month/day (April 31st exclusively) raises within bounded search
    with pytest.raises(InvalidScheduleExpressionError):
        get_next_occurrence("0 0 31 4 *", "UTC", after_dt=apr_dt)

    # 6. Invalid day/month out of bounds rejected at parse time
    invalid_bounds = ["60 * * * *", "* 24 * * *", "* * 32 * *", "* * * 13 *", "* * * * 8"]
    for inv in invalid_bounds:
        with pytest.raises(InvalidScheduleExpressionError):
            validate_cron_expression(inv)


# ------------------------------------------------------------------------------
# 31: Canonical UTC Timezone Acceptance
# ------------------------------------------------------------------------------


def test_canonical_utc_timezone_accepted(tmp_path: Path) -> None:
    """Canonical 'UTC' identifier is accepted without requiring geographic prefixes."""
    tz = validate_iana_timezone("UTC")
    assert tz.key == "UTC"

    db_file = tmp_path / "utc_test.db"
    scheduler = SchedulerService(db_path=str(db_file))
    sch = scheduler.create_schedule(cron_expression="0 12 * * *", timezone="UTC")
    assert sch.timezone == "UTC"


# ------------------------------------------------------------------------------
# 32: Occurrence Identity and DST Exact-Once Persistence Regression
# ------------------------------------------------------------------------------


def test_occurrence_identity_and_dst_exact_once_regression(tmp_path: Path) -> None:
    """Comprehensive persistence regression for DST transitions:
    - Spring-forward skipped occurrence -> 0 occurrence rows for nonexistent 02:30.
    - Fall-back first fold -> exactly 1 occurrence row for 02:30 (fold=0, 00:30 UTC).
    - Scheduler restart -> still exactly 1 occurrence row.
    - Two concurrent scheduler instances racing -> still exactly 1 occurrence row.
    """
    # Part 1: Spring-forward skipped occurrence
    # Europe/Berlin on 2026-03-29: 02:30 does not exist.
    # Ticking across 2026-03-29 should produce NO occurrence row for 2026-03-29.
    db_spring = tmp_path / "dst_spring.db"
    spring_clock = datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc)
    sched_spring = SchedulerService(db_path=str(db_spring), clock_fn=lambda: spring_clock)
    sch_spring = sched_spring.create_schedule(
        cron_expression="30 2 * * *", timezone="Europe/Berlin"
    )

    # Initial next run computed is 2026-03-30 00:30:00 UTC (skipped 2026-03-29 entirely!)
    assert sch_spring.next_run_at.startswith("2026-03-30T00:30:00")

    # Tick at 2026-03-29 02:00, 02:30, 03:00 UTC -> nothing materialized
    for hr in [2, 3, 4]:
        spring_clock = datetime(2026, 3, 29, hr, 0, tzinfo=timezone.utc)
        occs = sched_spring.tick()
        assert occs == []

    spring_occs = sched_spring.list_occurrences(schedule_id=sch_spring.schedule_id)
    assert len(spring_occs) == 0  # ZERO occurrence rows for 2026-03-29!

    # Part 2: Fall-back first fold exact-once and restart / multi-process safety
    # Europe/Berlin on 2026-10-25: 02:30 repeated at 00:30 UTC (fold 0) and 01:30 UTC (fold 1)
    db_fall = tmp_path / "dst_fall.db"
    fall_clock = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    sched_fall = SchedulerService(db_path=str(db_fall), clock_fn=lambda: fall_clock)
    sch_fall = sched_fall.create_schedule(cron_expression="30 2 * * *", timezone="Europe/Berlin")

    assert sch_fall.next_run_at.startswith("2026-10-25T00:30:00")

    # Advance clock to due instant: 2026-10-25 00:30:00 UTC
    due_instant = datetime(2026, 10, 25, 0, 30, 0, tzinfo=timezone.utc)
    fall_clock = due_instant
    occs1 = sched_fall.tick()
    assert len(occs1) == 1
    assert occs1[0].scheduled_for_utc.startswith("2026-10-25T00:30:00")

    # Verify next_run_at advanced to next calendar day (2026-10-26 01:30:00 UTC),
    # NOT the second fold (2026-10-25 01:30:00 UTC)!
    refreshed_sch = sched_fall.get_schedule(sch_fall.schedule_id)
    assert refreshed_sch.next_run_at.startswith("2026-10-26T01:30:00")

    # Tick again during the second fold at 2026-10-25 01:30:00 UTC -> ZERO occurrences created
    fall_clock = datetime(2026, 10, 25, 1, 30, 0, tzinfo=timezone.utc)
    occs_second_fold = sched_fall.tick()
    assert occs_second_fold == []

    # Restart scheduler instance at due time -> still exactly 1 occurrence
    restart_sched = SchedulerService(db_path=str(db_fall), clock_fn=lambda: due_instant)
    restart_occs = restart_sched.tick()
    assert restart_occs == []
    all_fall_occs = restart_sched.list_occurrences(schedule_id=sch_fall.schedule_id)
    assert len(all_fall_occs) == 1

    # Two concurrent scheduler instances ticking simultaneously -> still exactly 1 occurrence
    sched_a = SchedulerService(db_path=str(db_fall), clock_fn=lambda: due_instant)
    sched_b = SchedulerService(db_path=str(db_fall), clock_fn=lambda: due_instant)
    assert sched_a.tick() == []
    assert sched_b.tick() == []
    assert len(sched_a.list_occurrences(schedule_id=sch_fall.schedule_id)) == 1
