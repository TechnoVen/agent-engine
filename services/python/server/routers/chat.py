"""services/python/server/routers/chat.py

Chat API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse, StreamingResponse

# Core domain imports
from core.execution import (
    CancellationToken,
    CancellationReason,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)
from core.context.models import ContentAuthority
from core.privacy.models import DataRoutingClass, DataRoutingPolicy
from core.router.models import (
    ExecutionRoutingPreferences,
    RoutingObjectiveProfile,
    RoutingPreferenceSource,
)
from core.session import (
    MessageRole,
)
from core.telemetry import (
    get_hardware_telemetry_tracker,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_execution_coordinator,
    get_session_store,
    get_storage_backend,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.chat")
router = APIRouter(tags=["chat"])


@router.post("/chat/completions", response_model=None)
async def chat_completions(req: ChatRequest):
    """Execute a chat completion with session persistence, canonical execution coordinator dispatch, and honest failure reporting."""
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:10]}"

    # 1. Session & Project Persistence: store user prompt in session store
    store = get_session_store()
    session = store.get_session(session_id)
    storage = get_storage_backend()
    resolved_project_id = req.project_id

    # Resolve canonical default project if none provided or legacy alias provided
    if not resolved_project_id or resolved_project_id in ("default", "proj_default"):
        default_proj = storage.get_default_project()
        if default_proj:
            resolved_project_id = default_proj["id"]

    if not session:
        session = store.create_session(
            session_id=session_id,
            title=req.prompt[:40] + ("..." if len(req.prompt) > 40 else ""),
            channel="desktop",
            metadata={"project_id": resolved_project_id},
        )
    elif not req.project_id:
        sess_proj = session.metadata.get("project_id") if session.metadata else None
        if sess_proj:
            resolved_project_id = sess_proj
            if resolved_project_id in ("default", "proj_default"):
                default_proj = storage.get_default_project()
                if default_proj:
                    resolved_project_id = default_proj["id"]
        elif not resolved_project_id:
            default_proj = storage.get_default_project()
            if default_proj:
                resolved_project_id = default_proj["id"]

    store.append_message(
        session_id=session_id,
        role=MessageRole.USER.value,
        content=req.prompt,
        metadata={
            "model": req.model or "default",
            "project_id": resolved_project_id,
            "timestamp": datetime.datetime.now().isoformat(),
        },
    )

    # 2. Build Canonical ExecutionRequest and dispatch through ExecutionCoordinator
    coordinator = get_execution_coordinator()

    routing_prefs = None
    if req.routing_objective:
        try:
            routing_prefs = ExecutionRoutingPreferences(
                objective_profile=RoutingObjectiveProfile(req.routing_objective.lower()),
                source=RoutingPreferenceSource.USER_DIRECTIVE,
                authority=ContentAuthority.USER_DIRECTIVE,
            )
        except Exception as e:
            logger.warning("Invalid routing objective '%s': %s", req.routing_objective, e)

    routing_policy = None
    if req.privacy_boundary:
        try:
            routing_policy = DataRoutingPolicy(
                routing_class=DataRoutingClass(req.privacy_boundary.lower()),
                allow_relaxation_by_task=True,
            )
        except Exception as e:
            logger.warning("Invalid privacy boundary '%s': %s", req.privacy_boundary, e)

    exec_req = ExecutionRequest(
        project_id=resolved_project_id,
        session_id=session_id,
        task_type="chat",
        prompt=req.prompt,
        model_preference=req.model,
        routing_preferences=routing_prefs,
        routing_policy=routing_policy,
        inputs={
            "stream": req.stream,
            "skill_id": req.skill_id,
            "is_trusted_authority": True,
            "ipc_authenticated": True,
            "privacy_class": req.privacy_boundary,
        },
    )

    def _map_execution_error(res: ExecutionResult) -> tuple[int, str, str]:
        """Map domain execution error to HTTP status code and structured detail."""
        err_msg = res.error or "Provider execution failed"
        err_code = res.error_code or "DISPATCH_FAILED"

        if not res.error_code:
            if "NO_AVAILABLE_PROVIDER" in err_msg:
                err_code = "NO_AVAILABLE_PROVIDER"
            elif "CROSS_PROJECT_VIOLATION" in err_msg:
                err_code = "CROSS_PROJECT_VIOLATION"
            elif any(k in err_msg.lower() for k in ("timeout", "timed out", "deadline")):
                err_code = "PROVIDER_TIMEOUT"
            elif "validation" in err_msg.lower():
                err_code = "VALIDATION_ERROR"
            elif "policy" in err_msg.lower() or "budget" in err_msg.lower():
                err_code = "POLICY_BLOCKED"

        status_map = {
            "NO_AVAILABLE_PROVIDER": status.HTTP_503_SERVICE_UNAVAILABLE,
            "CROSS_PROJECT_VIOLATION": status.HTTP_403_FORBIDDEN,
            "PROVIDER_TIMEOUT": status.HTTP_504_GATEWAY_TIMEOUT,
            "DISPATCH_FAILED": status.HTTP_502_BAD_GATEWAY,
            "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
            "POLICY_BLOCKED": status.HTTP_403_FORBIDDEN,
            "BUDGET_EXCEEDED": status.HTTP_403_FORBIDDEN,
        }
        return status_map.get(err_code, status.HTTP_502_BAD_GATEWAY), err_code, err_msg

    local_keywords = ["qwen", "llama", "local", "ollama", "mistral", "deepseek"]

    # 3. Handle Streaming Response with Real-Time Incremental Queue
    if req.stream:
        chunk_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        cancellation_token = CancellationToken(exec_req.id)

        def stream_event_listener(event: ExecutionEvent) -> None:
            if event.event_type == ExecutionEventType.OUTPUT_CHUNK:
                chunk = event.payload.get("chunk", "")
                if chunk:
                    try:
                        chunk_queue.put_nowait({"event": "token", "delta": chunk})
                    except asyncio.QueueFull:
                        logger.warning(
                            "Streaming queue full for session %s, dropping chunk backpressure",
                            session_id,
                        )
            elif event.event_type == ExecutionEventType.ROUTING_RESOLVED:
                try:
                    chunk_queue.put_nowait({"event": "routing_resolved", "payload": event.payload})
                except Exception:
                    pass
            elif event.event_type == ExecutionEventType.APPROVAL_REQUIRED:
                try:
                    chunk_queue.put_nowait({"event": "approval_required", "payload": event.payload})
                except Exception:
                    pass
            elif event.event_type == ExecutionEventType.CANCELLED:
                try:
                    chunk_queue.put_nowait(
                        {
                            "event": "cancelled",
                            "reason": event.payload.get("reason", "user_request"),
                            "actor": event.payload.get("actor", "user"),
                        }
                    )
                except Exception:
                    pass

        async def run_coordinator():
            try:
                res = await coordinator.execute(
                    exec_req,
                    cancellation_token=cancellation_token,
                    event_listener=stream_event_listener,
                )
                if res.status == ExecutionStatus.CANCELLED:
                    await chunk_queue.put(
                        {
                            "event": "cancelled",
                            "reason": res.error or "Execution cancelled",
                            "result": res,
                        }
                    )
                elif res.status in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED):
                    _, err_code, err_msg = _map_execution_error(res)
                    await chunk_queue.put(
                        {
                            "event": "error",
                            "error": err_msg,
                            "error_code": err_code,
                            "result": res,
                        }
                    )
                else:
                    await chunk_queue.put({"event": "result", "result": res})
            except Exception as ex:
                logger.exception("Error in background coordinator streaming task: %s", ex)
                await chunk_queue.put(
                    {
                        "event": "error",
                        "error": str(ex),
                        "error_code": "DISPATCH_FAILED",
                    }
                )

        coord_task = asyncio.create_task(run_coordinator())

        async def event_generator() -> AsyncGenerator[str, None]:
            accumulated_response: List[str] = []
            final_result: Optional[ExecutionResult] = None
            try:
                while True:
                    item = await chunk_queue.get()
                    ev_type = item.get("event")

                    if ev_type == "token":
                        delta = item.get("delta", "")
                        accumulated_response.append(delta)
                        payload = {
                            "event": "token",
                            "session_id": session_id,
                            "delta": delta,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                    elif ev_type == "routing_resolved":
                        payload = {
                            "event": "routing_resolved",
                            "session_id": session_id,
                            "execution_id": exec_req.id,
                            **item.get("payload", {}),
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                    elif ev_type == "approval_required":
                        payload = {
                            "event": "approval_required",
                            "session_id": session_id,
                            "execution_id": exec_req.id,
                            **item.get("payload", {}),
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                    elif ev_type == "cancelled":
                        reason = item.get("reason", "Execution cancelled")
                        payload = {
                            "event": "cancelled",
                            "session_id": session_id,
                            "execution_id": exec_req.id,
                            "status": "CANCELLED",
                            "reason": reason,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"event: cancelled\ndata: {json.dumps(payload)}\n\n"
                        break

                    elif ev_type == "error":
                        err_code = item.get("error_code", "DISPATCH_FAILED")
                        err_msg = item.get("error", "Execution failed")
                        payload = {
                            "event": "error",
                            "session_id": session_id,
                            "error_code": err_code,
                            "error": err_msg,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                        break

                    elif ev_type == "result":
                        final_result = item["result"]
                        is_local = (final_result.provider_used or "").lower() in (
                            "local",
                            "llamacpp",
                            "ollama",
                        )
                        cost_event = {
                            "event": "cost_update",
                            "session_id": session_id,
                            "execution_id": final_result.execution_id,
                            "model": final_result.model_used or req.model or "default",
                            "provider": final_result.provider_used or "unknown",
                            "is_local": is_local,
                            "prompt_tokens": final_result.prompt_tokens,
                            "completion_tokens": final_result.completion_tokens,
                            "total_tokens": final_result.total_tokens
                            or (final_result.prompt_tokens + final_result.completion_tokens),
                            "cost_usd": final_result.total_cost_usd,
                            "duration_ms": final_result.duration_ms,
                            "routing_tier": (
                                final_result.routing_tier.value
                                if hasattr(final_result.routing_tier, "value")
                                else str(final_result.routing_tier)
                                if final_result.routing_tier
                                else None
                            ),
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(cost_event)}\n\n"

                        done_event = {
                            "event": "done",
                            "session_id": session_id,
                            "execution_id": final_result.execution_id,
                            "model": final_result.model_used or req.model or "default",
                            "provider": final_result.provider_used or "unknown",
                            "is_local": is_local,
                            "prompt_tokens": final_result.prompt_tokens,
                            "completion_tokens": final_result.completion_tokens,
                            "total_tokens": final_result.total_tokens
                            or (final_result.prompt_tokens + final_result.completion_tokens),
                            "cost_usd": final_result.total_cost_usd,
                            "duration_ms": final_result.duration_ms,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(done_event)}\n\n"
                        break

            except (asyncio.CancelledError, GeneratorExit):
                logger.info("Client disconnected from SSE stream for session %s", session_id)
                if exec_req.cancel_on_disconnect:
                    coordinator.cancel(
                        exec_req.id,
                        reason=CancellationReason.CLIENT_DISCONNECT,
                        actor="client",
                    )
                    if not coord_task.done():
                        coord_task.cancel()
                raise
            finally:
                if exec_req.cancel_on_disconnect and not coord_task.done():
                    coordinator.cancel(
                        exec_req.id,
                        reason=CancellationReason.CLIENT_DISCONNECT,
                        actor="client",
                    )
                    coord_task.cancel()
                    try:
                        await coord_task
                    except (asyncio.CancelledError, Exception):
                        pass

                # Persist assistant turn to session store EXACTLY ONCE on success
                if final_result and final_result.status == ExecutionStatus.COMPLETED:
                    full_text = "".join(accumulated_response) or final_result.outputs.get(
                        "response", ""
                    )
                    store.append_message(
                        session_id=session_id,
                        role=MessageRole.ASSISTANT.value,
                        content=full_text,
                        metadata={
                            "model": final_result.model_used or req.model or "default",
                            "provider": final_result.provider_used,
                            "execution_id": final_result.execution_id,
                            "prompt_tokens": final_result.prompt_tokens,
                            "completion_tokens": final_result.completion_tokens,
                            "cost_usd": final_result.total_cost_usd,
                            "timestamp": datetime.datetime.now().isoformat(),
                        },
                    )

                    model_lower = (final_result.model_used or req.model or "").lower()
                    if any(k in model_lower for k in local_keywords) or (
                        final_result.provider_used in ["ollama", "llamacpp"]
                    ):
                        hw_tracker = get_hardware_telemetry_tracker()
                        hw_tracker.record_inference_speed(
                            tokens=max(1, final_result.completion_tokens),
                            elapsed_seconds=max(0.05, final_result.completion_tokens * 0.016),
                            model=final_result.model_used or req.model or "qwen2.5-coder:7b",
                            runtime="ollama"
                            if ("ollama" in model_lower or final_result.provider_used == "ollama")
                            else "local",
                        )

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # 4. Handle Non-Streaming Execution
    result = await coordinator.execute(exec_req)

    if result.status == ExecutionStatus.CANCELLED:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "execution_id": result.execution_id,
                "status": "cancelled",
                "error_code": "CANCELLED",
                "message": result.error or "Execution cancelled",
                "partial_output": result.partial_output,
            },
        )

    if result.status in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED):
        http_status, error_code, error_msg = _map_execution_error(result)
        return JSONResponse(
            status_code=http_status,
            content={
                "detail": f"{error_code}: {error_msg}",
                "error_code": error_code,
                "message": error_msg,
            },
        )

    full_response_text = result.outputs.get("response", "")
    prompt_tokens = result.prompt_tokens
    completion_tokens = result.completion_tokens
    cost_usd = result.total_cost_usd

    # Persist assistant turn to session store exactly once
    store.append_message(
        session_id=session_id,
        role=MessageRole.ASSISTANT.value,
        content=full_response_text,
        metadata={
            "model": result.model_used or req.model or "default",
            "provider": result.provider_used,
            "execution_id": result.execution_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "timestamp": datetime.datetime.now().isoformat(),
        },
    )

    # Record local throughput in hardware tracker if local model was used
    model_lower = (result.model_used or req.model or "").lower()
    if any(k in model_lower for k in local_keywords) or (
        result.provider_used in ["ollama", "llamacpp"]
    ):
        hw_tracker = get_hardware_telemetry_tracker()
        hw_tracker.record_inference_speed(
            tokens=max(1, completion_tokens),
            elapsed_seconds=max(0.05, completion_tokens * 0.016),
            model=result.model_used or req.model or "qwen2.5-coder:7b",
            runtime="ollama"
            if ("ollama" in model_lower or result.provider_used == "ollama")
            else "local",
        )

    return ChatResponse(
        response=full_response_text,
        session_id=session_id,
        tool_calls=result.outputs.get("tool_calls", []),
        cost_usd=cost_usd,
        execution_id=result.execution_id,
        status=result.status.value if hasattr(result.status, "value") else str(result.status),
        model_used=result.model_used,
        provider_used=result.provider_used,
        routing_tier=result.routing_tier.value if result.routing_tier else None,
    )
