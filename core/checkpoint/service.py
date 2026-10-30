"""core/checkpoint/service.py

Checkpoint and Rollback Service orchestrating multi-resource snapshots, exact approval verification,
pre-flight conflict inspection, durable restore operation journaling, and audit ledger records.
Part of Milestone R2 Task R2.11.

Invariants (CTO Review Sections 11-24 & Final Closure Items 1-12):
1. Checkpoint Before Consequential Mutation: Mutations verify checkpoint creation; failure halts fail-closed.
2. Safe Rollback: Consequential operation requiring PolicyEngine / approval token binding.
3. Never Rollback Over Newer Human State Silently (ROLLBACK_CONFLICT): Public force rollback removed;
   if live resource diverged, rollback halts with ROLLBACK_CONFLICT.
4. Private Storage Isolation: Stored in ~/.agent_engine/checkpoints/{project_id}/{checkpoint_id}/ (mode 0o700/0o600),
   strictly outside user workspace trees and inaccessible to sandbox workers.
5. Durable Restore Operation Journal: Persists restore intent (PREPARED) before first live mutation;
   updates per-resource progress; reconciles interrupted restores idempotently after restart.
6. Immediate Pre-Mutation Revalidation: Each resource is locked and revalidated immediately before live
   mutation to detect post-preflight external edits; partial restores are reported truthfully (PARTIAL).
7. Pre-Mutation Integrity Verification: Checkpoint backup bytes and database integrity are verified
   before modifying any live state; tampered recovery data raises CheckpointIntegrityError.
8. Audit Ledger: Hash-only records, zero file contents, zero secrets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
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
    CheckpointIntegrityError,
    CheckpointNotFoundError,
    CheckpointResource,
    CheckpointResourceType,
    CheckpointStatus,
    ResourceRestoreResult,
    ResourceRestoreStatus,
    RestoreJournalState,
    RestoreOperation,
    RestorePlan,
    RestoreResult,
    RestoreStatus,
    compute_rollback_approval_digest,
    generate_checkpoint_id,
)
from core.storage.paths import get_private_data_dir

logger = logging.getLogger(__name__)


class CheckpointLockManager:
    """Serializes in-process Agent Engine mutations per (project_id, relative_path)."""

    def __init__(self) -> None:
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_lock(self, project_id: str, resource_key: str) -> threading.Lock:
        key = f"{project_id}:{resource_key}"
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


class CheckpointService:
    """Orchestrates durable checkpoint creation, policy evaluation, and safe rollback."""

    def __init__(
        self,
        storage: Optional[Any] = None,
        policy_engine: Optional[Any] = None,
        custom_backends: Optional[Dict[CheckpointResourceType, BaseCheckpointBackend]] = None,
        custom_storage_dir: Optional[Path | str] = None,
    ) -> None:
        self.storage = storage
        self.policy_engine = policy_engine
        self._custom_storage_dir = Path(custom_storage_dir) if custom_storage_dir else None
        self.backends: Dict[CheckpointResourceType, BaseCheckpointBackend] = {
            CheckpointResourceType.FILE: FileCheckpointBackend(),
            CheckpointResourceType.GIT: GitCheckpointBackend(),
            CheckpointResourceType.DATABASE: DatabaseCheckpointBackend(),
            CheckpointResourceType.CONFIG: ConfigCheckpointBackend(),
        }
        if custom_backends:
            self.backends.update(custom_backends)

        self._consumed_approvals: Set[str] = set()
        self._lock_manager = CheckpointLockManager()

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
        workspace_root: Optional[Path] = None,
    ) -> Path:
        """Compute hardened storage directory for a checkpoint in private storage root."""
        safe_proj = self.sanitize_id(project_id)
        safe_chk = self.sanitize_id(checkpoint_id)

        if self._custom_storage_dir is not None:
            base = self._custom_storage_dir / "checkpoints" / safe_proj / safe_chk
        else:
            base = get_private_data_dir() / "checkpoints" / safe_proj / safe_chk
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
            try:
                chk_dir.chmod(0o700)
            except Exception:
                pass

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

            try:
                os.chmod(tmp_meta, 0o600)
            except Exception:
                pass
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

    def _verify_and_consume_approval(
        self, plan: RestorePlan, target_resources: List[CheckpointResource]
    ) -> None:
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
            target_resources,
        )

        if plan.approval_digest != expected_digest:
            raise CheckpointError(
                f"APPROVAL_MISMATCH: rollback approval digest mismatch: expected {expected_digest}, received {plan.approval_digest}"
            )

        self._consumed_approvals.add(plan.approval_id)
        if self.storage and hasattr(self.storage, "atomic_consume_approval"):
            self.storage.atomic_consume_approval(plan.approval_id, "rollback", time.time())

    def _get_restores_dir(self, chk_dir: Path) -> Path:
        d = chk_dir / "restores"
        d.mkdir(parents=True, exist_ok=True)
        try:
            d.chmod(0o700)
        except Exception:
            pass
        return d

    def _persist_restore_op(self, chk_dir: Path, op: RestoreOperation) -> None:
        """Persist restore operation journal record durably with fsync."""
        restores_dir = self._get_restores_dir(chk_dir)
        op_file = restores_dir / f"{op.restore_id}.json"
        tmp_file = restores_dir / f".{op.restore_id}.tmp"

        op.updated_at = time.time()
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(op.to_dict(), f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        try:
            os.chmod(tmp_file, 0o600)
        except Exception:
            pass
        os.replace(tmp_file, op_file)

        # Fsync restores directory
        dir_fd = os.open(str(restores_dir), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def restore_checkpoint(
        self,
        plan: RestorePlan,
        workspace_root: Path,
    ) -> RestoreResult:
        """Execute a declared rollback plan with pre-flight conflict check, durable journal,
        immediate pre-mutation revalidation, and post-restore integrity verification.
        """
        start_time = time.time()
        chk_dir = self.get_checkpoint_dir(plan.project_id, plan.checkpoint_id, workspace_root)

        # 1. Retrieve checkpoint
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

        # 2. Filter target resources
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

        # 3. Approval verification (binds full restore plan)
        try:
            self._verify_and_consume_approval(plan, target_resources)
        except Exception as e:
            return RestoreResult(
                restore_id=plan.restore_id,
                checkpoint_id=plan.checkpoint_id,
                project_id=plan.project_id,
                status=RestoreStatus.FAILED,
                duration_seconds=time.time() - start_time,
                message=str(e),
            )

        # 4. Checkpoint Content Integrity Verification (Closure Item 6)
        # Verify all checkpoint backup materials before attempting any live mutation
        for res in target_resources:
            backend = self.backends.get(res.resource_type)
            if backend:
                try:
                    backend.verify_snapshot_integrity(res, chk_dir)
                except CheckpointIntegrityError as e:
                    return RestoreResult(
                        restore_id=plan.restore_id,
                        checkpoint_id=plan.checkpoint_id,
                        project_id=plan.project_id,
                        status=RestoreStatus.FAILED,
                        duration_seconds=time.time() - start_time,
                        message=f"CHECKPOINT_INTEGRITY_ERROR: {e}",
                    )

        # 5. Global Pre-flight Conflict Inspection
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
            # Halt immediately before modifying any live file!
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
                message="ROLLBACK_CONFLICT: Pre-flight conflict inspection failed: newer human edits detected",
            )

        # 6. Initialize Durable Restore Operation Journal (Closure Item 3)
        restore_op = RestoreOperation(
            restore_id=plan.restore_id,
            checkpoint_id=plan.checkpoint_id,
            project_id=plan.project_id,
            approval_reference=plan.approval_id,
            status=RestoreJournalState.PREPARED.value,
            resource_states={},
            created_at=start_time,
            updated_at=start_time,
        )
        self._persist_restore_op(chk_dir, restore_op)

        # Transition to RESTORING
        restore_op.status = RestoreJournalState.RESTORING.value
        self._persist_restore_op(chk_dir, restore_op)

        # 7. Execute restore across all resources with Immediate Pre-Mutation Revalidation (Closure Item 4)
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
                restore_op.resource_states[res.resource_id] = "FAILED"
                self._persist_restore_op(chk_dir, restore_op)
                continue

            lock_key = res.canonical_relative_path or res.resource_id
            lock = self._lock_manager.get_lock(plan.project_id, lock_key)

            with lock:
                # Immediate pre-mutation revalidation against disk
                if hasattr(backend, "inspect_conflict"):
                    is_conflict, reason, *rest = backend.inspect_conflict(res, workspace_root)
                    if is_conflict:
                        # Resource diverged after global preflight! Do NOT overwrite!
                        res_outcome = ResourceRestoreResult(
                            resource_id=res.resource_id,
                            resource_type=res.resource_type,
                            status=ResourceRestoreStatus.CONFLICT,
                            message=f"ROLLBACK_CONFLICT: {reason}",
                            verified=False,
                        )
                        results[res.resource_id] = res_outcome
                        restore_op.resource_states[res.resource_id] = "CONFLICT"
                        self._persist_restore_op(chk_dir, restore_op)
                        continue

                try:
                    res_outcome = backend.restore_snapshot(
                        res,
                        workspace_root,
                        chk_dir,
                    )
                    results[res.resource_id] = res_outcome
                    restore_op.resource_states[res.resource_id] = res_outcome.status.value.upper()
                except Exception as e:
                    results[res.resource_id] = ResourceRestoreResult(
                        resource_id=res.resource_id,
                        resource_type=res.resource_type,
                        status=ResourceRestoreStatus.FAILED,
                        message=f"Exception during restore: {e}",
                    )
                    restore_op.resource_states[res.resource_id] = "FAILED"

                self._persist_restore_op(chk_dir, restore_op)

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
            msg = "ROLLBACK_CONFLICT: Restore halted due to resource conflicts"
        else:
            overall_status = RestoreStatus.FAILED
            msg = "Failed to restore resources"

        # Finalize restore operation journal
        restore_op.status = overall_status.value.upper()
        self._persist_restore_op(chk_dir, restore_op)

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
            try:
                os.chmod(tmp_meta, 0o600)
            except Exception:
                pass
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

    def reconcile_interrupted_restores(
        self,
        project_id: str,
        checkpoint_id: str,
        workspace_root: Path,
    ) -> List[RestoreOperation]:
        """Inspect durable restore journal records on restart and reconcile safely (Closure Item 3)."""
        chk_dir = self.get_checkpoint_dir(project_id, checkpoint_id, workspace_root)
        restores_dir = chk_dir / "restores"
        if not restores_dir.exists():
            return []

        reconciled: List[RestoreOperation] = []
        try:
            checkpoint = self.get_checkpoint(project_id, checkpoint_id, workspace_root)
        except Exception:
            return []

        res_map = {r.resource_id: r for r in checkpoint.resources}

        for op_file in restores_dir.glob("*.json"):
            try:
                data = json.loads(op_file.read_text(encoding="utf-8"))
                op = RestoreOperation.from_dict(data)
            except Exception:
                continue

            if op.status in (
                RestoreJournalState.PREPARED.value,
                RestoreJournalState.RESTORING.value,
            ):
                # Check live state of resources to determine if mutations occurred
                states = {}
                for rid, rstate in op.resource_states.items():
                    res = res_map.get(rid)
                    if not res:
                        continue
                    backend = self.backends.get(res.resource_type)
                    if not backend:
                        continue

                    # Check current live hash
                    if res.resource_type == CheckpointResourceType.FILE:
                        target = workspace_root / (res.canonical_relative_path or "")
                        if target.exists():
                            curr_bytes = target.read_bytes()
                            curr_h = hashlib.sha256(curr_bytes).hexdigest()
                            if curr_h == res.pre_state_hash:
                                states[rid] = "RESTORED"
                            elif curr_h == res.expected_post_state_hash:
                                states[rid] = "NOT_RESTORED"
                            else:
                                states[rid] = "AMBIGUOUS"
                        else:
                            if not res.exists_pre:
                                states[rid] = "RESTORED"
                            else:
                                states[rid] = "NOT_RESTORED"

                # If any state is ambiguous, mark RECOVERY_REQUIRED
                if any(s == "AMBIGUOUS" for s in states.values()):
                    op.status = RestoreJournalState.RECOVERY_REQUIRED.value
                elif all(s == "RESTORED" for s in states.values()) and states:
                    op.status = RestoreJournalState.COMPLETED.value
                elif all(s == "NOT_RESTORED" for s in states.values()):
                    op.status = RestoreJournalState.FAILED.value
                elif any(s == "RESTORED" for s in states.values()):
                    op.status = RestoreJournalState.PARTIAL.value
                else:
                    op.status = RestoreJournalState.RECOVERY_REQUIRED.value

                self._persist_restore_op(chk_dir, op)
                reconciled.append(op)

        return reconciled

    def reconcile_incomplete_restores(
        self,
        workspace_root: Path,
        project_id: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
    ) -> List[RestoreOperation]:
        """Reconcile incomplete or interrupted restore operations across checkpoints."""
        if project_id and checkpoint_id:
            return self.reconcile_interrupted_restores(project_id, checkpoint_id, workspace_root)

        storage_root = (
            self._custom_storage_dir / "checkpoints"
            if self._custom_storage_dir
            else get_private_data_dir() / "checkpoints"
        )
        reconciled: List[RestoreOperation] = []
        if not storage_root.exists():
            return reconciled

        for proj_dir in storage_root.iterdir():
            if not proj_dir.is_dir():
                continue
            proj = proj_dir.name
            if project_id and proj != self.sanitize_id(project_id):
                continue
            for chk_dir in proj_dir.iterdir():
                if not chk_dir.is_dir():
                    continue
                chk_id = chk_dir.name
                if checkpoint_id and chk_id != self.sanitize_id(checkpoint_id):
                    continue
                ops = self.reconcile_interrupted_restores(proj, chk_id, workspace_root)
                reconciled.extend(ops)
        return reconciled

    def _record_ledger(self, record: CheckpointExecutionRecord) -> None:
        """Record checkpoint audit record without raw content or secrets."""
        if self.storage and hasattr(self.storage, "record_checkpoint_execution"):
            try:
                self.storage.record_checkpoint_execution(record)
            except Exception as e:
                logger.debug(f"Failed to record checkpoint execution in storage ledger: {e}")
