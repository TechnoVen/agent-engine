"""core/providers/adapters/ollama.py

Ollama Local Provider Adapter for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterator, Optional

import dspy
import requests

from core.providers.base import (
    NormalizedProviderError,
    ProviderAdapter,
    ProviderConnectionError,
    ProviderInvocationResult,
    ProviderTimeoutError,
)
from core.providers.models import (
    ProviderHealth,
    ProviderHealthStatus,
)

logger = logging.getLogger("agent_engine.providers.ollama")


class OllamaAdapter(ProviderAdapter):
    """Canonical adapter for local Ollama daemon service."""

    def _get_base_url(self) -> str:
        return (
            self._definition.config.endpoint_url
            or os.getenv("OLLAMA_BASE_URL")
            or "http://localhost:11434"
        ).rstrip("/")

    def test_connection(self, timeout: float = 3.0) -> ProviderHealth:
        base_url = self._get_base_url()
        probe_url = f"{base_url}/api/tags"

        t0 = time.perf_counter()
        try:
            resp = requests.get(probe_url, timeout=timeout)
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
                error_message=f"Ollama connection timed out after {timeout}s",
                last_checked_at=time.time(),
            )
        except Exception as e:
            h = ProviderHealth(
                status=ProviderHealthStatus.UNAVAILABLE,
                error_message=f"Cannot reach Ollama at {base_url}: {e}",
                last_checked_at=time.time(),
            )

        self._definition.health = h
        return h

    def check_health(self, timeout: float = 2.0) -> ProviderHealth:
        return self.test_connection(timeout=timeout)

    def create_dspy_lm(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        cache: bool = True,
        timeout: Optional[float] = None,
    ) -> dspy.LM:
        m = model or self._definition.default_model
        # Use configured environment override if available
        env_model = os.getenv("OLLAMA_MODEL")
        if not model and env_model:
            m = env_model
        model_name = m if m.startswith("ollama_chat/") else f"ollama_chat/{m}"
        base_url = self._get_base_url()
        to = timeout or self._definition.config.timeout_seconds or 120.0

        return dspy.LM(
            model_name,
            api_base=base_url,
            max_tokens=min(max_tokens or 1024, 4096),
            cache=cache,
            timeout=to,
        )

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
