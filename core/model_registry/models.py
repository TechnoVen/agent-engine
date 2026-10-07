"""core/model_registry/models.py

Canonical Model Data Structures and Capability Schemas for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).

Design Invariants:
1. Structured Model Identity: ModelIdentity(provider_id, model_id) avoids delimiter parsing ambiguities.
   Versioned serialization (v1:provider:model) supports colons, slashes, spaces, and Unicode.
2. 3-Valued Logic: Capabilities and privacy facts use TriStateBool (TRUE, FALSE, UNKNOWN).
   UNKNOWN cannot satisfy hard requirements.
3. Provenance Precedence: USER_OVERRIDE (4) > LOCAL_INSPECTED (3) > REMOTE_DISCOVERY (2) > BUILTIN (1).
   Field-level provenance is preserved and never converted to provider-certified truth.
4. Latency Separation: Catalog baseline classification is strictly preserved separately from live telemetry.
5. Pricing Discipline: Unit-explicit (PER_1M_TOKENS) and time-aware; missing pricing is UNKNOWN, never zero.
6. Non-Routing Candidate Evaluation: Eligibility + explainable rejection reasons without premature ranking.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional, Union
import urllib.parse

from pydantic import BaseModel, Field, field_validator


class TriStateBool(str, Enum):
    """3-Valued logic for model capabilities and privacy facts.

    Invariants:
    - TRUE: Confirmed supported / true.
    - FALSE: Confirmed unsupported / false.
    - UNKNOWN: Unverified or indeterminate; CANNOT satisfy hard requirements.
    """

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    @classmethod
    def from_bool(cls, val: Optional[Union[bool, TriStateBool]]) -> TriStateBool:
        if val is True or val == TriStateBool.TRUE:
            return cls.TRUE
        if val is False or val == TriStateBool.FALSE:
            return cls.FALSE
        return cls.UNKNOWN

    def satisfies(self, required: bool) -> bool:
        """Check if this capability/fact satisfies a requirement.

        UNKNOWN fails hard requirements (required=True).
        """
        if required:
            return self == TriStateBool.TRUE
        return True


class ExecutionLocation(str, Enum):
    """Execution location of model inference."""

    LOCAL = "local"
    REMOTE = "remote"
    UNKNOWN = "unknown"


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
    """Categorical latency classification for model catalog baselines."""

    FAST = "fast"  # < 1000ms TTFT
    MEDIUM = "medium"  # 1000ms - 3000ms
    SLOW = "slow"  # 3000ms - 8000ms
    REASONING = "reasoning"  # Deep thinking / iterative reasoning models (> 8000ms)
    UNKNOWN = "unknown"


class PriceUnit(str, Enum):
    """Standardized price unit."""

    PER_1M_TOKENS = "per_1m_tokens"
    PER_1K_TOKENS = "per_1k_tokens"


class PriceDirection(str, Enum):
    """Token price direction."""

    INPUT = "input"
    OUTPUT = "output"


class TokenPrice(BaseModel):
    """Unit-explicit and time-aware token price."""

    amount: float  # Exactly 0.0 means free; missing price is represented by None profile
    currency: str = "USD"
    unit: PriceUnit = PriceUnit.PER_1M_TOKENS
    direction: PriceDirection
    source: ProvenanceType = ProvenanceType.BUILTIN
    effective_at: float = Field(default_factory=time.time)


class ObservedLatencyMetrics(BaseModel):
    """Live observed telemetry metrics separate from catalog baseline classification."""

    p50_ms: Optional[float] = None
    p90_ms: Optional[float] = None
    p99_ms: Optional[float] = None
    last_observed_ms: Optional[float] = None
    sample_count: int = 0
    observed_at: Optional[float] = None


class LatencyProfile(BaseModel):
    """Latency representation keeping static catalog baseline separate from live telemetry."""

    catalog_latency_class: LatencyClass = LatencyClass.MEDIUM
    catalog_latency_ms: Optional[float] = None
    observed_metrics: Optional[ObservedLatencyMetrics] = None

    def __init__(
        self,
        latency_class: Optional[LatencyClass] = None,
        catalog_latency_ms: Optional[float] = None,
        **data: Any,
    ):
        if latency_class is not None and "catalog_latency_class" not in data:
            data["catalog_latency_class"] = latency_class
        if catalog_latency_ms is not None:
            data["catalog_latency_ms"] = catalog_latency_ms
        super().__init__(**data)

    @property
    def latency_class(self) -> LatencyClass:
        """Catalog latency class preserved without destructive live mutation."""
        return self.catalog_latency_class

    @property
    def effective_latency_ms(self) -> Optional[float]:
        """Return observed latency if available, else catalog baseline."""
        if self.observed_metrics and self.observed_metrics.last_observed_ms is not None:
            return self.observed_metrics.last_observed_ms
        return self.catalog_latency_ms


class CapabilityFact(BaseModel):
    """Fine-grained capability fact preserving explicit provenance."""

    value: TriStateBool = TriStateBool.UNKNOWN
    source: ProvenanceType = ProvenanceType.BUILTIN
    updated_at: float = Field(default_factory=time.time)
    verified: bool = False


class ModelCapabilities(BaseModel):
    """Fine-grained capability dimensions evaluated with 3-valued logic and per-field provenance."""

    reasoning: TriStateBool = TriStateBool.UNKNOWN
    coding: TriStateBool = TriStateBool.UNKNOWN
    vision: TriStateBool = TriStateBool.UNKNOWN
    tools: TriStateBool = TriStateBool.UNKNOWN
    structured_output: TriStateBool = TriStateBool.UNKNOWN
    embeddings: TriStateBool = TriStateBool.UNKNOWN
    streaming: TriStateBool = TriStateBool.UNKNOWN
    custom_capabilities: Dict[str, Any] = Field(default_factory=dict)
    facts: Dict[str, CapabilityFact] = Field(default_factory=dict)

    def get_fact(self, capability_name: str) -> CapabilityFact:
        """Retrieve capability fact with provenance metadata."""
        if capability_name in self.facts:
            return self.facts[capability_name]
        val = getattr(self, capability_name, None)
        if isinstance(val, TriStateBool):
            return CapabilityFact(value=val, source=ProvenanceType.BUILTIN)
        return CapabilityFact(value=TriStateBool.UNKNOWN, source=ProvenanceType.BUILTIN)

    def set_fact(
        self,
        capability_name: str,
        value: TriStateBool,
        source: ProvenanceType,
        verified: bool = False,
    ) -> None:
        """Set capability value and record its provenance."""
        if hasattr(self, capability_name) and capability_name not in (
            "custom_capabilities",
            "facts",
        ):
            setattr(self, capability_name, value)
        else:
            self.custom_capabilities[capability_name] = value

        self.facts[capability_name] = CapabilityFact(
            value=value,
            source=source,
            updated_at=time.time(),
            verified=verified,
        )

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
    """Privacy and data sovereignty properties with 3-valued truth discipline."""

    execution_location: ExecutionLocation = ExecutionLocation.UNKNOWN
    data_leaves_device: TriStateBool = TriStateBool.UNKNOWN
    zero_data_retention: TriStateBool = TriStateBool.UNKNOWN
    compliance_tags: List[str] = Field(default_factory=list)
    provenance: ProvenanceType = ProvenanceType.BUILTIN
    authoritative: bool = False

    def __init__(
        self,
        is_local: Optional[Union[bool, TriStateBool]] = None,
        data_leaves_device: Optional[Union[bool, TriStateBool]] = None,
        zero_data_retention: Optional[Union[bool, TriStateBool]] = None,
        **data: Any,
    ):
        if is_local is not None and "execution_location" not in data:
            if is_local is True or is_local == TriStateBool.TRUE:
                data["execution_location"] = ExecutionLocation.LOCAL
            elif is_local is False or is_local == TriStateBool.FALSE:
                data["execution_location"] = ExecutionLocation.REMOTE
            else:
                data["execution_location"] = ExecutionLocation.UNKNOWN

        if data_leaves_device is not None and "data_leaves_device" not in data:
            if isinstance(data_leaves_device, bool):
                data["data_leaves_device"] = TriStateBool.from_bool(data_leaves_device)
            else:
                data["data_leaves_device"] = data_leaves_device

        if zero_data_retention is not None and "zero_data_retention" not in data:
            if isinstance(zero_data_retention, bool):
                data["zero_data_retention"] = TriStateBool.from_bool(zero_data_retention)
            else:
                data["zero_data_retention"] = zero_data_retention

        super().__init__(**data)

    @property
    def is_local(self) -> TriStateBool:
        if self.execution_location == ExecutionLocation.LOCAL:
            return TriStateBool.TRUE
        elif self.execution_location == ExecutionLocation.REMOTE:
            return TriStateBool.FALSE
        return TriStateBool.UNKNOWN


class PricingProfile(BaseModel):
    """Token pricing metadata with explicit units and freshness timestamp."""

    input_price: Optional[TokenPrice] = None
    output_price: Optional[TokenPrice] = None
    is_free: bool = False  # e.g., local models
    pricing_updated_at: Optional[float] = None

    def __init__(
        self,
        input_cost_per_million: Optional[float] = None,
        output_cost_per_million: Optional[float] = None,
        **data: Any,
    ):
        if input_cost_per_million is not None and "input_price" not in data:
            data["input_price"] = TokenPrice(
                amount=input_cost_per_million,
                direction=PriceDirection.INPUT,
                unit=PriceUnit.PER_1M_TOKENS,
            )
        if output_cost_per_million is not None and "output_price" not in data:
            data["output_price"] = TokenPrice(
                amount=output_cost_per_million,
                direction=PriceDirection.OUTPUT,
                unit=PriceUnit.PER_1M_TOKENS,
            )
        super().__init__(**data)

    @property
    def input_cost_per_million(self) -> Optional[float]:
        if self.is_free:
            return 0.0
        if self.input_price is not None:
            if self.input_price.unit == PriceUnit.PER_1M_TOKENS:
                return self.input_price.amount
            elif self.input_price.unit == PriceUnit.PER_1K_TOKENS:
                return self.input_price.amount * 1000.0
        return None

    @property
    def output_cost_per_million(self) -> Optional[float]:
        if self.is_free:
            return 0.0
        if self.output_price is not None:
            if self.output_price.unit == PriceUnit.PER_1M_TOKENS:
                return self.output_price.amount
            elif self.output_price.unit == PriceUnit.PER_1K_TOKENS:
                return self.output_price.amount * 1000.0
        return None


class ModelIdentity(BaseModel):
    """Structured identity decoupling provider from model identifier.

    Handles model identifiers containing colons, slashes, spaces, and Unicode.
    """

    provider_id: str
    model_id: str

    @property
    def canonical_id(self) -> str:
        """Display canonical identifier 'provider_id:model_id'."""
        return f"{self.provider_id}:{self.model_id}"

    def to_serialized_id(self) -> str:
        """Explicit versioned round-trippable serialized format."""
        return f"v1:{urllib.parse.quote(self.provider_id, safe='')}:{urllib.parse.quote(self.model_id, safe='')}"

    @classmethod
    def from_serialized_id(cls, s: str) -> ModelIdentity:
        return parse_model_identifier(s)

    def __str__(self) -> str:
        return self.canonical_id

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ModelIdentity):
            return self.provider_id == other.provider_id and self.model_id == other.model_id
        return False

    def __hash__(self) -> int:
        return hash((self.provider_id, self.model_id))


def parse_model_identifier(raw: Union[str, ModelIdentity]) -> ModelIdentity:
    """Parse a model identifier into a structured ModelIdentity.

    Parsing Rules:
    1. If already ModelIdentity: return unchanged.
    2. Versioned format 'v1:provider:model': split into exactly 3 parts using split(':', 2)
       and URL-unquote components.
    3. Compact format 'provider:model': split on the FIRST colon only using split(':', 1).
       Never uses unrestricted value.split(':').
    """
    if isinstance(raw, ModelIdentity):
        return raw
    clean = str(raw).strip()
    if clean.startswith("v1:"):
        parts = clean.split(":", 2)
        if len(parts) != 3:
            raise ValueError(
                f"Malformed v1 model identifier '{raw}': expected 'v1:provider_id:model_id'"
            )
        pid = urllib.parse.unquote(parts[1]).strip().lower()
        mid = urllib.parse.unquote(parts[2]).strip()
        if not pid or not mid:
            raise ValueError(f"Invalid model identifier in '{raw}': empty provider or model ID")
        return ModelIdentity(provider_id=pid, model_id=mid)

    if ":" not in clean:
        raise ValueError(
            f"Invalid scoped model identifier '{raw}': expected 'provider_id:model_id'"
        )

    parts = clean.split(":", 1)
    pid = parts[0].strip().lower()
    mid = parts[1].strip()
    if not pid or not mid:
        raise ValueError(
            f"Invalid scoped model identifier '{raw}': neither provider_id nor model_id may be empty"
        )
    return ModelIdentity(provider_id=pid, model_id=mid)


class ModelDefinition(BaseModel):
    """Canonical model registration record indexed by structured ModelIdentity."""

    identity: ModelIdentity
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

    def __init__(self, **data: Any):
        # Support ergonomic direct provider_id and model_id arguments
        if "identity" not in data and "provider_id" in data and "model_id" in data:
            data["identity"] = ModelIdentity(
                provider_id=data.pop("provider_id"),
                model_id=data.pop("model_id"),
            )
        super().__init__(**data)

    @property
    def provider_id(self) -> str:
        return self.identity.provider_id

    @provider_id.setter
    def provider_id(self, v: str) -> None:
        self.identity = ModelIdentity(
            provider_id=v.strip().lower(), model_id=self.identity.model_id
        )

    @property
    def model_id(self) -> str:
        return self.identity.model_id

    @property
    def canonical_id(self) -> str:
        """Return canonical display identity 'provider_id:model_id'."""
        return self.identity.canonical_id

    def to_serialized_id(self) -> str:
        """Return versioned serialized identity."""
        return self.identity.to_serialized_id()

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
    """Result container evaluating a ModelDefinition against ModelRequirements.

    Invariants:
    - Score is strictly a deterministic metadata completeness metric [0.0, 1.0].
    - It does not rank or select a winner among eligible candidates.
    """

    canonical_id: str
    provider_id: str
    model_id: str
    model_definition: ModelDefinition
    eligible: bool
    rejection_reasons: List[str] = Field(default_factory=list)
    score: float = 0.0
