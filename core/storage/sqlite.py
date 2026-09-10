"""SQLite storage backend implementation for Agent Engine.

Provides zero-setup, local-first single-user persistence with WAL mode,
transaction safety, and thread safety.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.storage.base import StorageBackend

DEFAULT_SQLITE_PATH = "/home/nadir/agent_engine/data/agent_engine.db"


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
                        messages TEXT NOT NULL DEFAULT '[]'
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
                        success INTEGER NOT NULL DEFAULT 1
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
                """)
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

                if file_path and patched_code is not None:
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
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = metadata or {}
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO sessions (session_id, user_id, created_at, updated_at, metadata, messages)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, user_id, now_iso, now_iso, json.dumps(meta), json.dumps([])),
                )
                conn.commit()
                return {
                    "session_id": session_id,
                    "user_id": user_id,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "metadata": meta,
                    "messages": [],
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
                return data
            finally:
                if not self._is_memory:
                    conn.close()

    def list_sessions(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if user_id:
                    cursor.execute(
                        "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                        (user_id, limit),
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
                    )
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

    def update_session(
        self,
        session_id: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT metadata, messages FROM sessions WHERE session_id = ?", (session_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return False

                current_meta = json.loads(row["metadata"] or "{}")
                current_msgs = json.loads(row["messages"] or "[]")

                if metadata is not None:
                    current_meta.update(metadata)
                if messages is not None:
                    current_msgs = messages

                cursor.execute(
                    """
                    UPDATE sessions
                    SET updated_at = ?, metadata = ?, messages = ?
                    WHERE session_id = ?
                    """,
                    (now_iso, json.dumps(current_meta), json.dumps(current_msgs), session_id),
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
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO cost_records (timestamp, agent_name, model_name, prompt_tokens, completion_tokens, cost_usd, task_id, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                if not self._is_memory:
                    conn.close()

    def get_cost_summary(
        self, agent_name: Optional[str] = None, model_name: Optional[str] = None
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
