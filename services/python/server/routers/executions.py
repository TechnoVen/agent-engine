"""services/python/server/routers/executions.py

Executions API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse

# Core domain imports
from core.execution import (
    ExecutionCoordinator,
)
from core.ledger import (
    ExecutionLedgerService,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_execution_coordinator,
    get_ledger_service,
    get_storage_backend,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.executions")
router = APIRouter(tags=["executions"])


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution_endpoint(
    execution_id: str,
    req: Optional[CancelExecutionRequest] = None,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Canonical cancellation endpoint for in-flight or queued executions."""
    reason = req.reason if req and req.reason else "user_request"
    actor = req.actor if req and req.actor else "user"

    # 1. Inspect current execution state
    record = coordinator.get_execution(execution_id)
    if not record:
        active_exec = coordinator._active_executions.get(execution_id)
        if not active_exec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Execution '{execution_id}' not found",
            )
        status_val = (
            active_exec.status.value
            if hasattr(active_exec.status, "value")
            else str(active_exec.status)
        )
    else:
        status_val = record.get("status")

    # 2. Terminal state conflict check: completed/partial/terminal cannot become cancelled
    if status_val in ("completed", "partial", "blocked", "failed", "timed_out"):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error_code": "TERMINAL_STATE_CONFLICT",
                "detail": f"Execution already terminated with status '{status_val}'",
                "status": status_val,
                "execution_id": execution_id,
            },
        )

    # 3. Idempotent check: already cancelled
    if status_val == "cancelled":
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "execution_id": execution_id,
                "status": "cancelled",
                "cancellation_requested": False,
                "message": "Execution already cancelled",
            },
        )

    # 4. Invoke coordinator.cancel
    try:
        res = coordinator.cancel(execution_id, reason=reason, actor=actor)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(val_err),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=res,
    )


@router.get("/executions")
async def list_recent_executions_endpoint(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    project_id: Optional[str] = Query(None),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """List recent executions across projects with factual provenance."""
    backend = coordinator.storage
    if hasattr(backend, "list_executions"):
        records = backend.list_executions(project_id=project_id, limit=limit, offset=offset)
        return JSONResponse(content=records)
    return JSONResponse(content=[])


@router.get("/executions/{execution_id}")
async def get_execution_endpoint(
    execution_id: str,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Retrieve execution details by ID."""
    record = coordinator.get_execution(execution_id)
    if not record:
        active_exec = coordinator._active_executions.get(execution_id)
        if active_exec:
            record = active_exec.model_dump()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )
    return JSONResponse(content=record)


@router.get("/executions/{execution_id}/events")
async def get_execution_events_endpoint(
    execution_id: str,
    after_sequence_num: Optional[int] = Query(None),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Retrieve durable events recorded for an execution."""
    record = coordinator.get_execution(execution_id)
    if not record and execution_id not in coordinator._active_executions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )
    events = coordinator.get_execution_events(execution_id, after_sequence_num=after_sequence_num)
    return JSONResponse(content={"execution_id": execution_id, "events": events})


@router.get("/projects/{project_id}/executions")
async def list_project_executions_endpoint(
    project_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ledger_service: ExecutionLedgerService = Depends(get_ledger_service),
):
    """List execution summaries belonging to a project."""
    backend = get_storage_backend()
    if hasattr(backend, "get_project") and not backend.get_project(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    summaries = ledger_service.list_project_executions(project_id, limit=limit, offset=offset)
    return JSONResponse(content=[s.to_dict() for s in summaries])


@router.get("/events")
async def stream_events():
    """Subscribe to real-time Server-Sent Events (SSE)."""
    client_queue: asyncio.Queue = asyncio.Queue()
    _event_subscribers.append(client_queue)

    async def event_stream() -> AsyncGenerator[str, None]:
        # Initial connection acknowledgement
        init_event = {
            "event": "agent_status",
            "agent_name": "engine_core",
            "status": "idle",
            "timestamp": datetime.datetime.now().isoformat(),
        }
        yield f"data: {json.dumps(init_event)}\n\n"
        try:
            while True:
                data = await client_queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if client_queue in _event_subscribers:
                _event_subscribers.remove(client_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
