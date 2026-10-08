"""Domain models for Cost-Per-Success (CPS) and Attempt/Task Economics (Task R3.10).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/ROADMAP.md (R3.10), docs/STATUS.md
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import time
from typing import Any, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.model_registry.models import ModelIdentity, parse_model_identifier


class Money(BaseModel):
    """Canonical exact monetary representation for Agent Engine economics.

    Stores currency amounts as exact integer micros (1 USD = 1,000,000 micros)
    to eliminate floating-point drift across large datasets.
    """

    model_config = ConfigDict(frozen=True)

    amount_micros: int = 0
    currency: str = "USD"

    @classmethod
    def from_usd(cls, usd: float | Decimal | int | str) -> Money:
        """Create a Money object from a USD amount with exact half-up rounding to micros."""
        if isinstance(usd, (float, int)):
            d = Decimal(str(usd))
        elif isinstance(usd, str):
            d = Decimal(usd.strip())
        else:
            d = usd
        micros = int((d * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return cls(amount_micros=micros, currency="USD")

    @classmethod
    def from_micros(cls, micros: int, currency: str = "USD") -> Money:
        """Create a Money object from integer micros."""
        if currency.upper() != "USD":
            raise ValueError(f"Unsupported currency '{currency}'; S1 requires 'USD'")
        return cls(amount_micros=int(micros), currency=currency.upper())

    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        """Create a zero-amount Money instance."""
        return cls(amount_micros=0, currency=currency.upper())

    @property
    def as_decimal(self) -> Decimal:
        """Return the exact decimal representation in currency units."""
        return Decimal(self.amount_micros) / Decimal(1_000_000)

    @property
    def as_usd(self) -> float:
        """Return the float representation in USD."""
        return float(self.as_decimal)

    def to_usd(self) -> float:
        """Return the float representation in USD."""
        return self.as_usd

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: cannot add {self.currency} and {other.currency}")
        return Money(amount_micros=self.amount_micros + other.amount_micros, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(
                f"Currency mismatch: cannot subtract {other.currency} from {self.currency}"
            )
        return Money(amount_micros=self.amount_micros - other.amount_micros, currency=self.currency)

    def __mul__(self, factor: int | float | Decimal) -> Money:
        if isinstance(factor, (int, float)):
            f = Decimal(str(factor))
        elif isinstance(factor, Decimal):
            f = factor
        else:
            return NotImplemented
        new_micros = int(
            (Decimal(self.amount_micros) * f).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        return Money(amount_micros=new_micros, currency=self.currency)

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(
                f"Currency mismatch: cannot compare {self.currency} and {other.currency}"
            )
        return self.amount_micros < other.amount_micros

    def __le__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(
                f"Currency mismatch: cannot compare {self.currency} and {other.currency}"
            )
        return self.amount_micros <= other.amount_micros

    def __gt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(
                f"Currency mismatch: cannot compare {self.currency} and {other.currency}"
            )
        return self.amount_micros > other.amount_micros

    def __ge__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(
                f"Currency mismatch: cannot compare {self.currency} and {other.currency}"
            )
        return self.amount_micros >= other.amount_micros

    def __repr__(self) -> str:
        return f"Money({self.as_decimal:.6f} {self.currency})"


class TaskOutcome(str, Enum):
    """Observable outcome of a task attempt or logical task."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class OutcomeSource(str, Enum):
    """Canonical trusted evaluator or source producing an outcome."""

    DETERMINISTIC_VERIFIER = "DETERMINISTIC_VERIFIER"
    GOLDEN_EVAL = "GOLDEN_EVAL"
    STRUCTURED_VALIDATOR = "STRUCTURED_VALIDATOR"
    HUMAN_ACCEPTANCE = "HUMAN_ACCEPTANCE"
    HUMAN_REJECTION = "HUMAN_REJECTION"
    OTHER_TRUSTED_EVALUATOR = "OTHER_TRUSTED_EVALUATOR"
    UNKNOWN = "UNKNOWN"


class EvidenceSource(str, Enum):
    """Origin environment of the economic evidence."""

    GOLDEN_EVAL = "GOLDEN_EVAL"
    PRODUCTION_OBSERVATION = "PRODUCTION_OBSERVATION"
    BENCHMARK_RUN = "BENCHMARK_RUN"


class OutcomeEvidence(BaseModel):
    """Minimized, typed verification evidence supporting a task outcome.

    Strict Invariant (Directive 12): Contains zero prompt text, response bodies,
    credentials, or personal user data.
    """

    outcome: TaskOutcome
    outcome_source: OutcomeSource = OutcomeSource.UNKNOWN
    evaluator_id: Optional[str] = None
    evaluator_version: Optional[str] = None
    observed_at: float = Field(default_factory=time.time)
    reason_code: Optional[str] = None
    artifact_hash: Optional[str] = None


class HumanCorrectionEvent(BaseModel):
    """Explicit human intervention event (Directive 7 & 11).

    Invariant: Must originate from an explicit user action (e.g. reject,
    request regeneration, manual edit approval), never inferred from timing,
    continuation of conversation, or length of execution.
    """

    correction_event_id: str = Field(default_factory=lambda: f"corr_{uuid.uuid4().hex[:12]}")
    task_id: str
    logical_task_id: Optional[str] = None
    source: str = "trusted_user_action"
    trusted_actor: str = "user"
    correction_type: str  # e.g. "explicit_reject", "request_regeneration", "manual_override"
    observed_at: float = Field(default_factory=time.time)
    reason: Optional[str] = None
    reason_code: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if not self.logical_task_id:
            self.logical_task_id = self.task_id


class AttemptEconomicsRecord(BaseModel):
    """Economics of a single provider/model invocation attempt (Directive 2)."""

    attempt_id: str = Field(default_factory=lambda: f"att_{uuid.uuid4().hex[:12]}")
    execution_id: str
    logical_task_id: str
    model_identity: ModelIdentity
    provider_id: str
    cost: Money
    prompt_tokens: int = 0
    completion_tokens: int = 0
    outcome: TaskOutcome = TaskOutcome.UNKNOWN
    outcome_evidence: Optional[OutcomeEvidence] = None
    is_fallback: bool = False
    is_retry: bool = False
    is_synthetic: bool = False
    attempt_index: int = 0
    created_at: float = Field(default_factory=time.time)


class LogicalTaskEconomicsRecord(BaseModel):
    """Economics of an entire multi-attempt chain serving one user task (Directive 2 & 4).

    Invariant: 1 task with 4 attempts = 1 logical task, 4 attempts.
    Attribution is made to the initial routing decision.
    """

    logical_task_id: str
    task_family: str = "general"
    initial_routing_decision: Optional[str] = None
    initial_model_identity: ModelIdentity
    initial_provider_id: str
    routing_policy_version: str = "v1"
    fallback_policy_version: str = "v1"
    effective_privacy_class: str = "ANY_CONFIGURED"
    evaluator_id: Optional[str] = None
    evaluator_version: Optional[str] = None
    evidence_source: EvidenceSource = EvidenceSource.PRODUCTION_OBSERVATION
    attempt_ids: List[str] = Field(default_factory=list)
    attempts: List[AttemptEconomicsRecord] = Field(default_factory=list)
    total_cost: Money = Field(default_factory=lambda: Money(amount_micros=0, currency="USD"))
    final_outcome: TaskOutcome = TaskOutcome.UNKNOWN
    correction_event: Optional[HumanCorrectionEvent] = None
    currency: str = "USD"
    created_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None

    @field_validator("effective_privacy_class", mode="before")
    @classmethod
    def _normalize_privacy_class_task(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.upper()
        if hasattr(v, "value"):
            return str(v.value).upper()
        return str(v).upper()

    def add_attempt(self, attempt: AttemptEconomicsRecord) -> None:
        """Add an attempt to this logical task chain and recompute total chain cost."""
        if attempt.attempt_id not in self.attempt_ids:
            self.attempt_ids.append(attempt.attempt_id)
            self.attempts.append(attempt)
        # Sum total cost exactly using Money
        self.total_cost = self.total_cost + attempt.cost
        if attempt.outcome_evidence:
            self.final_outcome = attempt.outcome_evidence.outcome
        elif attempt.outcome != TaskOutcome.UNKNOWN:
            self.final_outcome = attempt.outcome


class EconomicsCohortKey(BaseModel):
    """Multidimensional key defining an isolated economics cohort (Directive 2 & 5).

    Invariant: Incompatible privacy classes, evaluator versions, policy versions,
    or different initial ModelIdentities NEVER merge into the same cohort.
    """

    model_config = ConfigDict(frozen=True)

    initial_model_identity: ModelIdentity
    task_family: str
    evaluator_id: Optional[str] = None
    evaluator_version: str = "v1"
    routing_policy_version: str = "v1"
    fallback_policy_version: str = "v1"
    effective_privacy_class: str = "ANY_CONFIGURED"
    evidence_source: EvidenceSource = EvidenceSource.PRODUCTION_OBSERVATION

    def __init__(
        self,
        initial_model_identity: Optional[ModelIdentity] = None,
        initial_model_identity_str: Optional[str] = None,
        **data: Any,
    ) -> None:
        if initial_model_identity is None and initial_model_identity_str is not None:
            initial_model_identity = parse_model_identifier(initial_model_identity_str)
        if initial_model_identity is not None and "initial_model_identity" not in data:
            data["initial_model_identity"] = initial_model_identity
        super().__init__(**data)

    @property
    def initial_model_identity_str(self) -> str:
        return self.initial_model_identity.canonical_id

    @field_validator("effective_privacy_class", mode="before")
    @classmethod
    def _normalize_privacy_class_key(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.upper()
        if hasattr(v, "value"):
            return str(v.value).upper()
        return str(v).upper()


class EvidenceSufficiencyStatus(str, Enum):
    """Status indicating whether cohort evidence satisfies policy thresholds."""

    SUFFICIENT_EVIDENCE = "SUFFICIENT_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_SUCCESS_EVIDENCE = "NO_SUCCESS_EVIDENCE"


class SufficiencyPolicy(BaseModel):
    """Deterministic, policy-versioned threshold rules over evaluable logical tasks (Directive 3 & 8).

    Evaluable tasks are logical tasks with definitive verified outcomes:
    SUCCESS or FAILURE (excluding UNKNOWN and PARTIAL which lack definitive truth).
    """

    policy_version: str = "v1_min5_evaluable5_success1"
    min_logical_tasks: int = 5
    min_evaluable_tasks: int = 5
    min_verified_successes: int = 1
    allow_partial_as_evaluable: bool = False

    def evaluate(
        self,
        logical_tasks_count: int,
        verified_successes: int,
        failures_count: int = 0,
        partials_count: int = 0,
        unknowns_count: int = 0,
    ) -> EvidenceSufficiencyStatus:
        """Evaluate sufficiency status over logical task aggregates."""
        if verified_successes == 0:
            return EvidenceSufficiencyStatus.NO_SUCCESS_EVIDENCE

        if logical_tasks_count < self.min_logical_tasks:
            return EvidenceSufficiencyStatus.INSUFFICIENT_EVIDENCE

        evaluable_count = verified_successes + failures_count
        if self.allow_partial_as_evaluable:
            evaluable_count += partials_count

        if evaluable_count < self.min_evaluable_tasks:
            return EvidenceSufficiencyStatus.INSUFFICIENT_EVIDENCE

        if verified_successes < self.min_verified_successes:
            return EvidenceSufficiencyStatus.INSUFFICIENT_EVIDENCE

        return EvidenceSufficiencyStatus.SUFFICIENT_EVIDENCE


class ModelEconomicsSummary(BaseModel):
    """Complete summary of economics for a model cohort (Directive 2, 3, 7, 8, 10)."""

    cohort_key: EconomicsCohortKey
    initial_model_identity: ModelIdentity
    initial_provider_id: str
    task_family: str
    logical_tasks_count: int
    total_attempts_count: int
    verified_successes: int
    failures: int
    partials: int
    unknowns: int
    evaluable_tasks_count: int = 0
    known_correction_count: int = 0
    total_cost: Money
    mean_task_cost: Money
    observed_cost_per_verified_success: Optional[Money] = None
    expected_cost_per_success: Optional[Money] = None
    expected_cost_per_success_provenance: Optional[str] = None
    estimator_version: str = "v1_empirical_cohort"
    evidence_window: str = "all_recorded_tasks"
    sufficiency_policy_version: str = "v1_min5_evaluable5_success1"
    status: EvidenceSufficiencyStatus
    currency: str = "USD"
    evaluator_version: str
    routing_policy_version: str
    fallback_policy_version: str
    effective_privacy_class: str
    evidence_source: EvidenceSource
    sample_freshness: Optional[float] = None


class CostPerSuccessEstimate(BaseModel):
    """Empirical cost-per-success estimate exposed to the router (Directive 14)."""

    estimated_cps: Money
    provenance: str = "EMPIRICAL_ESTIMATE"
    cohort_key: EconomicsCohortKey
    evaluator_version: str
    policy_version: str
    sample_count: int
    success_count: int
    status: EvidenceSufficiencyStatus
