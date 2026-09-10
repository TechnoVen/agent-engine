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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "messages": self.messages,
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
    ) -> Dict[str, Any]:
        """Create a new conversational / agent session."""
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a session by ID."""
        pass

    @abstractmethod
    def list_sessions(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List sessions optionally filtered by user ID."""
        pass

    @abstractmethod
    def update_session(
        self,
        session_id: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update messages or metadata in a session."""
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        """Remove a session."""
        pass

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
    ) -> int:
        """Record an LLM / step execution cost entry."""
        pass

    @abstractmethod
    def get_cost_summary(
        self, agent_name: Optional[str] = None, model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregated cost, token counts, and request metrics."""
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
