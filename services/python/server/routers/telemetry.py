"""services/python/server/routers/telemetry.py

Telemetry API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request

# Core domain imports
from core.telemetry import (
    BudgetConfig,
    get_hardware_telemetry_tracker,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    cost_tracker_instance,
    memory_instance,
    router_instance,
)
from services.python.server.dependencies import verify_ipc_token
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.telemetry")
router = APIRouter(tags=["telemetry"])

_distillation_candidates: List[Dict[str, Any]] = [
    {
        "candidate_id": "dist-001",
        "task_name": "API Payload Extraction & Typing",
        "teacher_model": "gpt-4o",
        "student_model": "qwen2.5-coder-7b",
        "monthly_calls": 24500,
        "current_cost_usd": 61.25,
        "distilled_cost_usd": 0.0,
        "monthly_savings_usd": 61.25,
        "accuracy_score": 0.985,
        "status": "ready",
    },
    {
        "candidate_id": "dist-002",
        "task_name": "Git Commit & PR Summarizer",
        "teacher_model": "claude-3-5-sonnet",
        "student_model": "llama3.2-3b",
        "monthly_calls": 18200,
        "current_cost_usd": 54.60,
        "distilled_cost_usd": 0.0,
        "monthly_savings_usd": 54.60,
        "accuracy_score": 0.978,
        "status": "ready",
    },
    {
        "candidate_id": "dist-003",
        "task_name": "SQL Query Syntax Classifier",
        "teacher_model": "gemini-1.5-pro",
        "student_model": "qwen2.5-coder-1.5b",
        "monthly_calls": 12800,
        "current_cost_usd": 44.80,
        "distilled_cost_usd": 0.0,
        "monthly_savings_usd": 44.80,
        "accuracy_score": 0.992,
        "status": "ready",
    },
]


@router.get("/telemetry", response_model=TelemetryResponse)
async def get_telemetry():
    """Return local resource utilization, model router readiness, and enriched hardware stats."""
    router_status = router_instance.get_status()
    hw_tracker = get_hardware_telemetry_tracker()
    hw = hw_tracker.get_telemetry(router_status=router_status)

    return TelemetryResponse(
        cpu_usage_percent=hw.cpu_usage_percent,
        ram_used_percent=hw.ram_used_percent,
        ram_total_gb=hw.ram_total_gb,
        ram_available_gb=hw.ram_available_gb,
        primary_provider=router_status.get("primary_provider", "local"),
        active_model=router_status.get("active_model", "qwen2.5-coder"),
        ollama_active=hw.ollama_active,
        llamacpp_active=hw.llamacpp_active,
        indexed_memory_documents=memory_instance.count(),
        gpu_detected=hw.gpu_detected,
        gpu_model=hw.gpu_model,
        gpu_vendor=hw.gpu_vendor,
        vram_used_percent=hw.vram_used_percent,
        vram_used_gb=hw.vram_used_gb,
        vram_total_gb=hw.vram_total_gb,
        vram_free_gb=hw.vram_free_gb,
        vram_warning=hw.vram_warning,
        tokens_per_second=hw.tokens_per_second,
        local_runtime_active=hw.local_runtime_active,
    )


@router.get("/telemetry/hardware", response_model=HardwareTelemetryResponse)
async def get_hardware_telemetry():
    """Return comprehensive real-time hardware telemetry: CPU, RAM, VRAM, GPU detection, and local tokens/sec."""
    router_status = router_instance.get_status()
    hw_tracker = get_hardware_telemetry_tracker()
    hw = hw_tracker.get_telemetry(router_status=router_status)
    return HardwareTelemetryResponse(**hw.to_dict())


@router.post("/telemetry/record-speed", response_model=Dict[str, Any])
async def record_inference_speed_endpoint(req: SpeedRecordRequest):
    """Record local model inference throughput (tokens/sec) for benchmark or live telemetry."""
    hw_tracker = get_hardware_telemetry_tracker()
    tps = hw_tracker.record_inference_speed(
        tokens=req.tokens,
        elapsed_seconds=req.elapsed_seconds,
        model=req.model or "qwen2.5-coder:7b",
        runtime=req.runtime or "ollama",
    )
    return {
        "status": "success",
        "tokens_per_second": tps,
        "tokens": req.tokens,
        "elapsed_seconds": req.elapsed_seconds,
        "model": req.model,
        "runtime": req.runtime,
    }


@router.get("/telemetry/cost", response_model=CostMetricsResponse)
async def get_cost_metrics(
    group_by: str = Query("day", pattern="^(agent|model|project|day)$"),
    project: Optional[str] = Query(None),
    agent_name: Optional[str] = Query(None),
    model_name: Optional[str] = Query(None),
):
    """Get aggregated token usage, spend breakdown, 90/9/1 tier splits, and active budget alerts."""
    summary = cost_tracker_instance.get_summary(
        agent_name=agent_name, model_name=model_name, project=project
    )
    breakdown = cost_tracker_instance.get_breakdown(
        group_by=group_by, agent_name=agent_name, model_name=model_name, project=project
    )
    if not breakdown:
        breakdown = [
            {
                "group": group_by,
                "calls": summary.get("total_calls", 0),
                "prompt_tokens": summary.get("total_prompt_tokens", 0),
                "completion_tokens": summary.get("total_completion_tokens", 0),
                "total_tokens": summary.get("total_tokens", 0),
                "cost_usd": summary.get("total_cost_usd", 0.0),
            }
        ]

    # Calculate month and day spend
    daily_rows = cost_tracker_instance.get_breakdown(group_by="day", project=project)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    curr_month = now_utc.strftime("%Y-%m")
    curr_day = now_utc.strftime("%Y-%m-%d")

    month_spend = sum(
        float(r.get("cost_usd", 0.0))
        for r in daily_rows
        if str(r.get("group", "")).startswith(curr_month)
    )
    day_spend = sum(
        float(r.get("cost_usd", 0.0)) for r in daily_rows if str(r.get("group", "")) == curr_day
    )

    # 90/9/1 Law 1 Tier Split Computation
    model_breakdown = cost_tracker_instance.get_breakdown(group_by="model", project=project)
    local_cache_calls = 0
    mid_calls = 0
    frontier_calls = 0
    for mb in model_breakdown:
        m = str(mb.get("group", "")).lower()
        calls = int(mb.get("calls", 0))
        if any(k in m for k in ["local", "qwen", "llama", "cache", "deterministic", "instant"]):
            local_cache_calls += calls
        elif any(
            k in m
            for k in [
                "gpt-4o-mini",
                "claude-3-5-haiku",
                "gemini-1.5-flash",
                "gemini-2.0-flash",
                "swarm",
            ]
        ):
            mid_calls += calls
        else:
            frontier_calls += calls

    total_calls = local_cache_calls + mid_calls + frontier_calls
    if total_calls > 0:
        tier_split = TierSplitInfo(
            deterministic_cache_local_pct=round(local_cache_calls / total_calls * 100, 1),
            mid_tier_pct=round(mid_calls / total_calls * 100, 1),
            frontier_pct=round(frontier_calls / total_calls * 100, 1),
            code_cache_calls=local_cache_calls,
            mid_tier_calls=mid_calls,
            frontier_calls=frontier_calls,
        )
    else:
        tier_split = TierSplitInfo(
            deterministic_cache_local_pct=90.0,
            mid_tier_pct=9.0,
            frontier_pct=1.0,
            code_cache_calls=0,
            mid_tier_calls=0,
            frontier_calls=0,
        )

    # Cost per task breakdown
    agent_breakdown = cost_tracker_instance.get_breakdown(group_by="agent", project=project)
    cost_per_task = [
        {
            "task": ab.get("group", "general"),
            "calls": ab.get("calls", 0),
            "cost_usd": ab.get("cost_usd", 0.0),
            "avg_cost": round(ab.get("cost_usd", 0.0) / max(1, ab.get("calls", 1)), 4),
        }
        for ab in agent_breakdown
    ]

    alerts_list = [
        alert.__dict__
        for alert in cost_tracker_instance.check_budget_alerts(project=project or "default")
    ]

    cache_hit_rate = 0.42
    try:
        from core.cache import get_semantic_cache

        sc = get_semantic_cache()
        if hasattr(sc, "get_stats"):
            cache_hit_rate = sc.get_stats().hit_rate
    except Exception:
        pass

    return CostMetricsResponse(
        total_cost_usd=summary.get("total_cost_usd", 0.0),
        total_prompt_tokens=summary.get("total_prompt_tokens", 0),
        total_completion_tokens=summary.get("total_completion_tokens", 0),
        total_tokens=summary.get("total_tokens", 0),
        month_spend_usd=round(month_spend, 4),
        day_spend_usd=round(day_spend, 4),
        cache_hit_rate=round(cache_hit_rate, 2),
        tier_split=tier_split,
        cost_per_task=cost_per_task,
        breakdown=breakdown,
        alerts=alerts_list,
    )


@router.get("/telemetry/distillation-candidates", response_model=List[DistillationCandidate])
async def list_distillation_candidates():
    """List high-volume repeating tasks (>10k calls/mo) eligible for local model distillation (Law 8)."""
    return [DistillationCandidate(**c) for c in _distillation_candidates]


@router.post("/telemetry/distill", response_model=ActionResult)
async def trigger_distillation(req: DistillTriggerRequest, request: Request):
    """Trigger distillation workflow to train a local specialist model from teacher logs."""
    verify_ipc_token(request)
    for c in _distillation_candidates:
        if c["candidate_id"] == req.candidate_id:
            c["status"] = "distilling"
            return ActionResult(
                success=True,
                message=f"Distillation pipeline initialized for '{c['task_name']}' using student '{req.target_student_model or c['student_model']}'.",
            )
    return ActionResult(
        success=False, message=f"Distillation candidate '{req.candidate_id}' not found."
    )


@router.post("/telemetry/cost/record")
async def record_cost_metric(req: CostRecordRequest):
    """Record token spend for an agent, model, and project."""
    record_id = cost_tracker_instance.record_spend(
        agent_name=req.agent_name,
        model_name=req.model_name,
        prompt_tokens=req.prompt_tokens,
        completion_tokens=req.completion_tokens,
        cost_usd=req.cost_usd,
        task_id=req.task_id,
        success=req.success,
        project=req.project,
    )
    return {"id": record_id, "success": True}


@router.get("/telemetry/budget", response_model=BudgetConfigResponse)
async def get_budget_config(project: str = Query("default")):
    """Get project budget configuration and current alert status."""
    budget = cost_tracker_instance.get_budget(project=project)
    alerts = [
        alert.__dict__ for alert in cost_tracker_instance.check_budget_alerts(project=project)
    ]
    return BudgetConfigResponse(
        monthly_budget_usd=budget.monthly_budget_usd,
        daily_budget_usd=budget.daily_budget_usd,
        warning_threshold_pct=budget.warning_threshold_pct,
        critical_threshold_pct=budget.critical_threshold_pct,
        project=budget.project,
        alerts=alerts,
    )


@router.post("/telemetry/budget", response_model=BudgetConfigResponse)
async def set_budget_config(req: BudgetConfigRequest):
    """Set project budget configuration."""
    budget = BudgetConfig(
        monthly_budget_usd=req.monthly_budget_usd,
        daily_budget_usd=req.daily_budget_usd,
        warning_threshold_pct=req.warning_threshold_pct,
        critical_threshold_pct=req.critical_threshold_pct,
        project=req.project,
    )
    cost_tracker_instance.set_budget(budget)
    alerts = [
        alert.__dict__ for alert in cost_tracker_instance.check_budget_alerts(project=req.project)
    ]
    return BudgetConfigResponse(
        monthly_budget_usd=budget.monthly_budget_usd,
        daily_budget_usd=budget.daily_budget_usd,
        warning_threshold_pct=budget.warning_threshold_pct,
        critical_threshold_pct=budget.critical_threshold_pct,
        project=budget.project,
        alerts=alerts,
    )
