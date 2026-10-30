"""services/python/server/routers/ledger.py

Ledger API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse

# Core domain imports
from core.ledger import (
    ExecutionLedgerService,
    LedgerSecurityError,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_ledger_service,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.ledger")
router = APIRouter(tags=["ledger"])


@router.get("/executions/{execution_id}/trace")
async def get_execution_trace_endpoint(
    execution_id: str,
    project_id: Optional[str] = Query(None),
    x_project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    ledger_service: ExecutionLedgerService = Depends(get_ledger_service),
):
    """Retrieve authoritative execution trace projection with project-scope integrity verification."""
    effective_project_id = project_id or x_project_id
    try:
        trace = ledger_service.get_execution_trace(execution_id, project_id=effective_project_id)
        if not trace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Execution '{execution_id}' not found",
            )
        return JSONResponse(content=trace.to_public_dict())
    except LedgerSecurityError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
