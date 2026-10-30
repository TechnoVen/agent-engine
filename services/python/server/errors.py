"""services/python/server/errors.py

Canonical Domain Error Translation & HTTP Transport Mapping for Agent Engine.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging
from typing import Dict
from fastapi import HTTPException, status

from core.execution.models import ExecutionResult
from core.adapters import AdapterDisabledError, AdapterNotFoundError
from core.context import MissingContextFieldError
from core.safety import OperationExpiredError, SecurityBoundaryViolation

logger = logging.getLogger("agent_engine.api.errors")

ERROR_CODE_HTTP_MAP: Dict[str, int] = {
    "NO_AVAILABLE_PROVIDER": status.HTTP_503_SERVICE_UNAVAILABLE,
    "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY": status.HTTP_403_FORBIDDEN,
    "PRIVACY_POLICY_BLOCKED": status.HTTP_403_FORBIDDEN,
    "PROVIDER_TIMEOUT": status.HTTP_504_GATEWAY_TIMEOUT,
    "DISPATCH_FAILED": status.HTTP_502_BAD_GATEWAY,
    "POLICY_BLOCKED": status.HTTP_403_FORBIDDEN,
    "BUDGET_EXCEEDED": status.HTTP_403_FORBIDDEN,
    "CROSS_PROJECT_VIOLATION": status.HTTP_403_FORBIDDEN,
    "EXECUTION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "CANCELLED": status.HTTP_409_CONFLICT,
    "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
    "AUTHENTICATION_REQUIRED": status.HTTP_401_UNAUTHORIZED,
}


def map_execution_error_to_http(result: ExecutionResult) -> HTTPException:
    """Translate an ExecutionResult failure into a standard HTTPException."""
    code = result.error_code or "DISPATCH_FAILED"
    status_code = ERROR_CODE_HTTP_MAP.get(code, status.HTTP_500_INTERNAL_SERVER_ERROR)
    detail = result.error or "Execution failed"
    return HTTPException(status_code=status_code, detail={"error": detail, "code": code})


def handle_domain_error(ex: Exception) -> HTTPException:
    """Translate domain exceptions to canonical HTTPExceptions."""
    if isinstance(ex, HTTPException):
        return ex
    if isinstance(ex, AdapterNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    if isinstance(ex, AdapterDisabledError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
    if isinstance(ex, (SecurityBoundaryViolation, PermissionError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
    if isinstance(ex, OperationExpiredError):
        return HTTPException(status_code=status.HTTP_410_GONE, detail=str(ex))
    if isinstance(ex, MissingContextFieldError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))
    if isinstance(ex, (KeyError, ValueError)):
        msg = str(ex)
        if "CROSS_PROJECT_VIOLATION" in msg or "not authorized" in msg.lower():
            return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
        if "not found" in msg.lower():
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    if isinstance(ex, TimeoutError):
        return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(ex))

    logger.error("Unhandled domain error: %s", ex, exc_info=True)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Internal server error: {ex}",
    )
