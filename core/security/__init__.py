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

__all__ = [
    "CredentialBackend",
    "CredentialManager",
    "EncryptedVaultBackend",
    "KeyringBackend",
    "VaultIntegrityError",
    "get_credential_manager",
    "mask_secret",
    "reset_credential_manager",
]
