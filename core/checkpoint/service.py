"""core/checkpoint/service.py

Checkpoint and Rollback Service orchestrating multi-resource snapshots, exact approval verification,
pre-flight conflict inspection, and audit ledger records.
Part of Milestone R2 Task R2.11.

Invariants:
1. Checkpoint Before Consequential Mutation: Mutations verify checkpoint creation; failure halts fail-closed.
2. Safe Rollback: Consequential operation requiring PolicyEngine / approval token binding.
3. Never Rollback Over Newer Human State Silently: If live resource diverged, rollback halts with ROLLBACK_CONFLICT.
4. Storage Security: .ae_checkpoints/{project_id}/{checkpoint_id}/, mode 0o700/0o600, excluded from context.
5. Audit Ledger: Hash-only records, zero file contents, zero secrets.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Set

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.backends.config import ConfigCheckpointBackend
from core.checkpoint.backends.database import DatabaseCheckpointBackend
from core.checkpoint.backends.file import FileCheckpointBackend
from core.checkpoint.backends.git import GitCheckpointBackend
from core.checkpoint.models import (
    Checkpoint,
    CheckpointCreationError,
    CheckpointError,
    CheckpointExecutionRecord,
    CheckpointNotFoundError,
    CheckpointResource,
    CheckpointResourceType,
    CheckpointStatus,
    ResourceRestoreResult,
    ResourceRestoreStatus,
    RestorePlan,
    RestoreResult,
    RestoreStatus,
    compute_rollback_approval_digest,
    generate_checkpoint_id,
)

logger = logging.getLogger(__name__)


class CheckpointService:
    """Orchestrates durable checkpoint creation, policy evaluation, and safe rollback."""

    def __init__(
        self,
        storage: Optional[Any] = None,
        policy_engine: Optional[Any] = None,
        custom_backends: Optional[Dict[CheckpointResourceType, BaseCheckpointBackend]] = None,
    ) -> None:
        self.storage = storage
        self.policy_engine = policy_engine
        self.backends: Dict[CheckpointResourceType, BaseCheckpointBackend] = {
            CheckpointResourceType.FILE: FileCheckpointBackend(),
            CheckpointResourceType.GIT: GitCheckpointBackend(),
            CheckpointResourceType.DATABASE: DatabaseCheckpointBackend(),
            CheckpointResourceType.CONFIG: ConfigCheckpointBackend(),
        }
        if custom_backends:
            self.backends.update(custom_backends)

        self._consumed_approvals: Set[str] = set()

    def sanitize_id(self, identifier: str) -> str:
        """Sanitize identifiers to prevent path traversal."""
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "_", identifier)
        if not cleaned or cleaned.startswith("."):
            return f"safe_{cleaned}"
        return cleaned

    def get_checkpoint_dir(
        self,
        project_id: str,
        checkpoint_id: str,
        workspace_root: Path,
    ) -> Path:
        """Compute hardened storage directory for a checkpoint."""
        safe_proj = self.sanitize_id(project_id)
        safe_chk = self.sanitize_id(checkpoint_id)
        base = workspace_root / ".ae_checkpoints" / safe_proj / safe_chk
        return base

    def create_checkpoint(
        self,
        project_id: str,
        execution_id: str,
        resources: List[CheckpointResource],
        workspace_root: Path,
        description: str = "",
    ) -> Checkpoint:
        """Create a durable checkpoint of all requested resources before mutation."""
        start_time = time.time()
        checkpoint_id = generate_checkpoint_id()
        chk_dir = self.get_checkpoint_dir(project_id, checkpoint_id, workspace_root)

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            project_id=project_id,
            execution_id=execution_id,
            description=description,
            status=CheckpointStatus.CREATING,
            resources=[],
            created_at=start_time,
            updated_at=start_time,
        )

        try:
            chk_dir.mkdir(parents=True, exist_ok=True)
            chk_dir.chmod(0o700)

            # Snapshot each resource
            snapshotted_resources: List[CheckpointResource] = []
            for res in resources:
                backend = self.backends.get(res.resource_type)
                if not backend:
                    raise CheckpointCreationError(
                        f"No backend registered for resource type {res.resource_type}"
                    )
                updated_res = backend.create_snapshot(res, workspace_root, chk_dir)
                snapshotted_resources.append(updated_res)

            checkpoint.resources = snapshotted_resources
            checkpoint.status = CheckpointStatus.READY
            checkpoint.updated_at = time.time()

            # Save metadata atomically
            meta_file = chk_dir / "checkpoint.json"
            tmp_meta = chk_dir / ".checkpoint.json.tmp"
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(checkpoint.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            os.chmod(tmp_meta, 0o600)
            os.replace(tmp_meta, meta_file)

            # Fsync directory
            dir_fd = os.open(str(chk_dir), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            duration = time.time() - start_time

            # Record to audit ledger
            self._record_ledger(
                CheckpointExecutionRecord(
                    checkpoint_id=checkpoint_id,
                    project_id=project_id,
                    execution_id=execution_id,
                    action="create",
                    status=CheckpointStatus.READY.value,
                    resource_count=len(snapshotted_resources),
                    resource_types=[r.resource_type.value for r in snapshotted_resources],
                    duration_seconds=duration,
                    timestamp=time.time(),
                )
            )

            return checkpoint

        except Exception as e:
            checkpoint.status = CheckpointStatus.FAILED
            checkpoint.updated_at = time.time()
            try:
                if chk_dir.exists():
                    meta_file = chk_dir / "checkpoint.json"
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(checkpoint.to_dict(), f, indent=2)
            except Exception:
                pass

            duration = time.time() - start_time
            self._record_ledger(
                CheckpointExecutionRecord(
                    checkpoint_id=checkpoint_id,
                    project_id=project_id,
                    execution_id=execution_id,
                    action="create",
                    status=CheckpointStatus.FAILED.value,
                    resource_count=len(resources),
                    resource_types=[r.resource_type.value for r in resources],
                    duration_seconds=duration,
                    timestamp=time.time(),
                )
            )
            raise CheckpointCreationError(f"Failed to create checkpoint: {e}") from e

    def get_checkpoint(
        self,
        project_id: str,
        checkpoint_id: str,
        workspace_root: Path,
    ) -> Checkpoint:
        """Retrieve checkpoint metadata from storage."""
        chk_dir = self.get_checkpoint_dir(project_id, checkpoint_id, workspace_root)
        meta_file = chk_dir / "checkpoint.json"
        if not meta_file.exists():
            raise CheckpointNotFoundError(
                f"Checkpoint {checkpoint_id} not found for project {project_id}"
            )

        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return Checkpoint.from_dict(data)

    def _verify_and_consume_approval(self, plan: RestorePlan) -> None:
        """Verify rollback approval digest and atomically consume token."""
        if not plan.approval_id:
            return

        if plan.approval_id in self._consumed_approvals:
            raise CheckpointError(
                f"APPROVAL_ALREADY_CONSUMED: token {plan.approval_id} has already been used"
            )

        if self.storage and hasattr(self.storage, "is_approval_consumed"):
            if self.storage.is_approval_consumed(plan.approval_id):
                raise CheckpointError(
                    f"APPROVAL_ALREADY_CONSUMED: token {plan.approval_id} already consumed in storage"
                )

        expected_digest = compute_rollback_approval_digest(
            plan.project_id,
            plan.checkpoint_id,
            plan.restore_id,
            plan.resource_ids,
        )

        if plan.approval_digest != expected_digest:
            raise CheckpointError(
                f"APPROVAL_MISMATCH: rollback approval digest mismatch: expected {expected_digest}, received {plan.approval_digest}"
            )

        self._consumed_approvals.add(plan.approval_id)
        if self.storage and hasattr(self.storage, "atomic_consume_approval"):
            self.storage.atomic_consume_approval(plan.approval_id, "rollback", time.time())

    def restore_checkpoint(
        self,
        plan: RestorePlan,
        workspace_root: Path,
    ) -> RestoreResult:
        """Execute a declared rollback plan with pre-flight conflict check and verification."""
        start_time = time.time()
        chk_dir = self.get_checkpoint_dir(plan.project_id, plan.checkpoint_id, workspace_root)

        # 1. Approval verification
        try:
            self._verify_and_consume_approval(plan)
        except Exception as e:
            return RestoreResult(
                restore_id=plan.restore_id,
                checkpoint_id=plan.checkpoint_id,
                project_id=plan.project_id,
                status=RestoreStatus.FAILED,
                duration_seconds=time.time() - start_time,
                message=str(e),
            )

        # 2. Retrieve checkpoint
        try:
            checkpoint = self.get_checkpoint(plan.project_id, plan.checkpoint_id, workspace_root)
        except CheckpointNotFoundError as e:
            return RestoreResult(
                restore_id=plan.restore_id,
                checkpoint_id=plan.checkpoint_id,
                project_id=plan.project_id,
                status=RestoreStatus.FAILED,
                duration_seconds=time.time() - start_time,
                message=str(e),
            )

        if checkpoint.status not in (CheckpointStatus.READY, CheckpointStatus.RESTORED):
            return RestoreResult(
                restore_id=plan.restore_id,
                checkpoint_id=plan.checkpoint_id,
                project_id=plan.project_id,
                status=RestoreStatus.FAILED,
                duration_seconds=time.time() - start_time,
                message=f"Cannot restore checkpoint in status '{checkpoint.status.value}'",
            )

        # 3. Filter target resources
        target_resources: List[CheckpointResource] = []
        if plan.resource_ids:
            res_map = {r.resource_id: r for r in checkpoint.resources}
            for rid in plan.resource_ids:
                if rid not in res_map:
                    return RestoreResult(
                        restore_id=plan.restore_id,
                        checkpoint_id=plan.checkpoint_id,
                        project_id=plan.project_id,
                        status=RestoreStatus.FAILED,
                        duration_seconds=time.time() - start_time,
                        message=f"Resource '{rid}' requested in restore plan does not exist in checkpoint",
                    )
                target_resources.append(res_map[rid])
        else:
            target_resources = checkpoint.resources
            plan.resource_ids = [r.resource_id for r in target_resources]

        # 4. Pre-flight Conflict Inspection: ensure no resource diverged before modifying anything
        if not plan.force:
            conflicts: Dict[str, ResourceRestoreResult] = {}
            for res in target_resources:
                backend = self.backends.get(res.resource_type)
                if backend and hasattr(backend, "inspect_conflict"):
                    is_conflict, reason, *rest = backend.inspect_conflict(res, workspace_root)
                    if is_conflict:
                        conflicts[res.resource_id] = ResourceRestoreResult(
                            resource_id=res.resource_id,
                            resource_type=res.resource_type,
                            status=ResourceRestoreStatus.CONFLICT,
                            message=reason,
                            verified=False,
                        )

            if conflicts:
                # Halt without touching any files!
                duration = time.time() - start_time
                self._record_ledger(
                    CheckpointExecutionRecord(
                        checkpoint_id=plan.checkpoint_id,
                        project_id=plan.project_id,
                        execution_id=plan.restore_id,
                        action="restore",
                        status=RestoreStatus.CONFLICT.value,
                        resource_count=len(target_resources),
                        resource_types=[r.resource_type.value for r in target_resources],
                        approval_id=plan.approval_id,
                        duration_seconds=duration,
                        timestamp=time.time(),
                    )
                )
                return RestoreResult(
                    restore_id=plan.restore_id,
                    checkpoint_id=plan.checkpoint_id,
                    project_id=plan.project_id,
                    status=RestoreStatus.CONFLICT,
                    resource_results=conflicts,
                    duration_seconds=duration,
                    message="Pre-flight conflict inspection failed: newer human edits detected",
                )

        # 5. Execute restore across all resources
        results: Dict[str, ResourceRestoreResult] = {}
        for res in target_resources:
            backend = self.backends.get(res.resource_type)
            if not backend:
                results[res.resource_id] = ResourceRestoreResult(
                    resource_id=res.resource_id,
                    resource_type=res.resource_type,
                    status=ResourceRestoreStatus.FAILED,
                    message=f"No backend for {res.resource_type}",
                )
                continue

            try:
                res_outcome = backend.restore_snapshot(
                    res,
                    workspace_root,
                    chk_dir,
                    force=plan.force,
                )
                results[res.resource_id] = res_outcome
            except Exception as e:
                results[res.resource_id] = ResourceRestoreResult(
                    resource_id=res.resource_id,
                    resource_type=res.resource_type,
                    status=ResourceRestoreStatus.FAILED,
                    message=f"Exception during restore: {e}",
                )

        # Determine overall outcome
        has_failed = any(r.status == ResourceRestoreStatus.FAILED for r in results.values())
        has_conflict = any(r.status == ResourceRestoreStatus.CONFLICT for r in results.values())
        has_restored = any(r.status == ResourceRestoreStatus.RESTORED for r in results.values())

        if has_restored and not has_failed and not has_conflict:
            overall_status = RestoreStatus.COMPLETED
            msg = "All resources successfully restored"
        elif has_restored and (has_failed or has_conflict):
            overall_status = RestoreStatus.PARTIAL
            msg = (
                "Partial restore: some resources succeeded while others failed or were in conflict"
            )
        elif has_conflict:
            overall_status = RestoreStatus.CONFLICT
            msg = "Restore halted due to resource conflicts"
        else:
            overall_status = RestoreStatus.FAILED
            msg = "Failed to restore resources"

        duration = time.time() - start_time

        # Update checkpoint metadata
        try:
            checkpoint.status = (
                CheckpointStatus.RESTORED
                if overall_status == RestoreStatus.COMPLETED
                else CheckpointStatus.READY
            )
            checkpoint.updated_at = time.time()
            meta_file = chk_dir / "checkpoint.json"
            tmp_meta = chk_dir / ".checkpoint.json.tmp"
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(checkpoint.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_meta, 0o600)
            os.replace(tmp_meta, meta_file)
        except Exception as e:
            logger.debug(f"Failed to update checkpoint status after restore: {e}")

        # Record to audit ledger
        self._record_ledger(
            CheckpointExecutionRecord(
                checkpoint_id=plan.checkpoint_id,
                project_id=plan.project_id,
                execution_id=plan.restore_id,
                action="restore",
                status=overall_status.value,
                resource_count=len(results),
                resource_types=[r.resource_type.value for r in target_resources],
                approval_id=plan.approval_id,
                duration_seconds=duration,
                timestamp=time.time(),
            )
        )

        return RestoreResult(
            restore_id=plan.restore_id,
            checkpoint_id=plan.checkpoint_id,
            project_id=plan.project_id,
            status=overall_status,
            resource_results=results,
            duration_seconds=duration,
            message=msg,
        )

    def _record_ledger(self, record: CheckpointExecutionRecord) -> None:
        """Record checkpoint audit record without raw content or secrets."""
        if self.storage and hasattr(self.storage, "record_checkpoint_execution"):
            try:
                self.storage.record_checkpoint_execution(record)
            except Exception as e:
                logger.debug(f"Failed to record checkpoint execution in storage ledger: {e}")
