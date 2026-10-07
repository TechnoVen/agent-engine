"""core/inference/models.py

Canonical data structures and schemas for the Managed Local Inference Supervisor.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Narrow 0.5 state machine: STOPPED, STARTING, READY, STOPPING, FAILED.
2. Loopback-only binding: host strictly restricted to 127.0.0.1 / localhost / ::1.
3. Structured model identity integration: binds canonical ModelIdentity.
4. Binary integrity & provenance: records version, implementation, SHA-256, and origin.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from core.model_registry.models import ModelIdentity


class RuntimeState(str, Enum):
    """Lifecycle state machine for managed inference runtime."""

    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"


class RuntimeBinaryInfo(BaseModel):
    """Integrity and provenance details of the managed runtime executable."""

    binary_path: str
    version: str
    implementation: str = "llama.cpp"
    sha256: str
    provenance: str = "managed_installation"


class RuntimeSpec(BaseModel):
    """Specification configuration for launching a managed inference instance."""

    model_identity: ModelIdentity
    model_path: str
    context_size: int = Field(default=2048, ge=128, le=131072)
    host: str = "127.0.0.1"
    port: Optional[int] = Field(default=None, ge=1024, le=65535)
    api_key: Optional[str] = Field(default=None, repr=False)
    gpu_layers: int = Field(default=0, ge=0)
    threads: Optional[int] = Field(default=None, ge=1)
    startup_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    shutdown_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    extra_args: List[str] = Field(default_factory=list)

    @field_validator("host")
    @classmethod
    def validate_loopback_only(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if v_clean not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(
                f"Invalid host '{v}': managed inference server must strictly bind to loopback (127.0.0.1 / localhost / ::1). "
                "0.0.0.0 or LAN exposure is strictly prohibited."
            )
        return v_clean


class RuntimeHealth(BaseModel):
    """Factual point-in-time health report of the managed inference runtime."""

    state: RuntimeState
    is_ready: bool = False
    pid: Optional[int] = None
    endpoint_url: Optional[str] = None
    model_loaded: Optional[str] = None
    latency_ms: Optional[float] = None
    last_checked_at: float = Field(default_factory=time.time)
    error_message: Optional[str] = None


class RuntimeInstance(BaseModel):
    """Active or historical execution instance of a managed runtime.

    Security Boundary Note:
    api_key is ephemeral and per-launch. repr=False prevents leakage into string logs or tracebacks.
    """

    instance_id: str
    spec: RuntimeSpec
    state: RuntimeState = RuntimeState.STOPPED
    pid: Optional[int] = None
    endpoint_url: Optional[str] = None
    api_key: Optional[str] = Field(default=None, repr=False)
    started_at: Optional[float] = None
    ready_at: Optional[float] = None
    stopped_at: Optional[float] = None
    exit_code: Optional[int] = None
    exit_reason: Optional[str] = None
    binary_info: Optional[RuntimeBinaryInfo] = None
    resource_snapshot_before: Optional[Dict[str, Any]] = None
    resource_snapshot_after: Optional[Dict[str, Any]] = None
