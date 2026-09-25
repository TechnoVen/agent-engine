"""tests/test_r2_workspace_paths.py

Milestone R2 Task R2.5: Canonical workspace path enforcement & containment test suite.
Covers all 20 required verification scenarios per CTO Security Review.
"""

import os
from unittest.mock import patch
import pytest

from core.safety.pending import (
    PendingOperationRegistry,
    SecurityBoundaryViolation,
)
from core.safety.policy import PolicyEngine
from core.skills.boundary import (
    CapabilityBoundary,
    validate_project_path,
)
from core.skills.models import SkillPermission
from core.skills.path import (
    WorkspacePathResolver,
    WorkspacePathViolation,
    _is_relative_to,
    compute_effective_workspace_scopes,
)


@pytest.fixture
def workspace(tmp_path):
    """Provide an isolated workspace project directory with subdirectories."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "docs").mkdir()
    (ws / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (ws / "docs" / "readme.txt").write_text("documentation\n", encoding="utf-8")
    return ws


@pytest.fixture
def outside_dir(tmp_path):
    """Provide an external directory outside the project root."""
    out = tmp_path / "outside"
    out.mkdir()
    (out / "secret.txt").write_text("super_secret_outside_data\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Test 1: ../ Lexical escape blocked
# ---------------------------------------------------------------------------
def test_01_parent_directory_lexical_escape_blocked(workspace):
    """1. ../ lexical escape blocked."""
    resolver = WorkspacePathResolver(workspace)

    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve("../outside.txt")
    assert (
        "escapes project root" in str(exc_info.value).lower()
        or "isolation violation" in str(exc_info.value).lower()
    )

    with pytest.raises(WorkspacePathViolation):
        resolver.resolve("src/../../outside.txt")

    # validate_project_path also raises WorkspacePathViolation (subclass of PermissionError)
    with pytest.raises(PermissionError):
        validate_project_path(workspace, "../outside.txt")


# ---------------------------------------------------------------------------
# Test 2: Absolute external path blocked
# ---------------------------------------------------------------------------
def test_02_absolute_external_path_blocked(workspace, outside_dir):
    """2. Absolute external path blocked."""
    resolver = WorkspacePathResolver(workspace)

    external_file = outside_dir / "secret.txt"
    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve(str(external_file))
    assert (
        "escapes project root" in str(exc_info.value).lower()
        or "isolation violation" in str(exc_info.value).lower()
    )

    with pytest.raises(PermissionError):
        validate_project_path(workspace, str(external_file))


# ---------------------------------------------------------------------------
# Test 3: External-target symlink blocked
# ---------------------------------------------------------------------------
def test_03_external_target_symlink_blocked(workspace, outside_dir):
    """3. External-target symlink blocked."""
    symlink_file = workspace / "escape_link.txt"
    symlink_file.symlink_to(outside_dir / "secret.txt")

    resolver = WorkspacePathResolver(workspace)
    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve("escape_link.txt")
    assert (
        "escapes project root" in str(exc_info.value).lower()
        or "isolation violation" in str(exc_info.value).lower()
    )


# ---------------------------------------------------------------------------
# Test 4: Intermediate external symlink blocked
# ---------------------------------------------------------------------------
def test_04_intermediate_external_symlink_blocked(workspace, outside_dir):
    """4. Intermediate external symlink blocked."""
    symlink_dir = workspace / "external_dir"
    symlink_dir.symlink_to(outside_dir)

    resolver = WorkspacePathResolver(workspace)
    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve("external_dir/secret.txt")
    assert (
        "escapes project root" in str(exc_info.value).lower()
        or "isolation violation" in str(exc_info.value).lower()
    )


# ---------------------------------------------------------------------------
# Test 5: Internal symlink remains allowed where policy permits
# ---------------------------------------------------------------------------
def test_05_internal_symlink_allowed(workspace):
    """5. Internal symlink remains allowed where policy permits."""
    real_target = workspace / "src" / "main.py"
    link_path = workspace / "main_link.py"
    link_path.symlink_to(real_target)

    resolver = WorkspacePathResolver(workspace)
    resolved = resolver.resolve("main_link.py")

    assert resolved.canonical_path == real_target.resolve()
    assert resolved.canonical_relative_path == "src/main.py"
    assert resolved.exists is True
    assert str(resolved) == str(real_target.resolve())

    # Public dict omits machine host path
    pub = resolved.to_public_dict()
    assert pub["relative_path"] == "src/main.py"
    assert "workspace" not in pub["relative_path"]
    assert str(workspace) not in str(pub)


# ---------------------------------------------------------------------------
# Test 6: Changing internal symlink destination invalidates prior exact approval
# ---------------------------------------------------------------------------
def test_06_changing_symlink_invalidates_prior_exact_approval(workspace):
    """6. Changing internal symlink destination invalidates prior exact approval."""
    target_a = workspace / "target_a.txt"
    target_a.write_text("initial safe content")
    target_b = workspace / "target_b.txt"
    target_b.write_text("different sensitive content")

    active_link = workspace / "active_link.txt"
    active_link.symlink_to(target_a)

    policy_engine = PolicyEngine()
    registry = PendingOperationRegistry()

    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ],
        policy_engine=policy_engine,
        pending_registry=registry,
    )

    # Initial resolution binds canonical relative destination ("target_a.txt")
    initial_res = boundary.resolve_path("active_link.txt")
    assert initial_res.canonical_relative_path == "target_a.txt"

    # Register operation using canonical destination
    approved_args = {"path": initial_res.canonical_relative_path}
    op = registry.register_operation(
        tool_name="filesystem.read_file",
        tool_args=approved_args,
        capability="filesystem",
    )
    _, approval_token = registry.approve_operation(op.operation_id)

    # Before execution, adversary swaps active_link to point to target_b
    active_link.unlink()
    active_link.symlink_to(target_b)

    # Executing read_file via active_link now resolves canonical destination target_b.txt
    # which fails cryptographic argument verification against the approved token
    with pytest.raises(SecurityBoundaryViolation) as exc_info:
        boundary.read_file("active_link.txt", approval_token=approval_token)
    assert "Cryptographic argument verification failed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 7: Nonexistent target with safe parent allowed
# ---------------------------------------------------------------------------
def test_07_nonexistent_target_with_safe_parent_allowed(workspace):
    """7. Nonexistent target with safe parent allowed."""
    resolver = WorkspacePathResolver(workspace)
    resolved = resolver.resolve("src/new_module/deep/file.py")

    assert resolved.exists is False
    assert resolved.canonical_relative_path == "src/new_module/deep/file.py"
    assert (
        resolved.canonical_path == (workspace / "src" / "new_module" / "deep" / "file.py").resolve()
    )
    assert resolved.matched_scope == workspace.resolve()


# ---------------------------------------------------------------------------
# Test 8: Nonexistent target with escaping symlink parent blocked
# ---------------------------------------------------------------------------
def test_08_nonexistent_target_with_escaping_symlink_parent_blocked(workspace, outside_dir):
    """8. Nonexistent target with escaping symlink parent blocked."""
    escaping_dir_link = workspace / "escape_folder"
    escaping_dir_link.symlink_to(outside_dir)

    resolver = WorkspacePathResolver(workspace)
    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve("escape_folder/new_file.txt")
    assert (
        "escapes project root" in str(exc_info.value).lower()
        or "isolation violation" in str(exc_info.value).lower()
    )


# ---------------------------------------------------------------------------
# Test 9: Trusted subscope permits target inside it
# ---------------------------------------------------------------------------
def test_09_trusted_subscope_permits_target_inside(workspace):
    """9. Trusted subscope permits target inside it."""
    src_dir = workspace / "src"
    resolver = WorkspacePathResolver(workspace, authorized_scopes=[src_dir])

    resolved = resolver.resolve("src/main.py")
    assert resolved.canonical_path == (src_dir / "main.py").resolve()
    assert resolved.matched_scope == src_dir.resolve()
    assert resolved.canonical_relative_path == "src/main.py"


# ---------------------------------------------------------------------------
# Test 10: Target outside subscope but inside project blocked
# ---------------------------------------------------------------------------
def test_10_target_outside_subscope_blocked(workspace):
    """10. Target outside subscope but inside project blocked."""
    src_dir = workspace / "src"
    resolver = WorkspacePathResolver(workspace, authorized_scopes=[src_dir])

    # docs/readme.txt is inside project root, but outside authorized scope 'src'
    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve("docs/readme.txt")
    assert "outside authorized workspace scopes" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test 11: Caller cannot widen subscope (widening ignored / declared scope enforced)
# ---------------------------------------------------------------------------
def test_11_caller_cannot_widen_subscope(workspace):
    """11. Caller cannot widen subscope (widening ignored / declared scope enforced)."""
    declared_scopes = ["src"]
    # Caller attempts to widen to full project root
    requested_scopes = ["."]

    effective = compute_effective_workspace_scopes(
        project_root=workspace,
        declared_scopes=declared_scopes,
        requested_scopes=requested_scopes,
    )

    expected_src = (workspace / "src").resolve()
    assert effective == [expected_src]

    # Boundary initialized with effective scopes enforces src constraint
    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ],
        workspace_scopes=effective,
    )
    with pytest.raises(WorkspacePathViolation):
        boundary.resolve_path("docs/readme.txt")


# ---------------------------------------------------------------------------
# Test 12: Malicious Skill metadata scope outside project rejected
# ---------------------------------------------------------------------------
def test_12_malicious_skill_metadata_scope_outside_project_rejected(workspace):
    """12. Malicious Skill metadata scope outside project rejected."""
    # Declarations escaping project root
    with pytest.raises(WorkspacePathViolation) as exc_info:
        compute_effective_workspace_scopes(
            project_root=workspace,
            declared_scopes=["../../etc"],
        )
    assert "escapes project root" in str(exc_info.value).lower()

    # Absolute scope escaping project root
    with pytest.raises(WorkspacePathViolation):
        compute_effective_workspace_scopes(
            project_root=workspace,
            declared_scopes=["/etc"],
        )

    # WorkspacePathResolver directly rejects malicious scopes
    with pytest.raises(WorkspacePathViolation):
        WorkspacePathResolver(workspace, authorized_scopes=["../forbidden"])


# ---------------------------------------------------------------------------
# Test 13: Null-byte path rejected (\0)
# ---------------------------------------------------------------------------
def test_13_null_byte_path_rejected_fail_closed(workspace):
    """13. Null-byte path rejected (\0)."""
    resolver = WorkspacePathResolver(workspace)

    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve("src/main.py\0.txt")
    assert "null byte" in str(exc_info.value).lower()

    with pytest.raises(WorkspacePathViolation):
        resolver.resolve("\0/etc/passwd")

    with pytest.raises(WorkspacePathViolation):
        compute_effective_workspace_scopes(workspace, declared_scopes=["src\0bad"])

    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ, SkillPermission.WRITE_LOCAL],
    )
    with pytest.raises(WorkspacePathViolation):
        boundary.read_file("test\0file.txt")

    with pytest.raises(WorkspacePathViolation):
        boundary.write_file("test\0file.txt", "data")


# ---------------------------------------------------------------------------
# Test 14: Canonical project-relative path reaches policy
# ---------------------------------------------------------------------------
def test_14_canonical_project_relative_path_reaches_policy(workspace):
    """14. Canonical project-relative path reaches policy."""
    policy_engine = PolicyEngine()
    evaluated_args = []

    original_evaluate = policy_engine.evaluate

    def mock_eval(tool_name, tool_args, context):
        evaluated_args.append(dict(tool_args))
        return original_evaluate(tool_name=tool_name, tool_args=tool_args, context=context)

    with patch.object(policy_engine, "evaluate", side_effect=mock_eval):
        boundary = CapabilityBoundary(
            project_root=workspace,
            declared_permissions=[SkillPermission.READ],
            policy_engine=policy_engine,
        )
        # Request path with redundant components
        boundary.read_file("src/../src/./main.py")

    assert len(evaluated_args) == 1
    # Must receive canonical relative path, not redundant or host-absolute
    assert evaluated_args[0]["path"] == "src/main.py"


# ---------------------------------------------------------------------------
# Test 15: Exact approval digest uses canonical target
# ---------------------------------------------------------------------------
def test_15_exact_approval_digest_uses_canonical_target(workspace):
    """15. Exact approval digest uses canonical target."""
    registry = PendingOperationRegistry()
    policy_engine = PolicyEngine()

    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.WRITE_LOCAL],
        policy_engine=policy_engine,
        pending_registry=registry,
    )

    # Approve write to canonical relative target bound to project identity
    canonical_rel = "docs/new_doc.txt"
    approved_args = {
        "path": canonical_rel,
        "content": "hello world",
        "project_id": boundary.project_id,
    }
    op = registry.register_operation(
        tool_name="filesystem.write_file",
        tool_args=approved_args,
        capability="filesystem",
    )
    _, token = registry.approve_operation(op.operation_id)

    # Writing using relative path with redundant components succeeds because
    # it canonicalizes to docs/new_doc.txt before policy check
    written_bytes = boundary.write_file(
        "docs/../docs/new_doc.txt", "hello world", approval_token=token
    )
    assert written_bytes == len("hello world".encode("utf-8"))
    assert (workspace / "docs" / "new_doc.txt").read_text() == "hello world"


# ---------------------------------------------------------------------------
# Test 16: Subprocess cwd outside scope blocked
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_16_subprocess_cwd_outside_scope_blocked(workspace, outside_dir):
    """16. Subprocess cwd outside scope blocked."""
    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.EXECUTE],
        workspace_scopes=[workspace / "src"],
    )

    # Cwd pointing outside project root
    with pytest.raises(WorkspacePathViolation):
        await boundary.run_subprocess(["ls"], cwd=outside_dir)

    # Cwd pointing inside project root but outside authorized scope 'src'
    with pytest.raises(WorkspacePathViolation):
        await boundary.run_subprocess(["ls"], cwd=workspace / "docs")

    # Cwd pointing to nonexistent folder
    with pytest.raises(FileNotFoundError):
        await boundary.run_subprocess(["ls"], cwd=workspace / "src" / "nonexistent")

    # Cwd pointing to file rather than directory
    with pytest.raises(NotADirectoryError):
        await boundary.run_subprocess(["ls"], cwd=workspace / "src" / "main.py")

    # Valid cwd inside scope succeeds
    code, stdout, stderr = await boundary.run_subprocess(["pwd"], cwd="src")
    assert code == 0
    assert "src" in stdout


# ---------------------------------------------------------------------------
# Test 17: read_file honors canonical containment
# ---------------------------------------------------------------------------
def test_17_read_file_honors_canonical_containment(workspace, outside_dir):
    """17. read_file honors canonical containment."""
    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ],
    )

    with pytest.raises(WorkspacePathViolation):
        boundary.read_file(str(outside_dir / "secret.txt"))

    with pytest.raises(WorkspacePathViolation):
        boundary.read_file("../../outside_secret.txt")

    # Inside project succeeds
    content = boundary.read_file("src/main.py")
    assert "print('hello')" in content


# ---------------------------------------------------------------------------
# Test 18: write_file honors canonical containment
# ---------------------------------------------------------------------------
def test_18_write_file_honors_canonical_containment(workspace, outside_dir):
    """18. write_file honors canonical containment."""
    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.WRITE_LOCAL],
    )

    with pytest.raises(WorkspacePathViolation):
        boundary.write_file(str(outside_dir / "overwrite.txt"), "forbidden")

    with pytest.raises(WorkspacePathViolation):
        boundary.write_file("../escape.txt", "forbidden")

    assert not (outside_dir / "overwrite.txt").exists()


# ---------------------------------------------------------------------------
# Test 19: delete_file honors canonical containment
# ---------------------------------------------------------------------------
def test_19_delete_file_honors_canonical_containment(workspace, outside_dir):
    """19. delete_file honors canonical containment."""
    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.WRITE_LOCAL, SkillPermission.DESTRUCTIVE],
    )

    outside_file = outside_dir / "secret.txt"
    with pytest.raises(WorkspacePathViolation):
        boundary.delete_file(str(outside_file))

    assert outside_file.exists()


# ---------------------------------------------------------------------------
# Test 20: Platform-specific path semantics covered
# ---------------------------------------------------------------------------
def test_20_platform_specific_path_semantics(workspace):
    """20. Platform-specific path semantics covered (separators, case normalization, Windows drive roots)."""
    resolver = WorkspacePathResolver(workspace)

    # Backslash separator normalization on POSIX and Windows
    resolved_sub = resolver.resolve("src\\main.py")
    assert resolved_sub.canonical_path == (workspace / "src" / "main.py").resolve()
    assert resolved_sub.canonical_relative_path == "src/main.py"

    # Drive-relative path rejected (e.g. C:escape.txt) fail-closed
    with pytest.raises(WorkspacePathViolation) as exc_info:
        resolver.resolve("C:escape.txt")
    assert "drive-relative" in str(exc_info.value).lower()

    # Foreign drive absolute path rejected on non-Windows
    if os.name != "nt":
        with pytest.raises(WorkspacePathViolation) as exc_info:
            resolver.resolve("C:\\Windows\\System32")
        assert (
            "escapes" in str(exc_info.value).lower()
            or "windows absolute drive" in str(exc_info.value).lower()
        )

    # Case normalization check in _is_relative_to
    path_a = workspace / "src" / "main.py"
    path_b = workspace / "src"
    assert _is_relative_to(path_a, path_b) is True
    assert _is_relative_to(path_b, path_a) is False


# ---------------------------------------------------------------------------
# Test 21: Multiple-scope union and intersection semantics (empty fails closed)
# ---------------------------------------------------------------------------
def test_21_multiple_scope_union_and_intersection_semantics(workspace):
    """21. Multiple-scope union and intersection semantics:
    effective = project_root ∩ union(capability_scopes) ∩ union(policy_scopes) ∩ optional_caller_narrower_scope.
    Empty effective authority must fail closed.
    """
    (workspace / "tests").mkdir(parents=True, exist_ok=True)
    (workspace / "docs").mkdir(parents=True, exist_ok=True)

    # 1. Non-empty intersection of unions: {"src", "tests"} ∩ {"src", "docs"} == {"src"}
    effective = compute_effective_workspace_scopes(
        project_root=workspace,
        capability_scopes=["src", "tests"],
        policy_scopes=["src", "docs"],
    )
    expected_src = (workspace / "src").resolve()
    assert effective == [expected_src]

    # 2. Disjoint intersection fails closed (empty effective authority raises WorkspacePathViolation)
    with pytest.raises(WorkspacePathViolation) as exc_info:
        compute_effective_workspace_scopes(
            project_root=workspace,
            capability_scopes=["src"],
            policy_scopes=["docs"],
        )
    assert "no intersecting authority" in str(exc_info.value).lower()

    # 3. Explicit empty policy scopes list fails closed
    with pytest.raises(WorkspacePathViolation) as exc_info:
        compute_effective_workspace_scopes(
            project_root=workspace,
            capability_scopes=["src"],
            policy_scopes=[],
        )
    assert "empty" in str(exc_info.value).lower()

    # 4. Explicit empty authorized_scopes list in WorkspacePathResolver fails closed
    with pytest.raises(WorkspacePathViolation) as exc_info:
        WorkspacePathResolver(workspace, authorized_scopes=[])
    assert "empty" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test 22: Caller narrowing separation and invalid narrower scope rejection
# ---------------------------------------------------------------------------
def test_22_caller_narrowing_separation_and_invalid_scope_rejection(workspace):
    """22. Caller narrowing separation:
    Caller can restrict authority, never create or widen authority.
    Invalid or disjoint requested scope fails closed.
    """
    (workspace / "src" / "utils").mkdir(parents=True, exist_ok=True)
    expected_utils = (workspace / "src" / "utils").resolve()
    expected_src = (workspace / "src").resolve()

    # 1. Valid narrowing within authorized capability scope
    effective_narrowed = compute_effective_workspace_scopes(
        project_root=workspace,
        capability_scopes=["src"],
        requested_workspace_scope="src/utils",
    )
    assert effective_narrowed == [expected_utils]

    # 2. Requested working directory alias also narrows
    effective_narrowed_wd = compute_effective_workspace_scopes(
        project_root=workspace,
        capability_scopes=["src"],
        requested_workspace_scope=None,
        requested_scopes=None,
    )
    assert effective_narrowed_wd == [expected_src]

    # 3. Disjoint caller scope rejected fail-closed
    with pytest.raises(WorkspacePathViolation) as exc_info:
        compute_effective_workspace_scopes(
            project_root=workspace,
            capability_scopes=["src"],
            requested_workspace_scope="docs",
        )
    assert "outside authorized workspace authority" in str(exc_info.value).lower()

    # 4. Widening attempt rejected via anti-widening (base scope preserved)
    effective_anti_widened = compute_effective_workspace_scopes(
        project_root=workspace,
        capability_scopes=["src"],
        requested_workspace_scope=".",
    )
    assert effective_anti_widened == [expected_src]


# ---------------------------------------------------------------------------
# Test 23: ResolvedWorkspacePath.__fspath__ returns canonical destination
# ---------------------------------------------------------------------------
def test_23_resolved_workspace_path_fspath_returns_canonical_destination(workspace):
    """23. ResolvedWorkspacePath.__fspath__: os.fspath(val) == canonical_destination on aliased inputs."""
    target_file = workspace / "src" / "main.py"
    symlink_file = workspace / "src" / "alias.py"
    if symlink_file.exists() or symlink_file.is_symlink():
        symlink_file.unlink()
    symlink_file.symlink_to(target_file)

    resolver = WorkspacePathResolver(workspace)

    # 1. Symlink aliased input
    resolved_symlink = resolver.resolve(symlink_file)
    assert isinstance(resolved_symlink, os.PathLike)
    assert os.fspath(resolved_symlink) == str(target_file.resolve())
    assert os.fspath(resolved_symlink) != str(symlink_file)

    # 2. Traversal aliased input
    resolved_traversal = resolver.resolve("src/../src/./main.py")
    assert isinstance(resolved_traversal, os.PathLike)
    assert os.fspath(resolved_traversal) == str(target_file.resolve())
    assert os.fspath(resolved_traversal) != "src/../src/./main.py"


# ---------------------------------------------------------------------------
# Test 24: Cross-project exact authorization binding fails closed
# ---------------------------------------------------------------------------
def test_24_cross_project_exact_authorization_binding(tmp_path):
    """24. Bind immutable project identity (project_id) into file authorization;
    ensure approval for Project A cannot authorize Project B even with identical relative paths.
    """
    proj_a = tmp_path / "project_a"
    proj_b = tmp_path / "project_b"
    proj_a.mkdir(parents=True, exist_ok=True)
    proj_b.mkdir(parents=True, exist_ok=True)
    (proj_a / "src").mkdir(parents=True, exist_ok=True)
    (proj_b / "src").mkdir(parents=True, exist_ok=True)

    registry = PendingOperationRegistry()
    policy_engine = PolicyEngine()

    boundary_a = CapabilityBoundary(
        project_root=proj_a,
        declared_permissions=[SkillPermission.WRITE_LOCAL],
        policy_engine=policy_engine,
        pending_registry=registry,
        project_id="proj_alpha_123",
    )
    boundary_b = CapabilityBoundary(
        project_root=proj_b,
        declared_permissions=[SkillPermission.WRITE_LOCAL],
        policy_engine=policy_engine,
        pending_registry=registry,
        project_id="proj_beta_456",
    )

    # Approve write to canonical relative target on Project A
    canonical_rel = "src/config.py"
    approved_args = {
        "path": canonical_rel,
        "content": "secret_key = 'A'",
        "project_id": "proj_alpha_123",
    }
    op = registry.register_operation(
        tool_name="filesystem.write_file",
        tool_args=approved_args,
        capability="filesystem",
    )
    _, token = registry.approve_operation(op.operation_id)

    # Attempting to consume token on Project B with identical relative path fails closed
    from core.safety.pending import SecurityBoundaryViolation

    with pytest.raises(SecurityBoundaryViolation) as exc_info:
        boundary_b.write_file(canonical_rel, "secret_key = 'A'", approval_token=token)
    assert (
        "cryptographic argument verification failed" in str(exc_info.value).lower()
        or "does not match" in str(exc_info.value).lower()
    )

    # Ensure Project B file was not written
    assert not (proj_b / "src" / "config.py").exists()

    # Now execute on Project A with the valid token - succeeds
    written = boundary_a.write_file(canonical_rel, "secret_key = 'A'", approval_token=token)
    assert written == len("secret_key = 'A'".encode("utf-8"))
    assert (proj_a / "src" / "config.py").read_text() == "secret_key = 'A'"
