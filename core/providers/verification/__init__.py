"""core/providers/verification/__init__.py

Public symbols for Provider Connection Verification subsystem (Task R3.11).
"""

from core.providers.verification.models import (
    CURRENT_VERIFICATION_METHOD_VERSION,
    DEFAULT_VERIFICATION_TTL_SECONDS,
    ConnectionVerificationStatus,
    ProviderConnectionVerification,
)
from core.providers.verification.service import (
    ProviderVerificationService,
    get_provider_verification_service,
    reset_provider_verification_service,
)

__all__ = [
    "CURRENT_VERIFICATION_METHOD_VERSION",
    "DEFAULT_VERIFICATION_TTL_SECONDS",
    "ConnectionVerificationStatus",
    "ProviderConnectionVerification",
    "ProviderVerificationService",
    "get_provider_verification_service",
    "reset_provider_verification_service",
]
