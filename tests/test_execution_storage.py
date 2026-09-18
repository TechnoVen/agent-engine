"""Tests for Execution Storage Repository & Alembic Migration (Task R1.1)."""

import os
from pathlib import Path
import subprocess
import sys

from core.execution.models import (
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
    RoutingTier,
    generate_event_id,
    generate_execution_id,
)
from core.storage.sqlite import SQLiteBackend


def test_sqlite_execution_crud_lifecycle(tmp_path):
    """Verify create, get, update, and list operations on executions table."""
    db_path = str(tmp_path / "test_exec.db")
    backend = SQLiteBackend(db_path=db_path)

    exec_id = generate_execution_id()
    req = ExecutionRequest(
        project_id="proj_alpha",
        session_id="sess_100",
        task_type="chat",
        prompt="Write a unit test",
        inputs={"format": "python"},
        target_tier=RoutingTier.MID,
    )
    execution_data = {
        "id": exec_id,
        "project_id": "proj_alpha",
        "session_id": "sess_100",
        "request": req.model_dump(),
        "status": ExecutionStatus.CREATED.value,
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "routing_tier": RoutingTier.MID.value,
        "input_tokens": 50,
        "output_tokens": 120,
        "total_cost_usd": 0.00045,
        "is_cost_estimated": False,
    }

    # 1. Create
    created = backend.create_execution(execution_data)
    assert created["id"] == exec_id
    assert created["status"] == "created"

    # 2. Get
    fetched = backend.get_execution(exec_id)
    assert fetched is not None
    assert fetched["id"] == exec_id
    assert fetched["project_id"] == "proj_alpha"
    assert fetched["model"] == "gemini-2.0-flash"
    assert fetched["request"]["prompt"] == "Write a unit test"

    # 3. Update
    updated = backend.update_execution(
        exec_id,
        {
            "status": ExecutionStatus.COMPLETED.value,
            "output_tokens": 200,
            "total_cost_usd": 0.0008,
            "completed_at": "2026-09-18T12:00:00Z",
        },
    )
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["output_tokens"] == 200
    assert updated["completed_at"] == "2026-09-18T12:00:00Z"

    # 4. List with filters
    list_all = backend.list_executions(project_id="proj_alpha")
    assert len(list_all) == 1
    assert list_all[0]["id"] == exec_id

    list_status = backend.list_executions(project_id="proj_alpha", status="completed")
    assert len(list_status) == 1

    list_other = backend.list_executions(project_id="nonexistent")
    assert len(list_other) == 0


def test_sqlite_execution_events_stream(tmp_path):
    """Verify recording and ordered retrieval of execution events."""
    db_path = str(tmp_path / "test_events.db")
    backend = SQLiteBackend(db_path=db_path)

    exec_id = generate_execution_id()
    # Create parent execution first
    backend.create_execution(
        {
            "id": exec_id,
            "project_id": "proj_events",
            "status": "running",
            "request": {"prompt": "Streaming test"},
        }
    )

    # Record sequence of events
    event_1 = {
        "id": generate_event_id(),
        "execution_id": exec_id,
        "sequence_num": 0,
        "event_type": ExecutionEventType.STATE_CHANGE.value,
        "payload": {"status": "running"},
    }
    event_2 = {
        "id": generate_event_id(),
        "execution_id": exec_id,
        "sequence_num": 1,
        "event_type": ExecutionEventType.OUTPUT_CHUNK.value,
        "payload": {"chunk": "Hello "},
    }
    event_3 = {
        "id": generate_event_id(),
        "execution_id": exec_id,
        "sequence_num": 2,
        "event_type": ExecutionEventType.OUTPUT_CHUNK.value,
        "payload": {"chunk": "world!"},
    }

    backend.record_execution_event(event_1)
    backend.record_execution_event(event_2)
    backend.record_execution_event(event_3)

    # Retrieve all events
    events = backend.get_execution_events(exec_id)
    assert len(events) == 3
    assert events[0]["sequence_num"] == 0
    assert events[1]["sequence_num"] == 1
    assert events[2]["sequence_num"] == 2
    assert events[1]["payload"]["chunk"] == "Hello "

    # Retrieve events after sequence_num 0
    sub_events = backend.get_execution_events(exec_id, after_sequence_num=0)
    assert len(sub_events) == 2
    assert sub_events[0]["sequence_num"] == 1
    assert sub_events[1]["sequence_num"] == 2


def test_alembic_canonical_executions_migration(tmp_path):
    """Verify that Alembic runs 003_canonical_executions migration cleanly."""
    migration_db = tmp_path / "migration_test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{migration_db}"

    repo_root = Path(__file__).resolve().parents[1]

    # Run alembic upgrade head
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Alembic upgrade failed: {result.stderr}"

    import sqlite3

    conn = sqlite3.connect(str(migration_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {r[0] for r in cursor.fetchall()}
    conn.close()

    assert "executions" in tables
    assert "execution_events" in tables

    # Test downgrade to 002
    result_down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "002_unified_session_store"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result_down.returncode == 0, f"Alembic downgrade failed: {result_down.stderr}"

    conn = sqlite3.connect(str(migration_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables_after = {r[0] for r in cursor.fetchall()}
    conn.close()

    assert "executions" not in tables_after
    assert "execution_events" not in tables_after
