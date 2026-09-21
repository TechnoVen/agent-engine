"""services/python/server/app.py

FastAPI Application Factory for Agent Engine Sidecar Server.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import os
import time
from typing import List

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.python.server.container import START_TIME
from services.python.server.dependencies import verify_ipc_token
from services.python.server.routers import (
    adapters,
    artifacts,
    chat,
    collaboration,
    credentials,
    executions,
    ledger,
    memory,
    models,
    patches,
    pipelines,
    policies,
    projects,
    skills,
    swarm,
    system,
    tasks,
    telemetry,
    workflows,
)


ALLOWED_ORIGINS: List[str] = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
custom_origins = os.environ.get("AGENT_ENGINE_ALLOWED_ORIGINS")
if custom_origins:
    ALLOWED_ORIGINS.extend([o.strip() for o in custom_origins.split(",") if o.strip()])


def create_app() -> FastAPI:
    """Construct and configure the canonical Agent Engine FastAPI application."""
    app = FastAPI(
        title="Agent Engine Local API",
        description="Local HTTP and SSE interface between Agent Engine Tauri Shell and Python Sidecar",
        version="1.0.0",
        openapi_url="/v1/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root liveness probe
    @app.get("/healthz")
    async def healthz():
        """Liveness probe for Tauri shell and process supervisor."""
        uptime = time.time() - START_TIME
        return {
            "status": "ok",
            "service": "agent-engine-sidecar",
            "version": "0.1.0",
            "engine": "Agent Engine",
            "uptime_seconds": round(uptime, 2),
        }

    # Mount domain routers under /v1 with mandatory IPC authentication
    v1_router = APIRouter(prefix="/v1", dependencies=[Depends(verify_ipc_token)])
    v1_router.include_router(chat.router)
    v1_router.include_router(executions.router)
    v1_router.include_router(ledger.router)
    v1_router.include_router(artifacts.router)
    v1_router.include_router(pipelines.router)
    v1_router.include_router(skills.router)
    v1_router.include_router(adapters.router)
    v1_router.include_router(projects.router)
    v1_router.include_router(policies.router)
    v1_router.include_router(telemetry.router)
    v1_router.include_router(models.router)
    v1_router.include_router(credentials.router)
    v1_router.include_router(workflows.router)
    v1_router.include_router(swarm.router)
    v1_router.include_router(tasks.router)
    v1_router.include_router(memory.router)
    v1_router.include_router(collaboration.router)
    v1_router.include_router(patches.router)
    v1_router.include_router(system.router)

    app.include_router(v1_router)

    # Retain reference for inspection/backward compatibility
    app.state.v1_router = v1_router

    return app
