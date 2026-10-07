"""core/providers/models.py

Canonical Provider Data Structures and Contracts for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).

Design Invariants:
1. Stable provider identity: provider_id is a machine-readable identifier strictly
   separated from display name, aliases, endpoint URL, and concrete models.
2. Provider vs model responsibilities: Provider contracts govern connection endpoints,
   auth boundaries, transports, timeouts, rate limits, and health evidence.
   Model cataloging and capability mapping remain strictly decoupled (Task R3.2).
3. Explicit health state taxonomy: CONFIGURED, AVAILABLE, HEALTHY, DEGRADED,
   UNAVAILABLE, AUTHENTICATION_FAILED with real timestamped probe evidence.
4. R2.6 Secret Boundary: Credentials reference SecretReference or environment keys;
   plaintext secrets are never stored in configurations, definitions, or serialized dicts.
5. Ledger Evidence: ProviderCallEvidence captures canonical provider_id, endpoint class,
   and operational metrics without revealing credentials.
"""

from __future__ import annotations

from enum import Enum
import re
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from core.security.secrets import SecretReference

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9_\-]+$")


class ProviderAuthType(str, Enum):
    """Authentication mechanisms supported by providers."""

    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    CUSTOM = "custom"


class ProviderEndpointStyle(str, Enum):
    """Protocol / wire format style used by the provider."""

    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"
    CUSTOM = "custom"


class ProviderHealthStatus(str, Enum):
    """Explicit lifecycle health states for provider instances."""

    CONFIGURED = "configured"  # Configured in engine, awaiting initial health probe
    AVAILABLE = "available"  # Reachable and operational
    HEALTHY = "healthy"  # Fully operational, latency within threshold, zero recent errors
    DEGRADED = "degraded"  # Operational but elevated latency or transient retries
    UNAVAILABLE = "unavailable"  # Unreachable, connection refused, circuit open, or 5xx
    AUTHENTICATION_FAILED = "authentication_failed"  # 401 / 403 or invalid credential


class ProviderCapabilities(BaseModel):
    """Operational capabilities exposed by a provider infrastructure."""

    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    is_local: bool = False
    requires_credentials: bool = True
    max_context_window: Optional[int] = None
    concurrency_limit: Optional[int] = None
    degraded_latency_threshold_ms: float = 3000.0


class ProviderHealth(BaseModel):
    """Timestamped health evidence produced by active probes."""

    status: ProviderHealthStatus = ProviderHealthStatus.CONFIGURED
    latency_ms: float = 0.0
    last_checked_at: float = Field(default_factory=time.time)
    error_message: Optional[str] = None
    consecutive_failures: int = 0
    details: Dict[str, Any] = Field(default_factory=dict)

    def is_usable(self) -> bool:
        """Return True if provider can accept inference requests."""
        return self.status in (
            ProviderHealthStatus.HEALTHY,
            ProviderHealthStatus.AVAILABLE,
            ProviderHealthStatus.DEGRADED,
            ProviderHealthStatus.CONFIGURED,
        )


class ProviderConfiguration(BaseModel):
    """Runtime configuration for a provider instance (credential & endpoint boundary)."""

    provider_id: str
    endpoint_url: Optional[str] = None
    auth_type: ProviderAuthType = ProviderAuthType.API_KEY
    secret_ref: Optional[SecretReference] = None
    credential_key: Optional[str] = None  # e.g. "OPENAI_API_KEY"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    custom_headers: Dict[str, str] = Field(default_factory=dict)
    extra_config: Dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if not v_clean or not _PROVIDER_ID_PATTERN.match(v_clean):
            raise ValueError(
                f"Invalid provider_id '{v}': must match [a-z0-9_\\-]+ and be non-empty"
            )
        return v_clean


class ProviderDefinition(BaseModel):
    """Authoritative canonical registration record for an intelligence provider."""

    provider_id: str
    display_name: str
    endpoint_style: ProviderEndpointStyle
    default_endpoint_url: Optional[str] = None
    default_model: str
    aliases: List[str] = Field(default_factory=list)
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    config: ProviderConfiguration
    health: ProviderHealth = Field(default_factory=ProviderHealth)

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if not v_clean or not _PROVIDER_ID_PATTERN.match(v_clean):
            raise ValueError(
                f"Invalid provider_id '{v}': must match [a-z0-9_\\-]+ and be non-empty"
            )
        return v_clean

    def to_safe_dict(self) -> Dict[str, Any]:
        """Export safe public representation guaranteed to contain 0 plaintext secrets."""
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "endpoint_style": self.endpoint_style.value,
            "default_endpoint_url": self.default_endpoint_url,
            "default_model": self.default_model,
            "aliases": self.aliases,
            "capabilities": self.capabilities.model_dump(),
            "config": {
                "provider_id": self.config.provider_id,
                "endpoint_url": self.config.endpoint_url,
                "auth_type": self.config.auth_type.value,
                "credential_configured": bool(self.config.secret_ref or self.config.credential_key),
                "credential_key": self.config.credential_key,
                "timeout_seconds": self.config.timeout_seconds,
                "max_retries": self.config.max_retries,
                "is_enabled": self.config.is_enabled,
            },
            "health": self.health.model_dump(),
        }


class ProviderCallEvidence(BaseModel):
    """Immutable audit record of a provider invocation for the execution ledger."""

    call_id: str
    provider_id: str
    model_id: str
    endpoint_class: str
    started_at: float
    completed_at: float
    latency_ms: float
    status: str = "completed"  # "completed", "failed", "cancelled"
    error_type: Optional[str] = None
    input_tokens_estimated: int = 0
    output_tokens_estimated: int = 0
    is_fallback: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)
