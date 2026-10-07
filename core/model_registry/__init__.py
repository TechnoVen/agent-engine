"""core/model_registry/__init__.py

Canonical Model Capability Subsystem for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).
"""

from core.model_registry.catalog import get_builtin_catalog
from core.model_registry.models import (
    HardwareRequirements,
    LatencyClass,
    LatencyProfile,
    ModelCandidate,
    ModelCapabilities,
    ModelDefinition,
    ModelRequirements,
    PricingProfile,
    PrivacyProfile,
    ProvenanceType,
    TriStateBool,
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
    # Profiles & Components
    "ModelCapabilities",
    "HardwareRequirements",
    "PrivacyProfile",
    "PricingProfile",
    "LatencyProfile",
    # Core Registry Models
    "ModelDefinition",
    "ModelRequirements",
    "ModelCandidate",
    # Catalog
    "get_builtin_catalog",
    # Registry & Singleton
    "ModelRegistry",
    "get_model_registry",
    "reset_model_registry",
]
