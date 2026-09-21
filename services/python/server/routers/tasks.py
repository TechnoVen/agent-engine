"""services/python/server/routers/tasks.py

Tasks API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse


# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_storage_backend,
)
from services.python.server.dependencies import verify_ipc_token
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.tasks")
router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=ScheduledTaskListResponse)
async def list_scheduled_tasks():
    """List all scheduled recurring agent tasks."""
    backend = get_storage_backend()
    tasks = backend.list_scheduled_tasks()
    return ScheduledTaskListResponse(tasks=[ScheduledTaskResponse(**t) for t in tasks])


@router.post("/tasks", response_model=ScheduledTaskResponse)
async def create_scheduled_task_endpoint(req: ScheduledTaskCreateRequest, request: Request):
    """Create and persist a new scheduled task."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    task_data = req.model_dump()
    created = backend.create_scheduled_task(task_data)
    return ScheduledTaskResponse(**created)


@router.post("/tasks/{task_id}/toggle", response_model=ScheduledTaskResponse)
async def toggle_scheduled_task_endpoint(
    task_id: str, req: ScheduledTaskToggleRequest, request: Request
):
    """Toggle a scheduled task status (active/paused)."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    updated = backend.update_scheduled_task_status(task_id, req.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return ScheduledTaskResponse(**updated)


@router.post("/tasks/{task_id}/run")
async def trigger_scheduled_task_endpoint(task_id: str, request: Request):
    """Trigger an immediate execution of a scheduled task."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    task = backend.get_scheduled_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error_code": "RUNTIME_NOT_AVAILABLE",
            "status": "deferred",
            "target_milestone": "R4",
            "message": f"Scheduled task execution runtime for '{task_id}' is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Task persistence and scheduling configuration are supported in R1.",
            "detail": f"Scheduled task execution runtime for '{task_id}' is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Task persistence and scheduling configuration are supported in R1.",
        },
    )


@router.delete("/tasks/{task_id}")
async def delete_scheduled_task_endpoint(task_id: str, request: Request):
    """Delete a scheduled task."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    deleted = backend.delete_scheduled_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"status": "deleted", "task_id": task_id}
