"""core/skills/path.py

Canonical Workspace Path Enforcement & Containment for Agent Engine.
Part of Milestone R2 Task R2.5 (Canonical workspace path enforcement).

Design Invariants:
1. One canonical ResolvedWorkspacePath value object.
2. Pre-authorization realpath resolution (symlink destination, parent directory chain).
3. Trusted workspace scope hierarchy:
   project_root -> authorized scope -> requested target.
4. Immediate pre-side-effect revalidation (defense against filesystem TOCTOU races).
5. Cross-platform path semantics (POSIX, Windows drive roots, case normalization).
6. Null-byte rejection fail-closed.
7. Public trace / ledger exposure uses project-relative paths, not host paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import ntpath
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Union

logger = logging.getLogger("agent_engine.skills.path")


class WorkspacePathViolation(PermissionError):
    """Raised when a path escapes the project root or authorized workspace scopes."""

    pass


@dataclass(frozen=True)
class ResolvedWorkspacePath(os.PathLike[str]):
    """Canonical value object for an authorized workspace path."""

    requested_path: str
    canonical_path: Path
    canonical_relative_path: str
    project_root: Path
    matched_scope: Path
    exists: bool

    def __fspath__(self) -> str:
        return str(self.canonical_path)

    def __str__(self) -> str:
        return str(self.canonical_path)

    def to_public_dict(self) -> Dict[str, Any]:
        """Return trace representation with machine absolute host paths omitted."""
        scope_repr = self.matched_scope.name if self.matched_scope != self.project_root else "/"
        return {
            "requested_path": self.requested_path,
            "relative_path": self.canonical_relative_path,
            "scope": scope_repr,
            "exists": self.exists,
        }


def _is_relative_to(path: Path, base: Path) -> bool:
    """Cross-platform check whether `path` is contained within or equals `base`."""
    try:
        norm_path = Path(os.path.normcase(str(path.resolve())))
        norm_base = Path(os.path.normcase(str(base.resolve())))
        norm_path.relative_to(norm_base)
        return True
    except (ValueError, RuntimeError):
        return False


def compute_effective_workspace_scopes(
    project_root: Union[str, Path, os.PathLike[str]],
    capability_scopes: Optional[Iterable[Union[str, Path, os.PathLike[str]]]] = None,
    policy_scopes: Optional[Iterable[Union[str, Path, os.PathLike[str]]]] = None,
    requested_workspace_scope: Optional[
        Union[str, Path, os.PathLike[str], Iterable[Union[str, Path, os.PathLike[str]]]]
    ] = None,
    # Backward compatibility:
    declared_scopes: Optional[Iterable[Union[str, Path, os.PathLike[str]]]] = None,
    requested_scopes: Optional[Iterable[Union[str, Path, os.PathLike[str]]]] = None,
) -> List[Path]:
    """Compute effective workspace scopes via safe intersection.

    Canonical rule:
    effective = project_root ∩ union(capability_scopes) ∩ union(policy_scopes) ∩ optional_caller_narrower_scope

    Caller input may only narrow within authorized scopes. It can never create or widen authority.
    Empty effective authority fails closed.
    """
    raw_root = os.fspath(project_root)
    if "\0" in raw_root:
        raise WorkspacePathViolation("Null byte detected in project root path")
    root_resolved = Path(os.path.realpath(os.path.abspath(raw_root)))

    # Handle backward-compatible aliases
    eff_cap_scopes = capability_scopes if capability_scopes is not None else declared_scopes
    eff_req_scope = (
        requested_workspace_scope if requested_workspace_scope is not None else requested_scopes
    )

    # 1. Base authorized scopes: capability-declared scopes (union) or full project root
    base_scopes: List[Path] = []
    if eff_cap_scopes:
        for s in eff_cap_scopes:
            raw_s = os.fspath(s)
            if "\0" in raw_s:
                raise WorkspacePathViolation("Null byte detected in capability scope path")
            p = Path(raw_s)
            cand = root_resolved / p if not p.is_absolute() else p
            cand_real = Path(os.path.realpath(os.path.abspath(str(cand))))
            if _is_relative_to(cand_real, root_resolved):
                base_scopes.append(cand_real)
            else:
                raise WorkspacePathViolation(
                    f"Declared capability scope '{s}' escapes project root '{root_resolved}'"
                )
    if not base_scopes:
        base_scopes = [root_resolved]

    # 2. Intersect with policy-authorized scopes if provided
    if policy_scopes is not None:
        pol_resolved_scopes: List[Path] = []
        for pol_s in policy_scopes:
            raw_pol = os.fspath(pol_s)
            if "\0" in raw_pol:
                raise WorkspacePathViolation("Null byte detected in policy scope path")
            p = Path(raw_pol)
            cand = root_resolved / p if not p.is_absolute() else p
            cand_real = Path(os.path.realpath(os.path.abspath(str(cand))))
            if not _is_relative_to(cand_real, root_resolved):
                raise WorkspacePathViolation(
                    f"Policy scope '{pol_s}' escapes project root '{root_resolved}'"
                )
            pol_resolved_scopes.append(cand_real)

        if not pol_resolved_scopes:
            # Policy explicitly provided empty list -> empty authority fails closed
            raise WorkspacePathViolation("Policy scopes list is empty; failing closed")

        # Intersection: union(capability_scopes) ∩ union(policy_scopes)
        intersected: List[Path] = []
        for pol in pol_resolved_scopes:
            for base in base_scopes:
                if _is_relative_to(pol, base):
                    intersected.append(pol)
                elif _is_relative_to(base, pol):
                    intersected.append(base)

        if not intersected:
            raise WorkspacePathViolation(
                "No intersecting authority between capability scopes and policy scopes; failing closed"
            )
        base_scopes = intersected

    # 3. Caller requested scopes (can only NARROW, never WIDEN; invalid scope fails closed)
    if eff_req_scope is not None:
        if isinstance(eff_req_scope, (str, Path, os.PathLike)):
            req_list = [eff_req_scope]
        else:
            req_list = list(eff_req_scope)

        if not req_list:
            raise WorkspacePathViolation("Requested workspace scope is empty; failing closed")

        narrowed: List[Path] = []
        for req_s in req_list:
            raw_req = os.fspath(req_s)
            if "\0" in raw_req:
                raise WorkspacePathViolation("Null byte detected in requested scope path")
            p = Path(raw_req)
            cand = root_resolved / p if not p.is_absolute() else p
            cand_real = Path(os.path.realpath(os.path.abspath(str(cand))))
            if not _is_relative_to(cand_real, root_resolved):
                raise WorkspacePathViolation(
                    f"Requested scope '{req_s}' resolves outside project root '{root_resolved}'"
                )

            # Check if cand_real narrows any authorized base_scope or matches anti-widening
            matched = False
            for base in base_scopes:
                if _is_relative_to(cand_real, base):
                    # Caller requested narrower scope or equal
                    narrowed.append(cand_real)
                    matched = True
                elif _is_relative_to(base, cand_real):
                    # Caller requested a wider scope than base (e.g. caller requested '.' when base is 'src')
                    # Anti-widening: ignore caller widening attempt, enforce authorized base scope
                    narrowed.append(base)
                    matched = True

            if not matched:
                raise WorkspacePathViolation(
                    f"Requested scope '{req_s}' is outside authorized workspace authority"
                )

        if not narrowed:
            raise WorkspacePathViolation(
                "Effective workspace scope authority is empty after applying requested scope; failing closed"
            )
        base_scopes = narrowed

    # Deduplicate while preserving order
    seen: Set[Path] = set()
    result: List[Path] = []
    for s in base_scopes:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


class WorkspacePathResolver:
    """Authoritative path canonicalizer and containment validator for workspace capabilities."""

    def __init__(
        self,
        project_root: Union[str, Path, os.PathLike[str]],
        authorized_scopes: Optional[Iterable[Union[str, Path, os.PathLike[str]]]] = None,
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
        if self.project_root.exists() and not self.project_root.is_dir():
            raise NotADirectoryError(f"Project root is not a directory: {self.project_root}")

        # Validate and canonicalize authorized workspace scopes
        self.authorized_scopes: List[Path] = []
        if authorized_scopes is not None:
            for s in authorized_scopes:
                raw_s = os.fspath(s)
                if "\0" in raw_s:
                    raise WorkspacePathViolation("Null byte detected in authorized scope path")
                cand = Path(raw_s)
                if not cand.is_absolute():
                    cand = self.project_root / cand
                cand_real = Path(os.path.realpath(os.path.abspath(str(cand))))

                # Scopes themselves must reside strictly inside project_root
                if not _is_relative_to(cand_real, self.project_root):
                    raise WorkspacePathViolation(
                        f"Scope validation failure: Authorized scope '{s}' resolves to '{cand_real}', "
                        f"which escapes project root '{self.project_root}'"
                    )
                self.authorized_scopes.append(cand_real)

            if not self.authorized_scopes:
                raise WorkspacePathViolation(
                    "Authorized workspace scopes collection is empty; failing closed"
                )
        else:
            self.authorized_scopes = [self.project_root]

    def resolve(
        self,
        target_path: Union[str, Path, os.PathLike[str]],
    ) -> ResolvedWorkspacePath:
        """Resolve, canonicalize, and validate containment for a requested target path."""
        raw_path = os.fspath(target_path)
        if "\0" in raw_path:
            raise WorkspacePathViolation(
                "Null byte detected in path; operation rejected fail-closed"
            )

        if not raw_path.strip():
            raise WorkspacePathViolation("Empty path provided")

        # Windows drive-relative escape check (e.g. 'C:file' instead of 'C:\\file' or 'C:/file')
        nt_drive, nt_tail = ntpath.splitdrive(raw_path)
        if nt_drive and nt_tail and not nt_tail.startswith(("\\", "/")):
            raise WorkspacePathViolation(
                f"Drive-relative path '{raw_path}' rejected (ambiguous working directory escape)"
            )

        # Cross-platform check for absolute path with foreign drive on non-Windows
        if os.name != "nt" and nt_drive and ntpath.isabs(raw_path):
            raise WorkspacePathViolation(
                f"Windows absolute drive path '{raw_path}' escapes POSIX project root '{self.project_root}'"
            )

        norm_input = raw_path.replace("\\", "/") if os.name != "nt" else raw_path
        target = Path(norm_input)
        if not target.is_absolute():
            candidate = self.project_root / target
        else:
            candidate = target

        # Handle existing path or symlink
        if candidate.exists() or os.path.islink(candidate):
            canonical_path = Path(os.path.realpath(candidate))
            exists = canonical_path.exists()

            # Containment check in project root
            if not _is_relative_to(canonical_path, self.project_root):
                raise WorkspacePathViolation(
                    f"Project isolation violation: Path '{raw_path}' resolves to '{canonical_path}', "
                    f"which escapes project root '{self.project_root}'"
                )

            # Containment check in authorized workspace scopes
            matched_scope: Optional[Path] = None
            for scope in self.authorized_scopes:
                if _is_relative_to(canonical_path, scope):
                    matched_scope = scope
                    break

            if matched_scope is None:
                raise WorkspacePathViolation(
                    f"Scope violation: Path '{raw_path}' resolves to '{canonical_path}', "
                    f"which is outside authorized workspace scopes"
                )

            try:
                rel_path = canonical_path.relative_to(self.project_root).as_posix()
            except ValueError:
                rel_path = "."

            return ResolvedWorkspacePath(
                requested_path=raw_path,
                canonical_path=canonical_path,
                canonical_relative_path=rel_path,
                project_root=self.project_root,
                matched_scope=matched_scope,
                exists=exists,
            )

        # Handle non-existent target: parent-chain validation
        curr = candidate
        unresolved_components: List[str] = []
        while not curr.exists() and not os.path.islink(curr):
            unresolved_components.append(curr.name)
            parent = curr.parent
            if parent == curr:  # reached filesystem root
                break
            curr = parent
        unresolved_components.reverse()

        # Check existing ancestor
        ancestor_canonical = Path(os.path.realpath(curr))
        if not _is_relative_to(ancestor_canonical, self.project_root):
            raise WorkspacePathViolation(
                f"Parent chain isolation violation: Parent of '{raw_path}' resolves to '{ancestor_canonical}', "
                f"which escapes project root '{self.project_root}'"
            )

        matched_scope = None
        for scope in self.authorized_scopes:
            if _is_relative_to(ancestor_canonical, scope):
                matched_scope = scope
                break

        if matched_scope is None:
            raise WorkspacePathViolation(
                f"Scope violation: Parent of '{raw_path}' resolves to '{ancestor_canonical}', "
                f"which is outside authorized workspace scopes"
            )

        # Verify no lexical directory traversal escapes in the remaining non-existent chain
        for part in unresolved_components:
            if part in ("..", ".", ""):
                raise WorkspacePathViolation(
                    f"Directory traversal component '{part}' in non-existent path '{raw_path}'"
                )

        target_canonical = ancestor_canonical.joinpath(*unresolved_components)

        if not _is_relative_to(target_canonical, self.project_root):
            raise WorkspacePathViolation(
                f"Project isolation violation: Target path '{raw_path}' resolves outside project root"
            )

        if not _is_relative_to(target_canonical, matched_scope):
            raise WorkspacePathViolation(
                f"Scope violation: Target path '{raw_path}' resolves outside authorized scope '{matched_scope}'"
            )

        try:
            rel_path = target_canonical.relative_to(self.project_root).as_posix()
        except ValueError:
            rel_path = "."

        return ResolvedWorkspacePath(
            requested_path=raw_path,
            canonical_path=target_canonical,
            canonical_relative_path=rel_path,
            project_root=self.project_root,
            matched_scope=matched_scope,
            exists=False,
        )
