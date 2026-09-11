"""Base storage interface and abstract repository protocol for Agent Engine.

Supports both local-first (SQLite) and cloud enterprise (PostgreSQL) backends
as defined in ADR-003 and resolving Conflict C3.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class PatchRecord:
    id: Optional[int]
    file_path: str
    timestamp: str
    status: str
    patch_type: str
    risk_level: Optional[str] = None
    report: Optional[str] = None
    original_code: Optional[str] = None
    patched_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "timestamp": self.timestamp,
            "status": self.status,
            "patch_type": self.patch_type,
            "risk_level": self.risk_level,
            "report": self.report,
            "original_code": self.original_code,
            "patched_code": self.patched_code,
        }


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    title: str = "Untitled Session"
    tenant_id: str = "default"
    channel: str = "web"
    status: str = "active"
    parent_session_id: Optional[str] = None
    fork_point_message_id: Optional[str] = None
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "messages": self.messages,
            "title": self.title,
            "tenant_id": self.tenant_id,
            "channel": self.channel,
            "status": self.status,
            "parent_session_id": self.parent_session_id,
            "fork_point_message_id": self.fork_point_message_id,
            "summary": self.summary,
        }


@dataclass
class UserRecord:
    user_id: str
    email: str
    role: str = "developer"
    tenant_id: str = "default"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


@dataclass
class PolicyRecord:
    policy_id: str
    name: str
    rules: Dict[str, Any]
    description: Optional[str] = None
    is_active: bool = True
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "rules": self.rules,
            "description": self.description,
            "is_active": self.is_active,
            "updated_at": self.updated_at,
        }


@dataclass
class CostRecord:
    id: Optional[int]
    timestamp: str
    agent_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    task_id: Optional[str] = None
    success: bool = True
    project: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent_name": self.agent_name,
            "model_name": self.model_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "task_id": self.task_id,
            "success": self.success,
            "project": self.project,
        }


@dataclass
class BenchmarkRecord:
    id: Optional[int]
    model_name: str
    task_type: str
    success_rate: float
    latency_ms: float
    cost_per_success: float
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model_name": self.model_name,
            "task_type": self.task_type,
            "success_rate": self.success_rate,
            "latency_ms": self.latency_ms,
            "cost_per_success": self.cost_per_success,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class AuditLogRecord:
    id: Optional[int]
    timestamp: str
    tool_name: str
    tool_args: Dict[str, Any]
    decision: str  # allow, block, stage, warn
    risk_level: str  # low, medium, high, critical
    risk_score: float
    policy_id: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "decision": self.decision,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "policy_id": self.policy_id,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "session_id": self.session_id,
        }


class StorageBackend(ABC):
    """Abstract base repository for all Agent Engine persistent state."""

    @abstractmethod
    def init_db(self) -> None:
        """Initialize required schema tables and indexes."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close database connections and cleanup resources."""
        pass

    # --- 1. AUDIT & STAGED PATCHES ---
    @abstractmethod
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
        """Persist a staged code patch and return its unique ID."""
        pass

    @abstractmethod
    def get_staged_patches(self) -> List[Dict[str, Any]]:
        """Retrieve all currently staged patches ordered newest first."""
        pass

    @abstractmethod
    def get_patch(self, patch_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a specific patch by primary key."""
        pass

    @abstractmethod
    def apply_patch(self, patch_id: int) -> bool:
        """Apply patch to disk and update database record status to applied."""
        pass

    @abstractmethod
    def reject_patch(self, patch_id: int) -> bool:
        """Mark patch as rejected in the database."""
        pass

    # --- 2. SESSIONS ---
    @abstractmethod
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
        """Create a new conversational / agent session."""
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a session by ID."""
        pass

    @abstractmethod
    def list_sessions(
        self,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List sessions optionally filtered by user ID, tenant, channel, or status."""
        pass

    @abstractmethod
    def update_session(
        self,
        session_id: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        status: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> bool:
        """Update messages, metadata, or status in a session."""
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        """Remove a session."""
        pass

    def search_sessions(
        self, query: str, user_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search sessions by keyword matching in title, metadata, or messages."""
        return []

    def fork_session(
        self,
        session_id: str,
        new_session_id: str,
        fork_point_message_id: Optional[str] = None,
        title: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fork an existing session into a new branch."""
        return None

    # --- 3. USERS & TENANTS ---
    @abstractmethod
    def create_user(
        self,
        user_id: str,
        email: str,
        role: str = "developer",
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        """Create or register a user."""
        pass

    @abstractmethod
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a user by ID."""
        pass

    @abstractmethod
    def list_users(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List users, optionally filtered by tenant."""
        pass

    # --- 4. POLICIES ---
    @abstractmethod
    def save_policy(
        self,
        policy_id: str,
        name: str,
        rules: Dict[str, Any],
        description: Optional[str] = None,
        is_active: bool = True,
    ) -> Dict[str, Any]:
        """Create or update a policy."""
        pass

    @abstractmethod
    def get_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a policy by ID."""
        pass

    @abstractmethod
    def list_policies(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """List all policies."""
        pass

    # --- 5. FINANCE & COST RECORDS ---
    @abstractmethod
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
        """Record an LLM / step execution cost entry."""
        pass

    @abstractmethod
    def get_cost_summary(
        self,
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregated cost, token counts, and request metrics."""
        pass

    @abstractmethod
    def get_cost_breakdown(
        self,
        group_by: str = "day",
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get aggregated cost breakdown grouped by agent, model, project, or day."""
        pass

    # --- 6. BENCHMARKS & EVALUATIONS ---
    @abstractmethod
    def record_benchmark(
        self,
        model_name: str,
        task_type: str,
        success_rate: float,
        latency_ms: float,
        cost_per_success: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record a model evaluation benchmark."""
        pass

    @abstractmethod
    def get_benchmarks(self, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve benchmarks, optionally filtered by task type."""
        pass

    # --- 7. SAFETY AUDIT LOGS ---
    @abstractmethod
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
        """Record a safety audit log entry for a tool invocation."""
        pass

    @abstractmethod
    def list_audit_logs(
        self,
        limit: int = 50,
        decision: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent safety audit logs."""
        pass


# Backward-compatible and semantic alias
StorageRepository = StorageBackend
