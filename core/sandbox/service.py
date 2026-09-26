"""core/sandbox/service.py

Unified Sandbox Service for isolated execution of worker processes.
Part of Milestone R2 Task R2.8 (Sandbox worker runtime).

Design Invariants:
1. Fail-closed: If secure sandbox backend is unavailable, execution fails with SandboxUnavailableError.
   Host fallback is strictly prohibited.
2. Canonical Path Containment (R2.5): Workspaces and mounts are validated using WorkspacePathResolver;
   symlinks escaping workspace are blocked.
3. Secrets Injection (R2.6): Authorized SecretReferences are resolved narrow-scoped for consumer
   'sandbox_worker', injected strictly to child process environment, and wiped immediately.
4. Untrusted Output Classification (R2.7): Worker stdout and stderr produce ContextItems with
   EXTERNAL_UNTRUSTED trust and NO_AUTHORITY.
5. Process Lifecycle & Cancellation (R1.9): Processes are monitored and terminated on cancellation.
6. Artifact Brokering (R1.10): Generated workspace artifacts are validated against path traversal,
   size, and symlink escapes before registration.
7. Ledger Evidence (R1.11): Records execution metadata without secret values or private absolute paths.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set

from core.artifacts.service import ArtifactService
from core.sandbox.backend import (
    DarwinSandboxBackend,
    LinuxBubblewrapBackend,
    NullSandboxBackend,
    SandboxBackend,
    WindowsSandboxBackend,
)
from core.sandbox.models import (
    SandboxExecutionRecord,
    SandboxFilesystemGrant,
    SandboxNetworkGrant,
    SandboxResult,
    SandboxSecurityError,
    SandboxSpec,
    SandboxUnavailableError,
    generate_sandbox_id,
)
from core.security.credentials import PROVIDER_ENV_MAP
from core.security.secrets import SecretsService
from core.skills.path import WorkspacePathResolver, WorkspacePathViolation
from core.storage.base import StorageBackend

logger = logging.getLogger("agent_engine.sandbox.service")


class SandboxService:
    """Canonical service orchestrating container-isolated worker processes."""

    def __init__(
        self,
        backend: Optional[SandboxBackend] = None,
        secrets_service: Optional[SecretsService] = None,
        artifact_service: Optional[ArtifactService] = None,
        storage: Optional[StorageBackend] = None,
        default_timeout_seconds: float = 30.0,
    ):
        self.secrets_service = secrets_service
        self.artifact_service = artifact_service
        self.storage = storage
        self.default_timeout_seconds = default_timeout_seconds

        if backend is not None:
            self.backend = backend
        else:
            self.backend = self._detect_platform_backend()

    def _detect_platform_backend(self) -> SandboxBackend:
        if sys.platform.startswith("linux"):
            backend = LinuxBubblewrapBackend()
            if backend.is_available():
                return backend
            logger.warning(
                "Linux Bubblewrap backend is not available on this host. Sandbox will fail closed."
            )
            return backend
        elif sys.platform == "darwin":
            return DarwinSandboxBackend()
        elif sys.platform == "win32":
            return WindowsSandboxBackend()
        else:
            return NullSandboxBackend()

    def is_available(self) -> bool:
        """Check if a secure sandbox backend is functional on this platform."""
        return self.backend.is_available()

    def execute(
        self,
        spec: SandboxSpec,
        project_id: Optional[str] = None,
        project_root: Optional[Path] = None,
    ) -> SandboxResult:
        """Execute a workload inside the isolated sandbox container.

        Enforces all security invariants fail-closed.
        """
        # 1. Fail-closed backend availability check
        if not self.backend.is_available():
            raise SandboxUnavailableError(
                f"Secure sandbox backend '{self.backend.name}' is unavailable on this platform. "
                "Execution rejected fail-closed to prevent unconstrained host execution (R2.8)."
            )

        start_time = time.time()
        execution_id = generate_sandbox_id()

        # 2. Filesystem boundary & Path Containment (R2.5)
        ws_path = spec.filesystem.workspace_dir
        if not ws_path.exists():
            raise SandboxSecurityError(f"Workspace directory does not exist: {ws_path}")
        if not ws_path.is_dir():
            raise SandboxSecurityError(f"Workspace path is not a directory: {ws_path}")

        # If project_root is provided, validate containment
        if project_root is not None:
            try:
                resolver = WorkspacePathResolver(
                    project_root,
                    authorized_scopes=[ws_path],
                )
                resolved = resolver.resolve(ws_path, mode="read_write")
                ws_path = resolved.path
            except WorkspacePathViolation as e:
                raise SandboxSecurityError(
                    f"Workspace path violates project containment boundaries: {e}"
                ) from e

        # Validate additional mounts
        for mount in spec.filesystem.mounts:
            if not mount.source.exists():
                raise SandboxSecurityError(f"Mount source does not exist: {mount.source}")
            # Ensure mount source does not traverse an unauthorized symlink
            if mount.source.is_symlink():
                resolved_src = mount.source.resolve()
                if project_root and not resolved_src.is_relative_to(project_root.resolve()):
                    raise SandboxSecurityError(
                        f"Mount source symlink points outside project root: {mount.source} -> {resolved_src}"
                    )

        # 3. Snapshot existing files in workspace for artifact brokering
        pre_existing_files: Set[str] = set()
        try:
            for root, _, files in os.walk(ws_path):
                for f in files:
                    p = Path(root) / f
                    try:
                        rel = str(p.relative_to(ws_path))
                        pre_existing_files.add(rel)
                    except ValueError:
                        pass
        except Exception as e:
            logger.debug(f"Failed to snapshot workspace files: {e}")

        # 4. Resolve authorized secrets (R2.6)
        resolved_secrets: Dict[str, str] = {}
        if spec.secret_grants:
            if self.secrets_service is None:
                raise SandboxSecurityError(
                    "SandboxSpec requested secret_grants, but SecretsService is not configured."
                )

            consumer_id = "sandbox_worker"
            for ref in spec.secret_grants:
                try:
                    sec_val = self.secrets_service.resolve_for_consumer(
                        consumer_id,
                        ref,
                        context={"project_id": project_id},
                    )
                    # Determine target env var name
                    env_name = PROVIDER_ENV_MAP.get(ref.provider.lower(), ref.name.upper())
                    raw_val = sec_val.reveal(consumer_id)
                    resolved_secrets[env_name] = raw_val
                    sec_val.wipe()
                except Exception as e:
                    raise SandboxSecurityError(
                        f"Failed to authorize and resolve secret '{ref.canonical_id}' for sandbox: {e}"
                    ) from e

        # 5. Execute via platform backend
        result: SandboxResult
        try:
            result = self.backend.execute(
                spec=spec,
                resolved_secrets=resolved_secrets,
                execution_id=execution_id,
            )
        finally:
            # Wipe local secret references from memory
            for k in list(resolved_secrets.keys()):
                resolved_secrets[k] = ""
            resolved_secrets.clear()

        # 6. Artifact Brokering (R1.10 / Section 15)
        candidate_artifacts: List[str] = []
        try:
            for root, _, files in os.walk(ws_path):
                for f in files:
                    p = Path(root) / f
                    # Skip internal sandbox scripts
                    if f.startswith("._sbx_script_"):
                        continue
                    try:
                        rel = str(p.relative_to(ws_path))
                        if rel not in pre_existing_files:
                            # Validate candidate artifact path containment
                            if p.is_symlink():
                                target = p.resolve()
                                if not target.is_relative_to(ws_path.resolve()):
                                    logger.warning(
                                        f"Rejecting generated artifact symlink escaping workspace: {rel}"
                                    )
                                    continue
                            # Ensure size sanity (reject > 20 MB artifacts)
                            if p.stat().st_size > 20 * 1024 * 1024:
                                logger.warning(
                                    f"Rejecting generated artifact exceeding 20MB limit: {rel}"
                                )
                                continue
                            candidate_artifacts.append(rel)
                    except (ValueError, OSError) as e:
                        logger.warning(f"Error inspecting candidate artifact {p}: {e}")
        except Exception as e:
            logger.warning(f"Error discovering generated artifacts: {e}")

        result.artifacts = candidate_artifacts

        # 7. Record security audit ledger (R1.11 / Section 19)
        end_time = time.time()
        # Redact private host paths from workspace_scope
        ws_scope_label = (
            ws_path.name
            if project_root and ws_path == project_root
            else f"workspace:{ws_path.name}"
        )
        audit_record = SandboxExecutionRecord(
            execution_id=execution_id,
            backend=self.backend.name,
            workspace_scope=ws_scope_label,
            network_allowed=spec.network.allowed,
            secret_reference_ids=[r.canonical_id for r in spec.secret_grants],
            status=result.status,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=result.duration_seconds,
            artifacts=candidate_artifacts,
            exit_code=result.exit_code,
            failure_category=result.status.value if not result.is_success else None,
        )

        if self.storage and hasattr(self.storage, "record_sandbox_execution"):
            try:
                self.storage.record_sandbox_execution(audit_record)
            except Exception as e:
                logger.debug(f"Failed to persist sandbox audit record: {e}")

        logger.debug(f"Sandbox audit record: {audit_record.to_dict()}")

        logger.info(
            f"Sandbox execution {execution_id} finished via {self.backend.name}: "
            f"status={result.status.value}, exit_code={result.exit_code}, "
            f"artifacts={len(candidate_artifacts)}"
        )

        return result

    def run_code(
        self,
        code: str,
        workspace_dir: Path,
        project_id: Optional[str] = None,
        project_root: Optional[Path] = None,
        network_allowed: bool = False,
        secret_grants: Optional[List[Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> SandboxResult:
        """Convenience method to execute a Python code snippet in isolated sandbox."""
        spec = SandboxSpec(
            command=[],
            script=code,
            filesystem=SandboxFilesystemGrant(
                workspace_dir=workspace_dir,
                allow_tmpfs=True,
            ),
            network=SandboxNetworkGrant(allowed=network_allowed),
            secret_grants=secret_grants or [],
            timeout_seconds=timeout_seconds or self.default_timeout_seconds,
        )
        return self.execute(spec=spec, project_id=project_id, project_root=project_root)
