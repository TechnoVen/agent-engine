"""core/sandbox/models.py

Data models and contracts for the Sandbox Worker Runtime and Resource Limits.
Part of Milestone R2 Tasks R2.8 (Sandbox worker runtime) and R2.9 (Sandbox resource limits).

Design Invariants:
1. Default-deny security posture: Network is disabled by default; environment is minimal.
2. Source workspace is READ_ONLY by default: Untrusted code cannot overwrite canonical project files.
   Changes must emerge through output staging or private scratch directories.
3. Execution- and capability-bound secrets: Secrets are resolved only for authorized parent specs
   and bound to exact (project_id, execution_id, capability_id) identity.
4. Redaction in public evidence: Injected secrets are scrubbed from stdout, stderr, ledger, and logs.
5. Accurate secret-wipe terminology: Parent-side SecretValue lifetime and references are minimized
   after spawn; the explicitly injected value remains available inside the authorized worker for the
   worker lifetime. Python runtime memory cannot guarantee physical byte zeroization.
6. Enforced OS resource limits (R2.9): Wall time, CPU time, memory, process count, and output
   backpressure are enforced by kernel primitives (cgroup v2 scopes and rlimits on Linux) fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from core.context.models import (
    ContextItem,
)
from core.execution.cancellation import CancellationToken
from core.security.secrets import SecretReference


class SandboxStatus(str, Enum):
    """Execution status of a sandbox worker process."""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


class SandboxMountMode(str, Enum):
    """Filesystem mount mode for sandbox boundary enforcement."""

    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    OUTPUT_ONLY = "output_only"
    SCRATCH = "scratch"


class SandboxTerminalReason(str, Enum):
    """Canonical terminal reason for sandbox worker termination."""

    NORMAL = "normal"
    USER_CANCELLED = "user_cancelled"
    WALL_TIME_LIMIT = "wall_time_limit"
    CPU_LIMIT = "cpu_limit"
    MEMORY_LIMIT = "memory_limit"
    PROCESS_LIMIT = "process_limit"
    OUTPUT_LIMIT = "output_limit"
    RESOURCE_ISOLATION_UNAVAILABLE = "resource_isolation_unavailable"
    SECURITY_VIOLATION = "security_violation"
    BACKEND_ERROR = "backend_error"
    CONCURRENCY_CAPACITY_EXCEEDED = "concurrency_capacity_exceeded"
    MEMORY_CAPACITY_EXCEEDED = "memory_capacity_exceeded"


class SandboxError(Exception):
    """Base exception for sandbox runtime errors."""

    pass


class SandboxUnavailableError(SandboxError):
    """Raised when no secure platform backend is available.

    Fail-closed: Execution will NOT fall back to host execution.
    """

    pass


class SandboxSecurityError(SandboxError):
    """Raised when a sandbox security invariant (mount escape, symlink, secret boundary) is violated."""

    pass


class SandboxTimeoutError(SandboxError):
    """Raised when worker execution exceeds configured timeout."""

    pass


class SandboxCancellationError(SandboxError):
    """Raised when worker execution is cancelled."""

    pass


class ResourceLimitExceededError(SandboxError):
    """Raised when an enforced resource limit (CPU, memory, processes, output) is breached."""

    def __init__(
        self,
        reason: SandboxTerminalReason,
        message: str,
        violating_dimension: Optional[str] = None,
        configured_limit: Any = None,
        observed_value: Any = None,
        status: Optional[SandboxStatus] = None,
    ):
        super().__init__(message)
        self.reason = reason
        self.violating_dimension = violating_dimension
        self.configured_limit = configured_limit
        self.observed_value = observed_value
        if status is not None:
            self.status = status
        elif reason in (
            SandboxTerminalReason.CONCURRENCY_CAPACITY_EXCEEDED,
            SandboxTerminalReason.MEMORY_CAPACITY_EXCEEDED,
        ):
            self.status = SandboxStatus.BLOCKED
        else:
            self.status = SandboxStatus.FAILED


class ResourceIsolationUnavailableError(SandboxError):
    """Raised when required OS resource isolation primitive is unavailable on the platform."""

    pass


@dataclass(frozen=True)
class SandboxMount:
    """Represents an explicit filesystem mount into the sandbox environment."""

    source: Path
    target: Path
    mode: SandboxMountMode = SandboxMountMode.READ_ONLY
    read_only: bool = True

    def __post_init__(self) -> None:
        src = Path(self.source).resolve()
        tgt = Path(self.target)
        if not tgt.is_absolute():
            raise ValueError(f"Mount target must be an absolute path inside sandbox, got: {tgt}")
        object.__setattr__(self, "source", src)
        object.__setattr__(self, "target", tgt)
        is_ro = self.mode in (SandboxMountMode.READ_ONLY,)
        object.__setattr__(self, "read_only", is_ro)


@dataclass
class SandboxFilesystemGrant:
    """Filesystem boundaries and mounts granted to the worker.

    Invariant: Source project workspace is READ_ONLY by default.
    """

    workspace_dir: Path
    project_root: Optional[Path] = None
    project_mount_mode: SandboxMountMode = SandboxMountMode.READ_ONLY
    scratch_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    mounts: List[SandboxMount] = field(default_factory=list)
    allow_tmpfs: bool = True
    system_paths: List[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspace_dir = Path(self.workspace_dir).resolve()
        if self.project_root is not None:
            self.project_root = Path(self.project_root).resolve()
        if self.scratch_dir is not None:
            self.scratch_dir = Path(self.scratch_dir).resolve()
        if self.output_dir is not None:
            self.output_dir = Path(self.output_dir).resolve()


class SandboxNetworkMode(str, Enum):
    """Supported sandbox network modes (R2.9).

    Invariant: Only DENY and ALLOW_UNRESTRICTED are supported at R2.9.
    Domain filtering, egress proxying, and bandwidth shaping are not claimed or supported.
    """

    DENY = "deny"
    ALLOW_UNRESTRICTED = "allow_unrestricted"


@dataclass
class SandboxNetworkGrant:
    """Network boundary granted to the worker. Default is complete isolation.

    Rule: Caller cannot turn DENY -> ALLOW merely by modifying SandboxSpec;
    ALLOW_UNRESTRICTED requires explicit PolicyEngine authorization (R2.9).
    """

    allowed: bool = False
    mode: SandboxNetworkMode = SandboxNetworkMode.DENY
    allowed_hosts: List[str] = field(default_factory=list)
    authorized_by_policy: bool = False

    def __post_init__(self) -> None:
        if self.mode == SandboxNetworkMode.ALLOW_UNRESTRICTED:
            self.allowed = True
        elif self.allowed and self.mode == SandboxNetworkMode.DENY:
            self.mode = SandboxNetworkMode.ALLOW_UNRESTRICTED


@dataclass
class SandboxResourcePolicy:
    """Resource limits and quotas enforced on the sandbox worker (R2.9).

    Distinct CPU Controls (CTO Review Section 1):
    1. cpu_quota_percent: Rate limit (e.g. 50.0 for 50% CPU rate/share via cgroup CPUQuota).
    2. rlimit_cpu_seconds: Per-process hardware limit trap via RLIMIT_CPU.
    3. max_cpu_time_seconds: Cumulative sandbox-wide CPU budget across all tasks measured
       via cgroup cpu.stat usage_usec.
    4. max_wall_time_seconds: Elapsed real wall-clock time limit.
    """

    max_wall_time_seconds: float = 30.0
    max_cpu_time_seconds: Optional[float] = 30.0
    cpu_quota_percent: Optional[float] = 100.0  # Rate limit: 100% of 1 CPU core
    rlimit_cpu_seconds: Optional[int] = None  # Defense-in-depth per-process CPU trap
    max_memory_bytes: Optional[int] = 512 * 1024 * 1024  # 512 MB
    max_processes: Optional[int] = 32  # Maximum sandbox resource-group tasks (TasksMax=32)
    max_stdout_bytes: int = 10 * 1024 * 1024  # 10 MB output backpressure
    max_stderr_bytes: int = 10 * 1024 * 1024  # 10 MB output backpressure
    require_swap_disabled: bool = True  # Enforce MemorySwapMax=0 where supported
    profile_name: str = "untrusted_default_v1"

    @classmethod
    def untrusted_default(cls) -> SandboxResourcePolicy:
        """Canonical constructor for untrusted or generated code execution (R2.9 Section 4 & 7)."""
        return cls(
            max_wall_time_seconds=30.0,
            max_cpu_time_seconds=30.0,
            cpu_quota_percent=100.0,
            rlimit_cpu_seconds=None,
            max_memory_bytes=512 * 1024 * 1024,
            max_processes=32,
            max_stdout_bytes=10 * 1024 * 1024,
            max_stderr_bytes=10 * 1024 * 1024,
            require_swap_disabled=True,
            profile_name="untrusted_default_v1",
        )

    def validate_for_untrusted(self) -> None:
        """Verify that all mandatory limits are explicitly bounded for untrusted execution."""
        missing = []
        if self.max_wall_time_seconds is None or self.max_wall_time_seconds <= 0:
            missing.append("max_wall_time_seconds")
        if self.max_memory_bytes is None or self.max_memory_bytes <= 0:
            missing.append("max_memory_bytes")
        if self.max_processes is None or self.max_processes <= 0:
            missing.append("max_processes")
        if self.max_stdout_bytes is None or self.max_stdout_bytes <= 0:
            missing.append("max_stdout_bytes")
        if self.max_stderr_bytes is None or self.max_stderr_bytes <= 0:
            missing.append("max_stderr_bytes")
        if self.max_cpu_time_seconds is None and self.cpu_quota_percent is None:
            missing.append("max_cpu_time_seconds or cpu_quota_percent")
        if missing:
            raise ResourceLimitExceededError(
                reason=SandboxTerminalReason.RESOURCE_ISOLATION_UNAVAILABLE,
                message=f"Untrusted execution policy missing mandatory bounded limits: {', '.join(missing)}",
                violating_dimension="mandatory_policy_fields",
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_cpu_time_seconds": self.max_cpu_time_seconds,
            "cpu_quota_percent": self.cpu_quota_percent,
            "rlimit_cpu_seconds": self.rlimit_cpu_seconds,
            "max_memory_bytes": self.max_memory_bytes,
            "max_processes": self.max_processes,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
            "require_swap_disabled": self.require_swap_disabled,
            "profile_name": self.profile_name,
        }

    def clamp_to_ceiling(self, ceiling: SandboxResourcePolicy) -> SandboxResourcePolicy:
        """Return a new policy clamped to system ceiling limits (R2.9)."""
        return SandboxResourcePolicy(
            max_wall_time_seconds=min(self.max_wall_time_seconds, ceiling.max_wall_time_seconds),
            max_cpu_time_seconds=min(self.max_cpu_time_seconds, ceiling.max_cpu_time_seconds)
            if (self.max_cpu_time_seconds is not None and ceiling.max_cpu_time_seconds is not None)
            else (self.max_cpu_time_seconds or ceiling.max_cpu_time_seconds),
            cpu_quota_percent=min(self.cpu_quota_percent, ceiling.cpu_quota_percent)
            if (self.cpu_quota_percent is not None and ceiling.cpu_quota_percent is not None)
            else (self.cpu_quota_percent or ceiling.cpu_quota_percent),
            rlimit_cpu_seconds=min(self.rlimit_cpu_seconds, ceiling.rlimit_cpu_seconds)
            if (self.rlimit_cpu_seconds is not None and ceiling.rlimit_cpu_seconds is not None)
            else (self.rlimit_cpu_seconds or ceiling.rlimit_cpu_seconds),
            max_memory_bytes=min(self.max_memory_bytes, ceiling.max_memory_bytes)
            if (self.max_memory_bytes is not None and ceiling.max_memory_bytes is not None)
            else (self.max_memory_bytes or ceiling.max_memory_bytes),
            max_processes=min(self.max_processes, ceiling.max_processes)
            if (self.max_processes is not None and ceiling.max_processes is not None)
            else (self.max_processes or ceiling.max_processes),
            max_stdout_bytes=min(self.max_stdout_bytes, ceiling.max_stdout_bytes),
            max_stderr_bytes=min(self.max_stderr_bytes, ceiling.max_stderr_bytes),
            require_swap_disabled=self.require_swap_disabled and ceiling.require_swap_disabled,
            profile_name=self.profile_name,
        )


@dataclass
class SandboxSpec:
    """Specification for invoking an isolated worker process."""

    command: List[str]
    filesystem: SandboxFilesystemGrant
    cwd: Optional[Path] = None
    network: SandboxNetworkGrant = field(default_factory=SandboxNetworkGrant)
    secret_grants: List[SecretReference] = field(default_factory=list)
    env_allowlist: Dict[str, str] = field(default_factory=dict)
    resource_policy: SandboxResourcePolicy = field(default_factory=SandboxResourcePolicy)
    timeout_seconds: float = 30.0
    cancellation_token: Optional[CancellationToken] = None
    script: Optional[str] = None
    capability_id: Optional[str] = None
    project_id: Optional[str] = None
    execution_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.command and not self.script:
            raise ValueError("SandboxSpec must declare either a command or a script.")
        if self.cwd is None:
            self.cwd = self.filesystem.workspace_dir
        else:
            self.cwd = Path(self.cwd)
        # Synchronize timeout_seconds with resource_policy.max_wall_time_seconds
        if (
            self.resource_policy.max_wall_time_seconds
            and self.resource_policy.max_wall_time_seconds != 30.0
        ):
            self.timeout_seconds = self.resource_policy.max_wall_time_seconds
        elif self.timeout_seconds != 30.0:
            self.resource_policy.max_wall_time_seconds = self.timeout_seconds


@dataclass
class SandboxResult:
    """Outcome of sandbox worker execution."""

    execution_id: str
    exit_code: int
    stdout: str
    stderr: str
    status: SandboxStatus
    timed_out: bool = False
    cancelled: bool = False
    terminal_reason: SandboxTerminalReason = SandboxTerminalReason.NORMAL
    output_truncated: bool = False
    artifacts: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    resource_usage: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == SandboxStatus.COMPLETED and self.exit_code == 0

    def to_context_item(
        self,
        source_id: Optional[str] = None,
        include_stderr: bool = True,
        redacted_secrets: Optional[List[str]] = None,
    ) -> ContextItem:
        """Classify worker execution output as untrusted external evidence (R2.7).

        Redacts any known sensitive injected secrets before creating ContextItem.
        """
        combined = self.stdout
        if include_stderr and self.stderr:
            combined = f"{self.stdout}\n[STDERR]\n{self.stderr}" if self.stdout else self.stderr

        if redacted_secrets:
            for s in redacted_secrets:
                if s:
                    combined = combined.replace(s, "[REDACTED_SECRET]")

        sid = source_id or f"sandbox:{self.execution_id}"
        meta = {
            "execution_id": self.execution_id,
            "exit_code": self.exit_code,
            "status": self.status.value,
            "terminal_reason": self.terminal_reason.value,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "output_truncated": self.output_truncated,
            "artifacts": list(self.artifacts),
            "resource_usage": dict(self.resource_usage),
        }
        return ContextItem.from_external_content(
            content=combined,
            source_id=sid,
            source_type="sandbox_worker_output",
            metadata=meta,
        )


@dataclass
class SandboxExecutionRecord:
    """Audit record for execution ledger (R1.11, R2.8 & R2.9).

    Guarantees: No raw secrets or host-private absolute paths are stored.
    """

    execution_id: str
    backend: str
    workspace_scope: str
    network_allowed: bool
    secret_reference_ids: List[str]
    status: SandboxStatus
    terminal_reason: str
    start_time: float
    end_time: float
    duration_seconds: float
    artifacts: List[str]
    exit_code: int
    failure_category: Optional[str] = None
    resource_policy: Optional[Dict[str, Any]] = None
    resource_usage: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "backend": self.backend,
            "workspace_scope": self.workspace_scope,
            "network_allowed": self.network_allowed,
            "secret_reference_ids": self.secret_reference_ids,
            "status": self.status.value,
            "terminal_reason": self.terminal_reason,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "artifacts": self.artifacts,
            "exit_code": self.exit_code,
            "failure_category": self.failure_category,
            "resource_policy": self.resource_policy,
            "resource_usage": self.resource_usage,
        }


def generate_sandbox_id() -> str:
    """Generate a unique sandbox execution identifier."""
    return f"sbx-{uuid.uuid4().hex[:12]}"
