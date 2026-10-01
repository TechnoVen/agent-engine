"""core/checkpoint/backends/base.py

Abstract base class for checkpoint resource backends.
Part of Milestone R2 Task R2.11.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.checkpoint.models import CheckpointResource, ResourceRestoreResult


class BaseCheckpointBackend(ABC):
    """Abstract base class for all checkpoint resource backends."""

    @abstractmethod
    def create_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> CheckpointResource:
        """Create a durable snapshot of the given resource in checkpoint_dir.

        Args:
            resource: The resource metadata to capture.
            workspace_root: Root directory of the workspace/project.
            checkpoint_dir: Directory where the checkpoint data is stored.

        Returns:
            The updated CheckpointResource with hashes, storage_reference, and metadata.
        """
        pass

    @abstractmethod
    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
        force: bool = False,
    ) -> ResourceRestoreResult:
        """Restore the resource from the snapshot in checkpoint_dir.

        Args:
            resource: The resource to restore.
            workspace_root: Root directory of the workspace/project.
            checkpoint_dir: Directory where the checkpoint data is stored.
            force: If True, overwrite even if live state has diverged.

        Returns:
            ResourceRestoreResult describing outcome and verification.
        """
        pass
