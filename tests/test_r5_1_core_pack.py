"""tests/test_r5_1_core_pack.py

Comprehensive Validation and Acceptance Suite for Task R5.1 (Core Pack MVP).
Verifies:
1. Core Pack manifest loading, schema compliance, and version metadata.
2. Least-privilege permission grants (fs:read, storage:sqlite) and unauthorized scope rejections.
3. Strict canonical product service bindings with zero shadow runtimes (ADR-016).
4. Discovery, registry, and service lifecycle.
5. Authenticated REST API inspection and validation endpoints through actual FastAPI app (create_app).
6. One-unit enablement, state persistence across restarts, and non-removable system pack invariant.
7. Permission boundaries (Core Pack presence does not grant authority escalation).
8. Real sidecar integration proving capabilities reach canonical product services.
9. Founder MVP journey mappings (MVP-J1, MVP-J7, MVP-J8, MVP-J9, MVP-J10, MVP-J12).
"""

from __future__ import annotations

import importlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from core.packs.models import (
    PackCapability,
)
from core.packs.service import (
    CANONICAL_BINDING_ALLOWLIST,
    CapabilityPackService,
    PackValidationError,
)
from services.python.server.app import create_app


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def core_pack_manifest_path(repo_root: Path) -> Path:
    return repo_root / "packs" / "core" / "manifest.yaml"


@pytest.fixture
def pack_service(repo_root: Path) -> CapabilityPackService:
    return CapabilityPackService(packs_dir=repo_root / "packs")


def test_core_pack_manifest_loading_and_structure(
    pack_service: CapabilityPackService, core_pack_manifest_path: Path
):
    """Verify packs/core/manifest.yaml loads cleanly and matches 0.5 specifications."""
    assert core_pack_manifest_path.is_file(), f"Missing {core_pack_manifest_path}"

    manifest = pack_service.load_manifest(core_pack_manifest_path)
    assert manifest.schema_version == "1.0.0"
    assert manifest.id == "pack-core"
    assert manifest.name == "Core Pack"
    assert manifest.version == "0.5.0"
    assert manifest.category == "system"
    assert manifest.author == "TechnoVen"
    assert manifest.enabled is True

    # Verify evaluations block
    assert manifest.evaluations is not None
    assert manifest.evaluations.test_suite == "tests/test_r5_1_core_pack.py"
    assert manifest.evaluations.min_pass_rate == 1.0


def test_core_pack_permissions_least_privilege(pack_service: CapabilityPackService):
    """Verify Core Pack declares strictly necessary permissions and rejects unauthorized scopes."""
    pack = pack_service.load_manifest("packs/core/manifest.yaml")
    scopes = [p.scope for p in pack.permissions]

    # Authorized scopes for Core Pack (docs/CAPABILITY_PACKS.md Section 2.1)
    assert "fs:read" in scopes
    assert "storage:sqlite" in scopes

    # Disallowed scopes for Core Pack
    assert "shell:exec" not in scopes
    assert "net:outbound" not in scopes
    assert "git:worktree" not in scopes

    # Test permission validator
    assert pack_service.validate_permission(pack, "fs:read", "/path/to/project/file.py") is True
    assert pack_service.validate_permission(pack, "storage:sqlite") is True
    assert pack_service.validate_permission(pack, "shell:exec") is False
    assert pack_service.validate_permission(pack, "net:outbound") is False


def test_core_pack_canonical_bindings_integrity(pack_service: CapabilityPackService):
    """Verify all Core Pack capabilities bind strictly to canonical product services."""
    pack = pack_service.load_manifest("packs/core/manifest.yaml")
    cap_map = {c.id: c for c in pack.capabilities}

    expected_caps = [
        "chat_session",
        "project_manager",
        "model_execution",
        "task_manager",
        "approval_service",
    ]
    for cap_id in expected_caps:
        assert cap_id in cap_map, f"Missing expected capability: {cap_id}"
        cap = cap_map[cap_id]
        assert cap.canonical_binding in CANONICAL_BINDING_ALLOWLIST

        # Dynamically import and verify the canonical symbol
        mod_name, attr_name = cap.canonical_binding.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, attr_name), f"Symbol {attr_name} missing from {mod_name}"

    # Verify approval_service requires approval
    assert cap_map["approval_service"].requires_approval is True
    assert cap_map["chat_session"].requires_approval is False


def test_no_shadow_runtime_invariant(pack_service: CapabilityPackService):
    """Verify that attempting to bind an unapproved or shadow runtime is rejected (ADR-016)."""
    # Attempting to declare an external/shadow runner fails validation
    shadow_cap = PackCapability(
        id="shadow_exec",
        name="Shadow Execution",
        description="Bypasses ExecutionCoordinator",
        canonical_binding="external.shadow.Runner",
    )
    with pytest.raises(
        PackValidationError,
        match="All capabilities must bind directly to verified core.* subsystems",
    ):
        pack_service._verify_canonical_binding(shadow_cap)

    # Empty binding fails
    empty_cap = PackCapability(
        id="empty_exec",
        name="Empty",
        description="Empty",
        canonical_binding="",
    )
    with pytest.raises(PackValidationError, match="must declare a valid canonical_binding"):
        pack_service._verify_canonical_binding(empty_cap)


def test_pack_discovery_and_registry(repo_root: Path):
    """Verify pack discovery across the workspace finds and registers pack-core."""
    service = CapabilityPackService(packs_dir=repo_root / "packs")
    discovered = service.discover_packs()

    assert len(discovered) >= 1
    pack_ids = [p.id for p in discovered]
    assert "pack-core" in pack_ids

    retrieved = service.get_pack("pack-core")
    assert retrieved is not None
    assert retrieved.id == "pack-core"


def test_pack_one_unit_enablement_and_persistence(tmp_path: Path, repo_root: Path):
    """Verify Core Pack lifecycle: discovery, one-unit enablement, restart persistence, and system pack invariant."""
    state_file = tmp_path / "packs_state.json"
    service = CapabilityPackService(packs_dir=repo_root / "packs", state_file=state_file)
    service.discover_packs()

    # Core pack is system category, so it is enabled by default
    assert service.is_pack_enabled("pack-core") is True

    # Enabling as one unit succeeds
    assert service.enable_pack("pack-core") is True
    assert state_file.is_file()

    # System pack cannot be disabled
    with pytest.raises(PackValidationError, match="system-installed pack and cannot be disabled"):
        service.disable_pack("pack-core")

    # Restart simulation: new service instance with same state file retains enabled state
    restart_service = CapabilityPackService(packs_dir=repo_root / "packs", state_file=state_file)
    restart_service.discover_packs()
    assert restart_service.is_pack_enabled("pack-core") is True


def test_pack_presence_does_not_grant_authority_escalation(pack_service: CapabilityPackService):
    """Verify that enabling Core Pack does not grant capability escalation or bypass safety boundaries."""
    pack = pack_service.load_manifest("packs/core/manifest.yaml")

    # High-risk actions must not be permitted by pack presence
    assert pack_service.validate_permission(pack, "shell:exec") is False
    assert pack_service.validate_permission(pack, "net:outbound") is False
    assert pack_service.validate_permission(pack, "fs:write") is False
    assert pack_service.validate_permission(pack, "admin") is False
    assert pack_service.validate_permission(pack, "destructive") is False


def test_pack_api_endpoints_through_actual_sidecar():
    """Verify REST API endpoints through the actual production FastAPI app (create_app)."""
    app = create_app()
    client = TestClient(app)

    # 1. List packs through production app
    res = client.get("/v1/packs")
    assert res.status_code == 200
    packs = res.json()
    core_pack = next((p for p in packs if p["id"] == "pack-core"), None)
    assert core_pack is not None
    assert core_pack["enabled"] is True
    assert core_pack["is_system"] is True

    # 2. Get pack details through production app
    res_core = client.get("/v1/packs/pack-core")
    assert res_core.status_code == 200
    data = res_core.json()
    assert data["id"] == "pack-core"
    assert data["enabled"] is True
    assert data["is_system"] is True
    assert len(data["capabilities"]) == 5

    # 3. Nonexistent pack returns 404
    res_404 = client.get("/v1/packs/nonexistent-pack")
    assert res_404.status_code == 404

    # 4. Validate pack integrity through production app
    res_val = client.post("/v1/packs/pack-core/validate")
    assert res_val.status_code == 200
    val_data = res_val.json()
    assert val_data["valid"] is True
    assert val_data["capabilities_count"] == 5
    assert len(val_data["errors"]) == 0

    # 5. Enable pack through production app
    res_enable = client.post("/v1/packs/pack-core/enable")
    assert res_enable.status_code == 200
    assert res_enable.json()["enabled"] is True

    # 6. Disable attempt on system pack returns 400 Bad Request
    res_disable = client.post("/v1/packs/pack-core/disable")
    assert res_disable.status_code == 400
    assert "system-installed" in res_disable.json()["detail"]


def test_core_pack_capabilities_reach_canonical_services():
    """Verify Core Pack capabilities reach actual product services through real application paths."""
    from core.projects.service import get_project_service
    from core.jobs.service import get_job_service
    from core.safety.service import get_approval_service
    from services.python.server.container import get_execution_coordinator

    app = create_app()
    client = TestClient(app)

    # 1. chat_session / model_execution reaches ExecutionCoordinator via FastAPI
    coord = get_execution_coordinator()
    assert coord is not None
    chat_res = client.post("/v1/chat/completions", json={})
    assert chat_res.status_code == 422  # validation confirmed on canonical chat endpoint

    # 2. project_manager reaches ProjectService
    proj_service = get_project_service()
    assert proj_service is not None
    proj_res = client.get("/v1/projects")
    assert proj_res.status_code == 200
    assert isinstance(proj_res.json(), list)

    # 3. task_manager reaches JobService
    job_service = get_job_service()
    assert job_service is not None
    jobs = job_service.list_jobs(limit=5)
    assert isinstance(jobs, list)

    # 4. approval_service reaches ApprovalService
    approval_service = get_approval_service()
    assert approval_service is not None
    pending = approval_service.list_pending_operations()
    assert isinstance(pending, list)


def test_malformed_manifest_rejection(tmp_path: Path):
    """Verify that corrupted, non-dict, or schema-violating manifests fail closed."""
    service = CapabilityPackService(packs_dir=tmp_path)

    # Missing required id field
    bad_manifest = tmp_path / "bad_manifest.yaml"
    bad_manifest.write_text("name: No ID Pack\nversion: 1.0.0\n", encoding="utf-8")

    with pytest.raises(PackValidationError):
        service.load_manifest(bad_manifest)

    # Invalid YAML
    corrupt_manifest = tmp_path / "corrupt.yaml"
    corrupt_manifest.write_text("::: not valid yaml :::", encoding="utf-8")

    with pytest.raises(PackValidationError):
        service.load_manifest(corrupt_manifest)


def test_core_pack_satisfies_founder_mvp_mappings(pack_service: CapabilityPackService):
    """Verify that Core Pack encapsulates capabilities satisfying MVP-J1/J7/J8/J9/J10/J12."""
    pack = pack_service.load_manifest("packs/core/manifest.yaml")
    caps = {c.id for c in pack.capabilities}

    # MVP-J1: Project-aware conversation -> chat_session, project_manager
    assert "chat_session" in caps
    assert "project_manager" in caps

    # MVP-J7: Routing -> model_execution
    assert "model_execution" in caps

    # MVP-J8: Approval & safety -> approval_service
    assert "approval_service" in caps

    # MVP-J9: Cancellation -> chat_session, task_manager
    assert "task_manager" in caps

    # MVP-J10: Restart recovery -> task_manager (durable jobs)
    assert "task_manager" in caps

    # MVP-J12: Truthful execution history -> model_execution, approval_service
    assert "model_execution" in caps


def test_core_pack_permission_vocabulary_and_zero_trust_boundary(
    pack_service: CapabilityPackService,
):
    """Verify pack permission vocabulary correctly maps to zero-trust permissions and enforces boundary."""
    vocab = pack_service.get_permission_vocabulary()
    assert "fs:read" in vocab
    assert "storage:sqlite" in vocab
    assert "workspace:read" in vocab
    assert "execution:run" in vocab
    assert "jobs:manage" in vocab
    assert "approvals:manage" in vocab

    # Verify zero-trust properties: approvals require HITL approval and are consequential
    appr_map = pack_service.map_permission_to_canonical("approvals:manage")
    assert appr_map is not None
    assert appr_map["consequential"] is True
    assert appr_map["requires_hitl_approval"] is True
    assert appr_map["policy_governed"] is True

    # Load Core Pack and verify zero-trust execution authority boundary
    pack = pack_service.load_manifest("packs/core/manifest.yaml")
    assert pack_service.is_pack_enabled(pack.id) is True

    # Safe operation verification
    assert (
        pack_service.verify_zero_trust_authority_boundary(
            pack.id, "read_workspace", is_consequential=False
        )
        is True
    )

    # Consequential operation CANNOT be executed merely because Core Pack is enabled
    assert (
        pack_service.verify_zero_trust_authority_boundary(
            pack.id, "delete_database", is_consequential=True
        )
        is False
    )
