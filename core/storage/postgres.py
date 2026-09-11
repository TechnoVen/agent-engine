"""PostgreSQL storage backend implementation for Agent Engine.

Provides enterprise multi-tenant cloud persistence using SQLAlchemy engine,
connection pooling, and tenant isolation as defined in ADR-003 and ADR-007.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core.storage.base import StorageBackend

DEFAULT_POSTGRES_URL = "postgresql://postgres:postgres@localhost:5432/agent_engine"


class PostgresBackend(StorageBackend):
    """Cloud PostgreSQL repository implementation supporting multi-tenancy."""

    def __init__(self, connection_url: Optional[str] = None):
        url = (
            connection_url
            or os.getenv("POSTGRES_URL")
            or os.getenv("DATABASE_URL")
            or DEFAULT_POSTGRES_URL
        )
        # If user provides postgresql:// without driver, normalize if needed
        self.connection_url = url
        self.engine: Engine = create_engine(self.connection_url, future=True)
        self.init_db()

    def init_db(self) -> None:
        """Create schema tables with PostgreSQL types and multi-tenant constraints."""
        is_pg = self.engine.dialect.name == "postgresql"
        serial_pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"

        with self.engine.begin() as conn:
            # Audit Patches
            conn.execute(
                text(f"""
                CREATE TABLE IF NOT EXISTS audit_patches (
                    id {serial_pk},
                    file_path TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL,
                    patch_type TEXT NOT NULL,
                    risk_level TEXT,
                    report TEXT,
                    original_code TEXT,
                    patched_code TEXT
                );
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_audit_patches_status ON audit_patches(status);
            """)
            )

            # Sessions
            conn.execute(
                text("""
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
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_sessions_user ON sessions(user_id);
            """)
            )

            # Users & Multi-Tenant accounts
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'developer',
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                );
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_users_tenant ON users(tenant_id);
            """)
            )

            # Guardrail Policies
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS policies (
                    policy_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    rules TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
            """)
            )

            # Cost Records
            conn.execute(
                text(f"""
                CREATE TABLE IF NOT EXISTS cost_records (
                    id {serial_pk},
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
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_cost_agent ON cost_records(agent_name);
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_cost_model ON cost_records(model_name);
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_cost_project ON cost_records(project);
            """)
            )

            # Benchmarks
            conn.execute(
                text(f"""
                CREATE TABLE IF NOT EXISTS benchmarks (
                    id {serial_pk},
                    model_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    success_rate REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    cost_per_success REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{{}}'
                );
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_benchmarks_task ON benchmarks(task_type);
            """)
            )

            # Safety Audit Logs
            conn.execute(
                text(f"""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id {serial_pk},
                    timestamp TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_args TEXT NOT NULL DEFAULT '{{}}',
                    decision TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    policy_id TEXT,
                    reason TEXT,
                    suggestion TEXT,
                    session_id TEXT
                );
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_audit_logs_decision ON audit_logs(decision);
            """)
            )
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_pg_audit_logs_timestamp ON audit_logs(timestamp);
            """)
            )

            # Ensure unified session columns exist if upgrading an older database
            for col_name, col_type in [
                ("title", "TEXT NOT NULL DEFAULT 'Untitled Session'"),
                ("tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
                ("channel", "TEXT NOT NULL DEFAULT 'web'"),
                ("status", "TEXT NOT NULL DEFAULT 'active'"),
                ("parent_session_id", "TEXT"),
                ("fork_point_message_id", "TEXT"),
                ("summary", "TEXT"),
            ]:
                try:
                    conn.execute(
                        text(
                            f"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS {col_name} {col_type};"
                        )
                    )
                except Exception:
                    pass
            for idx_name, col in [
                ("idx_pg_sessions_tenant", "tenant_id"),
                ("idx_pg_sessions_status", "status"),
                ("idx_pg_sessions_parent", "parent_session_id"),
            ]:
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON sessions({col});"))
                except Exception:
                    pass

    def close(self) -> None:
        """Dispose the engine connection pool."""
        self.engine.dispose()

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
        with self.engine.begin() as conn:
            cursor = conn.execute(
                text("""
                    INSERT INTO audit_patches (file_path, timestamp, status, patch_type, risk_level, report, original_code, patched_code)
                    VALUES (:file_path, :timestamp, :status, :patch_type, :risk_level, :report, :original_code, :patched_code)
                    RETURNING id
                """),
                {
                    "file_path": file_path,
                    "timestamp": now_iso,
                    "status": status,
                    "patch_type": patch_type,
                    "risk_level": risk_level,
                    "report": report,
                    "original_code": original_code,
                    "patched_code": patched_code,
                },
            )
            row = cursor.fetchone()
            if row:
                return int(row[0])
            row = conn.execute(text("SELECT MAX(id) as max_id FROM audit_patches")).fetchone()
            return int(row.max_id) if row and row.max_id else 1

    def get_staged_patches(self) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM audit_patches WHERE status = 'staged' ORDER BY id DESC")
            )
            return [dict(row._mapping) for row in result]

    def get_patch(self, patch_id: int) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM audit_patches WHERE id = :id"), {"id": patch_id}
            )
            row = result.fetchone()
            return dict(row._mapping) if row else None

    def apply_patch(self, patch_id: int) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("SELECT * FROM audit_patches WHERE id = :id"), {"id": patch_id}
            )
            row = result.fetchone()
            if not row or row._mapping["status"] != "staged":
                return False

            file_path = row._mapping["file_path"]
            patched_code = row._mapping["patched_code"]

            if file_path and patched_code is not None:
                os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(patched_code)

            conn.execute(
                text("UPDATE audit_patches SET status = 'applied' WHERE id = :id"),
                {"id": patch_id},
            )
            return True

    def reject_patch(self, patch_id: int) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("UPDATE audit_patches SET status = 'rejected' WHERE id = :id"),
                {"id": patch_id},
            )
            return result.rowcount > 0

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

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO sessions (
                        session_id, user_id, created_at, updated_at, metadata, messages,
                        title, tenant_id, channel, status, parent_session_id, fork_point_message_id, summary
                    )
                    VALUES (
                        :session_id, :user_id, :created_at, :updated_at, :metadata, :messages,
                        :title, :tenant_id, :channel, :status, :parent_session_id, :fork_point_message_id, :summary
                    )
                """),
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "metadata": json.dumps(meta),
                    "messages": json.dumps([]),
                    "title": resolved_title,
                    "tenant_id": resolved_tenant,
                    "channel": resolved_channel,
                    "status": resolved_status,
                    "parent_session_id": resolved_parent,
                    "fork_point_message_id": resolved_fork_point,
                    "summary": resolved_summary,
                },
            )
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

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM sessions WHERE session_id = :id"), {"id": session_id}
            )
            row = result.fetchone()
            if not row:
                return None
            data = dict(row._mapping)
            data["metadata"] = json.loads(data.get("metadata") or "{}")
            data["messages"] = json.loads(data.get("messages") or "[]")
            data.setdefault("title", data["metadata"].get("title", "Untitled Session"))
            data.setdefault("tenant_id", data["metadata"].get("tenant_id", "default"))
            data.setdefault("channel", data["metadata"].get("channel", "web"))
            data.setdefault("status", data["metadata"].get("status", "active"))
            return data

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            query = "SELECT * FROM sessions WHERE 1=1"
            params: Dict[str, Any] = {"limit": limit}
            if user_id:
                query += " AND user_id = :user_id"
                params["user_id"] = user_id
            if tenant_id:
                query += " AND tenant_id = :tenant_id"
                params["tenant_id"] = tenant_id
            if channel:
                query += " AND channel = :channel"
                params["channel"] = channel
            if status:
                query += " AND status = :status"
                params["status"] = status
            query += " ORDER BY updated_at DESC LIMIT :limit"

            result = conn.execute(text(query), params)
            results = []
            for row in result:
                item = dict(row._mapping)
                item["metadata"] = json.loads(item.get("metadata") or "{}")
                item["messages"] = json.loads(item.get("messages") or "[]")
                item.setdefault("title", item["metadata"].get("title", "Untitled Session"))
                item.setdefault("tenant_id", item["metadata"].get("tenant_id", "default"))
                item.setdefault("channel", item["metadata"].get("channel", "web"))
                item.setdefault("status", item["metadata"].get("status", "active"))
                results.append(item)
            return results

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
        with self.engine.begin() as conn:
            result = conn.execute(
                text("SELECT * FROM sessions WHERE session_id = :id"),
                {"id": session_id},
            )
            row = result.fetchone()
            if not row:
                return False

            current_row = dict(row._mapping)
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

            update_res = conn.execute(
                text("""
                    UPDATE sessions
                    SET updated_at = :updated_at, metadata = :metadata, messages = :messages,
                        title = :title, status = :status, summary = :summary
                    WHERE session_id = :id
                """),
                {
                    "updated_at": now_iso,
                    "metadata": json.dumps(current_meta),
                    "messages": json.dumps(current_msgs),
                    "title": new_title,
                    "status": new_status,
                    "summary": new_summary,
                    "id": session_id,
                },
            )
            return update_res.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM sessions WHERE session_id = :id"), {"id": session_id}
            )
            return result.rowcount > 0

    def search_sessions(
        self, query: str, user_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            sql = """
                SELECT * FROM sessions
                WHERE (title LIKE :query OR metadata LIKE :query OR messages LIKE :query)
            """
            params: Dict[str, Any] = {"query": f"%{query}%", "limit": limit}
            if user_id:
                sql += " AND user_id = :user_id"
                params["user_id"] = user_id
            sql += " ORDER BY updated_at DESC LIMIT :limit"

            result = conn.execute(text(sql), params)
            results = []
            for row in result:
                item = dict(row._mapping)
                item["metadata"] = json.loads(item.get("metadata") or "{}")
                item["messages"] = json.loads(item.get("messages") or "[]")
                results.append(item)
            return results

    def fork_session(
        self,
        session_id: str,
        new_session_id: str,
        fork_point_message_id: Optional[str] = None,
        title: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
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

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO sessions (
                        session_id, user_id, created_at, updated_at, metadata, messages,
                        title, tenant_id, channel, status, parent_session_id, fork_point_message_id, summary
                    )
                    VALUES (
                        :session_id, :user_id, :created_at, :updated_at, :metadata, :messages,
                        :title, :tenant_id, :channel, :status, :parent_session_id, :fork_point_message_id, :summary
                    )
                """),
                {
                    "session_id": new_session_id,
                    "user_id": target_user,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "metadata": json.dumps(meta),
                    "messages": json.dumps(forked_msgs),
                    "title": target_title,
                    "tenant_id": parent.get("tenant_id", "default"),
                    "channel": parent.get("channel", "web"),
                    "status": "active",
                    "parent_session_id": session_id,
                    "fork_point_message_id": fork_msg_id,
                    "summary": parent.get("summary"),
                },
            )
        return self.get_session(new_session_id)

    # --- 3. USERS & TENANTS ---

    def create_user(
        self,
        user_id: str,
        email: str,
        role: str = "developer",
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO users (user_id, email, role, tenant_id, created_at, is_active)
                    VALUES (:user_id, :email, :role, :tenant_id, :created_at, 1)
                """),
                {
                    "user_id": user_id,
                    "email": email,
                    "role": role,
                    "tenant_id": tenant_id,
                    "created_at": now_iso,
                },
            )
        return {
            "user_id": user_id,
            "email": email,
            "role": role,
            "tenant_id": tenant_id,
            "created_at": now_iso,
            "is_active": True,
        }

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM users WHERE user_id = :id"), {"id": user_id})
            row = result.fetchone()
            if not row:
                return None
            data = dict(row._mapping)
            data["is_active"] = bool(data["is_active"])
            return data

    def list_users(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            if tenant_id:
                result = conn.execute(
                    text("SELECT * FROM users WHERE tenant_id = :tenant_id ORDER BY user_id"),
                    {"tenant_id": tenant_id},
                )
            else:
                result = conn.execute(text("SELECT * FROM users ORDER BY user_id"))
            results = []
            for row in result:
                data = dict(row._mapping)
                data["is_active"] = bool(data["is_active"])
                results.append(data)
            return results

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
        with self.engine.begin() as conn:
            # Check existing
            check = conn.execute(
                text("SELECT policy_id FROM policies WHERE policy_id = :id"), {"id": policy_id}
            ).fetchone()
            if check:
                conn.execute(
                    text("""
                        UPDATE policies
                        SET name = :name, description = :description, rules = :rules, is_active = :is_active, updated_at = :updated_at
                        WHERE policy_id = :id
                    """),
                    {
                        "name": name,
                        "description": description,
                        "rules": json.dumps(rules),
                        "is_active": 1 if is_active else 0,
                        "updated_at": now_iso,
                        "id": policy_id,
                    },
                )
            else:
                conn.execute(
                    text("""
                        INSERT INTO policies (policy_id, name, description, rules, is_active, updated_at)
                        VALUES (:id, :name, :description, :rules, :is_active, :updated_at)
                    """),
                    {
                        "id": policy_id,
                        "name": name,
                        "description": description,
                        "rules": json.dumps(rules),
                        "is_active": 1 if is_active else 0,
                        "updated_at": now_iso,
                    },
                )
        return {
            "policy_id": policy_id,
            "name": name,
            "description": description,
            "rules": rules,
            "is_active": is_active,
            "updated_at": now_iso,
        }

    def get_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM policies WHERE policy_id = :id"), {"id": policy_id}
            )
            row = result.fetchone()
            if not row:
                return None
            data = dict(row._mapping)
            data["rules"] = json.loads(data.get("rules") or "{}")
            data["is_active"] = bool(data["is_active"])
            return data

    def list_policies(self, active_only: bool = False) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            if active_only:
                result = conn.execute(
                    text("SELECT * FROM policies WHERE is_active = 1 ORDER BY policy_id")
                )
            else:
                result = conn.execute(text("SELECT * FROM policies ORDER BY policy_id"))
            results = []
            for row in result:
                data = dict(row._mapping)
                data["rules"] = json.loads(data.get("rules") or "{}")
                data["is_active"] = bool(data["is_active"])
                results.append(data)
            return results

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
        with self.engine.begin() as conn:
            cursor = conn.execute(
                text("""
                    INSERT INTO cost_records (timestamp, agent_name, model_name, prompt_tokens, completion_tokens, cost_usd, task_id, success, project)
                    VALUES (:timestamp, :agent_name, :model_name, :prompt_tokens, :completion_tokens, :cost_usd, :task_id, :success, :project)
                    RETURNING id
                """),
                {
                    "timestamp": now_iso,
                    "agent_name": agent_name,
                    "model_name": model_name,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost_usd": cost_usd,
                    "task_id": task_id,
                    "success": 1 if success else 0,
                    "project": project,
                },
            )
            row = cursor.fetchone()
            if row:
                return int(row[0])
            row = conn.execute(text("SELECT MAX(id) as max_id FROM cost_records")).fetchone()
            return int(row.max_id) if row and row.max_id else 1

    def get_cost_summary(
        self,
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.engine.connect() as conn:
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
            params: Dict[str, Any] = {}
            if agent_name:
                query += " AND agent_name = :agent_name"
                params["agent_name"] = agent_name
            if model_name:
                query += " AND model_name = :model_name"
                params["model_name"] = model_name
            if project:
                query += " AND project = :project"
                params["project"] = project

            row = conn.execute(text(query), params).fetchone()
            if not row:
                return {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "success_rate": 1.0,
                    "total_cost_usd": 0.0,
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_tokens": 0,
                }
            total_calls = row._mapping["total_calls"]
            succ_calls = row._mapping["successful_calls"]
            success_rate = (succ_calls / total_calls) if total_calls > 0 else 1.0

            return {
                "total_calls": total_calls,
                "successful_calls": succ_calls,
                "success_rate": round(success_rate, 4),
                "total_cost_usd": round(float(row._mapping["total_cost_usd"]), 6),
                "total_prompt_tokens": int(row._mapping["total_prompt_tokens"]),
                "total_completion_tokens": int(row._mapping["total_completion_tokens"]),
                "total_tokens": int(row._mapping["total_prompt_tokens"])
                + int(row._mapping["total_completion_tokens"]),
            }

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
            "day": "SUBSTR(timestamp, 1, 10)",
        }
        target_col = col_map.get(group_by.lower(), "SUBSTR(timestamp, 1, 10)")
        with self.engine.connect() as conn:
            query = f"""
                SELECT
                    {target_col} AS "group",
                    COUNT(*) AS calls,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(cost_usd), 0.0) AS cost_usd
                FROM cost_records
                WHERE 1=1
            """
            params: Dict[str, Any] = {}
            if agent_name:
                query += " AND agent_name = :agent_name"
                params["agent_name"] = agent_name
            if model_name:
                query += " AND model_name = :model_name"
                params["model_name"] = model_name
            if project:
                query += " AND project = :project"
                params["project"] = project

            query += f' GROUP BY {target_col} ORDER BY "cost_usd" DESC'
            result = conn.execute(text(query), params)
            results = []
            for row in result:
                results.append(
                    {
                        "group": str(row._mapping["group"] or "unknown"),
                        "calls": int(row._mapping["calls"]),
                        "prompt_tokens": int(row._mapping["prompt_tokens"]),
                        "completion_tokens": int(row._mapping["completion_tokens"]),
                        "total_tokens": int(row._mapping["prompt_tokens"])
                        + int(row._mapping["completion_tokens"]),
                        "cost_usd": round(float(row._mapping["cost_usd"]), 6),
                    }
                )
            return results

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
        with self.engine.begin() as conn:
            cursor = conn.execute(
                text("""
                    INSERT INTO benchmarks (model_name, task_type, success_rate, latency_ms, cost_per_success, timestamp, metadata)
                    VALUES (:model_name, :task_type, :success_rate, :latency_ms, :cost_per_success, :timestamp, :metadata)
                    RETURNING id
                """),
                {
                    "model_name": model_name,
                    "task_type": task_type,
                    "success_rate": success_rate,
                    "latency_ms": latency_ms,
                    "cost_per_success": cost_per_success,
                    "timestamp": now_iso,
                    "metadata": json.dumps(meta),
                },
            )
            row = cursor.fetchone()
            if row:
                return int(row[0])
            row = conn.execute(text("SELECT MAX(id) as max_id FROM benchmarks")).fetchone()
            return int(row.max_id) if row and row.max_id else 1

    def get_benchmarks(self, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            if task_type:
                result = conn.execute(
                    text("SELECT * FROM benchmarks WHERE task_type = :task_type ORDER BY id DESC"),
                    {"task_type": task_type},
                )
            else:
                result = conn.execute(text("SELECT * FROM benchmarks ORDER BY id DESC"))
            results = []
            for row in result:
                data = dict(row._mapping)
                data["metadata"] = json.loads(data.get("metadata") or "{}")
                results.append(data)
            return results

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
        with self.engine.begin() as conn:
            stmt = text(
                """
                INSERT INTO audit_logs (
                    timestamp, tool_name, tool_args, decision, risk_level,
                    risk_score, policy_id, reason, suggestion, session_id
                )
                VALUES (
                    :timestamp, :tool_name, :tool_args, :decision, :risk_level,
                    :risk_score, :policy_id, :reason, :suggestion, :session_id
                )
                """
            )
            conn.execute(
                stmt,
                {
                    "timestamp": now_iso,
                    "tool_name": tool_name,
                    "tool_args": json.dumps(tool_args),
                    "decision": decision,
                    "risk_level": risk_level,
                    "risk_score": float(risk_score),
                    "policy_id": policy_id,
                    "reason": reason,
                    "suggestion": suggestion,
                    "session_id": session_id,
                },
            )
            row = conn.execute(text("SELECT MAX(id) as max_id FROM audit_logs")).fetchone()
            return int(row.max_id) if row and row.max_id else 1

    def list_audit_logs(
        self,
        limit: int = 50,
        decision: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            query = "SELECT * FROM audit_logs"
            conditions = []
            params: Dict[str, Any] = {"limit": limit}
            if decision:
                conditions.append("decision = :decision")
                params["decision"] = decision
            if session_id:
                conditions.append("session_id = :session_id")
                params["session_id"] = session_id
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY id DESC LIMIT :limit"

            result = conn.execute(text(query), params)
            results = []
            for row in result:
                data = dict(row._mapping)
                data["tool_args"] = json.loads(data.get("tool_args") or "{}")
                results.append(data)
            return results
