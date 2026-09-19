"""SQLite storage backend implementation for Agent Engine.

Provides zero-setup, local-first single-user persistence with WAL mode,
transaction safety, and thread safety.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.storage.base import StorageBackend

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")


class SQLiteBackend(StorageBackend):
    """Local SQLite repository implementation."""

    def __init__(self, db_path: str = DEFAULT_SQLITE_PATH):
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._lock = threading.RLock()
        self._memory_conn: Optional[sqlite3.Connection] = None
        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self) -> None:
        """Initialize all 6 domain tables with indexes."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.executescript("""
                    CREATE TABLE IF NOT EXISTS audit_patches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        status TEXT NOT NULL,
                        patch_type TEXT NOT NULL,
                        risk_level TEXT,
                        report TEXT,
                        original_code TEXT,
                        patched_code TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_audit_patches_status ON audit_patches(status);

                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        messages TEXT NOT NULL DEFAULT '[]',
                        title TEXT NOT NULL DEFAULT 'Untitled Session',
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        channel TEXT NOT NULL DEFAULT 'web',
                        status TEXT NOT NULL DEFAULT 'active',
                        parent_session_id TEXT,
                        fork_point_message_id TEXT,
                        summary TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        email TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'developer',
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        created_at TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

                    CREATE TABLE IF NOT EXISTS policies (
                        policy_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        rules TEXT NOT NULL DEFAULT '{}',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS cost_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        agent_name TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        prompt_tokens INTEGER NOT NULL,
                        completion_tokens INTEGER NOT NULL,
                        cost_usd REAL NOT NULL,
                        task_id TEXT,
                        success INTEGER NOT NULL DEFAULT 1,
                        project TEXT NOT NULL DEFAULT 'default'
                    );
                    CREATE INDEX IF NOT EXISTS idx_cost_agent ON cost_records(agent_name);
                    CREATE INDEX IF NOT EXISTS idx_cost_model ON cost_records(model_name);

                    CREATE TABLE IF NOT EXISTS benchmarks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        model_name TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        success_rate REAL NOT NULL,
                        latency_ms REAL NOT NULL,
                        cost_per_success REAL NOT NULL,
                        timestamp TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_benchmarks_task ON benchmarks(task_type);

                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        tool_args TEXT NOT NULL DEFAULT '{}',
                        decision TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        risk_score REAL NOT NULL,
                        policy_id TEXT,
                        reason TEXT,
                        suggestion TEXT,
                        session_id TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_audit_logs_decision ON audit_logs(decision);
                    CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);

                    CREATE TABLE IF NOT EXISTS scheduled_tasks (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        cron TEXT NOT NULL,
                        cron_human TEXT NOT NULL DEFAULT '',
                        agent_persona TEXT NOT NULL DEFAULT 'Senior Engineer',
                        model TEXT NOT NULL DEFAULT 'instant',
                        status TEXT NOT NULL DEFAULT 'active',
                        last_run TEXT,
                        next_run TEXT,
                        cost_per_run REAL NOT NULL DEFAULT 0.0012,
                        monthly_estimate REAL NOT NULL DEFAULT 0.036,
                        is_off_peak INTEGER NOT NULL DEFAULT 1,
                        notification_channel TEXT NOT NULL DEFAULT 'slack',
                        prompt TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status ON scheduled_tasks(status);

                    CREATE TABLE IF NOT EXISTS collaborative_rooms (
                        room_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        topic TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'active',
                        policy_id TEXT,
                        active_adapters TEXT NOT NULL DEFAULT '[]',
                        session_ids TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_rooms_project ON collaborative_rooms(project_id);
                    CREATE INDEX IF NOT EXISTS idx_rooms_status ON collaborative_rooms(status);

                    CREATE TABLE IF NOT EXISTS room_participants (
                        room_id TEXT NOT NULL,
                        participant_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        role TEXT NOT NULL,
                        participant_type TEXT NOT NULL DEFAULT 'human',
                        adapter_type TEXT,
                        permissions TEXT NOT NULL DEFAULT '[]',
                        joined_at TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        PRIMARY KEY (room_id, participant_id),
                        FOREIGN KEY (room_id) REFERENCES collaborative_rooms(room_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_participants_room ON room_participants(room_id);
                    CREATE INDEX IF NOT EXISTS idx_participants_role ON room_participants(role);

                    CREATE TABLE IF NOT EXISTS room_tasks (
                        task_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'pending',
                        priority TEXT NOT NULL DEFAULT 'medium',
                        assigned_to TEXT,
                        assigned_adapter TEXT,
                        parent_task_id TEXT,
                        dependencies TEXT NOT NULL DEFAULT '[]',
                        created_by TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        result TEXT,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        FOREIGN KEY (room_id) REFERENCES collaborative_rooms(room_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_tasks_room_status ON room_tasks(room_id, status);
                    CREATE INDEX IF NOT EXISTS idx_tasks_parent ON room_tasks(parent_task_id);

                    CREATE TABLE IF NOT EXISTS skill_collections (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        tags TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS collection_skills (
                        collection_id TEXT NOT NULL,
                        skill_id TEXT NOT NULL,
                        added_at TEXT NOT NULL,
                        PRIMARY KEY (collection_id, skill_id),
                        FOREIGN KEY (collection_id) REFERENCES skill_collections(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_collection_skills_skill ON collection_skills(skill_id);

                    CREATE TABLE IF NOT EXISTS executions (
                        id TEXT PRIMARY KEY,
                        session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
                        project_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        provider TEXT,
                        model TEXT,
                        routing_tier TEXT,
                        input_tokens INTEGER DEFAULT 0,
                        output_tokens INTEGER DEFAULT 0,
                        total_cost_usd REAL DEFAULT 0.0,
                        is_cost_estimated INTEGER NOT NULL DEFAULT 0,
                        started_at TEXT,
                        completed_at TEXT,
                        error_code TEXT,
                        error_message TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_executions_project ON executions(project_id);
                    CREATE INDEX IF NOT EXISTS idx_executions_session ON executions(session_id);
                    CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);

                    CREATE TABLE IF NOT EXISTS execution_events (
                        id TEXT PRIMARY KEY,
                        execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
                        sequence_num INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        UNIQUE(execution_id, sequence_num)
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_execution ON execution_events(execution_id);

                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        root_path TEXT NOT NULL UNIQUE,
                        instructions TEXT NOT NULL DEFAULT '',
                        settings_json TEXT NOT NULL DEFAULT '{}',
                        is_default INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);

                    CREATE TABLE IF NOT EXISTS artifacts (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        type TEXT NOT NULL DEFAULT 'file',
                        mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                        storage_kind TEXT NOT NULL DEFAULT 'filesystem',
                        file_path TEXT,
                        inline_content TEXT,
                        sha256_hash TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ready',
                        lineage_json TEXT NOT NULL DEFAULT '{}',
                        created_by TEXT,
                        created_at TEXT NOT NULL,
                        deleted_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
                    CREATE INDEX IF NOT EXISTS idx_artifacts_execution ON artifacts(execution_id);
                    CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(type);
                    CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);
                """)
                conn.commit()

                # Migration check: ensure 'deleted_at' column exists in artifacts
                cursor.execute("PRAGMA table_info(artifacts)")
                existing_art_cols = [row[1] for row in cursor.fetchall()]
                if "deleted_at" not in existing_art_cols and "id" in existing_art_cols:
                    cursor.execute("ALTER TABLE artifacts ADD COLUMN deleted_at TEXT")
                    conn.commit()

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artifacts_deleted_at ON artifacts(deleted_at)"
                )
                conn.commit()

                # Migration check: ensure 'is_default' column exists before indexing and inserting
                cursor.execute("PRAGMA table_info(projects)")
                existing_proj_cols = [row[1] for row in cursor.fetchall()]
                if "is_default" not in existing_proj_cols:
                    cursor.execute(
                        "ALTER TABLE projects ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0"
                    )
                    conn.commit()

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_projects_is_default ON projects(is_default)"
                )
                # Migrate any legacy 'default' or 'proj_default' project records to a canonical proj_<hex12> ID
                cursor.execute("SELECT id FROM projects WHERE id IN ('default', 'proj_default')")
                legacy_rows = cursor.fetchall()
                if legacy_rows:
                    legacy_ids = [row[0] for row in legacy_rows]
                    cursor.execute(
                        "SELECT id FROM projects WHERE is_default = 1 AND id NOT IN ('default', 'proj_default') LIMIT 1"
                    )
                    existing_canonical_default = cursor.fetchone()
                    if existing_canonical_default:
                        canonical_default_id = existing_canonical_default[0]
                        for lid in legacy_ids:
                            cursor.execute(
                                "UPDATE executions SET project_id = ? WHERE project_id = ?",
                                (canonical_default_id, lid),
                            )
                            cursor.execute(
                                "UPDATE cost_records SET project = ? WHERE project = ?",
                                (canonical_default_id, lid),
                            )
                            cursor.execute("DELETE FROM projects WHERE id = ?", (lid,))
                    else:
                        canonical_default_id = f"proj_{uuid.uuid4().hex[:12]}"
                        first_lid = legacy_ids[0]
                        cursor.execute(
                            "UPDATE projects SET id = ?, is_default = 1 WHERE id = ?",
                            (canonical_default_id, first_lid),
                        )
                        cursor.execute(
                            "UPDATE executions SET project_id = ? WHERE project_id = ?",
                            (canonical_default_id, first_lid),
                        )
                        cursor.execute(
                            "UPDATE cost_records SET project = ? WHERE project = ?",
                            (canonical_default_id, first_lid),
                        )
                        for other_lid in legacy_ids[1:]:
                            cursor.execute(
                                "UPDATE executions SET project_id = ? WHERE project_id = ?",
                                (canonical_default_id, other_lid),
                            )
                            cursor.execute(
                                "UPDATE cost_records SET project = ? WHERE project = ?",
                                (canonical_default_id, other_lid),
                            )
                            cursor.execute("DELETE FROM projects WHERE id = ?", (other_lid,))
                    conn.commit()

                # Cascade any executions or cost records still referencing legacy aliases to the canonical default project
                cursor.execute(
                    "SELECT id FROM projects WHERE is_default = 1 ORDER BY created_at ASC LIMIT 1"
                )
                def_row = cursor.fetchone()
                if def_row:
                    target_def_id = def_row[0]
                    cursor.execute(
                        "UPDATE executions SET project_id = ? WHERE project_id IN ('default', 'proj_default')",
                        (target_def_id,),
                    )
                    cursor.execute(
                        "UPDATE cost_records SET project = ? WHERE project IN ('default', 'proj_default')",
                        (target_def_id,),
                    )
                    conn.commit()
                else:
                    canonical_default_id = f"proj_{uuid.uuid4().hex[:12]}"
                    cursor.execute(
                        """
                        INSERT INTO projects (id, name, description, root_path, instructions, settings_json, is_default, created_at, updated_at)
                        VALUES (?, 'Default Project', 'Default workspace project', '/workspace', '', '{}', 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """,
                        (canonical_default_id,),
                    )
                    conn.commit()

                # Migration check: ensure 'project' column exists in existing database
                cursor.execute("PRAGMA table_info(cost_records)")
                existing_cols = [row[1] for row in cursor.fetchall()]
                if "project" not in existing_cols:
                    cursor.execute(
                        "ALTER TABLE cost_records ADD COLUMN project TEXT NOT NULL DEFAULT 'default'"
                    )
                    conn.commit()

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cost_project ON cost_records(project)"
                )
                conn.commit()

                # Migration check: ensure unified session columns exist in existing database
                cursor.execute("PRAGMA table_info(sessions)")
                existing_sess_cols = [row[1] for row in cursor.fetchall()]
                session_cols_to_add = [
                    ("title", "TEXT NOT NULL DEFAULT 'Untitled Session'"),
                    ("tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
                    ("channel", "TEXT NOT NULL DEFAULT 'web'"),
                    ("status", "TEXT NOT NULL DEFAULT 'active'"),
                    ("parent_session_id", "TEXT"),
                    ("fork_point_message_id", "TEXT"),
                    ("summary", "TEXT"),
                ]
                for col_name, col_def in session_cols_to_add:
                    if col_name not in existing_sess_cols:
                        cursor.execute(f"ALTER TABLE sessions ADD COLUMN {col_name} {col_def}")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant_id)"
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id)"
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

    def close(self) -> None:
        """Close memory connection if open."""
        with self._lock:
            if self._memory_conn:
                self._memory_conn.close()
                self._memory_conn = None

    # --- 1. AUDIT & STAGED PATCHES ---

    def stage_patch(
        self,
        file_path: str,
        patch_type: str,
        risk_level: str,
        report: str,
        original_code: str,
        patched_code: str,
        status: str = "staged",
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO audit_patches (file_path, timestamp, status, patch_type, risk_level, report, original_code, patched_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_path,
                        now_iso,
                        status,
                        patch_type,
                        risk_level,
                        report,
                        original_code,
                        patched_code,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                if not self._is_memory:
                    conn.close()

    def get_staged_patches(self) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM audit_patches WHERE status = 'staged' ORDER BY id DESC"
                )
                return [dict(r) for r in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    def get_patch(self, patch_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM audit_patches WHERE id = ?", (patch_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                if not self._is_memory:
                    conn.close()

    def apply_patch(self, patch_id: int) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM audit_patches WHERE id = ?", (patch_id,))
                row = cursor.fetchone()
                if not row or row["status"] != "staged":
                    return False

                file_path = row["file_path"]
                patched_code = row["patched_code"]
                original_code = row["original_code"]

                if file_path and patched_code is not None:
                    # Stale patch verification (remediates F05):
                    # Prevent destroying intervening edits if file content has changed on disk
                    if os.path.exists(file_path) and original_code is not None:
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                current_content = f.read()
                            if current_content != original_code:
                                return False
                        except Exception:
                            return False

                    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(patched_code)

                cursor.execute(
                    "UPDATE audit_patches SET status = 'applied' WHERE id = ?", (patch_id,)
                )
                conn.commit()
                return True
            finally:
                if not self._is_memory:
                    conn.close()

    def reject_patch(self, patch_id: int) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE audit_patches SET status = 'rejected' WHERE id = ?", (patch_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 2. SESSIONS ---

    def create_session(
        self,
        session_id: str,
        user_id: str = "default_user",
        metadata: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        tenant_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        parent_session_id: Optional[str] = None,
        fork_point_message_id: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = metadata or {}
        resolved_title = title or meta.get("title") or "Untitled Session"
        resolved_tenant = tenant_id or meta.get("tenant_id") or "default"
        resolved_channel = channel or meta.get("channel") or "web"
        resolved_status = status or meta.get("status") or "active"
        resolved_parent = parent_session_id or meta.get("parent_session_id")
        resolved_fork_point = fork_point_message_id or meta.get("fork_point_message_id")
        resolved_summary = summary or meta.get("summary")

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO sessions (
                        session_id, user_id, created_at, updated_at, metadata, messages,
                        title, tenant_id, channel, status, parent_session_id, fork_point_message_id, summary
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        user_id,
                        now_iso,
                        now_iso,
                        json.dumps(meta),
                        json.dumps([]),
                        resolved_title,
                        resolved_tenant,
                        resolved_channel,
                        resolved_status,
                        resolved_parent,
                        resolved_fork_point,
                        resolved_summary,
                    ),
                )
                conn.commit()
                return {
                    "session_id": session_id,
                    "user_id": user_id,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "metadata": meta,
                    "messages": [],
                    "title": resolved_title,
                    "tenant_id": resolved_tenant,
                    "channel": resolved_channel,
                    "status": resolved_status,
                    "parent_session_id": resolved_parent,
                    "fork_point_message_id": resolved_fork_point,
                    "summary": resolved_summary,
                }
            finally:
                if not self._is_memory:
                    conn.close()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["metadata"] = json.loads(data.get("metadata") or "{}")
                data["messages"] = json.loads(data.get("messages") or "[]")
                data.setdefault("title", data["metadata"].get("title", "Untitled Session"))
                data.setdefault("tenant_id", data["metadata"].get("tenant_id", "default"))
                data.setdefault("channel", data["metadata"].get("channel", "web"))
                data.setdefault("status", data["metadata"].get("status", "active"))
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT * FROM sessions WHERE 1=1"
                params: List[Any] = []
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                if tenant_id:
                    query += " AND tenant_id = ?"
                    params.append(tenant_id)
                if channel:
                    query += " AND channel = ?"
                    params.append(channel)
                if status:
                    query += " AND status = ?"
                    params.append(status)
                query += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, tuple(params))
                results = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["metadata"] = json.loads(item.get("metadata") or "{}")
                    item["messages"] = json.loads(item.get("messages") or "[]")
                    item.setdefault("title", item["metadata"].get("title", "Untitled Session"))
                    item.setdefault("tenant_id", item["metadata"].get("tenant_id", "default"))
                    item.setdefault("channel", item["metadata"].get("channel", "web"))
                    item.setdefault("status", item["metadata"].get("status", "active"))
                    results.append(item)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def update_session(
        self,
        session_id: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        status: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                if not row:
                    return False

                current_row = dict(row)
                current_meta = json.loads(current_row.get("metadata") or "{}")
                current_msgs = json.loads(current_row.get("messages") or "[]")

                if metadata is not None:
                    current_meta.update(metadata)
                if messages is not None:
                    current_msgs = messages

                new_title = (
                    title
                    if title is not None
                    else current_meta.get("title", current_row.get("title", "Untitled Session"))
                )
                new_status = (
                    status
                    if status is not None
                    else current_meta.get("status", current_row.get("status", "active"))
                )
                new_summary = (
                    summary
                    if summary is not None
                    else current_meta.get("summary", current_row.get("summary"))
                )

                cursor.execute(
                    """
                    UPDATE sessions
                    SET updated_at = ?, metadata = ?, messages = ?, title = ?, status = ?, summary = ?
                    WHERE session_id = ?
                    """,
                    (
                        now_iso,
                        json.dumps(current_meta),
                        json.dumps(current_msgs),
                        new_title,
                        new_status,
                        new_summary,
                        session_id,
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def search_sessions(
        self, query: str, user_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                sql = """
                    SELECT * FROM sessions
                    WHERE (title LIKE ? OR metadata LIKE ? OR messages LIKE ?)
                """
                params: List[Any] = [f"%{query}%", f"%{query}%", f"%{query}%"]
                if user_id:
                    sql += " AND user_id = ?"
                    params.append(user_id)
                sql += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(sql, tuple(params))
                results = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["metadata"] = json.loads(item.get("metadata") or "{}")
                    item["messages"] = json.loads(item.get("messages") or "[]")
                    results.append(item)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def fork_session(
        self,
        session_id: str,
        new_session_id: str,
        fork_point_message_id: Optional[str] = None,
        title: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            parent = self.get_session(session_id)
            if not parent:
                return None

            parent_msgs = parent.get("messages") or []
            forked_msgs: List[Dict[str, Any]] = []
            fork_msg_id = fork_point_message_id

            if fork_point_message_id:
                found = False
                for m in parent_msgs:
                    forked_msgs.append(m)
                    if m.get("message_id") == fork_point_message_id:
                        found = True
                        break
                if not found:
                    forked_msgs = list(parent_msgs)
            else:
                forked_msgs = list(parent_msgs)
                if forked_msgs:
                    fork_msg_id = forked_msgs[-1].get("message_id")

            now_iso = datetime.now(timezone.utc).isoformat()
            target_title = title or f"Fork of {parent.get('title', 'Session')}"
            target_user = user_id or parent.get("user_id", "default_user")
            meta = dict(parent.get("metadata") or {})
            meta["forked_from"] = session_id

            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO sessions (
                        session_id, user_id, created_at, updated_at, metadata, messages,
                        title, tenant_id, channel, status, parent_session_id, fork_point_message_id, summary
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_session_id,
                        target_user,
                        now_iso,
                        now_iso,
                        json.dumps(meta),
                        json.dumps(forked_msgs),
                        target_title,
                        parent.get("tenant_id", "default"),
                        parent.get("channel", "web"),
                        "active",
                        session_id,
                        fork_msg_id,
                        parent.get("summary"),
                    ),
                )
                conn.commit()
                return self.get_session(new_session_id)
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 3. USERS & TENANTS ---

    def create_user(
        self,
        user_id: str,
        email: str,
        role: str = "developer",
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO users (user_id, email, role, tenant_id, created_at, is_active)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (user_id, email, role, tenant_id, now_iso),
                )
                conn.commit()
                return {
                    "user_id": user_id,
                    "email": email,
                    "role": role,
                    "tenant_id": tenant_id,
                    "created_at": now_iso,
                    "is_active": True,
                }
            finally:
                if not self._is_memory:
                    conn.close()

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["is_active"] = bool(data["is_active"])
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_users(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if tenant_id:
                    cursor.execute(
                        "SELECT * FROM users WHERE tenant_id = ? ORDER BY user_id", (tenant_id,)
                    )
                else:
                    cursor.execute("SELECT * FROM users ORDER BY user_id")
                results = []
                for row in cursor.fetchall():
                    data = dict(row)
                    data["is_active"] = bool(data["is_active"])
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 4. POLICIES ---

    def save_policy(
        self,
        policy_id: str,
        name: str,
        rules: Dict[str, Any],
        description: Optional[str] = None,
        is_active: bool = True,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO policies (policy_id, name, description, rules, is_active, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(policy_id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        rules = excluded.rules,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at
                    """,
                    (
                        policy_id,
                        name,
                        description,
                        json.dumps(rules),
                        1 if is_active else 0,
                        now_iso,
                    ),
                )
                conn.commit()
                return {
                    "policy_id": policy_id,
                    "name": name,
                    "description": description,
                    "rules": rules,
                    "is_active": is_active,
                    "updated_at": now_iso,
                }
            finally:
                if not self._is_memory:
                    conn.close()

    def get_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM policies WHERE policy_id = ?", (policy_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["rules"] = json.loads(data.get("rules") or "{}")
                data["is_active"] = bool(data["is_active"])
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_policies(self, active_only: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if active_only:
                    cursor.execute("SELECT * FROM policies WHERE is_active = 1 ORDER BY policy_id")
                else:
                    cursor.execute("SELECT * FROM policies ORDER BY policy_id")
                results = []
                for row in cursor.fetchall():
                    data = dict(row)
                    data["rules"] = json.loads(data.get("rules") or "{}")
                    data["is_active"] = bool(data["is_active"])
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 5. FINANCE & COST RECORDS ---

    def record_cost(
        self,
        agent_name: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        task_id: Optional[str] = None,
        success: bool = True,
        project: str = "default",
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO cost_records (timestamp, agent_name, model_name, prompt_tokens, completion_tokens, cost_usd, task_id, success, project)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_iso,
                        agent_name,
                        model_name,
                        prompt_tokens,
                        completion_tokens,
                        cost_usd,
                        task_id,
                        1 if success else 0,
                        project,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                if not self._is_memory:
                    conn.close()

    def get_cost_summary(
        self,
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = """
                    SELECT
                        COUNT(*) as total_calls,
                        COALESCE(SUM(cost_usd), 0.0) as total_cost_usd,
                        COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                        COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) as successful_calls
                    FROM cost_records
                    WHERE 1=1
                """
                params: List[Any] = []
                if agent_name:
                    query += " AND agent_name = ?"
                    params.append(agent_name)
                if model_name:
                    query += " AND model_name = ?"
                    params.append(model_name)
                if project:
                    query += " AND project = ?"
                    params.append(project)

                cursor.execute(query, params)
                row = cursor.fetchone()
                total_calls = row["total_calls"]
                succ_calls = row["successful_calls"]
                success_rate = (succ_calls / total_calls) if total_calls > 0 else 1.0

                return {
                    "total_calls": total_calls,
                    "successful_calls": succ_calls,
                    "success_rate": round(success_rate, 4),
                    "total_cost_usd": round(float(row["total_cost_usd"]), 6),
                    "total_prompt_tokens": int(row["total_prompt_tokens"]),
                    "total_completion_tokens": int(row["total_completion_tokens"]),
                    "total_tokens": int(row["total_prompt_tokens"])
                    + int(row["total_completion_tokens"]),
                }
            finally:
                if not self._is_memory:
                    conn.close()

    def get_cost_breakdown(
        self,
        group_by: str = "day",
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        col_map = {
            "agent": "agent_name",
            "model": "model_name",
            "project": "project",
            "day": "substr(timestamp, 1, 10)",
        }
        target_col = col_map.get(group_by.lower(), "substr(timestamp, 1, 10)")
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = f"""
                    SELECT
                        {target_col} as `group`,
                        COUNT(*) as calls,
                        COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                        COALESCE(SUM(cost_usd), 0.0) as cost_usd
                    FROM cost_records
                    WHERE 1=1
                """
                params: List[Any] = []
                if agent_name:
                    query += " AND agent_name = ?"
                    params.append(agent_name)
                if model_name:
                    query += " AND model_name = ?"
                    params.append(model_name)
                if project:
                    query += " AND project = ?"
                    params.append(project)

                query += f" GROUP BY {target_col} ORDER BY cost_usd DESC"
                cursor.execute(query, params)
                results = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "group": str(row["group"] or "unknown"),
                            "calls": int(row["calls"]),
                            "prompt_tokens": int(row["prompt_tokens"]),
                            "completion_tokens": int(row["completion_tokens"]),
                            "total_tokens": int(row["prompt_tokens"])
                            + int(row["completion_tokens"]),
                            "cost_usd": round(float(row["cost_usd"]), 6),
                        }
                    )
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 6. BENCHMARKS & EVALUATIONS ---

    def record_benchmark(
        self,
        model_name: str,
        task_type: str,
        success_rate: float,
        latency_ms: float,
        cost_per_success: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = metadata or {}
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO benchmarks (model_name, task_type, success_rate, latency_ms, cost_per_success, timestamp, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model_name,
                        task_type,
                        success_rate,
                        latency_ms,
                        cost_per_success,
                        now_iso,
                        json.dumps(meta),
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                if not self._is_memory:
                    conn.close()

    def get_benchmarks(self, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if task_type:
                    cursor.execute(
                        "SELECT * FROM benchmarks WHERE task_type = ? ORDER BY id DESC",
                        (task_type,),
                    )
                else:
                    cursor.execute("SELECT * FROM benchmarks ORDER BY id DESC")
                results = []
                for row in cursor.fetchall():
                    data = dict(row)
                    data["metadata"] = json.loads(data.get("metadata") or "{}")
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 7. SAFETY AUDIT LOGS ---

    def record_audit_log(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        decision: str,
        risk_level: str,
        risk_score: float,
        policy_id: Optional[str] = None,
        reason: Optional[str] = None,
        suggestion: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO audit_logs (
                        timestamp, tool_name, tool_args, decision, risk_level,
                        risk_score, policy_id, reason, suggestion, session_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_iso,
                        tool_name,
                        json.dumps(tool_args),
                        decision,
                        risk_level,
                        float(risk_score),
                        policy_id,
                        reason,
                        suggestion,
                        session_id,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                if not self._is_memory:
                    conn.close()

    def list_audit_logs(
        self,
        limit: int = 50,
        offset: int = 0,
        decision: Optional[str] = None,
        risk_level: Optional[str] = None,
        tool_name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT * FROM audit_logs"
                conditions = []
                params: List[Any] = []
                if decision:
                    conditions.append("decision = ?")
                    params.append(decision)
                if risk_level:
                    conditions.append("risk_level = ?")
                    params.append(risk_level)
                if tool_name:
                    conditions.append("tool_name LIKE ?")
                    params.append(f"%{tool_name}%")
                if session_id:
                    conditions.append("session_id = ?")
                    params.append(session_id)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " ORDER BY id DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(query, tuple(params))
                results = []
                for row in cursor.fetchall():
                    data = dict(row)
                    data["tool_args"] = json.loads(data.get("tool_args") or "{}")
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def count_audit_logs(
        self,
        decision: Optional[str] = None,
        risk_level: Optional[str] = None,
        tool_name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT COUNT(*) FROM audit_logs"
                conditions = []
                params: List[Any] = []
                if decision:
                    conditions.append("decision = ?")
                    params.append(decision)
                if risk_level:
                    conditions.append("risk_level = ?")
                    params.append(risk_level)
                if tool_name:
                    conditions.append("tool_name LIKE ?")
                    params.append(f"%{tool_name}%")
                if session_id:
                    conditions.append("session_id = ?")
                    params.append(session_id)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
                return row[0] if row else 0
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 8. SCHEDULED TASKS PERSISTENCE ---

    def create_scheduled_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                task_id = task.get("id") or f"task-{int(time.time() * 1000)}"
                created_at = task.get("created_at") or datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO scheduled_tasks (
                        id, name, description, cron, cron_human, agent_persona,
                        model, status, last_run, next_run, cost_per_run,
                        monthly_estimate, is_off_peak, notification_channel,
                        prompt, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        task["name"],
                        task.get("description", ""),
                        task["cron"],
                        task.get("cron_human", task["cron"]),
                        task.get("agent_persona", "Senior Engineer"),
                        task.get("model", "instant"),
                        task.get("status", "active"),
                        task.get("last_run"),
                        task.get("next_run", "Tonight, 02:00 AM (Off-peak)"),
                        float(task.get("cost_per_run", 0.0012)),
                        float(task.get("monthly_estimate", 0.036)),
                        1 if task.get("is_off_peak", True) else 0,
                        task.get("notification_channel", "slack"),
                        task["prompt"],
                        created_at,
                    ),
                )
                conn.commit()
                res = self.get_scheduled_task(task_id)
                return res if res is not None else task
            finally:
                if not self._is_memory:
                    conn.close()

    def get_scheduled_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["is_off_peak"] = bool(d.get("is_off_peak", 1))
                return d
            finally:
                if not self._is_memory:
                    conn.close()

    def list_scheduled_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM scheduled_tasks ORDER BY created_at ASC")
                rows = cursor.fetchall()
                if not rows:
                    # Seed default tasks if table is empty
                    default_tasks = [
                        {
                            "id": "task-1",
                            "name": "Daily Inbox Digest",
                            "description": "Summarizes critical emails, mentions, and urgent unread threads at 8 AM.",
                            "cron": "0 8 * * *",
                            "cron_human": "Every day at 8:00 AM",
                            "agent_persona": "Executive Drafter",
                            "model": "instant",
                            "status": "active",
                            "last_run": "Today, 08:00 AM",
                            "next_run": "Tomorrow, 08:00 AM",
                            "cost_per_run": 0.0008,
                            "monthly_estimate": 0.024,
                            "is_off_peak": False,
                            "notification_channel": "slack",
                            "prompt": "Summarize all high-priority unread emails and draft responses for urgent items.",
                            "created_at": "2026-03-01",
                        },
                        {
                            "id": "task-2",
                            "name": "Weekly Expense & Spend Audit",
                            "description": "Generates weekly financial reconciliation and token budget usage Sunday at 6 PM.",
                            "cron": "0 18 * * 0",
                            "cron_human": "Every Sunday at 6:00 PM",
                            "agent_persona": "Deep Researcher",
                            "model": "instant",
                            "status": "active",
                            "last_run": "Sun, Mar 8, 06:00 PM",
                            "next_run": "Sun, Mar 15, 06:00 PM",
                            "cost_per_run": 0.0025,
                            "monthly_estimate": 0.010,
                            "is_off_peak": False,
                            "notification_channel": "slack",
                            "prompt": "Compile weekly expenditure report and verify zero 90/9/1 budget breaches.",
                            "created_at": "2026-03-02",
                        },
                        {
                            "id": "task-3",
                            "name": "Off-Peak Security & AST Audit",
                            "description": "Runs zero-trust safety checks, AST sanitization, and dependency vulnerabilities overnight.",
                            "cron": "0 2 * * *",
                            "cron_human": "Every day at 2:00 AM (Off-peak)",
                            "agent_persona": "Security Auditor",
                            "model": "reasoning",
                            "status": "active",
                            "last_run": "Today, 02:00 AM",
                            "next_run": "Tomorrow, 02:00 AM (Off-peak)",
                            "cost_per_run": 0.0064,
                            "monthly_estimate": 0.192,
                            "is_off_peak": True,
                            "notification_channel": "webhook",
                            "prompt": "Inspect AST diffs, detect dangerous shell patterns, and review staged patches.",
                            "created_at": "2026-03-05",
                        },
                    ]
                    for t in default_tasks:
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO scheduled_tasks (
                                id, name, description, cron, cron_human, agent_persona,
                                model, status, last_run, next_run, cost_per_run,
                                monthly_estimate, is_off_peak, notification_channel,
                                prompt, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                t["id"],
                                t["name"],
                                t["description"],
                                t["cron"],
                                t["cron_human"],
                                t["agent_persona"],
                                t["model"],
                                t["status"],
                                t.get("last_run"),
                                t.get("next_run"),
                                t["cost_per_run"],
                                t["monthly_estimate"],
                                1 if t["is_off_peak"] else 0,
                                t["notification_channel"],
                                t["prompt"],
                                t["created_at"],
                            ),
                        )
                    conn.commit()
                    cursor.execute("SELECT * FROM scheduled_tasks ORDER BY created_at ASC")
                    rows = cursor.fetchall()

                result = []
                for row in rows:
                    d = dict(row)
                    d["is_off_peak"] = bool(d.get("is_off_peak", 1))
                    result.append(d)
                return result
            finally:
                if not self._is_memory:
                    conn.close()

    def update_scheduled_task_status(self, task_id: str, status: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE scheduled_tasks SET status = ? WHERE id = ?",
                    (status, task_id),
                )
                conn.commit()
                return self.get_scheduled_task(task_id)
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_scheduled_task(self, task_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 9. COLLABORATIVE ROOMS ---

    def create_room(self, room: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                room_id = room.get("room_id") or f"room_{uuid.uuid4().hex[:10]}"
                created_at = room.get("created_at") or now_iso
                updated_at = room.get("updated_at") or now_iso

                active_adapters = room.get("active_adapters") or []
                if not isinstance(active_adapters, str):
                    active_adapters = json.dumps(active_adapters)

                session_ids = room.get("session_ids") or []
                if not isinstance(session_ids, str):
                    session_ids = json.dumps(session_ids)

                meta = room.get("metadata") or {}
                if not isinstance(meta, str):
                    meta = json.dumps(meta)

                cursor.execute(
                    """
                    INSERT INTO collaborative_rooms (
                        room_id, project_id, name, description, topic, status,
                        policy_id, active_adapters, session_ids, created_at, updated_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        room_id,
                        room.get("project_id", "default"),
                        room.get("name", "Untitled Room"),
                        room.get("description", ""),
                        room.get("topic", ""),
                        room.get("status", "active"),
                        room.get("policy_id"),
                        active_adapters,
                        session_ids,
                        created_at,
                        updated_at,
                        meta,
                    ),
                )
                conn.commit()
                return self.get_room(room_id) or room
            finally:
                if not self._is_memory:
                    conn.close()

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM collaborative_rooms WHERE room_id = ?", (room_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["active_adapters"] = json.loads(data.get("active_adapters") or "[]")
                data["session_ids"] = json.loads(data.get("session_ids") or "[]")
                data["metadata"] = json.loads(data.get("metadata") or "{}")
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_rooms(
        self, project_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT * FROM collaborative_rooms"
                params: List[Any] = []
                clauses: List[str] = []

                if project_id:
                    clauses.append("project_id = ?")
                    params.append(project_id)
                if status:
                    clauses.append("status = ?")
                    params.append(status)

                if clauses:
                    query += " WHERE " + " AND ".join(clauses)
                query += " ORDER BY updated_at DESC"

                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    data["active_adapters"] = json.loads(data.get("active_adapters") or "[]")
                    data["session_ids"] = json.loads(data.get("session_ids") or "[]")
                    data["metadata"] = json.loads(data.get("metadata") or "{}")
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def update_room(self, room_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                set_clauses: List[str] = []
                params: List[Any] = []

                for k, v in updates.items():
                    if k in ("room_id", "created_at"):
                        continue
                    if k in ("active_adapters", "session_ids", "metadata") and not isinstance(
                        v, str
                    ):
                        v = json.dumps(v)
                    set_clauses.append(f"{k} = ?")
                    params.append(v)

                if not set_clauses:
                    return self.get_room(room_id)

                set_clauses.append("updated_at = ?")
                params.append(datetime.now(timezone.utc).isoformat())
                params.append(room_id)

                sql = f"UPDATE collaborative_rooms SET {', '.join(set_clauses)} WHERE room_id = ?"
                cursor.execute(sql, tuple(params))
                conn.commit()
                return self.get_room(room_id)
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_room(self, room_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM collaborative_rooms WHERE room_id = ?", (room_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def add_room_participant(self, participant: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                joined_at = participant.get("joined_at") or now_iso
                perms = participant.get("permissions") or []
                if not isinstance(perms, str):
                    perms = json.dumps(perms)
                meta = participant.get("metadata") or {}
                if not isinstance(meta, str):
                    meta = json.dumps(meta)

                cursor.execute(
                    """
                    INSERT INTO room_participants (
                        room_id, participant_id, name, role, participant_type, adapter_type,
                        permissions, joined_at, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(room_id, participant_id) DO UPDATE SET
                        name = excluded.name,
                        role = excluded.role,
                        participant_type = excluded.participant_type,
                        adapter_type = excluded.adapter_type,
                        permissions = excluded.permissions,
                        metadata = excluded.metadata
                    """,
                    (
                        participant["room_id"],
                        participant["participant_id"],
                        participant.get("name", participant["participant_id"]),
                        participant.get("role", "member"),
                        participant.get("participant_type", "human"),
                        participant.get("adapter_type"),
                        perms,
                        joined_at,
                        meta,
                    ),
                )
                conn.commit()
                res = self.get_room_participant(
                    participant["room_id"], participant["participant_id"]
                )
                return res if res is not None else participant
            finally:
                if not self._is_memory:
                    conn.close()

    def get_room_participant(self, room_id: str, participant_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM room_participants WHERE room_id = ? AND participant_id = ?",
                    (room_id, participant_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["permissions"] = json.loads(data.get("permissions") or "[]")
                data["metadata"] = json.loads(data.get("metadata") or "{}")
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_room_participants(self, room_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM room_participants WHERE room_id = ? ORDER BY joined_at ASC",
                    (room_id,),
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    data["permissions"] = json.loads(data.get("permissions") or "[]")
                    data["metadata"] = json.loads(data.get("metadata") or "{}")
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def update_room_participant(
        self, room_id: str, participant_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                set_clauses: List[str] = []
                params: List[Any] = []

                for k, v in updates.items():
                    if k in ("room_id", "participant_id", "joined_at"):
                        continue
                    if k in ("permissions", "metadata") and not isinstance(v, str):
                        v = json.dumps(v)
                    set_clauses.append(f"{k} = ?")
                    params.append(v)

                if not set_clauses:
                    return self.get_room_participant(room_id, participant_id)

                params.append(room_id)
                params.append(participant_id)
                sql = f"UPDATE room_participants SET {', '.join(set_clauses)} WHERE room_id = ? AND participant_id = ?"
                cursor.execute(sql, tuple(params))
                conn.commit()
                return self.get_room_participant(room_id, participant_id)
            finally:
                if not self._is_memory:
                    conn.close()

    def remove_room_participant(self, room_id: str, participant_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM room_participants WHERE room_id = ? AND participant_id = ?",
                    (room_id, participant_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def create_room_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                created_at = task.get("created_at") or now_iso
                updated_at = task.get("updated_at") or now_iso
                deps = task.get("dependencies") or []
                if not isinstance(deps, str):
                    deps = json.dumps(deps)
                meta = task.get("metadata") or {}
                if not isinstance(meta, str):
                    meta = json.dumps(meta)
                res = task.get("result")
                if res is not None and not isinstance(res, str):
                    res = json.dumps(res)

                cursor.execute(
                    """
                    INSERT INTO room_tasks (
                        task_id, room_id, title, description, status, priority,
                        assigned_to, assigned_adapter, parent_task_id, dependencies,
                        created_by, created_at, updated_at, result, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        status = excluded.status,
                        priority = excluded.priority,
                        assigned_to = excluded.assigned_to,
                        assigned_adapter = excluded.assigned_adapter,
                        parent_task_id = excluded.parent_task_id,
                        dependencies = excluded.dependencies,
                        updated_at = excluded.updated_at,
                        result = excluded.result,
                        metadata = excluded.metadata
                    """,
                    (
                        task["task_id"],
                        task["room_id"],
                        task["title"],
                        task.get("description", ""),
                        task.get("status", "pending"),
                        task.get("priority", "medium"),
                        task.get("assigned_to"),
                        task.get("assigned_adapter"),
                        task.get("parent_task_id"),
                        deps,
                        task.get("created_by", "human"),
                        created_at,
                        updated_at,
                        res,
                        meta,
                    ),
                )
                conn.commit()
                found = self.get_room_task(task["room_id"], task["task_id"])
                return found if found is not None else task
            finally:
                if not self._is_memory:
                    conn.close()

    def get_room_task(self, room_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM room_tasks WHERE room_id = ? AND task_id = ?",
                    (room_id, task_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["dependencies"] = json.loads(data.get("dependencies") or "[]")
                data["metadata"] = json.loads(data.get("metadata") or "{}")
                if data.get("result"):
                    try:
                        data["result"] = json.loads(data["result"])
                    except Exception:
                        pass
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_room_tasks(
        self,
        room_id: str,
        status: Optional[str] = None,
        assigned_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                sql = "SELECT * FROM room_tasks WHERE room_id = ?"
                params: List[Any] = [room_id]
                if status:
                    sql += " AND status = ?"
                    params.append(status)
                if assigned_to:
                    sql += " AND assigned_to = ?"
                    params.append(assigned_to)
                sql += " ORDER BY created_at ASC"

                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    data["dependencies"] = json.loads(data.get("dependencies") or "[]")
                    data["metadata"] = json.loads(data.get("metadata") or "{}")
                    if data.get("result"):
                        try:
                            data["result"] = json.loads(data["result"])
                        except Exception:
                            pass
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def update_room_task(
        self, room_id: str, task_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                set_clauses: List[str] = []
                params: List[Any] = []

                for k, v in updates.items():
                    if k in ("room_id", "task_id", "created_at", "created_by"):
                        continue
                    if (
                        k in ("dependencies", "metadata", "result")
                        and v is not None
                        and not isinstance(v, str)
                    ):
                        v = json.dumps(v)
                    set_clauses.append(f"{k} = ?")
                    params.append(v)

                if not set_clauses:
                    return self.get_room_task(room_id, task_id)

                set_clauses.append("updated_at = ?")
                params.append(datetime.now(timezone.utc).isoformat())
                params.append(room_id)
                params.append(task_id)

                sql = f"UPDATE room_tasks SET {', '.join(set_clauses)} WHERE room_id = ? AND task_id = ?"
                cursor.execute(sql, tuple(params))
                conn.commit()
                return self.get_room_task(room_id, task_id)
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_room_task(self, room_id: str, task_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM room_tasks WHERE room_id = ? AND task_id = ?",
                    (room_id, task_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 13. CANONICAL EXECUTIONS (R1.1) ---

    def create_execution(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        """Create and persist an execution record."""
        exec_id = execution["id"]
        session_id = execution.get("session_id")
        project_id = execution["project_id"]
        status = execution.get("status", "created")
        if isinstance(status, str):
            status_val = status
        else:
            status_val = getattr(status, "value", str(status))

        req = execution.get("request", {})
        if isinstance(req, str):
            req_json = req
        elif hasattr(req, "model_dump_json"):
            req_json = req.model_dump_json()
        else:
            req_json = json.dumps(req)

        routing_tier = execution.get("routing_tier")
        if routing_tier is not None and not isinstance(routing_tier, str):
            routing_tier = getattr(routing_tier, "value", str(routing_tier))

        created_at = execution.get("created_at") or datetime.now(timezone.utc).isoformat()

        if session_id:
            # Auto-ensure session exists if specified to satisfy relational foreign key
            if not self.get_session(session_id):
                try:
                    self.create_session(
                        session_id=session_id, user_id="default_user", title="Execution Session"
                    )
                except Exception:
                    pass

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO executions (
                        id, session_id, project_id, status, request_json,
                        provider, model, routing_tier, input_tokens, output_tokens,
                        total_cost_usd, is_cost_estimated, started_at, completed_at,
                        error_code, error_message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        exec_id,
                        session_id,
                        project_id,
                        status_val,
                        req_json,
                        execution.get("provider"),
                        execution.get("model"),
                        routing_tier,
                        execution.get("input_tokens", 0),
                        execution.get("output_tokens", 0),
                        float(execution.get("total_cost_usd", 0.0)),
                        1 if execution.get("is_cost_estimated") else 0,
                        execution.get("started_at"),
                        execution.get("completed_at"),
                        execution.get("error_code"),
                        execution.get("error_message"),
                        created_at,
                    ),
                )
                conn.commit()
                found = self.get_execution(exec_id)
                return found if found is not None else execution
            finally:
                if not self._is_memory:
                    conn.close()

    def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an execution record by primary key."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM executions WHERE id = ?", (execution_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["is_cost_estimated"] = bool(data.get("is_cost_estimated"))
                if data.get("request_json"):
                    try:
                        data["request"] = json.loads(data["request_json"])
                    except Exception:
                        data["request"] = data["request_json"]
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def update_execution(
        self, execution_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update an execution record."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                set_clauses: List[str] = []
                params: List[Any] = []

                valid_columns = {
                    "session_id",
                    "project_id",
                    "status",
                    "request_json",
                    "provider",
                    "model",
                    "routing_tier",
                    "input_tokens",
                    "output_tokens",
                    "total_cost_usd",
                    "is_cost_estimated",
                    "started_at",
                    "completed_at",
                    "error_code",
                    "error_message",
                }

                for k, v in updates.items():
                    if k in ("id", "created_at"):
                        continue
                    if k in ("request", "request_json"):
                        k = "request_json"
                        if not isinstance(v, str):
                            v = (
                                v.model_dump_json()
                                if hasattr(v, "model_dump_json")
                                else json.dumps(v)
                            )
                    if k not in valid_columns:
                        continue
                    if k == "status" and hasattr(v, "value"):
                        v = v.value
                    elif k == "routing_tier" and hasattr(v, "value"):
                        v = v.value
                    elif k == "is_cost_estimated":
                        v = 1 if v else 0
                    set_clauses.append(f"{k} = ?")
                    params.append(v)

                if not set_clauses:
                    return self.get_execution(execution_id)

                params.append(execution_id)
                sql = f"UPDATE executions SET {', '.join(set_clauses)} WHERE id = ?"
                cursor.execute(sql, tuple(params))
                conn.commit()
                return self.get_execution(execution_id)
            finally:
                if not self._is_memory:
                    conn.close()

    def list_executions(
        self,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List executions filtered by project, session, or status."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                sql = "SELECT * FROM executions WHERE 1=1"
                params: List[Any] = []
                if project_id:
                    sql += " AND project_id = ?"
                    params.append(project_id)
                if session_id:
                    sql += " AND session_id = ?"
                    params.append(session_id)
                if status:
                    if hasattr(status, "value"):
                        status = status.value
                    sql += " AND status = ?"
                    params.append(status)
                sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    data["is_cost_estimated"] = bool(data.get("is_cost_estimated"))
                    if data.get("request_json"):
                        try:
                            data["request"] = json.loads(data["request_json"])
                        except Exception:
                            data["request"] = data["request_json"]
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def record_execution_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Persist an append-only execution event."""
        evt_id = event["id"]
        execution_id = event["execution_id"]
        seq_num = event["sequence_num"]
        timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
        evt_type = event["event_type"]
        if hasattr(evt_type, "value"):
            evt_type = evt_type.value

        payload = event.get("payload") if "payload" in event else event.get("payload_json", {})
        if isinstance(payload, str):
            payload_json = payload
        elif hasattr(payload, "model_dump_json"):
            payload_json = payload.model_dump_json()
        else:
            payload_json = json.dumps(payload)

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO execution_events (id, execution_id, sequence_num, timestamp, event_type, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (evt_id, execution_id, seq_num, timestamp, evt_type, payload_json),
                )
                conn.commit()
                return event
            finally:
                if not self._is_memory:
                    conn.close()

    def get_execution_events(
        self, execution_id: str, after_sequence_num: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve ordered event stream for an execution by execution_id or request_id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                sql = "SELECT * FROM execution_events WHERE execution_id = ?"
                params: List[Any] = [execution_id]
                if after_sequence_num is not None:
                    sql += " AND sequence_num > ?"
                    params.append(after_sequence_num)
                sql += " ORDER BY sequence_num ASC"

                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    if data.get("payload_json"):
                        try:
                            data["payload"] = json.loads(data["payload_json"])
                        except Exception:
                            data["payload"] = data["payload_json"]
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 14. CANONICAL PROJECTS (R1.6) ---

    def create_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """Create and persist a canonical project."""
        proj_id = project.get("id") or f"proj_{uuid.uuid4().hex[:12]}"
        name = project["name"]
        description = project.get("description")
        root_path = project.get("root_path", f"/workspace/{proj_id}")
        instructions = project.get("instructions", "")
        settings = project.get("settings", {})
        if hasattr(settings, "model_dump"):
            settings = settings.model_dump()
        settings_json = json.dumps(settings) if isinstance(settings, dict) else str(settings)
        is_default = 1 if project.get("is_default") else 0
        now_iso = datetime.now(timezone.utc).isoformat()
        created_at = project.get("created_at") or now_iso
        updated_at = project.get("updated_at") or now_iso

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if is_default:
                    cursor.execute("UPDATE projects SET is_default = 0 WHERE is_default = 1")
                cursor.execute(
                    """
                    INSERT INTO projects (id, name, description, root_path, instructions, settings_json, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proj_id,
                        name,
                        description,
                        root_path,
                        instructions,
                        settings_json,
                        is_default,
                        created_at,
                        updated_at,
                    ),
                )
                conn.commit()
                found = self.get_project(proj_id)
                return found if found is not None else project
            finally:
                if not self._is_memory:
                    conn.close()

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a project by canonical primary key or resolve backward-compatible aliases."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if project_id in ("default", "proj_default"):
                    cursor.execute(
                        "SELECT * FROM projects WHERE is_default = 1 ORDER BY created_at ASC LIMIT 1"
                    )
                else:
                    cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["is_default"] = bool(data.get("is_default", 0))
                if data.get("settings_json"):
                    try:
                        data["settings"] = json.loads(data["settings_json"])
                    except Exception:
                        data["settings"] = {}
                else:
                    data["settings"] = {}
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def get_default_project(self) -> Optional[Dict[str, Any]]:
        """Retrieve the canonical default project (where is_default = 1)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM projects WHERE is_default = 1 ORDER BY created_at ASC LIMIT 1"
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["is_default"] = bool(data.get("is_default", 0))
                if data.get("settings_json"):
                    try:
                        data["settings"] = json.loads(data["settings_json"])
                    except Exception:
                        data["settings"] = {}
                else:
                    data["settings"] = {}
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update an existing project."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if updates.get("is_default"):
                    cursor.execute(
                        "UPDATE projects SET is_default = 0 WHERE is_default = 1 AND id != ?",
                        (project_id,),
                    )
                set_clauses: List[str] = []
                params: List[Any] = []

                for k, v in updates.items():
                    if k in ("id", "created_at"):
                        continue
                    if k == "settings":
                        k = "settings_json"
                        if hasattr(v, "model_dump"):
                            v = v.model_dump()
                        v = json.dumps(v) if isinstance(v, dict) else str(v)
                    elif k == "settings_json" and isinstance(v, dict):
                        v = json.dumps(v)
                    set_clauses.append(f"{k} = ?")
                    params.append(v)

                if "updated_at" not in updates:
                    set_clauses.append("updated_at = ?")
                    params.append(datetime.now(timezone.utc).isoformat())

                if not set_clauses:
                    return self.get_project(project_id)

                params.append(project_id)
                sql = f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = ?"
                cursor.execute(sql, tuple(params))
                conn.commit()
                return self.get_project(project_id)
            finally:
                if not self._is_memory:
                    conn.close()

    def list_projects(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List canonical projects with pagination."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM projects ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    if data.get("settings_json"):
                        try:
                            data["settings"] = json.loads(data["settings_json"])
                        except Exception:
                            data["settings"] = {}
                    else:
                        data["settings"] = {}
                    data["is_default"] = bool(data.get("is_default", 0))
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_project(self, project_id: str) -> bool:
        """Delete a project by primary key."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    # --- 15. CANONICAL ARTIFACTS (R1.10) ---

    def create_artifact(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a canonical artifact metadata record."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                lineage_str = (
                    json.dumps(artifact.get("lineage", {}))
                    if isinstance(artifact.get("lineage"), (dict, list))
                    else str(artifact.get("lineage", "{}"))
                )
                cursor.execute(
                    """
                    INSERT INTO artifacts (
                        id, project_id, execution_id, name, type, mime_type,
                        storage_kind, file_path, inline_content, sha256_hash,
                        size_bytes, status, lineage_json, created_by, created_at,
                        deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact["id"],
                        artifact["project_id"],
                        artifact["execution_id"],
                        artifact["name"],
                        artifact.get("type", "file"),
                        artifact.get("mime_type", "application/octet-stream"),
                        artifact.get("storage_kind", "filesystem"),
                        artifact.get("file_path"),
                        artifact.get("inline_content"),
                        artifact["sha256_hash"],
                        artifact["size_bytes"],
                        artifact.get("status", "ready"),
                        lineage_str,
                        artifact.get("created_by"),
                        artifact.get("created_at", datetime.now(timezone.utc).isoformat()),
                        artifact.get("deleted_at"),
                    ),
                )
                conn.commit()
                return artifact
            finally:
                if not self._is_memory:
                    conn.close()

    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve artifact metadata by primary key."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                if data.get("lineage_json"):
                    try:
                        data["lineage"] = json.loads(data["lineage_json"])
                    except Exception:
                        data["lineage"] = {}
                else:
                    data["lineage"] = {}
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_artifacts_by_execution(
        self, execution_id: str, include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        """List all artifacts produced or referenced by an execution."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if include_deleted:
                    sql = "SELECT * FROM artifacts WHERE execution_id = ? ORDER BY created_at ASC"
                else:
                    sql = (
                        "SELECT * FROM artifacts WHERE execution_id = ? AND status != 'deleted' "
                        "ORDER BY created_at ASC"
                    )
                cursor.execute(sql, (execution_id,))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    if data.get("lineage_json"):
                        try:
                            data["lineage"] = json.loads(data["lineage_json"])
                        except Exception:
                            data["lineage"] = {}
                    else:
                        data["lineage"] = {}
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def list_artifacts_by_project(
        self, project_id: str, include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        """List all artifacts belonging to a project."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if include_deleted:
                    sql = "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at DESC"
                else:
                    sql = (
                        "SELECT * FROM artifacts WHERE project_id = ? AND status != 'deleted' "
                        "ORDER BY created_at DESC"
                    )
                cursor.execute(sql, (project_id,))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    if data.get("lineage_json"):
                        try:
                            data["lineage"] = json.loads(data["lineage_json"])
                        except Exception:
                            data["lineage"] = {}
                    else:
                        data["lineage"] = {}
                    results.append(data)
                return results
            finally:
                if not self._is_memory:
                    conn.close()

    def update_artifact(
        self, artifact_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update artifact metadata."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                set_clauses = []
                params = []
                for key, val in updates.items():
                    if key == "lineage":
                        set_clauses.append("lineage_json = ?")
                        params.append(
                            json.dumps(val) if isinstance(val, (dict, list)) else str(val)
                        )
                    elif key in (
                        "name",
                        "type",
                        "mime_type",
                        "storage_kind",
                        "file_path",
                        "inline_content",
                        "sha256_hash",
                        "size_bytes",
                        "status",
                        "created_by",
                        "deleted_at",
                    ):
                        set_clauses.append(f"{key} = ?")
                        params.append(val)
                if not set_clauses:
                    return self.get_artifact(artifact_id)
                params.append(artifact_id)
                sql = f"UPDATE artifacts SET {', '.join(set_clauses)} WHERE id = ?"
                cursor.execute(sql, tuple(params))
                conn.commit()
                return self.get_artifact(artifact_id)
            finally:
                if not self._is_memory:
                    conn.close()

    def delete_artifact(self, artifact_id: str) -> bool:
        """Mark an artifact record as DELETED and clear payload references (tombstone preservation)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    UPDATE artifacts
                    SET status = 'deleted',
                        deleted_at = ?,
                        file_path = NULL,
                        inline_content = NULL
                    WHERE id = ? AND status != 'deleted'
                    """,
                    (now_iso, artifact_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
