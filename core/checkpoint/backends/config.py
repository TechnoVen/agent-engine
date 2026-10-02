"""core/checkpoint/backends/config.py

Configuration checkpoint backend preserving schema versions and SecretReferences without plaintext.
Part of Milestone R2 Task R2.11.

Invariants (CTO Review Closure Item 10):
- Typed serialization: SecretReference preserved as safe dict; live SecretValue raises CheckpointError.
- Unknown/unserializable sensitive objects fail closed rather than calling repr().
- Preserves schema versions.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
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
)
from core.patch.service import atomic_commit_create
from core.security.secrets import SecretReference, SecretValue


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

    def _sanitize_config_for_snapshot(self, data: Any) -> Any:
        """Typed serialization preserving SecretReference and rejecting SecretValue (Closure Item 10)."""
        if isinstance(data, SecretValue):
            raise CheckpointError(
                "Cannot snapshot configuration containing live SecretValue; use SecretReference."
            )

        if isinstance(data, SecretReference):
            return {
                "secret_id": data.secret_id,
                "provider": data.provider,
                "description": getattr(data, "description", None),
            }

        if isinstance(data, dict):
            sanitized = {}
            for k, v in data.items():
                if isinstance(v, SecretValue):
                    raise CheckpointError(f"Config key '{k}' contains live SecretValue.")
                sanitized[k] = self._sanitize_config_for_snapshot(v)
            return sanitized

        if isinstance(data, list):
            return [self._sanitize_config_for_snapshot(item) for item in data]

        if isinstance(data, (str, int, float, bool, type(None))):
            if isinstance(data, str) and any(
                data.startswith(prefix) for prefix in ("sk-", "ghp_", "xoxb-", "AIza")
            ):
                raise CheckpointError(
                    "Config string contains plaintext secret token. Use SecretReference instead."
                )
            return data

        # Unknown object -> fail closed rather than calling repr()
        raise CheckpointError(
            f"Unsupported configuration value of type {type(data).__name__}; refusing unsafe serialization."
        )

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

    def verify_snapshot_integrity(
        self,
        resource: CheckpointResource,
        checkpoint_dir: Path,
    ) -> None:
        """Verify config backup exists and hash matches before mutation."""
        if not resource.exists_pre:
            return

        if not resource.storage_reference:
            raise CheckpointIntegrityError(
                "CHECKPOINT_INTEGRITY_ERROR: missing config storage_reference"
            )

        backup_file = checkpoint_dir / resource.storage_reference
        if not backup_file.exists():
            raise CheckpointIntegrityError(
                f"CHECKPOINT_INTEGRITY_ERROR: config backup {backup_file} not found"
            )

        data = backup_file.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != resource.pre_state_hash:
            raise CheckpointIntegrityError(
                f"CHECKPOINT_INTEGRITY_ERROR: config backup for {resource.resource_id} tampered: expected {resource.pre_state_hash}, found {actual_hash}"
            )

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
                return (
                    True,
                    f"ROLLBACK_CONFLICT: Config {resource.canonical_relative_path} removed externally",
                    None,
                )
            return False, "", None

        curr_bytes = target.read_bytes()
        curr_hash = hashlib.sha256(curr_bytes).hexdigest()

        if resource.expected_post_state_hash is not None:
            if curr_hash != resource.expected_post_state_hash:
                return (
                    True,
                    f"ROLLBACK_CONFLICT: Config {resource.canonical_relative_path} diverged: expected {resource.expected_post_state_hash}, found {curr_hash}",
                    curr_hash,
                )

        return False, "", curr_hash

    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> ResourceRestoreResult:
        if not resource.canonical_relative_path:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.CONFIG,
                status=ResourceRestoreStatus.FAILED,
                message="Missing canonical_relative_path",
            )

        target = self._resolve_safe_path(resource.canonical_relative_path, workspace_root)

        # 1. Verify backup integrity
        self.verify_snapshot_integrity(resource, checkpoint_dir)

        # 2. Conflict check
        is_conflict, conflict_reason, curr_hash = self.inspect_conflict(resource, workspace_root)
        if is_conflict:
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
        bck_data = backup_file.read_bytes()

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
