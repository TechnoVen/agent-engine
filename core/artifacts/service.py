"""Canonical Artifact Service (Task R1.10).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md (Section 2.9 & Section 3), docs/ROADMAP.md (R1.10)
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.artifacts.models import (
    Artifact,
    ArtifactStatus,
    ArtifactStorageKind,
    ArtifactType,
    current_timestamp_iso,
    generate_artifact_id,
)
from core.storage.base import StorageBackend

logger = logging.getLogger("agent_engine.artifacts.service")

DEFAULT_INLINE_THRESHOLD_BYTES = 8192  # 8 KB threshold for inline storage


class ArtifactSecurityError(Exception):
    """Raised when an artifact operation violates project isolation or filesystem boundary."""

    pass


class ArtifactNotFoundError(Exception):
    """Raised when an artifact cannot be found."""

    pass


class ArtifactIntegrityError(Exception):
    """Raised when an artifact payload does not match its recorded SHA-256 hash or size."""

    pass


class ArtifactService:
    """Canonical service managing artifact creation, retrieval, integrity, and isolation."""

    def __init__(
        self,
        storage: StorageBackend,
        base_artifacts_dir: Optional[str] = None,
        inline_threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES,
    ):
        self.storage = storage
        if base_artifacts_dir:
            self.base_artifacts_dir = os.path.abspath(base_artifacts_dir)
        else:
            repo_root = Path(__file__).resolve().parents[2]
            self.base_artifacts_dir = str(repo_root / "data" / "artifacts")
        self.inline_threshold_bytes = inline_threshold_bytes
        os.makedirs(self.base_artifacts_dir, exist_ok=True)

    def _resolve_safe_project_dir(self, project_id: str) -> str:
        """Resolve and validate the base storage directory for a specific project."""
        if not project_id or ".." in project_id or "/" in project_id or "\\" in project_id:
            raise ArtifactSecurityError(f"Invalid project_id for artifact storage: '{project_id}'")

        project_dir = os.path.realpath(os.path.join(self.base_artifacts_dir, project_id))
        base_dir_real = os.path.realpath(self.base_artifacts_dir)

        # Validate containment
        if os.path.commonpath([base_dir_real, project_dir]) != base_dir_real:
            raise ArtifactSecurityError(
                f"Project directory '{project_dir}' escapes base artifacts directory"
            )

        os.makedirs(project_dir, exist_ok=True)
        return project_dir

    def _resolve_safe_file_path(self, project_id: str, artifact_id: str, filename: str) -> str:
        """Resolve and enforce containment for a prospective artifact file path."""
        project_dir = self._resolve_safe_project_dir(project_id)

        # Sanitize filename: strip directory components and traversal tokens
        clean_name = os.path.basename(filename.replace("\\", "/"))
        if not clean_name or clean_name in (".", ".."):
            clean_name = "unnamed_artifact"

        storage_filename = f"{artifact_id}_{clean_name}"
        candidate_path = os.path.realpath(os.path.join(project_dir, storage_filename))

        # Strict directory traversal and symlink escape verification
        if os.path.commonpath([project_dir, candidate_path]) != project_dir:
            raise ArtifactSecurityError(
                f"Artifact path '{candidate_path}' escapes project boundary '{project_dir}'"
            )

        return candidate_path

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
            # Write to managed filesystem path
            abs_path = self._resolve_safe_file_path(project_id, artifact_id, name)
            with open(abs_path, "wb") as f:
                f.write(payload_bytes)
            # Record relative path for portability: {project_id}/{basename}
            file_path_relative = os.path.relpath(abs_path, self.base_artifacts_dir)

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
        """Retrieve artifact metadata by ID with optional project isolation enforcement."""
        raw = self.storage.get_artifact(artifact_id)
        if not raw:
            return None

        artifact = Artifact.model_validate(raw)

        # Enforce project isolation
        if project_id and artifact.project_id != project_id:
            raise ArtifactSecurityError(
                f"Access denied: Artifact '{artifact_id}' belongs to project '{artifact.project_id}', "
                f"not authorized for project '{project_id}'"
            )

        return artifact

    def get_artifact_payload(self, artifact_id: str, project_id: Optional[str] = None) -> bytes:
        """Retrieve the payload bytes for an artifact and verify cryptographic integrity."""
        artifact = self.get_artifact(artifact_id, project_id=project_id)
        if not artifact:
            raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found")

        if artifact.storage_kind == ArtifactStorageKind.INLINE:
            payload = (artifact.inline_content or "").encode("utf-8")
        else:
            if not artifact.file_path:
                raise ArtifactNotFoundError(f"Artifact '{artifact_id}' has no file_path recorded")

            abs_path = os.path.realpath(os.path.join(self.base_artifacts_dir, artifact.file_path))
            project_dir = self._resolve_safe_project_dir(artifact.project_id)

            # Security check: must reside inside project directory
            if os.path.commonpath([project_dir, abs_path]) != project_dir:
                raise ArtifactSecurityError(
                    f"Artifact payload path '{abs_path}' escapes authorized project root '{project_dir}'"
                )

            if not os.path.exists(abs_path):
                raise ArtifactNotFoundError(f"Artifact payload file missing at '{abs_path}'")

            with open(abs_path, "rb") as f:
                payload = f.read()

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
        self, execution_id: str, project_id: Optional[str] = None
    ) -> List[Artifact]:
        """List all artifacts produced or referenced by an execution with project isolation."""
        records = self.storage.list_artifacts_by_execution(execution_id)
        artifacts = [Artifact.model_validate(r) for r in records]

        if project_id:
            # Filter and verify project isolation
            artifacts = [a for a in artifacts if a.project_id == project_id]

        return artifacts

    def list_artifacts_by_project(self, project_id: str) -> List[Artifact]:
        """List all artifacts belonging to a project."""
        if not project_id:
            raise ValueError("project_id is required to list artifacts")
        records = self.storage.list_artifacts_by_project(project_id)
        return [Artifact.model_validate(r) for r in records]

    def delete_artifact(self, artifact_id: str, project_id: Optional[str] = None) -> bool:
        """Delete artifact payload and remove or mark as DELETED in storage."""
        artifact = self.get_artifact(artifact_id, project_id=project_id)
        if not artifact:
            return False

        # If stored on filesystem, safely delete the file
        if artifact.storage_kind == ArtifactStorageKind.FILESYSTEM and artifact.file_path:
            abs_path = os.path.realpath(os.path.join(self.base_artifacts_dir, artifact.file_path))
            project_dir = self._resolve_safe_project_dir(artifact.project_id)
            if os.path.commonpath([project_dir, abs_path]) == project_dir and os.path.exists(
                abs_path
            ):
                try:
                    os.remove(abs_path)
                except OSError as ex:
                    logger.warning("Error deleting artifact file '%s': %s", abs_path, ex)

        # Delete from database
        deleted = self.storage.delete_artifact(artifact_id)
        logger.info("Deleted artifact %s for project %s", artifact_id, artifact.project_id)
        return deleted
