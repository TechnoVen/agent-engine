"""core/checkpoint/backends/file.py

File-level checkpoint backend capturing exact byte snapshots, permissions, and atomic restore.
Part of Milestone R2 Task R2.11.

Invariants:
- Pre-state and post-state byte hashing using raw SHA-256.
- Refuses to overwrite newer human edits on rollback (ROLLBACK_CONFLICT) unless force=True.
- Atomic commit using Linux renameat2(RENAME_NOREPLACE) for newly created files or os.replace for updates.
- Durable backup storage in checkpoint directory with 0o600 permissions.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import uuid

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.models import (
    CheckpointError,
    CheckpointResource,
    CheckpointResourceType,
    ResourceRestoreResult,
    ResourceRestoreStatus,
    RestoreVerificationError,
    RollbackConflictError,
)
from core.patch.service import atomic_commit_create


class FileCheckpointBackend(BaseCheckpointBackend):
    """Handles snapshot and rollback of single files within a workspace."""

    def _resolve_safe_path(self, relative_path: str, workspace_root: Path) -> Path:
        """Ensure path is canonical and strictly within workspace root."""
        root = workspace_root.resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise CheckpointError(
                f"Security violation: path {relative_path} escapes workspace root {workspace_root}"
            )
        return target

    def create_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> CheckpointResource:
        """Create a durable snapshot of a file before execution."""
        if not resource.canonical_relative_path:
            raise CheckpointError("canonical_relative_path is required for file resources")

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        if target.exists():
            if not target.is_file():
                raise CheckpointError(f"Target path {target} exists but is not a regular file")

            data = target.read_bytes()
            pre_hash = hashlib.sha256(data).hexdigest()
            stat_res = target.stat()
            file_mode = stat_res.st_mode & 0o777

            files_dir = checkpoint_dir / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            files_dir.chmod(0o700)

            backup_filename = f"{resource.resource_id}.bak"
            backup_file = files_dir / backup_filename

            # Write backup with exclusive creation mode 'xb' and fsync
            with open(backup_file, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            os.chmod(backup_file, 0o600)

            resource.exists_pre = True
            resource.pre_state_hash = pre_hash
            resource.storage_reference = f"files/{backup_filename}"
            resource.file_mode = file_mode
        else:
            resource.exists_pre = False
            resource.pre_state_hash = None
            resource.storage_reference = None
            resource.file_mode = None

        return resource

    def inspect_conflict(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
    ) -> tuple[bool, str, str | None]:
        """Inspect if live file has diverged with newer human edits.

        Returns (is_conflict, reason, current_hash).
        """
        if not resource.canonical_relative_path:
            return False, "", None

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        if not target.exists():
            # If expected_post_state_hash was recorded (meaning execution left a file),
            # but live file is absent, someone deleted it!
            if resource.expected_post_state_hash is not None:
                return (
                    True,
                    f"File {resource.canonical_relative_path} was deleted externally (expected post-state {resource.expected_post_state_hash})",
                    None,
                )
            return False, "", None

        curr_data = target.read_bytes()
        curr_hash = hashlib.sha256(curr_data).hexdigest()

        if resource.expected_post_state_hash is not None:
            if curr_hash != resource.expected_post_state_hash:
                return (
                    True,
                    f"File {resource.canonical_relative_path} has diverged with newer human edits: expected post-state {resource.expected_post_state_hash}, found {curr_hash}",
                    curr_hash,
                )

        return False, "", curr_hash

    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
        force: bool = False,
    ) -> ResourceRestoreResult:
        """Restore the file to its pre-execution state."""
        if not resource.canonical_relative_path:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.FAILED,
                message="Missing canonical_relative_path",
            )

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        # Check conflict first
        is_conflict, conflict_reason, curr_hash = self.inspect_conflict(resource, workspace_root)
        if is_conflict and not force:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.CONFLICT,
                message=conflict_reason,
                verified=False,
                initial_hash=curr_hash,
            )

        # Case 1: Pre-state was absent -> restore absence (delete file if created)
        if not resource.exists_pre:
            if target.exists():
                try:
                    target.unlink()
                    dir_fd = os.open(str(target.parent), os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except Exception as e:
                    return ResourceRestoreResult(
                        resource_id=resource.resource_id,
                        resource_type=CheckpointResourceType.FILE,
                        status=ResourceRestoreStatus.FAILED,
                        message=f"Failed to remove created file during restore: {e}",
                        verified=False,
                        initial_hash=curr_hash,
                    )
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.RESTORED,
                message="Restored absent state (file removed)",
                verified=True,
                initial_hash=curr_hash,
                restored_hash=None,
            )

        # Case 2: Pre-state was present -> restore bytes from backup
        if not resource.storage_reference:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.FAILED,
                message="Missing storage_reference for present file",
                verified=False,
            )

        backup_file = checkpoint_dir / resource.storage_reference
        if not backup_file.exists():
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.FAILED,
                message=f"Backup file {backup_file} not found",
                verified=False,
            )

        bck_data = backup_file.read_bytes()
        bck_hash = hashlib.sha256(bck_data).hexdigest()
        if bck_hash != resource.pre_state_hash:
            raise RestoreVerificationError(
                f"Corrupted backup for {resource.resource_id}: expected {resource.pre_state_hash}, found {bck_hash}"
            )

        # Ensure target parent exists
        target.parent.mkdir(parents=True, exist_ok=True)

        # Staged write to temporary sibling file
        tmp_name = f".tmp_rst_{resource.resource_id}_{uuid.uuid4().hex[:8]}"
        tmp_restore = target.parent / tmp_name

        try:
            with open(tmp_restore, "wb") as f:
                f.write(bck_data)
                f.flush()
                os.fsync(f.fileno())

            if resource.file_mode:
                os.chmod(tmp_restore, resource.file_mode)

            # Atomic commit
            if target.exists():
                os.replace(tmp_restore, target)
            else:
                atomic_commit_create(tmp_restore, target)

            # Fsync directory
            dir_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            # Post-restore verification
            verify_data = target.read_bytes()
            verify_hash = hashlib.sha256(verify_data).hexdigest()
            if verify_hash != resource.pre_state_hash:
                raise RestoreVerificationError(
                    f"Post-restore verification failed for {target}: expected {resource.pre_state_hash}, got {verify_hash}"
                )

            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.RESTORED,
                message="Successfully restored file from backup",
                verified=True,
                initial_hash=curr_hash,
                restored_hash=verify_hash,
            )

        except Exception as e:
            if tmp_restore.exists():
                try:
                    tmp_restore.unlink()
                except Exception:
                    pass
            if isinstance(e, (RestoreVerificationError, RollbackConflictError)):
                raise
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.FAILED,
                message=f"Failed to restore file: {e}",
                verified=False,
                initial_hash=curr_hash,
            )
