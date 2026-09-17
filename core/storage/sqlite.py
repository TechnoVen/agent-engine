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
                """)
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
