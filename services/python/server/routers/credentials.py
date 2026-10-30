"""services/python/server/routers/credentials.py

Credentials API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging
import sys
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

# Core domain imports
from core.security import mask_secret

# Services container, schemas, errors, transport, dependencies
from services.python.server.dependencies import verify_ipc_token
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.credentials")
router = APIRouter(tags=["credentials"])


def _get_credential_manager():
    api_mod = sys.modules.get("services.python.server.api")
    if (
        api_mod
        and hasattr(api_mod, "get_credential_manager")
        and api_mod.get_credential_manager is not _get_credential_manager
    ):
        return api_mod.get_credential_manager()
    from core.security import get_credential_manager as core_get_cred_mgr

    return core_get_cred_mgr()


@router.get("/credentials", response_model=List[CredentialInfo])
async def list_credentials_endpoint(
    service: Optional[str] = Query(None, description="Optional service namespace filter"),
):
    """List stored credentials across secure backends with values masked."""
    mgr = _get_credential_manager()
    items = mgr.list_credentials(service=service)
    return [
        CredentialInfo(
            service=item["service"],
            key=item["key"],
            masked_value=item["masked_value"],
            backend=item.get("backend", mgr.active_backend_name),
            updated_at=item.get("updated_at"),
        )
        for item in items
    ]


@router.post(
    "/credentials",
    response_model=CredentialInfo,
    status_code=status.HTTP_201_CREATED,
)
async def set_credential_endpoint(req: SetCredentialRequest, request: Request):
    """Store a credential in the secure backend (OS Keychain with AES-256-GCM Vault fallback)."""
    verify_ipc_token(request)
    if not req.key.strip():
        raise HTTPException(status_code=400, detail="Credential key cannot be empty")
    if not req.value.strip():
        raise HTTPException(status_code=400, detail="Credential value cannot be empty")

    mgr = _get_credential_manager()
    mgr.set_credential(req.service.strip(), req.key.strip(), req.value)

    return CredentialInfo(
        service=req.service.strip(),
        key=req.key.strip(),
        masked_value=mask_secret(req.value),
        backend=mgr.active_backend_name,
        updated_at=time.time(),
    )


@router.get("/credentials/{service}/{key}", response_model=GetCredentialResponse)
async def get_credential_endpoint(
    service: str,
    key: str,
    request: Request,
    reveal: bool = Query(False, description="Whether to reveal the plaintext secret value"),
):
    """Retrieve a stored credential. Plaintext reveal is permanently disabled for security."""
    if reveal:
        verify_ipc_token(request)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Plaintext credential reveal is disabled for security",
        )

    mgr = _get_credential_manager()
    val = mgr.get_credential(service, key)
    if val is None:
        raise HTTPException(
            status_code=404, detail=f"Credential '{key}' not found under service '{service}'"
        )

    return GetCredentialResponse(
        service=service,
        key=key,
        masked_value=mask_secret(val),
        backend=mgr.active_backend_name,
        value=None,
        revealed=False,
        updated_at=time.time(),
    )


@router.delete("/credentials/{service}/{key}", response_model=ActionResult)
async def delete_credential_endpoint(service: str, key: str, request: Request):
    """Delete a stored credential from secure backends."""
    verify_ipc_token(request)
    mgr = _get_credential_manager()
    deleted = mgr.delete_credential(service, key)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Credential '{key}' not found under service '{service}'"
        )
    return ActionResult(
        success=True,
        message=f"Credential '{key}' successfully deleted from service '{service}'",
    )


@router.post("/credentials/test", response_model=TestCredentialResponse)
async def test_credential_endpoint(req: TestCredentialRequest):
    """Test API authentication and connectivity for a model provider."""
    mgr = _get_credential_manager()
    res = mgr.test_provider_key(req.provider, api_key=req.api_key, base_url=req.base_url)
    return TestCredentialResponse(
        provider=res["provider"],
        valid=res["valid"],
        latency_ms=res["latency_ms"],
        error=res.get("error"),
    )
