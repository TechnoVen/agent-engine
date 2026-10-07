"""core/providers/base.py

Canonical Provider Adapter Base Class and Normalized Error Types.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).

Design Invariants:
1. Normalized error types: All low-level transport/HTTP exceptions are mapped to
   typed ProviderError subclasses (Auth, RateLimit, Timeout, Connection, Server, Not Found).
2. Secret resolution boundary: Adapters resolve secrets through SecretsService or safe
   environment lookups directly into constructor parameters or headers. Zero global os.environ mutation.
3. Health check discipline: Probes are low-cost, strictly bounded by timeouts, and produce
   truthful timestamped ProviderHealth evidence.
4. Dual runtime support: Adapters support both direct execution (.invoke, .stream) and
   construction of configured DSPy LM clients (.create_dspy_lm) for seamless kernel integration.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
import logging
import os
from typing import Any, Dict, Iterator, Optional

import dspy

from core.providers.models import (
    ProviderDefinition,
    ProviderHealth,
)

logger = logging.getLogger("agent_engine.providers.base")


class NormalizedProviderError(Exception):
    """Base exception for all normalized provider-layer errors."""

    def __init__(
        self,
        message: str,
        provider_id: str,
        status_code: Optional[int] = None,
        raw_error: Optional[Exception] = None,
    ) -> None:
        super().__init__(f"[{provider_id}] {message}")
        self.provider_id = provider_id
        self.status_code = status_code
        self.raw_error = raw_error


class ProviderAuthenticationError(NormalizedProviderError):
    """Raised when authentication fails (HTTP 401, 403, invalid or expired API key)."""

    pass


class ProviderRateLimitError(NormalizedProviderError):
    """Raised when upstream rate limits or quotas are exceeded (HTTP 429)."""

    pass


class ProviderTimeoutError(NormalizedProviderError):
    """Raised when an upstream request times out."""

    pass


class ProviderConnectionError(NormalizedProviderError):
    """Raised when connection cannot be established (DNS error, connection refused)."""

    pass


class ProviderNotFoundError(NormalizedProviderError):
    """Raised when a requested model or endpoint is not found (HTTP 404)."""

    pass


class ProviderServerError(NormalizedProviderError):
    """Raised when upstream returns server-side 5xx errors."""

    pass


class ProviderInvalidRequestError(NormalizedProviderError):
    """Raised when request payload or parameters are malformed (HTTP 400)."""

    pass


@dataclass
class ProviderInvocationResult:
    """Standardized response container for provider text generation."""

    content: str
    model: str
    provider_id: str
    finish_reason: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(abc.ABC):
    """Abstract base class for all canonical provider adapters."""

    def __init__(
        self,
        definition: ProviderDefinition,
        secrets_service: Optional[Any] = None,
    ) -> None:
        self._definition = definition
        self._secrets_service = secrets_service

    @property
    def definition(self) -> ProviderDefinition:
        return self._definition

    @property
    def provider_id(self) -> str:
        return self._definition.provider_id

    def _get_secrets_service(self) -> Optional[Any]:
        if self._secrets_service is not None:
            return self._secrets_service
        try:
            from core.security import get_secrets_service

            self._secrets_service = get_secrets_service()
            return self._secrets_service
        except Exception:
            return None

    def resolve_api_key(self, consumer_id: Optional[str] = None) -> Optional[str]:
        """Resolve the active credential for this provider without mutating os.environ.

        Enforces R2.6 secret isolation:
        1. Checks definition.config.secret_ref via SecretsService if available.
        2. Checks definition.config.credential_key via SecretsService or env lookup.
        3. Never mutates global os.environ.
        """
        config = self._definition.config
        secrets_svc = self._get_secrets_service()

        # 1. Resolve from SecretReference via SecretsService
        if config.secret_ref and secrets_svc:
            try:
                # If consumer_id is provided, resolve bound SecretValue container
                cid = consumer_id or f"provider:{self.provider_id}"
                sec_val = secrets_svc.resolve_for_consumer(
                    config.secret_ref,
                    consumer_id=cid,
                    project_id=config.secret_ref.project_id,
                )
                if sec_val:
                    return sec_val.reveal(cid)
            except Exception as e:
                logger.debug("Failed resolving SecretReference for '%s': %s", self.provider_id, e)

        # 2. Resolve via credential_key name in SecretsService
        cred_key = config.credential_key
        if cred_key:
            if secrets_svc:
                try:
                    val = secrets_svc.get_api_key(self.provider_id)
                    if val:
                        return val
                    val = secrets_svc.get_api_key(cred_key)
                    if val:
                        return val
                except Exception:
                    pass

            # Safe read-only environment check without mutation
            env_val = os.getenv(cred_key)
            if env_val:
                return env_val

        return None

    @abc.abstractmethod
    def test_connection(self, timeout: float = 5.0) -> ProviderHealth:
        """Perform an active connectivity and authentication probe.

        Updates self.definition.health and returns the result.
        """
        pass

    @abc.abstractmethod
    def check_health(self, timeout: float = 3.0) -> ProviderHealth:
        """Perform a low-cost, lightweight latency and availability probe.

        Updates self.definition.health and returns the result.
        """
        pass

    @abc.abstractmethod
    def create_dspy_lm(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        cache: bool = True,
        timeout: Optional[float] = None,
        api_key: Optional[str] = None,
    ) -> dspy.LM:
        """Construct a configured dspy.LM client with credentials injected directly."""
        pass

    @abc.abstractmethod
    def invoke(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderInvocationResult:
        """Execute a text generation call through the provider."""
        pass

    @abc.abstractmethod
    def stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream response chunks from the provider."""
        pass

    def normalize_http_error(
        self,
        status_code: int,
        error_text: str,
        raw_error: Optional[Exception] = None,
    ) -> NormalizedProviderError:
        """Translate HTTP status codes to standard NormalizedProviderError instances."""
        if status_code in (401, 403):
            return ProviderAuthenticationError(
                f"Authentication failed: {error_text}",
                provider_id=self.provider_id,
                status_code=status_code,
                raw_error=raw_error,
            )
        if status_code == 429:
            return ProviderRateLimitError(
                f"Rate limit exceeded: {error_text}",
                provider_id=self.provider_id,
                status_code=status_code,
                raw_error=raw_error,
            )
        if status_code == 404:
            return ProviderNotFoundError(
                f"Resource not found: {error_text}",
                provider_id=self.provider_id,
                status_code=status_code,
                raw_error=raw_error,
            )
        if status_code == 400:
            return ProviderInvalidRequestError(
                f"Invalid request: {error_text}",
                provider_id=self.provider_id,
                status_code=status_code,
                raw_error=raw_error,
            )
        if status_code >= 500:
            return ProviderServerError(
                f"Upstream server error: {error_text}",
                provider_id=self.provider_id,
                status_code=status_code,
                raw_error=raw_error,
            )
        return NormalizedProviderError(
            f"Provider error ({status_code}): {error_text}",
            provider_id=self.provider_id,
            status_code=status_code,
            raw_error=raw_error,
        )
