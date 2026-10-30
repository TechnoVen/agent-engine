"""Canonical Artifact Service (Task R1.10).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md (Section 2.9 & Section 3), docs/ROADMAP.md (R1.10)
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from core.artifacts.models import (
    Artifact,
    ArtifactStatus,
    ArtifactStorageKind,
    ArtifactType,
    current_timestamp_iso,
    generate_artifact_id,
)
from core.artifacts.storage import (
    ArtifactPayloadStore,
    ArtifactSecurityError,
    LocalFilesystemPayloadStore,
)
from core.storage.base import StorageBackend

logger = logging.getLogger("agent_engine.artifacts.service")

DEFAULT_INLINE_THRESHOLD_BYTES = 8192  # 8 KB threshold for inline storage


class ArtifactNotFoundError(Exception):
    """Raised when an artifact cannot be found or has been deleted."""

    pass


class ArtifactIntegrityError(Exception):
    """Raised when an artifact payload does not match its recorded SHA-256 hash or size."""

    pass


class ArtifactService:
    """Canonical service managing artifact creation, retrieval, integrity, and project-scope boundaries.

    Trust boundary note:
    Stage R1 enforces project-scope integrity (preventing accidental cross-project data access or path escape).
    Stage R2 will introduce authenticated actor identity and RBAC project authorization.
    TODO(R2): Integrate authenticated actor identity in Stage R2 project authorization.
    """

    def __init__(
        self,
        storage: StorageBackend,
        base_artifacts_dir: Optional[str] = None,
        payload_store: Optional[ArtifactPayloadStore] = None,
        inline_threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES,
    ):
        self.storage = storage
        if payload_store:
            self.payload_store = payload_store
            self.base_artifacts_dir = getattr(payload_store, "base_dir", "")
        else:
            self.payload_store = LocalFilesystemPayloadStore(base_dir=base_artifacts_dir)
            self.base_artifacts_dir = self.payload_store.base_dir
        self.inline_threshold_bytes = inline_threshold_bytes

    def _resolve_safe_project_dir(self, project_id: str) -> str:
        """Resolve and validate the base storage directory for a specific project."""
        if hasattr(self.payload_store, "resolve_safe_project_dir"):
            return self.payload_store.resolve_safe_project_dir(project_id)
        if not project_id or ".." in project_id or "/" in project_id or "\\" in project_id:
            raise ArtifactSecurityError(f"Invalid project_id for artifact storage: '{project_id}'")
        return project_id

    def create_artifact(
        self,
        project_id: str,
        execution_id: str,
        name: str,
        content: bytes | str,
        type: ArtifactType | str = ArtifactType.FILE,
        mime_type: str = "application/octet-stream",
        storage_kind: Optional[ArtifactStorageKind | str] = None,
        lineage: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
        status: ArtifactStatus | str = ArtifactStatus.READY,
    ) -> Artifact:
        """Create, persist payload, compute SHA-256 digest, and store metadata for an artifact."""
        if not project_id:
            raise ValueError("project_id is required to create an artifact")
        if not execution_id:
            raise ValueError("execution_id is required to create an artifact")

        # Validate project boundary upfront
        self._resolve_safe_project_dir(project_id)

        # Encode content to bytes
        if isinstance(content, str):
            payload_bytes = content.encode("utf-8")
            is_text = True
        else:
            payload_bytes = content
            is_text = False

        size_bytes = len(payload_bytes)
        sha256_hash = hashlib.sha256(payload_bytes).hexdigest()
        artifact_id = generate_artifact_id()

        # Parse type and status enums
        parsed_type = type if isinstance(type, ArtifactType) else ArtifactType(str(type).lower())
        parsed_status = (
            status if isinstance(status, ArtifactStatus) else ArtifactStatus(str(status).lower())
        )

        # Determine storage mechanism
        if storage_kind is not None:
            resolved_kind = (
                storage_kind
                if isinstance(storage_kind, ArtifactStorageKind)
                else ArtifactStorageKind(str(storage_kind).lower())
            )
        else:
            # Auto-selection based on size and content
            if size_bytes <= self.inline_threshold_bytes and is_text:
                resolved_kind = ArtifactStorageKind.INLINE
            else:
                resolved_kind = ArtifactStorageKind.FILESYSTEM

        file_path_relative: Optional[str] = None
        inline_content: Optional[str] = None

        if resolved_kind == ArtifactStorageKind.INLINE:
            inline_content = payload_bytes.decode("utf-8", errors="replace")
        else:
            # Delegate physical storage to payload store abstraction
            file_path_relative = self.payload_store.write(
                project_id=project_id,
                artifact_id=artifact_id,
                filename=name,
                data=payload_bytes,
            )

        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            execution_id=execution_id,
            name=name,
            type=parsed_type,
            mime_type=mime_type,
            storage_kind=resolved_kind,
            file_path=file_path_relative,
            inline_content=inline_content,
            sha256_hash=sha256_hash,
            size_bytes=size_bytes,
            status=parsed_status,
            lineage=lineage or {},
            created_by=created_by,
            created_at=current_timestamp_iso(),
        )

        # Persist metadata to database
        self.storage.create_artifact(artifact.to_dict())
        logger.info(
            "Created artifact %s ('%s', %d bytes, kind=%s) for execution %s",
            artifact.id,
            artifact.name,
            artifact.size_bytes,
            artifact.storage_kind.value,
            execution_id,
        )
        return artifact

    def get_artifact(
        self, artifact_id: str, project_id: Optional[str] = None
    ) -> Optional[Artifact]:
        """Retrieve artifact metadata by ID with project-scope integrity verification."""
        raw = self.storage.get_artifact(artifact_id)
        if not raw:
            return None

        artifact = Artifact.model_validate(raw)

        # Enforce project-scope integrity
        if project_id and artifact.project_id != project_id:
            raise ArtifactSecurityError(
                f"Scope boundary violation: Artifact '{artifact_id}' belongs to project '{artifact.project_id}', "
                f"not authorized for project '{project_id}'"
            )

        return artifact

    def get_artifact_payload(self, artifact_id: str, project_id: Optional[str] = None) -> bytes:
        """Retrieve payload bytes for an artifact and verify cryptographic integrity."""
        artifact = self.get_artifact(artifact_id, project_id=project_id)
        if not artifact:
            raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found")

        if artifact.status == ArtifactStatus.DELETED:
            raise ArtifactNotFoundError(f"Artifact '{artifact_id}' has been deleted")

        if artifact.storage_kind == ArtifactStorageKind.INLINE:
            payload = (artifact.inline_content or "").encode("utf-8")
        else:
            if not artifact.file_path:
                raise ArtifactNotFoundError(f"Artifact '{artifact_id}' has no file_path recorded")

            try:
                payload = self.payload_store.read(artifact.project_id, artifact.file_path)
            except FileNotFoundError:
                raise ArtifactNotFoundError(
                    f"Artifact payload file missing for '{artifact_id}' at '{artifact.file_path}'"
                )

        # Integrity verification
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != artifact.sha256_hash:
            raise ArtifactIntegrityError(
                f"Artifact '{artifact_id}' SHA-256 mismatch: expected {artifact.sha256_hash}, got {actual_hash}"
            )
        if len(payload) != artifact.size_bytes:
            raise ArtifactIntegrityError(
                f"Artifact '{artifact_id}' size mismatch: expected {artifact.size_bytes} bytes, got {len(payload)}"
            )

        return payload

    def verify_integrity(self, artifact_id: str, project_id: Optional[str] = None) -> bool:
        """Verify whether an artifact's stored payload matches its recorded SHA-256 and size."""
        try:
            self.get_artifact_payload(artifact_id, project_id=project_id)
            return True
        except (ArtifactIntegrityError, ArtifactNotFoundError, ArtifactSecurityError) as err:
            logger.warning("Integrity verification failed for artifact %s: %s", artifact_id, err)
            return False

    def list_artifacts_by_execution(
        self,
        execution_id: str,
        project_id: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[Artifact]:
        """List artifacts produced or referenced by an execution with project-scope isolation.

        By default, excluded deleted artifacts unless include_deleted=True.
        """
        records = self.storage.list_artifacts_by_execution(
            execution_id, include_deleted=include_deleted
        )
        artifacts = [Artifact.model_validate(r) for r in records]

        if project_id:
            # Filter and verify project-scope boundary
            artifacts = [a for a in artifacts if a.project_id == project_id]

        if not include_deleted:
            artifacts = [a for a in artifacts if a.status != ArtifactStatus.DELETED]

        return artifacts

    def list_artifacts_by_project(
        self, project_id: str, include_deleted: bool = False
    ) -> List[Artifact]:
        """List artifacts belonging to a project, excluding deleted items by default."""
        if not project_id:
            raise ValueError("project_id is required to list artifacts")
        self._resolve_safe_project_dir(project_id)
        records = self.storage.list_artifacts_by_project(
            project_id, include_deleted=include_deleted
        )
        artifacts = [Artifact.model_validate(r) for r in records]
        if not include_deleted:
            artifacts = [a for a in artifacts if a.status != ArtifactStatus.DELETED]
        return artifacts

    def delete_artifact(self, artifact_id: str, project_id: Optional[str] = None) -> bool:
        """Delete artifact payload from storage and record metadata tombstone in database.

        Preserves execution provenance, identity, and auditability:
        - Payload is physically removed from storage.
        - Database record is updated with status=DELETED and deleted_at timestamp.
        """
        artifact = self.get_artifact(artifact_id, project_id=project_id)
        if not artifact:
            return False

        if artifact.status == ArtifactStatus.DELETED:
            return True  # Idempotent deletion

        # Delete physical payload from storage backend
        if artifact.storage_kind == ArtifactStorageKind.FILESYSTEM and artifact.file_path:
            self.payload_store.delete(artifact.project_id, artifact.file_path)

        # Mark metadata tombstone in database
        updated = self.storage.delete_artifact(artifact_id)
        logger.info(
            "Marked artifact %s as DELETED for project %s (tombstone preserved)",
            artifact_id,
            artifact.project_id,
        )
        return updated
