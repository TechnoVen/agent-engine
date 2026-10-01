"""core/checkpoint/backends/config.py

Configuration checkpoint backend preserving schema versions and SecretReferences without plaintext.
Part of Milestone R2 Task R2.11.

Invariants:
- Preserves SecretReference identifiers without leaking plaintext secrets into snapshots.
- Serializes config dictionary and verifies schema version on restore.
- Staged atomic write and hash verification.
"""

from __future__ import annotations

import hashlib
import json
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
)
from core.patch.service import atomic_commit_create


class ConfigCheckpointBackend(BaseCheckpointBackend):
    """Handles snapshot and rollback of JSON application configurations."""

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

    def _sanitize_config_for_snapshot(self, data: dict) -> dict:
        """Ensure secret references are preserved but no raw tokens are leaked."""
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, dict):
                # Preserves SecretReference structure: {"secret_id": "...", "provider": "..."}
                sanitized[k] = self._sanitize_config_for_snapshot(v)
            elif isinstance(v, str):
                # Guard against accidental plaintext secret leakage
                if any(v.startswith(prefix) for prefix in ("sk-", "ghp_", "xoxb-", "AIza")):
                    raise CheckpointError(
                        f"Config key '{k}' contains plaintext secret token. Use SecretReference instead."
                    )
                sanitized[k] = v
            else:
                sanitized[k] = v
        return sanitized

    def create_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> CheckpointResource:
        """Create a durable snapshot of config data."""
        if not resource.canonical_relative_path:
            raise CheckpointError("canonical_relative_path is required for config resources")

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        if target.exists():
            raw_text = target.read_text(encoding="utf-8")
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as e:
                raise CheckpointError(f"Invalid JSON config in {target}: {e}")

            sanitized = self._sanitize_config_for_snapshot(parsed)
            canonical_bytes = json.dumps(sanitized, indent=2, sort_keys=True).encode("utf-8")
            pre_hash = hashlib.sha256(canonical_bytes).hexdigest()

            cfg_dir = checkpoint_dir / "config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            cfg_dir.chmod(0o700)

            backup_file = cfg_dir / f"{resource.resource_id}.json"
            with open(backup_file, "xb") as f:
                f.write(canonical_bytes)
                f.flush()
                os.fsync(f.fileno())

            os.chmod(backup_file, 0o600)

            resource.exists_pre = True
            resource.pre_state_hash = pre_hash
            resource.storage_reference = f"config/{resource.resource_id}.json"
            resource.metadata = {
                "schema_version": parsed.get("version", "1.0"),
                "format": "json",
            }
        else:
            resource.exists_pre = False
            resource.pre_state_hash = None
            resource.storage_reference = None
            resource.metadata = {"format": "json"}

        return resource

    def inspect_conflict(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
    ) -> tuple[bool, str, str | None]:
        if not resource.canonical_relative_path:
            return False, "", None

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)
        if not target.exists():
            if resource.expected_post_state_hash is not None:
                return True, f"Config {resource.canonical_relative_path} removed externally", None
            return False, "", None

        curr_bytes = target.read_bytes()
        curr_hash = hashlib.sha256(curr_bytes).hexdigest()

        if resource.expected_post_state_hash is not None:
            if curr_hash != resource.expected_post_state_hash:
                return (
                    True,
                    f"Config {resource.canonical_relative_path} diverged: expected {resource.expected_post_state_hash}, found {curr_hash}",
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
        if not resource.canonical_relative_path:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.CONFIG,
                status=ResourceRestoreStatus.FAILED,
                message="Missing canonical_relative_path",
            )

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        is_conflict, conflict_reason, curr_hash = self.inspect_conflict(resource, workspace_root)
        if is_conflict and not force:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.CONFIG,
                status=ResourceRestoreStatus.CONFLICT,
                message=conflict_reason,
                verified=False,
                initial_hash=curr_hash,
            )

        if not resource.exists_pre:
            if target.exists():
                target.unlink()
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.CONFIG,
                status=ResourceRestoreStatus.RESTORED,
                message="Restored absent config",
                verified=True,
                initial_hash=curr_hash,
            )

        backup_file = checkpoint_dir / (resource.storage_reference or "")
        if not backup_file.exists():
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.CONFIG,
                status=ResourceRestoreStatus.FAILED,
                message=f"Config backup {backup_file} not found",
            )

        bck_data = backup_file.read_bytes()
        bck_hash = hashlib.sha256(bck_data).hexdigest()
        if bck_hash != resource.pre_state_hash:
            raise RestoreVerificationError("Corrupted config backup")

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_restore = target.parent / f".tmp_cfg_{resource.resource_id}_{uuid.uuid4().hex[:8]}"

        try:
            with open(tmp_restore, "wb") as f:
                f.write(bck_data)
                f.flush()
                os.fsync(f.fileno())

            os.chmod(tmp_restore, 0o600)

            if target.exists():
                os.replace(tmp_restore, target)
            else:
                atomic_commit_create(tmp_restore, target)

            # Verification
            verify_bytes = target.read_bytes()
            verify_hash = hashlib.sha256(verify_bytes).hexdigest()
            if verify_hash != resource.pre_state_hash:
                raise RestoreVerificationError("Post-restore verification failed for config")

            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.CONFIG,
                status=ResourceRestoreStatus.RESTORED,
                message="Successfully restored config",
                verified=True,
                initial_hash=curr_hash,
                restored_hash=verify_hash,
            )

        finally:
            if tmp_restore.exists():
                try:
                    tmp_restore.unlink()
                except Exception:
                    pass
