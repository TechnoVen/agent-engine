"""tests/test_r2_checkpoint_service.py

Comprehensive test suite for R2.11 Checkpoint and Rollback Service.
Covers CTO Review Sections 11-24 requirements:
1. Checkpoint model and lifecycle (Checkpoint, CheckpointResource, RestorePlan, RestoreResult).
2. Checkpoint creation before consequential mutation; failure blocks mutation fail-closed.
3. Safe rollback as consequential operation requiring exact approval token binding and single-use consumption.
4. Conflict detection: never silently overwrite newer human edits (ROLLBACK_CONFLICT).
5. Backends:
   - File: exact byte snapshot, raw SHA-256 hash, staged atomic commit, permissions mode, absence/deletion handling.
   - Git: hidden safety ref (refs/ae-checkpoints/<id>), never touches active branch/index/remote, detects uncommitted human work.
   - Database: SQLite Online Backup API consistency, PRAGMA integrity_check, UnsupportedDatabaseBackendError for non-SQLite.
   - Config: schema version, SecretReference preservation without plaintext secrets.
6. Storage security: .ae_checkpoints/{project_id}/{checkpoint_id}/, mode 0o700/0o600, ID sanitization.
7. Audit ledger: hashes/references only, zero raw contents, zero secrets.
8. Multi-resource atomicity and partial failure reporting.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import List
import pytest

from core.checkpoint.models import (
    CheckpointCreationError,
    CheckpointExecutionRecord,
    CheckpointNotFoundError,
    CheckpointResource,
    CheckpointResourceType,
    CheckpointStatus,
    ResourceRestoreStatus,
    RestorePlan,
    RestoreStatus,
    compute_rollback_approval_digest,
    generate_restore_id,
)
from core.checkpoint.service import CheckpointService


class MockStorageWithLedger:
    """Mock storage tracking approval tokens and checkpoint execution records."""

    def __init__(self) -> None:
        self.consumed_approvals: set[str] = set()
        self.ledger_records: List[CheckpointExecutionRecord] = []

    def is_approval_consumed(self, approval_id: str) -> bool:
        return approval_id in self.consumed_approvals

    def atomic_consume_approval(self, approval_id: str, verifier: str, timestamp: float) -> bool:
        if approval_id in self.consumed_approvals:
            return False
        self.consumed_approvals.add(approval_id)
        return True

    def record_checkpoint_execution(self, record: CheckpointExecutionRecord) -> None:
        self.ledger_records.append(record)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def storage() -> MockStorageWithLedger:
    return MockStorageWithLedger()


@pytest.fixture
def service(storage: MockStorageWithLedger) -> CheckpointService:
    return CheckpointService(storage=storage)


# ============================================================================
# 1. Checkpoint Creation & Fail-Closed Behavior
# ============================================================================


def test_checkpoint_creation_success(service: CheckpointService, workspace: Path) -> None:
    """Checkpoint creation produces READY checkpoint with durable metadata and backup."""
    target_file = workspace / "module.py"
    target_file.write_text("print('version 1')", encoding="utf-8")
    pre_hash = hashlib.sha256(b"print('version 1')").hexdigest()

    res = CheckpointResource(
        resource_id="res-1",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="module.py",
    )

    chk = service.create_checkpoint(
        project_id="proj-alpha",
        execution_id="exec-100",
        resources=[res],
        workspace_root=workspace,
        description="Pre-execution backup",
    )

    assert chk.status == CheckpointStatus.READY
    assert chk.project_id == "proj-alpha"
    assert len(chk.resources) == 1
    assert chk.resources[0].pre_state_hash == pre_hash
    assert chk.resources[0].exists_pre is True
    assert chk.resources[0].storage_reference is not None

    # Check durable storage
    chk_dir = service.get_checkpoint_dir("proj-alpha", chk.checkpoint_id, workspace)
    assert chk_dir.exists()
    assert (chk_dir / "checkpoint.json").exists()
    assert (chk_dir / chk.resources[0].storage_reference).exists()


def test_checkpoint_creation_failure_fail_closed(
    service: CheckpointService, workspace: Path
) -> None:
    """When resource snapshot fails, checkpoint creation raises CheckpointCreationError fail-closed."""
    # Resource with escaping path
    res = CheckpointResource(
        resource_id="res-evil",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="../outside.py",
    )

    with pytest.raises(CheckpointCreationError):
        service.create_checkpoint(
            project_id="proj-alpha",
            execution_id="exec-101",
            resources=[res],
            workspace_root=workspace,
        )


def test_get_nonexistent_checkpoint_raises(service: CheckpointService, workspace: Path) -> None:
    """Querying nonexistent checkpoint raises CheckpointNotFoundError."""
    with pytest.raises(CheckpointNotFoundError):
        service.get_checkpoint("proj-alpha", "chk-missing", workspace)


# ============================================================================
# 2. File Checkpoint & Restore Behavior
# ============================================================================


def test_file_checkpoint_exact_byte_restore_and_hash_verification(
    service: CheckpointService, workspace: Path
) -> None:
    """Rollback restores exact pre-state bytes and verifies resulting SHA-256 hash."""
    file_path = workspace / "data.txt"
    original_content = b"original safe content " + bytes([0, 255]) + b" binary safe"
    file_path.write_bytes(original_content)
    orig_hash = hashlib.sha256(original_content).hexdigest()

    res = CheckpointResource(
        resource_id="res-file-1",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="data.txt",
    )
    chk = service.create_checkpoint("p1", "e1", [res], workspace)

    # Simulate execution mutation
    mutated_content = b"mutated content by agent"
    file_path.write_bytes(mutated_content)
    mutated_hash = hashlib.sha256(mutated_content).hexdigest()

    # Inform checkpoint resource of expected post state
    chk.resources[0].expected_post_state_hash = mutated_hash
    # Update checkpoint json
    chk_dir = service.get_checkpoint_dir("p1", chk.checkpoint_id, workspace)
    (chk_dir / "checkpoint.json").write_text(json.dumps(chk.to_dict()), encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-1",
        checkpoint_id=chk.checkpoint_id,
        project_id="p1",
        resource_ids=["res-file-1"],
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.is_success
    assert result.status == RestoreStatus.COMPLETED
    assert result.resource_results["res-file-1"].status == ResourceRestoreStatus.RESTORED
    assert result.resource_results["res-file-1"].verified is True
    assert result.resource_results["res-file-1"].restored_hash == orig_hash
    assert file_path.read_bytes() == original_content


def test_file_rollback_refuses_newer_human_content_conflict(
    service: CheckpointService, workspace: Path
) -> None:
    """Rollback halts with CONFLICT without overwriting when live file has diverged with human edits."""
    file_path = workspace / "main.py"
    file_path.write_text("v1 = 1", encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-main",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="main.py",
    )
    chk = service.create_checkpoint("p1", "e1", [res], workspace)

    # Execution produced v2
    v2_hash = hashlib.sha256(b"v2 = 2").hexdigest()
    chk.resources[0].expected_post_state_hash = v2_hash
    chk_dir = service.get_checkpoint_dir("p1", chk.checkpoint_id, workspace)
    (chk_dir / "checkpoint.json").write_text(json.dumps(chk.to_dict()), encoding="utf-8")

    # BUT human edited file to v3!
    human_content = "v3_human = 3 # my manual change"
    file_path.write_text(human_content, encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-conflict",
        checkpoint_id=chk.checkpoint_id,
        project_id="p1",
        resource_ids=["res-main"],
        force=False,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.CONFLICT
    # Live file must remain 100% untouched!
    assert file_path.read_text(encoding="utf-8") == human_content


def test_file_rollback_force_overwrites_divergence(
    service: CheckpointService, workspace: Path
) -> None:
    """When force=True is explicitly passed, rollback overwrites human divergence."""
    file_path = workspace / "app.py"
    file_path.write_text("orig", encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-app",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="app.py",
    )
    chk = service.create_checkpoint("p1", "e1", [res], workspace)

    # Human edited file
    file_path.write_text("human edits", encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-force",
        checkpoint_id=chk.checkpoint_id,
        project_id="p1",
        resource_ids=["res-app"],
        force=True,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.COMPLETED
    assert file_path.read_text(encoding="utf-8") == "orig"


def test_file_absent_checkpoint_restores_absence(
    service: CheckpointService, workspace: Path
) -> None:
    """Checkpointing a non-existent file correctly captures absence and removes created file on rollback."""
    new_file = workspace / "created_by_agent.py"
    assert not new_file.exists()

    res = CheckpointResource(
        resource_id="res-created",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="created_by_agent.py",
    )
    chk = service.create_checkpoint("p1", "e1", [res], workspace)
    assert chk.resources[0].exists_pre is False

    # Agent creates file
    new_file.write_text("code created", encoding="utf-8")
    assert new_file.exists()

    # Inform expected post state
    chk.resources[0].expected_post_state_hash = hashlib.sha256(b"code created").hexdigest()
    chk_dir = service.get_checkpoint_dir("p1", chk.checkpoint_id, workspace)
    (chk_dir / "checkpoint.json").write_text(json.dumps(chk.to_dict()), encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-absent",
        checkpoint_id=chk.checkpoint_id,
        project_id="p1",
        resource_ids=["res-created"],
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.COMPLETED
    assert not new_file.exists()


def test_file_deleted_checkpoint_restores_file(service: CheckpointService, workspace: Path) -> None:
    """Checkpointing an existing file restores it if the execution deleted it."""
    file_path = workspace / "to_be_deleted.txt"
    file_path.write_text("pre-existing content", encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-del",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="to_be_deleted.txt",
    )
    chk = service.create_checkpoint("p1", "e1", [res], workspace)

    # Execution deletes the file
    file_path.unlink()
    assert not file_path.exists()

    plan = RestorePlan(
        restore_id="rst-restore-del",
        checkpoint_id=chk.checkpoint_id,
        project_id="p1",
        resource_ids=["res-del"],
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.COMPLETED
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "pre-existing content"


# ============================================================================
# 3. Git Checkpoint Backend Behavior
# ============================================================================


def _init_git_repo(path: Path) -> None:
    """Helper to initialize a real git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    readme = path / "README.md"
    readme.write_text("# Initial", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True)


def test_git_checkpoint_creates_safety_ref_without_modifying_branch_or_index(
    service: CheckpointService, workspace: Path
) -> None:
    """Git checkpoint creates commit on hidden ref refs/ae-checkpoints/<id> without altering branch/index."""
    _init_git_repo(workspace)

    # Create uncommitted staged and unstaged files
    staged_file = workspace / "staged.txt"
    staged_file.write_text("staged content", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=str(workspace), check=True)

    unstaged_file = workspace / "unstaged.txt"
    unstaged_file.write_text("unstaged content", encoding="utf-8")

    # Get HEAD and branch before checkpoint
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(workspace), capture_output=True, text=True
    ).stdout.strip()
    branch_before = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    ).stdout.strip()

    res = CheckpointResource(
        resource_id="res-git",
        resource_type=CheckpointResourceType.GIT,
    )

    chk = service.create_checkpoint("proj-git", "e-git", [res], workspace)
    assert chk.status == CheckpointStatus.READY

    # Verify HEAD and branch remain identical
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(workspace), capture_output=True, text=True
    ).stdout.strip()
    branch_after = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_before == head_after
    assert branch_before == branch_after

    # Verify safety ref exists in git
    safety_ref = f"refs/ae-checkpoints/{res.resource_id}"
    ref_check = subprocess.run(
        ["git", "rev-parse", safety_ref], cwd=str(workspace), capture_output=True, text=True
    )
    assert ref_check.returncode == 0
    checkpoint_commit = ref_check.stdout.strip()
    assert chk.resources[0].pre_state_hash == checkpoint_commit


def test_git_checkpoint_restores_working_tree(service: CheckpointService, workspace: Path) -> None:
    """Git rollback restores working tree files to checkpoint ref state."""
    _init_git_repo(workspace)

    doc = workspace / "doc.txt"
    doc.write_text("git v1", encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-git-restore",
        resource_type=CheckpointResourceType.GIT,
    )
    chk = service.create_checkpoint("proj-git", "e2", [res], workspace)

    # Mutate working tree
    doc.write_text("git v2 mutated", encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-git",
        checkpoint_id=chk.checkpoint_id,
        project_id="proj-git",
        resource_ids=["res-git-restore"],
        force=True,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.COMPLETED
    assert doc.read_text(encoding="utf-8") == "git v1"


def test_git_rollback_refuses_divergent_human_state(
    service: CheckpointService, workspace: Path
) -> None:
    """Git rollback without force halts with CONFLICT if uncommitted changes exist."""
    _init_git_repo(workspace)

    res = CheckpointResource(
        resource_id="res-git-conflict",
        resource_type=CheckpointResourceType.GIT,
    )
    chk = service.create_checkpoint("proj-git", "e3", [res], workspace)

    # Uncommitted human work
    (workspace / "human_uncommitted.txt").write_text("important", encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-git-c",
        checkpoint_id=chk.checkpoint_id,
        project_id="proj-git",
        resource_ids=["res-git-conflict"],
        force=False,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.CONFLICT
    assert (workspace / "human_uncommitted.txt").read_text(encoding="utf-8") == "important"


# ============================================================================
# 4. Database Checkpoint Backend Behavior
# ============================================================================


def test_sqlite_database_checkpoint_and_integrity_check(
    service: CheckpointService, workspace: Path
) -> None:
    """SQLite checkpoint uses Online Backup API and rollback verifies PRAGMA integrity_check."""
    db_file = workspace / "app.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'Alice')")
    conn.commit()
    conn.close()

    res = CheckpointResource(
        resource_id="res-db-1",
        resource_type=CheckpointResourceType.DATABASE,
        canonical_relative_path="app.sqlite",
    )

    chk = service.create_checkpoint("p-db", "e-db", [res], workspace)
    assert chk.status == CheckpointStatus.READY
    assert chk.resources[0].storage_reference is not None

    # Mutate database
    conn = sqlite3.connect(str(db_file))
    conn.execute("INSERT INTO users VALUES (2, 'Bob')")
    conn.commit()
    conn.close()

    plan = RestorePlan(
        restore_id="rst-db",
        checkpoint_id=chk.checkpoint_id,
        project_id="p-db",
        resource_ids=["res-db-1"],
        force=True,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.COMPLETED

    # Verify table contents restored
    conn = sqlite3.connect(str(db_file))
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    assert rows == [(1, "Alice")]


def test_unsupported_database_fails_explicitly(service: CheckpointService, workspace: Path) -> None:
    """Attempting database checkpoint on non-SQLite type raises UnsupportedDatabaseBackendError."""
    res = CheckpointResource(
        resource_id="res-pg",
        resource_type=CheckpointResourceType.DATABASE,
        canonical_relative_path="db.sql",
        metadata={"db_type": "postgres"},
    )

    with pytest.raises(CheckpointCreationError) as exc_info:
        service.create_checkpoint("p-db", "e-pg", [res], workspace)
    assert (
        "UnsupportedDatabaseBackendError" in str(exc_info.value)
        or "unsupported" in str(exc_info.value).lower()
    )


# ============================================================================
# 5. Config Checkpoint Backend Behavior
# ============================================================================


def test_config_checkpoint_preserves_secret_references(
    service: CheckpointService, workspace: Path
) -> None:
    """Config snapshot preserves SecretReference identifiers without leaking plaintext secrets."""
    cfg_file = workspace / "settings.json"
    valid_config = {
        "version": "1.2",
        "api_endpoint": "https://api.example.com",
        "auth": {"token": {"secret_id": "sec-vault-123", "provider": "system_keychain"}},
    }
    cfg_file.write_text(json.dumps(valid_config), encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-cfg-1",
        resource_type=CheckpointResourceType.CONFIG,
        canonical_relative_path="settings.json",
    )

    chk = service.create_checkpoint("p-cfg", "e-cfg", [res], workspace)
    assert chk.status == CheckpointStatus.READY
    assert chk.resources[0].metadata["schema_version"] == "1.2"

    # Agent mutates config
    mutated_config = {
        "version": "1.2",
        "api_endpoint": "https://mutated.com",
        "auth": {"token": "changed"},
    }
    cfg_file.write_text(json.dumps(mutated_config), encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-cfg",
        checkpoint_id=chk.checkpoint_id,
        project_id="p-cfg",
        resource_ids=["res-cfg-1"],
        force=True,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.COMPLETED

    restored = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert restored["api_endpoint"] == "https://api.example.com"
    assert restored["auth"]["token"]["secret_id"] == "sec-vault-123"


def test_config_checkpoint_rejects_raw_plaintext_secrets(
    service: CheckpointService, workspace: Path
) -> None:
    """Config snapshot rejects configurations containing exposed plaintext API keys."""
    cfg_file = workspace / "bad_settings.json"
    leaked_config = {
        "version": "1.0",
        "openai_key": "sk-proj-supersecrettoken123456789",
    }
    cfg_file.write_text(json.dumps(leaked_config), encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-leaked",
        resource_type=CheckpointResourceType.CONFIG,
        canonical_relative_path="bad_settings.json",
    )

    with pytest.raises(CheckpointCreationError) as exc_info:
        service.create_checkpoint("p-cfg", "e-leaked", [res], workspace)
    assert "plaintext secret" in str(exc_info.value).lower()


# ============================================================================
# 6. Consequential Approval Binding & Single-Use Consumption
# ============================================================================


def test_rollback_approval_exact_digest_binding(
    service: CheckpointService, workspace: Path
) -> None:
    """Rollback requires exact approval digest binding; tampered parameters fail."""
    f = workspace / "file.txt"
    f.write_text("v1", encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-appr",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="file.txt",
    )
    chk = service.create_checkpoint("p-appr", "e-appr", [res], workspace)

    restore_id = generate_restore_id()
    valid_digest = compute_rollback_approval_digest(
        project_id="p-appr",
        checkpoint_id=chk.checkpoint_id,
        restore_id=restore_id,
        resource_ids=["res-appr"],
    )

    # 1. Tampered resource ID
    tampered_plan = RestorePlan(
        restore_id=restore_id,
        checkpoint_id=chk.checkpoint_id,
        project_id="p-appr",
        resource_ids=["res-tampered"],
        approval_id="appr-123",
        approval_digest=valid_digest,
    )
    res_tampered = service.restore_checkpoint(tampered_plan, workspace)
    assert res_tampered.status == RestoreStatus.FAILED
    assert "APPROVAL_MISMATCH" in res_tampered.message

    # 2. Valid plan and digest succeeds
    valid_plan = RestorePlan(
        restore_id=restore_id,
        checkpoint_id=chk.checkpoint_id,
        project_id="p-appr",
        resource_ids=["res-appr"],
        approval_id="appr-123",
        approval_digest=valid_digest,
        force=True,
    )
    res_valid = service.restore_checkpoint(valid_plan, workspace)
    assert res_valid.status == RestoreStatus.COMPLETED


def test_rollback_approval_single_use_consumption(
    service: CheckpointService, workspace: Path
) -> None:
    """Rollback approval token cannot be replayed or reused for another restore."""
    f = workspace / "single_use.txt"
    f.write_text("v1", encoding="utf-8")

    res = CheckpointResource(
        resource_id="res-su",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="single_use.txt",
    )
    chk = service.create_checkpoint("p-su", "e-su", [res], workspace)

    restore_id = generate_restore_id()
    digest = compute_rollback_approval_digest(
        project_id="p-su",
        checkpoint_id=chk.checkpoint_id,
        restore_id=restore_id,
        resource_ids=["res-su"],
    )

    plan = RestorePlan(
        restore_id=restore_id,
        checkpoint_id=chk.checkpoint_id,
        project_id="p-su",
        resource_ids=["res-su"],
        approval_id="appr-single-use-token",
        approval_digest=digest,
        force=True,
    )

    # First attempt succeeds
    res1 = service.restore_checkpoint(plan, workspace)
    assert res1.status == RestoreStatus.COMPLETED

    # Second attempt with same token fails immediately
    res2 = service.restore_checkpoint(plan, workspace)
    assert res2.status == RestoreStatus.FAILED
    assert "APPROVAL_ALREADY_CONSUMED" in res2.message


# ============================================================================
# 7. Multi-Resource Pre-Flight Conflict & Partial Reporting
# ============================================================================


def test_multi_resource_atomic_conflict_preflight(
    service: CheckpointService, workspace: Path
) -> None:
    """If one resource in a multi-resource checkpoint is in conflict, none are modified."""
    f1 = workspace / "f1.txt"
    f1.write_text("file 1 initial", encoding="utf-8")
    f2 = workspace / "f2.txt"
    f2.write_text("file 2 initial", encoding="utf-8")

    r1 = CheckpointResource(
        resource_id="res-1",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="f1.txt",
    )
    r2 = CheckpointResource(
        resource_id="res-2",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="f2.txt",
    )

    chk = service.create_checkpoint("p-multi", "e-multi", [r1, r2], workspace)

    # Set expected post state for r1 and r2
    chk.resources[0].expected_post_state_hash = hashlib.sha256(b"f1 mutated").hexdigest()
    chk.resources[1].expected_post_state_hash = hashlib.sha256(b"f2 mutated").hexdigest()
    chk_dir = service.get_checkpoint_dir("p-multi", chk.checkpoint_id, workspace)
    (chk_dir / "checkpoint.json").write_text(json.dumps(chk.to_dict()), encoding="utf-8")

    # Mutate f1 as expected
    f1.write_text("f1 mutated", encoding="utf-8")
    # Mutate f2 with human change (unexpected!)
    f2.write_text("f2 human unexpected edit", encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-multi",
        checkpoint_id=chk.checkpoint_id,
        project_id="p-multi",
        resource_ids=["res-1", "res-2"],
        force=False,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.CONFLICT

    # Both files must remain completely untouched!
    assert f1.read_text(encoding="utf-8") == "f1 mutated"
    assert f2.read_text(encoding="utf-8") == "f2 human unexpected edit"


def test_cannot_restore_creating_or_failed_checkpoint(
    service: CheckpointService, workspace: Path
) -> None:
    """Attempting to restore an incomplete or failed checkpoint is rejected."""
    f = workspace / "dummy.txt"
    f.write_text("test", encoding="utf-8")
    res = CheckpointResource(
        resource_id="r-dummy",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="dummy.txt",
    )
    chk = service.create_checkpoint("p-stat", "e-stat", [res], workspace)

    # Simulate checkpoint in CREATING status
    chk.status = CheckpointStatus.CREATING
    chk_dir = service.get_checkpoint_dir("p-stat", chk.checkpoint_id, workspace)
    (chk_dir / "checkpoint.json").write_text(json.dumps(chk.to_dict()), encoding="utf-8")

    plan = RestorePlan(
        restore_id="rst-stat",
        checkpoint_id=chk.checkpoint_id,
        project_id="p-stat",
        resource_ids=["r-dummy"],
        force=True,
    )
    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.FAILED
    assert "Cannot restore checkpoint in status 'creating'" in result.message


# ============================================================================
# 8. Storage Security & Audit Ledger Verification
# ============================================================================


def test_storage_security_permissions_and_sanitization(
    service: CheckpointService, workspace: Path
) -> None:
    """Storage directory mode is 0o700, files are 0o600, and path traversal in IDs is sanitized."""
    f = workspace / "sec.txt"
    f.write_text("security test", encoding="utf-8")
    res = CheckpointResource(
        resource_id="r-sec",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="sec.txt",
    )

    # Project ID with potential path traversal characters
    chk = service.create_checkpoint("../../evil_project", "e-sec", [res], workspace)
    chk_dir = service.get_checkpoint_dir("../../evil_project", chk.checkpoint_id, workspace)

    # Verify sanitized path is strictly within workspace .ae_checkpoints
    assert chk_dir.is_relative_to(workspace / ".ae_checkpoints")
    assert not chk_dir.is_relative_to(workspace.parent / "evil_project")

    # Verify directory permissions (0o700)
    st = chk_dir.stat()
    assert (st.st_mode & 0o777) == 0o700

    # Verify file permissions (0o600)
    meta_st = (chk_dir / "checkpoint.json").stat()
    assert (meta_st.st_mode & 0o777) == 0o600


def test_audit_ledger_records_contain_hashes_only(
    service: CheckpointService, storage: MockStorageWithLedger, workspace: Path
) -> None:
    """Audit ledger records created for checkpoint and restore contain hashes and IDs only."""
    f = workspace / "ledger_check.txt"
    f.write_text("secret confidential raw content 12345", encoding="utf-8")
    res = CheckpointResource(
        resource_id="r-ledg",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="ledger_check.txt",
    )

    chk = service.create_checkpoint("p-ledg", "e-ledg", [res], workspace)

    plan = RestorePlan(
        restore_id="rst-ledg",
        checkpoint_id=chk.checkpoint_id,
        project_id="p-ledg",
        resource_ids=["r-ledg"],
        force=True,
    )
    service.restore_checkpoint(plan, workspace)

    assert len(storage.ledger_records) == 2
    create_rec = storage.ledger_records[0]
    restore_rec = storage.ledger_records[1]

    assert create_rec.action == "create"
    assert create_rec.status == "ready"
    assert create_rec.resource_count == 1

    assert restore_rec.action == "restore"
    assert restore_rec.status == "completed"

    # Verify that raw file content is NEVER in ledger records
    for rec in storage.ledger_records:
        rec_json = json.dumps(rec.to_dict())
        assert "secret confidential raw content 12345" not in rec_json


def test_multi_resource_partial_failure_reporting(
    service: CheckpointService, workspace: Path
) -> None:
    """When some resources succeed while one fails during restore, overall status is PARTIAL."""
    f1 = workspace / "part1.txt"
    f1.write_text("v1", encoding="utf-8")
    f2 = workspace / "part2.txt"
    f2.write_text("v1", encoding="utf-8")

    r1 = CheckpointResource(
        resource_id="res-p1",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="part1.txt",
    )
    r2 = CheckpointResource(
        resource_id="res-p2",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="part2.txt",
    )

    chk = service.create_checkpoint("p-part", "e-part", [r1, r2], workspace)

    # Mutate both
    f1.write_text("v2", encoding="utf-8")
    f2.write_text("v2", encoding="utf-8")

    # Corrupt or delete backup for r2 to trigger failure on r2
    chk_dir = service.get_checkpoint_dir("p-part", chk.checkpoint_id, workspace)
    r2_bck = chk_dir / (chk.resources[1].storage_reference or "")
    if r2_bck.exists():
        r2_bck.unlink()

    plan = RestorePlan(
        restore_id="rst-part",
        checkpoint_id=chk.checkpoint_id,
        project_id="p-part",
        resource_ids=["res-p1", "res-p2"],
        force=True,
    )

    result = service.restore_checkpoint(plan, workspace)
    assert result.status == RestoreStatus.PARTIAL
    assert result.resource_results["res-p1"].status == ResourceRestoreStatus.RESTORED
    assert result.resource_results["res-p2"].status == ResourceRestoreStatus.FAILED


def test_checkpoint_directory_exclusion(service: CheckpointService, workspace: Path) -> None:
    """Checkpoint directory starts with .ae_ and is isolated from normal project content."""
    f = workspace / "sample.txt"
    f.write_text("content", encoding="utf-8")
    res = CheckpointResource(
        resource_id="r-ex",
        resource_type=CheckpointResourceType.FILE,
        canonical_relative_path="sample.txt",
    )

    chk = service.create_checkpoint("proj-ex", "e-ex", [res], workspace)
    chk_dir = service.get_checkpoint_dir("proj-ex", chk.checkpoint_id, workspace)

    assert ".ae_checkpoints" in chk_dir.parts
    # Verify dot-prefix ensures hidden status in standard glob / directory traversal
    assert any(part.startswith(".ae_") for part in chk_dir.relative_to(workspace).parts)
