"""services/python/server/dependencies.py

FastAPI dependency providers and security verifiers for Agent Engine.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import os
from fastapi import HTTPException, Request, status


def verify_ipc_token(request: Request) -> bool:
    """Verify IPC token when AGENT_ENGINE_IPC_TOKEN is configured in the environment."""
    expected_token = os.environ.get("AGENT_ENGINE_IPC_TOKEN")
    if not expected_token:
        return True

    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "X-IPC-Token" in request.headers:
        token = request.headers.get("X-IPC-Token")

    if not token or token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: invalid or missing IPC token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True
