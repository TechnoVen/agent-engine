"""services/python/server/routers/patches.py

Patches API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

# Core domain imports
from core.safety import (
    SecurityBoundaryViolation,
    get_pending_registry,
)
from server.watcher import apply_staged_patch, get_staged_patches, reject_staged_patch

# Services container, schemas, errors, transport, dependencies
from services.python.server.dependencies import verify_ipc_token
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.patches")
router = APIRouter(tags=["patches"])


@router.get("/patches", response_model=List[PatchInfo])
async def list_patches():
    """List all pending staged patches from the Sentry database."""
    staged = get_staged_patches()
    return [
        PatchInfo(
            id=p["id"],
            file_path=p["file_path"],
            patch_type=p["patch_type"],
            risk_level=p["risk_level"],
            report=p["report"],
            status=p["status"],
            timestamp=p["timestamp"],
        )
        for p in staged
    ]


@router.post("/patches/{patch_id}/apply", response_model=ActionResult)
async def apply_patch(
    patch_id: int,
    request: Request,
    approval_token: Optional[str] = Query(
        None, description="Single-use approval token for high-risk patches"
    ),
):
    """Apply a staged patch directly to the filesystem."""
    verify_ipc_token(request)
    if approval_token:
        registry = get_pending_registry()
        try:
            registry.consume_token(
                approval_token=approval_token,
                tool_name="filesystem:apply_patch",
                tool_args={"patch_id": patch_id},
            )
        except SecurityBoundaryViolation as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Security boundary violation: {e}",
            )
    success = apply_staged_patch(patch_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Patch #{patch_id} could not be applied: not found, already applied, or target file has conflicting modifications on disk.",
        )
    return ActionResult(success=True, message=f"Successfully applied patch #{patch_id}")


@router.post("/patches/{patch_id}/reject", response_model=ActionResult)
async def reject_patch(patch_id: int, request: Request):
    """Reject and dismiss a staged patch in SQLite."""
    verify_ipc_token(request)
    success = reject_staged_patch(patch_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patch #{patch_id} not found or already rejected.",
        )
    return ActionResult(success=True, message=f"Successfully rejected patch #{patch_id}")
