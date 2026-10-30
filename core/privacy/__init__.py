"""core/privacy package.

Canonical privacy classes and data-routing policy subsystem for Agent Engine.
Part of Milestone R3 Task R3.8.
"""

from __future__ import annotations

from core.privacy.engine import (
    PrivacyPolicyEngine,
    get_system_routing_policy,
    reset_system_routing_policy,
    set_system_routing_policy,
)
from core.privacy.models import (
    ApprovedCloudTarget,
    DataRoutingClass,
    DataRoutingPolicy,
    EffectiveRoutingPolicy,
    NoEligibleModelUnderPrivacyPolicyError,
    PrivacyEligibilityReason,
    ProviderPrivacyEligibility,
    RoutingPolicySource,
)

__all__ = [
    "ApprovedCloudTarget",
    "DataRoutingClass",
    "DataRoutingPolicy",
    "EffectiveRoutingPolicy",
    "NoEligibleModelUnderPrivacyPolicyError",
    "PrivacyEligibilityReason",
    "PrivacyPolicyEngine",
    "ProviderPrivacyEligibility",
    "RoutingPolicySource",
    "get_system_routing_policy",
    "reset_system_routing_policy",
    "set_system_routing_policy",
]
