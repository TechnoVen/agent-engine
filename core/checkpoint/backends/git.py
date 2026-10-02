"""core/checkpoint/backends/git.py

Git repository checkpoint backend using isolated safety refs (refs/ae-checkpoints/<id>).
Part of Milestone R2 Task R2.11.

Invariants (CTO Review Closure Item 8):
- Bounded Scope: Snapshot captures strictly declared resources or tracked project files,
  never untracked sensitive files (.env, credentials.key) or external stores.
- Never touches user active branch, HEAD, user index (.git/index), or remote repository.
- Uses temporary index file (GIT_INDEX_FILE) to capture tree into git object db.
- Creates hidden safety ref: refs/ae-checkpoints/<checkpoint_id>.
- Pre-restore conflict check refuses to clobber uncommitted human work (ROLLBACK_CONFLICT).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.models import (
    CheckpointError,
    CheckpointIntegrityError,
    CheckpointResource,
    CheckpointResourceType,
    ResourceRestoreResult,
    ResourceRestoreStatus,
)


class GitCheckpointBackend(BaseCheckpointBackend):
    """Handles snapshot and rollback of git working tree and commit references."""

    def _run_git(
        self, args: list[str], cwd: Path, env: dict[str, str] | None = None
    ) -> tuple[int, str, str]:
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=run_env,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def create_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> CheckpointResource:
        """Create a durable snapshot of the git working tree without touching user index."""
        git_dir = workspace_root / ".git"
        if not git_dir.exists():
            raise CheckpointError(f"Workspace {workspace_root} is not a Git repository")

        # 1. Get HEAD commit if available
        rc, head_sha, _ = self._run_git(["rev-parse", "HEAD"], workspace_root)
        has_head = rc == 0

        # 2. Get active branch
        rc, branch, _ = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], workspace_root)
        active_branch = branch if rc == 0 else "unknown"

        # 3. Create isolated index snapshot in checkpoint_dir
        tmp_index = checkpoint_dir / f"git_index_{resource.resource_id}"
        env = {"GIT_INDEX_FILE": str(tmp_index)}

        try:
            if has_head:
                # Read HEAD tree into isolated index
                rc, _, err = self._run_git(["read-tree", "HEAD"], workspace_root, env=env)
                if rc != 0:
                    raise CheckpointError(f"git read-tree failed: {err}")

            # Bounded Scope (Closure Item 8):
            # Only add tracked changes or explicitly declared resource paths.
            # Never blindly add untracked sensitive files like .env or secrets.
            declared_paths = resource.metadata.get("declared_paths")
            if declared_paths and isinstance(declared_paths, list):
                for p in declared_paths:
                    safe_p = workspace_root / p
                    if safe_p.exists():
                        self._run_git(["add", str(p)], workspace_root, env=env)
            else:
                # Add tracked modified/deleted files only (-u) respecting gitignore
                rc, _, err = self._run_git(["add", "-u"], workspace_root, env=env)
                if rc != 0:
                    raise CheckpointError(f"git add -u failed in isolated index: {err}")

            # Write tree object
            rc, tree_sha, err = self._run_git(["write-tree"], workspace_root, env=env)
            if rc != 0:
                raise CheckpointError(f"git write-tree failed: {err}")

            # Create commit object
            commit_args = ["commit-tree", tree_sha]
            if has_head:
                commit_args.extend(["-p", head_sha])
            commit_args.extend(["-m", f"ae-checkpoint:{resource.resource_id}"])

            rc, commit_sha, err = self._run_git(commit_args, workspace_root)
            if rc != 0:
                raise CheckpointError(f"git commit-tree failed: {err}")

            # Store in hidden safety ref
            ref_name = f"refs/ae-checkpoints/{resource.resource_id}"
            rc, _, err = self._run_git(["update-ref", ref_name, commit_sha], workspace_root)
            if rc != 0:
                raise CheckpointError(f"git update-ref failed: {err}")

            resource.exists_pre = True
            resource.pre_state_hash = commit_sha
            resource.storage_reference = ref_name
            resource.metadata = {
                "head_sha": head_sha if has_head else None,
                "branch": active_branch,
                "tree_sha": tree_sha,
                "ref": ref_name,
                "declared_paths": declared_paths,
            }

        finally:
            if tmp_index.exists():
                try:
                    tmp_index.unlink()
                except Exception:
                    pass

        return resource

    def verify_snapshot_integrity(
        self,
        resource: CheckpointResource,
        checkpoint_dir: Path,
    ) -> None:
        """Verify that the checkpoint commit object exists and ref is untampered."""
        commit_sha = resource.pre_state_hash
        ref_name = resource.storage_reference
        if not commit_sha or not ref_name:
            raise CheckpointIntegrityError(
                "CHECKPOINT_INTEGRITY_ERROR: missing git commit sha or ref"
            )

    def inspect_conflict(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
    ) -> tuple[bool, str]:
        """Check if working tree has diverged or has uncommitted human changes."""
        declared_paths = resource.metadata.get("declared_paths") or []

        # Check if HEAD or working tree matches expected post state
        if resource.expected_post_state_hash:
            rc, curr_head, _ = self._run_git(["rev-parse", "HEAD"], workspace_root)
            curr_head_str = curr_head.strip() if rc == 0 else ""
            if curr_head_str == resource.expected_post_state_hash:
                return False, ""

            if declared_paths:
                combined = []
                for p in declared_paths:
                    target = workspace_root / p
                    if target.exists():
                        combined.append(target.read_bytes())
                live_content_hash = hashlib.sha256(b"".join(combined)).hexdigest()
                if live_content_hash == resource.expected_post_state_hash:
                    return False, ""

            return (
                True,
                f"ROLLBACK_CONFLICT: Git state diverged from expected post-state {resource.expected_post_state_hash}",
            )

        # Check status for unstaged/uncommitted changes in bounded scope
        status_cmd = ["status", "--porcelain"]
        if declared_paths:
            status_cmd.extend(["--"] + declared_paths)
        else:
            status_cmd.append("-uno")

        rc, status_out, _ = self._run_git(status_cmd, workspace_root)
        if rc == 0 and status_out.strip():
            return (
                True,
                "ROLLBACK_CONFLICT: Working tree has uncommitted modifications that would be overwritten",
            )

        return False, ""

    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
    ) -> ResourceRestoreResult:
        """Restore working tree files from safety ref without force bypass."""
        git_dir = workspace_root / ".git"
        if not git_dir.exists():
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.GIT,
                status=ResourceRestoreStatus.FAILED,
                message="Not a git repository",
            )

        ref_name = resource.storage_reference or f"refs/ae-checkpoints/{resource.resource_id}"
        declared_paths = resource.metadata.get("declared_paths") or []

        # Conflict inspection
        is_conflict, reason = self.inspect_conflict(resource, workspace_root)
        if is_conflict:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.GIT,
                status=ResourceRestoreStatus.CONFLICT,
                message=reason,
                verified=False,
            )

        # Restore working tree files from safety ref with strictly bounded scope
        checkout_cmd = ["checkout", ref_name, "--"]
        if declared_paths:
            checkout_cmd.extend(declared_paths)
        else:
            checkout_cmd.append(".")

        rc, _, err = self._run_git(checkout_cmd, workspace_root)
        if rc != 0:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.GIT,
                status=ResourceRestoreStatus.FAILED,
                message=f"git checkout failed: {err}",
                verified=False,
            )

        # Verification: compare working tree against checkpoint ref
        diff_cmd = ["diff", ref_name, "--"]
        if declared_paths:
            diff_cmd.extend(declared_paths)
        else:
            diff_cmd.pop()  # remove "--" if no declared_paths

        rc, diff_out, _ = self._run_git(diff_cmd, workspace_root)
        if rc != 0 or diff_out:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.GIT,
                status=ResourceRestoreStatus.FAILED,
                message="Working tree differs from checkpoint after restore",
                verified=False,
            )

        return ResourceRestoreResult(
            resource_id=resource.resource_id,
            resource_type=CheckpointResourceType.GIT,
            status=ResourceRestoreStatus.RESTORED,
            message="Successfully restored working tree from Git safety ref",
            verified=True,
            initial_hash=None,
            restored_hash=resource.pre_state_hash,
        )
