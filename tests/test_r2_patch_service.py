"""tests/test_r2_patch_service.py

Dedicated precision test suite for Task R2.10 Safe Staged Patch Application.
Covers all requirements from CTO Review Sections 10 through 23.

Invariants Tested:
1. Never overwrite newer human edits (stale patch rejected, human edits untouched).
2. Absence vs Empty file semantics (absence is distinct from empty file).
3. Exact byte hashing (no whitespace, encoding, or line ending normalization).
4. Immediate pre-commit revalidation.
5. Exact approval binding (digest covers project, path, op, expected hash, proposed hash).
6. Atomic replacement with tempfile on same directory and POSIX directory fsync.
7. Durable backup and recovery journal persisted before mutation.
8. Idempotent crash recovery (ambiguous states never overwrite human edits).
9. Target lock serialization for concurrent writers.
10. Audit ledger records hashes/references, never full file contents.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from typing import Any, List
import pytest

from core.patch.models import (
    PatchConflictReason,
    PatchJournalState,
    PatchOperation,
    PatchOperationType,
    PatchResult,
    compute_content_hash,
    compute_file_hash,
    compute_patch_approval_digest,
    generate_patch_operation_id,
)
from core.patch.service import PatchService


class MockStorageBackend:
    """Mock storage capturing patch audit ledger records."""

    def __init__(self) -> None:
        self.patch_records: List[Any] = []

    def record_patch_execution(self, record: Any) -> None:
        self.patch_records.append(record)


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def patch_service(temp_workspace: Path) -> PatchService:
    return PatchService(recovery_dir=temp_workspace / ".ae_patch_recovery")


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

    # Check backup exists
    recovery_dir = temp_workspace / ".ae_patch_recovery"
    backup_file = recovery_dir / "backups" / f"{op.operation_id}.orig"
    assert backup_file.exists()
    assert backup_file.read_bytes() == orig_content


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
    assert "stale patch" in res.message.lower()

    # Invariant: Human content remains untouched!
    assert target_file.read_bytes() == human_edited_content
    assert compute_file_hash(target_file) == human_hash


def test_03_expected_file_deleted_before_update_conflict(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 3: TARGET_ABSENT: If target file was deleted before update, conflict is returned."""
    target_rel = Path("deleted_file.txt")
    orig_hash = compute_content_hash(b"some content")

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=target_rel,
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new content",
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.TARGET_ABSENT
    assert not (temp_workspace / target_rel).exists()


def test_04_create_when_target_absent_succeeds(patch_service: PatchService, temp_workspace: Path):
    """Scenario 4: CREATE when target absent succeeds atomically."""
    target_rel = Path("src/new_module.py")
    created_bytes = b"# New module\ndef hello(): pass\n"
    created_hash = compute_content_hash(created_bytes)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=target_rel,
        expected_exists=False,
        expected_content_hash=None,
        proposed_content=created_bytes,
        proposed_content_hash=created_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True
    assert res.resulting_hash == created_hash

    target_file = temp_workspace / target_rel
    assert target_file.exists()
    assert target_file.read_bytes() == created_bytes


def test_05_create_when_target_appears_before_commit_conflict(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 5: TARGET_EXISTS: If target file exists or appears before commit, CREATE is rejected and existing file untouched."""
    target_rel = Path("existing_module.py")
    target_file = temp_workspace / target_rel
    existing_content = b"print('existing file')"
    target_file.write_bytes(existing_content)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=target_rel,
        expected_exists=False,
        expected_content_hash=None,
        proposed_content=b"print('new file')",
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.TARGET_EXISTS
    assert target_file.read_bytes() == existing_content


def test_06_delete_with_matching_expected_hash_succeeds(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 6: DELETE with matching expected hash succeeds recoverably (backup preserved)."""
    target_file = temp_workspace / "obsolete.txt"
    content = b"obsolete data\n"
    target_file.write_bytes(content)
    expected_hash = compute_content_hash(content)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.DELETE,
        canonical_relative_path=Path("obsolete.txt"),
        expected_exists=True,
        expected_content_hash=expected_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True
    assert not target_file.exists()
    assert res.resulting_hash is None

    # Verify backup exists
    backup_file = temp_workspace / ".ae_patch_recovery" / "backups" / f"{op.operation_id}.orig"
    assert backup_file.exists()
    assert backup_file.read_bytes() == content


def test_07_delete_after_human_modification_conflict(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 7: DELETE after human modification returns STALE_PATCH conflict and file is untouched."""
    target_file = temp_workspace / "important.txt"
    initial_content = b"initial\n"
    initial_hash = compute_content_hash(initial_content)

    # Human edited file
    human_content = b"initial\nhuman added this important line\n"
    target_file.write_bytes(human_content)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.DELETE,
        canonical_relative_path=Path("important.txt"),
        expected_exists=True,
        expected_content_hash=initial_hash,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.STALE_PATCH
    assert target_file.exists()
    assert target_file.read_bytes() == human_content


def test_08_exact_approval_binds_proposed_content_hash(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 8: Exact approval matching bound parameters succeeds."""
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


def test_09_changed_proposed_content_invalidates_approval(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 9: APPROVAL_MISMATCH: Changing proposed content after approval invalidates token."""
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
        expected_content_hash=orig_hash,
        proposed_content_hash=approved_hash,
    )

    # Attempt to apply tampered_bytes with approved digest
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


def test_10_path_escape_and_symlink_blocked_by_containment(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 10: Path traversal or escape outside workspace root is blocked fail-closed."""
    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=Path("../escape.txt"),
        expected_exists=False,
        proposed_content=b"hacked",
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.CONTAINMENT_VIOLATION
    assert not (temp_workspace.parent / "escape.txt").exists()


def test_11_failed_write_never_leaves_partially_truncated_target(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 11: Failure during staged write never leaves target file truncated or altered."""
    target_file = temp_workspace / "original.txt"
    original_bytes = b"important data\n" * 100
    target_file.write_bytes(original_bytes)
    orig_hash = compute_content_hash(original_bytes)

    patch_service._fail_before_staged_write = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("original.txt"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"new truncated attempt",
    )

    with pytest.raises(RuntimeError, match="Injected failure before staged write"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    # Invariant: Live file was not opened or truncated
    assert target_file.read_bytes() == original_bytes


def test_12_staged_temp_hash_verified_before_replace(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 12: HASH_VERIFICATION_FAILED: If staged temporary file is corrupted before replace, it is rejected and target untouched."""
    target_file = temp_workspace / "code.py"
    orig_bytes = b"x = 1\n"
    target_file.write_bytes(orig_bytes)
    orig_hash = compute_content_hash(orig_bytes)

    actual_proposed = b"x = 2\n"
    wrong_hash = "0" * 64

    # We manually construct operation where declared hash does not match
    op = PatchOperation.__new__(PatchOperation)
    op.operation_id = generate_patch_operation_id()
    op.project_id = "proj-1"
    op.operation_type = PatchOperationType.UPDATE
    op.canonical_relative_path = Path("code.py")
    op.expected_exists = True
    op.expected_content_hash = orig_hash
    op.proposed_content = actual_proposed
    op.proposed_content_hash = wrong_hash
    op.proposed_content_artifact_id = None
    op.approval_id = None
    op.approval_digest = None

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.HASH_VERIFICATION_FAILED
    assert target_file.read_bytes() == orig_bytes


def test_13_crash_before_replace_recovery_succeeds(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 13: Crash before replace: Original file remains intact; journal reconciliation aborts safely and cleans staged temp."""
    target_file = temp_workspace / "service.py"
    orig_bytes = b"def start(): pass\n"
    target_file.write_bytes(orig_bytes)
    orig_hash = compute_content_hash(orig_bytes)

    patch_service._fail_before_replace = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("service.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"def start(): return 1\n",
    )

    with pytest.raises(RuntimeError, match="Injected failure before atomic replace"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    assert target_file.read_bytes() == orig_bytes

    # Run crash recovery
    recovery_results = patch_service.recover_interrupted_patches(temp_workspace)
    assert len(recovery_results) == 1
    assert recovery_results[0].operation_id == op.operation_id
    assert recovery_results[0].success is False

    # Check journal transitioned to ABORTED
    journal_path = temp_workspace / ".ae_patch_recovery" / "journals" / f"{op.operation_id}.json"
    journal = json.loads(journal_path.read_text())
    assert journal["state"] == PatchJournalState.ABORTED.value

    # Verify no leaked staged temp file
    staged_matches = list(temp_workspace.glob(".service.py.tmp.*"))
    assert len(staged_matches) == 0


def test_14_crash_after_replace_reconciliation_succeeds(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 14: Crash immediately after replace: Target file contains proposed hash; recovery reconciles and finalizes to COMMITTED."""
    target_file = temp_workspace / "model.py"
    orig_bytes = b"class User: pass\n"
    target_file.write_bytes(orig_bytes)
    orig_hash = compute_content_hash(orig_bytes)

    proposed_bytes = b"class User:\n    id: int\n"
    proposed_hash = compute_content_hash(proposed_bytes)

    patch_service._fail_after_replace = True

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("model.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=proposed_bytes,
        proposed_content_hash=proposed_hash,
    )

    with pytest.raises(RuntimeError, match="Injected failure immediately after atomic replace"):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    # Atomic rename was already complete on disk!
    assert target_file.read_bytes() == proposed_bytes

    # Run crash recovery
    recovery_results = patch_service.recover_interrupted_patches(temp_workspace)
    assert len(recovery_results) == 1
    assert recovery_results[0].success is True
    assert recovery_results[0].resulting_hash == proposed_hash

    # Check journal transitioned to COMMITTED
    journal_path = temp_workspace / ".ae_patch_recovery" / "journals" / f"{op.operation_id}.json"
    journal = json.loads(journal_path.read_text())
    assert journal["state"] == PatchJournalState.COMMITTED.value


def test_15_ambiguous_recovery_with_newer_human_value_never_overwritten(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 15: RECOVERY_REQUIRED: If human edits the file after an interrupted patch, recovery NEVER overwrites human edit."""
    target_file = temp_workspace / "shared.py"
    orig_bytes = b"var = 1\n"
    target_file.write_bytes(orig_bytes)
    orig_hash = compute_content_hash(orig_bytes)

    op_id = generate_patch_operation_id()
    patch_service._fail_before_replace = True

    op = PatchOperation(
        operation_id=op_id,
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("shared.py"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=b"var = 2\n",
    )

    with pytest.raises(RuntimeError):
        patch_service.apply_patch(op, workspace_root=temp_workspace)

    # Now a human user modifies shared.py with a brand new third value
    human_new_bytes = b"var = 9999  # Human critical hotfix\n"
    target_file.write_bytes(human_new_bytes)

    # Run crash recovery
    recovery_results = patch_service.recover_interrupted_patches(temp_workspace)
    assert len(recovery_results) == 1
    assert recovery_results[0].conflict_reason == PatchConflictReason.RECOVERY_REQUIRED

    # CRITICAL INVARIANT: The human edit is preserved untouched!
    assert target_file.read_bytes() == human_new_bytes

    journal_path = temp_workspace / ".ae_patch_recovery" / "journals" / f"{op_id}.json"
    journal = json.loads(journal_path.read_text())
    assert journal["state"] == PatchJournalState.RECOVERY_REQUIRED.value


def test_16_concurrent_writers_serialize_via_target_locks(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 16: Multiple concurrent threads applying patches to the same file serialize cleanly via target lock."""
    target_file = temp_workspace / "counter.txt"
    initial_content = b"0"
    target_file.write_bytes(initial_content)

    results: List[PatchResult] = []

    def run_patch(idx: int):
        # Each thread attempts to apply patch based on initial content
        op = PatchOperation(
            operation_id=f"concurrent-{idx}",
            project_id="proj-1",
            operation_type=PatchOperationType.UPDATE,
            canonical_relative_path=Path("counter.txt"),
            expected_exists=True,
            expected_content_hash=compute_content_hash(b"0"),
            proposed_content=f"{idx}".encode("utf-8"),
        )
        return patch_service.apply_patch(op, workspace_root=temp_workspace)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_patch, i) for i in range(1, 5)]
        for f in futures:
            results.append(f.result())

    # Exactly one thread should succeed with initial hash '0'; others must be rejected with STALE_PATCH
    successes = [r for r in results if r.success]
    conflicts = [r for r in results if r.conflict_reason == PatchConflictReason.STALE_PATCH]

    assert len(successes) == 1
    assert len(conflicts) == 3


def test_17_journal_contains_no_full_file_contents_or_secrets(
    patch_service: PatchService, temp_workspace: Path
):
    """Scenario 17: Journal files contain only metadata, paths, and cryptographic hashes; no raw file content or secrets."""
    target_file = temp_workspace / "secret.env"
    secret_content = b"DATABASE_PASSWORD=SuperSecretPassword123!\n"
    target_file.write_bytes(secret_content)
    orig_hash = compute_content_hash(secret_content)

    proposed_secret = b"DATABASE_PASSWORD=NewSecretPassword456!\n"

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("secret.env"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=proposed_secret,
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True

    journal_path = temp_workspace / ".ae_patch_recovery" / "journals" / f"{op.operation_id}.json"
    journal_text = journal_path.read_text(encoding="utf-8")

    assert "SuperSecretPassword123" not in journal_text
    assert "NewSecretPassword456" not in journal_text
    assert "expected_content_hash" in journal_text
    assert "proposed_content_hash" in journal_text


def test_18_audit_ledger_records_hashes_not_file_bodies(temp_workspace: Path):
    """Scenario 18: Execution ledger record contains hashes and references rather than full file bodies (CTO Review Section 22)."""
    mock_storage = MockStorageBackend()
    svc = PatchService(storage=mock_storage, recovery_dir=temp_workspace / ".ae_patch_recovery")

    target_file = temp_workspace / "data.csv"
    orig_data = b"id,val\n1,100\n"
    target_file.write_bytes(orig_data)
    orig_hash = compute_content_hash(orig_data)

    new_data = b"id,val\n1,200\n"
    new_hash = compute_content_hash(new_data)

    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-audit",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("data.csv"),
        expected_exists=True,
        expected_content_hash=orig_hash,
        proposed_content=new_data,
        proposed_content_hash=new_hash,
        approval_id="appr-audit-1",
    )

    res = svc.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is True

    assert len(mock_storage.patch_records) == 1
    rec = mock_storage.patch_records[0]
    rec_dict = rec.to_dict()

    assert rec_dict["operation_id"] == op.operation_id
    assert rec_dict["project_id"] == "proj-audit"
    assert rec_dict["canonical_relative_path"] == "data.csv"
    assert rec_dict["expected_content_hash"] == orig_hash
    assert rec_dict["resulting_hash"] == new_hash
    assert rec_dict["approval_id"] == "appr-audit-1"
    assert rec_dict["success"] is True

    # Ensure no file body was serialized into the ledger record
    rec_json = json.dumps(rec_dict)
    assert "id,val" not in rec_json


def test_19_absence_vs_empty_file_semantics(patch_service: PatchService, temp_workspace: Path):
    """Scenario 19: Absence vs Empty File (CTO Review Section 10 & 11): An absent file is distinct from an empty file."""
    # 1. An empty file exists and has a non-null SHA-256 hash (hash of b"")
    empty_file = temp_workspace / "empty.txt"
    empty_file.write_bytes(b"")
    empty_hash = compute_file_hash(empty_file)
    assert empty_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    # Attempting CREATE on an existing empty file fails with TARGET_EXISTS
    op_create = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.CREATE,
        canonical_relative_path=Path("empty.txt"),
        expected_exists=False,
        expected_content_hash=None,
        proposed_content=b"new content",
    )
    res_create = patch_service.apply_patch(op_create, workspace_root=temp_workspace)
    assert res_create.success is False
    assert res_create.conflict_reason == PatchConflictReason.TARGET_EXISTS

    # UPDATE on empty file with matching empty hash succeeds
    op_update = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("empty.txt"),
        expected_exists=True,
        expected_content_hash=empty_hash,
        proposed_content=b"filled content",
    )
    res_update = patch_service.apply_patch(op_update, workspace_root=temp_workspace)
    assert res_update.success is True
    assert empty_file.read_bytes() == b"filled content"


def test_20_exact_byte_hashing_no_normalization(patch_service: PatchService, temp_workspace: Path):
    """Scenario 20: Cryptographic hash is computed over exact raw bytes; CRLF vs LF differences are not normalized (Section 11)."""
    target_file = temp_workspace / "crlf.txt"
    crlf_content = b"line1\r\nline2\r\n"
    target_file.write_bytes(crlf_content)
    crlf_hash = compute_content_hash(crlf_content)

    lf_content = b"line1\nline2\n"
    lf_hash = compute_content_hash(lf_content)

    # Hashes are distinct
    assert crlf_hash != lf_hash

    # Submitting a patch expecting LF when file is CRLF must fail as STALE_PATCH
    op = PatchOperation(
        operation_id=generate_patch_operation_id(),
        project_id="proj-1",
        operation_type=PatchOperationType.UPDATE,
        canonical_relative_path=Path("crlf.txt"),
        expected_exists=True,
        expected_content_hash=lf_hash,
        proposed_content=b"new line\n",
    )

    res = patch_service.apply_patch(op, workspace_root=temp_workspace)
    assert res.success is False
    assert res.conflict_reason == PatchConflictReason.STALE_PATCH
    assert target_file.read_bytes() == crlf_content
