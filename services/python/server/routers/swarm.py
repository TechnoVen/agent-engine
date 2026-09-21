"""services/python/server/routers/swarm.py

Swarm API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

# Core domain imports
from core.workflows import (
    SwarmAgentSpec,
    SwarmCase,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_swarm_coordinator,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.swarm")
router = APIRouter(tags=["swarm"])


@router.get("/swarm/cases", response_model=List[SwarmCase])
async def list_swarm_cases_endpoint():
    """List featured multi-agent swarm team templates."""
    coordinator = get_swarm_coordinator()
    return coordinator.list_cases()


@router.post("/swarm/estimate")
async def estimate_swarm_cost_endpoint(req: SwarmEstimateRequest):
    """Estimate execution cost for a swarm team dispatch before running."""
    coordinator = get_swarm_coordinator()
    agents: List[SwarmAgentSpec] = []
    if req.agents:
        for a in req.agents:
            agents.append(SwarmAgentSpec.model_validate(a))
    elif req.case_id:
        c = coordinator.get_case(req.case_id)
        if c:
            agents = c.agents
    if not agents:
        agents = coordinator.list_cases()[0].agents

    est = coordinator.estimate_cost(agents, model_tier=req.model_tier)
    return {"estimated_cost_usd": est, "agent_count": len(agents), "model_tier": req.model_tier}


@router.post("/swarm/run")
async def run_swarm_endpoint(req: SwarmRunApiRequest):
    """Dispatch prompt to a parallel swarm of specialized agents and return aggregated results."""
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error_code": "RUNTIME_NOT_AVAILABLE",
            "status": "deferred",
            "target_milestone": "R4",
            "message": "Swarm multi-agent execution runtime is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Swarm team templates and cost estimation are supported in R1.",
            "detail": "Swarm multi-agent execution runtime is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Swarm team templates and cost estimation are supported in R1.",
        },
    )
