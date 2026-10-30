"""core/jobs/migrations.py

Schema Migrations for the Canonical Job Domain (Task R4.1).
Part of Milestone R4 (Task R4.1 - Canonical Job Domain).

Provides explicit versioned migrations for SQLite persistence,
ensuring zero data loss on restart and deterministic schema states.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, List, Optional, Tuple

from core.jobs.models import current_timestamp_iso

logger = logging.getLogger("agent_engine.jobs.migrations")

MIGRATIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS job_schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def _migration_001_initial_job_domain(conn: sqlite3.Connection) -> None:
    """Migration 001: Initial Job Domain tables, indexes, and constraints."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_reference TEXT,
            payload_summary_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT 'authority:local_user',
            project_id TEXT,
            schedule_id TEXT,
            policy_context_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);",
        "CREATE INDEX IF NOT EXISTS idx_jobs_project_id ON jobs(project_id);",
        "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);",
        """
        CREATE TABLE IF NOT EXISTS job_attempts (
            attempt_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL,
            execution_id TEXT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            failure_classification TEXT,
            failure_message TEXT,
            UNIQUE(job_id, attempt_number)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_attempts_job_id ON job_attempts(job_id);",
        "CREATE INDEX IF NOT EXISTS idx_attempts_execution_id ON job_attempts(execution_id);",
        """
        CREATE TABLE IF NOT EXISTS job_events (
            event_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            attempt_id TEXT,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_job_id ON job_events(job_id);",
        "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON job_events(timestamp);",
        """
        CREATE TABLE IF NOT EXISTS job_dependencies (
            dependency_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            depends_on_job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            dependency_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(job_id, depends_on_job_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_dependencies_job_id ON job_dependencies(job_id);",
        "CREATE INDEX IF NOT EXISTS idx_dependencies_depends_on ON job_dependencies(depends_on_job_id);",
        """
        CREATE TABLE IF NOT EXISTS job_artifacts (
            job_artifact_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'output',
            created_at TEXT NOT NULL,
            UNIQUE(job_id, artifact_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_id ON job_artifacts(job_id);",
        "CREATE INDEX IF NOT EXISTS idx_job_artifacts_artifact_id ON job_artifacts(artifact_id);",
        """
        CREATE TABLE IF NOT EXISTS job_schedules (
            schedule_id TEXT PRIMARY KEY,
            job_template_id TEXT,
            job_type TEXT NOT NULL,
            cron_expression TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            enabled INTEGER NOT NULL DEFAULT 1,
            payload_reference TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON job_schedules(enabled);",
    ]

    for stmt in ddl_statements:
        conn.execute(stmt)


def _migration_002_persistent_job_queue(conn: sqlite3.Connection) -> None:
    """Migration 002: Persistent Job Queue table and deterministic event sequence numbering."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS job_queue (
            queue_entry_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id) ON DELETE CASCADE,
            enqueued_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            lease_owner TEXT,
            lease_token TEXT,
            lease_generation INTEGER NOT NULL DEFAULT 0,
            lease_acquired_at TEXT,
            lease_expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_job_queue_available_expires ON job_queue(available_at, lease_expires_at);",
        "CREATE INDEX IF NOT EXISTS idx_job_queue_job_id ON job_queue(job_id);",
        "ALTER TABLE job_events ADD COLUMN sequence_number INTEGER NOT NULL DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS idx_events_job_seq ON job_events(job_id, sequence_number);",
    ]

    for stmt in ddl_statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass
            else:
                raise

    # Backfill sequence_number for any existing pre-v2 rows using rowid
    conn.execute("UPDATE job_events SET sequence_number = rowid WHERE sequence_number = 0;")


def _migration_003_worker_attempt_ownership(conn: sqlite3.Connection) -> None:
    """Migration 003: Worker attempt ownership and lease generation tracking."""
    ddl_statements = [
        "ALTER TABLE job_attempts ADD COLUMN worker_id TEXT;",
        "ALTER TABLE job_attempts ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS idx_attempts_worker_gen ON job_attempts(worker_id, lease_generation);",
    ]

    for stmt in ddl_statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass
            else:
                raise


def _migration_004_job_idempotency_and_retry(conn: sqlite3.Connection) -> None:
    """Migration 004: Durable idempotency records and retry tracking."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS job_idempotency_records (
            idempotency_key TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            operation_kind TEXT NOT NULL,
            argument_digest TEXT NOT NULL,
            capability TEXT NOT NULL,
            status TEXT NOT NULL,
            claimed_by_attempt TEXT,
            result_reference TEXT,
            result_payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_idempotency_job_id ON job_idempotency_records(job_id);",
        "CREATE INDEX IF NOT EXISTS idx_idempotency_status ON job_idempotency_records(status);",
        "CREATE INDEX IF NOT EXISTS idx_idempotency_digest ON job_idempotency_records(argument_digest);",
    ]

    for stmt in ddl_statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                pass
            else:
                raise


def _migration_005_job_control_and_timeouts(conn: sqlite3.Connection) -> None:
    """Migration 005: Durable job execution controls, generation fencing, and timeouts."""
    ddl_statements = [
        "ALTER TABLE jobs ADD COLUMN control_intent TEXT NOT NULL DEFAULT 'none';",
        "ALTER TABLE jobs ADD COLUMN control_generation INTEGER NOT NULL DEFAULT 0;",
        "ALTER TABLE jobs ADD COLUMN timeout_seconds INTEGER;",
        "ALTER TABLE jobs ADD COLUMN timeout_at TEXT;",
        "ALTER TABLE jobs ADD COLUMN prior_status_before_pause TEXT;",
        "CREATE INDEX IF NOT EXISTS idx_jobs_control ON jobs(control_intent, control_generation);",
        "CREATE INDEX IF NOT EXISTS idx_jobs_timeout ON jobs(status, timeout_at);",
    ]

    for stmt in ddl_statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                pass
            else:
                raise


def _migration_006_timezone_aware_scheduler(conn: sqlite3.Connection) -> None:
    """Migration 006: Timezone-aware scheduler, occurrence tracking, and schedule generation fencing."""
    ddl_statements = [
        # 1. Upgrade job_schedules with template spec, generation fencing, and policies
        "ALTER TABLE job_schedules ADD COLUMN schedule_generation INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE job_schedules ADD COLUMN missed_run_policy TEXT NOT NULL DEFAULT 'skip';",
        "ALTER TABLE job_schedules ADD COLUMN next_run_at TEXT;",
        "ALTER TABLE job_schedules ADD COLUMN last_run_at TEXT;",
        "ALTER TABLE job_schedules ADD COLUMN payload_summary_json TEXT NOT NULL DEFAULT '{}';",
        "ALTER TABLE job_schedules ADD COLUMN created_by TEXT NOT NULL DEFAULT 'authority:local_user';",
        "ALTER TABLE job_schedules ADD COLUMN project_id TEXT;",
        "ALTER TABLE job_schedules ADD COLUMN timeout_seconds INTEGER;",
        "CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON job_schedules(enabled, next_run_at);",
        # 2. Scheduled occurrences table with strict generation-fenced uniqueness
        """
        CREATE TABLE IF NOT EXISTS scheduled_occurrences (
            occurrence_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL REFERENCES job_schedules(schedule_id) ON DELETE CASCADE,
            scheduled_for_utc TEXT NOT NULL,
            scheduled_for_local TEXT NOT NULL,
            schedule_generation INTEGER NOT NULL,
            job_id TEXT UNIQUE REFERENCES jobs(job_id) ON DELETE SET NULL,
            materialized_at TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(schedule_id, schedule_generation, scheduled_for_utc)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_occurrences_schedule ON scheduled_occurrences(schedule_id);",
        "CREATE INDEX IF NOT EXISTS idx_occurrences_scheduled_utc ON scheduled_occurrences(scheduled_for_utc);",
        "CREATE INDEX IF NOT EXISTS idx_occurrences_job_id ON scheduled_occurrences(job_id);",
    ]

    for stmt in ddl_statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                pass
            else:
                raise


def _migration_007_canonical_workflows(conn: sqlite3.Connection) -> None:
    """Migration 007: Canonical Workflow Domain tables, indexes, and constraints (Task R4.8)."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS workflow_definitions (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            version TEXT NOT NULL,
            status TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            definition_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_workflow_defs_status ON workflow_definitions(status);",
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            workflow_run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflow_definitions(workflow_id) ON DELETE CASCADE,
            definition_hash TEXT NOT NULL,
            definition_snapshot_json TEXT NOT NULL,
            status TEXT NOT NULL,
            inputs_json TEXT NOT NULL DEFAULT '{}',
            outputs_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);",
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);",
        """
        CREATE TABLE IF NOT EXISTS workflow_node_runs (
            node_run_id TEXT PRIMARY KEY,
            workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(workflow_run_id) ON DELETE CASCADE,
            node_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            job_id TEXT REFERENCES jobs(job_id) ON DELETE SET NULL,
            status TEXT NOT NULL,
            inputs_json TEXT NOT NULL DEFAULT '{}',
            outputs_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(workflow_run_id, node_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_node_runs_run_id ON workflow_node_runs(workflow_run_id);",
        "CREATE INDEX IF NOT EXISTS idx_node_runs_job_id ON workflow_node_runs(job_id);",
        "CREATE INDEX IF NOT EXISTS idx_node_runs_status ON workflow_node_runs(status);",
    ]
    cursor = conn.cursor()
    for stmt in ddl_statements:
        cursor.execute(stmt)


def _migration_008_workflow_provenance_retention(conn: sqlite3.Connection) -> None:
    """Migration 008: Workflow provenance retention — enforce ON DELETE RESTRICT on workflow_runs (Task R4.8)."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS workflow_runs_v8 (
            workflow_run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflow_definitions(workflow_id) ON DELETE RESTRICT,
            definition_hash TEXT NOT NULL,
            definition_snapshot_json TEXT NOT NULL,
            status TEXT NOT NULL,
            inputs_json TEXT NOT NULL DEFAULT '{}',
            outputs_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        """,
        "INSERT INTO workflow_runs_v8 SELECT * FROM workflow_runs;",
        "DROP TABLE workflow_runs;",
        "ALTER TABLE workflow_runs_v8 RENAME TO workflow_runs;",
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);",
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);",
    ]
    cursor = conn.cursor()
    for stmt in ddl_statements:
        cursor.execute(stmt)


def _migration_009_workflow_hitl_gates(conn: sqlite3.Connection) -> None:
    """Migration 009: Human-in-the-loop workflow gate execution state (Task R4.9)."""
    ddl_statements = [
        "ALTER TABLE workflow_node_runs ADD COLUMN approval_id TEXT;",
        "ALTER TABLE workflow_node_runs ADD COLUMN operation_digest TEXT;",
        "ALTER TABLE workflow_node_runs ADD COLUMN suspended_at TEXT;",
        "ALTER TABLE workflow_node_runs ADD COLUMN resolved_at TEXT;",
        "CREATE INDEX IF NOT EXISTS idx_node_runs_approval_id ON workflow_node_runs(approval_id);",
        """
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            execution_id TEXT,
            actor TEXT NOT NULL DEFAULT 'local_operator',
            capability TEXT NOT NULL,
            operation_digest TEXT NOT NULL,
            digest_version INTEGER NOT NULL DEFAULT 1,
            token_verifier TEXT NOT NULL,
            issued_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            decision TEXT NOT NULL DEFAULT 'approved',
            status TEXT NOT NULL DEFAULT 'pending',
            consumed_at REAL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_approvals_token_verifier ON approvals(token_verifier);",
        "CREATE INDEX IF NOT EXISTS idx_approvals_execution_id ON approvals(execution_id);",
        "CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);",
    ]
    cursor = conn.cursor()
    for stmt in ddl_statements:
        try:
            cursor.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                pass
            else:
                raise


MIGRATION_REGISTRY: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "001_initial_job_domain", _migration_001_initial_job_domain),
    (2, "002_persistent_job_queue", _migration_002_persistent_job_queue),
    (3, "003_worker_attempt_ownership", _migration_003_worker_attempt_ownership),
    (4, "004_job_idempotency_and_retry", _migration_004_job_idempotency_and_retry),
    (5, "005_job_control_and_timeouts", _migration_005_job_control_and_timeouts),
    (6, "006_timezone_aware_scheduler", _migration_006_timezone_aware_scheduler),
    (7, "007_canonical_workflows", _migration_007_canonical_workflows),
    (8, "008_workflow_provenance_retention", _migration_008_workflow_provenance_retention),
    (9, "009_workflow_hitl_gates", _migration_009_workflow_hitl_gates),
]


def apply_job_migrations(conn: sqlite3.Connection, target_version: Optional[int] = None) -> int:
    """Apply all pending job migrations within transaction boundaries.

    Args:
        conn: Open SQLite database connection.
        target_version: Optional maximum migration version to apply. If None, applies all.

    Returns:
        int: Number of newly applied migrations.
    """
    conn.execute(MIGRATIONS_TABLE_DDL)
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM job_schema_migrations ORDER BY version ASC")
    applied_versions = {row[0] for row in cursor.fetchall()}

    # Check whether foreign keys are currently enabled
    cursor.execute("PRAGMA foreign_keys;")
    fk_row = cursor.fetchone()
    fk_enabled = bool(fk_row[0]) if fk_row else False

    applied_count = 0
    for version, name, migration_func in MIGRATION_REGISTRY:
        if target_version is not None and version > target_version:
            continue
        if version not in applied_versions:
            logger.info("Applying job domain migration %d: %s", version, name)
            if fk_enabled:
                conn.execute("PRAGMA foreign_keys = OFF;")
            try:
                with conn:
                    migration_func(conn)
                    conn.execute(
                        "INSERT INTO job_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                        (version, name, current_timestamp_iso()),
                    )
            finally:
                if fk_enabled:
                    conn.execute("PRAGMA foreign_keys = ON;")
            applied_count += 1

    return applied_count


def get_current_job_schema_version(conn: sqlite3.Connection) -> int:
    """Get the latest applied job schema version."""
    conn.execute(MIGRATIONS_TABLE_DDL)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(version) FROM job_schema_migrations")
    row = cursor.fetchone()
    return row[0] if (row and row[0] is not None) else 0
