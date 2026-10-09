"""core/jobs/migrations.py

Schema Migrations for the Canonical Job Domain (Task R4.1).
Part of Milestone R4 (Task R4.1 - Canonical Job Domain).

Provides explicit versioned migrations for SQLite persistence,
ensuring zero data loss on restart and deterministic schema states.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, List, Tuple

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


MIGRATION_REGISTRY: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "001_initial_job_domain", _migration_001_initial_job_domain),
    (2, "002_persistent_job_queue", _migration_002_persistent_job_queue),
]


def apply_job_migrations(conn: sqlite3.Connection) -> int:
    """Apply all pending job migrations within transaction boundaries.

    Returns:
        int: Number of newly applied migrations.
    """
    conn.execute(MIGRATIONS_TABLE_DDL)
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM job_schema_migrations ORDER BY version ASC")
    applied_versions = {row[0] for row in cursor.fetchall()}

    applied_count = 0
    for version, name, migration_func in MIGRATION_REGISTRY:
        if version not in applied_versions:
            logger.info("Applying job domain migration %d: %s", version, name)
            with conn:
                migration_func(conn)
                conn.execute(
                    "INSERT INTO job_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, current_timestamp_iso()),
                )
            applied_count += 1

    return applied_count


def get_current_job_schema_version(conn: sqlite3.Connection) -> int:
    """Get the latest applied job schema version."""
    conn.execute(MIGRATIONS_TABLE_DDL)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(version) FROM job_schema_migrations")
    row = cursor.fetchone()
    return row[0] if (row and row[0] is not None) else 0
