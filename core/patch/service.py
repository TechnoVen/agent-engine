"""core/patch/service.py

Safe Staged Patch Application Service.
Part of Milestone R2 Task R2.10.

Invariants (CTO Review Sections 10-22):
1. Never overwrite newer human edits: Stale patch proposals are rejected fail-closed,
   leaving live human edits untouched.
2. Exact-approval digest binding: An approval token binds project, path, operation type,
   expected hash, and proposed hash. Any modification invalidates approval.
3. Pre-commit revalidation: Live file state is inspected immediately before mutation.
4. Atomic replacement: Changes are written to a staged temporary file on the same
   filesystem, fsynced, hash-verified, and atomically renamed (os.replace).
5. Posix directory fsync: Parent directory fsync guarantees durability across crashes.
6. Durable journal & backup: Journal and original backup are persisted before mutation.
7. Idempotent crash recovery: Startup recovery inspects journal state against live disk hash;
   ambiguous states with newer human edits are never overwritten (RECOVERY_REQUIRED).
8. Target serialization: Agent Engine's own writers are serialized per (project, path).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional

from core.artifacts.service import ArtifactService
from core.patch.models import (
    PatchConflictReason,
    PatchExecutionRecord,
    PatchJournalEntry,
    PatchJournalState,
    PatchOperation,
    PatchOperationType,
    PatchResult,
    compute_content_hash,
    compute_file_hash,
    compute_patch_approval_digest,
)
from core.skills.path import WorkspacePathResolver, WorkspacePathViolation
from core.storage.base import StorageBackend

logger = logging.getLogger("agent_engine.patch.service")


class PatchLockManager:
    """Serializes in-process concurrent writers to the same project file."""

    def __init__(self) -> None:
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_lock(self, project_id: str, relative_path: str) -> threading.Lock:
        key = f"{project_id}:{relative_path}"
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


class PatchService:
    """Canonical service for applying safe, staged, recoverable patches."""

    def __init__(
        self,
        artifact_service: Optional[ArtifactService] = None,
        storage: Optional[StorageBackend] = None,
        recovery_dir: Optional[Path] = None,
    ) -> None:
        self.artifact_service = artifact_service
        self.storage = storage
        self._custom_recovery_dir = recovery_dir
        self.lock_manager = PatchLockManager()

        # Deterministic failure injection hooks for verification (CTO Review Section 23)
        self._fail_before_backup: bool = False
        self._fail_before_journal_fsync: bool = False
        self._fail_before_staged_write: bool = False
        self._fail_before_precommit_reval: bool = False
        self._fail_before_replace: bool = False
        self._fail_after_replace: bool = False

    def _get_recovery_dir(self, workspace_root: Path) -> Path:
        """Resolve persistent recovery directory for journals and backups."""
        if self._custom_recovery_dir is not None:
            d = Path(self._custom_recovery_dir)
        else:
            d = workspace_root / ".ae_patch_recovery"
        d.mkdir(parents=True, exist_ok=True)
        (d / "journals").mkdir(parents=True, exist_ok=True)
        (d / "backups").mkdir(parents=True, exist_ok=True)
        return d

    def apply_patch(
        self,
        operation: PatchOperation,
        workspace_root: Path,
    ) -> PatchResult:
        """Atomically and safely apply an untrusted proposed patch operation to workspace.

        Enforces containment, approval binding, pre-commit revalidation, backup,
        journaling, atomic replacement, and directory fsync.
        """
        start_time = time.time()
        workspace_root = Path(workspace_root).resolve()
        recovery_dir = self._get_recovery_dir(workspace_root)
        journal_dir = recovery_dir / "journals"
        backup_dir = recovery_dir / "backups"

        rel_str = str(operation.canonical_relative_path)
        file_lock = self.lock_manager.get_lock(operation.project_id, rel_str)

        with file_lock:
            # 1. Path Containment & Canonical Resolution (R2.5)
            resolver = WorkspacePathResolver(project_root=workspace_root)
            target_path: Path
            try:
                resolved = resolver.resolve(operation.canonical_relative_path)
                target_path = resolved.canonical_path
            except WorkspacePathViolation as ex:
                logger.warning(f"Patch path containment violation: {ex}")
                return self._create_result(
                    operation=operation,
                    success=False,
                    conflict_reason=PatchConflictReason.CONTAINMENT_VIOLATION,
                    message=f"Path containment violation: {ex}",
                    start_time=start_time,
                )

            # 2. Exact Approval Digest Verification (Section 13)
            if operation.approval_digest is not None:
                expected_digest = compute_patch_approval_digest(
                    project_id=operation.project_id,
                    canonical_relative_path=rel_str,
                    operation_type=operation.operation_type,
                    expected_content_hash=operation.expected_content_hash,
                    proposed_content_hash=operation.proposed_content_hash,
                )
                if operation.approval_digest != expected_digest:
                    logger.warning(
                        f"Patch approval digest mismatch for {rel_str}. "
                        f"Expected {expected_digest[:10]}, got {operation.approval_digest[:10]}"
                    )
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.APPROVAL_MISMATCH,
                        message="Approval digest mismatch: approval token does not bind proposed patch parameters.",
                        start_time=start_time,
                    )

            # 3. Resolve Proposed Content Bytes
            proposed_bytes: Optional[bytes] = None
            if operation.operation_type in (PatchOperationType.CREATE, PatchOperationType.UPDATE):
                if operation.proposed_content is not None:
                    proposed_bytes = operation.proposed_content
                elif operation.proposed_content_artifact_id is not None:
                    if self.artifact_service is None:
                        return self._create_result(
                            operation=operation,
                            success=False,
                            conflict_reason=PatchConflictReason.INTERNAL_ERROR,
                            message="ArtifactService required to resolve proposed_content_artifact_id.",
                            start_time=start_time,
                        )
                    art = self.artifact_service.get_artifact(operation.proposed_content_artifact_id)
                    if art is None:
                        return self._create_result(
                            operation=operation,
                            success=False,
                            conflict_reason=PatchConflictReason.INTERNAL_ERROR,
                            message=f"Artifact {operation.proposed_content_artifact_id} not found.",
                            start_time=start_time,
                        )
                    art_path = self.artifact_service.get_artifact_path(
                        operation.proposed_content_artifact_id
                    )
                    proposed_bytes = art_path.read_bytes()

                # Verify proposed content matches declared proposed_content_hash
                actual_proposed_hash = compute_content_hash(proposed_bytes or b"")
                if (
                    operation.proposed_content_hash
                    and actual_proposed_hash != operation.proposed_content_hash
                ):
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.HASH_VERIFICATION_FAILED,
                        message="Proposed content bytes do not match declared proposed_content_hash.",
                        start_time=start_time,
                    )

            # 4. Inspect Live State & Initial Pre-check (Section 12)
            live_exists = target_path.exists()
            live_hash = compute_file_hash(target_path) if live_exists else None

            if operation.operation_type == PatchOperationType.CREATE:
                if live_exists:
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.TARGET_EXISTS,
                        message=f"Target file already exists on disk: {rel_str}",
                        initial_hash=live_hash,
                        start_time=start_time,
                    )
            else:
                # UPDATE or DELETE
                if not live_exists:
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.TARGET_ABSENT,
                        message=f"Target file does not exist on disk: {rel_str}",
                        start_time=start_time,
                    )
                if live_hash != operation.expected_content_hash:
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.STALE_PATCH,
                        message=(
                            f"Target file modified (stale patch): expected {operation.expected_content_hash[:8]}, "
                            f"found {live_hash[:8] if live_hash else 'NONE'}."
                        ),
                        initial_hash=live_hash,
                        start_time=start_time,
                    )

            # 5. Durable Backup Before Mutation (Section 17)
            backup_file: Optional[Path] = None
            backup_id: Optional[str] = None
            if live_exists and operation.operation_type in (
                PatchOperationType.UPDATE,
                PatchOperationType.DELETE,
            ):
                if self._fail_before_backup:
                    raise RuntimeError("Injected failure before backup")
                backup_file = backup_dir / f"{operation.operation_id}.orig"
                orig_bytes = target_path.read_bytes()
                with open(backup_file, "wb") as bf:
                    bf.write(orig_bytes)
                    bf.flush()
                    os.fsync(bf.fileno())
                backup_id = f"backup-{operation.operation_id}"

            # 6. Journal Before Mutation (Section 16)
            journal_path = journal_dir / f"{operation.operation_id}.json"
            staged_path: Optional[Path] = None
            if operation.operation_type in (PatchOperationType.CREATE, PatchOperationType.UPDATE):
                target_path.parent.mkdir(parents=True, exist_ok=True)
                staged_path = (
                    target_path.parent / f".{target_path.name}.tmp.{operation.operation_id}"
                )

            journal_entry = PatchJournalEntry(
                operation_id=operation.operation_id,
                project_id=operation.project_id,
                canonical_relative_path=rel_str,
                operation_type=operation.operation_type.value,
                expected_exists=operation.expected_exists,
                expected_content_hash=operation.expected_content_hash,
                proposed_content_hash=operation.proposed_content_hash,
                backup_path=str(backup_file) if backup_file else None,
                staged_path=str(staged_path) if staged_path else None,
                target_path=str(target_path),
                state=PatchJournalState.PREPARED,
            )
            self._save_journal(journal_path, journal_entry)

            # 7. Write and Verify Staged Temporary File (Section 14)
            if operation.operation_type in (PatchOperationType.CREATE, PatchOperationType.UPDATE):
                if self._fail_before_staged_write:
                    raise RuntimeError("Injected failure before staged write")

                assert proposed_bytes is not None
                assert staged_path is not None
                with open(staged_path, "wb") as sf:
                    sf.write(proposed_bytes)
                    sf.flush()
                    os.fsync(sf.fileno())

                staged_hash = compute_file_hash(staged_path)
                if staged_hash != operation.proposed_content_hash:
                    # Clean staged file and abort
                    if staged_path.exists():
                        staged_path.unlink()
                    journal_entry.state = PatchJournalState.ABORTED
                    self._save_journal(journal_path, journal_entry)
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.HASH_VERIFICATION_FAILED,
                        message="Staged temporary file hash verification failed.",
                        initial_hash=live_hash,
                        start_time=start_time,
                    )

            # 8. Immediate Pre-Commit Revalidation (Section 12)
            if self._fail_before_precommit_reval:
                raise RuntimeError("Injected failure before pre-commit revalidation")

            recheck_exists = target_path.exists()
            recheck_hash = compute_file_hash(target_path) if recheck_exists else None

            if operation.operation_type == PatchOperationType.CREATE:
                if recheck_exists:
                    if staged_path and staged_path.exists():
                        staged_path.unlink()
                    journal_entry.state = PatchJournalState.ABORTED
                    self._save_journal(journal_path, journal_entry)
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.TARGET_EXISTS,
                        message=f"Target file appeared before commit: {rel_str}",
                        initial_hash=recheck_hash,
                        start_time=start_time,
                    )
            else:
                if not recheck_exists:
                    if staged_path and staged_path.exists():
                        staged_path.unlink()
                    journal_entry.state = PatchJournalState.ABORTED
                    self._save_journal(journal_path, journal_entry)
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.TARGET_ABSENT,
                        message=f"Target file disappeared before commit: {rel_str}",
                        start_time=start_time,
                    )
                if recheck_hash != operation.expected_content_hash:
                    if staged_path and staged_path.exists():
                        staged_path.unlink()
                    journal_entry.state = PatchJournalState.ABORTED
                    self._save_journal(journal_path, journal_entry)
                    return self._create_result(
                        operation=operation,
                        success=False,
                        conflict_reason=PatchConflictReason.STALE_PATCH,
                        message=(
                            f"Target file modified before commit (stale patch): expected "
                            f"{operation.expected_content_hash[:8]}, found {recheck_hash[:8] if recheck_hash else 'NONE'}."
                        ),
                        initial_hash=recheck_hash,
                        start_time=start_time,
                    )

            # Transition journal to APPLYING
            journal_entry.state = PatchJournalState.APPLYING
            self._save_journal(journal_path, journal_entry)

            if self._fail_before_replace:
                raise RuntimeError("Injected failure before atomic replace")

            # 9. Atomic Replacement & Directory Fsync (Section 14 & 15)
            if operation.operation_type in (PatchOperationType.CREATE, PatchOperationType.UPDATE):
                assert staged_path is not None
                # Preserve file permissions if updating
                if live_exists:
                    try:
                        orig_stat = target_path.stat()
                        os.chmod(staged_path, orig_stat.st_mode & 0o777)
                    except Exception:
                        pass
                os.replace(staged_path, target_path)
            elif operation.operation_type == PatchOperationType.DELETE:
                target_path.unlink()

            # POSIX directory fsync
            self._fsync_directory(target_path.parent)

            if self._fail_after_replace:
                raise RuntimeError("Injected failure immediately after atomic replace")

            # 10. Finalize Journal to COMMITTED
            journal_entry.state = PatchJournalState.COMMITTED
            self._save_journal(journal_path, journal_entry)

            resulting_hash = compute_file_hash(target_path) if target_path.exists() else None

            result = self._create_result(
                operation=operation,
                success=True,
                initial_hash=live_hash,
                resulting_hash=resulting_hash,
                backup_id=backup_id,
                journal_id=operation.operation_id,
                message=f"Patch {operation.operation_id} committed successfully.",
                start_time=start_time,
            )
            return result

    def recover_interrupted_patches(self, workspace_root: Path) -> List[PatchResult]:
        """Perform idempotent crash recovery on startup or recovery inspection (CTO Review Section 18).

        Reconciles uncommitted or interrupted journals against live disk hashes.
        Never resolves an ambiguous crash state by blindly restoring an old backup
        over a newer human edit.
        """
        recovery_dir = self._get_recovery_dir(workspace_root)
        journal_dir = recovery_dir / "journals"
        results: List[PatchResult] = []

        for j_file in sorted(journal_dir.glob("*.json")):
            try:
                data = json.loads(j_file.read_text(encoding="utf-8"))
                entry = PatchJournalEntry.from_dict(data)
            except Exception as e:
                logger.error(f"Failed to parse journal {j_file}: {e}")
                continue

            if entry.state in (PatchJournalState.COMMITTED, PatchJournalState.ABORTED):
                continue

            # Interrupted write in progress (PREPARED or APPLYING)
            target = Path(entry.target_path) if entry.target_path else None
            if target is None:
                continue

            rel_str = entry.canonical_relative_path
            current_exists = target.exists()
            current_hash = compute_file_hash(target) if current_exists else None
            staged = Path(entry.staged_path) if entry.staged_path else None

            # Case 1: Target equals proposed hash -> Replace succeeded before crash!
            if entry.proposed_content_hash and current_hash == entry.proposed_content_hash:
                if staged and staged.exists():
                    try:
                        staged.unlink()
                    except Exception:
                        pass
                entry.state = PatchJournalState.COMMITTED
                self._save_journal(j_file, entry)
                results.append(
                    PatchResult(
                        operation_id=entry.operation_id,
                        project_id=entry.project_id,
                        canonical_relative_path=rel_str,
                        operation_type=PatchOperationType(entry.operation_type),
                        success=True,
                        initial_hash=entry.expected_content_hash,
                        resulting_hash=current_hash,
                        journal_id=entry.operation_id,
                        message="Reconciled successfully: atomic rename was complete on disk.",
                    )
                )
                continue

            # Case 2: Target equals expected original hash (or is absent for CREATE)
            if (not entry.expected_exists and not current_exists) or (
                entry.expected_exists and current_hash == entry.expected_content_hash
            ):
                # Safe abort/cleanup
                if staged and staged.exists():
                    try:
                        staged.unlink()
                    except Exception:
                        pass
                entry.state = PatchJournalState.ABORTED
                self._save_journal(j_file, entry)
                results.append(
                    PatchResult(
                        operation_id=entry.operation_id,
                        project_id=entry.project_id,
                        canonical_relative_path=rel_str,
                        operation_type=PatchOperationType(entry.operation_type),
                        success=False,
                        conflict_reason=PatchConflictReason.INTERNAL_ERROR,
                        initial_hash=current_hash,
                        resulting_hash=current_hash,
                        journal_id=entry.operation_id,
                        message="Safely aborted interrupted patch: original target file remained intact.",
                    )
                )
                continue

            # Case 3: Ambiguous state — target contains a third/human value!
            # Invariant: NEVER overwrite newer human edits!
            entry.state = PatchJournalState.RECOVERY_REQUIRED
            self._save_journal(j_file, entry)
            logger.critical(
                f"Patch crash recovery detected ambiguous file state for {rel_str}. "
                f"Target contains unknown hash {current_hash[:8] if current_hash else 'ABSENT'}. "
                f"Halting recovery without overwriting to preserve human edits (CTO Review Section 18)."
            )
            results.append(
                PatchResult(
                    operation_id=entry.operation_id,
                    project_id=entry.project_id,
                    canonical_relative_path=rel_str,
                    operation_type=PatchOperationType(entry.operation_type),
                    success=False,
                    conflict_reason=PatchConflictReason.RECOVERY_REQUIRED,
                    initial_hash=current_hash,
                    resulting_hash=current_hash,
                    journal_id=entry.operation_id,
                    message="Ambiguous crash state detected: live file modified by human; original retained untouched.",
                )
            )

        return results

    def _save_journal(self, path: Path, entry: PatchJournalEntry) -> None:
        """Atomically persist journal entry with fsync."""
        entry.updated_at = time.time()
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
        content = json.dumps(entry.to_dict(), indent=2).encode("utf-8")
        with open(tmp_path, "wb") as f:
            f.write(content)
            f.flush()
            if self._fail_before_journal_fsync:
                raise RuntimeError("Injected failure before journal fsync")
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        self._fsync_directory(path.parent)

    def _fsync_directory(self, dir_path: Path) -> None:
        """POSIX directory fsync for metadata durability."""
        try:
            if hasattr(os, "O_DIRECTORY"):
                fd = os.open(str(dir_path), os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except Exception:
            pass

    def _create_result(
        self,
        operation: PatchOperation,
        success: bool,
        start_time: float,
        conflict_reason: Optional[PatchConflictReason] = None,
        message: str = "",
        initial_hash: Optional[str] = None,
        resulting_hash: Optional[str] = None,
        backup_id: Optional[str] = None,
        journal_id: Optional[str] = None,
    ) -> PatchResult:
        duration = time.time() - start_time
        res = PatchResult(
            operation_id=operation.operation_id,
            project_id=operation.project_id,
            canonical_relative_path=str(operation.canonical_relative_path),
            operation_type=operation.operation_type,
            success=success,
            conflict_reason=conflict_reason,
            message=message,
            initial_hash=initial_hash,
            resulting_hash=resulting_hash,
            backup_id=backup_id,
            journal_id=journal_id or operation.operation_id,
            duration_seconds=round(duration, 4),
        )

        # Record to audit ledger (CTO Review Section 22)
        if self.storage and hasattr(self.storage, "record_patch_execution"):
            record = PatchExecutionRecord(
                operation_id=operation.operation_id,
                project_id=operation.project_id,
                canonical_relative_path=str(operation.canonical_relative_path),
                operation_type=operation.operation_type.value,
                expected_content_hash=operation.expected_content_hash,
                resulting_hash=resulting_hash,
                approval_id=operation.approval_id,
                success=success,
                conflict_reason=conflict_reason.value if conflict_reason else None,
                journal_state=PatchJournalState.COMMITTED.value
                if success
                else PatchJournalState.ABORTED.value,
                duration_seconds=res.duration_seconds,
                timestamp=time.time(),
            )
            try:
                self.storage.record_patch_execution(record)
            except Exception as e:
                logger.debug(f"Failed to record patch execution ledger: {e}")

        return res
