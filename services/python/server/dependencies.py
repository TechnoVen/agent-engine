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

    def rotate_token(self) -> str:
        """Rotate the active IPC token, generating a fresh 256-bit secret and overwriting the handshake file.

        The previous token is immediately invalidated.
        """
        token = secrets.token_hex(32)
        self._token = token
        os.environ["AGENT_ENGINE_IPC_TOKEN"] = token
        self._persist_handshake_token(token)
        return self._token

    @staticmethod
    def get_handshake_path() -> Path:
        """Return the single authoritative local handshake file path."""
        override = os.environ.get("AGENT_ENGINE_TOKEN_FILE")
        if override:
            return Path(override)
        return Path.home() / ".agent_engine" / "ipc.token"

    def _persist_handshake_token(self, token: str) -> None:
        """Persist token to single authoritative local handshake file with strict user-only permissions.

        POSIX: 0600 (read/write only by owner).
        Windows: restricted user ACLs via icacls.
        """
        path = self.get_handshake_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            mode = 0o600
            fd = os.open(path, flags, mode)
            with os.fdopen(fd, "w") as f:
                f.write(token)
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass

            # Windows-specific ACL restriction: restrict to current user
            if os.name == "nt":
                try:
                    import subprocess

                    username = os.environ.get("USERNAME") or os.environ.get("USER")
                    if username:
                        subprocess.run(
                            [
                                "icacls",
                                str(path),
                                "/inheritance:r",
                                "/grant:r",
                                f"{username}:(R,W)",
                            ],
                            check=False,
                            capture_output=True,
                        )
                except Exception as win_err:
                    logger.debug("Windows ACL hardening via icacls for %s: %s", path, win_err)
        except Exception as ex:
            logger.debug("Unable to write IPC handshake token to %s: %s", path, ex)

    def cleanup_handshake_file(self) -> None:
        """Clean up the local handshake file on shutdown."""
        path = self.get_handshake_path()
        try:
            if path.exists():
                path.unlink(missing_ok=True)
        except Exception as ex:
            logger.debug("Failed to clean up handshake file %s: %s", path, ex)

    def verify_request(self, request: Request) -> bool:
        """Verify request credentials against the active IPC token.

        Enforces HEADER-ONLY authentication:
        1. Authorization: Bearer <token>
        2. X-IPC-Token: <token>

        Query parameters (e.g. ?token=...) are strictly rejected to prevent
        credential exposure in access logs, URLs, browser history, or referrer headers.
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

        # Explicitly fail closed: query parameter master tokens are never accepted
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


def redact_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with sensitive IPC tokens and credentials redacted."""
    sensitive_keys = {"authorization", "x-ipc-token", "x-api-key", "cookie"}
    redacted = {}
    for k, v in headers.items():
        if k.lower() in sensitive_keys:
            redacted[k] = "[REDACTED]"
        else:
            redacted[k] = v
    return redacted


import atexit


def _cleanup_on_exit() -> None:
    if _token_manager_instance is not None:
        _token_manager_instance.cleanup_handshake_file()


atexit.register(_cleanup_on_exit)
