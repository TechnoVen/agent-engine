"""core/security/__init__.py

Core security package for Agent Engine.
Exports CredentialManager, secure backends, and secret masking utilities.
"""

from core.security.credentials import (
    CredentialBackend,
    CredentialManager,
    EncryptedVaultBackend,
    KeyringBackend,
    VaultIntegrityError,
    get_credential_manager,
    mask_secret,
    reset_credential_manager,
)
from core.security.secrets import (
    SecretMetadata,
    SecretReference,
    SecretValue,
    SecretsService,
    get_secrets_service,
    reset_secrets_service,
)

__all__ = [
    "CredentialBackend",
    "CredentialManager",
    "EncryptedVaultBackend",
    "KeyringBackend",
    "SecretMetadata",
    "SecretReference",
    "SecretValue",
    "SecretsService",
    "VaultIntegrityError",
    "get_credential_manager",
    "get_secrets_service",
    "mask_secret",
    "reset_credential_manager",
    "reset_secrets_service",
]
