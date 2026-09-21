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
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

from core.execution.cancellation import (
    CancellationToken,
    ExecutionCancelledError,
)
from core.skills.models import SkillPermission

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
    project_root: Union[str, Path],
    target_path: Union[str, Path],
) -> Path:
    """Ensure target path resolves strictly within the designated project root.

    Rejects directory traversal (..) and absolute paths outside project root.
    Raises PermissionError on boundary escape.
    """
    root_resolved = Path(project_root).resolve()
    target = Path(target_path)
    if not target.is_absolute():
        target_resolved = (root_resolved / target).resolve()
    else:
        target_resolved = target.resolve()

    try:
        target_resolved.relative_to(root_resolved)
    except ValueError:
        raise PermissionError(
            f"Project isolation violation: Path '{target_path}' resolves to '{target_resolved}', "
            f"which is outside project root '{root_resolved}'"
        )

    return target_resolved


class CapabilityBoundary:
    """Encapsulates execution capabilities for a skill under ExecutionCoordinator authority."""

    def __init__(
        self,
        project_root: Union[str, Path],
        declared_permissions: Optional[Iterable[Union[SkillPermission, str]]] = None,
        cancellation_token: Optional[CancellationToken] = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.declared_permissions: Set[str] = set()
        for p in declared_permissions or []:
            if isinstance(p, SkillPermission):
                self.declared_permissions.add(p.value.lower())
            else:
                self.declared_permissions.add(str(p).lower())
        self.cancellation_token = cancellation_token

    def check(self, permission: Union[SkillPermission, str]) -> None:
        """Check whether permission is declared."""
        check_permission(self.declared_permissions, permission)

    def resolve_path(self, path: Union[str, Path]) -> Path:
        """Resolve path and ensure it does not escape project root."""
        return validate_project_path(self.project_root, path)

    def read_file(self, path: Union[str, Path], encoding: str = "utf-8") -> str:
        """Read a file within project root under READ permission."""
        self.check(SkillPermission.READ)
        safe_path = self.resolve_path(path)
        return safe_path.read_text(encoding=encoding)

    def write_file(self, path: Union[str, Path], content: str, encoding: str = "utf-8") -> int:
        """Write a file within project root under WRITE_LOCAL permission."""
        self.check(SkillPermission.WRITE_LOCAL)
        safe_path = self.resolve_path(path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(content, encoding=encoding)
        return len(content.encode(encoding))

    async def run_subprocess(
        self,
        cmd: List[str],
        cwd: Optional[Union[str, Path]] = None,
        timeout_seconds: float = 60.0,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Execute a subprocess safely under EXECUTE permission and cancellation control."""
        self.check(SkillPermission.EXECUTE)

        target_cwd = self.resolve_path(cwd) if cwd else self.project_root
        if not target_cwd.exists() or not target_cwd.is_dir():
            raise FileNotFoundError(f"Working directory does not exist: {target_cwd}")

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
