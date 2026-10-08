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


class NumericFactProvenance(str, Enum):
    """Authority and verification origin of numerical facts."""

    DECLARED_FACT = "declared_fact"  # Vendor / publisher stated specification
    INSPECTED_FACT = "inspected_fact"  # Directly extracted from GGUF binary header
    MEASURED_FACT = "measured_fact"  # Measured empirically in testing
    DERIVED_ESTIMATE = "derived_estimate"  # Computed via mathematical formula (e.g. KV cache)
    CURATED_HEURISTIC = "curated_heuristic"  # Conservative engineering recommendation
    CURATED_POLICY = "curated_policy"  # Policy-assigned tier or ranking
    UNKNOWN = "unknown"  # Unverified / indeterminate


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


class ModelKVArchitectureMetadata(BaseModel):
    """Model architecture parameters required to calculate exact KV cache memory scaling."""

    num_layers: int
    num_kv_heads: int
    head_dim: int
    cache_element_bytes: int = 2  # FP16 KV cache in llama.cpp (2 bytes per element)
    provenance: NumericFactProvenance = NumericFactProvenance.DECLARED_FACT
    source: str = "official_model_config"


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
    usable_before_model_bytes: int  # Exact denominator: available_ram - OS - AE - runtime_base
    required_ram_bytes: int  # model resident min_ram + KV cache context bytes
    ram_headroom_bytes: int  # usable_before_model_bytes - required_ram_bytes
    ram_headroom_ratio: (
        float  # [0.0, 1.0] exact headroom fraction: ram_headroom_bytes / usable_before_model_bytes
    )
    memory_unit: str = "bytes"
    kv_context_bytes: int = 0
    kv_context_provenance: NumericFactProvenance = NumericFactProvenance.DERIVED_ESTIMATE
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
    parameter_count_provenance: NumericFactProvenance = NumericFactProvenance.DECLARED_FACT
    quantization: str  # e.g., "Q4_K_M"
    managed_runtime: str = "llamacpp"
    memory_unit: str = "bytes"
    artifact_size_bytes: int
    artifact_size_provenance: NumericFactProvenance = NumericFactProvenance.MEASURED_FACT
    artifact_size_source: str = "measured_gguf_release_file"
    min_ram_bytes: int
    min_ram_provenance: NumericFactProvenance = NumericFactProvenance.CURATED_HEURISTIC
    min_ram_source: str = "curated_catalog_policy_v2026.10.1"
    recommended_ram_bytes: int
    recommended_ram_provenance: NumericFactProvenance = NumericFactProvenance.CURATED_HEURISTIC
    recommended_ram_source: str = "curated_catalog_policy_v2026.10.1"
    accelerator_required: bool = False  # Hard requirement only if True; CPU-capable otherwise
    min_vram_bytes: Optional[int] = None
    recommended_vram_bytes: Optional[int] = None
    min_vram_bytes_if_gpu_required: Optional[int] = None
    supported_backends: List[str] = Field(
        default_factory=lambda: ["cpu", "cuda", "metal", "rocm", "vulkan"]
    )
    supported_architectures: List[str] = Field(
        default_factory=lambda: ["x86_64", "arm64", "aarch64"]
    )
    context_window_limit: int = 32768
    context_window_provenance: NumericFactProvenance = NumericFactProvenance.DECLARED_FACT
    kv_metadata: Optional[ModelKVArchitectureMetadata] = None
    capabilities: Dict[str, TriStateBool] = Field(default_factory=dict)
    quality_rank: int = 1  # Curated capability rank [1..10], strictly integer
    quality_rank_provenance: NumericFactProvenance = NumericFactProvenance.CURATED_POLICY
    quality_rank_source: str = "Agent Engine Curated Quality Policy v2026.10.1"
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
    resource_captured_at: float = 0.0
    resource_stale: bool = False
    warning: Optional[str] = None
