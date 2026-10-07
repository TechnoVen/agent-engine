"""core/providers/adapters/llamacpp.py

llama.cpp Local Provider Adapter for Agent Engine.
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
    ProviderAvailability,
    ProviderConfigurationState,
    ProviderHealth,
    ProviderHealthStatus,
)

logger = logging.getLogger("agent_engine.providers.llamacpp")


class LlamaCppAdapter(ProviderAdapter):
    """Canonical adapter for local llama.cpp server infrastructure."""

    def _get_base_url(self) -> str:
        url = (
            self._definition.config.endpoint_url
            or os.getenv("LLAMACPP_HOST")
            or "http://localhost:8080/v1"
        ).rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return url

    def test_connection(self, timeout: float = 3.0) -> ProviderHealth:
        effective_timeout = min(timeout, 5.0)
        base_url = self._get_base_url()
        probe_url = f"{base_url}/models"

        t0 = time.perf_counter()
        try:
            resp = requests.get(probe_url, timeout=effective_timeout)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            if resp.status_code == 200:
                threshold = self._definition.capabilities.degraded_latency_threshold_ms
                status = (
                    ProviderHealthStatus.DEGRADED
                    if elapsed_ms > threshold
                    else ProviderHealthStatus.HEALTHY
                )
                h = ProviderHealth(
                    config_state=ProviderConfigurationState.CONFIGURED,
                    availability=ProviderAvailability.AVAILABLE,
                    status=status,
                    latency_ms=elapsed_ms,
                    last_checked_at=time.time(),
                    consecutive_failures=0,
                    probe_type="transport_reachability",
                    details={"status_code": 200, "endpoint": probe_url},
                )
            else:
                h = ProviderHealth(
                    config_state=ProviderConfigurationState.CONFIGURED,
                    availability=ProviderAvailability.AVAILABLE,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=elapsed_ms,
                    error_message=f"HTTP {resp.status_code}: Upstream error",
                    last_checked_at=time.time(),
                    probe_type="transport_reachability",
                    details={"status_code": resp.status_code},
                )
        except requests.Timeout:
            h = ProviderHealth(
                config_state=ProviderConfigurationState.CONFIGURED,
                availability=ProviderAvailability.UNAVAILABLE,
                status=ProviderHealthStatus.UNHEALTHY,
                error_message=f"llama.cpp connection timed out after {effective_timeout}s",
                last_checked_at=time.time(),
                probe_type="transport_reachability",
            )
        except Exception:
            h = ProviderHealth(
                config_state=ProviderConfigurationState.CONFIGURED,
                availability=ProviderAvailability.UNAVAILABLE,
                status=ProviderHealthStatus.UNHEALTHY,
                error_message="Cannot reach llama.cpp server",
                last_checked_at=time.time(),
                probe_type="transport_reachability",
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
        api_key: Optional[str] = None,
    ) -> dspy.LM:
        m = model or self._definition.default_model
        env_model = os.getenv("LOCAL_MODEL_NAME")
        if not model and env_model:
            m = env_model
        model_name = m if m.startswith("openai/") else f"openai/{m}"
        base_url = self._get_base_url()
        to = timeout or self._definition.config.timeout_seconds or 120.0
        token = api_key or "local-token-placeholder"

        return dspy.LM(
            model_name,
            api_base=base_url,
            api_key=token,
            max_tokens=min(max_tokens or 1024, 2048),
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
