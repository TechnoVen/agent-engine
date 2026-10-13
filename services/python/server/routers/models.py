"""services/python/server/routers/models.py

Models API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

# Core domain imports
from core.cache import get_semantic_cache
from core.economics import (
    EvidenceSource,
    ModelEconomicsSummary,
    get_economics_service,
)
from core.providers.registry import get_provider_registry
from core.providers.verification.service import get_provider_verification_service
from core.eval import EvalSample, ModelEvalReport, ModelEvalSuite, get_golden_dataset
from core.model_download import DownloadStatus, get_download_manager
from core.model_recommendation import (
    CatalogModelEntry,
    LocalModelCatalog,
    LocalRecommendationResponse,
    TaskRequirements,
    recommend_local_models,
)
from core.model_registry.models import ModelIdentity
from core.resources import get_resource_manager
from core.router import (
    DEFAULT_TIER_MODELS,
    ExecutionRouter,
    ExecutionTier,
    StepProfile,
)
from core.safety import get_policy_engine

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_storage_backend,
)
from services.python.server.dependencies import verify_ipc_token
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.models")
router = APIRouter(tags=["models"])


@router.post("/cache/lookup", response_model=CacheLookupResponse)
async def lookup_cache(req: CacheLookupRequest):
    """Check semantic cache for a matching query with >= 0.95 similarity or exact match."""
    cache = get_semantic_cache()
    res = cache.lookup(
        query=req.query,
        namespace=req.namespace or "default",
        task_type=req.task_type,
        min_similarity=req.min_similarity if req.min_similarity is not None else 0.95,
    )
    return CacheLookupResponse(
        hit=res.hit,
        similarity=res.similarity,
        match_type=res.match_type,
        latency_ms=res.latency_ms,
        query=res.query,
        cached_response=res.entry.response if res.entry else None,
        entry_id=res.entry.entry_id if res.entry else None,
        task_type=res.entry.task_type if res.entry else None,
        created_at=res.entry.created_at if res.entry else None,
        tokens_saved=res.entry.tokens_saved if res.entry else 0,
        cost_saved_usd=res.entry.cost_saved_usd if res.entry else 0.0,
    )


@router.post("/cache/store", response_model=CacheStoreResponse, status_code=status.HTTP_201_CREATED)
async def store_cache(req: CacheStoreRequest):
    """Store a response in the semantic cache with dual-layer (exact + cosine) index."""
    cache = get_semantic_cache()
    try:
        entry = cache.store(
            query=req.query,
            response=req.response,
            task_type=req.task_type or "qa",
            ttl_seconds=req.ttl_seconds,
            namespace=req.namespace or "default",
            tokens_saved=req.tokens_saved or 0,
            cost_saved_usd=req.cost_saved_usd or 0.0,
            metadata=req.metadata or {},
        )
        return CacheStoreResponse(
            entry_id=entry.entry_id,
            stored=True,
            ttl_seconds=entry.ttl_seconds,
            task_type=entry.task_type,
            namespace=entry.namespace,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed storing cache entry: {str(e)}")


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_stats():
    """Retrieve semantic cache metrics, total entries, hit rate, and cost/tokens saved."""
    cache = get_semantic_cache()
    stats = cache.get_stats()
    return CacheStatsResponse(**stats.to_dict())


@router.post("/cache/clear", response_model=CacheClearResponse)
async def clear_cache(req: Optional[CacheClearRequest] = None):
    """Clear or prune expired entries from the semantic cache."""
    cache = get_semantic_cache()
    ns = req.namespace if req else None
    prune_only = req.prune_only if req else False

    if prune_only:
        pruned = cache.prune_expired()
        return CacheClearResponse(
            cleared=True,
            pruned_entries=pruned,
            message=f"Pruned {pruned} expired cache entries.",
        )
    else:
        cache.clear(namespace=ns)
        return CacheClearResponse(
            cleared=True,
            pruned_entries=0,
            message=f"Cache cleared successfully for namespace='{ns or 'all'}'.",
        )


@router.post("/eval/run", response_model=EvalRunResponse)
async def run_eval_endpoint(req: EvalRunRequest):
    """Run model evaluation suite against golden or custom dataset, computing cost-per-success and rankings."""
    suite = ModelEvalSuite()
    try:
        if req.custom_samples:
            samples = [
                EvalSample(
                    task_id=s.get("task_id", f"custom-{i}"),
                    task_type=req.task_type or "classification",
                    inputs=s.get("inputs", {}),
                    expected_output=s.get("expected_output"),
                    metric=s.get("metric", "exact"),
                )
                for i, s in enumerate(req.custom_samples)
            ]
        else:
            samples = get_golden_dataset(req.task_type or "classification")

        reports = suite.evaluate_models(
            model_names=req.model_names,
            dataset_or_task_type=samples,
            record=req.record_benchmark if req.record_benchmark is not None else True,
        )
        ranking = suite.rank_models(reports)
        return EvalRunResponse(
            task_type=req.task_type or "classification",
            reports=[r.to_dict() for r in reports],
            ranking=ranking.to_dict(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Eval run failed: {str(e)}"
        )


@router.get("/eval/rankings", response_model=EvalRankingResponse)
async def get_eval_rankings_endpoint(
    task_type: str = Query("classification", description="Task type to rank models for"),
):
    """Retrieve success-adjusted cost rankings from stored benchmarks for a given task type."""
    backend = get_storage_backend()
    benchmarks = backend.get_benchmarks(task_type=task_type)
    if not benchmarks:
        return EvalRankingResponse(
            task_type=task_type,
            ranked_models=[],
            recommended_model=None,
            frontier_baseline=None,
            savings_pct_vs_frontier=0.0,
        )

    reports = []
    for b in benchmarks:
        meta = b.get("metadata") or {}
        rep = ModelEvalReport(
            model_name=b["model_name"],
            task_type=b["task_type"],
            total_samples=meta.get("total_samples", 1),
            success_count=meta.get("success_count", 1),
            failure_count=0,
            success_rate=b["success_rate"],
            total_cost_usd=meta.get("total_cost_usd", 0.0),
            cost_per_success=b["cost_per_success"],
            avg_latency_ms=b["latency_ms"],
            p95_latency_ms=b["latency_ms"],
            total_tokens=meta.get("total_tokens", 0),
        )
        reports.append(rep)

    suite = ModelEvalSuite(storage=backend)
    ranking = suite.rank_models(reports)
    return EvalRankingResponse(**ranking.to_dict())


@router.get("/eval/benchmarks", response_model=EvalBenchmarksResponse)
async def get_eval_benchmarks_endpoint(
    task_type: Optional[str] = Query(None, description="Filter benchmarks by task type"),
):
    """Retrieve historical model evaluation benchmark runs."""
    backend = get_storage_backend()
    benchmarks = backend.get_benchmarks(task_type=task_type)
    return EvalBenchmarksResponse(
        benchmarks=benchmarks,
        total_count=len(benchmarks),
    )


@router.post("/router/route", response_model=RouteStepResponse)
async def route_step_endpoint(req: RouteStepRequest):
    """Classify a step according to multi-objective routing rules and resolve execution tier."""
    cache = get_semantic_cache()
    router = ExecutionRouter(cache=cache)
    step = StepProfile(
        step_name=req.step.step_name,
        is_deterministic=req.step.is_deterministic or False,
        is_cacheable=req.step.is_cacheable or False,
        requires_judgment=req.step.requires_judgment or False,
        complexity=req.step.complexity or "low",
        is_high_stakes=req.step.is_high_stakes or False,
        fallback_tier=ExecutionTier(req.step.fallback_tier)
        if req.step.fallback_tier
        else ExecutionTier.MID_MODEL,
        description=req.step.description or "",
        task_type=req.step.task_type,
        cache_namespace=req.step.cache_namespace or "default",
    )
    tier = router.route(step, req.inputs or {})
    resolved_model = router.resolve_model(tier, task_type=step.task_type)
    is_free = tier in (ExecutionTier.CODE, ExecutionTier.CACHE) or (
        resolved_model in ("local", "qwen2.5-coder", "llama3.2")
    )

    rationale = f"Step '{step.step_name}' classified as {tier.value} tier."
    if tier == ExecutionTier.CODE:
        rationale = "Deterministic logic executed in code (0 tokens, $0.00)."
    elif tier == ExecutionTier.CACHE:
        rationale = "Matched cache query (0 tokens, $0.00)."
    elif tier == ExecutionTier.FRONTIER_MODEL:
        rationale = "High-stakes or complex reasoning requires frontier model tier."

    return RouteStepResponse(
        step_name=step.step_name,
        tier=tier.value,
        resolved_model=resolved_model,
        rationale=rationale,
        is_free_tier=is_free,
    )


@router.get("/router/tiers", response_model=RouterTiersResponse)
async def get_router_tiers_endpoint():
    """Retrieve execution tiers, model allocations, and R3.9 multi-objective routing profiles."""
    tiers_map = {tier.value: models for tier, models in DEFAULT_TIER_MODELS.items()}
    guidelines = {
        "routing_objectives": "Multi-objective optimization: BALANCED, QUALITY_FIRST, COST_FIRST, LATENCY_FIRST.",
        "law_1_rule": "90% deterministic code/cache/small local model, 9% mid-tier, 1% frontier (advisory baseline).",
        "frontier_ceiling": "Max allowable frontier model steps is 10% in static pipeline ratio audits.",
        "context_target": "Average context per step < 8,000 tokens.",
    }
    return RouterTiersResponse(
        tiers=tiers_map,
        law_1_guidelines=guidelines,
    )


@router.get("/models/recommendations", response_model=LocalRecommendationResponse)
async def get_model_recommendations(
    task_type: Optional[str] = Query(None, description="Task type or domain"),
    coding: bool = Query(False, description="Require coding capability"),
    reasoning: bool = Query(False, description="Require reasoning capability"),
    vision: bool = Query(False, description="Require vision capability"),
    tools: bool = Query(False, description="Require tool calling capability"),
    structured_output: bool = Query(False, description="Require structured output capability"),
    min_context_tokens: int = Query(2048, ge=512, description="Minimum required context tokens"),
    require_local_only: bool = Query(True, description="Enforce local-only models"),
    required_accelerator: Optional[str] = Query(None, description="Required accelerator type"),
):
    """Retrieve deterministic local model recommendations (Fast, Balanced, Best Local) based on host hardware."""
    try:
        manager = get_resource_manager()
        snapshot = manager.get_snapshot()
        now = time.time()
        age = now - snapshot.captured_at
        warning: Optional[str] = None
        if age > 5.0 or snapshot.stale:
            try:
                snapshot = manager.get_snapshot(force_refresh=True)
            except Exception as exc:
                logger.warning("Failed to refresh stale resource snapshot: %s", exc)
                warning = f"Resource telemetry is stale ({age:.1f}s old); automatic refresh failed."

        reqs = TaskRequirements(
            task_type=task_type,
            coding=coding,
            reasoning=reasoning,
            vision=vision,
            tools=tools,
            structured_output=structured_output,
            min_context_tokens=min_context_tokens,
            require_local_only=require_local_only,
            required_accelerator=required_accelerator,
        )
        rec_res = recommend_local_models(snapshot=snapshot, requirements=reqs)
        if warning:
            rec_res.warning = warning
            rec_res.resource_stale = True
            rec_res.stale_telemetry = True
        return rec_res
    except Exception as e:
        logger.error("Failed to generate model recommendations: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate model recommendations: {str(e)}",
        )


@router.get("/models/catalog", response_model=List[CatalogModelEntry])
async def get_model_catalog():
    """Retrieve the curated local model catalog."""
    catalog = LocalModelCatalog()
    return catalog.get_all_models()


class StartModelDownloadRequest(BaseModel):
    model_id: str
    provider_id: str = "llamacpp"


@router.post(
    "/models/downloads", response_model=DownloadStatus, status_code=status.HTTP_202_ACCEPTED
)
async def start_model_download(req: StartModelDownloadRequest):
    """Start or resume a catalog-driven model download with single-flight locking."""
    catalog = LocalModelCatalog()
    ident = ModelIdentity(provider_id=req.provider_id, model_id=req.model_id)
    descriptor = catalog.get_artifact_descriptor(ident)
    if not descriptor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{req.model_id}' not found in curated local catalog. Arbitrary downloads rejected.",
        )
    policy_engine = get_policy_engine()
    decision = policy_engine.evaluate(
        tool_name="model_download",
        tool_args={
            "model_id": req.model_id,
            "provider_id": req.provider_id,
            "artifact_id": descriptor.artifact_id,
            "download_url": descriptor.source_url,
            "destination_filename": getattr(
                descriptor, "destination_filename", descriptor.artifact_id
            ),
        },
        context={
            "operation": "model_download",
            "model_id": req.model_id,
        },
    )
    if decision.is_denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "POLICY_BLOCKED",
                "reason": decision.reason or "Model download blocked by safety policy.",
                "policy_id": decision.matched_rule,
                "risk_score": decision.risk_score,
                "suggestion": decision.suggestion,
            },
        )
    if decision.requires_approval:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "APPROVAL_REQUIRED",
                "reason": decision.reason or "Model download requires approval.",
                "policy_id": decision.matched_rule,
                "risk_score": decision.risk_score,
                "suggestion": decision.suggestion,
            },
        )

    mgr = get_download_manager()
    try:
        return mgr.start_download(descriptor)
    except PermissionError as pe:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "POLICY_BLOCKED",
                "reason": str(pe),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to start model download: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start model download: {str(e)}",
        )


@router.get("/models/downloads", response_model=List[DownloadStatus])
async def list_model_downloads():
    """List all managed model download states and partial tasks."""
    mgr = get_download_manager()
    return mgr.list_downloads()


@router.get("/models/downloads/{artifact_id}", response_model=DownloadStatus)
async def get_model_download_status(artifact_id: str):
    """Inspect progress and verification state of a specific artifact."""
    mgr = get_download_manager()
    return mgr.get_status(artifact_id)


@router.post("/models/downloads/{artifact_id}/cancel")
async def cancel_model_download(artifact_id: str):
    """Signal an active model download to safely pause and flush partial progress."""
    mgr = get_download_manager()
    success = mgr.cancel_download(artifact_id)
    return {"artifact_id": artifact_id, "cancelled": success}


@router.get("/models/installed", response_model=List[DownloadStatus])
async def list_installed_models():
    """List verified local models ready for managed inference execution."""
    mgr = get_download_manager()
    return mgr.list_installed_models()


class StartManagedRuntimeRequest(BaseModel):
    model_id: str
    context_size: int = 4096
    gpu_layers: int = 0
    threads: Optional[int] = None


class ManagedRuntimeStatusResponse(BaseModel):
    state: str
    is_ready: bool = False
    pid: Optional[int] = None
    endpoint_url: Optional[str] = None
    model_loaded: Optional[str] = None
    latency_ms: Optional[float] = None
    last_checked_at: Optional[float] = None
    error_message: Optional[str] = None


@router.post("/models/runtime/start", response_model=ManagedRuntimeStatusResponse)
async def start_managed_runtime(req: StartManagedRuntimeRequest, request: Request):
    """Start or idempotently reuse a managed local llama.cpp runtime instance."""
    verify_ipc_token(request)
    mgr = get_download_manager()
    catalog = LocalModelCatalog()
    ident = ModelIdentity(provider_id="llamacpp", model_id=req.model_id)
    desc = catalog.get_artifact_descriptor(ident)
    artifact_id = (
        desc.artifact_id
        if desc
        else (req.model_id if req.model_id.endswith(".gguf") else f"{req.model_id}.gguf")
    )

    # 1. Resolve model file path
    final_p = mgr.storage.get_final_path(artifact_id)
    if not final_p.exists():
        alt_p = mgr.storage.get_final_path(req.model_id)
        if alt_p.exists():
            final_p = alt_p
        else:
            repo_p = Path.cwd() / "models" / artifact_id
            if not repo_p.exists():
                repo_p = Path.cwd() / "models" / req.model_id
            if repo_p.exists():
                final_p = repo_p
            elif (Path.home() / ".agent_engine" / "models" / artifact_id).exists():
                final_p = Path.home() / ".agent_engine" / "models" / artifact_id
            elif (Path.home() / ".agent_engine" / "models" / req.model_id).exists():
                final_p = Path.home() / ".agent_engine" / "models" / req.model_id
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Model artifact '{artifact_id}' not found. Please install the model before starting.",
                )

    # 2. Pre-flight validation
    from core.inference.validation import ModelArtifactValidator, ModelValidationError

    try:
        ModelArtifactValidator.validate(final_p)
    except ModelValidationError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model artifact validation failed: {ve}",
        )

    # 3. Build RuntimeSpec and start via supervisor
    from core.inference.models import RuntimeSpec
    from core.inference.supervisor import SupervisorError, get_local_inference_supervisor

    supervisor = get_local_inference_supervisor()
    spec = RuntimeSpec(
        model_identity=ident,
        model_path=str(final_p.resolve()),
        context_size=req.context_size or 4096,
        gpu_layers=req.gpu_layers or 0,
        threads=req.threads,
    )
    try:
        supervisor.start(spec)
    except SupervisorError as se:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start managed runtime: {se}",
        )

    health = supervisor.get_health()
    return ManagedRuntimeStatusResponse(
        state=health.state.value if hasattr(health.state, "value") else str(health.state),
        is_ready=health.is_ready,
        pid=health.pid,
        endpoint_url=health.endpoint_url,
        model_loaded=health.model_loaded,
        latency_ms=health.latency_ms,
        last_checked_at=health.last_checked_at,
        error_message=health.error_message,
    )


@router.post("/models/runtime/stop", response_model=ManagedRuntimeStatusResponse)
async def stop_managed_runtime(request: Request):
    """Stop the active managed local runtime instance with graceful termination."""
    verify_ipc_token(request)
    from core.inference.supervisor import get_local_inference_supervisor

    supervisor = get_local_inference_supervisor()
    supervisor.stop()
    health = supervisor.get_health()
    return ManagedRuntimeStatusResponse(
        state=health.state.value if hasattr(health.state, "value") else str(health.state),
        is_ready=health.is_ready,
        pid=health.pid,
        endpoint_url=health.endpoint_url,
        model_loaded=health.model_loaded,
        latency_ms=health.latency_ms,
        last_checked_at=health.last_checked_at,
        error_message=health.error_message,
    )


@router.get("/models/runtime/status", response_model=ManagedRuntimeStatusResponse)
async def get_managed_runtime_status(request: Request):
    """Inspect factual health and readiness of the managed local inference runtime."""
    verify_ipc_token(request)
    from core.inference.supervisor import get_local_inference_supervisor

    supervisor = get_local_inference_supervisor()
    health = supervisor.get_health()
    return ManagedRuntimeStatusResponse(
        state=health.state.value if hasattr(health.state, "value") else str(health.state),
        is_ready=health.is_ready,
        pid=health.pid,
        endpoint_url=health.endpoint_url,
        model_loaded=health.model_loaded,
        latency_ms=health.latency_ms,
        last_checked_at=health.last_checked_at,
        error_message=health.error_message,
    )


@router.get("/models/economics", response_model=List[ModelEconomicsSummary])
async def get_models_economics(
    request: Request,
    task_family: Optional[str] = Query(None, description="Filter by task family"),
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    model_id: Optional[str] = Query(None, description="Filter by model ID"),
    evidence_source: Optional[str] = Query(None, description="Filter by evidence source"),
    evaluator_version: Optional[str] = Query(None, description="Filter by evaluator version"),
    effective_privacy_class: Optional[str] = Query(
        None, description="Filter by effective privacy class"
    ),
):
    """Retrieve model economics summaries with whole-chain cost-per-success metrics."""
    verify_ipc_token(request)
    service = get_economics_service()
    src_enum = None
    if evidence_source:
        try:
            src_enum = EvidenceSource(evidence_source.upper())
        except ValueError:
            pass
    return service.list_economics(
        task_family=task_family,
        provider_id=provider_id,
        model_id=model_id,
        evidence_source=src_enum,
        evaluator_version=evaluator_version,
        effective_privacy_class=effective_privacy_class,
    )


@router.get("/providers", response_model=List[Dict[str, Any]])
async def list_providers_endpoint(
    request: Request,
    include_disabled: bool = Query(False),
):
    """List registered providers with configuration, health, and latest verification summary."""
    verify_ipc_token(request)
    reg = get_provider_registry()
    ver_svc = get_provider_verification_service()
    providers = reg.list_providers(include_disabled=include_disabled)

    results = []
    for p in providers:
        safe = p.to_safe_dict()
        ver = ver_svc.get_verification(p.provider_id)
        safe["verification"] = ver.to_safe_dict()
        results.append(safe)
    return results


@router.post(
    "/providers/{provider_id}/verify",
    response_model=ProviderConnectionVerificationResponse,
)
async def verify_provider_endpoint(
    request: Request,
    provider_id: str,
    payload: Optional[VerifyProviderRequest] = None,
):
    """Execute a real minimal provider operation verification probe (Task R3.11).

    Directives enforced:
    - Pins requested provider_id and model.
    - Zero fallback routing to other providers.
    - Passes PolicyEngine authorization gate.
    - Classified failure taxonomy with sanitized secret redaction.
    - Tagged as PROVIDER_VERIFICATION (excluded from R3.10 cohorts).
    """
    verify_ipc_token(request)
    ver_svc = get_provider_verification_service()
    model_id = payload.model_id if payload else None
    timeout = payload.timeout if payload else 5.0

    ver = ver_svc.verify_provider(provider_id=provider_id, model_id=model_id, timeout=timeout)
    return ProviderConnectionVerificationResponse(**ver.to_safe_dict())


@router.get(
    "/providers/{provider_id}/verification",
    response_model=ProviderConnectionVerificationResponse,
)
async def get_provider_verification_endpoint(
    request: Request,
    provider_id: str,
):
    """Retrieve the latest cached verification record for a provider."""
    verify_ipc_token(request)
    ver_svc = get_provider_verification_service()
    ver = ver_svc.get_verification(provider_id)
    return ProviderConnectionVerificationResponse(**ver.to_safe_dict())
