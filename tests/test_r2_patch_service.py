"""tests/test_r2_patch_service.py

Dedicated precision test suite for Task R2.10 Safe Staged Patch Application.
Covers all requirements from CTO Review Sections 10 through 23 and Closure Items 1 through 7.

Invariants Tested:
1. Precise S1 Guarantee: Agent Engine rejects patches whose expected source state
   no longer matches at the final pre-commit validation boundary. Agent Engine writers
   are serialized. A residual external-process race remains where the host filesystem
   does not offer an atomic content-compare-and-swap primitive.
2. CREATE Atomicity: renameat2(..., RENAME_NOREPLACE) guarantees atomic no-clobber.
   Adversarial race test proves concurrent creator file is never overwritten.
3. Absence vs Empty file semantics: absence is distinct from empty file.
4. Exact byte hashing: no whitespace, encoding, or line ending normalization.
5. Immediate pre-commit revalidation: re-checks disk state immediately prior to commit.
6. Exact approval binding: digest covers project, path, op, expected exists, expected hash, proposed hash.
7. Approval precedence & consumption: verified and consumed before commit; replay is blocked.
8. Artifact byte re-verification: actual bytes re-read and hashed before application.
9. Hardened recovery backups: project-scoped, operation-indexed, collision-safe, 0o600 permissions.
10. DELETE ordering: durable backup and journal exist before target is unlinked.
11. Deterministic fault-injection: 8 critical failure boundaries tested.
12. Idempotent crash recovery: ambiguous human edits are never overwritten (RECOVERY_REQUIRED).
13. Target lock serialization for concurrent writers.
14. Audit ledger records hashes/references, never full file contents or secrets.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from typing import Any, List
import pytest

from core.artifacts.service import ArtifactService
from core.patch.models import (
    PatchConflictReason,
    PatchOperation,
    PatchOperationType,
    compute_content_hash,
    compute_patch_approval_digest,
    generate_patch_operation_id,
)
from core.patch.service import (
    CreateAtomicityUnavailableError,
    PatchService,
)


class MockStorageBackend:
    """Mock storage capturing patch audit ledger records and supporting atomic approval consumption."""

    def __init__(self) -> None:
        self.patch_records: List[Any] = []
        self.approvals: dict[str, dict[str, Any]] = {}

    def record_patch_execution(self, record: Any) -> None:
        self.patch_records.append(record)

    def atomic_consume_approval(self, approval_id: str, token_verifier: str, now: float) -> bool:
        appr = self.approvals.get(approval_id)
        if not appr:
            return True  # If unmanaged, allow consumption
        if appr.get("status") == "consumed":
            return False
        appr["status"] = "consumed"
        appr["consumed_at"] = now
        return True


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def patch_service(temp_workspace: Path) -> PatchService:
    return PatchService(recovery_dir=temp_workspace / ".ae_patch_recovery")


# --- 1. CORE CRUD & S1 GUARANTEE SCENARIOS ---


def test_01_unchanged_expected_file_update_succeeds(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 1: UPDATE on unchanged file succeeds atomically, creates backup, and produces resulting hash."""
    target_file = temp_workspace / "config.json"
    orig_content = b'{"version": 1, "name": "agent_engine"}\n'
    target_file.write_bytes(orig_content)
    orig_hash = compute_content_hash(orig_content)

    new_content = b'{"version": 2, "name": "agent_engine"}\n'
    new_hash = compute_content_hash(new_content)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("config.json"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=new_content,
        proposed_content_hash=new_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True
    assert res.conflict_reason is None
    assert res.initial_hash == orig_hash
    assert res.resulting_hash == new_hash
    assert target_file.read_bytes() == new_content

    # Check project-scoped, collision-safe backup exists (Closure Item 4)
    recovery_dir = temp_workspace / ".ae_patch_recovery"
    backup_file = recovery_dir / "backups" / "proj-1" / f"{op.operation_id}.bak"
    assert backup_file.exists()
    assert backup_file.read_bytes() == orig_content
    assert res.backup_id == f"bak:proj-1:{op.operation_id}"


def test_02_changed_expected_file_stale_patch_rejected(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 2: STALE_PATCH: When a human edits the target file, older patch is rejected and human edit is untouched."""
    target_file = temp_workspace / "app.py"
    initial_content = b"def run():\n    return 42\n"
    initial_hash = compute_content_hash(initial_content)

    # Human edited file after proposal was created
    human_edited_content = b"def run():\n    # Human edit\n    return 100\n"
    target_file.write_bytes(human_edited_content)
    human_hash = compute_content_hash(human_edited_content)

    ai_proposed_content = b"def run():\n    return 999\n"

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("app.py"),
        expected_exists=True,
        expected_content_hash=initial_hash,
        proposed_content=ai_proposed_content,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.STALE_PATCH
    assert res.initial_hash == human_hash
    # Invariant: Human edit remains untouched
    assert target_file.read_bytes() == human_edited_content


def test_03_create_new_file_succeeds(patch_service: PatchService, temp_workspace: Path):
    """Scenario 3: CREATE on non-existent file succeeds and produces resulting hash."""
    target_file = temp_workspace / "new_module.py"
    assert not target_file.exists()

    content = b"# New module\nPI = 3.14159\n"
    expected_hash = compute_content_hash(content)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=Path("new_module.py"),
        expected_exists=False,
        expected_content_hash=None,
        proposed_content=content,
        proposed_content_hash=expected_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True
    assert res.conflict_reason is None
    assert res.initial_hash is None
    assert res.resulting_hash == expected_hash
    assert target_file.read_bytes() == content


def test_04_create_on_existing_file_rejected_target_exists(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 4: TARGET_EXISTS: Attempting to CREATE a file that already exists fails closed."""
    target_file = temp_workspace / "already_exists.txt"
    target_file.write_bytes(b"existing data\n")

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=Path("already_exists.txt"),
        expected_exists=False,
        expected_content_hash=None,
        proposed_content=b"new data\n",
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.TARGET_EXISTS
    assert target_file.read_bytes() == b"existing data\n"


def test_05_delete_existing_file_succeeds(patch_service: PatchService, temp_workspace: Path):
    """Scenario 5: DELETE on existing file removes target and preserves durable backup."""
    target_file = temp_workspace / "obsolete.txt"
    orig_content = b"to be deleted\n"
    target_file.write_bytes(orig_content)
    orig_hash = compute_content_hash(orig_content)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.DELETE,
        canonical_relative_path=Path("obsolete.txt"),
        expected_exists=True,
        expected_content_hash=orig_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True
    assert res.conflict_reason is None
    assert not target_file.exists()
    assert res.resulting_hash is None

    # Check project-scoped backup was preserved (Closure Items 4 & 6)
    recovery_dir = temp_workspace / ".ae_patch_recovery"
    backup_file = recovery_dir / "backups" / "proj-1" / f"{op.operation_id}.bak"
    assert backup_file.exists()
    assert backup_file.read_bytes() == orig_content


def test_06_delete_on_stale_file_rejected(patch_service: PatchService, temp_workspace: Path):
    """Scenario 6: STALE_PATCH on DELETE: Attempting to delete a file modified since proposal fails."""
    target_file = temp_workspace / "obsolete.txt"
    initial_content = b"original content\n"
    target_file.write_bytes(initial_content)
    orig_hash = compute_content_hash(initial_content)

    # Human edited file
    target_file.write_bytes(b"human modified content\n")

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.DELETE,
        canonical_relative_path=Path("obsolete.txt"),
        expected_exists=True,
        expected_content_hash=orig_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.STALE_PATCH
    assert target_file.exists()
    assert target_file.read_bytes() == b"human modified content\n"


# --- 2. CREATE ATOMICITY & ADVERSARIAL RACE (Closure Item 1) ---


def test_07_adversarial_create_race_atomic_no_clobber(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 7 (CTO Review Closure Item 1 Required Adversarial Test):
    Target absent during initial validation
    -> target absent during normal preparation
    -> external file created immediately before commit
    -> CREATE fails as conflict (TARGET_EXISTS)
    -> external content remains byte-identical.
    """
    target_file = temp_workspace / "race_target.txt"
    assert not target_file.exists()

    ai_content = b"AI generated content that must not overwrite external human file\n"
    external_human_content = b"EXTERNAL HUMAN PROCESS CONTENT CREATED DURING PRECOMMIT WINDOW\n"

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-race",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=Path("race_target.txt"),
        expected_exists=False,
        expected_content_hash=None,
        proposed_content=ai_content,
        proposed_content_hash=compute_content_hash(ai_content),
    )

    # We inject an external write immediately before commit by wrapping atomic_commit_create
    import core.patch.service as svc_mod

    real_atomic_commit_create = svc_mod.atomic_commit_create

    def raced_atomic_commit_create(staged: Path, target: Path):
        # Simulate external process winning the race right before renameat2
        target.write_bytes(external_human_content)
        # Now call real renameat2(RENAME_NOREPLACE) -> must detect target exists and raise FileExistsError
        return real_atomic_commit_create(staged, target)

    svc_mod.atomic_commit_create = raced_atomic_commit_create
    try:
        res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    finally:
        svc_mod.atomic_commit_create = real_atomic_commit_create

    # Verified: CREATE fails as conflict
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.TARGET_EXISTS
    assert "atomic no-clobber prevented overwrite" in res.message

    # Verified: External content remains byte-identical!
    assert target_file.exists()
    assert target_file.read_bytes() == external_human_content


def test_08_create_atomicity_unavailable_fails_closed(
    patch_service: PatchService, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 8: Non-Linux platform or unsupported renameat2 raises CREATE_ATOMICITY_UNAVAILABLE fail-closed."""
    target_file = temp_workspace / "platform_test.txt"
    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=Path("platform_test.txt"),
        expected_exists=False,
        expected_content_hash=None,
        proposed_content=b"content\n",
    )

    # Simulate non-Linux OS
    import core.patch.service as svc_mod

    def fake_atomic_commit(staged, target):
        raise CreateAtomicityUnavailableError("CREATE_ATOMICITY_UNAVAILABLE: non-Linux test")

    monkeypatch.setattr(svc_mod, "atomic_commit_create", fake_atomic_commit)

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.CREATE_ATOMICITY_UNAVAILABLE
    assert not target_file.exists()


# --- 3. APPROVAL PRECEDENCE, CONSUMPTION & INTEGRITY (Closure Item 3) ---


def test_09_approval_binding_expected_exists_and_hashes(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 9: Approval binds expected_exists, expected_hash, and proposed_hash."""
    target_file = temp_workspace / "secure.txt"
    orig_bytes = b"orig\n"
    target_file.write_bytes(orig_bytes)
    orig_hash = compute_content_hash(orig_bytes)

    new_bytes = b"approved change\n"
    new_hash = compute_content_hash(new_bytes)

    valid_digest = compute_patch_approval_digest(
        project_id="proj-sec",
        canonical_relative_path="secure.txt",
        operation_type=PatchOperationType.UPDATE,
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content_hash=new_hash,
    )

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-sec",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("secure.txt"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=new_bytes,
        proposed_content_hash=new_hash,
        approval_id="appr-123",
        approval_digest=valid_digest,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True
    assert target_file.read_bytes() == new_bytes


def test_10_tampered_proposed_hash_invalidates_approval(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 10: Same target + different proposed hash causes APPROVAL_MISMATCH."""
    target_file = temp_workspace / "secure.txt"
    orig_bytes = b"orig\n"
    target_file.write_bytes(orig_bytes)
    orig_hash = compute_content_hash(orig_bytes)

    approved_bytes = b"approved change\n"
    approved_hash = compute_content_hash(approved_bytes)

    tampered_bytes = b"unapproved backdoor injection\n"
    tampered_hash = compute_content_hash(tampered_bytes)

    approval_digest = compute_patch_approval_digest(
        project_id="proj-sec",
        canonical_relative_path="secure.txt",
        operation_type=PatchOperationType.UPDATE,
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content_hash=approved_hash,
    )

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-sec",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("secure.txt"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=tampered_bytes,
        proposed_content_hash=tampered_hash,
        approval_id="appr-123",
        approval_digest=approval_digest,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.APPROVAL_MISMATCH
    assert target_file.read_bytes() == orig_bytes


def test_11_artifact_bytes_mismatch_rejected(
    patch_service: PatchService, temp_workspace: Path, tmp_path: Path
):
    """Scenario 11 (Closure Item 3): Re-read artifact bytes from ArtifactService; if bytes differ from approved hash, reject."""
    from core.storage.sqlite import SQLiteBackend

    db = SQLiteBackend(":memory:")
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    art_service = ArtifactService(storage=db, base_artifacts_dir=str(art_dir))
    patch_service.artifact_service = art_service

    # Create artifact with initial content (large enough to exceed inline threshold or forced file storage)
    from core.artifacts.models import ArtifactStorageKind

    art = art_service.create_artifact(
        project_id="proj-1",
        execution_id="exec-1",
        name="patch_data.py",
        content=b"original approved code" * 1000,
        storage_kind=ArtifactStorageKind.FILESYSTEM,
    )
    approved_hash = art.sha256_hash

    # Now tamper with artifact bytes on disk directly
    full_art = art_service.get_artifact(art.id, project_id="proj-1")
    assert full_art is not None
    payload_file = Path(art_service.base_artifacts_dir) / full_art.file_path
    payload_file.write_bytes(b"tampered unapproved code" * 1000)

    target_file = temp_workspace / "dest.py"
    target_file.write_bytes(b"baseline")
    base_hash = compute_content_hash(b"baseline")

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("dest.py"),
        expected_exists=True,
        expected_content_hash=base_hash,
        proposed_content_artifact_id=art.id,
        proposed_content_hash=approved_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.HASH_VERIFICATION_FAILED
    assert target_file.read_bytes() == b"baseline"


def test_12_consumed_approval_cannot_apply_second_patch(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 12 (Closure Item 3): Consumed approval cannot be reused to apply a second patch."""
    mock_storage = MockStorageBackend()
    patch_service.storage = mock_storage

    target_file = temp_workspace / "app.txt"
    target_file.write_bytes(b"v1")
    v1_hash = compute_content_hash(b"v1")
    v2_hash = compute_content_hash(b"v2")

    digest = compute_patch_approval_digest(
        project_id="proj-1",
        canonical_relative_path="app.txt",
        operation_type=PatchOperationType.UPDATE,
        expected_exists=True,
        expected_content_hash=v1_hash,
        proposed_content_hash=v2_hash,
    )

    op1 = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("app.txt"),
        expected_exists=True,
        expected_content_hash=v1_hash,
        proposed_content=b"v2",
        proposed_content_hash=v2_hash,
        approval_id="appr-reuse-test",
        approval_digest=digest,
    )

    # First apply succeeds
    res1 = patch_service.apply_patch(op1, workspace_root=temp_workspace)
    assert res1.success is True
    assert target_file.read_bytes() == b"v2"

    # Second apply with same approval_id must be rejected fail-closed
    v3_hash = compute_content_hash(b"v3")
    digest2 = compute_patch_approval_digest(
        project_id="proj-1",
        canonical_relative_path="app.txt",
        operation_type=PatchOperationType.UPDATE,
        expected_exists=True,
        expected_content_hash=v2_hash,
        proposed_content_hash=v3_hash,
    )
    op2 = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("app.txt"),
        expected_exists=True,
        expected_content_hash=v2_hash,
        proposed_content=b"v3",
        proposed_content_hash=v3_hash,
        approval_id="appr-reuse-test",  # Replayed token!
        approval_digest=digest2,
    )

    res2 = patch_service.apply_patch(op2, workspace_root=temp_workspace)
    assert res2.success is False
    assert res2.conflict_reason == PatchConflictReason.APPROVAL_ALREADY_CONSUMED
    assert target_file.read_bytes() == b"v2"


# --- 4. HARDENED RECOVERY STORAGE & COLLISION SAFETY (Closure Item 4) ---


def test_13_hardened_recovery_backup_storage(patch_service: PatchService, temp_workspace: Path):
    """Scenario 13 (Closure Item 4): Backups are operation-scoped, collision-safe, project-scoped, and mode 0o600."""
    target_file = temp_workspace / "data.txt"
    target_file.write_bytes(b"sensitive project data\n")
    orig_hash = compute_content_hash(b"sensitive project data\n")

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-alpha",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("data.txt"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new data\n",
        proposed_content_hash=compute_content_hash(b"new data\n"),
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True

    # Backup must reside in .ae_patch_recovery/backups/proj-alpha/<op_id>.bak
    recovery_dir = temp_workspace / ".ae_patch_recovery"
    proj_backup_dir = recovery_dir / "backups" / "proj-alpha"
    assert proj_backup_dir.exists()
    backup_file = proj_backup_dir / f"{op.operation_id}.bak"
    assert backup_file.exists()
    assert backup_file.read_bytes() == b"sensitive project data\n"

    # Check file permissions (0o600)
    file_mode = backup_file.stat().st_mode & 0o777
    assert file_mode == 0o600

    # Public result exposes only opaque reference, not host path
    assert res.backup_id == f"bak:proj-alpha:{op.operation_id}"


# --- 5. DETERMINISTIC FAULT-INJECTION BOUNDARY TESTS (Closure Item 5) ---


def test_14_fault_injection_01_backup_failure(patch_service: PatchService, temp_workspace: Path):
    """Scenario 14: Failure during backup persistence leaves original target file completely untouched."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original critical content\n")
    orig_hash = compute_content_hash(b"original critical content\n")

    patch_service._fail_during_backup = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new content\n",
    )

    with pytest.raises(RuntimeError, match="Injected failure during backup persistence"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    # Invariant: Original file remains completely untouched
    assert target_file.read_bytes() == b"original critical content\n"


def test_15_fault_injection_02_prepared_journal_failure(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 15: Failure during PREPARED journal persistence leaves original file untouched."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original critical content\n")
    orig_hash = compute_content_hash(b"original critical content\n")

    patch_service._fail_during_prepared_journal = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new content\n",
    )

    with pytest.raises(RuntimeError, match="Injected failure during PREPARED journal"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    assert target_file.read_bytes() == b"original critical content\n"


def test_16_fault_injection_03_staged_write_failure(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 16: Failure during staged-file write leaves original file untouched."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original critical content\n")
    orig_hash = compute_content_hash(b"original critical content\n")

    patch_service._fail_during_staged_write = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new content\n",
    )

    with pytest.raises(RuntimeError, match="Injected failure during staged write"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    assert target_file.read_bytes() == b"original critical content\n"


def test_17_fault_injection_04_staged_fsync_failure(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 17: Failure during staged-file fsync leaves original file untouched."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original critical content\n")
    orig_hash = compute_content_hash(b"original critical content\n")

    patch_service._fail_during_staged_fsync = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new content\n",
    )

    with pytest.raises(RuntimeError, match="Injected failure during staged fsync"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    assert target_file.read_bytes() == b"original critical content\n"


def test_18_fault_injection_05_precommit_reval_failure(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 18: Failure during pre-commit revalidation leaves original file untouched."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original critical content\n")
    orig_hash = compute_content_hash(b"original critical content\n")

    patch_service._fail_during_precommit_revalidation = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new content\n",
    )

    with pytest.raises(RuntimeError, match="Injected failure during pre-commit revalidation"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    assert target_file.read_bytes() == b"original critical content\n"


def test_19_fault_injection_06_commit_failure(patch_service: PatchService, temp_workspace: Path):
    """Scenario 19: Failure during commit leaves original file untouched."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original critical content\n")
    orig_hash = compute_content_hash(b"original critical content\n")

    patch_service._fail_during_commit = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new content\n",
    )

    with pytest.raises(RuntimeError, match="Injected failure during filesystem commit"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    assert target_file.read_bytes() == b"original critical content\n"

    # Startup recovery aborts uncommitted patch cleanly
    results = patch_service.recover_interrupted_patches(workspace_root=temp_workspace)
    assert len(results) == 1
    assert results[0].success is False
    assert target_file.read_bytes() == b"original critical content\n"


def test_20_fault_injection_07_dir_fsync_failure_post_commit_reconciliation(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 20: Failure during directory fsync (post-commit) is reconciled to COMMITTED upon recovery."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original content\n")
    orig_hash = compute_content_hash(b"original content\n")

    proposed_content = b"new committed content\n"
    proposed_hash = compute_content_hash(proposed_content)

    patch_service._fail_during_dir_fsync = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=proposed_content,
        proposed_content_hash=proposed_hash,
    )

    with pytest.raises(RuntimeError, match="Injected failure during directory fsync"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    # Mutation happened on disk before dir fsync failure
    assert target_file.read_bytes() == proposed_content

    # Startup recovery detects target matches proposed_content_hash -> reconciles to COMMITTED
    results = patch_service.recover_interrupted_patches(workspace_root=temp_workspace)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].resulting_hash == proposed_hash


def test_21_fault_injection_08_committed_journal_failure_post_commit_reconciliation(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 21: Failure during final COMMITTED journal persistence is reconciled to COMMITTED upon recovery."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original content\n")
    orig_hash = compute_content_hash(b"original content\n")

    proposed_content = b"new committed content\n"
    proposed_hash = compute_content_hash(proposed_content)

    patch_service._fail_during_committed_journal = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=proposed_content,
        proposed_content_hash=proposed_hash,
    )

    with pytest.raises(RuntimeError, match="Injected failure during COMMITTED journal"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    assert target_file.read_bytes() == proposed_content

    # Startup recovery reconciles to COMMITTED
    results = patch_service.recover_interrupted_patches(workspace_root=temp_workspace)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].resulting_hash == proposed_hash


def test_22_recovery_ambiguous_state_halts_with_recovery_required(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 22 (Closure Item 5): Ambiguous crash state (target has newer human content) halts fail-closed with RECOVERY_REQUIRED."""
    target_file = temp_workspace / "critical.py"
    target_file.write_bytes(b"original content\n")
    orig_hash = compute_content_hash(b"original content\n")

    patch_service._fail_during_commit = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("critical.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"ai content\n",
        proposed_content_hash=compute_content_hash(b"ai content\n"),
    )

    with pytest.raises(RuntimeError):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    # Now simulate a human editing the file while engine was crashed
    target_file.write_bytes(b"NEWER HUMAN CONTENT EDITED WHILE ENGINE WAS DOWN\n")

    # Recovery must NOT overwrite human work; must halt with RECOVERY_REQUIRED
    results = patch_service.recover_interrupted_patches(workspace_root=temp_workspace)
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].conflict_reason == PatchConflictReason.RECOVERY_REQUIRED
    assert target_file.read_bytes() == b"NEWER HUMAN CONTENT EDITED WHILE ENGINE WAS DOWN\n"


# --- 6. DELETE ORDERING & CRASH RECOVERY (Closure Item 6) ---


def test_23_delete_ordering_and_recovery(patch_service: PatchService, temp_workspace: Path):
    """Scenario 23 (Closure Item 6): DELETE verifies backup exists before target is unlinked; recovery handles interrupted delete."""
    target_file = temp_workspace / "to_delete.txt"
    orig_bytes = b"important file to delete\n"
    target_file.write_bytes(orig_bytes)
    orig_hash = compute_content_hash(orig_bytes)

    # Fail during commit (before unlink)
    patch_service._fail_during_commit = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-del",
        operation_type=PatchOperationType.DELETE,
        canonical_relative_path=Path("to_delete.txt"),
        expected_exists=True,
        expected_content_hash=orig_hash,
    )

    with pytest.raises(RuntimeError):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    # Backup was created before the failure occurred
    recovery_dir = temp_workspace / ".ae_patch_recovery"
    backup_file = recovery_dir / "backups" / "proj-del" / f"{op.operation_id}.bak"
    assert backup_file.exists()
    assert backup_file.read_bytes() == orig_bytes

    # Original file is still intact
    assert target_file.exists()
    assert target_file.read_bytes() == orig_bytes

    # Recovery aborts cleanly
    results = patch_service.recover_interrupted_patches(workspace_root=temp_workspace)
    assert len(results) == 1
    assert results[0].success is False
    assert target_file.exists()


# --- 7. CONCURRENCY & AUDIT LEDGER (Closure Item 7) ---


def test_24_concurrent_patch_applications_serialized(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 24: Concurrent patch applications to the same file are serialized by PatchLockManager."""
    target_file = temp_workspace / "shared.txt"
    target_file.write_bytes(b"initial\n")
    init_hash = compute_content_hash(b"initial\n")

    op1 = PatchOperation(
        operation_id="patch-thread-1",
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("shared.txt"),
        expected_exists=True,
        expected_content_hash=init_hash,
        proposed_content=b"content from thread 1\n",
        proposed_content_hash=compute_content_hash(b"content from thread 1\n"),
    )

    op2 = PatchOperation(
        operation_id="patch-thread-2",
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("shared.txt"),
        expected_exists=True,
        expected_content_hash=init_hash,
        proposed_content=b"content from thread 2\n",
        proposed_content_hash=compute_content_hash(b"content from thread 2\n"),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(patch_service.apply_patch, op1, temp_workspace)
        f2 = executor.submit(patch_service.apply_patch, op2, temp_workspace)
        r1 = f1.result()
        r2 = f2.result()

    # Exactly one succeeded and one failed with STALE_PATCH
    statuses = [r1.success, r2.success]
    assert statuses.count(True) == 1
    assert statuses.count(False) == 1
    failed_res = r1 if not r1.success else r2
    assert failed_res.conflict_reason == PatchConflictReason.STALE_PATCH


def test_25_audit_ledger_contains_no_full_content_or_secrets(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 25 (Closure Item 7): Public audit ledger contains hashes and IDs, never full source contents or secrets."""
    mock_storage = MockStorageBackend()
    patch_service.storage = mock_storage

    target_file = temp_workspace / "secret_file.py"
    target_file.write_bytes(b"api_key = 'sk-12345'\n")
    orig_hash = compute_content_hash(b"api_key = 'sk-12345'\n")

    new_content = b"api_key = 'sk-67890'\n"
    new_hash = compute_content_hash(new_content)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-ledger",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("secret_file.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=new_content,
        proposed_content_hash=new_hash,
        approval_id="appr-audit-test",
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True

    # Check mock storage captured PatchExecutionRecord
    assert len(mock_storage.patch_records) == 1
    rec = mock_storage.patch_records[0]
    rec_dict = rec.to_dict()

    # Verify audit record does not leak content, backup bytes, or secrets
    serialized = json.dumps(rec_dict)
    assert "sk-12345" not in serialized
    assert "sk-67890" not in serialized
    assert "api_key" not in serialized

    # Verify hashes and metadata are present
    assert rec_dict["expected_content_hash"] == orig_hash
    assert rec_dict["resulting_hash"] == new_hash
    assert rec_dict["operation_id"] == op.operation_id
    assert rec_dict["project_id"] == "proj-ledger"
    assert rec_dict["approval_id"] == "appr-audit-test"
    assert rec_dict["journal_state"] == "committed"
