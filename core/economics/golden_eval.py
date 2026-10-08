"""Golden Evaluation Fixtures and Report Generator (Task R3.10 Directive 13 & 17).

Provides deterministic evaluation datasets proving that cheap but unreliable initial models
result in higher whole-chain cost-per-verified-success than reliable moderately priced models.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional

from core.economics.models import (
    AttemptEconomicsRecord,
    EvidenceSource,
    HumanCorrectionEvent,
    LogicalTaskEconomicsRecord,
    Money,
    OutcomeEvidence,
    OutcomeSource,
    SufficiencyPolicy,
    TaskOutcome,
)
from core.economics.service import EconomicsService
from core.model_registry.models import ModelIdentity


def build_golden_eval_service() -> EconomicsService:
    """Construct an EconomicsService populated with standard deterministic golden eval fixtures."""
    service = EconomicsService(
        default_sufficiency_policy=SufficiencyPolicy(
            policy_version="v1_golden_eval",
            min_logical_tasks=5,
            min_verified_successes=1,
            max_unknown_ratio=0.50,
        )
    )

    now = time.time()

    # --------------------------------------------------------------------------
    # 1. Reliable Expensive Initial Route: 5 tasks, 1 attempt each ($0.018), 100% success
    # --------------------------------------------------------------------------
    m_reliable = ModelIdentity(provider_id="anthropic", model_id="claude-3-5-sonnet")
    for i in range(1, 6):
        task_id = f"task_reliable_{i}"
        att = AttemptEconomicsRecord(
            attempt_id=f"att_rel_{i}_1",
            execution_id=f"exec_rel_{i}_1",
            logical_task_id=task_id,
            model_identity=m_reliable,
            provider_id="anthropic",
            cost=Money.from_usd(0.018),
            prompt_tokens=1500,
            completion_tokens=600,
            outcome=TaskOutcome.SUCCESS,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.SUCCESS,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                observed_at=now,
            ),
            is_fallback=False,
            is_retry=False,
            attempt_index=1,
            created_at=now - (100 - i),
        )
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="anthropic:claude-3-5-sonnet",
            initial_model_identity=m_reliable,
            initial_provider_id="anthropic",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            created_at=now - (100 - i),
            completed_at=now - (90 - i),
        )
        task.add_attempt(att)
        service.record_attempt(att)
        service.create_or_update_logical_task(task)

    # --------------------------------------------------------------------------
    # 2. Unreliable Cheap Initial Route: 5 tasks, 3 attempts each:
    #    Attempt 1: Cheap model fails ($0.005)
    #    Attempt 2: Retry fails ($0.005)
    #    Attempt 3: Expensive fallback model succeeds ($0.020)
    #    Total chain cost per task = $0.030
    # --------------------------------------------------------------------------
    m_cheap_unreliable = ModelIdentity(provider_id="cheap_cloud", model_id="mini-model")
    m_fallback = ModelIdentity(provider_id="expensive_cloud", model_id="fallback-large")

    for i in range(1, 6):
        task_id = f"task_unreliable_{i}"
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="cheap_cloud:mini-model",
            initial_model_identity=m_cheap_unreliable,
            initial_provider_id="cheap_cloud",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            created_at=now - (200 - i),
        )

        # Attempt 1: fail
        att1 = AttemptEconomicsRecord(
            attempt_id=f"att_unrel_{i}_1",
            execution_id=f"exec_unrel_{i}_1",
            logical_task_id=task_id,
            model_identity=m_cheap_unreliable,
            provider_id="cheap_cloud",
            cost=Money.from_usd(0.005),
            prompt_tokens=1500,
            completion_tokens=200,
            outcome=TaskOutcome.FAILURE,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.FAILURE,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                reason_code="SYNTAX_ERROR",
                observed_at=now,
            ),
            is_fallback=False,
            is_retry=False,
            attempt_index=1,
            created_at=now - (200 - i),
        )
        # Attempt 2: retry fail
        att2 = AttemptEconomicsRecord(
            attempt_id=f"att_unrel_{i}_2",
            execution_id=f"exec_unrel_{i}_2",
            logical_task_id=task_id,
            model_identity=m_cheap_unreliable,
            provider_id="cheap_cloud",
            cost=Money.from_usd(0.005),
            prompt_tokens=1500,
            completion_tokens=200,
            outcome=TaskOutcome.FAILURE,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.FAILURE,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                reason_code="UNIT_TEST_FAILED",
                observed_at=now,
            ),
            is_fallback=False,
            is_retry=True,
            attempt_index=2,
            created_at=now - (195 - i),
        )
        # Attempt 3: fallback success
        att3 = AttemptEconomicsRecord(
            attempt_id=f"att_unrel_{i}_3",
            execution_id=f"exec_unrel_{i}_3",
            logical_task_id=task_id,
            model_identity=m_fallback,
            provider_id="expensive_cloud",
            cost=Money.from_usd(0.020),
            prompt_tokens=1500,
            completion_tokens=700,
            outcome=TaskOutcome.SUCCESS,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.SUCCESS,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                observed_at=now,
            ),
            is_fallback=True,
            is_retry=False,
            attempt_index=3,
            created_at=now - (190 - i),
        )

        task.add_attempt(att1)
        task.add_attempt(att2)
        task.add_attempt(att3)
        service.record_attempt(att1)
        service.record_attempt(att2)
        service.record_attempt(att3)
        service.create_or_update_logical_task(task)

    # --------------------------------------------------------------------------
    # 3. Cheap Reliable Route (Local model): 5 tasks, $0.000 each, 100% success
    # --------------------------------------------------------------------------
    m_local_reliable = ModelIdentity(provider_id="local", model_id="qwen2.5-coder-free")
    for i in range(1, 6):
        task_id = f"task_local_{i}"
        att = AttemptEconomicsRecord(
            attempt_id=f"att_local_{i}_1",
            execution_id=f"exec_local_{i}_1",
            logical_task_id=task_id,
            model_identity=m_local_reliable,
            provider_id="local",
            cost=Money.from_usd(0.000),
            prompt_tokens=1200,
            completion_tokens=500,
            outcome=TaskOutcome.SUCCESS,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.SUCCESS,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                observed_at=now,
            ),
            created_at=now - (300 - i),
        )
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="local:qwen2.5-coder-free",
            initial_model_identity=m_local_reliable,
            initial_provider_id="local",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="LOCAL_ONLY",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            created_at=now - (300 - i),
        )
        task.add_attempt(att)
        service.record_attempt(att)
        service.create_or_update_logical_task(task)

    # --------------------------------------------------------------------------
    # 4. Zero Success Cohort: 5 tasks, all fail ($0.010 each)
    # --------------------------------------------------------------------------
    m_zero_success = ModelIdentity(provider_id="broken_cloud", model_id="broken-model")
    for i in range(1, 6):
        task_id = f"task_zero_{i}"
        att = AttemptEconomicsRecord(
            attempt_id=f"att_zero_{i}_1",
            execution_id=f"exec_zero_{i}_1",
            logical_task_id=task_id,
            model_identity=m_zero_success,
            provider_id="broken_cloud",
            cost=Money.from_usd(0.010),
            outcome=TaskOutcome.FAILURE,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.FAILURE,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                reason_code="SERVICE_UNAVAILABLE",
                observed_at=now,
            ),
            created_at=now - (400 - i),
        )
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="broken_cloud:broken-model",
            initial_model_identity=m_zero_success,
            initial_provider_id="broken_cloud",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            created_at=now - (400 - i),
        )
        task.add_attempt(att)
        service.record_attempt(att)
        service.create_or_update_logical_task(task)

    # --------------------------------------------------------------------------
    # 5. Insufficient Evidence Cohort: only 2 tasks
    # --------------------------------------------------------------------------
    m_insufficient = ModelIdentity(provider_id="experimental", model_id="new-model")
    for i in range(1, 3):
        task_id = f"task_insuf_{i}"
        att = AttemptEconomicsRecord(
            attempt_id=f"att_insuf_{i}_1",
            execution_id=f"exec_insuf_{i}_1",
            logical_task_id=task_id,
            model_identity=m_insufficient,
            provider_id="experimental",
            cost=Money.from_usd(0.012),
            outcome=TaskOutcome.SUCCESS,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.SUCCESS,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                observed_at=now,
            ),
            created_at=now - (500 - i),
        )
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="experimental:new-model",
            initial_model_identity=m_insufficient,
            initial_provider_id="experimental",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            created_at=now - (500 - i),
        )
        task.add_attempt(att)
        service.record_attempt(att)
        service.create_or_update_logical_task(task)

    # --------------------------------------------------------------------------
    # 6. Partial Outcome Cohort: 5 tasks, outcome = PARTIAL
    # --------------------------------------------------------------------------
    m_partial = ModelIdentity(provider_id="partial_cloud", model_id="truncated-model")
    for i in range(1, 6):
        task_id = f"task_part_{i}"
        att = AttemptEconomicsRecord(
            attempt_id=f"att_part_{i}_1",
            execution_id=f"exec_part_{i}_1",
            logical_task_id=task_id,
            model_identity=m_partial,
            provider_id="partial_cloud",
            cost=Money.from_usd(0.008),
            outcome=TaskOutcome.PARTIAL,
            outcome_evidence=OutcomeEvidence(
                outcome=TaskOutcome.PARTIAL,
                outcome_source=OutcomeSource.GOLDEN_EVAL,
                evaluator_id="golden_verifier",
                evaluator_version="v1",
                reason_code="MAX_TOKENS_EXCEEDED",
                observed_at=now,
            ),
            created_at=now - (600 - i),
        )
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="partial_cloud:truncated-model",
            initial_model_identity=m_partial,
            initial_provider_id="partial_cloud",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            created_at=now - (600 - i),
        )
        task.add_attempt(att)
        service.record_attempt(att)
        service.create_or_update_logical_task(task)

    # --------------------------------------------------------------------------
    # 7. Unknown Outcome Cohort: 5 tasks, outcome = UNKNOWN
    # --------------------------------------------------------------------------
    m_unknown = ModelIdentity(provider_id="unverified_cloud", model_id="opaque-model")
    for i in range(1, 6):
        task_id = f"task_unk_{i}"
        att = AttemptEconomicsRecord(
            attempt_id=f"att_unk_{i}_1",
            execution_id=f"exec_unk_{i}_1",
            logical_task_id=task_id,
            model_identity=m_unknown,
            provider_id="unverified_cloud",
            cost=Money.from_usd(0.007),
            outcome=TaskOutcome.UNKNOWN,
            created_at=now - (700 - i),
        )
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="unverified_cloud:opaque-model",
            initial_model_identity=m_unknown,
            initial_provider_id="unverified_cloud",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            created_at=now - (700 - i),
        )
        task.add_attempt(att)
        service.record_attempt(att)
        service.create_or_update_logical_task(task)

    # --------------------------------------------------------------------------
    # 8. Human Corrected Cohort: explicit human rejection event
    # --------------------------------------------------------------------------
    m_human_corr = ModelIdentity(provider_id="human_test", model_id="hallucinating-model")
    for i in range(1, 6):
        task_id = f"task_corr_{i}"
        att = AttemptEconomicsRecord(
            attempt_id=f"att_corr_{i}_1",
            execution_id=f"exec_corr_{i}_1",
            logical_task_id=task_id,
            model_identity=m_human_corr,
            provider_id="human_test",
            cost=Money.from_usd(0.015),
            outcome=TaskOutcome.SUCCESS,  # Initially marked completed
            created_at=now - (800 - i),
        )
        corr_event = HumanCorrectionEvent(
            task_id=task_id,
            source="trusted_user_action",
            correction_type="explicit_reject",
            observed_at=now - (795 - i),
            reason="User explicitly rejected incorrect calculation",
        )
        task = LogicalTaskEconomicsRecord(
            logical_task_id=task_id,
            task_family="coding",
            initial_routing_decision="human_test:hallucinating-model",
            initial_model_identity=m_human_corr,
            initial_provider_id="human_test",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            evaluator_version="v1",
            evidence_source=EvidenceSource.GOLDEN_EVAL,
            correction_event=corr_event,
            created_at=now - (800 - i),
        )
        task.add_attempt(att)
        service.record_attempt(att)
        service.create_or_update_logical_task(task)
        service.record_human_correction(corr_event)

    return service


def generate_golden_eval_report(service: Optional[EconomicsService] = None) -> Dict[str, Any]:
    """Generate a deterministic golden evaluation report verifying economics arithmetic."""
    svc = service or build_golden_eval_service()
    summaries = svc.list_economics(evidence_source=EvidenceSource.GOLDEN_EVAL)

    cohort_reports: List[Dict[str, Any]] = []
    for s in summaries:
        cohort_reports.append(
            {
                "cohort": s.cohort_key.initial_model_identity_str,
                "task_family": s.task_family,
                "logical_tasks": s.logical_tasks_count,
                "total_attempts": s.total_attempts_count,
                "verified_successes": s.verified_successes,
                "failures": s.failures,
                "partials": s.partials,
                "unknowns": s.unknowns,
                "total_cost_usd": s.total_cost.as_usd,
                "mean_task_cost_usd": s.mean_task_cost.as_usd,
                "observed_cost_per_verified_success_usd": (
                    s.observed_cost_per_verified_success.as_usd
                    if s.observed_cost_per_verified_success
                    else None
                ),
                "expected_cost_per_success_usd": (
                    s.expected_cost_per_success.as_usd if s.expected_cost_per_success else None
                ),
                "status": s.status.value,
                "privacy_class": s.effective_privacy_class,
            }
        )

    # Calculate key comparisons
    rel_summary = next(
        (s for s in summaries if "claude-3-5-sonnet" in s.cohort_key.initial_model_identity_str),
        None,
    )
    unrel_summary = next(
        (s for s in summaries if "mini-model" in s.cohort_key.initial_model_identity_str),
        None,
    )

    rel_cps = rel_summary.observed_cost_per_verified_success.as_usd if rel_summary else 0.0
    unrel_cps = unrel_summary.observed_cost_per_verified_success.as_usd if unrel_summary else 0.0

    return {
        "title": "Agent Engine R3.10 Golden Evaluation Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluator_version": "v1_golden_eval",
        "cohorts": cohort_reports,
        "mathematical_proof": {
            "reliable_route": {
                "initial_model": "anthropic:claude-3-5-sonnet",
                "per_attempt_cost_usd": 0.018,
                "chain_cost_per_verified_success_usd": rel_cps,
            },
            "unreliable_cheap_route": {
                "initial_model": "cheap_cloud:mini-model",
                "per_attempt_cost_usd": 0.005,
                "chain_cost_per_verified_success_usd": unrel_cps,
            },
            "proven_thesis": (
                f"Cheap model ($0.005/call) has higher whole-chain cost per verified success "
                f"(${unrel_cps:.3f}) than reliable model ($0.018/call -> ${rel_cps:.3f}) "
                f"due to failure retries and expensive fallback."
            ),
            "is_unreliable_more_expensive_per_success": unrel_cps > rel_cps,
        },
    }
