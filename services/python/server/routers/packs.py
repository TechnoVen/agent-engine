"""services/python/server/routers/packs.py

API router for Capability Packs inspection, validation, and lifecycle in Agent Engine 0.5.
Part of Milestone R5 (Founder Dogfood & Capability Packs) - Task R5.1 (Core Pack MVP).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, status

from core.packs.service import PackValidationError, get_capability_pack_service

logger = logging.getLogger("agent_engine.api.packs")
router = APIRouter(tags=["packs"])


@router.get("/packs", response_model=List[Dict[str, Any]])
async def list_packs_endpoint() -> List[Dict[str, Any]]:
    """List all registered capability packs with their current enabled states."""
    service = get_capability_pack_service()
    packs = service.list_packs()
    summaries = []
    for p in packs:
        s = service.get_pack_summary(p.id)
        if s:
            summaries.append(s)
        else:
            summaries.append(p.model_dump())
    return summaries


@router.get("/packs/{pack_id}", response_model=Dict[str, Any])
async def get_pack_endpoint(pack_id: str) -> Dict[str, Any]:
    """Retrieve details, status, and capabilities of a specific capability pack."""
    service = get_capability_pack_service()
    summary = service.get_pack_summary(pack_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability pack '{pack_id}' not found.",
        )
    return summary


@router.post("/packs/{pack_id}/validate", response_model=Dict[str, Any])
async def validate_pack_endpoint(pack_id: str) -> Dict[str, Any]:
    """Validate capability pack integrity, permission bounds, and zero-shadow-runtime invariant."""
    service = get_capability_pack_service()
    pack = service.get_pack(pack_id)
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability pack '{pack_id}' not found.",
        )

    errors: List[str] = []
    for cap in pack.capabilities:
        try:
            service._verify_canonical_binding(cap)
        except PackValidationError as e:
            errors.append(str(e))

    return {
        "pack_id": pack_id,
        "valid": len(errors) == 0,
        "capabilities_count": len(pack.capabilities),
        "permissions_count": len(pack.permissions),
        "errors": errors,
    }


@router.post("/packs/{pack_id}/enable", response_model=Dict[str, Any])
async def enable_pack_endpoint(pack_id: str) -> Dict[str, Any]:
    """Enable a capability pack as one unit."""
    service = get_capability_pack_service()
    try:
        service.enable_pack(pack_id)
    except PackValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    summary = service.get_pack_summary(pack_id)
    return summary or {"pack_id": pack_id, "enabled": True}


@router.post("/packs/{pack_id}/disable", response_model=Dict[str, Any])
async def disable_pack_endpoint(pack_id: str) -> Dict[str, Any]:
    """Disable a capability pack (system packs cannot be disabled)."""
    service = get_capability_pack_service()
    try:
        service.disable_pack(pack_id)
    except PackValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    summary = service.get_pack_summary(pack_id)
    return summary or {"pack_id": pack_id, "enabled": False}
