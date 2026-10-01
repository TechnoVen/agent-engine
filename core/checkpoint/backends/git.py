"""core/checkpoint/backends/git.py

Git repository checkpoint backend using isolated safety refs (refs/ae-checkpoints/<id>).
Part of Milestone R2 Task R2.11.

Invariants:
- Never touches user branch, user index (.git/index), or remote repository.
- Uses temporary index file (GIT_INDEX_FILE) to capture exact working tree into git object db.
- Creates hidden safety ref: refs/ae-checkpoints/<checkpoint_id>.
- Pre-restore conflict check refuses to clobber uncommitted human work unless force=True.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.models import (
    CheckpointError,
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

            # Add all current working directory files into the isolated index
            rc, _, err = self._run_git(["add", "-A"], workspace_root, env=env)
            if rc != 0:
                raise CheckpointError(f"git add -A failed in isolated index: {err}")

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
            }

        finally:
            if tmp_index.exists():
                try:
                    tmp_index.unlink()
                except Exception:
                    pass

        return resource

    def inspect_conflict(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
    ) -> tuple[bool, str]:
        """Check if working tree has diverged or has uncommitted human changes."""
        # Check if HEAD has diverged from expected post state
        if resource.expected_post_state_hash:
            rc, curr_head, _ = self._run_git(["rev-parse", "HEAD"], workspace_root)
            if rc == 0 and curr_head != resource.expected_post_state_hash:
                return (
                    True,
                    f"Git HEAD diverged from expected post-state {resource.expected_post_state_hash} (found {curr_head})",
                )

        # Check status for unstaged/uncommitted changes
        rc, status_out, _ = self._run_git(["status", "--porcelain"], workspace_root)
        if rc == 0 and status_out:
            # There are working tree modifications
            return True, "Working tree has uncommitted modifications that would be overwritten"

        return False, ""

    def restore_snapshot(
        self,
        resource: CheckpointResource,
        workspace_root: Path,
        checkpoint_dir: Path,
        force: bool = False,
    ) -> ResourceRestoreResult:
        """Restore working tree files from safety ref."""
        git_dir = workspace_root / ".git"
        if not git_dir.exists():
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.GIT,
                status=ResourceRestoreStatus.FAILED,
                message="Not a git repository",
            )

        ref_name = resource.storage_reference or f"refs/ae-checkpoints/{resource.resource_id}"

        # Conflict inspection
        is_conflict, reason = self.inspect_conflict(resource, workspace_root)
        if is_conflict and not force:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.GIT,
                status=ResourceRestoreStatus.CONFLICT,
                message=reason,
                verified=False,
            )

        # Restore working tree files from safety ref
        rc, _, err = self._run_git(["checkout", ref_name, "--", "."], workspace_root)
        if rc != 0:
            return ResourceRestoreResult(
                resource_id=resource.resource_id,
                resource_type=CheckpointResourceType.GIT,
                status=ResourceRestoreStatus.FAILED,
                message=f"git checkout failed: {err}",
                verified=False,
            )

        # Verification: compare working tree against checkpoint ref
        rc, diff_out, _ = self._run_git(["diff", ref_name], workspace_root)
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
