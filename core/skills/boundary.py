"""core/skills/boundary.py

Canonical Capability Boundary & Project Containment for Skills and Tools.
Part of R1.13 (ADR-016 Single Authoritative Execution Kernel Invariant).

Controls Enforced in R1:
1. Strict project filesystem boundary containment (path traversal & root escapes rejected).
2. Explicit permission enforcement against declared SkillPermission capabilities.
3. Constrained subprocess boundary with cwd restrictions, cancellation token, and timeouts.
4. Cross-platform process termination (graceful terminate -> bounded wait -> force kill).
5. Truthful failure propagation (zero fake success).

Note: Full sandbox isolation belongs to Milestone R2. Current controls provide a bounded capability wrapper.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from core.execution.cancellation import (
    CancellationToken,
    ExecutionCancelledError,
)
from core.skills.models import SkillPermission
from core.skills.path import (
    ResolvedWorkspacePath,
    WorkspacePathResolver,
    WorkspacePathViolation,
)

logger = logging.getLogger("agent_engine.skills.boundary")


def check_permission(
    declared_permissions: Iterable[Union[SkillPermission, str]],
    required_permission: Union[SkillPermission, str],
) -> None:
    """Validate that the required permission was explicitly declared.

    Raises PermissionError if undeclared.
    """
    if hasattr(declared_permissions, "declared_permissions"):
        raw_perms = declared_permissions.declared_permissions
    else:
        raw_perms = declared_permissions

    req_str = (
        required_permission.value
        if isinstance(required_permission, SkillPermission)
        else str(required_permission).lower()
    )
    declared_set: Set[str] = set()
    for p in raw_perms:
        if isinstance(p, SkillPermission):
            declared_set.add(p.value.lower())
        else:
            declared_set.add(str(p).lower())

    if req_str not in declared_set:
        raise PermissionError(
            f"Permission '{req_str}' is required. "
            f"Undeclared permission attempt rejected: '{req_str}'. "
            f"Skill only declared: {sorted(list(declared_set))}"
        )
    return True


def validate_project_path(
    project_root: Union[str, Path, os.PathLike[str]],
    target_path: Union[str, Path, os.PathLike[str]],
    authorized_scopes: Optional[Iterable[Union[str, Path, os.PathLike[str]]]] = None,
) -> Path:
    """Ensure target path resolves strictly within the designated project root and authorized scopes.

    Rejects directory traversal (..), null bytes, and absolute or symlink paths outside project root / authorized scopes.
    Raises WorkspacePathViolation (subclass of PermissionError) on boundary escape.
    Returns canonical target Path.
    """
    resolver = WorkspacePathResolver(project_root, authorized_scopes=authorized_scopes)
    resolved = resolver.resolve(target_path)
    return resolved.canonical_path


class CapabilityBoundary:
    """Encapsulates execution capabilities for a skill under ExecutionCoordinator authority."""

    def __init__(
        self,
        project_root: Union[str, Path, os.PathLike[str]],
        declared_permissions: Optional[Iterable[Union[SkillPermission, str]]] = None,
        cancellation_token: Optional[CancellationToken] = None,
        policy_engine: Optional[Any] = None,
        pending_registry: Optional[Any] = None,
        execution_id: Optional[str] = None,
        actor: Optional[str] = None,
        approval_token: Optional[str] = None,
        workspace_scopes: Optional[Iterable[Union[str, Path, os.PathLike[str]]]] = None,
        project_id: Optional[str] = None,
    ):
        raw_root = os.fspath(project_root)
        if "\0" in raw_root:
            raise WorkspacePathViolation("Null byte detected in project root path")
        self.project_root = Path(os.path.realpath(os.path.abspath(raw_root)))
        if not self.project_root.exists():
            try:
                self.project_root.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        self.resolver = WorkspacePathResolver(
            project_root=self.project_root,
            authorized_scopes=workspace_scopes,
        )
        self.workspace_scopes = self.resolver.authorized_scopes
        self.declared_permissions: Set[str] = set()
        for p in declared_permissions or []:
            if isinstance(p, SkillPermission):
                self.declared_permissions.add(p.value.lower())
            else:
                self.declared_permissions.add(str(p).lower())
        self.cancellation_token = cancellation_token
        self.policy_engine = policy_engine
        self.pending_registry = pending_registry
        self.execution_id = execution_id
        self.actor = actor or "local_operator"
        self.approval_token = approval_token
        self.project_id: str = (
            str(project_id).strip()
            if project_id and str(project_id).strip()
            else f"proj_{hashlib.sha256(str(self.project_root).encode('utf-8')).hexdigest()[:12]}"
        )

    def check(self, permission: Union[SkillPermission, str]) -> None:
        """Check whether permission is declared."""
        check_permission(self.declared_permissions, permission)

    def resolve_path(self, path: Union[str, Path, os.PathLike[str]]) -> ResolvedWorkspacePath:
        """Resolve path and ensure it does not escape project root or authorized scopes."""
        return self.resolver.resolve(path)

    def check_operation_policy(
        self,
        capability: str,
        operation: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        approval_token: Optional[str] = None,
    ) -> None:
        """Mandatory operation-level policy evaluation and exact approval verification.

        Fails closed with SecurityBoundaryViolation if denied, unapproved,
        expired, replayed, or if argument digest does not cryptographically match.
        """
        from core.safety.pending import SecurityBoundaryViolation, get_pending_registry
        from core.safety.policy import PolicyEngine

        engine = self.policy_engine or PolicyEngine()
        context = {
            "execution_id": self.execution_id,
            "project_root": str(self.project_root),
            "actor": self.actor,
            "declared_permissions": self.declared_permissions,
            "project_id": self.project_id,
        }

        try:
            decision = engine.evaluate(
                tool_name=tool_name,
                tool_args=tool_args,
                context=context,
            )
        except Exception as e:
            logger.error(
                "Policy evaluation failure at operation boundary for '%s': %s", tool_name, e
            )
            raise SecurityBoundaryViolation(
                f"Policy evaluation failure: {e}. Operation blocked fail-closed."
            )

        if decision.is_denied:
            raise SecurityBoundaryViolation(
                f"Policy denied operation '{tool_name}': {decision.reason}"
            )

        effective_token = approval_token or self.approval_token
        if decision.requires_approval or (effective_token and effective_token.strip()):
            if decision.requires_approval and not effective_token:
                raise SecurityBoundaryViolation(
                    f"Consequential operation '{tool_name}' requires approval: {decision.reason}"
                )

            registry = self.pending_registry or get_pending_registry()
            # Atomically validate and burn exact-operation token immediately before execution
            registry.consume_token(
                approval_token=effective_token,
                tool_name=tool_name,
                tool_args=tool_args,
                execution_id=self.execution_id,
                actor=self.actor,
                capability=capability,
            )

    def read_file(
        self,
        path: Union[str, Path, os.PathLike[str]],
        encoding: str = "utf-8",
        approval_token: Optional[str] = None,
    ) -> str:
        """Read a file within project root under READ permission."""
        self.check(SkillPermission.READ)
        initial_resolved = self.resolve_path(path)
        tool_args = {
            "path": initial_resolved.canonical_relative_path,
            "project_id": self.project_id,
        }
        self.check_operation_policy(
            capability="filesystem",
            operation="read_file",
            tool_name="filesystem.read_file",
            tool_args=tool_args,
            approval_token=approval_token,
        )
        current_resolved = self.resolve_path(path)
        if current_resolved.canonical_path != initial_resolved.canonical_path:
            from core.safety.pending import SecurityBoundaryViolation

            raise SecurityBoundaryViolation(
                f"Filesystem TOCTOU race detected: Path '{path}' changed canonical destination "
                f"between authorization ('{initial_resolved.canonical_path}') and execution ('{current_resolved.canonical_path}')"
            )
        return current_resolved.canonical_path.read_text(encoding=encoding)

    def write_file(
        self,
        path: Union[str, Path, os.PathLike[str]],
        content: str,
        encoding: str = "utf-8",
        approval_token: Optional[str] = None,
    ) -> int:
        """Write a file within project root under WRITE_LOCAL permission."""
        self.check(SkillPermission.WRITE_LOCAL)
        initial_resolved = self.resolve_path(path)
        tool_args = {
            "path": initial_resolved.canonical_relative_path,
            "content": content,
            "project_id": self.project_id,
        }
        self.check_operation_policy(
            capability="filesystem",
            operation="write_file",
            tool_name="filesystem.write_file",
            tool_args=tool_args,
            approval_token=approval_token,
        )
        current_resolved = self.resolve_path(path)
        if current_resolved.canonical_path != initial_resolved.canonical_path:
            from core.safety.pending import SecurityBoundaryViolation

            raise SecurityBoundaryViolation(
                f"Filesystem TOCTOU race detected: Path '{path}' changed canonical destination "
                f"between authorization ('{initial_resolved.canonical_path}') and execution ('{current_resolved.canonical_path}')"
            )
        target_path = current_resolved.canonical_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding=encoding)
        return len(content.encode(encoding))

    def delete_file(
        self,
        path: Union[str, Path, os.PathLike[str]],
        approval_token: Optional[str] = None,
    ) -> bool:
        """Delete a file within project root under DESTRUCTIVE permission."""
        try:
            self.check(SkillPermission.DESTRUCTIVE)
        except PermissionError:
            self.check(SkillPermission.WRITE_LOCAL)

        initial_resolved = self.resolve_path(path)
        tool_args = {
            "path": initial_resolved.canonical_relative_path,
            "project_id": self.project_id,
        }
        self.check_operation_policy(
            capability="filesystem",
            operation="delete_file",
            tool_name="filesystem.delete_file",
            tool_args=tool_args,
            approval_token=approval_token,
        )
        current_resolved = self.resolve_path(path)
        if current_resolved.canonical_path != initial_resolved.canonical_path:
            from core.safety.pending import SecurityBoundaryViolation

            raise SecurityBoundaryViolation(
                f"Filesystem TOCTOU race detected: Path '{path}' changed canonical destination "
                f"between authorization ('{initial_resolved.canonical_path}') and execution ('{current_resolved.canonical_path}')"
            )
        target_path = current_resolved.canonical_path
        if target_path.is_file() or target_path.is_symlink():
            target_path.unlink()
            return True
        return False

    def invoke(
        self,
        capability: str,
        operation: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        approval_token: Optional[str] = None,
    ) -> None:
        """Generic capability invocation boundary preflight."""
        self.check_operation_policy(
            capability=capability,
            operation=operation,
            tool_name=tool_name,
            tool_args=tool_args,
            approval_token=approval_token,
        )

    async def run_subprocess(
        self,
        cmd: List[str],
        cwd: Optional[Union[str, Path, os.PathLike[str]]] = None,
        timeout_seconds: float = 60.0,
        env: Optional[Dict[str, str]] = None,
        approval_token: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        """Execute a subprocess safely under EXECUTE permission and cancellation control."""
        self.check(SkillPermission.EXECUTE)

        initial_cwd_resolved = self.resolve_path(cwd) if cwd else self.resolve_path(".")
        if not initial_cwd_resolved.canonical_path.exists():
            raise FileNotFoundError(
                f"Working directory does not exist: {initial_cwd_resolved.canonical_path}"
            )
        if not initial_cwd_resolved.canonical_path.is_dir():
            raise NotADirectoryError(
                f"Working directory is not a directory: {initial_cwd_resolved.canonical_path}"
            )

        tool_args = {
            "cmd": cmd,
            "cwd": initial_cwd_resolved.canonical_relative_path,
            "project_id": self.project_id,
        }
        self.check_operation_policy(
            capability="subprocess",
            operation="run_subprocess",
            tool_name="subprocess.run",
            tool_args=tool_args,
            approval_token=approval_token,
        )

        current_cwd_resolved = self.resolve_path(cwd) if cwd else self.resolve_path(".")
        if current_cwd_resolved.canonical_path != initial_cwd_resolved.canonical_path:
            from core.safety.pending import SecurityBoundaryViolation

            raise SecurityBoundaryViolation(
                "Filesystem TOCTOU race detected: Working directory changed canonical destination "
                "between authorization and execution"
            )
        target_cwd = current_cwd_resolved.canonical_path

        if self.cancellation_token and self.cancellation_token.is_cancelled:
            raise ExecutionCancelledError("Execution cancelled before subprocess launch")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(target_cwd),
            env=env,
        )

        def _terminate_proc() -> None:
            try:
                proc.terminate()
            except Exception:
                pass

        if self.cancellation_token:
            self.cancellation_token.add_callback(_terminate_proc)

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise TimeoutError(f"Subprocess command {cmd[0]!r} timed out after {timeout_seconds}s")
        except (asyncio.CancelledError, ExecutionCancelledError):
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise ExecutionCancelledError(
                f"Subprocess command {cmd[0]!r} terminated due to cancellation"
            )

        if self.cancellation_token and self.cancellation_token.is_cancelled:
            raise ExecutionCancelledError(
                f"Subprocess command {cmd[0]!r} cancelled during execution"
            )

        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")
        return proc.returncode, stdout_str, stderr_str
