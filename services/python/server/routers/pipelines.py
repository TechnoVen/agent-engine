"""services/python/server/routers/pipelines.py

Pipelines API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

# Core domain imports
from core.cases import get_case_manager
from core.execution import (
    ExecutionCoordinator,
    ExecutionRequest,
    ExecutionStatus,
)
from core.pipelines import get_pipeline_registry
from core.router import (
    ExecutionTier,
    StepProfile,
    audit_pipeline,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_execution_coordinator,
    get_storage_backend,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.pipelines")
router = APIRouter(tags=["pipelines"])


@router.get("/pipelines", response_model=List[PipelineInfo])
async def list_pipelines():
    """List registered modular DSPy agent pipelines."""
    registry = get_pipeline_registry()
    return [PipelineInfo(**meta.to_dict()) for meta in registry.list_pipelines()]


@router.get("/pipelines/{name}", response_model=PipelineInfo)
async def get_pipeline_details(name: str):
    """Get metadata for a specific registered DSPy agent pipeline."""
    registry = get_pipeline_registry()
    meta = registry.get_metadata(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline '{name}' not found in registry.",
        )
    return PipelineInfo(**meta.to_dict())


@router.post("/pipelines/{name}/run", response_model=PipelineRunResponse)
async def run_pipeline(
    name: str,
    req: PipelineRunRequest,
    x_project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Execute a registered DSPy agent pipeline via the canonical ExecutionCoordinator."""
    registry = get_pipeline_registry()
    meta = registry.get_metadata(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline '{name}' not found in registry.",
        )
    effective_project_id = (
        req.project_id
        or (req.inputs.get("project_id") if isinstance(req.inputs, dict) else None)
        or x_project_id
    )
    if not effective_project_id or effective_project_id in ("default", "proj_default"):
        storage = get_storage_backend()
        default_proj = storage.get_default_project()
        if default_proj:
            effective_project_id = default_proj["id"]
        else:
            effective_project_id = "default"
    effective_session_id = req.session_id or (
        req.inputs.get("session_id") if isinstance(req.inputs, dict) else None
    )

    clean_inputs = dict(req.inputs) if isinstance(req.inputs, dict) else {}
    exec_req = ExecutionRequest(
        task_type="pipeline",
        prompt=str(
            clean_inputs.get("prompt")
            or clean_inputs.get("code")
            or clean_inputs.get("brief")
            or clean_inputs.get("document_text")
            or clean_inputs.get("outline")
            or f"Execute pipeline {name}"
        ),
        inputs={
            "pipeline_name": name,
            "pipeline_inputs": clean_inputs,
            **clean_inputs,
        },
        project_id=effective_project_id,
        session_id=effective_session_id,
    )

    coordinator.pipeline_registry = registry

    try:
        result = await coordinator.execute(exec_req)
        if result.status == ExecutionStatus.BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Execution of pipeline '{name}' blocked: {result.error}",
            )
        if result.status == ExecutionStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Execution of pipeline '{name}' cancelled: {result.error}",
            )
        if result.status == ExecutionStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Execution of pipeline '{name}' failed: {result.error}",
            )
        return PipelineRunResponse(
            pipeline=name,
            outputs=result.outputs,
            execution_id=result.execution_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution of pipeline '{name}' failed: {e}",
        )


@router.get("/cases", response_model=List[ModeCasesInfo])
async def list_curated_cases(
    query: Optional[str] = Query(None, description="Search term across curated cases"),
    mode: Optional[str] = Query(None, description="Filter by capability mode"),
):
    """List curated featured case templates across capability modes."""
    manager = get_case_manager()
    if query:
        matched = manager.search(query, mode=mode)
        return [
            ModeCasesInfo(
                mode=mode or "search",
                title=f"Search: '{query}'",
                tagline=f"Found {len(matched)} curated cases matching '{query}'",
                badge="Search",
                pipeline="default",
                categories=["All"],
                cases=[
                    FeaturedCaseInfo(**(c.model_dump() if hasattr(c, "model_dump") else c.dict()))
                    for c in matched
                ],
            )
        ]

    configs = (
        [manager.get_mode_config(mode)]
        if mode and manager.get_mode_config(mode)
        else manager.list_all_modes()
    )
    return [
        ModeCasesInfo(**(c.model_dump() if hasattr(c, "model_dump") else c.dict()))
        for c in configs
        if c
    ]


@router.get("/cases/{mode}", response_model=ModeCasesInfo)
async def get_curated_mode_cases(mode: str):
    """Retrieve curated case configuration for a specific capability mode."""
    manager = get_case_manager()
    conf = manager.get_mode_config(mode)
    if not conf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No curated cases configured for mode '{mode}'.",
        )
    dumped = conf.model_dump() if hasattr(conf, "model_dump") else conf.dict()
    return ModeCasesInfo(**dumped)


@router.post("/router/audit", response_model=AuditPipelineResponse)
async def audit_pipeline_endpoint(req: AuditPipelineRequest):
    """Audit an agent workflow against Law 1 (The 90/9/1 Rule)."""
    step_profiles = [
        StepProfile(
            step_name=s.step_name,
            is_deterministic=s.is_deterministic or False,
            is_cacheable=s.is_cacheable or False,
            requires_judgment=s.requires_judgment or False,
            complexity=s.complexity or "low",
            is_high_stakes=s.is_high_stakes or False,
            fallback_tier=ExecutionTier(s.fallback_tier)
            if s.fallback_tier
            else ExecutionTier.MID_MODEL,
            description=s.description or "",
            task_type=s.task_type,
            cache_namespace=s.cache_namespace or "default",
        )
        for s in req.steps
    ]
    audit_res = audit_pipeline(step_profiles)
    return AuditPipelineResponse(**audit_res.to_dict())
