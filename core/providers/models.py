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


class ProviderEndpointClass(str, Enum):
    """Canonical controlled taxonomy of endpoint types for execution ledger and routing."""

    CLOUD = "cloud"
    LOCAL_MANAGED = "local_managed"
    LOCAL_EXTERNAL = "local_external"
    CUSTOM_REMOTE = "custom_remote"


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


class ProviderConfigurationState(str, Enum):
    """Configuration validity state of a provider."""

    CONFIGURED = "configured"
    UNCONFIGURED = "unconfigured"
    INVALID = "invalid"


class ProviderAvailability(str, Enum):
    """Operational / transport reachability of a provider."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderHealthStatus(str, Enum):
    """Health quality and authentication state of a provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    AUTHENTICATION_FAILED = "authentication_failed"
    UNKNOWN = "unknown"


class ProviderCapabilities(BaseModel):
    """Operational capabilities exposed by a provider infrastructure."""

    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    supports_model_discovery: bool = False
    is_local: bool = False
    requires_credentials: bool = True
    max_context_window: Optional[int] = None
    concurrency_limit: Optional[int] = None
    degraded_latency_threshold_ms: float = 3000.0


class ProviderHealth(BaseModel):
    """Timestamped health evidence separating configuration, availability, and health dimensions.

    Invariants:
    1. configured != available != healthy.
    2. Zero secret leaks in error_message or details.
    3. Checked_at records monotonic time; stale indicates cache expiry.
    """

    config_state: ProviderConfigurationState = ProviderConfigurationState.UNCONFIGURED
    availability: ProviderAvailability = ProviderAvailability.UNKNOWN
    status: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN
    latency_ms: float = 0.0
    last_checked_at: float = Field(default_factory=time.time)
    error_message: Optional[str] = None
    degraded_reason: Optional[str] = None
    consecutive_failures: int = 0
    probe_type: str = "transport"
    stale: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return self.config_state == ProviderConfigurationState.CONFIGURED

    @property
    def is_available(self) -> bool:
        return self.availability == ProviderAvailability.AVAILABLE

    @property
    def is_healthy(self) -> bool:
        return self.status == ProviderHealthStatus.HEALTHY

    def is_usable(self) -> bool:
        """Return True if provider can accept inference requests."""
        return (
            self.config_state == ProviderConfigurationState.CONFIGURED
            and self.availability != ProviderAvailability.UNAVAILABLE
            and self.status
            not in (
                ProviderHealthStatus.AUTHENTICATION_FAILED,
                ProviderHealthStatus.UNHEALTHY,
            )
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
    endpoint_class: ProviderEndpointClass = ProviderEndpointClass.CLOUD
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
            "endpoint_class": self.endpoint_class.value,
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

    @field_validator("endpoint_class")
    @classmethod
    def validate_endpoint_class(cls, v: str) -> str:
        clean = v.strip().lower()
        valid = {e.value for e in ProviderEndpointClass}
        if clean not in valid:
            raise ValueError(
                f"Invalid endpoint_class '{v}': must be one of {sorted(valid)} (zero URLs/ports/queries allowed)"
            )
        return clean
