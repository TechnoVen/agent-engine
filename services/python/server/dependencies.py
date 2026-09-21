"""services/python/server/dependencies.py

FastAPI dependency providers and security verifiers for Agent Engine.
Part of Task R2.1 (Mandatory local IPC authentication).
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request, status

logger = logging.getLogger("agent_engine.security.ipc")


class IPCTokenManager:
    """Manages the canonical local IPC authentication secret for Agent Engine sidecar.

    Ensures fail-closed security for local-first execution while generating per-launch
    cryptographic tokens if none was explicitly configured in the environment.
    """

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._enforced: Optional[bool] = None

    def is_enforced(self) -> bool:
        """Check whether IPC authentication is strictly enforced."""
        if self._enforced is not None:
            return self._enforced
        # Explicit opt-in / opt-out
        if os.environ.get("AGENT_ENGINE_AUTH_ENFORCED") in ("1", "true", "True"):
            return True
        if os.environ.get("AGENT_ENGINE_AUTH_ENFORCED") in ("0", "false", "False"):
            return False
        # When token is configured in environment, always enforce
        if os.environ.get("AGENT_ENGINE_IPC_TOKEN"):
            return True
        # In live production runtime (not running under pytest), always enforce
        if "PYTEST_CURRENT_TEST" not in os.environ:
            return True
        return False

    def set_enforced(self, enforced: Optional[bool]) -> None:
        """Explicitly override enforcement status (primarily for testing)."""
        self._enforced = enforced

    def get_token(self) -> str:
        """Obtain the active IPC token, generating a 256-bit cryptographically secure secret if needed."""
        env_token = os.environ.get("AGENT_ENGINE_IPC_TOKEN")
        if env_token:
            self._token = env_token
            return self._token
        if self._token:
            return self._token

        # Generate per-launch 256-bit cryptographic secret
        token = secrets.token_hex(32)
        self._token = token
        os.environ["AGENT_ENGINE_IPC_TOKEN"] = token
        self._persist_handshake_token(token)
        return self._token

    def set_token(self, token: Optional[str]) -> None:
        """Set or reset the active token."""
        self._token = token
        if token is not None:
            os.environ["AGENT_ENGINE_IPC_TOKEN"] = token
        else:
            os.environ.pop("AGENT_ENGINE_IPC_TOKEN", None)

    def _persist_handshake_token(self, token: str) -> None:
        """Persist token to restricted local handshake file (POSIX 0600) for shell discovery."""
        candidates = [
            Path.home() / ".agent_engine" / "ipc.token",
            Path("data/ipc.token"),
        ]
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                fd = os.open(path, flags, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(token)
                try:
                    os.chmod(path, 0o600)
                except Exception:
                    pass
            except Exception as ex:
                logger.debug("Unable to write IPC handshake token to %s: %s", path, ex)

    def verify_request(self, request: Request) -> bool:
        """Verify request credentials against the active IPC token.

        Checks:
        1. Authorization: Bearer <token> header
        2. X-IPC-Token: <token> header
        3. token=<token> query parameter (for SSE event streams)
        """
        if not self.is_enforced():
            return True

        expected_token = self.get_token()

        # 1. Bearer token in Authorization header
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        # 2. X-IPC-Token custom header
        elif "X-IPC-Token" in request.headers:
            token = request.headers.get("X-IPC-Token")
        # 3. Query parameter for SSE / event streams
        elif "token" in request.query_params:
            token = request.query_params.get("token")

        if not token or not hmac.compare_digest(token, expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: invalid or missing IPC token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return True


# Global token manager singleton
_token_manager_instance: Optional[IPCTokenManager] = None


def get_token_manager() -> IPCTokenManager:
    """Obtain or initialize the global IPCTokenManager."""
    global _token_manager_instance
    if _token_manager_instance is None:
        _token_manager_instance = IPCTokenManager()
    return _token_manager_instance


def reset_token_manager() -> None:
    """Reset token manager instance (for test isolation)."""
    global _token_manager_instance
    _token_manager_instance = None


def verify_ipc_token(request: Request) -> bool:
    """FastAPI dependency for verifying local IPC token.

    Fails closed with HTTP 401 Unauthorized if missing, invalid, or mismatched.
    """
    return get_token_manager().verify_request(request)
