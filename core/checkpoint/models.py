"""core/checkpoint/models.py

Data models, enums, exceptions, and audit records for the Checkpoint and Rollback Service.
Part of Milestone R2 Task R2.11.

Invariants (CTO Review Sections 11-24):
1. Immutable Checkpoint Evidence: A checkpoint records immutable pre-execution state,
   expected post-execution state where known, recovery references, and integrity hashes.
2. Safe Rollback: Rollback is a consequential operation requiring authenticated actor,
   exact approval binding, and pre-restore conflict inspection.
3. Never Rollback Over Newer Human State Silently: If current state has diverged from
   expected post-state, rollback halts with ROLLBACK_CONFLICT and does not overwrite.
4. Audit-Safe Ledger: Stores references, status, and cryptographic hashes, never full
   file contents, database rows, or secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Any, Dict, List, Optional
import uuid


class CheckpointResourceType(str, Enum):
    """Supported checkpoint resource types."""

    FILE = "file"
    GIT = "git"
    DATABASE = "database"
    CONFIG = "config"


class CheckpointStatus(str, Enum):
    """Lifecycle states of a checkpoint."""

    CREATING = "creating"
    READY = "ready"
    RESTORING = "restoring"
    RESTORED = "restored"
    CONFLICT = "conflict"
    FAILED = "failed"


class RestoreStatus(str, Enum):
    """Overall outcome status of a restore operation."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CONFLICT = "conflict"


class ResourceRestoreStatus(str, Enum):
    """Per-resource outcome status during restore."""

    RESTORED = "restored"
    CONFLICT = "conflict"
    FAILED = "failed"
    SKIPPED = "skipped"


class CheckpointError(Exception):
    """Base exception for checkpoint operations."""

    pass


class CheckpointCreationError(CheckpointError):
    """Raised when a checkpoint cannot be durably created before mutation."""

    pass


class CheckpointNotFoundError(CheckpointError):
    """Raised when the requested checkpoint does not exist."""

    pass


class RollbackConflictError(CheckpointError):
    """Raised when live resource has diverged with newer human edits."""

    pass


class UnsupportedDatabaseBackendError(CheckpointError):
    """Raised when attempting checkpoint on an unsupported database type."""

    pass


class RestoreVerificationError(CheckpointError):
    """Raised when a restored resource fails post-restore integrity check."""

    pass


def generate_checkpoint_id() -> str:
    """Generate unique checkpoint identifier."""
    return f"chk-{uuid.uuid4().hex[:12]}"


def generate_restore_id() -> str:
    """Generate unique restore identifier."""
    return f"rst-{uuid.uuid4().hex[:12]}"


def compute_rollback_approval_digest(
    project_id: str,
    checkpoint_id: str,
    restore_id: str,
    resource_ids: List[str],
) -> str:
    """Compute cryptographic digest binding exact rollback parameters."""
    sorted_res = ",".join(sorted(resource_ids))
    raw = f"rollback_approval:{project_id}:{checkpoint_id}:{restore_id}:{sorted_res}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class CheckpointResource:
    """Snapshot evidence for a single resource within a checkpoint."""

    resource_id: str
    resource_type: CheckpointResourceType
    canonical_relative_path: Optional[str] = None
    pre_state_hash: Optional[str] = None
    expected_post_state_hash: Optional[str] = None
    exists_pre: bool = True
    exists_post: bool = True
    storage_reference: Optional[str] = None
    file_mode: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type.value,
            "canonical_relative_path": self.canonical_relative_path,
            "pre_state_hash": self.pre_state_hash,
            "expected_post_state_hash": self.expected_post_state_hash,
            "exists_pre": self.exists_pre,
            "exists_post": self.exists_post,
            "storage_reference": self.storage_reference,
            "file_mode": self.file_mode,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CheckpointResource:
        return cls(
            resource_id=data["resource_id"],
            resource_type=CheckpointResourceType(data["resource_type"]),
            canonical_relative_path=data.get("canonical_relative_path"),
            pre_state_hash=data.get("pre_state_hash"),
            expected_post_state_hash=data.get("expected_post_state_hash"),
            exists_pre=data.get("exists_pre", True),
            exists_post=data.get("exists_post", True),
            storage_reference=data.get("storage_reference"),
            file_mode=data.get("file_mode"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Checkpoint:
    """Durable snapshot container capturing resources before a consequential execution."""

    checkpoint_id: str
    project_id: str
    execution_id: str
    description: str = ""
    status: CheckpointStatus = CheckpointStatus.CREATING
    resources: List[CheckpointResource] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "project_id": self.project_id,
            "execution_id": self.execution_id,
            "description": self.description,
            "status": self.status.value,
            "resources": [r.to_dict() for r in self.resources],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            project_id=data["project_id"],
            execution_id=data["execution_id"],
            description=data.get("description", ""),
            status=CheckpointStatus(data.get("status", CheckpointStatus.CREATING.value)),
            resources=[CheckpointResource.from_dict(r) for r in data.get("resources", [])],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class ResourceRestoreResult:
    """Outcome of attempting to restore a single resource."""

    resource_id: str
    resource_type: CheckpointResourceType
    status: ResourceRestoreStatus
    message: str = ""
    verified: bool = False
    initial_hash: Optional[str] = None
    restored_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type.value,
            "status": self.status.value,
            "message": self.message,
            "verified": self.verified,
            "initial_hash": self.initial_hash,
            "restored_hash": self.restored_hash,
        }


@dataclass
class RestorePlan:
    """Declared plan for rolling back a set of resources within a checkpoint."""

    restore_id: str
    checkpoint_id: str
    project_id: str
    resource_ids: List[str] = field(default_factory=list)
    force: bool = False
    approval_id: Optional[str] = None
    approval_digest: Optional[str] = None


@dataclass
class RestoreResult:
    """Outcome of executing a RestorePlan."""

    restore_id: str
    checkpoint_id: str
    project_id: str
    status: RestoreStatus
    resource_results: Dict[str, ResourceRestoreResult] = field(default_factory=dict)
    duration_seconds: float = 0.0
    message: str = ""

    @property
    def is_success(self) -> bool:
        return self.status == RestoreStatus.COMPLETED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restore_id": self.restore_id,
            "checkpoint_id": self.checkpoint_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "resource_results": {k: v.to_dict() for k, v in self.resource_results.items()},
            "duration_seconds": self.duration_seconds,
            "message": self.message,
        }


@dataclass
class CheckpointExecutionRecord:
    """Audit ledger record for checkpoint creation and restore operations (CTO Review Section 23)."""

    checkpoint_id: str
    project_id: str
    execution_id: str
    action: str  # "create" or "restore"
    status: str
    resource_count: int
    resource_types: List[str]
    approval_id: Optional[str] = None
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "project_id": self.project_id,
            "execution_id": self.execution_id,
            "action": self.action,
            "status": self.status,
            "resource_count": self.resource_count,
            "resource_types": self.resource_types,
            "approval_id": self.approval_id,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
        }
