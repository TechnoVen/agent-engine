"""core/model_registry/__init__.py

Canonical Model Capability Subsystem for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).
"""

from core.model_registry.catalog import get_builtin_catalog
from core.model_registry.models import (
    CapabilityFact,
    ExecutionLocation,
    HardwareRequirements,
    LatencyClass,
    LatencyProfile,
    ModelCandidate,
    ModelCapabilities,
    ModelDefinition,
    ModelIdentity,
    ModelRequirements,
    ObservedLatencyMetrics,
    PriceDirection,
    PriceUnit,
    PricingProfile,
    PrivacyProfile,
    ProvenanceType,
    TokenPrice,
    TriStateBool,
    parse_model_identifier,
)
from core.model_registry.registry import (
    ModelRegistry,
    get_model_registry,
    reset_model_registry,
)

__all__ = [
    # Enums & 3-Valued Logic
    "TriStateBool",
    "ProvenanceType",
    "LatencyClass",
    "ExecutionLocation",
    "PriceUnit",
    "PriceDirection",
    # Profiles & Components
    "ModelIdentity",
    "CapabilityFact",
    "ModelCapabilities",
    "HardwareRequirements",
    "PrivacyProfile",
    "PricingProfile",
    "TokenPrice",
    "LatencyProfile",
    "ObservedLatencyMetrics",
    # Core Registry Models
    "ModelDefinition",
    "ModelRequirements",
    "ModelCandidate",
    "parse_model_identifier",
    # Catalog
    "get_builtin_catalog",
    # Registry & Singleton
    "ModelRegistry",
    "get_model_registry",
    "reset_model_registry",
]
