"""core/providers/adapters/anthropic.py

Anthropic Provider Adapter for Agent Engine.
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

logger = logging.getLogger("agent_engine.providers.anthropic")


class AnthropicAdapter(ProviderAdapter):
    """Canonical adapter for Anthropic Claude models."""

    def test_connection(self, timeout: float = 5.0) -> ProviderHealth:
        key = self.resolve_api_key()
        if not key:
            h = ProviderHealth(
                status=ProviderHealthStatus.AUTHENTICATION_FAILED,
                error_message="Missing Anthropic API key in SecretsService or environment",
                last_checked_at=time.time(),
            )
            self._definition.health = h
            return h

        endpoint = (self._definition.config.endpoint_url or "https://api.anthropic.com").rstrip("/")
        models_url = f"{endpoint}/v1/models"

        t0 = time.perf_counter()
        try:
            resp = requests.get(
                models_url,
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=timeout,
            )
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
                    details={"status_code": 200, "endpoint": models_url},
                )
            elif resp.status_code in (401, 403):
                h = ProviderHealth(
                    status=ProviderHealthStatus.AUTHENTICATION_FAILED,
                    latency_ms=elapsed_ms,
                    error_message=f"HTTP {resp.status_code}: Invalid Anthropic API key",
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
                error_message=str(e),
                last_checked_at=time.time(),
            )

        self._definition.health = h
        return h

    def check_health(self, timeout: float = 3.0) -> ProviderHealth:
        key = self.resolve_api_key()
        if not key:
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
        key = api_key or self.resolve_api_key()
        m = model or self._definition.default_model
        model_name = m if m.startswith("anthropic/") else f"anthropic/{m}"
        to = timeout or self._definition.config.timeout_seconds
        api_base = self._definition.config.endpoint_url

        kwargs: Dict[str, Any] = {
            "api_key": key,
            "max_tokens": max_tokens or 4000,
            "cache": cache,
            "timeout": to,
        }
        if api_base:
            kwargs["api_base"] = api_base

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
