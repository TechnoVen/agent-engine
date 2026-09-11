"""core/security/credentials.py

Secure credential and API key storage subsystem for Agent Engine.
Satisfies Milestone M2 (Desktop Alpha), ADR-001 (Hybrid Shell), and ADR-008 (Zero-Trust Local Encryption).

Architecture:
- CredentialBackend (Abstract Interface)
- KeyringBackend: System OS Keychain (macOS Keychain, Linux SecretService, Windows Credential Manager)
- EncryptedVaultBackend: AES-256-GCM encrypted file storage (PBKDF2-SHA256, 100,000 iterations)
- CredentialManager: Hybrid manager with automatic fallback and secret masking.
"""

from __future__ import annotations

import abc
import hashlib
import json
import logging
import os
import pathlib
import platform
import time
import uuid
from typing import Any, Dict, List, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import requests

logger = logging.getLogger("agent_engine.security.credentials")

# Standard provider key mappings
PROVIDER_ENV_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "kimi": "KIMI_API_KEY",
    "moonshot": "KIMI_API_KEY",
}


def mask_secret(value: str | None) -> str:
    """Mask a sensitive credential or API key for safe logging and UI display.

    Examples:
        sk-proj-1234567890abcdef -> sk-...cdef
        AIzaSyA1234567890abcdef   -> AIza...cdef
        short                     -> ******
    """
    if not value:
        return ""
    val = value.strip()
    if len(val) <= 6:
        return "******"
    if val.startswith("sk-"):
        suffix = val[-4:] if len(val) >= 7 else val[-2:]
        return f"sk-...{suffix}"
    if len(val) <= 12:
        return f"{val[:2]}...{val[-2:]}"
    return f"{val[:4]}...{val[-4:]}"


class VaultIntegrityError(Exception):
    """Raised when an encrypted vault file has been tampered with or corrupted."""

    pass


class CredentialBackend(abc.ABC):
    """Abstract interface for secure credential backends."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of the backend."""
        pass

    @abc.abstractmethod
    def set(self, service: str, key: str, value: str) -> None:
        """Store a secret value."""
        pass

    @abc.abstractmethod
    def get(self, service: str, key: str) -> Optional[str]:
        """Retrieve a secret value."""
        pass

    @abc.abstractmethod
    def delete(self, service: str, key: str) -> bool:
        """Delete a secret value. Returns True if found and deleted."""
        pass

    @abc.abstractmethod
    def list(self, service: Optional[str] = None) -> List[Dict[str, Any]]:
        """List stored credentials (with masked values)."""
        pass

    @abc.abstractmethod
    def has(self, service: str, key: str) -> bool:
        """Check if a credential exists."""
        pass


class EncryptedVaultBackend(CredentialBackend):
    """AES-256-GCM encrypted file storage for credentials with PBKDF2 key derivation.

    Vault File Format:
    - Bytes 0..7: Magic identifier b"AEVAULT1"
    - Bytes 8..23: 16-byte random salt for PBKDF2
    - Bytes 24..35: 12-byte random nonce for AES-256-GCM
    - Bytes 36..End: Ciphertext + 16-byte GCM authentication tag
    """

    MAGIC = b"AEVAULT1"
    SALT_SIZE = 16
    NONCE_SIZE = 12
    PBKDF2_ITERATIONS = 100_000

    def __init__(self, vault_path: Optional[str | pathlib.Path] = None):
        if vault_path is None:
            # Default to data/credentials.vault relative to project root
            base_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "data"
            self.vault_path = base_dir / "credentials.vault"
        else:
            self.vault_path = pathlib.Path(vault_path)

        self._master_seed = self._derive_master_seed()

    @property
    def name(self) -> str:
        return "encrypted_vault"

    def _derive_master_seed(self) -> bytes:
        """Derive a stable, machine-specific seed string for PBKDF2 key derivation."""
        # 1. Custom vault key override if set in environment
        env_key = os.environ.get("AGENT_ENGINE_VAULT_KEY")
        if env_key:
            return env_key.encode("utf-8")

        # 2. Machine/OS unique identifiers
        components = [
            str(uuid.getnode()),  # MAC address
            os.environ.get("USER", os.environ.get("USERNAME", "agent_engine")),
            platform.node(),
            platform.machine(),
        ]

        # On Linux, try reading machine-id for stable hardware anchoring
        for mid_path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                if os.path.exists(mid_path):
                    with open(mid_path, "r", encoding="utf-8") as f:
                        components.append(f.read().strip())
                    break
            except Exception:
                pass

        combined = ":".join(components)
        return hashlib.sha256(combined.encode("utf-8")).digest()

    def _derive_aes_key(self, salt: bytes) -> bytes:
        """Derive a 256-bit (32 byte) key from the master seed and salt using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )
        return kdf.derive(self._master_seed)

    def _read_vault_data(self) -> Dict[str, Any]:
        """Read and decrypt the vault file. Returns empty dict if file doesn't exist."""
        if not self.vault_path.exists():
            return {}

        try:
            with open(self.vault_path, "rb") as f:
                data = f.read()

            if len(data) < len(self.MAGIC) + self.SALT_SIZE + self.NONCE_SIZE:
                raise VaultIntegrityError("Vault file is truncated or invalid.")

            magic = data[: len(self.MAGIC)]
            if magic != self.MAGIC:
                raise VaultIntegrityError(f"Invalid vault header magic: {magic!r}")

            offset = len(self.MAGIC)
            salt = data[offset : offset + self.SALT_SIZE]
            offset += self.SALT_SIZE
            nonce = data[offset : offset + self.NONCE_SIZE]
            offset += self.NONCE_SIZE
            ciphertext_and_tag = data[offset:]

            key = self._derive_aes_key(salt)
            aesgcm = AESGCM(key)
            decrypted_bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, self.MAGIC)
            return json.loads(decrypted_bytes.decode("utf-8"))
        except InvalidTag as e:
            logger.error(
                "Failed to decrypt credentials vault: Authentication tag mismatch (tampering detected)"
            )
            raise VaultIntegrityError("Vault decryption failed: file corrupted or tampered.") from e
        except json.JSONDecodeError as e:
            logger.error("Vault decrypted content is not valid JSON")
            raise VaultIntegrityError("Vault contains corrupted JSON payload.") from e
        except Exception as e:
            if isinstance(e, VaultIntegrityError):
                raise
            logger.error(f"Error reading credentials vault: {e}")
            raise VaultIntegrityError(f"Vault read failed: {e}") from e

    def _write_vault_data(self, data: Dict[str, Any]) -> None:
        """Encrypt and atomically write data to the vault file."""
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)

        salt = os.urandom(self.SALT_SIZE)
        nonce = os.urandom(self.NONCE_SIZE)
        key = self._derive_aes_key(salt)
        aesgcm = AESGCM(key)

        serialized = json.dumps(data, indent=2).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, serialized, self.MAGIC)

        vault_payload = self.MAGIC + salt + nonce + ciphertext

        # Atomic write via temporary file
        tmp_path = self.vault_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "wb") as f:
                f.write(vault_payload)

            # Restrict permissions: 0o600 (owner read/write only)
            try:
                os.chmod(tmp_path, 0o600)
            except Exception:
                pass

            os.replace(tmp_path, self.vault_path)
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise e

    def set(self, service: str, key: str, value: str) -> None:
        vault = self._read_vault_data()
        service_store = vault.setdefault(service, {})
        service_store[key] = {
            "value": value,
            "updated_at": time.time(),
        }
        self._write_vault_data(vault)

    def get(self, service: str, key: str) -> Optional[str]:
        vault = self._read_vault_data()
        service_store = vault.get(service, {})
        entry = service_store.get(key)
        if isinstance(entry, dict):
            return entry.get("value")
        elif isinstance(entry, str):
            return entry
        return None

    def delete(self, service: str, key: str) -> bool:
        vault = self._read_vault_data()
        service_store = vault.get(service, {})
        if key in service_store:
            del service_store[key]
            self._write_vault_data(vault)
            return True
        return False

    def list(self, service: Optional[str] = None) -> List[Dict[str, Any]]:
        vault = self._read_vault_data()
        items: List[Dict[str, Any]] = []

        services_to_scan = [service] if service else list(vault.keys())
        for s in services_to_scan:
            if s not in vault or not isinstance(vault[s], dict):
                continue
            for k, entry in vault[s].items():
                val = entry.get("value") if isinstance(entry, dict) else str(entry)
                updated_at = entry.get("updated_at") if isinstance(entry, dict) else None
                items.append(
                    {
                        "service": s,
                        "key": k,
                        "masked_value": mask_secret(val),
                        "backend": self.name,
                        "updated_at": updated_at,
                    }
                )
        return items

    def has(self, service: str, key: str) -> bool:
        return self.get(service, key) is not None


class KeyringBackend(CredentialBackend):
    """System OS Keychain integration via Python `keyring`.

    Supported platforms:
    - macOS: Keychain Services
    - Linux: SecretService / DBus (GNOME Keyring, KWallet)
    - Windows: Windows Credential Manager

    Maintains a local metadata index in data/.keyring_index.json for listing stored keys.
    """

    DEFAULT_SERVICE_PREFIX = "agent-engine"

    def __init__(
        self,
        service_prefix: str = DEFAULT_SERVICE_PREFIX,
        index_path: Optional[str | pathlib.Path] = None,
    ):
        self.service_prefix = service_prefix
        if index_path is None:
            base_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "data"
            self.index_path = base_dir / ".keyring_index.json"
        else:
            self.index_path = pathlib.Path(index_path)

        import keyring

        self._keyring = keyring

    @property
    def name(self) -> str:
        return "os_keyring"

    def _service_name(self, service: str) -> str:
        if service == self.service_prefix:
            return self.service_prefix
        return f"{self.service_prefix}:{service}"

    def _read_index(self) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_index(self, index_data: List[Dict[str, Any]]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2)
            try:
                os.chmod(self.index_path, 0o600)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Could not write keyring metadata index: {e}")

    def is_usable(self) -> bool:
        """Test if the OS keyring is functional without throwing headless/unlocked errors."""
        try:
            kr = self._keyring.get_keyring()
            kr_name = kr.__class__.__name__.lower()
            if "fail" in kr_name or "null" in kr_name:
                return False

            # Probe by reading a non-existent canary key
            self._keyring.get_password("agent-engine-probe", "canary_probe")
            return True
        except Exception as e:
            logger.debug(f"OS Keyring probe failed (will fallback to encrypted vault): {e}")
            return False

    def set(self, service: str, key: str, value: str) -> None:
        srv = self._service_name(service)
        self._keyring.set_password(srv, key, value)

        # Update metadata index (values are NEVER stored in index)
        index = self._read_index()
        updated = False
        now = time.time()
        for item in index:
            if item.get("service") == service and item.get("key") == key:
                item["updated_at"] = now
                updated = True
                break
        if not updated:
            index.append({"service": service, "key": key, "updated_at": now})
        self._write_index(index)

    def get(self, service: str, key: str) -> Optional[str]:
        srv = self._service_name(service)
        return self._keyring.get_password(srv, key)

    def delete(self, service: str, key: str) -> bool:
        srv = self._service_name(service)
        deleted = False
        try:
            self._keyring.delete_password(srv, key)
            deleted = True
        except Exception:
            pass

        # Update metadata index
        index = self._read_index()
        new_index = [
            item
            for item in index
            if not (item.get("service") == service and item.get("key") == key)
        ]
        if len(new_index) != len(index):
            self._write_index(new_index)
            deleted = True
        return deleted

    def list(self, service: Optional[str] = None) -> List[Dict[str, Any]]:
        index = self._read_index()
        results = []
        for item in index:
            s = item.get("service", "")
            k = item.get("key", "")
            if service and s != service:
                continue

            try:
                val = self.get(s, k)
                if val is not None:
                    results.append(
                        {
                            "service": s,
                            "key": k,
                            "masked_value": mask_secret(val),
                            "backend": self.name,
                            "updated_at": item.get("updated_at"),
                        }
                    )
            except Exception:
                continue
        return results

    def has(self, service: str, key: str) -> bool:
        return self.get(service, key) is not None


class CredentialManager:
    """Unified Credential Manager coordinating OS Keychain and Encrypted Vault fallback.

    Resolution Order:
    1. Primary Backend (OS Keyring if available, else Encrypted Vault)
    2. Fallback Backend (Encrypted Vault)
    3. Process Environment Variables (os.getenv) for backward compatibility
    """

    def __init__(
        self,
        preferred_backend: Optional[str] = None,
        vault_path: Optional[str | pathlib.Path] = None,
    ):
        self.vault_backend = EncryptedVaultBackend(vault_path=vault_path)
        self.keyring_backend: Optional[KeyringBackend] = None

        backend_choice = (
            preferred_backend or os.environ.get("AGENT_ENGINE_CREDENTIAL_BACKEND", "auto")
        ).lower()

        if backend_choice == "vault":
            self._primary = self.vault_backend
        elif backend_choice == "keyring":
            try:
                self.keyring_backend = KeyringBackend()
                self._primary = self.keyring_backend
            except Exception as e:
                logger.warning(
                    f"KeyringBackend requested but initialization failed: {e}. Using vault."
                )
                self._primary = self.vault_backend
        else:
            # Auto mode: probe OS keyring
            try:
                kr = KeyringBackend()
                if kr.is_usable():
                    self.keyring_backend = kr
                    self._primary = self.keyring_backend
                    logger.info("Using OS Keyring backend for credentials.")
                else:
                    self._primary = self.vault_backend
                    logger.info("OS Keyring unavailable; using AES-256-GCM Encrypted Vault.")
            except Exception as e:
                logger.info(f"OS Keyring unavailable ({e}); falling back to Encrypted Vault.")
                self._primary = self.vault_backend

    @property
    def active_backend_name(self) -> str:
        return self._primary.name

    def set_credential(self, service: str, key: str, value: str) -> None:
        """Store a credential in the secure backend with automatic fallback."""
        try:
            self._primary.set(service, key, value)
        except Exception as e:
            if self._primary != self.vault_backend:
                logger.warning(
                    f"Primary backend {self._primary.name} failed to set credential: {e}. Falling back to vault."
                )
                self.vault_backend.set(service, key, value)
            else:
                raise

    def get_credential(self, service: str, key: str) -> Optional[str]:
        """Retrieve a credential from the secure backend with fallback."""
        try:
            val = self._primary.get(service, key)
            if val is not None:
                return val
        except Exception as e:
            logger.debug(f"Primary backend {self._primary.name} get failed: {e}")

        # Try vault fallback if primary is not vault
        if self._primary != self.vault_backend:
            try:
                val = self.vault_backend.get(service, key)
                if val is not None:
                    return val
            except Exception:
                pass

        return None

    def delete_credential(self, service: str, key: str) -> bool:
        """Delete a credential from backends."""
        deleted = False
        try:
            if self._primary.delete(service, key):
                deleted = True
        except Exception:
            pass

        if self._primary != self.vault_backend:
            try:
                if self.vault_backend.delete(service, key):
                    deleted = True
            except Exception:
                pass

        return deleted

    def list_credentials(self, service: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all stored credentials across backends (with masked values)."""
        seen: set[tuple[str, str]] = set()
        results: List[Dict[str, Any]] = []

        # 1. Primary backend
        try:
            for item in self._primary.list(service):
                ident = (item["service"], item["key"])
                if ident not in seen:
                    seen.add(ident)
                    results.append(item)
        except Exception as e:
            logger.warning(f"Error listing from primary backend {self._primary.name}: {e}")

        # 2. Vault backend if not primary
        if self._primary != self.vault_backend:
            try:
                for item in self.vault_backend.list(service):
                    ident = (item["service"], item["key"])
                    if ident not in seen:
                        seen.add(ident)
                        results.append(item)
            except Exception:
                pass

        return results

    def has_credential(self, service: str, key: str) -> bool:
        return self.get_credential(service, key) is not None

    # -----------------------------------------------------------------------
    # Provider API Key Helpers
    # -----------------------------------------------------------------------

    def get_api_key(self, provider_or_key: str) -> Optional[str]:
        """Resolve an LLM provider API key from secure storage, falling back to os.getenv.

        Handles aliases:
        - "openai" -> checks "OPENAI_API_KEY" in service "llm", "agent-engine", then os.getenv
        - "OPENAI_API_KEY" -> checks directly
        """
        raw = provider_or_key.strip()
        env_key = PROVIDER_ENV_MAP.get(raw.lower(), raw)

        def _is_valid_key(k: Optional[str]) -> bool:
            if not k:
                return False
            stripped = k.strip().lower()
            if stripped in (
                "",
                "your_key_here",
                "your_api_key_here",
                "your-key-here",
                "placeholder",
                "none",
                "null",
                "changeme",
                "todo",
            ):
                return False
            if stripped.startswith("<") or stripped.startswith("your_"):
                return False
            return True

        # 1. Check secure storage (service="llm", key=env_key)
        val = self.get_credential("llm", env_key)
        if _is_valid_key(val):
            return val

        # 2. Check service="agent-engine"
        val = self.get_credential("agent-engine", env_key)
        if _is_valid_key(val):
            return val

        # 3. Check raw provider name
        val = self.get_credential("llm", raw.lower())
        if _is_valid_key(val):
            return val

        # 4. Fallback to process environment variable
        env_val = os.getenv(env_key)
        if _is_valid_key(env_val):
            return env_val

        # 5. Check secondary alias if applicable (e.g. GOOGLE_API_KEY for gemini)
        if raw.lower() in ("gemini", "google"):
            alt_val = os.getenv("GOOGLE_API_KEY")
            if _is_valid_key(alt_val):
                return alt_val

        return None

    def set_api_key(self, provider: str, api_key: str) -> None:
        """Store an LLM provider API key in secure storage under service='llm'."""
        env_key = PROVIDER_ENV_MAP.get(provider.lower(), provider.upper())
        if not env_key.endswith("_API_KEY") and not env_key.endswith("_KEY"):
            env_key = f"{env_key}_API_KEY"
        self.set_credential("llm", env_key, api_key)

    def delete_api_key(self, provider: str) -> bool:
        """Delete an LLM provider API key from secure storage."""
        env_key = PROVIDER_ENV_MAP.get(provider.lower(), provider.upper())
        if not env_key.endswith("_API_KEY") and not env_key.endswith("_KEY"):
            env_key = f"{env_key}_API_KEY"
        res1 = self.delete_credential("llm", env_key)
        res2 = self.delete_credential("llm", provider.lower())
        return res1 or res2

    def list_api_keys(self) -> List[Dict[str, Any]]:
        """List all stored LLM provider API keys (masked)."""
        return self.list_credentials(service="llm")

    # -----------------------------------------------------------------------
    # Provider Connectivity Self-Test
    # -----------------------------------------------------------------------

    def test_provider_key(
        self,
        provider: str,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Test API connectivity and authentication for a provider key."""
        p_name = provider.lower()
        key_to_test = api_key or self.get_api_key(p_name)

        if not key_to_test:
            return {
                "provider": provider,
                "valid": False,
                "latency_ms": 0.0,
                "error": f"No API key configured for provider '{provider}'",
            }

        t0 = time.perf_counter()

        try:
            if p_name == "openai":
                resp = requests.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key_to_test}"},
                    timeout=timeout,
                )
            elif p_name in ("gemini", "google"):
                resp = requests.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key_to_test}",
                    timeout=timeout,
                )
            elif p_name == "anthropic":
                resp = requests.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": key_to_test,
                        "anthropic-version": "2023-06-01",
                    },
                    timeout=timeout,
                )
            elif p_name == "deepseek":
                resp = requests.get(
                    "https://api.deepseek.com/models",
                    headers={"Authorization": f"Bearer {key_to_test}"},
                    timeout=timeout,
                )
            elif p_name == "groq":
                resp = requests.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {key_to_test}"},
                    timeout=timeout,
                )
            elif p_name in ("kimi", "moonshot"):
                resp = requests.get(
                    "https://api.moonshot.cn/v1/models",
                    headers={"Authorization": f"Bearer {key_to_test}"},
                    timeout=timeout,
                )
            else:
                # Custom or unsupported provider: format validation only
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                return {
                    "provider": provider,
                    "valid": len(key_to_test) > 5,
                    "latency_ms": elapsed_ms,
                    "error": None if len(key_to_test) > 5 else "Key is too short",
                }

            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

            if resp.status_code in (200, 201):
                return {
                    "provider": provider,
                    "valid": True,
                    "latency_ms": elapsed_ms,
                    "error": None,
                }
            elif resp.status_code in (401, 403):
                return {
                    "provider": provider,
                    "valid": False,
                    "latency_ms": elapsed_ms,
                    "error": f"Authentication failed (HTTP {resp.status_code})",
                }
            else:
                # Other status (e.g. rate limit 429) might mean authentication succeeded
                if resp.status_code == 429:
                    return {
                        "provider": provider,
                        "valid": True,
                        "latency_ms": elapsed_ms,
                        "error": "Rate limited by provider (429)",
                    }
                return {
                    "provider": provider,
                    "valid": False,
                    "latency_ms": elapsed_ms,
                    "error": f"Provider returned HTTP {resp.status_code}",
                }

        except requests.exceptions.RequestException as e:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "provider": provider,
                "valid": False,
                "latency_ms": elapsed_ms,
                "error": f"Network error during verification: {e}",
            }
        except Exception as e:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "provider": provider,
                "valid": False,
                "latency_ms": elapsed_ms,
                "error": str(e),
            }


# Global singleton instance
_GLOBAL_CREDENTIAL_MANAGER: Optional[CredentialManager] = None


def get_credential_manager() -> CredentialManager:
    """Retrieve or initialize the global CredentialManager singleton."""
    global _GLOBAL_CREDENTIAL_MANAGER
    if _GLOBAL_CREDENTIAL_MANAGER is None:
        _GLOBAL_CREDENTIAL_MANAGER = CredentialManager()
    return _GLOBAL_CREDENTIAL_MANAGER


def reset_credential_manager() -> None:
    """Reset the global singleton (primarily used for unit testing)."""
    global _GLOBAL_CREDENTIAL_MANAGER
    _GLOBAL_CREDENTIAL_MANAGER = None
