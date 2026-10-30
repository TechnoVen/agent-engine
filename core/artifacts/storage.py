"""Artifact Payload Storage Abstraction (Task R1.10).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md (Section 2.9 & Section 3), docs/ROADMAP.md (R1.10)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent_engine.artifacts.storage")


class ArtifactSecurityError(Exception):
    """Raised when an artifact operation violates project-scope boundary or filesystem containment.

    Trust boundary note:
    In Stage R1, this validates project-scope integrity (preventing accidental cross-project
    leakage or path traversal). Full actor-based authorization and RBAC will be added in Stage R2.
    TODO(R2): Integrate authenticated actor identity in Stage R2 project authorization.
    """

    pass


class ArtifactPayloadStore(ABC):
    """Abstract interface defining payload persistence boundary.

    Decouples metadata management from physical storage (local filesystem,
    object storage, remote server) without altering the Artifact domain model.
    """

    @abstractmethod
    def write(self, project_id: str, artifact_id: str, filename: str, data: bytes) -> str:
        """Persist payload bytes and return canonical relative storage path."""
        pass

    @abstractmethod
    def read(self, project_id: str, file_path: str) -> bytes:
        """Read payload bytes for a project-scoped relative storage path."""
        pass

    @abstractmethod
    def delete(self, project_id: str, file_path: str) -> bool:
        """Delete stored payload bytes."""
        pass

    @abstractmethod
    def exists(self, project_id: str, file_path: str) -> bool:
        """Check if stored payload exists."""
        pass


class LocalFilesystemPayloadStore(ArtifactPayloadStore):
    """Canonical local filesystem storage implementation with directory traversal
    and symlink escape protection.
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = os.path.abspath(base_dir)
        else:
            repo_root = Path(__file__).resolve().parents[2]
            self.base_dir = str(repo_root / "data" / "artifacts")
        os.makedirs(self.base_dir, exist_ok=True)

    def resolve_safe_project_dir(self, project_id: str) -> str:
        """Resolve and validate the base storage directory for a specific project."""
        if not project_id or ".." in project_id or "/" in project_id or "\\" in project_id:
            raise ArtifactSecurityError(f"Invalid project_id for artifact storage: '{project_id}'")

        project_dir = os.path.realpath(os.path.join(self.base_dir, project_id))
        base_dir_real = os.path.realpath(self.base_dir)

        if os.path.commonpath([base_dir_real, project_dir]) != base_dir_real:
            raise ArtifactSecurityError(
                f"Project directory '{project_dir}' escapes base artifacts directory"
            )

        os.makedirs(project_dir, exist_ok=True)
        return project_dir

    def _resolve_safe_file_path(self, project_id: str, artifact_id: str, filename: str) -> str:
        """Resolve and enforce containment for a prospective artifact file path."""
        project_dir = self.resolve_safe_project_dir(project_id)

        clean_name = os.path.basename(filename.replace("\\", "/"))
        if not clean_name or clean_name in (".", ".."):
            clean_name = "unnamed_artifact"

        storage_filename = f"{artifact_id}_{clean_name}"
        candidate_path = os.path.realpath(os.path.join(project_dir, storage_filename))

        if os.path.commonpath([project_dir, candidate_path]) != project_dir:
            raise ArtifactSecurityError(
                f"Artifact path '{candidate_path}' escapes project boundary '{project_dir}'"
            )

        return candidate_path

    def write(self, project_id: str, artifact_id: str, filename: str, data: bytes) -> str:
        abs_path = self._resolve_safe_file_path(project_id, artifact_id, filename)
        with open(abs_path, "wb") as f:
            f.write(data)
        return os.path.relpath(abs_path, self.base_dir)

    def read(self, project_id: str, file_path: str) -> bytes:
        project_dir = self.resolve_safe_project_dir(project_id)
        abs_path = os.path.realpath(os.path.join(self.base_dir, file_path))

        if os.path.commonpath([project_dir, abs_path]) != project_dir:
            raise ArtifactSecurityError(
                f"Artifact payload path '{abs_path}' escapes authorized project root '{project_dir}'"
            )

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Artifact payload missing at '{abs_path}'")

        with open(abs_path, "rb") as f:
            return f.read()

    def delete(self, project_id: str, file_path: str) -> bool:
        try:
            project_dir = self.resolve_safe_project_dir(project_id)
            abs_path = os.path.realpath(os.path.join(self.base_dir, file_path))
            if os.path.commonpath([project_dir, abs_path]) == project_dir and os.path.exists(
                abs_path
            ):
                os.remove(abs_path)
                return True
        except Exception as ex:
            logger.warning("Error deleting artifact payload '%s': %s", file_path, ex)
        return False

    def exists(self, project_id: str, file_path: str) -> bool:
        try:
            project_dir = self.resolve_safe_project_dir(project_id)
            abs_path = os.path.realpath(os.path.join(self.base_dir, file_path))
            return os.path.commonpath([project_dir, abs_path]) == project_dir and os.path.exists(
                abs_path
            )
        except Exception:
            return False
