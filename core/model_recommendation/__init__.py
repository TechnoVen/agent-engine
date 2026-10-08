"""core/model_recommendation/__init__.py

Curated local model catalog and deterministic hardware-fit recommendation engine.
Part of Milestone R3 Task R3.5 (Local Model Catalog and Recommendation).
"""

from core.model_recommendation.catalog import (
    DEFAULT_CATALOG_UPDATED_AT,
    DEFAULT_CATALOG_VERSION,
    LocalModelCatalog,
    get_curated_local_models,
)
from core.model_recommendation.engine import (
    evaluate_capability_eligibility,
    evaluate_hardware_fit,
    recommend_local_models,
)
from core.model_recommendation.models import (
    CapabilityEligibility,
    CatalogModelEntry,
    HardwareFitResult,
    HardwareFitState,
    LocalModelRecommendation,
    LocalRecommendationResponse,
    ModelKVArchitectureMetadata,
    NumericFactProvenance,
    RecommendationExplanation,
    RecommendationTier,
    RequirementsProvenance,
    TaskRequirements,
)
from core.model_recommendation.policy import (
    DEFAULT_AGENT_ENGINE_RESERVE_BYTES,
    DEFAULT_DISCRETE_VRAM_RESERVE_BYTES,
    DEFAULT_OS_RESERVE_BYTES,
    DEFAULT_RUNTIME_BASE_RESERVE_BYTES,
    ReservePolicy,
    calculate_kv_context_overhead,
    calculate_model_kv_cache_bytes,
    calculate_safe_available_ram,
    calculate_safe_available_vram,
    calculate_usable_ram_before_model,
)

__all__ = [
    # Catalog
    "DEFAULT_CATALOG_UPDATED_AT",
    "DEFAULT_CATALOG_VERSION",
    "LocalModelCatalog",
    "get_curated_local_models",
    # Engine
    "evaluate_capability_eligibility",
    "evaluate_hardware_fit",
    "recommend_local_models",
    # Models
    "CapabilityEligibility",
    "CatalogModelEntry",
    "HardwareFitResult",
    "HardwareFitState",
    "LocalModelRecommendation",
    "LocalRecommendationResponse",
    "ModelKVArchitectureMetadata",
    "NumericFactProvenance",
    "RecommendationExplanation",
    "RecommendationTier",
    "RequirementsProvenance",
    "TaskRequirements",
    # Policy
    "DEFAULT_AGENT_ENGINE_RESERVE_BYTES",
    "DEFAULT_DISCRETE_VRAM_RESERVE_BYTES",
    "DEFAULT_OS_RESERVE_BYTES",
    "DEFAULT_RUNTIME_BASE_RESERVE_BYTES",
    "ReservePolicy",
    "calculate_kv_context_overhead",
    "calculate_model_kv_cache_bytes",
    "calculate_safe_available_ram",
    "calculate_safe_available_vram",
    "calculate_usable_ram_before_model",
]
