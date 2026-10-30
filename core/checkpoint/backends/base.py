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
        """Create a durable snapshot of the given resource in checkpoint_dir."""
        pass

    @abstractmethod
    def verify_snapshot_integrity(
        self,
        resource: CheckpointResource,
        checkpoint_dir: Path,
    ) -> None:
        """Verify the integrity of snapshot data before attempting any live mutation.

        Raises CheckpointIntegrityError if backup bytes, database snapshot, or git
        ref has been tampered with or corrupted.
        """
        pass

    @abstractmethod
    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> ResourceRestoreResult:
        """Restore the resource from the snapshot in checkpoint_dir.

        If live state diverges from expected post state, returns status CONFLICT
        (ROLLBACK_CONFLICT) without overwriting.
        """
        pass
