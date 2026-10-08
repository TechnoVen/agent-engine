"""core/router/models.py

Domain models and schemas for Quality/Cost/Latency Routing Objective.
Part of Milestone R3 Task R3.9 (Quality/cost/latency routing objective).

Design Invariants:
1. Strict Constrained Optimization: Optimization never overrides hard constraints (capabilities, privacy, availability).
2. Evidence-Based Quality: Derived from empirical task-family benchmarks or curated policies; zero brand or size bias.
3. Unit-Aware Pricing & True Zero: Distinguishes measured tokens and unit prices; free local models have factual price = 0; missing is UNKNOWN, never 0.
4. Latency Observation: Prefers live telemetry when fresh/reliable; missing is UNKNOWN, never fastest.
5. Health Signal: Unavailable/Auth-failed excluded; Degraded receives explicit utility penalty.
6. Metric Normalization: Comparable metrics mapped to bounded utilities in [0.0, 1.0].
7. Deterministic Tie-Breaking: Strict multi-stage tie-breaker invariant under candidate array shuffling.
8. Zero Secret Leakage: Never includes credentials, tokens, or auth headers in traces or decisions.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from core.execution.models import RoutingTier
from core.model_registry.models import ModelIdentity
from core.providers.models import ProviderHealthStatus


class RoutingObjectiveProfile(str, Enum):
    """Canonical objective profiles for multi-attribute routing optimization."""

    BALANCED = "balanced"
    QUALITY_FIRST = "quality_first"
    COST_FIRST = "cost_first"
    LATENCY_FIRST = "latency_first"


class RoutingObjective(BaseModel):
    """Configured objective weights and thresholds for model selection."""

    profile: RoutingObjectiveProfile = RoutingObjectiveProfile.BALANCED
    w_quality: float = 0.35
    w_cost: float = 0.30
    w_latency: float = 0.20
    w_health: float = 0.15

    # Optional hard cutoffs
    min_quality: Optional[float] = None
    max_cost_dollars: Optional[float] = None
    max_latency_ms: Optional[float] = None

    # Normalization scaling constants
    cost_norm_ceiling_usd: float = 0.05  # $0.05 per request is utility 0.0
    latency_norm_ceiling_ms: float = 5000.0  # 5000ms is utility 0.0

    @classmethod
    def from_profile(
        cls,
        profile: RoutingObjectiveProfile | str,
        min_quality: Optional[float] = None,
        max_cost_dollars: Optional[float] = None,
        max_latency_ms: Optional[float] = None,
    ) -> RoutingObjective:
        """Create a RoutingObjective initialized with canonical profile weights."""
        if isinstance(profile, str):
            clean_prof = profile.strip().lower()
            try:
                prof_enum = RoutingObjectiveProfile(clean_prof)
            except ValueError:
                prof_enum = RoutingObjectiveProfile.BALANCED
        else:
            prof_enum = profile

        if prof_enum == RoutingObjectiveProfile.QUALITY_FIRST:
            return cls(
                profile=prof_enum,
                w_quality=0.60,
                w_cost=0.15,
                w_latency=0.15,
                w_health=0.10,
                min_quality=min_quality,
                max_cost_dollars=max_cost_dollars,
                max_latency_ms=max_latency_ms,
            )
        elif prof_enum == RoutingObjectiveProfile.COST_FIRST:
            return cls(
                profile=prof_enum,
                w_quality=0.20,
                w_cost=0.55,
                w_latency=0.15,
                w_health=0.10,
                min_quality=min_quality,
                max_cost_dollars=max_cost_dollars,
                max_latency_ms=max_latency_ms,
            )
        elif prof_enum == RoutingObjectiveProfile.LATENCY_FIRST:
            return cls(
                profile=prof_enum,
                w_quality=0.20,
                w_cost=0.15,
                w_latency=0.55,
                w_health=0.10,
                min_quality=min_quality,
                max_cost_dollars=max_cost_dollars,
                max_latency_ms=max_latency_ms,
            )
        else:  # BALANCED
            return cls(
                profile=RoutingObjectiveProfile.BALANCED,
                w_quality=0.35,
                w_cost=0.30,
                w_latency=0.20,
                w_health=0.15,
                min_quality=min_quality,
                max_cost_dollars=max_cost_dollars,
                max_latency_ms=max_latency_ms,
            )


class QualityEvidence(BaseModel):
    """Verifiable evidence supporting candidate quality estimation."""

    score: Optional[float] = None  # [0.0, 1.0]
    task_family: str = "general"
    eval_id: Optional[str] = None
    version: Optional[str] = None
    sample_size: Optional[int] = None
    updated_at: Optional[float] = None
    provenance: str = "unknown"  # "eval_benchmark", "curated_policy", "catalog", "unknown"
    confidence: float = 0.0  # [0.0, 1.0]

    @property
    def is_known(self) -> bool:
        return self.score is not None and self.provenance != "unknown"


class CostEvidence(BaseModel):
    """Verifiable evidence supporting request-level cost estimation."""

    expected_cost_usd: Optional[float] = None
    input_tokens: int = 1000
    output_tokens: int = 500
    input_cost_per_1m: Optional[float] = None
    output_cost_per_1m: Optional[float] = None
    is_free: bool = False
    provenance: str = "unknown"  # "free_local", "measured_tokens_unit_pricing", "unknown"

    @property
    def is_known(self) -> bool:
        return self.is_free or (self.expected_cost_usd is not None and self.provenance != "unknown")


class LatencyEvidence(BaseModel):
    """Verifiable evidence supporting latency estimation."""

    latency_ms: Optional[float] = None
    p50_ms: Optional[float] = None
    sample_count: int = 0
    observed_at: Optional[float] = None
    provenance: str = "unknown"  # "observed_telemetry", "catalog_baseline", "unknown"
    confidence: float = 0.0

    @property
    def is_known(self) -> bool:
        return self.latency_ms is not None and self.provenance != "unknown"


class HealthEvidence(BaseModel):
    """Operational health signal for candidate provider."""

    status: ProviderHealthStatus = ProviderHealthStatus.HEALTHY
    is_degraded: bool = False
    degraded_reason: Optional[str] = None
    circuit_state: str = "CLOSED"
    checked_at: Optional[float] = None


class RoutingMetrics(BaseModel):
    """Aggregated raw metrics for a routing candidate."""

    quality: QualityEvidence = Field(default_factory=QualityEvidence)
    cost: CostEvidence = Field(default_factory=CostEvidence)
    latency: LatencyEvidence = Field(default_factory=LatencyEvidence)
    health: HealthEvidence = Field(default_factory=HealthEvidence)


class RoutingScore(BaseModel):
    """Normalized multi-attribute utility calculation."""

    quality_utility: float  # [0.0, 1.0]
    cost_utility: float  # [0.0, 1.0]
    latency_utility: float  # [0.0, 1.0]
    health_utility: float  # [0.0, 1.0]
    uncertainty_penalty: float = 0.0  # [0.0, 1.0] deducted for missing/unknown data
    total_score: float  # [0.0, 1.0]
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    explanation: str = ""


class RoutingCandidate(BaseModel):
    """Evaluated candidate model within the multi-objective optimization pipeline."""

    identity: ModelIdentity
    provider_id: str
    model_id: str
    routing_tier: RoutingTier
    metrics: RoutingMetrics
    score: Optional[RoutingScore] = None
    eligible: bool = True
    rejection_reasons: List[str] = Field(default_factory=list)

    @property
    def canonical_id(self) -> str:
        return self.identity.canonical_id


class RoutingRejection(BaseModel):
    """Detailed record of candidate exclusion during hard constraints phase."""

    model_id: str
    provider_id: str
    stage: str  # "CAPABILITY", "PRIVACY", "HEALTH", "BUDGET", "OBJECTIVE"
    reason: str


class RoutingDecision(BaseModel):
    """Authoritative explainable outcome of multi-objective routing optimization."""

    execution_id: Optional[str] = None
    selected_model: Optional[ModelIdentity] = None
    provider_id: Optional[str] = None
    routing_tier: Optional[RoutingTier] = None
    objective_profile: str
    objective_weights: Dict[str, float]
    effective_privacy_class: str
    policy_source: str

    eligible_candidates: List[RoutingCandidate] = Field(default_factory=list)
    rejected_candidates: List[RoutingRejection] = Field(default_factory=list)
    selected_candidate: Optional[RoutingCandidate] = None

    final_score: Optional[float] = None
    decision_reason: str = ""
    tie_break_applied: bool = False
    tie_break_reason: Optional[str] = None
    incomplete_data_warning: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)

    @property
    def fallback_chain(self) -> List[str]:
        """Ordered list of fallback provider targets from eligible ranking."""
        seen = set()
        res = []
        if self.provider_id:
            seen.add(self.provider_id)
        for c in self.eligible_candidates:
            if c.provider_id not in seen:
                seen.add(c.provider_id)
                res.append(c.provider_id)
        return res

    @property
    def winner(self) -> Optional[RoutingCandidate]:
        return self.selected_candidate

    @property
    def candidate_metrics(self) -> List[RoutingCandidate]:
        return self.eligible_candidates

    @property
    def eligible_candidates_count(self) -> int:
        return len(self.eligible_candidates)

    @property
    def rejections(self) -> List[RoutingRejection]:
        return self.rejected_candidates

    @property
    def privacy_rejections(self) -> List[RoutingRejection]:
        return [r for r in self.rejected_candidates if r.stage == "PRIVACY"]

    @property
    def selection_reason(self) -> str:
        return self.decision_reason
