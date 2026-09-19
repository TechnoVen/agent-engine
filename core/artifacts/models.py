"""Canonical Artifact Domain Models (Task R1.10).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md (Section 2.9 & Section 3), docs/ROADMAP.md (R1.10)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


def generate_artifact_id() -> str:
    """Generate canonical artifact ID with 'art_' prefix and 12 hex characters."""
    return f"art_{uuid.uuid4().hex[:12]}"


def current_timestamp_iso() -> str:
    """Return UTC ISO 8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


class ArtifactType(str, Enum):
    """Compact general classification for artifacts."""

    TEXT = "text"
    FILE = "file"
    DOCUMENT = "document"
    DATA = "data"
    CODE = "code"
    IMAGE = "image"
    LOG = "log"
    PATCH = "patch"
    OTHER = "other"


class ArtifactStatus(str, Enum):
    """Lifecycle status of an artifact."""

    CREATED = "created"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    DELETED = "deleted"


class ArtifactStorageKind(str, Enum):
    """Storage mechanism classification for artifact payload."""

    INLINE = "inline"
    FILESYSTEM = "filesystem"


class Artifact(BaseModel):
    """Durable, addressable output produced, consumed, or modified by an execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=generate_artifact_id)
    project_id: str
    execution_id: str
    name: str
    type: ArtifactType = ArtifactType.FILE
    mime_type: str = "application/octet-stream"
    storage_kind: ArtifactStorageKind = ArtifactStorageKind.FILESYSTEM
    file_path: Optional[str] = None
    inline_content: Optional[str] = None
    sha256_hash: str
    size_bytes: int
    status: ArtifactStatus = ArtifactStatus.READY
    lineage: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: str = Field(default_factory=current_timestamp_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Convert artifact model to dictionary format for persistence and API transport."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "execution_id": self.execution_id,
            "name": self.name,
            "type": self.type.value if isinstance(self.type, ArtifactType) else str(self.type),
            "mime_type": self.mime_type,
            "storage_kind": (
                self.storage_kind.value
                if isinstance(self.storage_kind, ArtifactStorageKind)
                else str(self.storage_kind)
            ),
            "file_path": self.file_path,
            "inline_content": self.inline_content,
            "sha256_hash": self.sha256_hash,
            "size_bytes": self.size_bytes,
            "status": (
                self.status.value if isinstance(self.status, ArtifactStatus) else str(self.status)
            ),
            "lineage": self.lineage,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }
