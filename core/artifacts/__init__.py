"""Canonical Artifacts Package (Task R1.10).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md (Section 2.9 & Section 3), docs/ROADMAP.md (R1.10)
"""

from core.artifacts.models import (
    Artifact,
    ArtifactStatus,
    ArtifactStorageKind,
    ArtifactType,
    generate_artifact_id,
)
from core.artifacts.service import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactSecurityError,
    ArtifactService,
)
from core.artifacts.storage import (
    ArtifactPayloadStore,
    LocalFilesystemPayloadStore,
)

__all__ = [
    "Artifact",
    "ArtifactStatus",
    "ArtifactStorageKind",
    "ArtifactType",
    "ArtifactService",
    "ArtifactSecurityError",
    "ArtifactNotFoundError",
    "ArtifactIntegrityError",
    "ArtifactPayloadStore",
    "LocalFilesystemPayloadStore",
    "generate_artifact_id",
]
