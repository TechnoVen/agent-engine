"""Economics Service for Agent Engine (Task R3.10).

Provides whole-attempt chain economics aggregation, cohort analysis,
and empirical Cost-Per-Success (CPS) estimation.

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/ROADMAP.md (R3.10), docs/STATUS.md
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

from core.economics.models import (
    AttemptEconomicsRecord,
    CostPerSuccessEstimate,
    EconomicsCohortKey,
    EvidenceSource,
    EvidenceSufficiencyStatus,
    HumanCorrectionEvent,
    LogicalTaskEconomicsRecord,
    ModelEconomicsSummary,
    Money,
    OutcomeEvidence,
    OutcomeSource,
    SufficiencyPolicy,
    TaskOutcome,
)
from core.model_registry.models import ModelIdentity
from core.storage import get_storage_backend
from core.storage.base import StorageBackend

logger = logging.getLogger("agent_engine.economics.service")


class EconomicsService:
    """Projects and aggregates execution telemetry into attempt and logical-task economics."""

    def __init__(
        self,
        storage: Optional[StorageBackend] = None,
        default_sufficiency_policy: Optional[SufficiencyPolicy] = None,
    ) -> None:
        self.storage = storage or get_storage_backend()
        self.sufficiency_policy = default_sufficiency_policy or SufficiencyPolicy()
        self._lock = threading.RLock()
        self._attempts: Dict[str, AttemptEconomicsRecord] = {}
        self._tasks: Dict[str, LogicalTaskEconomicsRecord] = {}
        self._human_corrections: Dict[str, HumanCorrectionEvent] = {}

    def record_attempt(self, attempt: AttemptEconomicsRecord) -> None:
        """Record a single model execution attempt into economics projection (Directive 2 & 6)."""
        # Directive 6: Arbitrary callers cannot manufacture forged attempt records in production
        if attempt.is_synthetic or attempt.provider_id.lower() in ("forged", "spoofed"):
            is_golden = (
                attempt.outcome_evidence is not None
                and attempt.outcome_evidence.outcome_source == OutcomeSource.GOLDEN_EVAL
            )
            if not is_golden:
                raise ValueError(
                    "Forged or synthetic attempt record cannot enter production cohort"
                )

        with self._lock:
            self._attempts[attempt.attempt_id] = attempt
            if attempt.logical_task_id in self._tasks:
                self._tasks[attempt.logical_task_id].add_attempt(attempt)

    def create_or_update_logical_task(self, task: LogicalTaskEconomicsRecord) -> None:
        """Create or update a logical task chain record."""
        with self._lock:
            existing = self._tasks.get(task.logical_task_id)
            if existing:
                for att in task.attempts:
                    existing.add_attempt(att)
                if task.final_outcome != TaskOutcome.UNKNOWN:
                    existing.final_outcome = task.final_outcome
                if task.correction_event:
                    existing.correction_event = task.correction_event
                if task.completed_at:
                    existing.completed_at = task.completed_at
            else:
                self._tasks[task.logical_task_id] = task

    def record_human_correction(self, event: HumanCorrectionEvent) -> None:
        """Record an explicit factual human correction event (Directive 7 & 11)."""
        with self._lock:
            self._human_corrections[event.correction_event_id] = event
            target_id = event.logical_task_id or event.task_id
            if target_id in self._tasks:
                task = self._tasks[target_id]
                task.correction_event = event
                if event.correction_type in ("explicit_reject", "explicit_user_rejection"):
                    task.final_outcome = TaskOutcome.FAILURE

    def get_logical_task(self, logical_task_id: str) -> Optional[LogicalTaskEconomicsRecord]:
        """Retrieve a logical task record by ID."""
        with self._lock:
            return self._tasks.get(logical_task_id)

    def get_attempt(self, attempt_id: str) -> Optional[AttemptEconomicsRecord]:
        """Retrieve an attempt record by ID."""
        with self._lock:
            return self._attempts.get(attempt_id)

    def compute_cohort_summary(
        self,
        cohort_key: EconomicsCohortKey,
        policy: Optional[SufficiencyPolicy] = None,
    ) -> ModelEconomicsSummary:
        """Aggregate all logical tasks belonging to a specific multidimensional cohort (Directive 2, 3, 5, 8)."""
        suff_policy = policy or self.sufficiency_policy
        with self._lock:
            cohort_tasks: List[LogicalTaskEconomicsRecord] = []
            for t in self._tasks.values():
                t_eval_version = t.evaluator_version or "v1"
                # Directive 2: Match initial_model_identity strictly
                if (
                    t.initial_model_identity == cohort_key.initial_model_identity
                    and t.task_family == cohort_key.task_family
                    and t_eval_version == cohort_key.evaluator_version
                    and t.routing_policy_version == cohort_key.routing_policy_version
                    and t.fallback_policy_version == cohort_key.fallback_policy_version
                    and t.effective_privacy_class == cohort_key.effective_privacy_class
                    and t.evidence_source == cohort_key.evidence_source
                ):
                    if (
                        cohort_key.evaluator_id is not None
                        and t.evaluator_id != cohort_key.evaluator_id
                    ):
                        continue
                    cohort_tasks.append(t)

            tasks_count = len(cohort_tasks)
            total_attempts_count = sum(len(t.attempts) for t in cohort_tasks)
            verified_successes = sum(
                1 for t in cohort_tasks if t.final_outcome == TaskOutcome.SUCCESS
            )
            failures = sum(1 for t in cohort_tasks if t.final_outcome == TaskOutcome.FAILURE)
            partials = sum(1 for t in cohort_tasks if t.final_outcome == TaskOutcome.PARTIAL)
            unknowns = sum(1 for t in cohort_tasks if t.final_outcome == TaskOutcome.UNKNOWN)

            evaluable_tasks_count = verified_successes + failures
            known_correction_count = sum(1 for t in cohort_tasks if t.correction_event is not None)

            total_micros = sum(t.total_cost.amount_micros for t in cohort_tasks)
            total_cost = Money.from_micros(total_micros, currency="USD")

            mean_micros = total_micros // tasks_count if tasks_count > 0 else 0
            mean_task_cost = Money.from_micros(mean_micros, currency="USD")

            # Directive 3: Whole-chain observed cost-per-success
            # If verified_successes == 0, observed CPS is None, status = NO_SUCCESS_EVIDENCE
            observed_cps: Optional[Money] = None
            if verified_successes > 0:
                cps_micros = total_micros // verified_successes
                observed_cps = Money.from_micros(cps_micros, currency="USD")

            status = suff_policy.evaluate(
                logical_tasks_count=tasks_count,
                verified_successes=verified_successes,
                failures_count=failures,
                partials_count=partials,
                unknowns_count=unknowns,
            )

            # Directive 8: Expected CPS named and provenance recorded
            expected_cps: Optional[Money] = None
            expected_cps_prov: Optional[str] = None
            if status == EvidenceSufficiencyStatus.SUFFICIENT_EVIDENCE and observed_cps is not None:
                expected_cps = observed_cps
                expected_cps_prov = "EMPIRICAL_ESTIMATE"
            else:
                expected_cps = None
                expected_cps_prov = status.value

            return ModelEconomicsSummary(
                cohort_key=cohort_key,
                initial_model_identity=cohort_key.initial_model_identity,
                initial_provider_id=cohort_key.initial_model_identity.provider_id,
                task_family=cohort_key.task_family,
                logical_tasks_count=tasks_count,
                total_attempts_count=total_attempts_count,
                verified_successes=verified_successes,
                failures=failures,
                partials=partials,
                unknowns=unknowns,
                evaluable_tasks_count=evaluable_tasks_count,
                known_correction_count=known_correction_count,
                total_cost=total_cost,
                mean_task_cost=mean_task_cost,
                observed_cost_per_verified_success=observed_cps,
                expected_cost_per_success=expected_cps,
                expected_cost_per_success_provenance=expected_cps_prov,
                estimator_version="v1_empirical_cohort",
                evidence_window="all_recorded_tasks",
                sufficiency_policy_version=suff_policy.policy_version,
                status=status,
                currency="USD",
                evaluator_version=cohort_key.evaluator_version,
                routing_policy_version=cohort_key.routing_policy_version,
                fallback_policy_version=cohort_key.fallback_policy_version,
                effective_privacy_class=cohort_key.effective_privacy_class,
                evidence_source=cohort_key.evidence_source,
                sample_freshness=time.time(),
            )

    def list_economics(
        self,
        task_family: Optional[str] = None,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        evidence_source: Optional[EvidenceSource] = None,
        evaluator_version: Optional[str] = None,
        effective_privacy_class: Optional[str] = None,
    ) -> List[ModelEconomicsSummary]:
        """List summaries for all active cohorts matching the requested filters."""
        with self._lock:
            cohort_keys = set()
            for t in self._tasks.values():
                k = EconomicsCohortKey(
                    initial_model_identity=t.initial_model_identity,
                    task_family=t.task_family,
                    evaluator_id=t.evaluator_id,
                    evaluator_version=t.evaluator_version or "v1",
                    routing_policy_version=t.routing_policy_version,
                    fallback_policy_version=t.fallback_policy_version,
                    effective_privacy_class=t.effective_privacy_class,
                    evidence_source=t.evidence_source,
                )
                cohort_keys.add(k)

            summaries: List[ModelEconomicsSummary] = []
            for k in cohort_keys:
                if task_family and k.task_family != task_family:
                    continue
                if provider_id and k.initial_model_identity.provider_id != provider_id:
                    continue
                if model_id and k.initial_model_identity.model_id != model_id:
                    continue
                if evidence_source and k.evidence_source != evidence_source:
                    continue
                if evaluator_version and k.evaluator_version != evaluator_version:
                    continue
                if effective_privacy_class and k.effective_privacy_class != effective_privacy_class:
                    continue

                summaries.append(self.compute_cohort_summary(k))

            summaries.sort(
                key=lambda s: (
                    s.task_family,
                    s.initial_provider_id,
                    s.initial_model_identity.model_id,
                    s.evidence_source.value,
                )
            )
            return summaries

    def complete_logical_task(
        self,
        logical_task_id: str,
        initial_model_identity: ModelIdentity,
        initial_provider_id: str,
        task_family: str = "general",
        initial_routing_decision: Optional[str] = None,
        evaluator_id: Optional[str] = None,
        evaluator_version: Optional[str] = "v1",
        routing_policy_version: str = "v1",
        fallback_policy_version: str = "v1",
        effective_privacy_class: str = "ANY_CONFIGURED",
        evidence_source: EvidenceSource = EvidenceSource.PRODUCTION_OBSERVATION,
        final_outcome: Optional[TaskOutcome] = None,
    ) -> LogicalTaskEconomicsRecord:
        """Complete and register or finalize a logical task chain record."""
        with self._lock:
            existing = self._tasks.get(logical_task_id)
            if existing is None:
                matched_attempts = [
                    att for att in self._attempts.values() if att.logical_task_id == logical_task_id
                ]
                existing = LogicalTaskEconomicsRecord(
                    logical_task_id=logical_task_id,
                    task_family=task_family,
                    initial_routing_decision=initial_routing_decision
                    or f"{initial_provider_id}:{initial_model_identity.model_id}",
                    initial_model_identity=initial_model_identity,
                    initial_provider_id=initial_provider_id,
                    routing_policy_version=routing_policy_version,
                    fallback_policy_version=fallback_policy_version,
                    effective_privacy_class=effective_privacy_class,
                    evaluator_id=evaluator_id,
                    evaluator_version=evaluator_version,
                    evidence_source=evidence_source,
                    final_outcome=final_outcome or TaskOutcome.UNKNOWN,
                    completed_at=time.time(),
                )
                for att in matched_attempts:
                    existing.add_attempt(att)
                matched_corrections = [
                    c
                    for c in self._human_corrections.values()
                    if (c.logical_task_id or c.task_id) == logical_task_id
                ]
                if matched_corrections:
                    existing.correction_event = matched_corrections[-1]
                self._tasks[logical_task_id] = existing
            else:
                if final_outcome is not None:
                    existing.final_outcome = final_outcome
                existing.task_family = task_family
                existing.initial_model_identity = initial_model_identity
                existing.initial_provider_id = initial_provider_id
                existing.evaluator_id = evaluator_id
                existing.evaluator_version = evaluator_version
                existing.routing_policy_version = routing_policy_version
                existing.fallback_policy_version = fallback_policy_version
                existing.effective_privacy_class = effective_privacy_class
                existing.evidence_source = evidence_source
                existing.completed_at = time.time()
            return existing

    def get_cost_per_success_estimate(
        self,
        model_identity: ModelIdentity,
        task_family: str = "general",
        effective_privacy_class: str = "ANY_CONFIGURED",
        evaluator_id: Optional[str] = None,
        evaluator_version: str = "v1",
        routing_policy_version: str = "v1",
        fallback_policy_version: str = "v1",
        evidence_source: EvidenceSource = EvidenceSource.PRODUCTION_OBSERVATION,
    ) -> Optional[CostPerSuccessEstimate]:
        """Retrieve cost-per-success estimate descriptor with provenance and status."""
        k = EconomicsCohortKey(
            initial_model_identity=model_identity,
            task_family=task_family,
            evaluator_id=evaluator_id,
            evaluator_version=evaluator_version,
            routing_policy_version=routing_policy_version,
            fallback_policy_version=fallback_policy_version,
            effective_privacy_class=effective_privacy_class,
            evidence_source=evidence_source,
        )
        summary = self.compute_cohort_summary(k)
        if summary.logical_tasks_count == 0:
            return None
        return CostPerSuccessEstimate(
            estimated_cps=summary.expected_cost_per_success
            or summary.observed_cost_per_verified_success
            or Money.zero(),
            provenance=summary.expected_cost_per_success_provenance or "EMPIRICAL_ESTIMATE",
            cohort_key=k,
            evaluator_version=evaluator_version,
            policy_version=routing_policy_version,
            sample_count=summary.logical_tasks_count,
            success_count=summary.verified_successes,
            status=summary.status,
        )

    def export_ledger(self) -> List[LogicalTaskEconomicsRecord]:
        """Export all current logical tasks in the economics ledger."""
        with self._lock:
            return list(self._tasks.values())

    def rebuild_from_records(self, records: Sequence[LogicalTaskEconomicsRecord]) -> int:
        """Rebuild economics store from pre-existing logical task records."""
        with self._lock:
            self._attempts.clear()
            self._tasks.clear()
            for rec in records:
                self.create_or_update_logical_task(rec)
                for att in rec.attempts:
                    self._attempts[att.attempt_id] = att
            return len(records)

    def get_expected_cps(
        self,
        model_identity: ModelIdentity,
        task_family: str = "general",
        effective_privacy_class: str = "ANY_CONFIGURED",
        evaluator_id: Optional[str] = None,
        evaluator_version: str = "v1",
        routing_policy_version: str = "v1",
        fallback_policy_version: str = "v1",
        evidence_source: EvidenceSource = EvidenceSource.PRODUCTION_OBSERVATION,
    ) -> Optional[CostPerSuccessEstimate]:
        """Retrieve empirical Cost-Per-Success estimate for routing optimization (Directive 14 & 15)."""
        k = EconomicsCohortKey(
            initial_model_identity=model_identity,
            task_family=task_family,
            evaluator_id=evaluator_id,
            evaluator_version=evaluator_version,
            routing_policy_version=routing_policy_version,
            fallback_policy_version=fallback_policy_version,
            effective_privacy_class=effective_privacy_class,
            evidence_source=evidence_source,
        )
        summary = self.compute_cohort_summary(k)
        if (
            summary.status == EvidenceSufficiencyStatus.SUFFICIENT_EVIDENCE
            and summary.expected_cost_per_success is not None
        ):
            return CostPerSuccessEstimate(
                estimated_cps=summary.expected_cost_per_success,
                provenance="EMPIRICAL_ESTIMATE",
                cohort_key=k,
                evaluator_version=evaluator_version,
                policy_version=routing_policy_version,
                sample_count=summary.logical_tasks_count,
                success_count=summary.verified_successes,
                status=summary.status,
            )
        return None

    def rebuild_from_canonical_ledger(
        self,
        executions: Sequence[Dict[str, Any]],
        events_by_exec_id: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
    ) -> int:
        """Rebuild economics projections from canonical execution ledger (Directive 6 & 10)."""
        with self._lock:
            self._attempts.clear()
            self._tasks.clear()
            count = 0
            for ex in executions:
                exec_id = ex.get("id") or ex.get("execution_id")
                if not exec_id:
                    continue

                provider = ex.get("provider", "unknown")
                model_name = ex.get("model", "unknown")
                identity = ModelIdentity(provider_id=provider, model_id=model_name)
                task_id = ex.get("task_id") or exec_id
                task_family = ex.get("task_type") or "general"
                cost_val = ex.get("total_cost_usd", 0.0)
                cost_money = Money.from_usd(cost_val)

                verif = ex.get("verification")
                outcome = TaskOutcome.UNKNOWN
                outcome_source = OutcomeSource.UNKNOWN
                eval_version = "v1"

                if isinstance(verif, dict):
                    if verif.get("passed") is True:
                        outcome = TaskOutcome.SUCCESS
                        outcome_source = OutcomeSource.DETERMINISTIC_VERIFIER
                    elif verif.get("passed") is False:
                        outcome = TaskOutcome.FAILURE
                        outcome_source = OutcomeSource.DETERMINISTIC_VERIFIER
                elif ex.get("status") in ("FAILED", "BLOCKED"):
                    outcome = TaskOutcome.FAILURE

                evidence = OutcomeEvidence(
                    outcome=outcome,
                    outcome_source=outcome_source,
                    evaluator_id="canonical_verifier" if outcome != TaskOutcome.UNKNOWN else None,
                    evaluator_version=eval_version,
                    observed_at=ex.get("completed_at_timestamp") or time.time(),
                )

                att = AttemptEconomicsRecord(
                    attempt_id=f"att_{exec_id}",
                    execution_id=exec_id,
                    logical_task_id=task_id,
                    model_identity=identity,
                    provider_id=provider,
                    cost=cost_money,
                    prompt_tokens=ex.get("input_tokens", 0),
                    completion_tokens=ex.get("output_tokens", 0),
                    outcome=outcome,
                    outcome_evidence=evidence,
                    created_at=ex.get("created_at_timestamp") or time.time(),
                )
                self.record_attempt(att)

                if task_id not in self._tasks:
                    task = LogicalTaskEconomicsRecord(
                        logical_task_id=task_id,
                        task_family=task_family,
                        initial_model_identity=identity,
                        initial_provider_id=provider,
                        routing_policy_version="v1",
                        fallback_policy_version="v1",
                        effective_privacy_class=ex.get("privacy_class", "ANY_CONFIGURED"),
                        evaluator_version=eval_version,
                        evidence_source=EvidenceSource.PRODUCTION_OBSERVATION,
                        total_cost=cost_money,
                        final_outcome=outcome,
                        created_at=ex.get("created_at_timestamp") or time.time(),
                    )
                    task.add_attempt(att)
                    self._tasks[task_id] = task
                else:
                    self._tasks[task_id].add_attempt(att)

                count += 1
            return count


_GLOBAL_ECONOMICS_SERVICE: Optional[EconomicsService] = None
_GLOBAL_LOCK = threading.Lock()


def get_economics_service(storage: Optional[StorageBackend] = None) -> EconomicsService:
    """Obtain canonical singleton EconomicsService instance."""
    global _GLOBAL_ECONOMICS_SERVICE
    with _GLOBAL_LOCK:
        if _GLOBAL_ECONOMICS_SERVICE is None:
            _GLOBAL_ECONOMICS_SERVICE = EconomicsService(storage=storage)
        return _GLOBAL_ECONOMICS_SERVICE


def reset_economics_service() -> None:
    """Reset singleton for test isolation."""
    global _GLOBAL_ECONOMICS_SERVICE
    with _GLOBAL_LOCK:
        _GLOBAL_ECONOMICS_SERVICE = None
