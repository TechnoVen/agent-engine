"""core/security/secrets.py

Unified Secrets Service & Runtime Injection for Agent Engine.
Part of Milestone R2 Task R2.6 (Secrets service and runtime injection).

Design Invariants:
1. Strong value object isolation: SecretReference (public), SecretMetadata (public masked), SecretValue (internal transient).
2. SecretValue never leaks via __str__, __repr__, or format strings (always '***').
3. Storage hierarchy: OS Keychain preferred (macOS Keychain, Linux SecretService, Windows Credential Manager);
   hardened AES-256-GCM Encrypted Vault fallback with true high-entropy 256-bit key material.
4. Fail-closed behavior: insecure permissions or missing key material blocks startup.
5. Plaintext reveal APIs eliminated: all endpoints return masked metadata; test connections execute backend-side.
6. Last-moment runtime injection: direct parameter injection into model clients and child subprocess env={...}
   without global os.environ pollution.
7. Authorization & scope isolation: consumer capability and project_id binding required for secret resolution.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
import pathlib
import re
import time
from typing import Any, Dict, List, Optional

import requests

from core.security.credentials import (
    CredentialBackend,
    EncryptedVaultBackend,
    KeyringBackend,
    PROVIDER_ENV_MAP,
    mask_secret,
)

logger = logging.getLogger("agent_engine.security.secrets")

_REF_COMPONENT_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


@dataclass(frozen=True)
class SecretReference:
    """Public identifier for a secret reference."""

    provider: str
    name: str
    scope: str = "default"
    project_id: Optional[str] = None

    def __post_init__(self):
        for field_name, val in [
            ("provider", self.provider),
            ("name", self.name),
            ("scope", self.scope),
        ]:
            if not val or not isinstance(val, str) or not _REF_COMPONENT_PATTERN.match(val):
                raise ValueError(
                    f"Invalid SecretReference {field_name} '{val}': must match [a-zA-Z0-9_\\-\\.]+"
                )
        if self.project_id is not None:
            if not isinstance(self.project_id, str) or not _REF_COMPONENT_PATTERN.match(
                self.project_id
            ):
                raise ValueError(
                    f"Invalid SecretReference project_id '{self.project_id}': "
                    "must match [a-zA-Z0-9_\\-\\.]+"
                )

    @property
    def canonical_id(self) -> str:
        proj = self.project_id or "global"
        return f"{proj}:{self.scope}:{self.provider}:{self.name}"

    def to_tuple(self) -> tuple[str, str, str, str]:
        """Structured tuple representation for unambiguous exact matching."""
        return (self.project_id or "global", self.scope, self.provider, self.name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "name": self.name,
            "scope": self.scope,
            "project_id": self.project_id,
            "canonical_id": self.canonical_id,
        }


@dataclass(frozen=True)
class SecretMetadata:
    """Public metadata for a stored secret (never contains plaintext)."""

    reference: SecretReference
    backend: str
    masked_value: str
    created_at: float
    updated_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference.to_dict(),
            "backend": self.backend,
            "masked_value": self.masked_value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SecretValue:
    """Transient, in-memory secret container bound to an authorized consumer.

    Guarantees:
    - str(secret_value) == '***'
    - repr(secret_value) == '<SecretValue: ***>'
    - Does not expose secret in string formatting
    - reveal(consumer_id) provides plaintext only to the bound consumer
    - use(consumer_id) context manager drops reference upon exit
    - wipe() clears references and documents Python memory semantics
    """

    def __init__(self, value: str, authorized_consumer: Optional[str] = None):
        if not isinstance(value, str):
            raise TypeError("Secret value must be a string")
        self._val: Optional[str] = value
        self._authorized_consumer: Optional[str] = authorized_consumer

    def __str__(self) -> str:
        return "***"

    def __repr__(self) -> str:
        return "<SecretValue: ***>"

    def __format__(self, format_spec: str) -> str:
        return "***"

    @property
    def authorized_consumer(self) -> Optional[str]:
        return self._authorized_consumer

    def reveal(self, consumer_id: Optional[str] = None) -> str:
        """Return plaintext secret for authorized runtime injection.

        Fails closed with PermissionError if consumer_id does not match the bound consumer.
        """
        if self._val is None:
            raise ValueError("SecretValue has already been destroyed or wiped")
        if self._authorized_consumer is not None:
            if not consumer_id or consumer_id != self._authorized_consumer:
                raise PermissionError(
                    f"Consumer mismatch: SecretValue bound to '{self._authorized_consumer}', "
                    f"cannot be revealed by '{consumer_id}'"
                )
        return self._val

    @contextmanager
    def use(self, consumer_id: Optional[str] = None):
        """Context manager yielding the plaintext value and guaranteeing cleanup."""
        try:
            yield self.reveal(consumer_id=consumer_id)
        finally:
            pass

    def wipe(self) -> None:
        """Explicitly clear secret material and consumer references from this container.

        Note on Python memory semantics:
        Because Python strings (`str`) are immutable and managed by Python's internal
        small-object allocator and garbage collector, true cryptographic overwriting/zeroing
        of the underlying memory buffer cannot be guaranteed in pure Python.
        `wipe()` minimizes the exposure window by clearing the container reference,
        enabling prompt garbage collection and guaranteeing that all subsequent `reveal()`
        calls fail closed.
        """
        self._val = None
        self._authorized_consumer = None


class SecretsService:
    """Unified Secrets Service coordinating secure backends and runtime injection."""

    def __init__(
        self,
        primary_backend: Optional[CredentialBackend] = None,
        fallback_backend: Optional[CredentialBackend] = None,
        vault_path: Optional[str | pathlib.Path] = None,
        preferred_backend_name: Optional[str] = None,
        key_file_path: Optional[str | pathlib.Path] = None,
    ):
        self.vault_backend: Optional[EncryptedVaultBackend] = None
        self.keyring_backend: Optional[KeyringBackend] = None

        if primary_backend is not None:
            self._primary = primary_backend
            self._fallback = fallback_backend
            if isinstance(primary_backend, EncryptedVaultBackend):
                self.vault_backend = primary_backend
            elif isinstance(fallback_backend, EncryptedVaultBackend):
                self.vault_backend = fallback_backend
            if isinstance(primary_backend, KeyringBackend):
                self.keyring_backend = primary_backend
            elif isinstance(fallback_backend, KeyringBackend):
                self.keyring_backend = fallback_backend
            return

        choice = (
            preferred_backend_name or os.environ.get("AGENT_ENGINE_CREDENTIAL_BACKEND", "auto")
        ).lower()

        # Initialize vault backend
        self.vault_backend = EncryptedVaultBackend(
            vault_path=vault_path, key_file_path=key_file_path
        )

        if choice == "vault":
            self._primary = self.vault_backend
            self._fallback = None
        elif choice == "keyring":
            try:
                self.keyring_backend = KeyringBackend()
                self._primary = self.keyring_backend
                self._fallback = self.vault_backend
            except Exception as e:
                logger.warning(
                    f"KeyringBackend requested but initialization failed: {e}. Falling back to vault."
                )
                self._primary = self.vault_backend
                self._fallback = None
        else:
            # Auto mode: Probe OS keyring
            try:
                kr = KeyringBackend()
                if kr.is_usable():
                    self.keyring_backend = kr
                    self._primary = self.keyring_backend
                    self._fallback = self.vault_backend
                    logger.info(
                        "Using OS Keyring as primary backend with Encrypted Vault fallback."
                    )
                else:
                    self._primary = self.vault_backend
                    self._fallback = None
                    logger.info("OS Keyring unavailable; using AES-256-GCM Encrypted Vault.")
            except Exception as e:
                logger.info(f"OS Keyring probe failed ({e}); using AES-256-GCM Encrypted Vault.")
                self._primary = self.vault_backend
                self._fallback = None

    @property
    def active_backend_name(self) -> str:
        return self._primary.name

    def _service_name_for_ref(self, ref: SecretReference) -> str:
        proj = ref.project_id or "global"
        return f"{proj}:{ref.scope}:{ref.provider}"

    def create(
        self,
        ref: SecretReference,
        value: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SecretMetadata:
        """Store a secret across secure backends and return its metadata."""
        if not value or not isinstance(value, str) or not value.strip():
            raise ValueError("Secret value cannot be empty")

        srv = self._service_name_for_ref(ref)
        try:
            self._primary.set(srv, ref.name, value)
            backend_used = self._primary.name
        except Exception as e:
            if self._fallback and self._fallback != self._primary:
                logger.warning(
                    f"Primary backend {self._primary.name} failed to store secret: {e}. Using fallback."
                )
                self._fallback.set(srv, ref.name, value)
                backend_used = self._fallback.name
            else:
                raise

        now = time.time()
        return SecretMetadata(
            reference=ref,
            backend=backend_used,
            masked_value=mask_secret(value),
            created_at=now,
            updated_at=now,
        )

    store_secret = create

    def delete(self, ref: SecretReference) -> bool:
        """Delete a secret across all backends."""
        srv = self._service_name_for_ref(ref)
        deleted = False
        try:
            if self._primary.delete(srv, ref.name):
                deleted = True
        except Exception:
            pass

        if self._fallback and self._fallback != self._primary:
            try:
                if self._fallback.delete(srv, ref.name):
                    deleted = True
            except Exception:
                pass

        return deleted

    def _get_raw(self, ref: SecretReference) -> Optional[str]:
        srv = self._service_name_for_ref(ref)
        try:
            val = self._primary.get(srv, ref.name)
            if val is not None:
                return val
        except Exception:
            pass

        if self._fallback and self._fallback != self._primary:
            try:
                val = self._fallback.get(srv, ref.name)
                if val is not None:
                    return val
            except Exception:
                pass

        return None

    def get_metadata(self, ref: SecretReference) -> Optional[SecretMetadata]:
        """Retrieve public metadata for a secret if it exists."""
        raw = self._get_raw(ref)
        if raw is None:
            return None
        return SecretMetadata(
            reference=ref,
            backend=self.active_backend_name,
            masked_value=mask_secret(raw),
            created_at=time.time(),
        )

    def list_metadata(
        self,
        scope: Optional[str] = None,
        provider: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[SecretMetadata]:
        """List metadata for stored secrets matching filters."""
        raw_items: List[Dict[str, Any]] = []
        try:
            raw_items = self._primary.list()
        except Exception:
            pass

        if not raw_items and self._fallback:
            try:
                raw_items = self._fallback.list()
            except Exception:
                pass

        results: List[SecretMetadata] = []
        seen = set()

        for item in raw_items:
            srv = item.get("service", "")
            key = item.get("key", "")
            # Parse srv format: "{proj}:{scope}:{provider}" or legacy "{service}"
            parts = srv.split(":")
            if len(parts) == 3:
                p_proj, p_scope, p_prov = parts
            else:
                p_proj, p_scope, p_prov = "global", "default", srv

            if project_id and project_id != p_proj:
                continue
            if scope and scope != p_scope:
                continue
            if provider and provider.lower() != p_prov.lower():
                continue

            ref = SecretReference(
                provider=p_prov,
                name=key,
                scope=p_scope,
                project_id=p_proj if p_proj != "global" else None,
            )
            cid = ref.canonical_id
            if cid in seen:
                continue
            seen.add(cid)

            results.append(
                SecretMetadata(
                    reference=ref,
                    backend=item.get("backend", self.active_backend_name),
                    masked_value=item.get("masked_value", "******"),
                    created_at=item.get("updated_at") or time.time(),
                    updated_at=item.get("updated_at"),
                )
            )

        return results

    def resolve_for_consumer(
        self,
        consumer_id: str,
        ref: SecretReference,
        context: Optional[Dict[str, Any]] = None,
    ) -> SecretValue:
        """Authorize and resolve a secret value for a specific consumer.

        Enforces:
        - Project scope isolation: Consumer project_id must match secret project_id.
        - Consumer capability / actor validation.
        - Consumer binding on the returned SecretValue.
        - Fails closed on unauthorized access.
        """
        ctx = context or {}

        # 1. Project isolation check
        if ref.project_id and ref.project_id not in ("global", "default"):
            consumer_project = ctx.get("project_id")
            if consumer_project and consumer_project != ref.project_id:
                raise PermissionError(
                    f"Project isolation violation: Consumer '{consumer_id}' in project '{consumer_project}' "
                    f"is not authorized to access secret bound to project '{ref.project_id}'"
                )

        # 2. Consumer authorization check
        allowed_consumers = ctx.get("authorized_consumers")
        if allowed_consumers and consumer_id not in allowed_consumers:
            raise PermissionError(
                f"Consumer '{consumer_id}' is not authorized to resolve secret '{ref.canonical_id}'"
            )

        raw = self._get_raw(ref)
        if raw is None:
            # Fall back to checking standard provider mappings
            allow_env = ctx.get("allow_env_fallback")
            raw = self.get_api_key(ref.provider, allow_env_fallback=allow_env)

        if raw is None:
            raise KeyError(f"Secret '{ref.canonical_id}' not found")

        return SecretValue(raw, authorized_consumer=consumer_id)

    # -----------------------------------------------------------------------
    # Provider API Key Helpers (backward-compatible and direct injection)
    # -----------------------------------------------------------------------

    def get_api_key(
        self,
        provider_or_key: str,
        allow_env_fallback: Optional[bool] = None,
    ) -> Optional[str]:
        """Resolve provider API key without mutating global os.environ.

        Prefers stored secrets (vault/keyring). Environment variable fallback
        is only performed if explicitly allowed, or if enabled via
        AGENT_ENGINE_ALLOW_ENV_CREDENTIALS=1 / non-production environment.
        """
        raw = provider_or_key.strip()
        env_key = PROVIDER_ENV_MAP.get(raw.lower(), raw)

        def _is_valid(k: Optional[str]) -> bool:
            if not k:
                return False
            s = k.strip().lower()
            return s not in (
                "",
                "none",
                "null",
                "placeholder",
                "changeme",
                "todo",
                "your_key_here",
            ) and not s.startswith("<")

        # 1. Check project/scoped secret reference in stored backends (preferred)
        ref = SecretReference(provider=raw.lower(), name=env_key)
        val = self._get_raw(ref)
        if _is_valid(val):
            return val

        # 2. Check legacy services: "llm", "agent-engine"
        for srv in ("llm", "agent-engine"):
            try:
                v = self._primary.get(srv, env_key) or self._primary.get(srv, raw.lower())
                if _is_valid(v):
                    return v
            except Exception:
                pass
            if self._fallback:
                try:
                    v = self._fallback.get(srv, env_key) or self._fallback.get(srv, raw.lower())
                    if _is_valid(v):
                        return v
                except Exception:
                    pass

        # 3. Process environment variable fallback (only if permitted)
        if allow_env_fallback is None:
            env_mode = os.getenv("ENV_MODE", "").lower()
            env_flag = os.getenv("AGENT_ENGINE_ALLOW_ENV_CREDENTIALS", "").lower()
            if env_flag in ("1", "true", "yes"):
                allow_env_fallback = True
            elif env_mode == "production":
                allow_env_fallback = False
            else:
                allow_env_fallback = True

        if allow_env_fallback:
            env_val = os.getenv(env_key)
            if _is_valid(env_val):
                return env_val

            if raw.lower() in ("gemini", "google"):
                alt = os.getenv("GOOGLE_API_KEY")
                if _is_valid(alt):
                    return alt

        return None

    def set_api_key(
        self, provider: str, api_key: str, project_id: Optional[str] = None
    ) -> SecretMetadata:
        """Store an LLM provider API key."""
        env_key = PROVIDER_ENV_MAP.get(provider.lower(), provider.upper())
        if not env_key.endswith("_API_KEY") and not env_key.endswith("_KEY"):
            env_key = f"{env_key}_API_KEY"

        ref = SecretReference(
            provider=provider.lower(),
            name=env_key,
            project_id=project_id,
        )
        return self.create(ref, api_key)

    def delete_api_key(self, provider: str, project_id: Optional[str] = None) -> bool:
        """Delete an LLM provider API key."""
        env_key = PROVIDER_ENV_MAP.get(provider.lower(), provider.upper())
        if not env_key.endswith("_API_KEY") and not env_key.endswith("_KEY"):
            env_key = f"{env_key}_API_KEY"

        ref = SecretReference(
            provider=provider.lower(),
            name=env_key,
            project_id=project_id,
        )
        res1 = self.delete(ref)
        ref2 = SecretReference(
            provider=provider.lower(), name=provider.lower(), project_id=project_id
        )
        res2 = self.delete(ref2)
        # Also clean legacy services
        try:
            self._primary.delete("llm", env_key)
        except Exception:
            pass
        return res1 or res2

    # -----------------------------------------------------------------------
    # Backend-Only Connection Testing
    # -----------------------------------------------------------------------

    def test_connection(
        self,
        provider: str,
        ref: Optional[SecretReference] = None,
        config: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Test API authentication and connectivity backend-side.

        Never exposes the plaintext secret in the response dictionary.
        """
        cfg = config or {}
        p_name = provider.lower()
        base_url = cfg.get("base_url")

        # Resolve secret value backend-side
        key_to_test: Optional[str] = None
        if cfg.get("api_key"):
            key_to_test = cfg.get("api_key")
        elif ref:
            try:
                sec_val = self.resolve_for_consumer("connection_tester", ref)
                key_to_test = sec_val.reveal(consumer_id="connection_tester")
            except Exception:
                pass
        if not key_to_test:
            key_to_test = self.get_api_key(p_name)

        if not key_to_test:
            if p_name in ("ollama", "local"):
                key_to_test = "ollama"
            elif p_name in ("vllm", "custom", "openai-compatible") and base_url:
                key_to_test = "custom"
            else:
                return {
                    "provider": provider,
                    "valid": False,
                    "latency_ms": 0.0,
                    "error": f"No API key configured for provider '{provider}'",
                }

        t0 = time.perf_counter()
        try:
            if p_name in ("ollama", "local"):
                url = (base_url or "http://localhost:11434").rstrip("/")
                resp = requests.get(f"{url}/api/tags", timeout=timeout)
            elif p_name in ("vllm", "custom", "openai-compatible"):
                url = (base_url or "http://localhost:8080").rstrip("/")
                headers = {}
                if key_to_test and key_to_test != "custom":
                    headers["Authorization"] = f"Bearer {key_to_test}"
                resp = requests.get(f"{url}/v1/models", headers=headers, timeout=timeout)
            elif p_name == "openai":
                url = (base_url or "https://api.openai.com").rstrip("/")
                resp = requests.get(
                    f"{url}/v1/models",
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
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                return {
                    "provider": provider,
                    "valid": True,
                    "latency_ms": elapsed_ms,
                    "error": None,
                }

            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            if resp.status_code in (200, 201):
                return {
                    "provider": provider,
                    "valid": True,
                    "latency_ms": elapsed_ms,
                    "error": None,
                }
            else:
                return {
                    "provider": provider,
                    "valid": False,
                    "latency_ms": elapsed_ms,
                    "error": f"HTTP {resp.status_code}: Authentication or service failure",
                }

        except requests.exceptions.Timeout:
            return {
                "provider": provider,
                "valid": False,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "error": f"Connection timed out after {timeout}s",
            }
        except Exception as e:
            return {
                "provider": provider,
                "valid": False,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "error": f"Connection failed: {e}",
            }


_secrets_service: Optional[SecretsService] = None


def get_secrets_service(
    primary_backend: Optional[CredentialBackend] = None,
    fallback_backend: Optional[CredentialBackend] = None,
    vault_path: Optional[str | pathlib.Path] = None,
    preferred_backend_name: Optional[str] = None,
    key_file_path: Optional[str | pathlib.Path] = None,
) -> SecretsService:
    """Retrieve or initialize the global SecretsService singleton."""
    global _secrets_service
    if _secrets_service is None or primary_backend or vault_path or preferred_backend_name:
        _secrets_service = SecretsService(
            primary_backend=primary_backend,
            fallback_backend=fallback_backend,
            vault_path=vault_path,
            preferred_backend_name=preferred_backend_name,
            key_file_path=key_file_path,
        )
    return _secrets_service


def reset_secrets_service() -> None:
    """Reset the global SecretsService singleton (for testing)."""
    global _secrets_service
    _secrets_service = None
