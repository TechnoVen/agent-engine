"""core/providers/adapters/compatible.py

Generic OpenAI-Compatible Provider Adapter for Agent Engine.
Supports vLLM, LocalAI, Ollama OpenAI endpoints, and custom inference gateways.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterator, Optional

import dspy
import requests

from core.providers.base import (
    NormalizedProviderError,
    ProviderAdapter,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderInvocationResult,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from core.providers.models import (
    ProviderHealth,
    ProviderHealthStatus,
)

logger = logging.getLogger("agent_engine.providers.compatible")


class OpenAICompatibleAdapter(ProviderAdapter):
    """Canonical adapter for any OpenAI-compatible HTTP inference endpoint."""

    def _get_base_url(self) -> str:
        return (
            self._definition.config.endpoint_url
            or self._definition.default_endpoint_url
            or "http://localhost:8080/v1"
        ).rstrip("/")

    def test_connection(self, timeout: float = 5.0) -> ProviderHealth:
        key = self.resolve_api_key()
        if self._definition.capabilities.requires_credentials and not key:
            h = ProviderHealth(
                status=ProviderHealthStatus.AUTHENTICATION_FAILED,
                error_message=f"Missing API key for provider '{self.provider_id}'",
                last_checked_at=time.time(),
            )
            self._definition.health = h
            return h

        base_url = self._get_base_url()
        probe_url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
        headers: Dict[str, str] = dict(self._definition.config.custom_headers)
        if key:
            headers["Authorization"] = f"Bearer {key}"

        t0 = time.perf_counter()
        try:
            resp = requests.get(probe_url, headers=headers, timeout=timeout)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            if resp.status_code == 200:
                threshold = self._definition.capabilities.degraded_latency_threshold_ms
                status = (
                    ProviderHealthStatus.DEGRADED
                    if elapsed_ms > threshold
                    else ProviderHealthStatus.HEALTHY
                )
                h = ProviderHealth(
                    status=status,
                    latency_ms=elapsed_ms,
                    last_checked_at=time.time(),
                    consecutive_failures=0,
                    details={"status_code": 200, "endpoint": probe_url},
                )
            elif resp.status_code in (401, 403):
                h = ProviderHealth(
                    status=ProviderHealthStatus.AUTHENTICATION_FAILED,
                    latency_ms=elapsed_ms,
                    error_message=f"HTTP {resp.status_code}: Authentication rejected by {probe_url}",
                    last_checked_at=time.time(),
                    details={"status_code": resp.status_code},
                )
            else:
                h = ProviderHealth(
                    status=ProviderHealthStatus.UNAVAILABLE,
                    latency_ms=elapsed_ms,
                    error_message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    last_checked_at=time.time(),
                    details={"status_code": resp.status_code},
                )
        except requests.Timeout:
            h = ProviderHealth(
                status=ProviderHealthStatus.UNAVAILABLE,
                error_message=f"Connection timed out after {timeout}s",
                last_checked_at=time.time(),
            )
        except Exception as e:
            h = ProviderHealth(
                status=ProviderHealthStatus.UNAVAILABLE,
                error_message=f"Connection error to {base_url}: {e}",
                last_checked_at=time.time(),
            )

        self._definition.health = h
        return h

    def check_health(self, timeout: float = 3.0) -> ProviderHealth:
        if self._definition.capabilities.requires_credentials and not self.resolve_api_key():
            h = ProviderHealth(
                status=ProviderHealthStatus.CONFIGURED,
                error_message="No API key configured",
                last_checked_at=time.time(),
            )
            self._definition.health = h
            return h
        return self.test_connection(timeout=timeout)

    def create_dspy_lm(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        cache: bool = True,
        timeout: Optional[float] = None,
        api_key: Optional[str] = None,
    ) -> dspy.LM:
        key = api_key or self.resolve_api_key() or "local-token-placeholder"
        m = model or self._definition.default_model
        model_name = m if m.startswith("openai/") else f"openai/{m}"
        base_url = self._get_base_url()
        to = timeout or self._definition.config.timeout_seconds

        kwargs: Dict[str, Any] = {
            "api_key": key,
            "api_base": base_url,
            "max_tokens": max_tokens or 2000,
            "cache": cache,
            "timeout": to,
        }
        return dspy.LM(model_name, **kwargs)

    def invoke(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderInvocationResult:
        lm = self.create_dspy_lm(model=model, max_tokens=max_tokens)
        t0 = time.perf_counter()
        try:
            call_kwargs = {}
            if temperature is not None:
                call_kwargs["temperature"] = temperature
            res = lm(prompt, **call_kwargs)
            text = res[0] if isinstance(res, list) else str(res)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return ProviderInvocationResult(
                content=text,
                model=model or self._definition.default_model,
                provider_id=self.provider_id,
                latency_ms=elapsed_ms,
            )
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "auth" in err_str:
                raise ProviderAuthenticationError(str(e), provider_id=self.provider_id) from e
            if "429" in err_str or "rate limit" in err_str:
                raise ProviderRateLimitError(str(e), provider_id=self.provider_id) from e
            if "timeout" in err_str:
                raise ProviderTimeoutError(str(e), provider_id=self.provider_id) from e
            if "connection" in err_str:
                raise ProviderConnectionError(str(e), provider_id=self.provider_id) from e
            raise NormalizedProviderError(str(e), provider_id=self.provider_id) from e

    def stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        lm = self.create_dspy_lm(model=model, max_tokens=max_tokens)
        if hasattr(lm, "stream"):
            yield from lm.stream(prompt, **kwargs)
        else:
            res = self.invoke(prompt, model=model, max_tokens=max_tokens, **kwargs)
            yield res.content
