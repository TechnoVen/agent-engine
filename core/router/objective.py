"""core/router/objective.py

Multi-Attribute Quality/Cost/Latency Routing Optimizer for Agent Engine.
Part of Milestone R3 Task R3.9 (Quality/cost/latency routing objective).

Design Invariants:
1. Hard Constraints Before Scoring: Capabilities, privacy, and provider availability act as strict
   binary exclusions. Prohibited models (e.g. cloud models under LOCAL_ONLY) never enter scoring.
2. Evidence-Based Quality: Derived from empirical task-family benchmarks or curated policies; zero brand/size bias.
3. Unit-Aware Pricing & True Zero: Free local models have factual price = 0; missing is UNKNOWN, never $0.00.
4. Latency Observation: Prefers live telemetry when fresh/reliable; missing is UNKNOWN, never fastest.
5. Health Signal: Unavailable/Auth-failed excluded; Degraded receives explicit utility penalty.
6. Metric Normalization: Comparable metrics mapped to bounded utilities in [0.0, 1.0].
7. Deterministic Tie-Breaking: Strict multi-stage tie-breaker invariant under candidate array shuffling.
8. Fallback Invariance: Ranked feasible candidates form the fallback chain; LOCAL_ONLY fallback contains 0 cloud models.
9. Zero Secret Leakage: Never includes credentials, tokens, or auth headers in traces or decisions.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Union

from core.execution.models import RoutingTier
from core.model_registry.models import (
    ModelDefinition,
    ModelRequirements,
)
from core.privacy.engine import PrivacyPolicyEngine
from core.privacy.models import (
    DataRoutingClass,
    EffectiveRoutingPolicy,
    NoEligibleModelUnderPrivacyPolicyError,
)
from core.providers.models import ProviderHealthStatus
from core.router.circuit_breaker import CircuitBreaker
from core.router.health import HealthProber
from core.router.models import (
    CostEvidence,
    HealthEvidence,
    LatencyEvidence,
    QualityEvidence,
    RoutingCandidate,
    RoutingDecision,
    RoutingMetrics,
    RoutingObjective,
    RoutingObjectiveProfile,
    RoutingRejection,
    RoutingScore,
)

logger = logging.getLogger("agent_engine.router.objective")


class RoutingOptimizer:
    """Constrained, deterministic, explainable multi-objective model routing optimizer."""

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreaker] = None,
        health_prober: Optional[HealthProber] = None,
    ) -> None:
        self.circuit_breaker = circuit_breaker
        self.health_prober = health_prober

    def optimize(
        self,
        candidates: Sequence[ModelDefinition],
        requirements: Optional[ModelRequirements] = None,
        effective_policy: Optional[EffectiveRoutingPolicy] = None,
        objective: Optional[Union[RoutingObjective, RoutingObjectiveProfile, str]] = None,
        task_type: Optional[str] = None,
        storage: Optional[Any] = None,
        estimated_input_tokens: int = 1000,
        estimated_output_tokens: int = 500,
        provider_health_map: Optional[Dict[str, ProviderHealthStatus]] = None,
        economics_service: Optional[Any] = None,
    ) -> RoutingDecision:
        """Execute the complete constrained multi-objective optimization pipeline.

        Pipeline:
        1. Mandatory Capability Constraints Filtering
        2. Privacy Policy Constraints Filtering (R3.8)
        3. Provider Health & Circuit Breaker Availability Filtering
        4. Budget / Latency Ceiling Constraints Filtering
        5. Feasible Candidate Set Evaluation
        6. Multi-Attribute Utility Scoring
        7. Deterministic Multi-Stage Tie-Breaking
        8. Decision & Fallback Chain Synthesis
        """
        now = time.time()
        # Resolve objective
        if objective is None:
            routing_obj = RoutingObjective.from_profile(RoutingObjectiveProfile.BALANCED)
        elif isinstance(objective, (RoutingObjectiveProfile, str)):
            routing_obj = RoutingObjective.from_profile(objective)
        else:
            routing_obj = objective

        eff_privacy_class = (
            effective_policy.effective_class.value
            if effective_policy
            else DataRoutingClass.ANY_CONFIGURED.value
        ).upper()
        policy_source = effective_policy.source.value if effective_policy else "default"

        rejections: List[RoutingRejection] = []
        feasible: List[ModelDefinition] = []

        # ======================================================================
        # STAGE 1, 2, 3, 4: Hard Constraints Exclusions Pipeline
        # ======================================================================
        for model in candidates:
            pid = model.provider_id
            mid = model.model_id

            # 1. Capability constraints check (R3.2)
            if requirements is not None:
                cap_checks = [
                    ("reasoning", requirements.require_reasoning),
                    ("coding", requirements.require_coding),
                    ("vision", requirements.require_vision),
                    ("tools", requirements.require_tools),
                    ("structured_output", requirements.require_structured_output),
                    ("embeddings", requirements.require_embeddings),
                    ("streaming", requirements.require_streaming),
                ]
                failed_cap = False
                for cap_name, req_val in cap_checks:
                    if req_val is True:
                        sat, err = model.capabilities.satisfies_requirement(cap_name, True)
                        if not sat:
                            rejections.append(
                                RoutingRejection(
                                    model_id=mid,
                                    provider_id=pid,
                                    stage="CAPABILITY",
                                    reason=err or f"Missing required capability '{cap_name}'",
                                )
                            )
                            failed_cap = True
                            break
                if failed_cap:
                    continue

                # Context window constraints
                if requirements.min_total_tokens is not None:
                    if model.max_total_context_tokens < requirements.min_total_tokens:
                        rejections.append(
                            RoutingRejection(
                                model_id=mid,
                                provider_id=pid,
                                stage="CAPABILITY",
                                reason=f"Total context {model.max_total_context_tokens} < required {requirements.min_total_tokens}",
                            )
                        )
                        continue

            # 2. Privacy policy constraints check (R3.8)
            if effective_policy is not None:
                priv_elig = PrivacyPolicyEngine.evaluate_model_privacy(model, effective_policy)
                if not priv_elig.eligible:
                    reasons_str = ", ".join(r.value for r in priv_elig.rejection_reasons)
                    rejections.append(
                        RoutingRejection(
                            model_id=mid,
                            provider_id=pid,
                            stage="PRIVACY",
                            reason=f"Prohibited under privacy policy '{effective_policy.effective_class.value}': {reasons_str}",
                        )
                    )
                    continue

            # 3. Provider Health & Circuit Breaker Availability check (R3.1)
            if self.circuit_breaker is not None:
                if not self.circuit_breaker.can_attempt(pid):
                    rejections.append(
                        RoutingRejection(
                            model_id=mid,
                            provider_id=pid,
                            stage="HEALTH",
                            reason=f"Circuit breaker for provider '{pid}' is OPEN",
                        )
                    )
                    continue

            # Check provider health status map if provided
            if provider_health_map:
                h_status = provider_health_map.get(pid, ProviderHealthStatus.HEALTHY)
                val_str = getattr(h_status, "value", str(h_status)).lower()
                if h_status in (
                    ProviderHealthStatus.UNHEALTHY,
                    ProviderHealthStatus.AUTHENTICATION_FAILED,
                ) or val_str in ("unavailable", "unhealthy", "authentication_failed"):
                    rejections.append(
                        RoutingRejection(
                            model_id=mid,
                            provider_id=pid,
                            stage="HEALTH",
                            reason=f"Provider '{pid}' health status is {val_str}",
                        )
                    )
                    continue
            elif self.health_prober is not None:
                probe = self.health_prober._cache.get(pid)
                if probe is not None:
                    probe_age = now - (probe.checked_at or 0.0)
                    if probe_age <= 10.0 and not probe.online:
                        rejections.append(
                            RoutingRejection(
                                model_id=mid,
                                provider_id=pid,
                                stage="HEALTH",
                                reason=f"Provider '{pid}' health prober check failed: {probe.error or 'offline'}",
                            )
                        )
                        continue

            # 4. Budget / Latency Ceiling Constraints
            if routing_obj.max_cost_dollars is not None and not model.pricing.is_free:
                in_cost = model.pricing.input_cost_per_million
                out_cost = model.pricing.output_cost_per_million or in_cost
                if in_cost is not None and out_cost is not None:
                    cost_est = (
                        estimated_input_tokens * in_cost + estimated_output_tokens * out_cost
                    ) / 1_000_000.0
                    if cost_est > routing_obj.max_cost_dollars:
                        rejections.append(
                            RoutingRejection(
                                model_id=mid,
                                provider_id=pid,
                                stage="BUDGET",
                                reason=f"Estimated cost ${cost_est:.4f} exceeds ceiling ${routing_obj.max_cost_dollars:.4f}",
                            )
                        )
                        continue

            if routing_obj.max_latency_ms is not None:
                lat_val = model.latency.effective_latency_ms
                if lat_val is not None and lat_val > routing_obj.max_latency_ms:
                    rejections.append(
                        RoutingRejection(
                            model_id=mid,
                            provider_id=pid,
                            stage="BUDGET",
                            reason=f"Estimated latency {lat_val:.1f}ms exceeds ceiling {routing_obj.max_latency_ms:.1f}ms",
                        )
                    )
                    continue

            # Passed all hard constraints -> candidate is feasible!
            feasible.append(model)

        # ======================================================================
        # STAGE 5: Feasible Set Verification
        # ======================================================================
        if not feasible:
            # Check if all models failed due to privacy
            privacy_rejections = [r for r in rejections if r.stage == "PRIVACY"]
            if (
                effective_policy
                and effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY
                and privacy_rejections
                and not any(r.stage != "PRIVACY" for r in rejections)
            ):
                raise NoEligibleModelUnderPrivacyPolicyError(
                    "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: No local model available and cloud fallback forbidden under LOCAL_ONLY",
                    rejection_details=[r.model_dump() for r in privacy_rejections],
                )

            return RoutingDecision(
                selected_model=None,
                provider_id="none",
                routing_tier=RoutingTier.LOCAL,
                objective_profile=routing_obj.profile.value,
                objective_weights={
                    "w_quality": routing_obj.w_quality,
                    "w_cost": routing_obj.w_cost,
                    "w_latency": routing_obj.w_latency,
                    "w_health": routing_obj.w_health,
                },
                effective_privacy_class=eff_privacy_class,
                policy_source=policy_source,
                eligible_candidates=[],
                rejected_candidates=rejections,
                decision_reason="No eligible models survived hard constraints pipeline.",
                timestamp=now,
            )

        # ======================================================================
        # STAGE 6: Multi-Attribute Utility Scoring
        # ======================================================================
        scored_candidates: List[RoutingCandidate] = []
        incomplete_data_warnings: List[str] = []

        for model in feasible:
            pid = model.provider_id
            mid = model.model_id
            tier = self._infer_tier(model)

            # 1. Quality Evidence
            quality_ev = self._collect_quality_evidence(model, task_type=task_type, storage=storage)

            # 2. Cost Evidence
            cost_ev = self._collect_cost_evidence(
                model,
                input_tokens=estimated_input_tokens,
                output_tokens=estimated_output_tokens,
                routing_obj=routing_obj,
                task_type=task_type,
                effective_privacy_class=eff_privacy_class,
                economics_service=economics_service,
            )

            # 3. Latency Evidence
            latency_ev = self._collect_latency_evidence(model)

            # 4. Health Evidence
            health_ev = self._collect_health_evidence(model, provider_health_map)

            metrics = RoutingMetrics(
                quality=quality_ev,
                cost=cost_ev,
                latency=latency_ev,
                health=health_ev,
            )

            # Compute Normalized Utilities in [0.0, 1.0]
            uncertainty_penalty = 0.0

            # Quality utility
            if quality_ev.is_known and quality_ev.score is not None:
                quality_util = max(0.0, min(1.0, quality_ev.score))
            else:
                # Unknown quality: neutral utility with uncertainty penalty
                quality_util = 0.50
                uncertainty_penalty += 0.10
                incomplete_data_warnings.append(
                    f"{model.canonical_id}: Quality UNKNOWN (used neutral 0.5 utility)"
                )

            # Cost utility
            if cost_ev.is_free:
                cost_util = 1.0
            elif cost_ev.is_cost_per_success and (
                cost_ev.cost_per_success_micros is not None
                or cost_ev.cost_per_success_usd is not None
            ):
                # Invert cost per success: 0 is 1.0, ceiling is 0.0 using exact integer micros ratio (Directive 5)
                cost_micros = (
                    cost_ev.cost_per_success_micros
                    if cost_ev.cost_per_success_micros is not None
                    else int(round(cost_ev.cost_per_success_usd * 1_000_000))
                )
                ceiling_micros = getattr(
                    routing_obj,
                    "cps_norm_ceiling_micros",
                    int(round(getattr(routing_obj, "cps_norm_ceiling_usd", 0.10) * 1_000_000)),
                )
                if ceiling_micros <= 0:
                    ceiling_micros = 100_000
                cost_norm = min(1.0, max(0.0, cost_micros / ceiling_micros))
                cost_util = max(0.0, min(1.0, 1.0 - cost_norm))
            elif cost_ev.is_known and cost_ev.expected_cost_usd is not None:
                # Invert request cost: 0.0 is 1.0, ceiling is 0.0
                cost_norm = cost_ev.expected_cost_usd / max(
                    0.001, routing_obj.cost_norm_ceiling_usd
                )
                cost_util = max(0.0, min(1.0, 1.0 - cost_norm))
            elif cost_ev.is_known and cost_ev.catalog_price_proxy is not None:
                # Invert catalog price proxy: 0.0 is 1.0, ceiling is 0.0
                proxy_ceiling = getattr(routing_obj, "price_proxy_norm_ceiling", 20.0)
                cost_norm = cost_ev.catalog_price_proxy / max(0.1, proxy_ceiling)
                cost_util = max(0.0, min(1.0, 1.0 - cost_norm))
            else:
                # Unknown cost: conservative utility with uncertainty penalty
                cost_util = 0.35
                uncertainty_penalty += 0.15
                incomplete_data_warnings.append(
                    f"{model.canonical_id}: Pricing UNKNOWN (used conservative 0.35 utility)"
                )

            # Latency utility
            if latency_ev.is_known and latency_ev.latency_ms is not None:
                lat_norm = latency_ev.latency_ms / max(100.0, routing_obj.latency_norm_ceiling_ms)
                latency_util = max(0.0, min(1.0, 1.0 - lat_norm))
            else:
                # Unknown latency: neutral utility with uncertainty penalty
                latency_util = 0.50
                uncertainty_penalty += 0.10
                incomplete_data_warnings.append(
                    f"{model.canonical_id}: Latency UNKNOWN (used neutral 0.5 utility)"
                )

            # Health utility
            if health_ev.status == ProviderHealthStatus.HEALTHY:
                health_util = 1.0
            elif health_ev.is_degraded or health_ev.status == ProviderHealthStatus.DEGRADED:
                health_util = 0.60  # Explicit health penalty
            elif health_ev.status == ProviderHealthStatus.UNKNOWN:
                health_util = 0.70  # Explicit penalty for unknown/stale health so stale HEALTHY is never an advantage
                uncertainty_penalty += 0.05
            else:
                health_util = 0.80

            # Total weighted multi-attribute score
            raw_total = (
                routing_obj.w_quality * quality_util
                + routing_obj.w_cost * cost_util
                + routing_obj.w_latency * latency_util
                + routing_obj.w_health * health_util
            ) - uncertainty_penalty

            final_score = max(0.0, min(1.0, raw_total))

            score_obj = RoutingScore(
                quality_utility=round(quality_util, 4),
                cost_utility=round(cost_util, 4),
                latency_utility=round(latency_util, 4),
                health_utility=round(health_util, 4),
                uncertainty_penalty=round(uncertainty_penalty, 4),
                total_score=round(final_score, 6),
                score_breakdown={
                    "w_quality * u_quality": round(routing_obj.w_quality * quality_util, 4),
                    "w_cost * u_cost": round(routing_obj.w_cost * cost_util, 4),
                    "w_latency * u_latency": round(routing_obj.w_latency * latency_util, 4),
                    "w_health * u_health": round(routing_obj.w_health * health_util, 4),
                    "uncertainty_deduction": round(uncertainty_penalty, 4),
                },
                explanation=(
                    f"Profile '{routing_obj.profile.value}': score={final_score:.4f} "
                    f"[Q={quality_util:.2f}, C={cost_util:.2f}, L={latency_util:.2f}, H={health_util:.2f}]"
                ),
            )

            cand = RoutingCandidate(
                identity=model.identity,
                provider_id=pid,
                model_id=mid,
                routing_tier=tier,
                metrics=metrics,
                score=score_obj,
                eligible=True,
                rejection_reasons=[],
            )
            scored_candidates.append(cand)

        # ======================================================================
        # STAGE 7: Deterministic Multi-Stage Tie-Breaking
        # ======================================================================
        # Invariant: Stable under candidate shuffling, dictionary order, or DB row order
        def sort_key(c: RoutingCandidate):
            score = c.score.total_score if c.score else 0.0
            q_conf = c.metrics.quality.confidence
            # Lower cost preferred
            c_cost = (
                0.0
                if c.metrics.cost.is_free
                else (
                    c.metrics.cost.cost_per_success_usd
                    if c.metrics.cost.is_cost_per_success
                    and c.metrics.cost.cost_per_success_usd is not None
                    else (
                        c.metrics.cost.expected_cost_usd
                        if c.metrics.cost.expected_cost_usd is not None
                        else (c.metrics.cost.catalog_price_proxy or 999.0)
                    )
                )
            )
            # Lower latency preferred
            c_lat = (
                c.metrics.latency.latency_ms
                if c.metrics.latency.latency_ms is not None
                else 99999.0
            )

            # Round total score to 5 decimal places to recognize ties
            rounded_score = round(score, 5)

            return (
                -rounded_score,  # Higher score first
                -q_conf,  # Higher quality confidence first
                c_cost,  # Lower cost first
                c_lat,  # Lower latency first
                c.provider_id,  # Alphabetical provider
                c.model_id,  # Alphabetical model
            )

        ranked = sorted(scored_candidates, key=sort_key)
        winner = ranked[0]

        tie_break_applied = False
        tie_break_reason = None
        if len(ranked) > 1:
            first_s = ranked[0].score.total_score if ranked[0].score else 0.0
            second_s = ranked[1].score.total_score if ranked[1].score else 0.0
            if abs(first_s - second_s) < 1e-5:
                tie_break_applied = True
                first_c = (
                    ranked[0].metrics.cost.expected_cost_usd
                    if ranked[0].metrics.cost.expected_cost_usd is not None
                    else (ranked[0].metrics.cost.catalog_price_proxy or 0.0)
                )
                second_c = (
                    ranked[1].metrics.cost.expected_cost_usd
                    if ranked[1].metrics.cost.expected_cost_usd is not None
                    else (ranked[1].metrics.cost.catalog_price_proxy or 0.0)
                )
                tie_break_reason = (
                    f"Deterministic tie-break between '{ranked[0].canonical_id}' and '{ranked[1].canonical_id}': "
                    f"confidence ({ranked[0].metrics.quality.confidence:.2f} vs {ranked[1].metrics.quality.confidence:.2f}), "
                    f"cost (${first_c:.4f} vs ${second_c:.4f}), "
                    f"canonical '{ranked[0].canonical_id}'"
                )

        # Build decision explanation
        explanation = (
            f"Selected '{winner.canonical_id}' under '{routing_obj.profile.value}' objective "
            f"(Score: {winner.score.total_score:.4f} from {len(ranked)} eligible candidates; "
            f"{len(rejections)} excluded by hard constraints)."
        )
        if tie_break_applied:
            explanation += f" [Tie-break: {tie_break_reason}]"

        warning_str = "; ".join(incomplete_data_warnings) if incomplete_data_warnings else None

        return RoutingDecision(
            selected_model=winner.identity,
            provider_id=winner.provider_id,
            routing_tier=winner.routing_tier,
            objective_profile=routing_obj.profile.value,
            objective_weights={
                "w_quality": routing_obj.w_quality,
                "w_cost": routing_obj.w_cost,
                "w_latency": routing_obj.w_latency,
                "w_health": routing_obj.w_health,
            },
            effective_privacy_class=eff_privacy_class,
            policy_source=policy_source,
            eligible_candidates=ranked,
            rejected_candidates=rejections,
            selected_candidate=winner,
            final_score=winner.score.total_score if winner.score else None,
            decision_reason=explanation,
            tie_break_applied=tie_break_applied,
            tie_break_reason=tie_break_reason,
            incomplete_data_warning=warning_str,
            objective_policy_version="r3.9_v1",
            metric_normalization_version="bounded_threshold_v1",
            timestamp=now,
        )

    # --------------------------------------------------------------------------
    # Helper Metric Extractors
    # --------------------------------------------------------------------------

    def _collect_quality_evidence(
        self,
        model: ModelDefinition,
        task_type: Optional[str] = None,
        storage: Optional[Any] = None,
    ) -> QualityEvidence:
        """Extract factual quality evidence without brand or size bias."""
        task_family = task_type or "general"

        # 1. Check empirical benchmarks from storage if provided (task-family specific preferred)
        if storage is not None and hasattr(storage, "get_benchmarks"):
            try:
                benchmarks = storage.get_benchmarks(task_type=task_type)

                # Sort benchmarks to prioritize exact task_family match over general
                def bench_priority(b):
                    b_tf = b.get("task_family") or b.get("task_type") or "general"
                    return 0 if b_tf == task_family else 1

                sorted_benchmarks = sorted(benchmarks, key=bench_priority)

                for b in sorted_benchmarks:
                    b_model = (b.get("model_name") or b.get("model") or "").strip().lower()
                    if b_model in (
                        model.model_id.lower(),
                        model.canonical_id.lower(),
                        model.display_name.lower(),
                    ):
                        succ = float(
                            b.get("score")
                            if b.get("score") is not None
                            else b.get("success_rate", 0.0)
                        )
                        meta = b.get("metadata", {})
                        conf = float(b.get("confidence", 0.90))
                        b_tf = b.get("task_family") or b.get("task_type") or task_family
                        return QualityEvidence(
                            score=succ,
                            task_family=b_tf,
                            eval_id=str(b.get("id", "benchmark")),
                            eval_version=str(b.get("version", "v1")),
                            sample_size=meta.get("sample_size"),
                            updated_at=b.get("created_at"),
                            captured_at=b.get("captured_at") or b.get("created_at"),
                            provenance="eval_benchmark",
                            confidence=conf,
                        )
            except Exception as e:
                logger.debug("Benchmark lookup failed: %s", e)

        # 2. Check model metadata for curated quality score or rank (fallback evidence only)
        curated_rank = model.metadata.get("curated_quality_rank")
        if curated_rank is not None:
            try:
                rank_f = float(curated_rank)
                score = min(1.0, max(0.0, rank_f / 10.0))
                return QualityEvidence(
                    score=score,
                    task_family=task_family,
                    provenance="curated_policy",
                    confidence=0.75,
                )
            except (ValueError, TypeError):
                pass

        explicit_score = model.metadata.get("quality_score")
        if explicit_score is not None:
            try:
                return QualityEvidence(
                    score=float(explicit_score),
                    task_family=task_family,
                    provenance="curated_policy",
                    confidence=0.70,
                )
            except (ValueError, TypeError):
                pass

        # 3. Unknown quality (Never infer quality from model size, provider brand, or capabilities)
        return QualityEvidence(
            score=None,
            task_family=task_family,
            provenance="unknown",
            confidence=0.0,
        )

    def _collect_cost_evidence(
        self,
        model: ModelDefinition,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        routing_obj: Optional[RoutingObjective] = None,
        task_type: Optional[str] = None,
        effective_privacy_class: Optional[str] = None,
        economics_service: Optional[Any] = None,
    ) -> CostEvidence:
        """Extract request-level token pricing facts, empirical cost-per-success, or catalog price proxy."""
        r_obj = routing_obj or RoutingObjective()
        cost_metric_pref = getattr(r_obj, "cost_metric", "COST_PER_SUCCESS_WHEN_SUFFICIENT")
        metric_version = getattr(r_obj, "cost_metric_policy_version", "v1_cps_when_sufficient")

        # 1. Check empirical Cost-Per-Success (Directive 14 & 15)
        if cost_metric_pref == "COST_PER_SUCCESS_WHEN_SUFFICIENT" and economics_service is not None:
            eff_priv = effective_privacy_class or "ANY_CONFIGURED"
            cps_est = None
            if hasattr(economics_service, "get_expected_cps"):
                cps_est = economics_service.get_expected_cps(
                    model_identity=model.identity,
                    task_family=task_type or "general",
                    effective_privacy_class=eff_priv,
                )
            if (
                cps_est is not None
                and hasattr(cps_est, "status")
                and (
                    cps_est.status == "SUFFICIENT_EVIDENCE"
                    or getattr(cps_est.status, "value", None) == "SUFFICIENT_EVIDENCE"
                )
            ):
                return CostEvidence(
                    expected_cost_usd=None,
                    catalog_price_proxy=None,
                    cost_metric="COST_PER_SUCCESS_WHEN_SUFFICIENT",
                    cost_metric_policy_version=metric_version,
                    cost_per_success_usd=cps_est.estimated_cps.as_usd,
                    cost_per_success_micros=cps_est.estimated_cps.amount_micros,
                    cost_per_success_status="SUFFICIENT_EVIDENCE",
                    cost_per_success_sample_count=cps_est.sample_count,
                    cost_per_success_provenance=cps_est.provenance,
                    is_cost_per_success=True,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    is_free=cps_est.estimated_cps.amount_micros == 0,
                    is_price_proxy=False,
                    provenance="empirical_cost_per_success",
                )

        if model.pricing is None:
            return CostEvidence(
                expected_cost_usd=None,
                catalog_price_proxy=None,
                cost_metric="REQUEST_COST_OR_PRICE_PROXY",
                cost_metric_policy_version=metric_version,
                cost_per_success_status="INSUFFICIENT_EVIDENCE",
                cost_per_success_provenance="fallback_r3_9_missing_pricing",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                is_free=False,
                is_price_proxy=False,
                provenance="unknown",
            )

        if model.pricing.is_free:
            return CostEvidence(
                expected_cost_usd=0.0,
                catalog_price_proxy=0.0,
                cost_metric="REQUEST_COST_OR_PRICE_PROXY",
                cost_metric_policy_version=metric_version,
                cost_per_success_status="INSUFFICIENT_EVIDENCE",
                cost_per_success_provenance="fallback_r3_9_free_local",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_per_1m=0.0,
                output_cost_per_1m=0.0,
                is_free=True,
                is_price_proxy=False,
                provenance="free_local",
            )

        in_price = model.pricing.input_cost_per_million
        out_price = model.pricing.output_cost_per_million or in_price

        if in_price is not None and out_price is not None:
            # If explicit token estimates exist, compute request-aware expected cost
            if (
                input_tokens is not None
                and input_tokens > 0
                and output_tokens is not None
                and output_tokens > 0
            ):
                cost_usd = (input_tokens * in_price + output_tokens * out_price) / 1_000_000.0
                return CostEvidence(
                    expected_cost_usd=round(cost_usd, 6),
                    catalog_price_proxy=None,
                    cost_metric="REQUEST_COST_OR_PRICE_PROXY",
                    cost_metric_policy_version=metric_version,
                    cost_per_success_status="INSUFFICIENT_EVIDENCE",
                    cost_per_success_provenance="fallback_r3_9_request_estimate",
                    is_price_proxy=False,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    input_cost_per_1m=in_price,
                    output_cost_per_1m=out_price,
                    is_free=False,
                    provenance="estimated_tokens_unit_pricing",
                )
            else:
                # Without request token estimates, compute catalog price proxy
                price_proxy = round(0.75 * in_price + 0.25 * out_price, 4)
                return CostEvidence(
                    expected_cost_usd=None,
                    catalog_price_proxy=price_proxy,
                    price_proxy_policy_version="v1_0.75_0.25",
                    cost_metric="REQUEST_COST_OR_PRICE_PROXY",
                    cost_metric_policy_version=metric_version,
                    cost_per_success_status="INSUFFICIENT_EVIDENCE",
                    cost_per_success_provenance="fallback_r3_9_catalog_proxy",
                    is_price_proxy=True,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    input_cost_per_1m=in_price,
                    output_cost_per_1m=out_price,
                    is_free=False,
                    provenance="catalog_price_proxy",
                )

        # Unknown pricing: missing is never zero
        return CostEvidence(
            expected_cost_usd=None,
            catalog_price_proxy=None,
            cost_metric="REQUEST_COST_OR_PRICE_PROXY",
            cost_metric_policy_version=metric_version,
            cost_per_success_status="INSUFFICIENT_EVIDENCE",
            cost_per_success_provenance="fallback_r3_9_unknown",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            is_free=False,
            is_price_proxy=False,
            provenance="unknown",
        )

    def _collect_latency_evidence(self, model: ModelDefinition) -> LatencyEvidence:
        """Extract latency facts preferring live observation over static classification."""
        if model.latency is None:
            return LatencyEvidence(
                latency_ms=None,
                provenance="unknown",
                confidence=0.0,
            )

        now = time.time()

        # 1. Active health prober cache if available
        if self.health_prober is not None:
            probe = self.health_prober._cache.get(model.provider_id)
            if probe and probe.latency_ms > 0 and probe.online:
                return LatencyEvidence(
                    latency_ms=probe.latency_ms,
                    p50_ms=probe.latency_ms,
                    sample_count=1,
                    observed_at=probe.checked_at,
                    provenance="observed_telemetry",
                    confidence=0.85,
                )

        # 2. Observed metrics on latency profile
        obs = model.latency.observed_metrics
        if obs and obs.last_observed_ms is not None and obs.sample_count > 0:
            # Check freshness (< 300s)
            obs_time = obs.observed_at or 0.0
            if (now - obs_time) < 300.0:
                return LatencyEvidence(
                    latency_ms=obs.p50_ms or obs.last_observed_ms,
                    p50_ms=obs.p50_ms,
                    sample_count=obs.sample_count,
                    observed_at=obs_time,
                    provenance="observed_telemetry",
                    confidence=0.90,
                )
            else:
                # Stale latency: lower confidence
                return LatencyEvidence(
                    latency_ms=obs.p50_ms or obs.last_observed_ms,
                    p50_ms=obs.p50_ms,
                    sample_count=obs.sample_count,
                    observed_at=obs_time,
                    provenance="observed_telemetry",
                    confidence=0.40,
                )

        # 3. Static catalog baseline
        if model.latency.catalog_latency_ms is not None:
            return LatencyEvidence(
                latency_ms=model.latency.catalog_latency_ms,
                provenance="catalog_baseline",
                confidence=0.50,
            )

        # 4. Latency class fallback estimate (if known class)
        class_val = getattr(model.latency.catalog_latency_class, "value", "unknown")
        if class_val and class_val not in ("unknown", "None"):
            lat_map = {
                "fast": 800.0,
                "medium": 2000.0,
                "slow": 5000.0,
                "reasoning": 10000.0,
            }
            if class_val in lat_map:
                return LatencyEvidence(
                    latency_ms=lat_map[class_val],
                    provenance="catalog_baseline",
                    confidence=0.45,
                )

        # Unknown latency
        return LatencyEvidence(
            latency_ms=None,
            provenance="unknown",
            confidence=0.0,
        )

    def _collect_health_evidence(
        self,
        model: ModelDefinition,
        health_map: Optional[Dict[str, ProviderHealthStatus]] = None,
    ) -> HealthEvidence:
        """Extract operational provider health status."""
        pid = model.provider_id
        circuit = "CLOSED"
        if self.circuit_breaker is not None:
            circuit = self.circuit_breaker.get_state(pid).value

        now = time.time()
        status = ProviderHealthStatus.HEALTHY
        if health_map and pid in health_map:
            status = health_map[pid]
        elif self.health_prober is not None:
            probe = self.health_prober._cache.get(pid)
            if probe is not None:
                probe_age = now - (probe.checked_at or 0.0)
                if probe_age > 10.0:
                    status = ProviderHealthStatus.UNKNOWN
                elif not probe.online:
                    status = ProviderHealthStatus.UNAVAILABLE
                elif probe.latency_ms > 4000.0:
                    status = ProviderHealthStatus.DEGRADED
                else:
                    status = ProviderHealthStatus.HEALTHY

        is_degraded = status == ProviderHealthStatus.DEGRADED
        return HealthEvidence(
            status=status,
            is_degraded=is_degraded,
            degraded_reason="Latency or failure rate elevated" if is_degraded else None,
            circuit_state=circuit,
            checked_at=now,
        )

    def _infer_tier(self, model: ModelDefinition) -> RoutingTier:
        """Infer canonical routing tier from model identity."""
        pid = model.provider_id.lower()
        mid = model.model_id.lower()

        if pid in ("ollama", "llamacpp"):
            return RoutingTier.LOCAL
        elif pid == "local":
            return RoutingTier.CODE
        elif "gpt-4o" in mid and "mini" not in mid:
            return RoutingTier.FRONTIER
        elif "sonnet" in mid or "opus" in mid or "pro" in mid or "r1" in mid:
            return RoutingTier.FRONTIER
        return RoutingTier.MID
