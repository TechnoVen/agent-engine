"""core/checkpoint/backends/database.py

Database checkpoint backend supporting consistent SQLite backups and fail-closed unsupported types.
Part of Milestone R2 Task R2.11.

Invariants:
- Uses SQLite Online Backup API (sqlite3.Connection.backup) for consistent live snapshot.
- Restores via SQLite backup API and executes PRAGMA integrity_check.
- Unsupported database types (PostgreSQL, MySQL, remote) fail explicitly with UnsupportedDatabaseBackendError.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.models import (
    CheckpointError,
    CheckpointResource,
    CheckpointResourceType,
    ResourceRestoreResult,
    ResourceRestoreStatus,
    RestoreVerificationError,
    UnsupportedDatabaseBackendError,
)


class DatabaseCheckpointBackend(BaseCheckpointBackend):
    """Handles snapshot and rollback of local SQLite databases."""

    def _resolve_safe_path(self, relative_path: str, workspace_root: Path) -> Path:
        root = workspace_root.resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise CheckpointError(
                f"Security violation: path {relative_path} escapes workspace root {workspace_root}"
            )
        return target

    def _check_db_type(self, resource: CheckpointResource) -> str:
        db_type = resource.metadata.get("db_type")
        if not db_type:
            path_str = resource.canonical_relative_path or ""
            if path_str.endswith((".db", ".sqlite", ".sqlite3")):
                db_type = "sqlite"
            else:
                db_type = "unknown"

        if db_type.lower() != "sqlite":
            raise UnsupportedDatabaseBackendError(
                f"Database type '{db_type}' is unsupported for automated rollback. Only SQLite is supported at S1."
            )
        return "sqlite"

    def create_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> CheckpointResource:
        """Create a durable consistent snapshot using SQLite Online Backup API."""
        self._check_db_type(resource)

        if not resource.canonical_relative_path:
            raise CheckpointError("canonical_relative_path is required for database resources")

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        if target.exists():
            db_dir = checkpoint_dir / "db"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_dir.chmod(0o700)

            backup_file = db_dir / f"{resource.resource_id}.sqlite"

            # Use SQLite Online Backup API for consistency
            src_conn = sqlite3.connect(str(target))
            dst_conn = sqlite3.connect(str(backup_file))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

            os.chmod(backup_file, 0o600)

            data = backup_file.read_bytes()
            pre_hash = hashlib.sha256(data).hexdigest()

            resource.exists_pre = True
            resource.pre_state_hash = pre_hash
            resource.storage_reference = f"db/{resource.resource_id}.sqlite"
            resource.metadata["db_type"] = "sqlite"
        else:
            resource.exists_pre = False
            resource.pre_state_hash = None
            resource.storage_reference = None
            resource.metadata["db_type"] = "sqlite"

        return resource

    def inspect_conflict(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
    ) -> tuple[bool, str, str | None]:
        """Check if live database has diverged with newer human edits."""
        if not resource.canonical_relative_path:
            return False, "", None

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)
        if not target.exists():
            if resource.expected_post_state_hash is not None:
                return (
                    True,
                    f"Database {resource.canonical_relative_path} was removed externally",
                    None,
                )
            return False, "", None

        curr_data = target.read_bytes()
        curr_hash = hashlib.sha256(curr_data).hexdigest()

        if resource.expected_post_state_hash is not None:
            if curr_hash != resource.expected_post_state_hash:
                return (
                    True,
                    f"Database {resource.canonical_relative_path} has diverged: expected {resource.expected_post_state_hash}, found {curr_hash}",
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
        """Restore SQLite database and verify PRAGMA integrity_check."""
        self._check_db_type(resource)

        if not resource.canonical_relative_path:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.FAILED,
                message="Missing canonical_relative_path",
            )

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        is_conflict, conflict_reason, curr_hash = self.inspect_conflict(resource, workspace_root)
        if is_conflict and not force:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.CONFLICT,
                message=conflict_reason,
                verified=False,
                initial_hash=curr_hash,
            )

        # Case 1: Pre-state was absent -> remove target db
        if not resource.exists_pre:
            if target.exists():
                try:
                    target.unlink()
                    for ext in ["-wal", "-shm"]:
                        aux = target.parent / f"{target.name}{ext}"
                        if aux.exists():
                            aux.unlink()
                except Exception as e:
                    return ResourceRestoreResult(
                        resource_id=resource.resource_id,
                        resource_type=CheckpointResourceType.DATABASE,
                        status=ResourceRestoreStatus.FAILED,
                        message=f"Failed to remove database: {e}",
                    )
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.RESTORED,
                message="Restored absent database",
                verified=True,
                initial_hash=curr_hash,
            )

        # Case 2: Pre-state was present -> restore via SQLite backup API
        backup_file = checkpoint_dir / (resource.storage_reference or "")
        if not backup_file.exists():
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.FAILED,
                message=f"Database backup {backup_file} not found",
            )

        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            bck_conn = sqlite3.connect(str(backup_file))
            live_conn = sqlite3.connect(str(target))
            try:
                bck_conn.backup(live_conn)
            finally:
                live_conn.close()
                bck_conn.close()

            # Integrity verification
            check_conn = sqlite3.connect(str(target))
            try:
                cur = check_conn.cursor()
                cur.execute("PRAGMA integrity_check")
                rows = cur.fetchall()
                if rows != [("ok",)]:
                    raise RestoreVerificationError(f"PRAGMA integrity_check failed: {rows}")
            finally:
                check_conn.close()

            restored_data = target.read_bytes()
            restored_hash = hashlib.sha256(restored_data).hexdigest()

            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.RESTORED,
                message="Successfully restored SQLite database and verified integrity",
                verified=True,
                initial_hash=curr_hash,
                restored_hash=restored_hash,
            )

        except Exception as e:
            if isinstance(e, RestoreVerificationError):
                raise
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.FAILED,
                message=f"Database restore failed: {e}",
                verified=False,
            )
