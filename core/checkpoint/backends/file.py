"""core/checkpoint/backends/file.py

File-level checkpoint backend capturing exact byte snapshots, permissions, and atomic restore.
Part of Milestone R2 Task R2.11.

Invariants:
- Pre-state and post-state byte hashing using raw SHA-256.
- Refuses to overwrite newer human edits on rollback (ROLLBACK_CONFLICT). Public force bypass removed.
- Atomic commit using Linux renameat2(RENAME_NOREPLACE) for newly created files or os.replace for updates.
- Durable backup storage in private checkpoint directory with 0o600 permissions.
- Accurate file mode preservation using stat.S_IMODE(st_mode) (e.g. 0600, 0644, 0755).
- Pre-mutation verification: verifies backup bytes match expected hash before any live write.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import uuid

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.models import (
    CheckpointError,
    CheckpointIntegrityError,
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
            file_mode = stat.S_IMODE(stat_res.st_mode)

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

    def verify_snapshot_integrity(
        self,
        resource: CheckpointResource,
        checkpoint_dir: Path,
    ) -> None:
        """Verify backup bytes exist and match expected SHA-256 hash before mutation."""
        if not resource.exists_pre:
            return

        if not resource.storage_reference:
            raise CheckpointIntegrityError(
                f"CHECKPOINT_INTEGRITY_ERROR: resource {resource.resource_id} has no storage_reference"
            )

        backup_file = checkpoint_dir / resource.storage_reference
        if not backup_file.exists():
            raise CheckpointIntegrityError(
                f"CHECKPOINT_INTEGRITY_ERROR: backup file {backup_file} is missing"
            )

        data = backup_file.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != resource.pre_state_hash:
            raise CheckpointIntegrityError(
                f"CHECKPOINT_INTEGRITY_ERROR: file backup for {resource.resource_id} tampered: expected {resource.pre_state_hash}, found {actual_hash}"
            )

    def inspect_conflict(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
    ) -> tuple[bool, str, str | None]:
        """Inspect if live file has diverged with newer human edits."""
        if not resource.canonical_relative_path:
            return False, "", None

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        if not target.exists():
            if resource.expected_post_state_hash is not None:
                return (
                    True,
                    f"ROLLBACK_CONFLICT: File {resource.canonical_relative_path} was deleted externally (expected post-state {resource.expected_post_state_hash})",
                    None,
                )
            return False, "", None

        curr_data = target.read_bytes()
        curr_hash = hashlib.sha256(curr_data).hexdigest()

        if resource.expected_post_state_hash is not None:
            if curr_hash != resource.expected_post_state_hash:
                return (
                    True,
                    f"ROLLBACK_CONFLICT: File {resource.canonical_relative_path} has diverged with newer human edits (expected post-state {resource.expected_post_state_hash}, found {curr_hash})",
                    curr_hash,
                )

        return False, "", curr_hash

    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> ResourceRestoreResult:
        """Restore the file to its pre-execution state without force bypass."""
        if not resource.canonical_relative_path:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.FAILED,
                message="Missing canonical_relative_path",
            )

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        # 1. Pre-restore integrity check on checkpoint backup
        self.verify_snapshot_integrity(resource, checkpoint_dir)

        # 2. Conflict check: Never overwrite newer human edits
        is_conflict, conflict_reason, curr_hash = self.inspect_conflict(resource, workspace_root)
        if is_conflict:
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
        backup_file = checkpoint_dir / (resource.storage_reference or "")
        bck_data = backup_file.read_bytes()

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

            # Apply exact original file permissions (e.g. 0600, 0644, 0755)
            file_perm = (
                stat.S_IMODE(resource.file_mode) if resource.file_mode is not None else 0o644
            )
            os.chmod(tmp_restore, file_perm)

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
            if isinstance(
                e, (RestoreVerificationError, RollbackConflictError, CheckpointIntegrityError)
            ):
                raise
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.FILE,
                status=ResourceRestoreStatus.FAILED,
                message=f"Failed to restore file: {e}",
                verified=False,
                initial_hash=curr_hash,
            )
