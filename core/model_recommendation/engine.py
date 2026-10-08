"""core/model_recommendation/engine.py

Authoritative, side-effect-free Local Model Recommendation Engine.
Part of Milestone R3 Task R3.5 (Local Model Catalog and Recommendation).

Invariants:
1. Pure Function: Zero downloads, zero process spawning, zero configuration mutations.
2. Hard Exclusions Before Scoring: Incompatible runtimes, architectures, accelerators,
   capabilities, or models requiring more memory than safe capacity are immediately rejected.
3. Separation of Concerns: CapabilityEligibility, HardwareFitResult, and LocalModelRecommendation
   remain completely separate domain evaluations.
4. Privacy & Anti-Fingerprinting: Privacy-safe explanations expose byte memory and core counts
   with zero hostnames, usernames, private paths, or serial numbers.
5. Deterministic Tiers: FAST, BALANCED, and BEST_LOCAL are selected purely from factual catalog
   and resource facts. When no candidate satisfies a tier, recommendation is None.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from core.model_recommendation.catalog import LocalModelCatalog
from core.model_recommendation.models import (
    CapabilityEligibility,
    CatalogModelEntry,
    HardwareFitResult,
    HardwareFitState,
    LocalModelRecommendation,
    LocalRecommendationResponse,
    RecommendationExplanation,
    RecommendationTier,
    RequirementsProvenance,
    TaskRequirements,
)
from core.model_recommendation.policy import (
    ReservePolicy,
    calculate_kv_context_overhead,
    calculate_safe_available_ram,
    calculate_safe_available_vram,
)
from core.model_registry.models import TriStateBool
from core.resources.models import ProbeStatus, ResourceSnapshot

logger = logging.getLogger("agent_engine.inference.recommendation")


def evaluate_capability_eligibility(
    model: CatalogModelEntry,
    requirements: TaskRequirements,
) -> CapabilityEligibility:
    """Evaluate whether a catalog model satisfies functional task requirements."""
    missing: List[str] = []
    rejections: List[str] = []

    # Check context limit
    if model.context_window_limit < requirements.min_context_tokens:
        msg = (
            f"Context window {model.context_window_limit} tokens is below required "
            f"{requirements.min_context_tokens} tokens."
        )
        missing.append("context_window")
        rejections.append(msg)

    # Check boolean capability requirements
    checks = [
        ("coding", requirements.coding),
        ("reasoning", requirements.reasoning),
        ("vision", requirements.vision),
        ("tools", requirements.tools),
        ("structured_output", requirements.structured_output),
    ]

    for cap_name, is_required in checks:
        if is_required:
            cap_val = model.capabilities.get(cap_name, TriStateBool.UNKNOWN)
            if cap_val != TriStateBool.TRUE:
                missing.append(cap_name)
                rejections.append(
                    f"Requires {cap_name}=TRUE, but model capability is {cap_val.value}."
                )

    return CapabilityEligibility(
        eligible=len(missing) == 0,
        missing_capabilities=missing,
        rejection_reasons=rejections,
    )


def evaluate_hardware_fit(
    model: CatalogModelEntry,
    snapshot: ResourceSnapshot,
    requirements: TaskRequirements,
    policy: ReservePolicy,
) -> HardwareFitResult:
    """Evaluate physical hardware feasibility of running a model against host resources."""
    rejection_reasons: List[str] = []

    # 1. Architecture compatibility check
    host_arch = snapshot.architecture.lower()
    if model.supported_architectures and host_arch not in [
        a.lower() for a in model.supported_architectures
    ]:
        rejection_reasons.append(
            f"Host architecture '{host_arch}' not in model supported architectures: {model.supported_architectures}"
        )
        return HardwareFitResult(
            state=HardwareFitState.DOES_NOT_FIT,
            safe_ram_available_bytes=0,
            required_ram_bytes=model.min_ram_bytes,
            ram_headroom_bytes=0,
            ram_headroom_ratio=0.0,
            accelerator_compatible=False,
            rejection_reasons=rejection_reasons,
            explanation="Incompatible CPU architecture.",
        )

    # 2. Check memory telemetry certainty
    if snapshot.memory.status != ProbeStatus.KNOWN:
        rejection_reasons.append(
            f"Memory telemetry probe status is {snapshot.memory.status.value}; cannot guarantee safety."
        )
        return HardwareFitResult(
            state=HardwareFitState.UNKNOWN,
            safe_ram_available_bytes=0,
            required_ram_bytes=model.min_ram_bytes,
            ram_headroom_bytes=0,
            ram_headroom_ratio=0.0,
            provenance=RequirementsProvenance.UNKNOWN,
            rejection_reasons=rejection_reasons,
            explanation="Unknown memory telemetry; UNKNOWN is never a safe default.",
        )

    # 3. Compute safe available RAM after reserves
    safe_ram = calculate_safe_available_ram(snapshot.memory.available_bytes, policy=policy)
    kv_overhead = calculate_kv_context_overhead(
        requirements.min_context_tokens, model.parameter_count_billions
    )
    total_min_ram_required = model.min_ram_bytes + kv_overhead + policy.runtime_base_reserve_bytes
    total_rec_ram_required = (
        model.recommended_ram_bytes + kv_overhead + policy.runtime_base_reserve_bytes
    )

    # 4. Accelerator / Unified Memory Evaluation
    is_unified = False
    best_vram: Optional[int] = None
    has_discrete_gpu = False

    for acc in snapshot.accelerators:
        if acc.is_unified_memory or (
            snapshot.platform == "darwin" and host_arch in ("arm64", "aarch64")
        ):
            is_unified = True
        elif acc.available_memory_bytes is not None:
            has_discrete_gpu = True
            v = acc.available_memory_bytes
            best_vram = max(best_vram or 0, v)

    # Invariant: If unified memory, dedicated VRAM is None (they are ONE pool, never added!)
    safe_vram = calculate_safe_available_vram(
        best_vram, is_unified_memory=is_unified, policy=policy
    )

    # Explicit accelerator requirement check
    acc_compatible = True
    if requirements.required_accelerator:
        req_acc = requirements.required_accelerator.lower()
        matching = [
            a
            for a in snapshot.accelerators
            if req_acc in a.backend.lower()
            or req_acc in a.vendor.lower()
            or (req_acc == "gpu" and a.total_memory_bytes)
        ]
        if not matching:
            acc_compatible = False
            rejection_reasons.append(
                f"Required accelerator '{requirements.required_accelerator}' not available on host."
            )

    # 5. Fit State Determination
    ram_headroom_bytes = safe_ram - total_min_ram_required
    ram_headroom_ratio = ram_headroom_bytes / max(1, safe_ram) if safe_ram > 0 else 0.0

    if not acc_compatible:
        fit_state = HardwareFitState.DOES_NOT_FIT
        explanation = "Required accelerator not present."
    elif safe_ram < total_min_ram_required:
        fit_state = HardwareFitState.DOES_NOT_FIT
        deficit_mb = round((total_min_ram_required - safe_ram) / (1024 * 1024), 1)
        rejection_reasons.append(
            f"Insufficient safe RAM: required {total_min_ram_required // (1024 * 1024)}MB (including reserves/KV), "
            f"but safe available is {safe_ram // (1024 * 1024)}MB (deficit: {deficit_mb}MB)."
        )
        explanation = f"Model requires {total_min_ram_required // (1024 * 1024)}MB RAM; machine has {safe_ram // (1024 * 1024)}MB safe available."
    elif (
        safe_ram < total_rec_ram_required or ram_headroom_ratio < policy.min_headroom_balanced_ratio
    ):
        fit_state = HardwareFitState.FITS_WITH_LIMITS
        explanation = (
            f"Fits with limits: safe available RAM {safe_ram // (1024 * 1024)}MB satisfies minimum {total_min_ram_required // (1024 * 1024)}MB "
            f"with {round(ram_headroom_ratio * 100, 1)}% headroom."
        )
    else:
        fit_state = HardwareFitState.FITS
        explanation = (
            f"Fits comfortably: safe available RAM {safe_ram // (1024 * 1024)}MB provides {round(ram_headroom_ratio * 100, 1)}% headroom "
            f"over recommended {total_rec_ram_required // (1024 * 1024)}MB requirement."
        )

    return HardwareFitResult(
        state=fit_state,
        safe_ram_available_bytes=safe_ram,
        required_ram_bytes=total_rec_ram_required
        if fit_state == HardwareFitState.FITS
        else total_min_ram_required,
        ram_headroom_bytes=ram_headroom_bytes,
        ram_headroom_ratio=max(0.0, min(1.0, ram_headroom_ratio)),
        available_vram_bytes=safe_vram,
        required_vram_bytes=model.min_vram_bytes,
        is_unified_memory=is_unified,
        accelerator_compatible=acc_compatible,
        backend_used="gpu" if (has_discrete_gpu or is_unified) and acc_compatible else "cpu",
        provenance=model.provenance,
        rejection_reasons=rejection_reasons,
        explanation=explanation,
    )


def recommend_local_models(
    catalog: Optional[LocalModelCatalog] = None,
    snapshot: Optional[ResourceSnapshot] = None,
    requirements: Optional[TaskRequirements] = None,
    policy: Optional[ReservePolicy] = None,
) -> LocalRecommendationResponse:
    """Pure, side-effect-free model recommendation algorithm.

    Deterministic Tier Policy:
    - FAST: Smallest / lowest-cost capable model with strong headroom (>= min_headroom_fast_ratio).
    - BALANCED: Stronger capable model with comfortable headroom (>= min_headroom_balanced_ratio).
    - BEST_LOCAL: Strongest capable model that safely fits detected hardware.
    - When no candidate satisfies a tier, recommendation is None. Never forces three answers.
    """
    cat = catalog or LocalModelCatalog()
    pol = policy or ReservePolicy()
    req = requirements or TaskRequirements()

    if snapshot is None:
        return LocalRecommendationResponse(
            evaluated_candidates_count=0,
            snapshot_timestamp=0.0,
            stale_telemetry=True,
        )

    all_models = cat.get_all_models()
    evaluated_count = len(all_models)
    rejection_summary: Dict[str, List[str]] = {}
    qualified_candidates: List[Tuple[CatalogModelEntry, HardwareFitResult]] = []

    for model in all_models:
        model_name = model.model_identity.canonical_id

        # 1. Hard Exclusion: Check functional capability eligibility
        eligibility = evaluate_capability_eligibility(model, req)
        if not eligibility.eligible:
            rejection_summary[model_name] = eligibility.rejection_reasons
            continue

        # 2. Hard Exclusion: Check physical hardware feasibility
        fit_result = evaluate_hardware_fit(model, snapshot, req, pol)
        if fit_result.state in (HardwareFitState.DOES_NOT_FIT, HardwareFitState.UNKNOWN):
            rejection_summary[model_name] = fit_result.rejection_reasons
            continue

        qualified_candidates.append((model, fit_result))

    if not qualified_candidates:
        return LocalRecommendationResponse(
            evaluated_candidates_count=evaluated_count,
            snapshot_timestamp=snapshot.captured_at,
            stale_telemetry=snapshot.stale,
            rejection_summary=rejection_summary,
        )

    # Privacy-safe resource representation
    factual_resources = {
        "platform": snapshot.platform,
        "architecture": snapshot.architecture,
        "cpu_logical_cores": snapshot.cpu.logical_cores,
        "available_ram_bytes": snapshot.memory.available_bytes,
        "total_ram_bytes": snapshot.memory.total_bytes,
        "is_unified_memory": any(a.is_unified_memory for a in snapshot.accelerators)
        or (snapshot.platform == "darwin" and snapshot.architecture in ("arm64", "aarch64")),
        "accelerators": [
            {
                "vendor": a.vendor,
                "device_name": a.device_name,
                "backend": a.backend,
                "total_memory_bytes": a.total_memory_bytes,
            }
            for a in snapshot.accelerators
        ],
    }

    reserves_used = {
        "os_reserve_bytes": pol.os_reserve_bytes,
        "agent_engine_reserve_bytes": pol.agent_engine_reserve_bytes,
        "runtime_base_reserve_bytes": pol.runtime_base_reserve_bytes,
    }

    # Deterministic Selection:
    # 1. BEST_LOCAL: Highest quality score among all qualified models
    best_candidate = max(
        qualified_candidates,
        key=lambda pair: (pair[0].quality_score, -pair[0].parameter_count_billions),
    )
    best_rec = LocalModelRecommendation(
        tier=RecommendationTier.BEST_LOCAL,
        model_identity=best_candidate[0].model_identity,
        fit_result=best_candidate[1],
        reason=f"Strongest capable model ({best_candidate[0].parameter_size}) that safely fits host memory.",
        model_entry=best_candidate[0],
    )

    # 2. FAST: Smallest / lowest resource footprint with strong headroom
    fast_eligible = [
        pair
        for pair in qualified_candidates
        if pair[1].ram_headroom_ratio >= pol.min_headroom_fast_ratio
    ]
    fast_rec: Optional[LocalModelRecommendation] = None
    if fast_eligible:
        fast_candidate = min(
            fast_eligible,
            key=lambda pair: (pair[0].parameter_count_billions, -pair[0].quality_score),
        )
        fast_rec = LocalModelRecommendation(
            tier=RecommendationTier.FAST,
            model_identity=fast_candidate[0].model_identity,
            fit_result=fast_candidate[1],
            reason=f"Lowest resource footprint ({fast_candidate[0].parameter_size}) with {round(fast_candidate[1].ram_headroom_ratio * 100, 1)}% headroom.",
            model_entry=fast_candidate[0],
        )

    # 3. BALANCED: Model with comfortable headroom between fast and best
    balanced_eligible = [
        pair
        for pair in qualified_candidates
        if pair[1].ram_headroom_ratio >= pol.min_headroom_balanced_ratio
    ]
    balanced_rec: Optional[LocalModelRecommendation] = None
    if balanced_eligible:
        # Prefer models in the sweet spot (3B - 7B range)
        balanced_candidate = max(
            balanced_eligible,
            key=lambda pair: (
                1.0 if 2.5 <= pair[0].parameter_count_billions <= 8.0 else 0.5,
                pair[0].quality_score,
            ),
        )
        balanced_rec = LocalModelRecommendation(
            tier=RecommendationTier.BALANCED,
            model_identity=balanced_candidate[0].model_identity,
            fit_result=balanced_candidate[1],
            reason=f"Optimal balance of capability and resource efficiency ({balanced_candidate[0].parameter_size}).",
            model_entry=balanced_candidate[0],
        )

    # Build explanations for each tier
    explanations: Dict[str, RecommendationExplanation] = {}
    for tier_enum, rec_obj in [
        (RecommendationTier.FAST, fast_rec),
        (RecommendationTier.BALANCED, balanced_rec),
        (RecommendationTier.BEST_LOCAL, best_rec),
    ]:
        if rec_obj:
            m = rec_obj.model_entry
            kv = calculate_kv_context_overhead(req.min_context_tokens, m.parameter_count_billions)
            explanations[tier_enum.value] = RecommendationExplanation(
                selected_tier=tier_enum,
                model_identity=rec_obj.model_identity,
                hardware_fit=rec_obj.fit_result,
                snapshot_timestamp=snapshot.captured_at,
                stale_telemetry=snapshot.stale,
                factual_resources_used=factual_resources,
                requirements_used={
                    "min_ram_bytes": m.min_ram_bytes,
                    "recommended_ram_bytes": m.recommended_ram_bytes,
                    "kv_overhead_bytes": kv,
                    "runtime_base_reserve_bytes": pol.runtime_base_reserve_bytes,
                    "context_tokens_evaluated": req.min_context_tokens,
                },
                reserves_used=reserves_used,
                provenance=m.provenance,
                rejection_reasons={
                    name: reasons
                    for name, reasons in rejection_summary.items()
                    if name != rec_obj.model_identity.canonical_id
                },
            )

    return LocalRecommendationResponse(
        fast=fast_rec,
        balanced=balanced_rec,
        best_local=best_rec,
        explanations=explanations,
        rejection_summary=rejection_summary,
        evaluated_candidates_count=evaluated_count,
        snapshot_timestamp=snapshot.captured_at,
        stale_telemetry=snapshot.stale,
    )
