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
import stat
import sys
import threading
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
    ResourceLimitExceededError,
    SandboxExecutionRecord,
    SandboxFilesystemGrant,
    SandboxMountMode,
    SandboxNetworkGrant,
    SandboxResourcePolicy,
    SandboxResult,
    SandboxSecurityError,
    SandboxSpec,
    SandboxTerminalReason,
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
        max_concurrent_sandboxes: int = 10,
        max_total_memory_bytes: Optional[int] = 1024 * 1024 * 1024,  # 1 GB ceiling
        max_resource_policy: Optional[SandboxResourcePolicy] = None,
    ):
        self.secrets_service = secrets_service
        self.artifact_service = artifact_service
        self.storage = storage
        self.default_timeout_seconds = default_timeout_seconds
        self.max_concurrent_sandboxes = max_concurrent_sandboxes
        self.max_total_memory_bytes = max_total_memory_bytes
        self.max_resource_policy = max_resource_policy or SandboxResourcePolicy(
            max_wall_time_seconds=300.0,
            max_stdout_bytes=50 * 1024 * 1024,
            max_stderr_bytes=50 * 1024 * 1024,
        )

        self._active_sandboxes: Dict[str, SandboxSpec] = {}
        self._lock = threading.Lock()

        if backend is not None:
            self.backend = backend
        else:
            self.backend = self._detect_platform_backend()

    @property
    def active_sandboxes_count(self) -> int:
        """Return the number of currently executing sandboxes."""
        with self._lock:
            return len(self._active_sandboxes)

    @property
    def active_execution_ids(self) -> List[str]:
        """Return list of active sandbox execution IDs."""
        with self._lock:
            return list(self._active_sandboxes.keys())

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

        # Enforce system resource ceiling (immutable limits)
        spec.resource_policy = spec.resource_policy.clamp_to_ceiling(self.max_resource_policy)
        spec.timeout_seconds = spec.resource_policy.max_wall_time_seconds

        # Concurrency & capacity accounting (R2.9)
        with self._lock:
            if len(self._active_sandboxes) >= self.max_concurrent_sandboxes:
                raise ResourceLimitExceededError(
                    reason=SandboxTerminalReason.PROCESS_LIMIT,
                    message=f"Maximum concurrent sandbox limit ({self.max_concurrent_sandboxes}) reached.",
                    violating_dimension="concurrent_sandboxes",
                    configured_limit=self.max_concurrent_sandboxes,
                    observed_value=len(self._active_sandboxes),
                )
            if self.max_total_memory_bytes and spec.resource_policy.max_memory_bytes:
                current_mem = sum(
                    s.resource_policy.max_memory_bytes or 0 for s in self._active_sandboxes.values()
                )
                if (
                    current_mem + spec.resource_policy.max_memory_bytes
                    > self.max_total_memory_bytes
                ):
                    raise ResourceLimitExceededError(
                        reason=SandboxTerminalReason.MEMORY_LIMIT,
                        message="Total concurrent sandbox memory allocation limit exceeded.",
                        violating_dimension="concurrent_memory_bytes",
                        configured_limit=self.max_total_memory_bytes,
                        observed_value=current_mem + spec.resource_policy.max_memory_bytes,
                    )
            self._active_sandboxes[execution_id] = spec

        try:
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
            scan_dirs = [ws_path]
            if spec.filesystem.output_dir and spec.filesystem.output_dir.exists():
                scan_dirs.append(spec.filesystem.output_dir)

            try:
                for base in scan_dirs:
                    for root, _, files in os.walk(base):
                        for f in files:
                            p = Path(root) / f
                            try:
                                rel = str(p.relative_to(base))
                                pre_existing_files.add(f"{base.name}:{rel}")
                            except ValueError:
                                pass
            except Exception as e:
                logger.debug(f"Failed to snapshot workspace files: {e}")

            # 4. Resolve authorized secrets (R2.6 / Item 2: Execution- and capability-bound)
            resolved_secrets: Dict[str, str] = {}
            injected_secret_values: List[str] = []

            if spec.secret_grants:
                if self.secrets_service is None:
                    raise SandboxSecurityError(
                        "SandboxSpec requested secret_grants, but SecretsService is not configured."
                    )

                # Bind consumer ID to exact execution & capability identity
                consumer_id = (
                    f"sandbox:{project_id or spec.project_id or 'default'}:"
                    f"{execution_id}:{spec.capability_id or 'exec'}"
                )
                for ref in spec.secret_grants:
                    try:
                        sec_val = self.secrets_service.resolve_for_consumer(
                            consumer_id,
                            ref,
                            context={"project_id": project_id},
                        )
                        env_name = PROVIDER_ENV_MAP.get(ref.provider.lower(), ref.name.upper())
                        raw_val = sec_val.reveal(consumer_id)
                        resolved_secrets[env_name] = raw_val
                        injected_secret_values.append(raw_val)
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

            # Item 4: Redaction of injected secrets from public execution evidence
            for secret_val in injected_secret_values:
                if secret_val:
                    result.stdout = result.stdout.replace(secret_val, "[REDACTED_SECRET]")
                    result.stderr = result.stderr.replace(secret_val, "[REDACTED_SECRET]")

            # 6. Artifact Brokering (R1.10 / Section 15 & Item 9: Regular-file validation)
            candidate_artifacts: List[str] = []
            try:
                for base in scan_dirs:
                    for root, _, files in os.walk(base):
                        for f in files:
                            p = Path(root) / f
                            # Skip internal sandbox scripts
                            if f.startswith("._sbx_script_"):
                                continue
                            try:
                                rel = str(p.relative_to(base))
                                key = f"{base.name}:{rel}"
                                if key in pre_existing_files:
                                    continue

                                # Validate path traversal / dotdot containment
                                if ".." in rel or rel.startswith("/"):
                                    logger.warning(f"Rejecting artifact path traversal: {rel}")
                                    continue

                                # Non-regular file rejection (FIFOs, Unix sockets, device nodes)
                                st_raw = p.stat(follow_symlinks=False)
                                if stat.S_ISFIFO(st_raw.st_mode) or stat.S_ISSOCK(st_raw.st_mode):
                                    logger.warning(f"Rejecting non-regular IPC artifact: {rel}")
                                    continue
                                if stat.S_ISCHR(st_raw.st_mode) or stat.S_ISBLK(st_raw.st_mode):
                                    logger.warning(f"Rejecting device node artifact: {rel}")
                                    continue

                                # Symlink validation
                                if p.is_symlink():
                                    target = p.resolve()
                                    if not target.is_relative_to(base.resolve()):
                                        logger.warning(
                                            f"Rejecting generated artifact symlink escaping workspace: {rel}"
                                        )
                                        continue
                                    if (
                                        not target.is_file()
                                        or target.is_fifo()
                                        or target.is_socket()
                                    ):
                                        logger.warning(
                                            f"Rejecting symlink pointing to non-regular target: {rel}"
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

            # 7. Record security audit ledger (R1.11 / Section 19 & Item 10)
            end_time = time.time()
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
                terminal_reason=result.terminal_reason.value,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=result.duration_seconds,
                artifacts=candidate_artifacts,
                exit_code=result.exit_code,
                failure_category=result.status.value if not result.is_success else None,
                resource_policy=spec.resource_policy.to_dict(),
                resource_usage=result.resource_usage,
            )

            if self.storage and hasattr(self.storage, "record_sandbox_execution"):
                try:
                    self.storage.record_sandbox_execution(audit_record)
                except Exception as e:
                    logger.debug(f"Failed to persist sandbox audit record: {e}")

            logger.debug(f"Sandbox audit record: {audit_record.to_dict()}")

            logger.info(
                f"Sandbox execution {execution_id} finished via {self.backend.name}: "
                f"status={result.status.value}, terminal_reason={result.terminal_reason.value}, "
                f"exit_code={result.exit_code}, artifacts={len(candidate_artifacts)}"
            )

            return result

        finally:
            with self._lock:
                self._active_sandboxes.pop(execution_id, None)

    def run_code(
        self,
        code: str,
        workspace_dir: Path,
        project_id: Optional[str] = None,
        project_root: Optional[Path] = None,
        network_allowed: bool = False,
        secret_grants: Optional[List[Any]] = None,
        timeout_seconds: Optional[float] = None,
        project_mount_mode: SandboxMountMode = SandboxMountMode.READ_ONLY,
        scratch_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        resource_policy: Optional[SandboxResourcePolicy] = None,
        capability_id: Optional[str] = None,
        cancellation_token: Optional[Any] = None,
    ) -> SandboxResult:
        """Convenience method to execute a Python code snippet in isolated sandbox."""
        policy = resource_policy or SandboxResourcePolicy()
        if timeout_seconds is not None:
            policy.max_wall_time_seconds = timeout_seconds

        spec = SandboxSpec(
            command=[],
            script=code,
            filesystem=SandboxFilesystemGrant(
                workspace_dir=workspace_dir,
                project_root=project_root,
                project_mount_mode=project_mount_mode,
                scratch_dir=scratch_dir,
                output_dir=output_dir,
                allow_tmpfs=True,
            ),
            network=SandboxNetworkGrant(allowed=network_allowed),
            secret_grants=secret_grants or [],
            resource_policy=policy,
            timeout_seconds=policy.max_wall_time_seconds,
            capability_id=capability_id,
            project_id=project_id,
            cancellation_token=cancellation_token,
        )
        return self.execute(spec=spec, project_id=project_id, project_root=project_root)
