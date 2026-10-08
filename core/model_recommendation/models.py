"""core/model_recommendation/models.py

Domain models and schemas for local model catalog and hardware-fit recommendation.
Part of Milestone R3 Task R3.5 (Local Model Catalog and Recommendation).

Design Invariants:
1. Three Distinct Concepts:
   - CapabilityEligibility: Functional task capability checks (coding, reasoning, context length).
   - HardwareFitResult: Factual hardware feasibility checks (FITS, FITS_WITH_LIMITS, DOES_NOT_FIT, UNKNOWN).
   - LocalModelRecommendation: Tiers (FAST, BALANCED, BEST_LOCAL) mapped deterministically.
2. UNKNOWN Handling: UNKNOWN hardware facts or model requirements can NEVER be presented as a safe default recommendation.
3. Requirements Provenance: Distinguishes INSPECTED_ARTIFACT, TRUSTED_CATALOG, MODEL_METADATA, ESTIMATE, and UNKNOWN.
4. Privacy & Anti-Fingerprinting: Exposes hardware metrics (RAM, VRAM, core count) with strictly ZERO hostname, username,
   private paths, or serial numbers.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.model_registry.models import ModelIdentity, TriStateBool


class HardwareFitState(str, Enum):
    """Physical feasibility classification of running a model on detected host hardware."""

    FITS = "fits"
    FITS_WITH_LIMITS = "fits_with_limits"
    DOES_NOT_FIT = "does_not_fit"
    UNKNOWN = "unknown"


class RequirementsProvenance(str, Enum):
    """Authority and origin of hardware requirement facts."""

    INSPECTED_ARTIFACT = "inspected_artifact"
    TRUSTED_CATALOG = "trusted_catalog"
    MODEL_METADATA = "model_metadata"
    ESTIMATE = "estimate"
    UNKNOWN = "unknown"


class RecommendationTier(str, Enum):
    """Deterministic model recommendation tiers."""

    FAST = "fast"
    BALANCED = "balanced"
    BEST_LOCAL = "best_local"


class TaskRequirements(BaseModel):
    """Functional requirements specified for a task or query."""

    task_type: Optional[str] = None
    coding: bool = False
    reasoning: bool = False
    vision: bool = False
    tools: bool = False
    structured_output: bool = False
    min_context_tokens: int = 2048
    require_local_only: bool = True
    required_accelerator: Optional[str] = None


class CapabilityEligibility(BaseModel):
    """Result of evaluating a model's functional capabilities against task requirements."""

    eligible: bool
    missing_capabilities: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    evaluated_at: float = Field(default_factory=time.time)


class HardwareFitResult(BaseModel):
    """Factual physical hardware feasibility evaluation for a specific model."""

    state: HardwareFitState
    safe_ram_available_bytes: int
    required_ram_bytes: int
    ram_headroom_bytes: int
    ram_headroom_ratio: float  # [0.0, 1.0] safe headroom fraction
    vram_fit_state: Optional[HardwareFitState] = None
    available_vram_bytes: Optional[int] = None
    required_vram_bytes: Optional[int] = None
    vram_headroom_bytes: Optional[int] = None
    is_unified_memory: bool = False
    accelerator_compatible: bool = True
    backend_used: str = "cpu"
    provenance: RequirementsProvenance = RequirementsProvenance.TRUSTED_CATALOG
    rejection_reasons: List[str] = Field(default_factory=list)
    explanation: str = ""


class CatalogModelEntry(BaseModel):
    """Curated local model specification in Agent Engine local catalog."""

    model_identity: ModelIdentity
    family: str  # e.g., "qwen2.5", "llama3.2"
    architecture: str  # e.g., "qwen2", "llama"
    parameter_size: str  # e.g., "1.5B", "3B", "7B", "14B"
    parameter_count_billions: float  # e.g., 1.5, 3.0, 7.0
    quantization: str  # e.g., "Q4_K_M"
    managed_runtime: str = "llamacpp"
    artifact_size_bytes: int
    min_ram_bytes: int
    recommended_ram_bytes: int
    min_vram_bytes: Optional[int] = None
    recommended_vram_bytes: Optional[int] = None
    supported_backends: List[str] = Field(
        default_factory=lambda: ["cpu", "cuda", "metal", "rocm", "vulkan"]
    )
    supported_architectures: List[str] = Field(
        default_factory=lambda: ["x86_64", "arm64", "aarch64"]
    )
    context_window_limit: int = 32768
    capabilities: Dict[str, TriStateBool] = Field(default_factory=dict)
    quality_score: float = 0.5  # Static benchmark capability score [0.0, 1.0]
    provenance: RequirementsProvenance = RequirementsProvenance.TRUSTED_CATALOG
    catalog_version: str = "2026.10.1"
    updated_at: str = "2026-10-08T00:00:00Z"


class LocalModelRecommendation(BaseModel):
    """Single recommended model for a specific performance/resource tier."""

    tier: RecommendationTier
    model_identity: ModelIdentity
    fit_result: HardwareFitResult
    reason: str
    model_entry: CatalogModelEntry


class RecommendationExplanation(BaseModel):
    """Full transparent audit trail explaining why a model was recommended or alternatives rejected."""

    selected_tier: RecommendationTier
    model_identity: ModelIdentity
    hardware_fit: HardwareFitResult
    snapshot_timestamp: float
    stale_telemetry: bool
    factual_resources_used: Dict[str, Any]
    requirements_used: Dict[str, Any]
    reserves_used: Dict[str, int]
    provenance: RequirementsProvenance
    rejection_reasons: Dict[str, List[str]] = Field(default_factory=dict)


class LocalRecommendationResponse(BaseModel):
    """Complete response containing Fast, Balanced, and Best Local recommendations."""

    fast: Optional[LocalModelRecommendation] = None
    balanced: Optional[LocalModelRecommendation] = None
    best_local: Optional[LocalModelRecommendation] = None
    explanations: Dict[str, RecommendationExplanation] = Field(default_factory=dict)
    rejection_summary: Dict[str, List[str]] = Field(default_factory=dict)
    evaluated_candidates_count: int = 0
    snapshot_timestamp: float = 0.0
    stale_telemetry: bool = False
