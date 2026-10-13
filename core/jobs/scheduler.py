"""core/jobs/scheduler.py

Timezone-Aware Recurring Job Scheduler Service (Task R4.7).
Part of Milestone R4 (Task R4.7 - Timezone-Aware Scheduler).

Governing Principles:
- The scheduler NEVER executes jobs directly. Occurrence materialization strictly
  creates fresh canonical Job instances enqueued into PersistentJobQueue.
- Timezone evaluation uses standard-library IANA timezones (zoneinfo.ZoneInfo).
  Legacy 3-letter abbreviations (e.g. EST, CET) and fixed offsets (UTC+1) are strictly rejected.
- Monotonic schedule generation fencing protects against races between schedule edits
  and in-flight occurrence materializations.
- Explicit missed-run policies (SKIP, RUN_ONCE):
  * SKIP: all missed runs during downtime/pause are recorded as missed_skipped,
    advancing next_run_at to the next future run without enqueuing jobs.
  * RUN_ONCE: exactly one run is materialized for the missed window (MISSED_RUN_ONCE),
    earlier missed runs are recorded as missed_skipped, then advances to next future run.
- Atomic occurrence materialization: single SQLite transaction (BEGIN IMMEDIATE) performs
  occurrence reservation, job creation, queue insertion, audit event logging, and
  schedule metadata advancement, eliminating crash inconsistency.
- Deduplication: Unique constraint on (schedule_id, schedule_generation, scheduled_for_utc)
  ensures multi-scheduler processes never duplicate an occurrence.
- DST semantics:
  * Nonexistent local times during spring-forward are skipped to the next valid calendar occurrence.
  * Ambiguous local times during fall-back fold are materialized deterministically exactly once (fold=0).
- Injectable clock support for deterministic testing without sleeping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import sqlite3
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from core.jobs.cron import (
    get_missed_occurrences,
    get_next_occurrence,
    validate_cron_expression,
    validate_iana_timezone,
)
from core.jobs.exceptions import (
    ScheduleNotFoundError,
    SchedulerError,
    StaleScheduleGenerationError,
)
from core.jobs.migrations import apply_job_migrations
from core.jobs.models import (
    JobEventType,
    JobSchedule,
    MissedRunPolicy,
    OccurrenceStatus,
    ScheduledOccurrence,
    format_utc_iso,
    generate_event_id,
    generate_job_id,
    generate_occurrence_id,
    generate_queue_entry_id,
    generate_schedule_id,
    parse_utc_iso,
    sanitize_bounded_dict,
)
from core.jobs.queue import PersistentJobQueue, SQLiteJobQueue
from core.jobs.repository import JobRepository
from core.jobs.sqlite import DEFAULT_JOBS_DB_PATH, SQLiteJobRepository

logger = logging.getLogger("agent_engine.jobs.scheduler")


class SchedulerService:
    """Timezone-aware recurring job scheduler service managing schedule definitions and ticks."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        repository: Optional[JobRepository] = None,
        queue: Optional[PersistentJobQueue] = None,
        clock_fn: Optional[Callable[[], datetime]] = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.db_path = db_path or os.getenv("SQLITE_DB_PATH") or DEFAULT_JOBS_DB_PATH
        self._clock_fn = clock_fn or (lambda: datetime.now(timezone.utc))
        self._poll_interval = poll_interval_seconds

        self._repo = repository or SQLiteJobRepository(db_path=db_path)
        self._queue = queue or SQLiteJobQueue(db_path=db_path)

        self._is_memory = (
            db_path == ":memory:"
            or "mode=memory" in db_path
            or (isinstance(self._repo, SQLiteJobRepository) and self._repo._is_memory)
        )
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Ensure schema migrations are applied
        self._init_db()

    def _init_db(self) -> None:
        """Apply migrations if running with file-backed SQLite or shared connection."""
        conn = self._get_connection()
        try:
            apply_job_migrations(conn)
        finally:
            if not self._is_memory:
                conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Obtain a SQLite connection configured with proper timeouts and WAL mode."""
        if (
            isinstance(self._repo, SQLiteJobRepository)
            and self._is_memory
            and self._repo._memory_conn is not None
        ):
            return self._repo._memory_conn

        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,  # Explicit transaction control
        )
        conn.row_factory = sqlite3.Row
        if not self._is_memory:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
        return conn

    def _now_utc(self) -> datetime:
        """Resolve current time in UTC using injected clock."""
        dt = self._clock_fn()
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # --------------------------------------------------------------------------
    # Public Schedule Management CRUD
    # --------------------------------------------------------------------------

    def create_schedule(
        self,
        cron_expression: str,
        timezone: str = "UTC",
        job_type: str = "chat",
        job_template_id: Optional[str] = None,
        payload_reference: Optional[str] = None,
        payload_summary: Optional[Dict[str, Any]] = None,
        missed_run_policy: Union[MissedRunPolicy, str] = MissedRunPolicy.SKIP,
        timeout_seconds: Optional[int] = None,
        created_by: str = "authority:local_user",
        project_id: Optional[str] = None,
        enabled: bool = True,
    ) -> JobSchedule:
        """Validate, compute initial next_run_at, and persist a new recurring schedule."""
        validate_iana_timezone(timezone)
        validate_cron_expression(cron_expression)

        policy = (
            MissedRunPolicy(missed_run_policy)
            if isinstance(missed_run_policy, str)
            else missed_run_policy
        )
        cleaned_summary = sanitize_bounded_dict(payload_summary or {})

        now_utc = self._now_utc()
        next_run_iso: Optional[str] = None
        if enabled:
            next_utc, _ = get_next_occurrence(
                cron_expression, timezone, after_dt=now_utc, inclusive=True
            )
            next_run_iso = format_utc_iso(next_utc)

        schedule = JobSchedule(
            schedule_id=generate_schedule_id(),
            job_template_id=job_template_id,
            job_type=job_type,
            cron_expression=cron_expression,
            timezone=timezone,
            enabled=enabled,
            schedule_generation=1,
            missed_run_policy=policy,
            payload_reference=payload_reference,
            payload_summary=cleaned_summary,
            created_by=created_by,
            project_id=project_id,
            timeout_seconds=timeout_seconds,
            next_run_at=next_run_iso,
            last_run_at=None,
            created_at=format_utc_iso(now_utc),
            updated_at=format_utc_iso(now_utc),
        )

        persisted = self._repo.create_schedule(schedule)
        logger.info(
            "Created schedule %s (cron='%s', tz='%s', next_run=%s)",
            persisted.schedule_id,
            persisted.cron_expression,
            persisted.timezone,
            persisted.next_run_at,
        )
        return persisted

    def get_schedule(self, schedule_id: str) -> Optional[JobSchedule]:
        """Retrieve schedule definition by identifier."""
        return self._repo.get_schedule(schedule_id)

    def list_schedules(self, enabled_only: bool = False) -> List[JobSchedule]:
        """List schedule definitions."""
        return self._repo.list_schedules(enabled_only=enabled_only)

    def update_schedule(
        self,
        schedule_id: str,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
        job_type: Optional[str] = None,
        job_template_id: Optional[str] = None,
        payload_reference: Optional[str] = None,
        payload_summary: Optional[Dict[str, Any]] = None,
        missed_run_policy: Optional[Union[MissedRunPolicy, str]] = None,
        timeout_seconds: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> JobSchedule:
        """Update schedule configuration and increment monotonic schedule_generation."""
        current = self._repo.get_schedule(schedule_id)
        if not current:
            raise ScheduleNotFoundError(f"Schedule {schedule_id} does not exist.")

        new_cron = cron_expression if cron_expression is not None else current.cron_expression
        new_tz = timezone if timezone is not None else current.timezone
        new_job_type = job_type if job_type is not None else current.job_type
        new_template_id = (
            job_template_id if job_template_id is not None else current.job_template_id
        )
        new_payload_ref = (
            payload_reference if payload_reference is not None else current.payload_reference
        )
        new_summary = (
            sanitize_bounded_dict(payload_summary)
            if payload_summary is not None
            else current.payload_summary
        )
        new_policy = (
            (
                MissedRunPolicy(missed_run_policy)
                if isinstance(missed_run_policy, str)
                else missed_run_policy
            )
            if missed_run_policy is not None
            else current.missed_run_policy
        )
        new_timeout = timeout_seconds if timeout_seconds is not None else current.timeout_seconds
        new_project = project_id if project_id is not None else current.project_id

        validate_iana_timezone(new_tz)
        validate_cron_expression(new_cron)

        now_utc = self._now_utc()
        new_generation = current.schedule_generation + 1

        new_next_run: Optional[str] = None
        if current.enabled:
            next_utc, _ = get_next_occurrence(new_cron, new_tz, after_dt=now_utc, inclusive=True)
            new_next_run = format_utc_iso(next_utc)

        updated_schedule = JobSchedule(
            schedule_id=current.schedule_id,
            job_template_id=new_template_id,
            job_type=new_job_type,
            cron_expression=new_cron,
            timezone=new_tz,
            enabled=current.enabled,
            schedule_generation=new_generation,
            missed_run_policy=new_policy,
            payload_reference=new_payload_ref,
            payload_summary=new_summary,
            created_by=current.created_by,
            project_id=new_project,
            timeout_seconds=new_timeout,
            next_run_at=new_next_run,
            last_run_at=current.last_run_at,
            created_at=current.created_at,
            updated_at=format_utc_iso(now_utc),
        )

        persisted = self._repo.update_schedule(updated_schedule)
        logger.info(
            "Updated schedule %s to generation %d (next_run=%s)",
            schedule_id,
            new_generation,
            persisted.next_run_at,
        )
        return persisted

    def enable_schedule(self, schedule_id: str) -> JobSchedule:
        """Enable a disabled schedule and re-evaluate next_run_at."""
        current = self._repo.get_schedule(schedule_id)
        if not current:
            raise ScheduleNotFoundError(f"Schedule {schedule_id} does not exist.")

        if current.enabled:
            return current

        now_utc = self._now_utc()
        now_iso = format_utc_iso(now_utc)

        next_utc, _ = get_next_occurrence(
            current.cron_expression, current.timezone, after_dt=now_utc, inclusive=True
        )
        next_run_iso = format_utc_iso(next_utc)

        # If RUN_ONCE policy and historical runs were missed while disabled,
        # set next_run_at to now_iso so the next tick immediately catches up.
        if current.missed_run_policy == MissedRunPolicy.RUN_ONCE and current.last_run_at:
            last_dt = parse_utc_iso(current.last_run_at)
            missed = get_missed_occurrences(
                current.cron_expression, current.timezone, since_dt=last_dt, up_to_dt=now_utc
            )
            if missed:
                next_run_iso = now_iso

        updated = JobSchedule(
            schedule_id=current.schedule_id,
            job_template_id=current.job_template_id,
            job_type=current.job_type,
            cron_expression=current.cron_expression,
            timezone=current.timezone,
            enabled=True,
            schedule_generation=current.schedule_generation,
            missed_run_policy=current.missed_run_policy,
            payload_reference=current.payload_reference,
            payload_summary=current.payload_summary,
            created_by=current.created_by,
            project_id=current.project_id,
            timeout_seconds=current.timeout_seconds,
            next_run_at=next_run_iso,
            last_run_at=current.last_run_at,
            created_at=current.created_at,
            updated_at=now_iso,
        )
        return self._repo.update_schedule(updated)

    def disable_schedule(self, schedule_id: str) -> JobSchedule:
        """Disable an active schedule and clear next_run_at."""
        current = self._repo.get_schedule(schedule_id)
        if not current:
            raise ScheduleNotFoundError(f"Schedule {schedule_id} does not exist.")

        if not current.enabled:
            return current

        now_utc = self._now_utc()
        updated = JobSchedule(
            schedule_id=current.schedule_id,
            job_template_id=current.job_template_id,
            job_type=current.job_type,
            cron_expression=current.cron_expression,
            timezone=current.timezone,
            enabled=False,
            schedule_generation=current.schedule_generation,
            missed_run_policy=current.missed_run_policy,
            payload_reference=current.payload_reference,
            payload_summary=current.payload_summary,
            created_by=current.created_by,
            project_id=current.project_id,
            timeout_seconds=current.timeout_seconds,
            next_run_at=None,
            last_run_at=current.last_run_at,
            created_at=current.created_at,
            updated_at=format_utc_iso(now_utc),
        )
        return self._repo.update_schedule(updated)

    def delete_schedule(self, schedule_id: str, force: bool = False) -> bool:
        """Delete schedule if permitted (no historical occurrences or explicit force)."""
        current = self._repo.get_schedule(schedule_id)
        if not current:
            raise ScheduleNotFoundError(f"Schedule {schedule_id} does not exist.")

        occurrences = self._repo.list_occurrences(schedule_id=schedule_id, limit=1)
        if occurrences and not force:
            raise SchedulerError(
                f"Cannot delete schedule {schedule_id} with historical occurrences; disable it instead."
            )

        return self._repo.delete_schedule(schedule_id)

    def list_occurrences(
        self, schedule_id: Optional[str] = None, limit: int = 100
    ) -> List[ScheduledOccurrence]:
        """List scheduled occurrences."""
        return self._repo.list_occurrences(schedule_id=schedule_id, limit=limit)

    # --------------------------------------------------------------------------
    # Tick Execution & Atomic Occurrence Materialization
    # --------------------------------------------------------------------------

    def tick(
        self,
        now: Optional[Union[datetime, str]] = None,
    ) -> List[ScheduledOccurrence]:
        """Evaluate all due schedules at "now" and atomically materialize occurrences.

        Returns:
            List of ScheduledOccurrence instances processed during this tick.
        """
        now_dt = self._resolve_dt(now)
        now_iso = format_utc_iso(now_dt)

        # Query enabled schedules with next_run_at <= now
        schedules = self._repo.list_schedules(enabled_only=True)
        due_schedules = [s for s in schedules if s.next_run_at and s.next_run_at <= now_iso]

        processed_occurrences: List[ScheduledOccurrence] = []

        for schedule in due_schedules:
            try:
                occurrences = self._process_due_schedule(schedule, now_dt)
                processed_occurrences.extend(occurrences)
            except Exception as e:
                logger.error(
                    "Error processing schedule %s at tick %s: %s",
                    schedule.schedule_id,
                    now_iso,
                    e,
                    exc_info=True,
                )

        return processed_occurrences

    def _resolve_dt(self, dt_val: Optional[Union[datetime, str]]) -> datetime:
        """Convert dt_val to aware UTC datetime."""
        if dt_val is None:
            return self._now_utc()
        if isinstance(dt_val, str):
            parsed = parse_utc_iso(dt_val)
            return parsed
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)

    def _process_due_schedule(
        self,
        schedule: JobSchedule,
        now_dt: datetime,
    ) -> List[ScheduledOccurrence]:
        """Calculate due/missed occurrences for a schedule and atomically materialize them."""
        # 1. Determine the search window
        if schedule.last_run_at:
            since_dt = parse_utc_iso(schedule.last_run_at)
        elif schedule.next_run_at:
            next_dt = parse_utc_iso(schedule.next_run_at)
            since_dt = next_dt - timedelta(seconds=1)
        else:
            since_dt = now_dt - timedelta(seconds=1)

        # 2. Get all occurrences due up to now_dt
        due_tuples = get_missed_occurrences(
            schedule.cron_expression,
            schedule.timezone,
            since_dt=since_dt,
            up_to_dt=now_dt,
        )

        if not due_tuples:
            # Nothing strictly due or clock skew; advance next_run_at to next occurrence
            next_utc, _ = get_next_occurrence(
                schedule.cron_expression, schedule.timezone, after_dt=now_dt
            )
            schedule.next_run_at = format_utc_iso(next_utc)
            schedule.updated_at = format_utc_iso(now_dt)
            self._repo.update_schedule(schedule)
            return []

        # 3. Apply MissedRunPolicy
        is_backlog = len(due_tuples) > 1

        if is_backlog and schedule.missed_run_policy == MissedRunPolicy.SKIP:
            # Under SKIP: mark all missed runs as MISSED_SKIPPED, no Job enqueued
            return self._apply_missed_skip_policy_atomic(schedule, due_tuples, now_dt)
        elif is_backlog and schedule.missed_run_policy == MissedRunPolicy.RUN_ONCE:
            # Under RUN_ONCE: skip earlier runs, materialize exactly the latest one
            return self._apply_missed_run_once_policy_atomic(schedule, due_tuples, now_dt)
        else:
            # Single occurrence (normal on-time execution)
            occ_utc, occ_local = due_tuples[-1]
            return self._materialize_occurrence_atomic(
                schedule=schedule,
                scheduled_for_utc=occ_utc,
                scheduled_for_local=occ_local,
                now_dt=now_dt,
                status=OccurrenceStatus.MATERIALIZED,
                event_type=JobEventType.OCCURRENCE_MATERIALIZED,
            )

    def _apply_missed_skip_policy_atomic(
        self,
        schedule: JobSchedule,
        due_tuples: List[Tuple[datetime, datetime]],
        now_dt: datetime,
    ) -> List[ScheduledOccurrence]:
        """Atomically record all missed occurrences as skipped and advance next_run_at."""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT enabled, schedule_generation FROM job_schedules WHERE schedule_id = ?",
                    (schedule.schedule_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return []
                if not bool(row["enabled"]):
                    return []
                current_gen = row["schedule_generation"]
                if current_gen != schedule.schedule_generation:
                    raise StaleScheduleGenerationError(
                        f"Schedule {schedule.schedule_id} generation changed ({current_gen} != {schedule.schedule_generation})."
                    )

                occurrences: List[ScheduledOccurrence] = []
                now_iso = format_utc_iso(now_dt)

                for occ_utc, occ_local in due_tuples:
                    utc_iso = format_utc_iso(occ_utc)
                    loc_iso = occ_local.isoformat()
                    occ_id = generate_occurrence_id()
                    try:
                        cursor.execute(
                            """
                            INSERT INTO scheduled_occurrences (
                                occurrence_id, schedule_id, scheduled_for_utc,
                                scheduled_for_local, schedule_generation, job_id,
                                materialized_at, status
                            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                            """,
                            (
                                occ_id,
                                schedule.schedule_id,
                                utc_iso,
                                loc_iso,
                                current_gen,
                                now_iso,
                                OccurrenceStatus.MISSED_SKIPPED.value,
                            ),
                        )
                    except sqlite3.IntegrityError:
                        # Already recorded
                        continue

                    occurrences.append(
                        ScheduledOccurrence(
                            occurrence_id=occ_id,
                            schedule_id=schedule.schedule_id,
                            scheduled_for_utc=utc_iso,
                            scheduled_for_local=loc_iso,
                            schedule_generation=current_gen,
                            job_id=None,
                            materialized_at=now_iso,
                            status=OccurrenceStatus.MISSED_SKIPPED,
                        )
                    )

                # Next future run after now
                next_utc, _ = get_next_occurrence(
                    schedule.cron_expression, schedule.timezone, after_dt=now_dt
                )
                latest_missed_iso = format_utc_iso(due_tuples[-1][0])
                next_run_iso = format_utc_iso(next_utc)

                cursor.execute(
                    """
                    UPDATE job_schedules
                    SET last_run_at = ?, next_run_at = ?, updated_at = ?
                    WHERE schedule_id = ? AND schedule_generation = ?
                    """,
                    (latest_missed_iso, next_run_iso, now_iso, schedule.schedule_id, current_gen),
                )

                logger.info(
                    "Schedule %s: skipped %d missed runs, advanced to %s",
                    schedule.schedule_id,
                    len(due_tuples),
                    next_run_iso,
                )
                return occurrences
        finally:
            if not self._is_memory:
                conn.close()

    def _apply_missed_run_once_policy_atomic(
        self,
        schedule: JobSchedule,
        due_tuples: List[Tuple[datetime, datetime]],
        now_dt: datetime,
    ) -> List[ScheduledOccurrence]:
        """Atomically skip earlier missed runs, materialize the latest missed run, and advance next_run_at."""
        earlier_tuples = due_tuples[:-1]
        latest_utc, latest_local = due_tuples[-1]

        # 1. Record earlier runs as skipped
        if earlier_tuples:
            self._apply_missed_skip_policy_atomic(schedule, earlier_tuples, now_dt)

        # 2. Materialize the latest run with MISSED_RUN_ONCE
        return self._materialize_occurrence_atomic(
            schedule=schedule,
            scheduled_for_utc=latest_utc,
            scheduled_for_local=latest_local,
            now_dt=now_dt,
            status=OccurrenceStatus.MISSED_RUN_ONCE,
            event_type=JobEventType.MISSED_RUN_MATERIALIZED,
        )

    def _materialize_occurrence_atomic(
        self,
        schedule: JobSchedule,
        scheduled_for_utc: datetime,
        scheduled_for_local: datetime,
        now_dt: datetime,
        status: OccurrenceStatus,
        event_type: JobEventType,
    ) -> List[ScheduledOccurrence]:
        """Single SQLite transaction performing occurrence reservation, Job creation,
        queue insertion, event recording, and schedule advancement.
        """
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()

                # 1. Verify schedule status and generation fencing
                cursor.execute(
                    """
                    SELECT schedule_id, enabled, schedule_generation, job_type, payload_reference,
                           payload_summary_json, created_by, project_id, timeout_seconds, cron_expression, timezone
                    FROM job_schedules WHERE schedule_id = ?
                    """,
                    (schedule.schedule_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return []
                if not bool(row["enabled"]):
                    return []
                current_gen = row["schedule_generation"]
                if current_gen != schedule.schedule_generation:
                    raise StaleScheduleGenerationError(
                        f"Schedule {schedule.schedule_id} generation changed ({current_gen} != {schedule.schedule_generation})."
                    )

                occ_id = generate_occurrence_id()
                job_id = generate_job_id()
                queue_entry_id = generate_queue_entry_id()
                now_iso = format_utc_iso(now_dt)
                utc_iso = format_utc_iso(scheduled_for_utc)
                loc_iso = scheduled_for_local.isoformat()

                # 2. Reserve occurrence in scheduled_occurrences
                try:
                    cursor.execute(
                        """
                        INSERT INTO scheduled_occurrences (
                            occurrence_id, schedule_id, scheduled_for_utc,
                            scheduled_for_local, schedule_generation, job_id,
                            materialized_at, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            occ_id,
                            schedule.schedule_id,
                            utc_iso,
                            loc_iso,
                            current_gen,
                            job_id,
                            now_iso,
                            status.value,
                        ),
                    )
                except sqlite3.IntegrityError:
                    # Race-safety: another scheduler instance already materialized this occurrence!
                    logger.warning(
                        "Occurrence %s (%s) already materialized by concurrent scheduler; skipping.",
                        schedule.schedule_id,
                        utc_iso,
                    )
                    return []

                # 3. Create canonical Job with provenance
                raw_summary = row["payload_summary_json"] or "{}"
                try:
                    summary_dict = json.loads(raw_summary)
                except Exception:
                    summary_dict = {}

                job_summary = {
                    **summary_dict,
                    "schedule_id": schedule.schedule_id,
                    "occurrence_id": occ_id,
                    "scheduled_for": utc_iso,
                }
                job_summary_json = json.dumps(job_summary)

                cursor.execute(
                    """
                    INSERT INTO jobs (
                        job_id, job_type, status, payload_reference, payload_summary_json,
                        created_by, project_id, schedule_id, timeout_seconds, created_at, updated_at
                    ) VALUES (?, ?, "ready", ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        row["job_type"],
                        row["payload_reference"],
                        job_summary_json,
                        row["created_by"],
                        row["project_id"],
                        schedule.schedule_id,
                        row["timeout_seconds"],
                        now_iso,
                        now_iso,
                    ),
                )

                # 4. Enqueue into job_queue
                cursor.execute(
                    """
                    INSERT INTO job_queue (
                        queue_entry_id, job_id, enqueued_at, available_at,
                        lease_owner, lease_token, lease_generation,
                        lease_acquired_at, lease_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, NULL, NULL, 0, NULL, NULL, ?, ?)
                    """,
                    (queue_entry_id, job_id, now_iso, now_iso, now_iso, now_iso),
                )

                # 5. Insert audit events
                # Event 1: JOB_CREATED
                cursor.execute(
                    """
                    INSERT INTO job_events (
                        event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
                    ) VALUES (?, ?, NULL, ?, 1, ?, ?)
                    """,
                    (
                        generate_event_id(),
                        job_id,
                        JobEventType.JOB_CREATED.value,
                        now_iso,
                        json.dumps({"schedule_id": schedule.schedule_id, "occurrence_id": occ_id}),
                    ),
                )

                # Event 2: OCCURRENCE_MATERIALIZED or MISSED_RUN_MATERIALIZED
                cursor.execute(
                    """
                    INSERT INTO job_events (
                        event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
                    ) VALUES (?, ?, NULL, ?, 2, ?, ?)
                    """,
                    (
                        generate_event_id(),
                        job_id,
                        event_type.value,
                        now_iso,
                        json.dumps(
                            {
                                "schedule_id": schedule.schedule_id,
                                "occurrence_id": occ_id,
                                "scheduled_for_utc": utc_iso,
                                "scheduled_for_local": loc_iso,
                                "schedule_generation": current_gen,
                            }
                        ),
                    ),
                )

                # Event 3: JOB_ENQUEUED
                cursor.execute(
                    """
                    INSERT INTO job_events (
                        event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
                    ) VALUES (?, ?, NULL, ?, 3, ?, ?)
                    """,
                    (
                        generate_event_id(),
                        job_id,
                        JobEventType.JOB_ENQUEUED.value,
                        now_iso,
                        json.dumps({"queue_entry_id": queue_entry_id}),
                    ),
                )

                # 6. Calculate next future run and update schedule
                next_utc, _ = get_next_occurrence(
                    row["cron_expression"],
                    row["timezone"],
                    after_dt=max(scheduled_for_utc, now_dt),
                )
                next_run_iso = format_utc_iso(next_utc)

                cursor.execute(
                    """
                    UPDATE job_schedules
                    SET last_run_at = ?, next_run_at = ?, updated_at = ?
                    WHERE schedule_id = ? AND schedule_generation = ?
                    """,
                    (utc_iso, next_run_iso, now_iso, schedule.schedule_id, current_gen),
                )

                logger.info(
                    "Materialized occurrence %s for schedule %s -> Job %s (next_run=%s)",
                    occ_id,
                    schedule.schedule_id,
                    job_id,
                    next_run_iso,
                )

                return [
                    ScheduledOccurrence(
                        occurrence_id=occ_id,
                        schedule_id=schedule.schedule_id,
                        scheduled_for_utc=utc_iso,
                        scheduled_for_local=loc_iso,
                        schedule_generation=current_gen,
                        job_id=job_id,
                        materialized_at=now_iso,
                        status=status,
                    )
                ]
        finally:
            if not self._is_memory:
                conn.close()

    # --------------------------------------------------------------------------
    # Background Polling Runner
    # --------------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler background polling loop."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="scheduler-service",
                daemon=True,
            )
            self._thread.start()
            logger.info("Scheduler service started (poll_interval=%.2fs)", self._poll_interval)

    def stop(self, timeout_seconds: float = 5.0) -> None:
        """Gracefully stop the scheduler polling loop."""
        with self._lock:
            if not self._running:
                return
            self._stop_event.set()
            thread = self._thread
            self._running = False

        if thread and thread.is_alive():
            thread.join(timeout=timeout_seconds)
            logger.info("Scheduler service stopped")

    def _run_loop(self) -> None:
        """Internal background loop running ticks until stopped."""
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.error("Unexpected error in scheduler loop: %s", e, exc_info=True)

            self._stop_event.wait(timeout=self._poll_interval)

    def __enter__(self) -> SchedulerService:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
