"""core/privacy/models.py

Canonical Privacy and Data-Routing Domain Models for Agent Engine.
Part of Milestone R3 Task R3.8 (Privacy classes and data-routing policy).

Design Invariants:
1. Three canonical classes: LOCAL_ONLY, APPROVED_CLOUD, ANY_CONFIGURED.
2. Deterministic 3-valued truth semantics: Unknown location or egress fails closed for LOCAL_ONLY.
3. Strict identity validation: Approved cloud targets reject wildcards, URLs, and credentials.
4. Strict non-relaxation semantics: Untrusted entities cannot relax privacy classes.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.model_registry.models import ExecutionLocation, TriStateBool
from core.providers.registry import _CANONICAL_ALIAS_MAP

_WILDCARD_PATTERN = re.compile(r"[\*\?\[\]]")
_CREDENTIAL_PATTERN = re.compile(
    r"(?:api[-_]?key|sk-[a-zA-Z0-9_\-]{8,}|bearer|token|secret|password)", re.IGNORECASE
)
_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)


class DataRoutingClass(str, Enum):
    """Canonical data routing privacy classes governing model selection and network egress."""

    LOCAL_ONLY = "local_only"
    APPROVED_CLOUD = "approved_cloud"
    ANY_CONFIGURED = "any_configured"

    @property
    def strictness_rank(self) -> int:
        """Numeric rank of policy strictness (higher number = stricter policy).

        LOCAL_ONLY (3) > APPROVED_CLOUD (2) > ANY_CONFIGURED (1).
        """
        if self == DataRoutingClass.LOCAL_ONLY:
            return 3
        elif self == DataRoutingClass.APPROVED_CLOUD:
            return 2
        return 1

    def is_relaxation_of(self, other: "DataRoutingClass") -> bool:
        """Return True if transitioning from `other` to `self` relaxes privacy."""
        return self.strictness_rank < other.strictness_rank

    def is_tightening_of(self, other: "DataRoutingClass") -> bool:
        """Return True if transitioning from `other` to `self` tightens privacy."""
        return self.strictness_rank > other.strictness_rank


class RoutingPolicySource(str, Enum):
    """Authoritative origin of an effective data routing policy."""

    PROFILE_DEFAULT = "profile_default"
    PROJECT_OVERRIDE = "project_override"
    TASK_OVERRIDE = "task_override"
    ENFORCED_FALLBACK = "enforced_fallback"


class ApprovedCloudTarget(BaseModel):
    """Explicitly approved cloud target identifier using canonical provider/model identities.

    Invariants:
    1. Rejects wildcards (*, ?), regexes, or substring patterns.
    2. Rejects URLs and protocol schemes (e.g. https://).
    3. Rejects credentials, keys, or bearer tokens.
    4. Automatically normalizes provider aliases into canonical provider IDs.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str
    model_id: Optional[str] = None

    @field_validator("provider_id", mode="before")
    @classmethod
    def validate_provider_id(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("provider_id must be a string")
        clean = v.strip().lower()
        if not clean:
            raise ValueError("provider_id cannot be empty")
        if _WILDCARD_PATTERN.search(clean):
            raise ValueError(f"Approved cloud provider_id cannot contain wildcards: '{clean}'")
        if _URL_PATTERN.search(clean):
            raise ValueError(f"Approved cloud provider_id cannot be a URL: '{clean}'")
        if _CREDENTIAL_PATTERN.search(clean):
            raise ValueError(
                "Approved cloud provider_id cannot contain credentials or secret tokens"
            )
        # Normalize alias
        return _CANONICAL_ALIAS_MAP.get(clean, clean)

    @field_validator("model_id", mode="before")
    @classmethod
    def validate_model_id(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("model_id must be a string")
        clean = v.strip().lower()
        if not clean:
            return None
        if _WILDCARD_PATTERN.search(clean):
            raise ValueError(f"Approved cloud model_id cannot contain wildcards: '{clean}'")
        if _URL_PATTERN.search(clean):
            raise ValueError(f"Approved cloud model_id cannot be a URL: '{clean}'")
        if _CREDENTIAL_PATTERN.search(clean):
            raise ValueError("Approved cloud model_id cannot contain credentials or secret tokens")
        return clean

    @property
    def canonical_target_id(self) -> str:
        """Formatted canonical target identifier."""
        if self.model_id:
            return f"{self.provider_id}:{self.model_id}"
        return self.provider_id


class DataRoutingPolicy(BaseModel):
    """Configured data routing policy at profile, project, or task level."""

    routing_class: DataRoutingClass = DataRoutingClass.LOCAL_ONLY
    approved_cloud_targets: List[ApprovedCloudTarget] = Field(default_factory=list)
    allow_relaxation_by_task: bool = False
    allow_project_relaxation: bool = False


class EffectiveRoutingPolicy(BaseModel):
    """Resolved authoritative data routing policy governing an execution lifecycle."""

    effective_class: DataRoutingClass
    source: RoutingPolicySource
    profile_policy: DataRoutingPolicy
    project_policy: Optional[DataRoutingPolicy] = None
    task_policy: Optional[DataRoutingPolicy] = None
    approved_targets: List[ApprovedCloudTarget] = Field(default_factory=list)
    relaxation_attempted: bool = False
    relaxation_denied: bool = False
    audit_reason: Optional[str] = None

    def is_target_approved(self, provider_id: str, model_id: Optional[str] = None) -> bool:
        """Check whether a cloud provider and optional model are explicitly approved."""
        canon_provider = _CANONICAL_ALIAS_MAP.get(
            provider_id.strip().lower(), provider_id.strip().lower()
        )
        canon_model = model_id.strip().lower() if model_id else None

        for target in self.approved_targets:
            if target.provider_id == canon_provider:
                # If target has no specific model_id, all models for this approved provider are approved
                if target.model_id is None:
                    return True
                # If target specified a model_id, it must match
                if canon_model and target.model_id == canon_model:
                    return True
        return False

    def is_provider_permitted(self, provider_id: str, provider_def: Optional[Any] = None) -> bool:
        """Check whether a provider is permitted under this effective privacy policy."""
        from core.privacy.engine import PrivacyPolicyEngine

        eligibility = PrivacyPolicyEngine.evaluate_provider_privacy(
            provider_id=provider_id,
            effective_policy=self,
            provider_def=provider_def,
        )
        return eligibility.eligible


class PrivacyEligibilityReason(str, Enum):
    """Exhaustive taxonomy of privacy eligibility outcomes and rejection codes."""

    ELIGIBLE = "eligible"
    PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER = "PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER"
    PRIVACY_PROVIDER_NOT_APPROVED = "PRIVACY_PROVIDER_NOT_APPROVED"
    PRIVACY_MODEL_NOT_APPROVED = "PRIVACY_MODEL_NOT_APPROVED"
    PRIVACY_LOCATION_UNKNOWN = "PRIVACY_LOCATION_UNKNOWN"
    PRIVACY_DATA_EGRESS_UNKNOWN = "PRIVACY_DATA_EGRESS_UNKNOWN"
    PRIVACY_DATA_LEAVES_DEVICE_FORBIDDEN = "PRIVACY_DATA_LEAVES_DEVICE_FORBIDDEN"
    NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY = "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY"


class ProviderPrivacyEligibility(BaseModel):
    """Detailed evaluation result of a candidate model/provider against an effective policy."""

    eligible: bool
    rejection_reasons: List[PrivacyEligibilityReason] = Field(default_factory=list)
    provider_id: str
    model_id: Optional[str] = None
    execution_location: ExecutionLocation = ExecutionLocation.UNKNOWN
    data_leaves_device: TriStateBool = TriStateBool.UNKNOWN


class NoEligibleModelUnderPrivacyPolicyError(Exception):
    """Raised when no provider/model satisfies privacy policy constraints (zero cloud fallback)."""

    def __init__(self, message: str, rejection_details: Optional[List[dict[str, Any]]] = None):
        super().__init__(message)
        self.message = message
        self.rejection_details = rejection_details or []
