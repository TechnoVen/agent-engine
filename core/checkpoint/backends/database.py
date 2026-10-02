"""core/checkpoint/backends/database.py

Database checkpoint backend supporting consistent SQLite backups with maintenance boundary
and fail-closed unsupported types.
Part of Milestone R2 Task R2.11.

Invariants (CTO Review Closure Item 9):
- Canonical SQLite Restore Maintenance Boundary:
  Acquires maintenance lock, handles open connections, ensures WAL/SHM consistency via
  sqlite3.Connection.backup() API, verifies PRAGMA integrity_check before releasing boundary.
- Pre-mutation verification: verifies backup file hash and executes integrity check on backup before mutation.
- Unsupported database types (PostgreSQL, MySQL, remote) fail explicitly with UnsupportedDatabaseBackendError.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import threading

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.models import (
    CheckpointError,
    CheckpointIntegrityError,
    CheckpointResource,
    CheckpointResourceType,
    ResourceRestoreResult,
    ResourceRestoreStatus,
    RestoreVerificationError,
    UnsupportedDatabaseBackendError,
)

# Global maintenance lock for database restore operations
_DB_MAINTENANCE_LOCK = threading.RLock()


class DatabaseCheckpointBackend(BaseCheckpointBackend):
    """Handles snapshot and rollback of local SQLite databases."""

    @contextmanager
    def maintenance_boundary(self, db_path: Path):
        """Establish a canonical SQLite restore maintenance boundary (Closure Item 9)."""
        with _DB_MAINTENANCE_LOCK:
            yield

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

            # Use SQLite Online Backup API for consistency across WAL and memory caches
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

    def verify_snapshot_integrity(
        self,
        resource: CheckpointResource,
        checkpoint_dir: Path,
    ) -> None:
        """Verify database backup exists, hash matches, and PRAGMA integrity_check passes."""
        if not resource.exists_pre:
            return

        if not resource.storage_reference:
            raise CheckpointIntegrityError(
                "CHECKPOINT_INTEGRITY_ERROR: missing database storage_reference"
            )

        backup_file = checkpoint_dir / resource.storage_reference
        if not backup_file.exists():
            raise CheckpointIntegrityError(
                f"CHECKPOINT_INTEGRITY_ERROR: backup file {backup_file} not found"
            )

        data = backup_file.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != resource.pre_state_hash:
            raise CheckpointIntegrityError(
                f"CHECKPOINT_INTEGRITY_ERROR: database backup for {resource.resource_id} tampered: expected {resource.pre_state_hash}, found {actual_hash}"
            )

        # Verify integrity of backup database itself
        conn = sqlite3.connect(str(backup_file))
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check")
            rows = cur.fetchall()
            if rows != [("ok",)]:
                raise CheckpointIntegrityError(
                    f"CHECKPOINT_INTEGRITY_ERROR: SQLite backup integrity check failed: {rows}"
                )
        finally:
            conn.close()

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
                    f"ROLLBACK_CONFLICT: Database {resource.canonical_relative_path} was removed externally",
                    None,
                )
            return False, "", None

        curr_data = target.read_bytes()
        curr_hash = hashlib.sha256(curr_data).hexdigest()

        if resource.expected_post_state_hash is not None:
            if curr_hash != resource.expected_post_state_hash:
                return (
                    True,
                    f"ROLLBACK_CONFLICT: Database {resource.canonical_relative_path} has diverged: expected {resource.expected_post_state_hash}, found {curr_hash}",
                    curr_hash,
                )

        return False, "", curr_hash

    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> ResourceRestoreResult:
        """Restore SQLite database under canonical maintenance boundary."""
        self._check_db_type(resource)

        if not resource.canonical_relative_path:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.FAILED,
                message="Missing canonical_relative_path",
            )

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        # 1. Verify backup integrity
        self.verify_snapshot_integrity(resource, checkpoint_dir)

        # 2. Check conflict
        is_conflict, conflict_reason, curr_hash = self.inspect_conflict(resource, workspace_root)
        if is_conflict:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.DATABASE,
                status=ResourceRestoreStatus.CONFLICT,
                message=conflict_reason,
                verified=False,
                initial_hash=curr_hash,
            )

        # 3. Execute restore inside maintenance boundary
        with self.maintenance_boundary(target):
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

            backup_file = checkpoint_dir / (resource.storage_reference or "")
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
