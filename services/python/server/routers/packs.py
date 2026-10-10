"""services/python/server/routers/packs.py

API router for Capability Packs inspection and validation in Agent Engine 0.5.
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
    """List all registered capability packs."""
    service = get_capability_pack_service()
    packs = service.list_packs()
    return [p.model_dump() for p in packs]


@router.get("/packs/{pack_id}", response_model=Dict[str, Any])
async def get_pack_endpoint(pack_id: str) -> Dict[str, Any]:
    """Retrieve details and capabilities of a specific capability pack."""
    service = get_capability_pack_service()
    pack = service.get_pack(pack_id)
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability pack '{pack_id}' not found.",
        )
    return pack.model_dump()


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
