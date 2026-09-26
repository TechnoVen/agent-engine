"""core/sandbox/models.py

Data models and contracts for the Sandbox Worker Runtime.
Part of Milestone R2 Task R2.8 (Sandbox worker runtime).

Design Invariants:
1. Default-deny security posture: Network is disabled by default; environment is minimal.
2. Explicit grants: Filesystem access is strictly bounded to explicitly granted workspace and mounts.
3. R2.7 Integration: Worker stdout, stderr, and produced files are classified as untrusted evidence.
4. R2.6 Integration: Secrets are injected only into the child process at launch and wiped immediately.
5. R1.9 Integration: Cancellation tokens terminate worker processes gracefully then forcefully.
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


@dataclass(frozen=True)
class SandboxMount:
    """Represents an explicit filesystem mount into the sandbox environment."""

    source: Path
    target: Path
    read_only: bool = True

    def __post_init__(self) -> None:
        src = Path(self.source).resolve()
        tgt = Path(self.target)
        if not tgt.is_absolute():
            raise ValueError(f"Mount target must be an absolute path inside sandbox, got: {tgt}")
        object.__setattr__(self, "source", src)
        object.__setattr__(self, "target", tgt)


@dataclass
class SandboxFilesystemGrant:
    """Filesystem boundaries and mounts granted to the worker."""

    workspace_dir: Path
    mounts: List[SandboxMount] = field(default_factory=list)
    allow_tmpfs: bool = True
    system_paths: List[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspace_dir = Path(self.workspace_dir).resolve()


@dataclass
class SandboxNetworkGrant:
    """Network boundary granted to the worker. Default is complete isolation."""

    allowed: bool = False
    allowed_hosts: List[str] = field(default_factory=list)


@dataclass
class SandboxSpec:
    """Specification for invoking an isolated worker process."""

    command: List[str]
    filesystem: SandboxFilesystemGrant
    cwd: Optional[Path] = None
    network: SandboxNetworkGrant = field(default_factory=SandboxNetworkGrant)
    secret_grants: List[SecretReference] = field(default_factory=list)
    env_allowlist: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    cancellation_token: Optional[CancellationToken] = None
    script: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.command and not self.script:
            raise ValueError("SandboxSpec must declare either a command or a script.")
        if self.cwd is None:
            self.cwd = self.filesystem.workspace_dir
        else:
            self.cwd = Path(self.cwd)


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
    artifacts: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def is_success(self) -> bool:
        return self.status == SandboxStatus.COMPLETED and self.exit_code == 0

    def to_context_item(
        self,
        source_id: Optional[str] = None,
        include_stderr: bool = True,
    ) -> ContextItem:
        """Classify worker execution output as untrusted external evidence (R2.7)."""
        combined = self.stdout
        if include_stderr and self.stderr:
            combined = f"{self.stdout}\n[STDERR]\n{self.stderr}" if self.stdout else self.stderr

        sid = source_id or f"sandbox:{self.execution_id}"
        meta = {
            "execution_id": self.execution_id,
            "exit_code": self.exit_code,
            "status": self.status.value,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "artifacts": list(self.artifacts),
        }
        return ContextItem.from_external_content(
            content=combined,
            source_id=sid,
            source_type="sandbox_worker_output",
            metadata=meta,
        )


@dataclass
class SandboxExecutionRecord:
    """Audit record for execution ledger (R1.11 & R2.8).

    Guarantees: No raw secrets or host-private absolute paths are stored.
    """

    execution_id: str
    backend: str
    workspace_scope: str
    network_allowed: bool
    secret_reference_ids: List[str]
    status: SandboxStatus
    start_time: float
    end_time: float
    duration_seconds: float
    artifacts: List[str]
    exit_code: int
    failure_category: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "backend": self.backend,
            "workspace_scope": self.workspace_scope,
            "network_allowed": self.network_allowed,
            "secret_reference_ids": self.secret_reference_ids,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "artifacts": self.artifacts,
            "exit_code": self.exit_code,
            "failure_category": self.failure_category,
        }


def generate_sandbox_id() -> str:
    """Generate a unique sandbox execution identifier."""
    return f"sbx-{uuid.uuid4().hex[:12]}"
