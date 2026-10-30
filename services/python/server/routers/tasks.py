"""services/python/server/routers/tasks.py

Tasks API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request, status
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
async def trigger_scheduled_task_endpoint(
    task_id: str,
    request: Request,
    canonical: bool = Query(default=False),
):
    """Trigger execution of a scheduled task. Dispatches to canonical JobService when canonical=True or X-Canonical-Runtime header is set; otherwise preserves deferred R1/R4 contract (HTTP 501)."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    task = backend.get_scheduled_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    is_canonical = canonical or (
        request.headers.get("x-canonical-runtime", "").lower() in ("true", "1")
    )
    if is_canonical:
        from core.jobs.service import get_job_service

        job_service = get_job_service()
        job = job_service.submit_job(
            job_type="agent_task",
            payload={
                "task_id": task_id,
                "task_name": task.get("name"),
                "prompt": task.get("action") or task.get("prompt"),
                "action": task.get("action") or task.get("prompt"),
                "schedule": task.get("cron") or task.get("schedule"),
                "persona": task.get("persona"),
                "schedule_id": task_id,
            },
            priority=task.get("priority", 0) if isinstance(task.get("priority"), int) else 0,
        )
        return {
            "status": "enqueued",
            "task_id": task_id,
            "job_id": job.job_id,
            "job_status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "message": f"Task '{task_id}' dispatched to canonical JobService as job '{job.job_id}'.",
        }

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
