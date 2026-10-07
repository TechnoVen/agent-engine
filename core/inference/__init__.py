"""core/inference/__init__.py

Managed Local Inference Supervisor Package.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Provides authoritative lifecycle management, health monitoring, secret-free execution,
and port allocation for Agent Engine's local llama.cpp-compatible inference runtime.
"""

from __future__ import annotations

from core.inference.binary import (
    BinaryNotFoundError,
    RuntimeBinaryInfo,
    RuntimeBinaryResolver,
    UntrustedBinaryLocationError,
)
from core.inference.environment import (
    build_child_environment,
    verify_child_environment_is_clean,
)
from core.inference.models import (
    RuntimeHealth,
    RuntimeInstance,
    RuntimeSpec,
    RuntimeState,
)
from core.inference.ports import (
    PortAllocationError,
    PortCollisionError,
    find_available_loopback_port,
    verify_endpoint_ownership,
)
from core.inference.process import RuntimeProcessHandle
from core.inference.supervisor import (
    LocalInferenceSupervisor,
    RuntimeCrashError,
    RuntimeStartupError,
    SupervisorError,
    get_local_inference_supervisor,
    reset_local_inference_supervisor,
)
from core.inference.validation import (
    InvalidModelFormatError,
    ModelArtifactValidator,
    ModelNotFoundError,
    ModelValidationError,
    ValidatedModelArtifact,
)

__all__ = [
    "RuntimeState",
    "RuntimeSpec",
    "RuntimeHealth",
    "RuntimeInstance",
    "RuntimeBinaryInfo",
    "RuntimeBinaryResolver",
    "BinaryNotFoundError",
    "UntrustedBinaryLocationError",
    "build_child_environment",
    "verify_child_environment_is_clean",
    "ModelArtifactValidator",
    "ValidatedModelArtifact",
    "ModelValidationError",
    "ModelNotFoundError",
    "InvalidModelFormatError",
    "find_available_loopback_port",
    "verify_endpoint_ownership",
    "PortAllocationError",
    "PortCollisionError",
    "RuntimeProcessHandle",
    "LocalInferenceSupervisor",
    "get_local_inference_supervisor",
    "reset_local_inference_supervisor",
    "SupervisorError",
    "RuntimeStartupError",
    "RuntimeCrashError",
]
