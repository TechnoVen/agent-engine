"""core/providers/verification/models.py

Canonical Provider Connection Verification Data Structures and Status Taxonomy.
Part of Milestone R3 Task R3.11 (Provider Connection Verification).

Design Invariants:
1. Operational Truth: "Connected" means a real provider operation succeeds (real completion canary),
   not merely that configuration exists or /models or /health responds.
2. Failure Classification: Granular, normalized taxonomy distinguishing auth, network, timeout,
   model not found, rate limit, quota exhaustion, and server/provider error.
3. Freshness Semantics: Timestamped verification results with explicit freshness boundaries
   (fresh verified, stale verification, never verified/not configured).
4. Secret Boundary: Sanitized errors and details contain zero plaintext API keys, tokens,
   or sensitive user/project prompt content.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.model_registry.models import ModelIdentity


class ConnectionVerificationStatus(str, Enum):
    """Canonical taxonomy of provider verification statuses (Task R3.11)."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    VERIFIED_CONNECTED = "VERIFIED_CONNECTED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class ProviderConnectionVerification(BaseModel):
    """Immutable audit record and cached status of a provider connection verification probe."""

    model_config = ConfigDict(frozen=True)

    provider_id: str
    model_identity: Optional[ModelIdentity] = None
    status: ConnectionVerificationStatus
    last_verified_at: float = Field(default_factory=time.time)
    latency_ms: float = 0.0
    failure_class: Optional[str] = None
    sanitized_error: Optional[str] = None
    verification_version: str = "v1"
    probe_type: str = "real_completion_canary"
    details: Dict[str, Any] = Field(default_factory=dict)

    def is_fresh(self, max_age_seconds: float = 86400.0) -> bool:
        """Return True if the verification is currently connected and within the freshness TTL."""
        if self.status != ConnectionVerificationStatus.VERIFIED_CONNECTED:
            return False
        return (time.time() - self.last_verified_at) <= max_age_seconds

    def display_state(self, max_age_seconds: float = 86400.0) -> str:
        """Human-readable display state for UI surfaces (Settings / Dashboard)."""
        if self.status == ConnectionVerificationStatus.VERIFIED_CONNECTED:
            return "Connected" if self.is_fresh(max_age_seconds) else "Verification stale"
        if self.status == ConnectionVerificationStatus.NOT_CONFIGURED:
            return "Not configured"
        return "Verification failed"

    def to_safe_dict(self) -> Dict[str, Any]:
        """Export safe public representation guaranteed to contain 0 plaintext secrets."""
        return {
            "provider_id": self.provider_id,
            "model_identity": self.model_identity.model_dump() if self.model_identity else None,
            "status": self.status.value,
            "last_verified_at": self.last_verified_at,
            "latency_ms": self.latency_ms,
            "failure_class": self.failure_class,
            "sanitized_error": self.sanitized_error,
            "verification_version": self.verification_version,
            "probe_type": self.probe_type,
            "is_fresh": self.is_fresh(),
            "display_state": self.display_state(),
            "details": self.details,
        }
