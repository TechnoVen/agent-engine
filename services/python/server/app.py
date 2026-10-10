"""services/python/server/app.py

FastAPI Application Factory for Agent Engine Sidecar Server.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

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
    packs,
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


PRODUCTION_ORIGINS: List[str] = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]

DEVELOPMENT_ORIGINS: List[str] = [
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

ALLOWED_ORIGINS: List[str] = PRODUCTION_ORIGINS


def get_allowed_origins() -> tuple[List[str], Optional[str]]:
    """Determine allowed CORS origins based on AGENT_ENGINE_ENV.

    Production mode: allows ONLY explicit Tauri desktop application origins.
    Arbitrary localhost ports and external web origins are strictly rejected.

    Development mode: permits known Vite/Tauri development server ports.
    """
    env = os.environ.get("AGENT_ENGINE_ENV", "production").lower()
    custom_origins = os.environ.get("AGENT_ENGINE_ALLOWED_ORIGINS")

    if env in ("development", "dev"):
        origins = list(PRODUCTION_ORIGINS) + list(DEVELOPMENT_ORIGINS)
        regex: Optional[str] = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    else:
        # Strict production: permit only official Tauri desktop origins
        origins = list(PRODUCTION_ORIGINS)
        regex = None

    if custom_origins:
        origins.extend([o.strip() for o in custom_origins.split(",") if o.strip()])

    return origins, regex


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

    origins, origin_regex = get_allowed_origins()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root liveness probe
    @app.get("/healthz")
    async def healthz():
        """Minimal liveness probe for Tauri shell and process supervisor.

        Exposes only minimal operational status and uptime.
        Never reveals provider names, models, local paths, user identities,
        projects, API credentials, or runtime secrets.
        """
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
    v1_router.include_router(packs.router)

    app.include_router(v1_router)

    # Retain reference for inspection/backward compatibility
    app.state.v1_router = v1_router

    return app
