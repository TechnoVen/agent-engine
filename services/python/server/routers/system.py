"""services/python/server/routers/system.py

System API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import io
import logging
import sys
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

# Core domain imports
from core.config import get_feature_flags, get_settings_manager, require_flag, set_flag_override
from core.diagnostics import build_diagnostics_bundle

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    START_TIME,
)
from services.python.server.dependencies import verify_ipc_token
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.system")
router = APIRouter(tags=["system"])


def _get_update_manager():
    api_mod = sys.modules.get("services.python.server.api")
    if (
        api_mod
        and hasattr(api_mod, "get_update_manager")
        and api_mod.get_update_manager is not _get_update_manager
    ):
        return api_mod.get_update_manager()
    from core.updater import get_update_manager as core_get_upd_mgr

    return core_get_upd_mgr()


@router.get("/health", response_model=SidecarHealthResponse)
async def get_sidecar_health():
    """Canonical health and status endpoint matching Tauri shell and client.ts expectations."""
    uptime = time.time() - START_TIME
    return SidecarHealthResponse(
        status="healthy",
        version="0.1.0",
        engine="Agent Engine",
        uptime_seconds=round(uptime, 2),
        timestamp=time.time(),
    )


@router.get("/auth/session", response_model=AuthSession)
async def get_auth_session():
    """Retrieve current session authentication and role."""
    return AuthSession(
        user_id="usr_local_owner",
        email="local@agent-engine.internal",
        role="Owner",
        tenant_id="default_tenant",
    )


@router.get(
    "/registry/search",
    response_model=List[RegistryPackage],
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def search_registry(q: str = Query(..., min_length=1)):
    """Search for skills or agent bundles in registry."""
    all_packages = [
        RegistryPackage(
            id="pkg_code_review",
            name="Code Review Checklist",
            version="1.0.0",
            description="Automated style and security audit checklist for python",
            author="Agent Engine Core",
        ),
        RegistryPackage(
            id="pkg_sql_gen",
            name="SQL Generator from Natural Language",
            version="1.0.0",
            description="Translate natural questions to schema-grounded SQL",
            author="Agent Engine Core",
        ),
    ]
    matches = [
        p for p in all_packages if q.lower() in p.name.lower() or q.lower() in p.description.lower()
    ]
    return matches


@router.get("/flags", response_model=FeatureFlagsResponse)
async def get_flags():
    """Retrieve current feature flag states and active overrides."""
    flags = get_feature_flags()
    return FeatureFlagsResponse(flags=flags.to_dict())


@router.post("/flags/{flag_name}", response_model=ActionResult)
async def override_flag(flag_name: str, req: FlagOverrideRequest):
    """Set a runtime override for a feature flag."""
    set_flag_override(flag_name, req.value)
    return ActionResult(success=True, message=f"Flag '{flag_name}' override set to {req.value}")


@router.get("/updater/status", response_model=UpdateStatusResponse)
async def get_updater_status_endpoint():
    """Retrieve auto-updater status, current version, active channel, and feed URL."""
    mgr = _get_update_manager()
    return UpdateStatusResponse(**mgr.get_status())


@router.post("/updater/channel", response_model=UpdateStatusResponse)
async def set_updater_channel_endpoint(req: SetChannelRequest):
    """Switch active update distribution channel (stable, beta, nightly)."""
    mgr = _get_update_manager()
    try:
        mgr.set_channel(req.channel)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UpdateStatusResponse(**mgr.get_status())


@router.post("/updater/check", response_model=UpdateCheckResponse)
async def check_updates_endpoint(req: Optional[UpdateCheckRequest] = None):
    """Check for new releases against the active or requested channel."""
    mgr = _get_update_manager()
    channel_override = req.channel if req else None
    info = mgr.check_for_updates(channel=channel_override)
    return UpdateCheckResponse(**info.to_dict())


@router.get("/settings/config", response_model=Dict[str, Any])
async def get_settings_config_endpoint():
    """Retrieve current application configuration decrypted from local encrypted storage."""
    mgr = get_settings_manager()
    settings = mgr.load_settings()
    return settings.to_dict()


@router.post("/settings/config", response_model=Dict[str, Any])
async def update_settings_config_endpoint(payload: Dict[str, Any], request: Request):
    """Update and persist application configuration into local encrypted vault."""
    verify_ipc_token(request)
    mgr = get_settings_manager()
    updated = mgr.save_settings(payload)
    return updated.to_dict()


@router.get("/diagnostics/export")
async def export_diagnostics_endpoint(
    format: str = Query("zip", description="Export format: 'zip' or 'json'"),
):
    """Export complete diagnostics bundle (system info, schema versions, redacted config, redacted logs)."""
    content_bytes, media_type, filename = build_diagnostics_bundle(format=format)
    if format.lower() == "json":
        return Response(content=content_bytes, media_type="application/json")

    return StreamingResponse(
        io.BytesIO(content_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/healthz")
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
