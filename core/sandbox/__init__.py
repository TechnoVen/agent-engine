"""core/sandbox/__init__.py

Canonical Sandbox Worker Runtime for Agent Engine.
Part of Milestone R2 Task R2.8 (Sandbox worker runtime).
"""

from core.sandbox.backend import (
    DarwinSandboxBackend,
    LinuxBubblewrapBackend,
    NullSandboxBackend,
    SandboxBackend,
    WindowsSandboxBackend,
)
from core.sandbox.models import (
    ResourceIsolationUnavailableError,
    ResourceLimitExceededError,
    SandboxCancellationError,
    SandboxError,
    SandboxExecutionRecord,
    SandboxFilesystemGrant,
    SandboxMount,
    SandboxMountMode,
    SandboxNetworkGrant,
    SandboxResourcePolicy,
    SandboxResult,
    SandboxSecurityError,
    SandboxSpec,
    SandboxStatus,
    SandboxTerminalReason,
    SandboxTimeoutError,
    SandboxUnavailableError,
    generate_sandbox_id,
)
from core.sandbox.service import SandboxService

__all__ = [
    "SandboxService",
    "SandboxBackend",
    "LinuxBubblewrapBackend",
    "DarwinSandboxBackend",
    "WindowsSandboxBackend",
    "NullSandboxBackend",
    "SandboxSpec",
    "SandboxFilesystemGrant",
    "SandboxMount",
    "SandboxMountMode",
    "SandboxNetworkGrant",
    "SandboxResourcePolicy",
    "SandboxResult",
    "SandboxStatus",
    "SandboxTerminalReason",
    "SandboxExecutionRecord",
    "SandboxError",
    "SandboxUnavailableError",
    "SandboxSecurityError",
    "SandboxTimeoutError",
    "SandboxCancellationError",
    "ResourceLimitExceededError",
    "ResourceIsolationUnavailableError",
    "generate_sandbox_id",
]
