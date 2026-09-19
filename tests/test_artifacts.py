"""Comprehensive Execution Artifact Model Tests (Task R1.10).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md (Section 2.9 & Section 3), docs/ROADMAP.md (R1.10)

Validates all 15 canonical artifact requirements:
1. test_artifact_creation_for_execution
2. test_artifact_metadata_persistence
3. test_artifact_payload_retrieval_inline_and_filesystem
4. test_artifact_sha256_integrity_verification
5. test_artifact_project_attribution
6. test_cross_project_access_denied
7. test_traversal_path_rejected
8. test_symlink_escape_rejected
9. test_execution_artifact_listing
10. test_project_artifact_listing
11. test_large_artifact_storage_kind
12. test_partial_output_artifact_on_cancellation
13. test_artifact_deletion
14. test_alembic_migration_005_round_trip
15. test_rest_endpoints_artifacts_crud_and_download
"""

import asyncio
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from core.artifacts import (
    Artifact,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactSecurityError,
    ArtifactService,
    ArtifactStatus,
    ArtifactStorageKind,
    ArtifactType,
    generate_artifact_id,
)
from core.execution import (
    CancellationReason,
    ExecutionCoordinator,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    RoutingTier,
)
from core.session.store import UnifiedSessionStore
from core.storage.sqlite import SQLiteBackend
from services.python.server.api import (
    app,
    set_artifact_service,
    set_execution_coordinator,
)


def ensure_execution(storage: SQLiteBackend, exec_id: str, project_id: str = "proj_alpha") -> None:
    """Ensure a parent execution record exists to satisfy foreign key constraints."""
    if not storage.get_execution(exec_id):
        storage.create_execution(
            {
                "id": exec_id,
                "project_id": project_id,
                "session_id": f"sess_{exec_id}",
                "request": {"prompt": "sample test prompt", "task_type": "chat"},
                "status": "completed",
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "routing_tier": "fast",
            }
        )


@pytest.fixture
def test_storage(tmp_path):
    """Create isolated SQLite database for artifact tests."""
    db_path = str(tmp_path / "test_artifacts.db")
    backend = SQLiteBackend(db_path=db_path)
    # Ensure sample project records exist for foreign keys
    backend.create_project(
        {
            "id": "proj_alpha",
            "name": "Project Alpha",
            "root_directory": str(tmp_path / "proj_alpha"),
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    backend.create_project(
        {
            "id": "proj_beta",
            "name": "Project Beta",
            "root_directory": str(tmp_path / "proj_beta"),
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    return backend


@pytest.fixture
def artifact_service(test_storage, tmp_path):
    """Create ArtifactService with isolated managed storage directory."""
    artifacts_dir = str(tmp_path / "managed_artifacts")
    return ArtifactService(
        storage=test_storage,
        base_artifacts_dir=artifacts_dir,
        inline_threshold_bytes=8192,
    )


def test_artifact_creation_for_execution(artifact_service, test_storage):
    """Test 1: Basic creation sets canonical ID, hashes, size, and status."""
    ensure_execution(test_storage, "exec_001", "proj_alpha")
    content = b"Hello, World! Canonical artifact test."
    expected_hash = hashlib.sha256(content).hexdigest()
    expected_size = len(content)

    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_001",
        name="test_output.txt",
        content=content,
        type=ArtifactType.TEXT,
        mime_type="text/plain",
    )

    assert art.id.startswith("art_")
    assert len(art.id) == 16  # 'art_' + 12 hex chars
    assert art.project_id == "proj_alpha"
    assert art.execution_id == "exec_001"
    assert art.name == "test_output.txt"
    assert art.type == ArtifactType.TEXT
    assert art.mime_type == "text/plain"
    assert art.sha256_hash == expected_hash
    assert art.size_bytes == expected_size
    assert art.status == ArtifactStatus.READY
    assert art.created_at is not None


def test_artifact_metadata_persistence(artifact_service, test_storage):
    """Test 2: Metadata persists accurately to SQLite and round-trips lineage."""
    ensure_execution(test_storage, "exec_002", "proj_alpha")
    lineage_data = {
        "generator_model": "claude-3-5-sonnet",
        "step": 3,
        "parameters": {"temperature": 0.2},
    }
    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_002",
        name="report.md",
        content="# Quarterly Report\nKey metrics...",
        type=ArtifactType.DOCUMENT,
        mime_type="text/markdown",
        lineage=lineage_data,
        created_by="user:nadir",
    )

    # Fetch from storage directly
    raw = test_storage.get_artifact(art.id)
    assert raw is not None
    assert raw["id"] == art.id
    assert raw["project_id"] == "proj_alpha"
    assert raw["execution_id"] == "exec_002"
    assert raw["lineage"] == lineage_data
    assert raw["created_by"] == "user:nadir"

    # Fetch through service
    fetched = artifact_service.get_artifact(art.id)
    assert fetched is not None
    assert fetched.id == art.id
    assert fetched.lineage == lineage_data
    assert fetched.created_by == "user:nadir"


def test_artifact_payload_retrieval_inline_and_filesystem(artifact_service, test_storage):
    """Test 3: Payload retrieval works for both inline (<8KB text) and filesystem storage."""
    ensure_execution(test_storage, "exec_003", "proj_alpha")

    # 3a. Inline artifact (< 8KB text)
    inline_text = "Small inline report."
    art_inline = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_003",
        name="inline.txt",
        content=inline_text,
        type=ArtifactType.TEXT,
        mime_type="text/plain",
    )
    assert art_inline.storage_kind == ArtifactStorageKind.INLINE
    assert art_inline.inline_content == inline_text
    assert art_inline.file_path is None

    payload_inline = artifact_service.get_artifact_payload(art_inline.id)
    assert payload_inline == inline_text.encode("utf-8")

    # 3b. Filesystem artifact (forced or binary)
    binary_data = b"\x00\x01\x02\x03\x04\xff\xfe"
    art_fs = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_003",
        name="data.bin",
        content=binary_data,
        type=ArtifactType.DATA,
        storage_kind=ArtifactStorageKind.FILESYSTEM,
    )
    assert art_fs.storage_kind == ArtifactStorageKind.FILESYSTEM
    assert art_fs.file_path is not None
    assert art_fs.inline_content is None

    payload_fs = artifact_service.get_artifact_payload(art_fs.id)
    assert payload_fs == binary_data


def test_artifact_sha256_integrity_verification(artifact_service, test_storage):
    """Test 4: Payload tampering raises ArtifactIntegrityError."""
    ensure_execution(test_storage, "exec_004", "proj_alpha")
    original_data = b"Authentic payload content."
    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_004",
        name="tamper_test.bin",
        content=original_data,
        storage_kind=ArtifactStorageKind.FILESYSTEM,
    )

    # Initial integrity check passes
    assert artifact_service.verify_integrity(art.id) is True

    # Tamper with file on disk
    abs_path = os.path.join(artifact_service.base_artifacts_dir, art.file_path)
    with open(abs_path, "wb") as f:
        f.write(b"CORRUPTED CONTENT")

    # Verification must fail and get_artifact_payload must raise ArtifactIntegrityError
    assert artifact_service.verify_integrity(art.id) is False
    with pytest.raises(ArtifactIntegrityError):
        artifact_service.get_artifact_payload(art.id)


def test_artifact_project_attribution(artifact_service, test_storage):
    """Test 5: Artifacts are strictly attributed to their declaring project."""
    ensure_execution(test_storage, "exec_005", "proj_alpha")
    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_005",
        name="project_check.txt",
        content="Alpha project data",
    )
    assert art.project_id == "proj_alpha"

    # Authorized project retrieval succeeds
    fetched = artifact_service.get_artifact(art.id, project_id="proj_alpha")
    assert fetched is not None
    assert fetched.id == art.id


def test_cross_project_access_denied(artifact_service, test_storage):
    """Test 6: Cross-project access raises ArtifactSecurityError."""
    ensure_execution(test_storage, "exec_006", "proj_alpha")
    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_006",
        name="confidential_alpha.txt",
        content="Project Alpha Secret",
    )

    # Unauthorized project (proj_beta) cannot get metadata
    with pytest.raises(ArtifactSecurityError):
        artifact_service.get_artifact(art.id, project_id="proj_beta")

    # Unauthorized project (proj_beta) cannot read payload
    with pytest.raises(ArtifactSecurityError):
        artifact_service.get_artifact_payload(art.id, project_id="proj_beta")

    # Unauthorized project (proj_beta) cannot delete
    with pytest.raises(ArtifactSecurityError):
        artifact_service.delete_artifact(art.id, project_id="proj_beta")


def test_traversal_path_rejected(artifact_service, test_storage):
    """Test 7: Directory traversal attempts are detected and rejected."""
    ensure_execution(test_storage, "exec_traversal_2", "proj_alpha")

    # 7a: Traversal in project_id
    with pytest.raises(ArtifactSecurityError):
        artifact_service.create_artifact(
            project_id="../../etc",
            execution_id="exec_traversal",
            name="malicious.txt",
            content="hacked",
        )

    # 7b: Path traversal in name is sanitized to a safe basename inside project dir
    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_traversal_2",
        name="../../../../../etc/passwd",
        content="passwd contents",
        storage_kind=ArtifactStorageKind.FILESYSTEM,
    )
    assert ".." not in art.file_path
    abs_path = os.path.realpath(os.path.join(artifact_service.base_artifacts_dir, art.file_path))
    project_dir = os.path.realpath(os.path.join(artifact_service.base_artifacts_dir, "proj_alpha"))
    assert os.path.commonpath([project_dir, abs_path]) == project_dir


def test_symlink_escape_rejected(artifact_service, test_storage, tmp_path):
    """Test 8: Symlink escape attempts outside project boundaries are blocked."""
    ensure_execution(test_storage, "exec_escape", "proj_alpha")

    # Create target outside project root
    secret_dir = tmp_path / "secret_system_dir"
    secret_dir.mkdir()
    secret_file = secret_dir / "target.txt"
    secret_file.write_text("outside data")

    # Create artifact record with file_path pointing to a symlink that points to secret_file
    proj_dir = Path(artifact_service.base_artifacts_dir) / "proj_alpha"
    proj_dir.mkdir(parents=True, exist_ok=True)
    escape_link = proj_dir / "symlink_escape.txt"
    if not escape_link.exists():
        escape_link.symlink_to(secret_file)

    art = Artifact(
        id=generate_artifact_id(),
        project_id="proj_alpha",
        execution_id="exec_escape",
        name="escape.txt",
        type=ArtifactType.FILE,
        storage_kind=ArtifactStorageKind.FILESYSTEM,
        file_path="proj_alpha/symlink_escape.txt",
        sha256_hash=hashlib.sha256(b"outside data").hexdigest(),
        size_bytes=len(b"outside data"),
        status=ArtifactStatus.READY,
    )
    artifact_service.storage.create_artifact(art.to_dict())

    # Reading payload must detect that the real path escapes project_dir and raise ArtifactSecurityError
    with pytest.raises(ArtifactSecurityError):
        artifact_service.get_artifact_payload(art.id, project_id="proj_alpha")


def test_execution_artifact_listing(artifact_service, test_storage):
    """Test 9: Listing artifacts by execution returns only relevant items with isolation."""
    ensure_execution(test_storage, "exec_A", "proj_alpha")
    ensure_execution(test_storage, "exec_B", "proj_alpha")

    art1 = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_A",
        name="step1.txt",
        content="step 1",
    )
    art2 = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_A",
        name="step2.txt",
        content="step 2",
    )
    art3 = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_B",
        name="stepB.txt",
        content="step B",
    )

    listed_a = artifact_service.list_artifacts_by_execution("exec_A")
    assert len(listed_a) == 2
    ids_a = {a.id for a in listed_a}
    assert art1.id in ids_a
    assert art2.id in ids_a
    assert art3.id not in ids_a

    # Listing with unauthorized project_id returns empty
    listed_isolated = artifact_service.list_artifacts_by_execution("exec_A", project_id="proj_beta")
    assert len(listed_isolated) == 0


def test_project_artifact_listing(artifact_service, test_storage):
    """Test 10: Listing artifacts by project returns only that project's artifacts."""
    ensure_execution(test_storage, "exec_10", "proj_alpha")
    ensure_execution(test_storage, "exec_11", "proj_beta")

    art_a = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_10",
        name="alpha_doc.txt",
        content="alpha",
    )
    art_b = artifact_service.create_artifact(
        project_id="proj_beta",
        execution_id="exec_11",
        name="beta_doc.txt",
        content="beta",
    )

    alpha_list = artifact_service.list_artifacts_by_project("proj_alpha")
    beta_list = artifact_service.list_artifacts_by_project("proj_beta")

    assert any(a.id == art_a.id for a in alpha_list)
    assert not any(a.id == art_b.id for a in alpha_list)

    assert any(a.id == art_b.id for a in beta_list)
    assert not any(a.id == art_a.id for a in beta_list)


def test_large_artifact_storage_kind(artifact_service, test_storage):
    """Test 11: Payloads exceeding 8KB threshold automatically store on filesystem."""
    ensure_execution(test_storage, "exec_large", "proj_alpha")
    large_text = "X" * (8192 + 500)  # > 8 KB
    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_large",
        name="large_payload.txt",
        content=large_text,
        type=ArtifactType.TEXT,
    )

    assert art.storage_kind == ArtifactStorageKind.FILESYSTEM
    assert art.inline_content is None
    assert art.file_path is not None
    assert art.size_bytes == len(large_text)

    # Verify SQLite record does not contain the payload body
    raw = test_storage.get_artifact(art.id)
    assert raw["inline_content"] is None
    assert raw["file_path"] == art.file_path

    # Retrieval works transparently
    retrieved = artifact_service.get_artifact_payload(art.id)
    assert retrieved.decode("utf-8") == large_text


@pytest.mark.anyio
async def test_partial_output_artifact_on_cancellation(tmp_path):
    """Test 12: Cancellation produces a PARTIAL artifact without session assistant message."""
    db_path = str(tmp_path / "cancel_artifact.db")
    storage = SQLiteBackend(db_path=db_path)
    storage.create_project(
        {
            "id": "proj_alpha",
            "name": "Project Alpha",
            "root_directory": str(tmp_path / "proj_alpha"),
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )

    art_service = ArtifactService(
        storage=storage,
        base_artifacts_dir=str(tmp_path / "artifacts"),
    )
    session_store = UnifiedSessionStore(backend=storage)
    session = session_store.create_session(
        title="Cancellation Session", metadata={"project_id": "proj_alpha"}
    )
    session_store.append_message(session.session_id, "user", "Explain quantum physics")

    started = asyncio.Event()

    async def slow_streaming_dispatch(ctx, tier, prov, model):
        yield "Chunk 1: Starting generation... "
        yield "Chunk 2: Here is partial progress. "
        started.set()
        for i in range(10):
            await asyncio.sleep(0.05)
            yield f"Chunk {i + 3}: Should not reach."

    coordinator = ExecutionCoordinator(
        storage=storage,
        session_store=session_store,
        dispatch_override=slow_streaming_dispatch,
        artifact_service=art_service,
    )

    exec_req = ExecutionRequest(
        project_id="proj_alpha",
        session_id=session.session_id,
        task_type="chat",
        prompt="Explain quantum physics",
        inputs={"stream": True},
        target_tier=RoutingTier.MID,
    )

    events_received = []

    # Start execution in background task
    task = asyncio.create_task(
        coordinator.execute(
            exec_req,
            event_listener=lambda e: events_received.append(e),
        )
    )

    # Wait until stream starts
    await asyncio.wait_for(started.wait(), timeout=5.0)

    # Trigger cancellation
    cancel_res = coordinator.cancel(
        exec_req.id,
        reason=CancellationReason.USER_REQUEST,
        actor="user:nadir",
    )
    assert cancel_res is not None
    assert (
        cancel_res.get("status") == "cancelled" or cancel_res.get("cancellation_requested") is True
    )

    result: ExecutionResult = await asyncio.wait_for(task, timeout=5.0)
    assert result.status == ExecutionStatus.CANCELLED
    assert result.partial_output is not None
    assert "Chunk 1" in result.partial_output

    # Check that a PARTIAL artifact was created
    assert len(result.artifacts_created) == 1
    partial_art_id = result.artifacts_created[0]

    art = art_service.get_artifact(partial_art_id)
    assert art is not None
    assert art.status == ArtifactStatus.PARTIAL
    assert art.name == "partial_output.txt"
    assert art.project_id == "proj_alpha"
    assert art.created_by == "user:nadir"
    assert art.lineage.get("cancellation_reason") == "user_request"

    # Verify ARTIFACT_CREATED event in durable event ledger
    artifact_events = [
        e
        for e in events_received
        if getattr(e, "event_type", None) == ExecutionEventType.ARTIFACT_CREATED
    ]
    assert len(artifact_events) >= 1
    assert artifact_events[0].payload["artifact_id"] == partial_art_id

    # Verify NO assistant message was persisted in session store
    updated_session = session_store.get_session(session.session_id)
    assistant_messages = [
        m
        for m in updated_session.messages
        if (m.role == "assistant" or getattr(m.role, "value", None) == "assistant")
    ]
    assert len(assistant_messages) == 0


def test_artifact_deletion(artifact_service, test_storage):
    """Test 13: Deleting an artifact marks tombstone status, deletes payload, and excludes from default listings."""
    ensure_execution(test_storage, "exec_del", "proj_alpha")
    art = artifact_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_del",
        name="to_delete.bin",
        content=b"Delete me please",
        storage_kind=ArtifactStorageKind.FILESYSTEM,
    )
    abs_path = os.path.join(artifact_service.base_artifacts_dir, art.file_path)
    assert os.path.exists(abs_path)

    # Delete
    deleted = artifact_service.delete_artifact(art.id, project_id="proj_alpha")
    assert deleted is True

    # 1. Check physical payload file deleted
    assert not os.path.exists(abs_path)

    # 2. Check metadata preserved as tombstone
    record = artifact_service.get_artifact(art.id)
    assert record is not None
    assert record.status == ArtifactStatus.DELETED
    assert record.deleted_at is not None

    # 3. Payload retrieval raises ArtifactNotFoundError
    with pytest.raises(ArtifactNotFoundError, match="has been deleted"):
        artifact_service.get_artifact_payload(art.id)

    # 4. Default listing excludes tombstone
    exec_arts = artifact_service.list_artifacts_by_execution("exec_del")
    assert not any(a.id == art.id for a in exec_arts)

    proj_arts = artifact_service.list_artifacts_by_project("proj_alpha")
    assert not any(a.id == art.id for a in proj_arts)

    # 5. Listing with include_deleted=True includes tombstone
    exec_arts_all = artifact_service.list_artifacts_by_execution("exec_del", include_deleted=True)
    assert any(a.id == art.id for a in exec_arts_all)

    proj_arts_all = artifact_service.list_artifacts_by_project("proj_alpha", include_deleted=True)
    assert any(a.id == art.id for a in proj_arts_all)


def test_alembic_migration_005_round_trip(tmp_path):
    """Test 14: Alembic migration 005_canonical_artifacts upgrade/downgrade round-trip."""
    migration_db = tmp_path / "migration_artifacts_test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{migration_db}"

    repo_root = Path(__file__).resolve().parents[1]

    # 1. Upgrade to head
    res_up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_up.returncode == 0, f"Alembic upgrade head failed: {res_up.stderr}"

    conn = sqlite3.connect(str(migration_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {r[0] for r in cursor.fetchall()}
    assert "artifacts" in tables

    # Verify columns in artifacts table
    cursor.execute("PRAGMA table_info(artifacts);")
    columns = {col[1] for col in cursor.fetchall()}
    expected_cols = {
        "id",
        "project_id",
        "execution_id",
        "name",
        "type",
        "mime_type",
        "storage_kind",
        "file_path",
        "inline_content",
        "sha256_hash",
        "size_bytes",
        "status",
        "lineage_json",
        "created_by",
        "created_at",
    }
    assert expected_cols.issubset(columns)
    conn.close()

    # 2. Downgrade to 004_canonical_projects
    res_down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "004_canonical_projects"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_down.returncode == 0, f"Alembic downgrade failed: {res_down.stderr}"

    conn = sqlite3.connect(str(migration_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables_after = {r[0] for r in cursor.fetchall()}
    conn.close()
    assert "artifacts" not in tables_after

    # 3. Upgrade back to head
    res_reup = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_reup.returncode == 0, f"Alembic re-upgrade failed: {res_reup.stderr}"


def test_rest_endpoints_artifacts_crud_and_download(tmp_path, monkeypatch):
    """Test 15: REST endpoints CRUD, content download, headers, and project boundary checks."""
    db_path = str(tmp_path / "api_artifacts.db")
    storage = SQLiteBackend(db_path=db_path)
    storage.create_project(
        {
            "id": "proj_alpha",
            "name": "Project Alpha",
            "root_directory": str(tmp_path / "proj_alpha"),
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    storage.create_project(
        {
            "id": "proj_beta",
            "name": "Project Beta",
            "root_directory": str(tmp_path / "proj_beta"),
            "created_at": "2026-09-19T12:00:00Z",
            "is_default": False,
        }
    )
    ensure_execution(storage, "exec_api_1", "proj_alpha")

    art_service = ArtifactService(
        storage=storage,
        base_artifacts_dir=str(tmp_path / "artifacts"),
    )
    coordinator = ExecutionCoordinator(storage=storage, artifact_service=art_service)

    # Set server instances and mock storage backend
    set_execution_coordinator(coordinator)
    set_artifact_service(art_service)
    monkeypatch.setattr("services.python.server.api.get_storage_backend", lambda: storage)

    client = TestClient(app)

    # 1. Create artifact directly via service
    content_bytes = b"Artifact API content payload for download."
    expected_etag = f'"{hashlib.sha256(content_bytes).hexdigest()}"'
    art = art_service.create_artifact(
        project_id="proj_alpha",
        execution_id="exec_api_1",
        name="api_download.txt",
        content=content_bytes,
        mime_type="text/plain",
        storage_kind=ArtifactStorageKind.FILESYSTEM,
    )

    # 2. GET /v1/artifacts/{id}
    res_meta = client.get(f"/v1/artifacts/{art.id}")
    assert res_meta.status_code == 200
    data = res_meta.json()
    assert data["id"] == art.id
    assert data["name"] == "api_download.txt"
    assert data["project_id"] == "proj_alpha"

    # 3. GET /v1/artifacts/{id}/content
    res_content = client.get(f"/v1/artifacts/{art.id}/content")
    assert res_content.status_code == 200
    assert res_content.content == content_bytes
    assert res_content.headers["Content-Disposition"] == 'attachment; filename="api_download.txt"'
    assert res_content.headers["ETag"] == expected_etag
    assert res_content.headers["Content-Length"] == str(len(content_bytes))

    # 4. Cross-project access denied with header X-Project-ID
    res_forbidden = client.get(
        f"/v1/artifacts/{art.id}",
        headers={"X-Project-ID": "proj_beta"},
    )
    assert res_forbidden.status_code == 403

    res_content_forbidden = client.get(
        f"/v1/artifacts/{art.id}/content",
        headers={"X-Project-ID": "proj_beta"},
    )
    assert res_content_forbidden.status_code == 403

    # 5. GET /v1/projects/{project_id}/artifacts
    res_proj_list = client.get("/v1/projects/proj_alpha/artifacts")
    assert res_proj_list.status_code == 200
    proj_artifacts = res_proj_list.json()
    assert len(proj_artifacts) >= 1
    assert proj_artifacts[0]["id"] == art.id

    # 6. GET /v1/executions/{execution_id}/artifacts
    res_exec_list = client.get("/v1/executions/exec_api_1/artifacts")
    assert res_exec_list.status_code == 200
    exec_artifacts = res_exec_list.json()
    assert len(exec_artifacts) >= 1
    assert exec_artifacts[0]["id"] == art.id

    # Cross-project execution artifacts access denied
    res_exec_forbidden = client.get(
        "/v1/executions/exec_api_1/artifacts",
        headers={"X-Project-ID": "proj_beta"},
    )
    assert res_exec_forbidden.status_code == 403

    # 7. DELETE /v1/artifacts/{id}
    res_del = client.delete(f"/v1/artifacts/{art.id}", headers={"X-Project-ID": "proj_alpha"})
    assert res_del.status_code == 200
    assert res_del.json() == {"success": True, "artifact_id": art.id}

    # Subsequent GET returns 200 with tombstone status and deleted_at
    res_after_del = client.get(f"/v1/artifacts/{art.id}")
    assert res_after_del.status_code == 200
    del_data = res_after_del.json()
    assert del_data["status"] == "deleted"
    assert del_data["deleted_at"] is not None

    # Subsequent content download returns 404
    res_content_del = client.get(f"/v1/artifacts/{art.id}/content")
    assert res_content_del.status_code == 404

    # Excluded from default listing, included with include_deleted=true
    res_exec_empty = client.get("/v1/executions/exec_api_1/artifacts")
    assert len(res_exec_empty.json()) == 0

    res_exec_tombstone = client.get("/v1/executions/exec_api_1/artifacts?include_deleted=true")
    assert len(res_exec_tombstone.json()) == 1
    assert res_exec_tombstone.json()[0]["id"] == art.id
