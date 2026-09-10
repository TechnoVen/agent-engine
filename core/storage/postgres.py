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
                    messages TEXT NOT NULL DEFAULT '[]'
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
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = metadata or {}
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO sessions (session_id, user_id, created_at, updated_at, metadata, messages)
                    VALUES (:session_id, :user_id, :created_at, :updated_at, :metadata, :messages)
                """),
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "metadata": json.dumps(meta),
                    "messages": json.dumps([]),
                },
            )
        return {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "metadata": meta,
            "messages": [],
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
            return data

    def list_sessions(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            if user_id:
                result = conn.execute(
                    text(
                        "SELECT * FROM sessions WHERE user_id = :user_id ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    {"user_id": user_id, "limit": limit},
                )
            else:
                result = conn.execute(
                    text("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT :limit"),
                    {"limit": limit},
                )
            results = []
            for row in result:
                item = dict(row._mapping)
                item["metadata"] = json.loads(item.get("metadata") or "{}")
                item["messages"] = json.loads(item.get("messages") or "[]")
                results.append(item)
            return results

    def update_session(
        self,
        session_id: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            result = conn.execute(
                text("SELECT metadata, messages FROM sessions WHERE session_id = :id"),
                {"id": session_id},
            )
            row = result.fetchone()
            if not row:
                return False

            current_meta = json.loads(row._mapping["metadata"] or "{}")
            current_msgs = json.loads(row._mapping["messages"] or "[]")

            if metadata is not None:
                current_meta.update(metadata)
            if messages is not None:
                current_msgs = messages

            update_res = conn.execute(
                text("""
                    UPDATE sessions
                    SET updated_at = :updated_at, metadata = :metadata, messages = :messages
                    WHERE session_id = :id
                """),
                {
                    "updated_at": now_iso,
                    "metadata": json.dumps(current_meta),
                    "messages": json.dumps(current_msgs),
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
