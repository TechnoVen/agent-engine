"""tests/test_r3_model_economics.py

Comprehensive precision test suite for Milestone R3 Task R3.10:
Chain-Level Model Economics & Cost-Per-Success Integration.

Covers all 22 required test invariants from Directive 20:
 1. TaskOutcome enum states (SUCCESS, FAILURE, PARTIAL, UNKNOWN).
 2. COMPLETED execution != SUCCESS; UNKNOWN is not success; PARTIAL reported separately.
 3. 1 logical task with 5 retries = 1 task; all retry/fallback spend included in task total cost.
 4. Attribution to initial routing decision (initial model receives chain cost; subsequent models not double-attributed).
 5. Zero verified successes produces NO_SUCCESS_EVIDENCE and observed_cps = None (no epsilon division).
 6. Evidence threshold uses logical tasks (>= 5), not attempt count.
 7. Incompatible evaluator versions and policy versions do not merge.
 8. LOCAL_ONLY cohort not merged with ANY_CONFIGURED.
 9. Monetary arithmetic uses exact integer micros via Money; cross-currency aggregation rejected.
10. Derivation from canonical execution truth / rebuild from ledger.
11. Explicit human correction recorded (HumanCorrectionEvent); inferred correction ignored.
12. Golden eval and production observations remain separate.
13. Golden eval report proves cheap-unreliable route ($0.030 CPS) worse than moderate-reliable route ($0.018 CPS).
14. Sufficient CPS evidence used by RoutingOptimizer under COST_FIRST.
15. Insufficient CPS evidence falls back to R3.9 cost metrics without error.
16. CPS integration preserves hard privacy (LOCAL_ONLY) and capability gates.
17. Routing weights remain static (no adaptive weight learning).
18. API GET /v1/models/economics returns filtered summaries; protected by IPC auth; contains no secrets or prompts.
19. Deterministic tie-breaking preserved with CPS.
20. CostPerSuccessEstimate provenance and status.
21. Desktop client API schema alignment.
22. Full cohort summary field validation.
"""

from __future__ import annotations

import os
import time
import pytest
from fastapi.testclient import TestClient

from core.economics import (
    AttemptEconomicsRecord,
    EconomicsCohortKey,
    EconomicsService,
    EvidenceSource,
    EvidenceSufficiencyStatus,
    HumanCorrectionEvent,
    ModelEconomicsSummary,
    Money,
    TaskOutcome,
    build_golden_eval_service,
    generate_golden_eval_report,
    generate_golden_eval_markdown_report,
    get_economics_service,
    reset_economics_service,
)
from core.execution.models import Execution, ExecutionRequest, ExecutionStatus
from core.model_registry.models import (
    LatencyClass,
    LatencyProfile,
    ModelCapabilities,
    ModelDefinition,
    ModelIdentity,
    PricingProfile,
    PrivacyProfile,
    TriStateBool,
)
from core.privacy.models import (
    DataRoutingClass,
    DataRoutingPolicy,
    EffectiveRoutingPolicy,
    RoutingPolicySource,
)
from core.router.models import (
    RoutingObjective,
    RoutingObjectiveProfile,
)
from core.router.objective import RoutingOptimizer
from services.python.server.app import create_app
from services.python.server.dependencies import get_token_manager, reset_token_manager


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------


def _make_model_def(
    provider_id: str,
    model_id: str,
    is_local: bool = False,
    input_price: float = 0.0,
    output_price: float = 0.0,
    catalog_latency_ms: float = 1000.0,
    supports_coding: bool = True,
    supports_vision: bool = False,
) -> ModelDefinition:
    return ModelDefinition(
        identity=ModelIdentity(provider_id=provider_id, model_id=model_id),
        display_name=f"{provider_id} {model_id}",
        capabilities=ModelCapabilities(
            coding=TriStateBool.TRUE if supports_coding else TriStateBool.FALSE,
            vision=TriStateBool.TRUE if supports_vision else TriStateBool.FALSE,
            tools=TriStateBool.TRUE,
        ),
        max_total_context_tokens=128000,
        pricing=PricingProfile(
            input_cost_per_million=input_price if not is_local else 0.0,
            output_cost_per_million=output_price if not is_local else 0.0,
            is_free=is_local,
        ),
        latency=LatencyProfile(
            catalog_latency_class=LatencyClass.FAST
            if catalog_latency_ms < 1000
            else LatencyClass.MEDIUM,
            catalog_latency_ms=catalog_latency_ms,
        ),
        privacy=PrivacyProfile(
            is_local=TriStateBool.TRUE if is_local else TriStateBool.FALSE,
            data_leaves_device=TriStateBool.FALSE if is_local else TriStateBool.TRUE,
        ),
    )


@pytest.fixture(autouse=True)
def clean_economics_service():
    """Reset economics service before each test."""
    reset_economics_service()
    yield
    reset_economics_service()


@pytest.fixture
def test_client():
    """FastAPI test client with IPC token configured and isolated."""
    old_token = os.environ.get("AGENT_ENGINE_IPC_TOKEN")
    os.environ["AGENT_ENGINE_IPC_TOKEN"] = "test-secret-token"
    reset_token_manager()
    mgr = get_token_manager()
    mgr.set_token("test-secret-token")
    mgr.set_enforced(True)
    app = create_app()
    client = TestClient(app)
    try:
        yield client
    finally:
        if old_token is not None:
            os.environ["AGENT_ENGINE_IPC_TOKEN"] = old_token
        else:
            os.environ.pop("AGENT_ENGINE_IPC_TOKEN", None)
        reset_token_manager()


# ---------------------------------------------------------------------------
# Test 1: TaskOutcome Enum States
# ---------------------------------------------------------------------------


def test_1_task_outcome_enum_states():
    assert TaskOutcome.SUCCESS.value == "SUCCESS"
    assert TaskOutcome.FAILURE.value == "FAILURE"
    assert TaskOutcome.PARTIAL.value == "PARTIAL"
    assert TaskOutcome.UNKNOWN.value == "UNKNOWN"
    assert len(TaskOutcome) == 4
    outcomes = {TaskOutcome.SUCCESS, TaskOutcome.FAILURE, TaskOutcome.PARTIAL, TaskOutcome.UNKNOWN}
    assert len(outcomes) == 4


# ---------------------------------------------------------------------------
# Test 2: COMPLETED Execution != SUCCESS; UNKNOWN is not Success
# ---------------------------------------------------------------------------


def test_2_completed_execution_is_not_success_and_unknown_is_not_success():
    execution = Execution(
        id="exec_1",
        session_id="sess_1",
        project_id="test_proj",
        request=ExecutionRequest(prompt="test prompt", project_id="test_proj"),
        status=ExecutionStatus.COMPLETED,
    )
    assert execution.status == ExecutionStatus.COMPLETED

    attempt = AttemptEconomicsRecord(
        execution_id=execution.id,
        logical_task_id="task_1",
        model_identity=ModelIdentity(provider_id="openai", model_id="gpt-4o"),
        provider_id="openai",
        cost=Money.from_usd(0.01),
        outcome=TaskOutcome.UNKNOWN,
    )
    assert attempt.outcome == TaskOutcome.UNKNOWN
    assert attempt.outcome != TaskOutcome.SUCCESS

    svc = EconomicsService()
    svc.record_attempt(attempt)
    svc.complete_logical_task(
        logical_task_id="task_1",
        initial_model_identity=ModelIdentity(provider_id="openai", model_id="gpt-4o"),
        initial_provider_id="openai",
        task_family="general",
    )
    summaries = svc.list_economics()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.verified_successes == 0
    assert summary.unknowns == 1
    assert summary.partials == 0
    assert summary.failures == 0
    assert summary.status == EvidenceSufficiencyStatus.NO_SUCCESS_EVIDENCE


# ---------------------------------------------------------------------------
# Test 3: 1 Logical Task with 5 Retries = 1 Task; Full Chain Spend Included
# ---------------------------------------------------------------------------


def test_3_single_logical_task_with_multiple_retries():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="openai", model_id="gpt-4o")

    costs = [0.002, 0.003, 0.001, 0.002, 0.004]
    for idx, c in enumerate(costs):
        outcome = TaskOutcome.SUCCESS if idx == 4 else TaskOutcome.FAILURE
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"exec_r_{idx}",
                logical_task_id="logical_task_chain_1",
                model_identity=model,
                provider_id="openai",
                cost=Money.from_usd(c),
                outcome=outcome,
                is_retry=(idx > 0),
                attempt_index=idx,
            )
        )

    task = svc.complete_logical_task(
        logical_task_id="logical_task_chain_1",
        initial_model_identity=model,
        initial_provider_id="openai",
        task_family="general",
        final_outcome=TaskOutcome.SUCCESS,
    )

    assert len(task.attempts) == 5
    assert task.total_cost.amount_micros == 12000
    assert task.final_outcome == TaskOutcome.SUCCESS

    summaries = svc.list_economics()
    assert len(summaries) == 1
    s = summaries[0]
    assert s.logical_tasks_count == 1
    assert s.total_attempts_count == 5
    assert s.total_cost.amount_micros == 12000
    assert s.mean_task_cost.amount_micros == 12000


# ---------------------------------------------------------------------------
# Test 4: Attribution to Initial Routing Decision
# ---------------------------------------------------------------------------


def test_4_attribution_to_initial_routing_decision():
    svc = EconomicsService()
    initial_model = ModelIdentity(provider_id="openai", model_id="gpt-4o-mini")
    fallback_model = ModelIdentity(provider_id="anthropic", model_id="claude-3-5-haiku")

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="exec_init",
            logical_task_id="chain_attr_1",
            model_identity=initial_model,
            provider_id="openai",
            cost=Money.from_usd(0.002),
            outcome=TaskOutcome.FAILURE,
            attempt_index=0,
        )
    )
    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="exec_fb",
            logical_task_id="chain_attr_1",
            model_identity=fallback_model,
            provider_id="anthropic",
            cost=Money.from_usd(0.005),
            outcome=TaskOutcome.SUCCESS,
            is_fallback=True,
            attempt_index=1,
        )
    )

    svc.complete_logical_task(
        logical_task_id="chain_attr_1",
        initial_model_identity=initial_model,
        initial_provider_id="openai",
        initial_routing_decision="openai:gpt-4o-mini",
        task_family="coding",
        final_outcome=TaskOutcome.SUCCESS,
    )

    summaries = svc.list_economics()
    assert len(summaries) == 1
    s_init = summaries[0]
    assert s_init.initial_model_identity.model_id == "gpt-4o-mini"
    assert s_init.logical_tasks_count == 1
    assert s_init.total_attempts_count == 2
    assert s_init.total_cost.amount_micros == 7000
    assert s_init.verified_successes == 1

    haiku_summaries = svc.list_economics(model_id="claude-3-5-haiku")
    assert len(haiku_summaries) == 0


# ---------------------------------------------------------------------------
# Test 5: Zero Verified Successes Produces NO_SUCCESS_EVIDENCE and None CPS
# ---------------------------------------------------------------------------


def test_5_zero_verified_successes_produces_no_success_evidence():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="mock", model_id="flaky-model")

    for i in range(10):
        t_id = f"task_zero_{i}"
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"exec_z_{i}",
                logical_task_id=t_id,
                model_identity=model,
                provider_id="mock",
                cost=Money.from_usd(0.005),
                outcome=TaskOutcome.FAILURE,
            )
        )
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=model,
            initial_provider_id="mock",
            task_family="general",
            final_outcome=TaskOutcome.FAILURE,
        )

    summaries = svc.list_economics()
    assert len(summaries) == 1
    s = summaries[0]
    assert s.logical_tasks_count == 10
    assert s.verified_successes == 0
    assert s.observed_cost_per_verified_success is None
    assert s.expected_cost_per_success is None
    assert s.status == EvidenceSufficiencyStatus.NO_SUCCESS_EVIDENCE

    est = svc.get_cost_per_success_estimate(model, task_family="general")
    assert est is not None
    assert est.status == EvidenceSufficiencyStatus.NO_SUCCESS_EVIDENCE
    assert est.success_count == 0


# ---------------------------------------------------------------------------
# Test 6: Evidence Threshold Uses Logical Tasks (>= 5), Not Attempt Count
# ---------------------------------------------------------------------------


def test_6_evidence_threshold_uses_logical_tasks_not_attempts():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="mock", model_id="worker")

    for i in range(10):
        outcome = TaskOutcome.SUCCESS if i == 9 else TaskOutcome.FAILURE
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"exec_att_{i}",
                logical_task_id="task_single",
                model_identity=model,
                provider_id="mock",
                cost=Money.from_usd(0.001),
                outcome=outcome,
            )
        )
    svc.complete_logical_task(
        logical_task_id="task_single",
        initial_model_identity=model,
        initial_provider_id="mock",
        task_family="general",
        final_outcome=TaskOutcome.SUCCESS,
    )

    summary = svc.list_economics()[0]
    assert summary.total_attempts_count == 10
    assert summary.logical_tasks_count == 1
    assert summary.status == EvidenceSufficiencyStatus.INSUFFICIENT_EVIDENCE

    for i in range(1, 5):
        t_id = f"task_more_{i}"
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"exec_m_{i}",
                logical_task_id=t_id,
                model_identity=model,
                provider_id="mock",
                cost=Money.from_usd(0.001),
                outcome=TaskOutcome.SUCCESS,
            )
        )
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=model,
            initial_provider_id="mock",
            task_family="general",
            final_outcome=TaskOutcome.SUCCESS,
        )

    summary_updated = svc.list_economics()[0]
    assert summary_updated.logical_tasks_count == 5
    assert summary_updated.verified_successes >= 1
    assert summary_updated.status == EvidenceSufficiencyStatus.SUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Test 7: Incompatible Evaluator Versions and Policy Versions Do Not Merge
# ---------------------------------------------------------------------------


def test_7_incompatible_evaluator_and_policy_versions_do_not_merge():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="mock", model_id="eval-test")

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="e1",
            logical_task_id="t1",
            model_identity=model,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
    )
    svc.complete_logical_task(
        logical_task_id="t1",
        initial_model_identity=model,
        initial_provider_id="mock",
        evaluator_version="v1.0",
        routing_policy_version="v1",
    )

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="e2",
            logical_task_id="t2",
            model_identity=model,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
    )
    svc.complete_logical_task(
        logical_task_id="t2",
        initial_model_identity=model,
        initial_provider_id="mock",
        evaluator_version="v2.0",
        routing_policy_version="v1",
    )

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="e3",
            logical_task_id="t3",
            model_identity=model,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
    )
    svc.complete_logical_task(
        logical_task_id="t3",
        initial_model_identity=model,
        initial_provider_id="mock",
        evaluator_version="v1.0",
        routing_policy_version="v2",
    )

    summaries = svc.list_economics()
    assert len(summaries) == 3
    versions = {(s.evaluator_version, s.routing_policy_version) for s in summaries}
    assert ("v1.0", "v1") in versions
    assert ("v2.0", "v1") in versions
    assert ("v1.0", "v2") in versions


# ---------------------------------------------------------------------------
# Test 8: LOCAL_ONLY Cohort Not Merged with ANY_CONFIGURED
# ---------------------------------------------------------------------------


def test_8_local_only_cohort_never_merged_with_any_configured():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="ollama", model_id="llama3.2:3b")

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="e_loc",
            logical_task_id="t_loc",
            model_identity=model,
            provider_id="ollama",
            cost=Money.zero(),
            outcome=TaskOutcome.SUCCESS,
        )
    )
    svc.complete_logical_task(
        logical_task_id="t_loc",
        initial_model_identity=model,
        initial_provider_id="ollama",
        effective_privacy_class="LOCAL_ONLY",
    )

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="e_cloud",
            logical_task_id="t_cloud",
            model_identity=model,
            provider_id="ollama",
            cost=Money.zero(),
            outcome=TaskOutcome.SUCCESS,
        )
    )
    svc.complete_logical_task(
        logical_task_id="t_cloud",
        initial_model_identity=model,
        initial_provider_id="ollama",
        effective_privacy_class="ANY_CONFIGURED",
    )

    summaries = svc.list_economics()
    assert len(summaries) == 2
    privacy_classes = {s.effective_privacy_class for s in summaries}
    assert privacy_classes == {"LOCAL_ONLY", "ANY_CONFIGURED"}


# ---------------------------------------------------------------------------
# Test 9: Monetary Arithmetic Uses Exact Integer Micros; Rejects Mixed Currency
# ---------------------------------------------------------------------------


def test_9_monetary_arithmetic_uses_integer_micros():
    m1 = Money(amount_micros=123456, currency="USD")
    m2 = Money(amount_micros=654321, currency="USD")
    m3 = m1 + m2
    assert m3.amount_micros == 777777
    assert m3.currency == "USD"
    assert m3.to_usd() == 0.777777

    m_eur = Money(amount_micros=1000, currency="EUR")
    with pytest.raises(ValueError, match="Currency mismatch"):
        _ = m1 + m_eur

    m_from_usd = Money.from_usd(0.005)
    assert m_from_usd.amount_micros == 5000

    zero = Money.zero("USD")
    total = zero
    for _ in range(10000):
        total = total + Money(amount_micros=10, currency="USD")
    assert total.amount_micros == 100000


# ---------------------------------------------------------------------------
# Test 10: Derivation from Canonical Execution Truth / Rebuild from Ledger
# ---------------------------------------------------------------------------


def test_10_derivation_from_canonical_execution_truth():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="openai", model_id="gpt-4o")

    for i in range(5):
        t_id = f"task_ledger_{i}"
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"ex_{i}",
                logical_task_id=t_id,
                model_identity=model,
                provider_id="openai",
                cost=Money.from_usd(0.01),
                outcome=TaskOutcome.SUCCESS,
            )
        )
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=model,
            initial_provider_id="openai",
            final_outcome=TaskOutcome.SUCCESS,
        )

    ledger = svc.export_ledger()
    assert len(ledger) == 5

    new_svc = EconomicsService()
    new_svc.rebuild_from_records(ledger)
    assert len(new_svc.list_economics()) == 1
    rebuilt_summary = new_svc.list_economics()[0]
    assert rebuilt_summary.logical_tasks_count == 5
    assert rebuilt_summary.verified_successes == 5
    assert rebuilt_summary.total_cost.amount_micros == 50000


# ---------------------------------------------------------------------------
# Test 11: Explicit Human Correction Recorded; Inferred Correction Ignored
# ---------------------------------------------------------------------------


def test_11_explicit_human_correction_recorded():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="openai", model_id="gpt-4o")

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="ex_human",
            logical_task_id="task_human_1",
            model_identity=model,
            provider_id="openai",
            cost=Money.from_usd(0.02),
            outcome=TaskOutcome.FAILURE,
        )
    )

    event = HumanCorrectionEvent(
        task_id="task_human_1",
        source="trusted_user_action",
        correction_type="explicit_reject",
        reason="Model hallucinated function argument",
    )
    svc.record_human_correction(event)

    task = svc.complete_logical_task(
        logical_task_id="task_human_1",
        initial_model_identity=model,
        initial_provider_id="openai",
        final_outcome=TaskOutcome.FAILURE,
    )
    assert task.correction_event is not None
    assert task.correction_event.source == "trusted_user_action"
    assert task.correction_event.correction_type == "explicit_reject"


# ---------------------------------------------------------------------------
# Test 12: Golden Eval and Production Observations Remain Separate
# ---------------------------------------------------------------------------


def test_12_golden_eval_and_production_remain_separate():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="openai", model_id="gpt-4o")

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="eg",
            logical_task_id="tg",
            model_identity=model,
            provider_id="openai",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
    )
    svc.complete_logical_task(
        logical_task_id="tg",
        initial_model_identity=model,
        initial_provider_id="openai",
        evidence_source=EvidenceSource.GOLDEN_EVAL,
    )

    svc.record_attempt(
        AttemptEconomicsRecord(
            execution_id="ep",
            logical_task_id="tp",
            model_identity=model,
            provider_id="openai",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
    )
    svc.complete_logical_task(
        logical_task_id="tp",
        initial_model_identity=model,
        initial_provider_id="openai",
        evidence_source=EvidenceSource.PRODUCTION_OBSERVATION,
    )

    summaries = svc.list_economics()
    assert len(summaries) == 2
    sources = {s.evidence_source for s in summaries}
    assert sources == {EvidenceSource.GOLDEN_EVAL, EvidenceSource.PRODUCTION_OBSERVATION}

    golden_only = svc.list_economics(evidence_source=EvidenceSource.GOLDEN_EVAL)
    assert len(golden_only) == 1
    assert golden_only[0].evidence_source == EvidenceSource.GOLDEN_EVAL


# ---------------------------------------------------------------------------
# Test 13: Golden Eval Report Proves Cheap-Unreliable Worse Than Moderate-Reliable
# ---------------------------------------------------------------------------


def test_13_golden_eval_proves_cheap_unreliable_worse_than_moderate_reliable():
    report = generate_golden_eval_report()
    assert "title" in report
    assert "mathematical_proof" in report
    proof = report["mathematical_proof"]

    cps_rel = proof["reliable_route"]["chain_cost_per_verified_success_usd"]
    cps_unrel = proof["unreliable_cheap_route"]["chain_cost_per_verified_success_usd"]

    assert cps_rel == 0.018
    assert cps_unrel == 0.030
    assert cps_unrel > cps_rel
    assert proof["is_unreliable_more_expensive_per_success"] is True


# ---------------------------------------------------------------------------
# Test 14: Sufficient CPS Evidence Used by RoutingOptimizer Under COST_FIRST
# ---------------------------------------------------------------------------


def test_14_sufficient_cps_evidence_used_under_cost_first():
    svc = EconomicsService()
    m_cheap_id = ModelIdentity(provider_id="mock", model_id="cheap-flaky")
    m_reliable_id = ModelIdentity(provider_id="mock", model_id="reliable-solid")

    for i in range(5):
        t_id = f"t_cheap_{i}"
        outcome = TaskOutcome.SUCCESS if i == 0 else TaskOutcome.FAILURE
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"ec_{i}",
                logical_task_id=t_id,
                model_identity=m_cheap_id,
                provider_id="mock",
                cost=Money.from_usd(0.006),
                outcome=outcome,
            )
        )
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=m_cheap_id,
            initial_provider_id="mock",
            task_family="general",
            final_outcome=outcome,
        )

    for i in range(5):
        t_id = f"t_rel_{i}"
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"er_{i}",
                logical_task_id=t_id,
                model_identity=m_reliable_id,
                provider_id="mock",
                cost=Money.from_usd(0.015),
                outcome=TaskOutcome.SUCCESS,
            )
        )
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=m_reliable_id,
            initial_provider_id="mock",
            task_family="general",
            final_outcome=TaskOutcome.SUCCESS,
        )

    optimizer = RoutingOptimizer()
    def_cheap = _make_model_def("mock", "cheap-flaky", input_price=2.0, output_price=2.0)
    def_reliable = _make_model_def("mock", "reliable-solid", input_price=10.0, output_price=10.0)

    decision = optimizer.optimize(
        candidates=[def_cheap, def_reliable],
        objective=RoutingObjectiveProfile.COST_FIRST,
        economics_service=svc,
    )
    assert decision.winner.identity.model_id == "reliable-solid"
    cost_ev = decision.winner.metrics.cost
    assert cost_ev.is_cost_per_success is True


# ---------------------------------------------------------------------------
# Test 15: Insufficient CPS Evidence Falls Back to R3.9 Nominal Cost Metrics
# ---------------------------------------------------------------------------


def test_15_insufficient_cps_evidence_falls_back_to_nominal_cost():
    svc = EconomicsService()
    optimizer = RoutingOptimizer()
    def_unknown = _make_model_def("mock", "novel-model", input_price=1.0, output_price=2.0)

    decision = optimizer.optimize(
        candidates=[def_unknown],
        objective=RoutingObjectiveProfile.COST_FIRST,
        economics_service=svc,
    )
    assert decision.winner.identity.model_id == "novel-model"
    cost_ev = decision.winner.metrics.cost
    assert cost_ev.is_cost_per_success is False
    assert cost_ev.cost_per_success_provenance == "fallback_r3_9_request_estimate"
    assert cost_ev.cost_per_success_status == EvidenceSufficiencyStatus.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Test 16: CPS Integration Preserves Hard Privacy and Capability Gates
# ---------------------------------------------------------------------------


def test_16_cps_preserves_hard_privacy_and_capability_gates():
    svc = EconomicsService()
    m_cloud_id = ModelIdentity(provider_id="openai", model_id="gpt-4o")

    for i in range(5):
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"ec_{i}",
                logical_task_id=f"tc_{i}",
                model_identity=m_cloud_id,
                provider_id="openai",
                cost=Money.from_usd(0.001),
                outcome=TaskOutcome.SUCCESS,
            )
        )
        svc.complete_logical_task(
            logical_task_id=f"tc_{i}",
            initial_model_identity=m_cloud_id,
            initial_provider_id="openai",
            final_outcome=TaskOutcome.SUCCESS,
        )

    optimizer = RoutingOptimizer()
    def_cloud = _make_model_def(
        "openai", "gpt-4o", is_local=False, input_price=1.0, output_price=1.0
    )
    def_local = _make_model_def("ollama", "llama3.2", is_local=True)

    policy = EffectiveRoutingPolicy(
        profile_policy=DataRoutingPolicy(default_class=DataRoutingClass.LOCAL_ONLY),
        effective_class=DataRoutingClass.LOCAL_ONLY,
        source=RoutingPolicySource.TASK_OVERRIDE,
    )

    decision = optimizer.optimize(
        candidates=[def_cloud, def_local],
        effective_policy=policy,
        objective=RoutingObjectiveProfile.COST_FIRST,
        economics_service=svc,
    )
    assert decision.winner.identity.provider_id == "ollama"
    assert any(
        r.provider_id == "openai" and r.stage == "PRIVACY" for r in decision.rejected_candidates
    )


# ---------------------------------------------------------------------------
# Test 17: Routing Weights Remain Static (No Adaptive Weight Learning)
# ---------------------------------------------------------------------------


def test_17_routing_weights_remain_static():
    svc = build_golden_eval_service()
    optimizer = RoutingOptimizer()

    obj = RoutingObjective.from_profile(RoutingObjectiveProfile.BALANCED)
    w_q, w_c, w_l, w_h = obj.w_quality, obj.w_cost, obj.w_latency, obj.w_health

    model = _make_model_def("openai", "gpt-4o", input_price=2.5, output_price=10.0)
    _ = optimizer.optimize(candidates=[model], objective=obj, economics_service=svc)

    assert obj.w_quality == w_q
    assert obj.w_cost == w_c
    assert obj.w_latency == w_l
    assert obj.w_health == w_h
    assert obj.w_quality == 0.35
    assert obj.w_cost == 0.30
    assert obj.w_latency == 0.20
    assert obj.w_health == 0.15


# ---------------------------------------------------------------------------
# Test 18: API GET /v1/models/economics Returns Filtered Summaries and No Secrets
# ---------------------------------------------------------------------------


def test_18_api_models_economics_security_and_filtering(test_client):
    svc = get_economics_service()
    m1 = ModelIdentity(provider_id="openai", model_id="gpt-4o")
    m2 = ModelIdentity(provider_id="anthropic", model_id="claude-3-5-sonnet")

    for i in range(5):
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"e_{i}",
                logical_task_id=f"t1_{i}",
                model_identity=m1,
                provider_id="openai",
                cost=Money.from_usd(0.01),
                outcome=TaskOutcome.SUCCESS,
            )
        )
        svc.complete_logical_task(
            logical_task_id=f"t1_{i}",
            initial_model_identity=m1,
            initial_provider_id="openai",
            task_family="coding",
            final_outcome=TaskOutcome.SUCCESS,
        )

    for i in range(5):
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"e2_{i}",
                logical_task_id=f"t2_{i}",
                model_identity=m2,
                provider_id="anthropic",
                cost=Money.from_usd(0.02),
                outcome=TaskOutcome.SUCCESS,
            )
        )
        svc.complete_logical_task(
            logical_task_id=f"t2_{i}",
            initial_model_identity=m2,
            initial_provider_id="anthropic",
            task_family="general",
            final_outcome=TaskOutcome.SUCCESS,
        )

    res_unauth = test_client.get("/v1/models/economics")
    assert res_unauth.status_code == 401

    token = get_token_manager().get_token()
    headers = {"X-IPC-Token": token}
    res_all = test_client.get("/v1/models/economics", headers=headers)
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert len(data_all) == 2

    res_coding = test_client.get("/v1/models/economics?task_family=coding", headers=headers)
    assert res_coding.status_code == 200
    data_coding = res_coding.json()
    assert len(data_coding) == 1
    assert data_coding[0]["task_family"] == "coding"

    import json

    text = json.dumps(data_all)
    assert "api_key" not in text
    assert "prompt" not in text
    assert "credential" not in text
    assert "secret" not in text


# ---------------------------------------------------------------------------
# Test 19: Deterministic Tie-Breaking Preserved with CPS
# ---------------------------------------------------------------------------


def test_19_deterministic_tie_breaking_preserved_with_cps():
    svc = EconomicsService()
    m_a_id = ModelIdentity(provider_id="mock_a", model_id="model-tie")
    m_b_id = ModelIdentity(provider_id="mock_b", model_id="model-tie")

    for m in (m_a_id, m_b_id):
        for i in range(5):
            svc.record_attempt(
                AttemptEconomicsRecord(
                    execution_id=f"e_{m.provider_id}_{i}",
                    logical_task_id=f"t_{m.provider_id}_{i}",
                    model_identity=m,
                    provider_id=m.provider_id,
                    cost=Money.from_usd(0.01),
                    outcome=TaskOutcome.SUCCESS,
                )
            )
            svc.complete_logical_task(
                logical_task_id=f"t_{m.provider_id}_{i}",
                initial_model_identity=m,
                initial_provider_id=m.provider_id,
                final_outcome=TaskOutcome.SUCCESS,
            )

    optimizer = RoutingOptimizer()
    def_b = _make_model_def("mock_b", "model-tie", input_price=5.0, output_price=5.0)
    def_a = _make_model_def("mock_a", "model-tie", input_price=5.0, output_price=5.0)

    res1 = optimizer.optimize(
        [def_b, def_a], objective=RoutingObjectiveProfile.BALANCED, economics_service=svc
    )
    res2 = optimizer.optimize(
        [def_b, def_a], objective=RoutingObjectiveProfile.BALANCED, economics_service=svc
    )
    assert res1.winner.provider_id == res2.winner.provider_id


# ---------------------------------------------------------------------------
# Test 20: CostPerSuccessEstimate Provenance and Status
# ---------------------------------------------------------------------------


def test_20_cost_per_success_estimate_provenance_and_status():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="openai", model_id="gpt-4o")

    est_empty = svc.get_cost_per_success_estimate(model)
    assert est_empty is None

    for i in range(5):
        svc.record_attempt(
            AttemptEconomicsRecord(
                execution_id=f"e_{i}",
                logical_task_id=f"t_{i}",
                model_identity=model,
                provider_id="openai",
                cost=Money.from_usd(0.01),
                outcome=TaskOutcome.SUCCESS,
            )
        )
        svc.complete_logical_task(
            logical_task_id=f"t_{i}",
            initial_model_identity=model,
            initial_provider_id="openai",
            final_outcome=TaskOutcome.SUCCESS,
        )

    est = svc.get_cost_per_success_estimate(model)
    assert est is not None
    assert est.provenance == "EMPIRICAL_ESTIMATE"
    assert est.status == EvidenceSufficiencyStatus.SUFFICIENT_EVIDENCE
    assert est.sample_count == 5
    assert est.success_count == 5
    assert est.estimated_cps.amount_micros == 10000


# ---------------------------------------------------------------------------
# Test 21: Desktop Client API Schema Alignment
# ---------------------------------------------------------------------------


def test_21_desktop_client_api_schema_alignment():
    svc = build_golden_eval_service()
    summaries = svc.list_economics()
    assert len(summaries) > 0
    s = summaries[0]
    data = s.model_dump()

    expected_fields = [
        "cohort_key",
        "initial_model_identity",
        "initial_provider_id",
        "task_family",
        "logical_tasks_count",
        "total_attempts_count",
        "verified_successes",
        "failures",
        "partials",
        "unknowns",
        "total_cost",
        "mean_task_cost",
        "observed_cost_per_verified_success",
        "status",
        "currency",
        "evaluator_version",
        "routing_policy_version",
        "fallback_policy_version",
        "effective_privacy_class",
        "evidence_source",
    ]
    for f in expected_fields:
        assert f in data, f"Missing expected field: {f}"

    assert "amount_micros" in data["total_cost"]
    assert "currency" in data["total_cost"]


# ---------------------------------------------------------------------------
# Test 22: Full Cohort Summary Field Validation
# ---------------------------------------------------------------------------


def test_22_full_cohort_summary_field_validation():
    key = EconomicsCohortKey(
        initial_model_identity_str="openai:gpt-4o",
        task_family="reasoning",
        evaluator_version="v1.2.0",
        routing_policy_version="v1",
        fallback_policy_version="v1",
        effective_privacy_class="ANY_CONFIGURED",
        evidence_source=EvidenceSource.GOLDEN_EVAL,
    )
    summary = ModelEconomicsSummary(
        cohort_key=key,
        initial_model_identity=ModelIdentity(provider_id="openai", model_id="gpt-4o"),
        initial_provider_id="openai",
        task_family="reasoning",
        logical_tasks_count=10,
        total_attempts_count=14,
        verified_successes=8,
        failures=1,
        partials=1,
        unknowns=0,
        total_cost=Money(amount_micros=180000, currency="USD"),
        mean_task_cost=Money(amount_micros=18000, currency="USD"),
        observed_cost_per_verified_success=Money(amount_micros=22500, currency="USD"),
        expected_cost_per_success=Money(amount_micros=22500, currency="USD"),
        status=EvidenceSufficiencyStatus.SUFFICIENT_EVIDENCE,
        currency="USD",
        evaluator_version="v1.2.0",
        routing_policy_version="v1",
        fallback_policy_version="v1",
        effective_privacy_class="ANY_CONFIGURED",
        evidence_source=EvidenceSource.GOLDEN_EVAL,
        sample_freshness=time.time(),
    )

    json_str = summary.model_dump_json()
    restored = ModelEconomicsSummary.model_validate_json(json_str)
    assert restored.cohort_key == summary.cohort_key
    assert restored.total_cost.amount_micros == 180000
    assert restored.observed_cost_per_verified_success.amount_micros == 22500
    assert restored.status == EvidenceSufficiencyStatus.SUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Test 23: Initial ModelIdentity Strictly Separates Cohorts (Directive 2)
# ---------------------------------------------------------------------------


def test_23_initial_model_identity_separates_cohorts():
    svc = EconomicsService()
    m_openai = ModelIdentity(provider_id="openai", model_id="gpt-4o")
    m_anthropic = ModelIdentity(provider_id="anthropic", model_id="claude-3-5-sonnet")

    for i in range(5):
        t1_id = f"t_openai_{i}"
        att1 = AttemptEconomicsRecord(
            execution_id=f"e_o_{i}",
            logical_task_id=t1_id,
            model_identity=m_openai,
            provider_id="openai",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
        svc.record_attempt(att1)
        svc.complete_logical_task(
            logical_task_id=t1_id,
            initial_model_identity=m_openai,
            initial_provider_id="openai",
            task_family="coding",
            evaluator_version="v1",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            final_outcome=TaskOutcome.SUCCESS,
        )

        t2_id = f"t_anthropic_{i}"
        att2 = AttemptEconomicsRecord(
            execution_id=f"e_a_{i}",
            logical_task_id=t2_id,
            model_identity=m_anthropic,
            provider_id="anthropic",
            cost=Money.from_usd(0.015),
            outcome=TaskOutcome.SUCCESS,
        )
        svc.record_attempt(att2)
        svc.complete_logical_task(
            logical_task_id=t2_id,
            initial_model_identity=m_anthropic,
            initial_provider_id="anthropic",
            task_family="coding",
            evaluator_version="v1",
            routing_policy_version="v1",
            fallback_policy_version="v1",
            effective_privacy_class="ANY_CONFIGURED",
            final_outcome=TaskOutcome.SUCCESS,
        )

    summaries = svc.list_economics(task_family="coding")
    assert len(summaries) == 2
    identities = {s.initial_model_identity.canonical_id for s in summaries}
    assert identities == {"openai:gpt-4o", "anthropic:claude-3-5-sonnet"}
    assert summaries[0].cohort_key != summaries[1].cohort_key


# ---------------------------------------------------------------------------
# Test 24: 5 UNKNOWN Tasks != Sufficient Evidence (Directive 3)
# ---------------------------------------------------------------------------


def test_24_unknown_tasks_do_not_produce_sufficient_evidence():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="mock", model_id="opaque-model")

    for i in range(5):
        t_id = f"t_unk_{i}"
        att = AttemptEconomicsRecord(
            execution_id=f"e_unk_{i}",
            logical_task_id=t_id,
            model_identity=model,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.UNKNOWN,
        )
        svc.record_attempt(att)
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=model,
            initial_provider_id="mock",
            final_outcome=TaskOutcome.UNKNOWN,
        )

    summaries = svc.list_economics()
    assert len(summaries) == 1
    s = summaries[0]
    assert s.logical_tasks_count == 5
    assert s.verified_successes == 0
    assert s.unknowns == 5
    assert s.evaluable_tasks_count == 0
    assert s.status == EvidenceSufficiencyStatus.NO_SUCCESS_EVIDENCE
    assert s.observed_cost_per_verified_success is None
    assert s.expected_cost_per_success is None

    # Test 5 tasks with 1 SUCCESS, 4 UNKNOWN (not enough evaluable tasks)
    svc_partial = EconomicsService()
    m2 = ModelIdentity(provider_id="mock", model_id="mostly-unknown")
    for i in range(5):
        t_id = f"t_mu_{i}"
        outcome = TaskOutcome.SUCCESS if i == 0 else TaskOutcome.UNKNOWN
        att = AttemptEconomicsRecord(
            execution_id=f"e_mu_{i}",
            logical_task_id=t_id,
            model_identity=m2,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=outcome,
        )
        svc_partial.record_attempt(att)
        svc_partial.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=m2,
            initial_provider_id="mock",
            final_outcome=outcome,
        )

    s2 = svc_partial.list_economics()[0]
    assert s2.logical_tasks_count == 5
    assert s2.verified_successes == 1
    assert s2.evaluable_tasks_count == 1  # 1 evaluable < 5 min_evaluable
    assert s2.status == EvidenceSufficiencyStatus.INSUFFICIENT_EVIDENCE
    assert s2.expected_cost_per_success is None


# ---------------------------------------------------------------------------
# Test 25: CPS Cost Evidence Applied Across All Profiles With Nonzero Cost Weight (Directive 4)
# ---------------------------------------------------------------------------


def test_25_cps_evidence_applied_across_all_profiles_with_cost_weight():
    svc = EconomicsService()
    m_id = ModelIdentity(provider_id="mock", model_id="solid-model")
    m_def = _make_model_def("mock", "solid-model", input_price=10.0, output_price=10.0)

    for i in range(5):
        t_id = f"t_cps_{i}"
        att = AttemptEconomicsRecord(
            execution_id=f"e_{i}",
            logical_task_id=t_id,
            model_identity=m_id,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
        svc.record_attempt(att)
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=m_id,
            initial_provider_id="mock",
            final_outcome=TaskOutcome.SUCCESS,
        )

    optimizer = RoutingOptimizer()

    profiles_to_test = [
        RoutingObjectiveProfile.BALANCED,
        RoutingObjectiveProfile.COST_FIRST,
        RoutingObjectiveProfile.QUALITY_FIRST,
        RoutingObjectiveProfile.LATENCY_FIRST,
    ]

    for p in profiles_to_test:
        decision = optimizer.optimize([m_def], objective=p, economics_service=svc)
        assert decision.selected_model is not None
        assert len(decision.eligible_candidates) > 0
        cand = decision.eligible_candidates[0]
        cost_ev = cand.metrics.cost
        assert cost_ev.is_cost_per_success is True
        assert cost_ev.cost_per_success_status == "SUFFICIENT_EVIDENCE"
        assert cost_ev.cost_per_success_micros == 10000
        # Cost utility normalized deterministically against 100,000 micros: (1.0 - 0.10) = 0.90
        assert cand.score.cost_utility == 0.90


# ---------------------------------------------------------------------------
# Test 26: Money Remains Exact Micros and Normalization is Deterministic (Directive 5)
# ---------------------------------------------------------------------------


def test_26_money_remains_exact_micros_and_deterministic_normalization():
    svc = EconomicsService()
    m_id = ModelIdentity(provider_id="mock", model_id="micro-model")

    # Record tasks with exact non-round micros: 12,345 micros per task
    for i in range(5):
        t_id = f"t_micro_{i}"
        att = AttemptEconomicsRecord(
            execution_id=f"e_m_{i}",
            logical_task_id=t_id,
            model_identity=m_id,
            provider_id="mock",
            cost=Money(amount_micros=12345, currency="USD"),
            outcome=TaskOutcome.SUCCESS,
        )
        svc.record_attempt(att)
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=m_id,
            initial_provider_id="mock",
            final_outcome=TaskOutcome.SUCCESS,
        )

    summary = svc.list_economics()[0]
    assert summary.total_cost.amount_micros == 61725
    assert summary.mean_task_cost.amount_micros == 12345
    assert summary.observed_cost_per_verified_success.amount_micros == 12345
    assert summary.expected_cost_per_success.amount_micros == 12345

    # Rebuild from records and confirm exact integer micros preservation
    ledger = svc.export_ledger()
    svc2 = EconomicsService()
    svc2.rebuild_from_records(ledger)
    summary2 = svc2.list_economics()[0]
    assert summary2.total_cost.amount_micros == 61725
    assert summary2.expected_cost_per_success.amount_micros == 12345


# ---------------------------------------------------------------------------
# Test 27: Arbitrary Forged Production Attempt Rejected (Directive 6)
# ---------------------------------------------------------------------------


def test_27_forged_attempt_cannot_enter_production_cohort():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="forged", model_id="fabricated-model")

    forged_attempt = AttemptEconomicsRecord(
        execution_id="forged_exec",
        logical_task_id="forged_task",
        model_identity=model,
        provider_id="forged",
        cost=Money.from_usd(0.001),
        outcome=TaskOutcome.SUCCESS,
        is_synthetic=True,
    )

    with pytest.raises(
        ValueError, match="Forged or synthetic attempt record cannot enter production cohort"
    ):
        svc.record_attempt(forged_attempt)


# ---------------------------------------------------------------------------
# Test 28: Explicit Human Correction Recorded vs Inferred Ignored (Directive 7)
# ---------------------------------------------------------------------------


def test_28_explicit_human_correction_vs_inferred_negative_test():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="mock", model_id="model-corr")

    for i in range(5):
        t_id = f"t_corr_test_{i}"
        att = AttemptEconomicsRecord(
            execution_id=f"e_ct_{i}",
            logical_task_id=t_id,
            model_identity=model,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
        svc.record_attempt(att)
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=model,
            initial_provider_id="mock",
            final_outcome=TaskOutcome.SUCCESS,
        )

    # Initially: 0 known corrections
    summary_before = svc.list_economics()[0]
    assert summary_before.known_correction_count == 0

    # Negative inference test: another attempt or message arrives on task 0 without explicit HumanCorrectionEvent
    att_continuation = AttemptEconomicsRecord(
        execution_id="e_cont_0",
        logical_task_id="t_corr_test_0",
        model_identity=model,
        provider_id="mock",
        cost=Money.from_usd(0.005),
        outcome=TaskOutcome.SUCCESS,
    )
    svc.record_attempt(att_continuation)
    summary_mid = svc.list_economics()[0]
    assert (
        summary_mid.known_correction_count == 0
    )  # Still 0! Inferred continuation is NOT a correction!

    # Explicit human rejection event
    event = HumanCorrectionEvent(
        task_id="t_corr_test_0",
        source="trusted_user_action",
        trusted_actor="user",
        correction_type="explicit_reject",
        reason="User clicked thumbs down and typed reject",
        reason_code="USER_THUMBS_DOWN",
    )
    svc.record_human_correction(event)
    summary_after = svc.list_economics()[0]
    assert summary_after.known_correction_count == 1
    assert summary_after.failures == 1
    assert summary_after.verified_successes == 4


# ---------------------------------------------------------------------------
# Test 29: Observed CPS Distinct From Expected CPS Under Insufficient Evidence (Directive 8)
# ---------------------------------------------------------------------------


def test_29_observed_cps_distinct_from_expected_cps():
    svc = EconomicsService()
    model = ModelIdentity(provider_id="mock", model_id="insuf-model")

    # Only 2 tasks (< 5) with success: observed CPS can be computed, but expected CPS is None
    for i in range(2):
        t_id = f"t_ins_{i}"
        att = AttemptEconomicsRecord(
            execution_id=f"e_i_{i}",
            logical_task_id=t_id,
            model_identity=model,
            provider_id="mock",
            cost=Money.from_usd(0.01),
            outcome=TaskOutcome.SUCCESS,
        )
        svc.record_attempt(att)
        svc.complete_logical_task(
            logical_task_id=t_id,
            initial_model_identity=model,
            initial_provider_id="mock",
            final_outcome=TaskOutcome.SUCCESS,
        )

    summary = svc.list_economics()[0]
    assert summary.logical_tasks_count == 2
    assert summary.verified_successes == 2
    assert summary.observed_cost_per_verified_success is not None
    assert summary.observed_cost_per_verified_success.amount_micros == 10000
    assert summary.status == EvidenceSufficiencyStatus.INSUFFICIENT_EVIDENCE
    assert summary.expected_cost_per_success is None
    assert summary.expected_cost_per_success_provenance == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# Test 30: Golden Eval Markdown Report Generated and Thesis Proven (Directive 9)
# ---------------------------------------------------------------------------


def test_30_golden_eval_markdown_report_generated():
    report_md = generate_golden_eval_markdown_report()
    assert "Agent Engine R3.10 Golden Evaluation Report" in report_md
    assert "Mathematical Thesis & Proven Proof" in report_md
    assert "0.018" in report_md
    assert "0.030" in report_md
    assert "66.7% higher Cost-Per-Success" in report_md


# ---------------------------------------------------------------------------
# Test 31: API Exposes Expected CPS, Provenance, and Known Correction Count (Directive 10)
# ---------------------------------------------------------------------------


def test_31_api_exposes_expected_cps_and_provenance(test_client):
    svc = build_golden_eval_service()
    from services.python.server.routers import models as models_router

    orig_svc = models_router.get_economics_service
    models_router.get_economics_service = lambda: svc
    try:
        resp = test_client.get(
            "/v1/models/economics",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        first = data[0]
        assert "expected_cost_per_success" in first
        assert "expected_cost_per_success_provenance" in first
        assert "known_correction_count" in first
        assert "evaluable_tasks_count" in first
        assert "sufficiency_policy_version" in first
    finally:
        models_router.get_economics_service = orig_svc
