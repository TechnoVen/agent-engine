"""services/python/server/routers/adapters.py

Adapters API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

# Core domain imports
from core.adapters import (
    get_adapter_registry,
)
from core.execution import (
    CancellationReason,
    ExecutionCoordinator,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_execution_coordinator,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.adapters")
router = APIRouter(tags=["adapters"])


@router.get("/adapters", response_model=List[Dict[str, Any]])
async def list_adapters_endpoint(include_health: bool = Query(False)):
    """List all registered agent adapters, their capabilities, and enabled status."""
    reg = get_adapter_registry()
    return reg.list_adapters(include_health=include_health)


@router.get("/adapters/{adapter_id}", response_model=Dict[str, Any])
async def get_adapter_endpoint(adapter_id: str):
    """Retrieve metadata and health status for a specific adapter."""
    reg = get_adapter_registry()
    adapter = reg.get(adapter_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adapter '{adapter_id}' not found",
        )
    meta = adapter.to_metadata_dict()
    meta["enabled"] = reg.is_enabled(adapter_id)
    try:
        health = adapter.health_check()
        meta["health"] = health.to_dict()
    except Exception as e:
        meta["health"] = {"status": "unavailable", "message": str(e), "latency_ms": 0.0}
    return meta


@router.post("/adapters/{adapter_id}/execute", response_model=Dict[str, Any])
async def execute_adapter_endpoint(
    adapter_id: str,
    payload: AdapterRunPayload,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Execute a prompt through the specified agent adapter via canonical ExecutionCoordinator."""
    reg = get_adapter_registry()
    if not reg.get(adapter_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adapter '{adapter_id}' not found",
        )
    if not reg.is_enabled(adapter_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Adapter '{adapter_id}' is disabled in Settings",
        )

    coordinator.adapter_registry = reg
    exec_req = ExecutionRequest(
        task_type="adapter",
        prompt=payload.prompt,
        inputs={
            "adapter_id": adapter_id,
            "model": payload.model,
            "temperature": payload.temperature,
            "max_tokens": payload.max_tokens,
            "timeout_seconds": payload.timeout_seconds or 60.0,
            "context": payload.context or {},
            "tools": payload.tools or [],
            "metadata": payload.metadata or {},
            "session_id": payload.session_id,
        },
        project_id="default",
        session_id=payload.session_id,
    )
    try:
        result = await coordinator.execute(exec_req)
        if result.status == ExecutionStatus.BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Execution of adapter '{adapter_id}' blocked: {result.error}",
            )
        if result.status == ExecutionStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Execution of adapter '{adapter_id}' cancelled: {result.error}",
            )
        if result.status == ExecutionStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Execution of adapter '{adapter_id}' failed: {result.error}",
            )
        return result.outputs
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/adapters/{adapter_id}/stream")
async def stream_adapter_endpoint(
    adapter_id: str,
    payload: AdapterRunPayload,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Stream token chunks and tool call events from the specified adapter via SSE through canonical ExecutionCoordinator."""
    reg = get_adapter_registry()
    if not reg.get(adapter_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adapter '{adapter_id}' not found",
        )
    if not reg.is_enabled(adapter_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Adapter '{adapter_id}' is disabled in Settings",
        )

    coordinator.adapter_registry = reg
    exec_req = ExecutionRequest(
        task_type="adapter",
        prompt=payload.prompt,
        inputs={
            "adapter_id": adapter_id,
            "stream": True,
            "model": payload.model,
            "temperature": payload.temperature,
            "max_tokens": payload.max_tokens,
            "timeout_seconds": payload.timeout_seconds or 60.0,
            "context": payload.context or {},
            "tools": payload.tools or [],
            "metadata": payload.metadata or {},
            "session_id": payload.session_id,
        },
        project_id="default",
        session_id=payload.session_id,
    )

    chunk_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

    def stream_event_listener(event: ExecutionEvent) -> None:
        if event.event_type == ExecutionEventType.OUTPUT_CHUNK:
            delta = event.payload.get("chunk") or event.payload.get("text") or ""
            chunk_queue.put_nowait({"type": "token", "delta": delta})
        elif event.event_type == ExecutionEventType.TOOL_CALL_STARTED:
            chunk_queue.put_nowait(
                {
                    "type": "tool_call",
                    "tool_call": {
                        "tool": event.payload.get("tool_id"),
                        "status": "started",
                    },
                }
            )

    async def run_coordinator():
        try:
            res = await coordinator.execute(exec_req, event_listener=stream_event_listener)
            if res.status == ExecutionStatus.FAILED:
                await chunk_queue.put(
                    {"type": "error", "error": res.error or "Adapter execution failed"}
                )
        except Exception as ex:
            logger.exception("Error in background adapter coordinator streaming task: %s", ex)
            await chunk_queue.put({"type": "error", "error": str(ex)})
        finally:
            await chunk_queue.put(None)

    coord_task = asyncio.create_task(run_coordinator())

    async def event_generator():
        try:
            while True:
                item = await chunk_queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            coordinator.cancel(
                exec_req.id, reason=CancellationReason.CLIENT_DISCONNECT, actor="client"
            )
            if not coord_task.done():
                coord_task.cancel()
            raise
        except Exception as e:
            err_data = json.dumps({"type": "error", "error": str(e)})
            yield f"data: {err_data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/adapters/{adapter_id}/test", response_model=Dict[str, Any])
async def test_adapter_endpoint(adapter_id: str):
    """Probe adapter connectivity, environment prerequisites, and latency."""
    reg = get_adapter_registry()
    adapter = reg.get(adapter_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adapter '{adapter_id}' not found",
        )
    try:
        health = adapter.health_check()
        return health.to_dict()
    except Exception as e:
        return {
            "status": "unavailable",
            "message": f"Test failed: {e}",
            "latency_ms": 0.0,
            "version": getattr(adapter, "version", None),
            "details": {"error": str(e)},
        }


@router.post("/channels/slack/events")
async def slack_events_webhook(request: Request):
    """Incoming webhook for Slack Events API and Socket Mode verification."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    # Handle Slack URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    reg = get_adapter_registry()
    adapter = reg.get("slack")
    if not adapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slack adapter not found")

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
        "envelope_ack": adapter.handle_socket_mode_envelope(body)
        if body.get("envelope_id")
        else None,
    }


@router.post("/channels/teams/activities")
async def teams_activities_webhook(request: Request):
    """Incoming webhook for Microsoft Teams Bot Framework Activities."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    reg = get_adapter_registry()
    adapter = reg.get("teams")
    if not adapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teams adapter not found")

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
    }


@router.post("/channels/discord/interactions")
async def discord_interactions_webhook(request: Request):
    """Incoming webhook for Discord Interactions and slash commands."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    # Discord Interaction Type 1: PING -> reply with PONG {"type": 1}
    if body.get("type") == 1:
        return {"type": 1}

    reg = get_adapter_registry()
    adapter = reg.get("discord")
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Discord adapter not found"
        )

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
    }


@router.post("/channels/mattermost/hooks")
async def mattermost_hooks_webhook(request: Request):
    """Incoming webhook for Mattermost slash commands, outgoing webhooks, and events."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    reg = get_adapter_registry()
    adapter = reg.get("mattermost")
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mattermost adapter not found"
        )

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
    }
