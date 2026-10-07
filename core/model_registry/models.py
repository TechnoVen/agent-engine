"""core/model_registry/models.py

Canonical Model Data Structures and Capability Schemas for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).

Design Invariants:
1. Scoped Canonical Identity: Exactly formatted as 'provider_id:model_id'.
2. 3-Valued Logic: Capabilities use TriStateBool (TRUE, FALSE, UNKNOWN).
   CRITICAL: UNKNOWN cannot satisfy hard requirements.
3. Decoupled from Provider Transport: Model capabilities describe intelligence properties,
   context windows, pricing, latency, and hardware constraints, strictly separated from
   underlying HTTP/network adapter lifecycle.
4. Comprehensive Dimensions: Reasoning, coding, vision, tools, structured output,
   embeddings, streaming, input/output/total context tokens, price, latency, privacy, hardware.
5. Explainable Eligibility: ModelCandidate records deterministic rejection reasons when filtered.
"""

from __future__ import annotations

from enum import Enum
import re
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

_SCOPED_ID_PATTERN = re.compile(r"^[a-z0-9_\-]+:[a-zA-Z0-9_\.\-:/]+$")


class TriStateBool(str, Enum):
    """3-Valued logic for model capabilities.

    Invariants:
    - TRUE: Capability is confirmed supported.
    - FALSE: Capability is confirmed unsupported.
    - UNKNOWN: Capability status is unverified; CANNOT satisfy hard requirements.
    """

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    @classmethod
    def from_bool(cls, val: Optional[bool]) -> TriStateBool:
        if val is True:
            return cls.TRUE
        if val is False:
            return cls.FALSE
        return cls.UNKNOWN

    def satisfies(self, required: bool) -> bool:
        """Check if this capability state satisfies a requirement.

        UNKNOWN fails hard requirements (required=True).
        """
        if required:
            return self == TriStateBool.TRUE
        return True


class ProvenanceType(str, Enum):
    """Source authority and precedence for model capability definitions.

    Precedence order: USER_OVERRIDE (4) > LOCAL_INSPECTED (3) > REMOTE_DISCOVERY (2) > BUILTIN (1).
    """

    BUILTIN = "builtin"
    REMOTE_DISCOVERY = "remote_discovery"
    LOCAL_INSPECTED = "local_inspected"
    USER_OVERRIDE = "user_override"

    @property
    def precedence(self) -> int:
        levels = {
            ProvenanceType.BUILTIN: 1,
            ProvenanceType.REMOTE_DISCOVERY: 2,
            ProvenanceType.LOCAL_INSPECTED: 3,
            ProvenanceType.USER_OVERRIDE: 4,
        }
        return levels.get(self, 0)


class LatencyClass(str, Enum):
    """Categorical latency classification for routing heuristics."""

    FAST = "fast"  # < 1000ms TTFT
    MEDIUM = "medium"  # 1000ms - 3000ms
    SLOW = "slow"  # 3000ms - 8000ms
    REASONING = "reasoning"  # Deep thinking / iterative reasoning models (> 8000ms)


class ModelCapabilities(BaseModel):
    """Fine-grained capability dimensions evaluated with 3-valued logic."""

    reasoning: TriStateBool = TriStateBool.UNKNOWN
    coding: TriStateBool = TriStateBool.UNKNOWN
    vision: TriStateBool = TriStateBool.UNKNOWN
    tools: TriStateBool = TriStateBool.UNKNOWN
    structured_output: TriStateBool = TriStateBool.UNKNOWN
    embeddings: TriStateBool = TriStateBool.UNKNOWN
    streaming: TriStateBool = TriStateBool.TRUE
    custom_capabilities: Dict[str, Any] = Field(default_factory=dict)

    def satisfies_requirement(
        self, capability_name: str, required_value: bool
    ) -> tuple[bool, Optional[str]]:
        """Evaluate a capability constraint using 3-valued logic.

        Returns (satisfied, failure_reason_if_not).
        """
        state = getattr(self, capability_name, None)
        if state is None:
            state = self.custom_capabilities.get(capability_name, TriStateBool.UNKNOWN)
            if isinstance(state, bool):
                state = TriStateBool.from_bool(state)
            elif not isinstance(state, TriStateBool):
                state = TriStateBool.UNKNOWN

        if not isinstance(state, TriStateBool):
            state = TriStateBool.UNKNOWN

        if not state.satisfies(required_value):
            if state == TriStateBool.UNKNOWN:
                return (
                    False,
                    f"Capability '{capability_name}' is UNKNOWN (cannot satisfy hard requirement)",
                )
            return (
                False,
                f"Missing required capability '{capability_name}' (model capability is FALSE)",
            )
        return (True, None)


class HardwareRequirements(BaseModel):
    """Declarative local hardware constraints for running or loading the model."""

    min_ram_bytes: Optional[int] = None
    min_vram_bytes: Optional[int] = None
    recommended_ram_bytes: Optional[int] = None
    quantization: Optional[str] = None  # e.g., "Q4_K_M", "Q8_0", "FP16"
    parameter_size: Optional[str] = None  # e.g., "3B", "7B", "70B"
    architecture: Optional[str] = None  # e.g., "llama", "qwen2", "mistral"
    context_vram_scaling_factor: float = 1.0


class PrivacyProfile(BaseModel):
    """Privacy and data sovereignty properties."""

    is_local: bool = False
    data_leaves_device: bool = True
    zero_data_retention: Optional[bool] = None
    compliance_tags: List[str] = Field(default_factory=list)


class PricingProfile(BaseModel):
    """Token pricing metadata with units and freshness timestamp."""

    input_cost_per_million: Optional[float] = None  # USD per 1,000,000 input tokens
    output_cost_per_million: Optional[float] = None  # USD per 1,000,000 output tokens
    currency: str = "USD"
    price_updated_at: float = Field(default_factory=time.time)


class LatencyProfile(BaseModel):
    """Latency metrics combining catalog estimates and live telemetry."""

    catalog_latency_ms: Optional[float] = None
    telemetry_latency_ms: Optional[float] = None
    telemetry_updated_at: Optional[float] = None
    latency_class: LatencyClass = LatencyClass.MEDIUM

    @property
    def effective_latency_ms(self) -> Optional[float]:
        if self.telemetry_latency_ms is not None:
            return self.telemetry_latency_ms
        return self.catalog_latency_ms


class ModelDefinition(BaseModel):
    """Canonical model registration record indexed by scoped provider_id:model_id."""

    provider_id: str
    model_id: str
    display_name: str
    description: Optional[str] = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)

    # Distinct context token dimensions
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    max_total_context_tokens: int = 4096

    pricing: PricingProfile = Field(default_factory=PricingProfile)
    latency: LatencyProfile = Field(default_factory=LatencyProfile)
    privacy: PrivacyProfile = Field(default_factory=PrivacyProfile)
    hardware: Optional[HardwareRequirements] = None

    provenance: ProvenanceType = ProvenanceType.BUILTIN
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def canonical_id(self) -> str:
        """Return canonical scoped identity 'provider_id:model_id'."""
        return f"{self.provider_id}:{self.model_id}"

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if not v_clean:
            raise ValueError("provider_id must be non-empty")
        return v_clean

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("model_id must be non-empty")
        return v_clean

    @field_validator("max_total_context_tokens")
    @classmethod
    def validate_total_tokens(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"max_total_context_tokens must be positive, got {v}")
        return v


class ModelRequirements(BaseModel):
    """Declarative criteria for model selection and constraint filtering."""

    # Hard capability constraints (True = must be confirmed TRUE, False/None = ignored)
    require_reasoning: Optional[bool] = None
    require_coding: Optional[bool] = None
    require_vision: Optional[bool] = None
    require_tools: Optional[bool] = None
    require_structured_output: Optional[bool] = None
    require_embeddings: Optional[bool] = None
    require_streaming: Optional[bool] = None

    # Context window constraints
    min_input_tokens: Optional[int] = None
    min_output_tokens: Optional[int] = None
    min_total_tokens: Optional[int] = None

    # Pricing constraints
    max_input_cost_per_million: Optional[float] = None
    max_output_cost_per_million: Optional[float] = None

    # Latency constraints
    max_latency_ms: Optional[float] = None
    allowed_latency_classes: Optional[List[LatencyClass]] = None

    # Privacy constraints
    require_local_only: bool = False
    allow_data_leaves_device: bool = True
    require_zero_retention: bool = False

    # Hardware constraints
    max_available_ram_bytes: Optional[int] = None
    max_available_vram_bytes: Optional[int] = None

    # Provider constraints
    allowed_providers: Optional[List[str]] = None
    excluded_providers: Optional[List[str]] = None

    # Tag and ID filters
    required_tags: List[str] = Field(default_factory=list)


class ModelCandidate(BaseModel):
    """Result container evaluating a ModelDefinition against ModelRequirements."""

    canonical_id: str
    provider_id: str
    model_id: str
    model_definition: ModelDefinition
    eligible: bool
    rejection_reasons: List[str] = Field(default_factory=list)
    score: float = 0.0
