# core/router/model_router.py
import logging
import os
import sys
from typing import Any, Callable

import dspy
from dotenv import load_dotenv

from core.router.circuit_breaker import CircuitBreaker
from core.router.config import RouterConfigFile, load_router_config
from core.router.health import HealthProber

# Ensure core.models is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

# Configure logging
logger = logging.getLogger("agent_engine.router")


class ModelRouter:
    """
    Hardened smart router with circuit breaker, active latency probing,
    per-task preference chains, and resilient fallback execution.
    """

    def __init__(
        self,
        config: RouterConfigFile | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        health_prober: HealthProber | None = None,
    ) -> None:
        self.config = config or load_router_config()
        self.provider_priority = list(self.config.default_priority)
        self.circuit_breaker = circuit_breaker or CircuitBreaker(self.config.circuit_breaker)
        self.health_prober = health_prober or HealthProber(
            default_timeout=self.config.health_check.timeout_seconds,
            cache_ttl_seconds=self.config.health_check.cache_ttl_seconds,
        )
        self._configured_lm: dspy.LM | None = None
        self._configured_label: str | None = None
        self._active_provider: str | None = None

    def _check_api_key(self, provider: str) -> bool:
        """Return True if the provider requires an API key and it is present."""
        return self.health_prober._check_api_key(provider)

    def check_local_ollama_health(self) -> bool:
        """Check if Ollama is reachable."""
        res = self.health_prober.probe_ollama()
        return res.online

    def check_local_llamacpp_health(self) -> bool:
        """Check if llama.cpp server is reachable."""
        res = self.health_prober.probe_llamacpp()
        return res.online

    def get_status(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return comprehensive health, latency, circuit state, and key status for all providers."""
        providers = [
            "ollama",
            "llamacpp",
            "gemini",
            "openai",
            "anthropic",
            "deepseek",
            "groq",
            "kimi",
        ]
        probe_results = self.health_prober.probe_all(
            providers=providers, force_refresh=force_refresh
        )
        status: dict[str, Any] = {}

        for p in providers:
            probe = probe_results.get(p)
            online = probe.online if probe else False
            latency = probe.latency_ms if probe else 0.0
            circuit_state = self.circuit_breaker.get_state(p)

            status[f"{p}_live"] = online
            status[f"{p}_latency_ms"] = latency
            status[f"{p}_circuit_state"] = circuit_state.value
            status[f"{p}_key_present"] = self._check_api_key(p)

        # Primary and fallback providers respecting circuit breaker and priority
        available = [
            p
            for p in self.provider_priority
            if (status.get(f"{p}_live") or status.get(f"{p}_key_present"))
            and self.circuit_breaker.can_attempt(p)
        ]
        status["primary_provider"] = (
            available[0]
            if available
            else (self.provider_priority[0] if self.provider_priority else "llamacpp")
        )
        status["fallback_provider"] = available[1] if len(available) > 1 else "llamacpp"
        status["active_model"] = self._configured_label or os.getenv(
            "LOCAL_MODEL_NAME", "qwen2.5-coder-3b-instruct-q4_k_m"
        )
        status["active_provider"] = self._active_provider or status["primary_provider"]
        status["circuit_breakers"] = self.circuit_breaker.get_status()
        return status

    def get_available_providers(self, task_type: str | None = None) -> list[str]:
        """
        Return an ordered list of providers available for invocation,
        filtering out providers whose circuit breaker is OPEN.
        """
        status = self.get_status()
        candidates: list[str]
        if task_type and task_type in self.config.task_preferences:
            candidates = self.config.task_preferences[task_type]
        else:
            candidates = self.provider_priority

        available: list[str] = []
        for p in candidates:
            # Fast fail: skip providers with OPEN circuit breaker immediately
            if not self.circuit_breaker.can_attempt(p):
                logger.debug("Skipping provider '%s': circuit breaker is OPEN", p)
                continue

            if status.get(f"{p}_live", False) or status.get(f"{p}_key_present", False):
                available.append(p)

        # If task preferences yielded no available providers, fall back to general priority
        if not available and task_type:
            for p in self.provider_priority:
                if self.circuit_breaker.can_attempt(p) and (
                    status.get(f"{p}_live", False) or status.get(f"{p}_key_present", False)
                ):
                    available.append(p)

        return available

    def create_lm(
        self, provider: str, cache: bool = True, num_ctx: int = 4096, **kwargs: Any
    ) -> tuple[dspy.LM, str]:
        """Instantiate a dspy.LM for the given provider using core.models.get_model_provider."""
        from core.models import get_model_provider

        model_name = kwargs.get("model") or kwargs.get("model_name")
        api_key = kwargs.get("api_key")
        if api_key:
            key_name = f"{provider.upper()}_API_KEY"
            os.environ[key_name] = api_key

        lm = get_model_provider(
            provider_name=provider,
            model_name=model_name,
            cache=cache,
            max_tokens=num_ctx,
        )
        if provider == "openai":
            label = f"OpenAI ({model_name or 'gpt-4o-mini'})"
        else:
            label = f"{provider.capitalize()} (ctx={num_ctx})"
        return lm, label

    def initialize_and_configure(
        self,
        force_provider: str | None = None,
        task_type: str | None = None,
        cache: bool = True,
        num_ctx: int = 4096,
    ) -> tuple[dspy.LM, str]:
        """
        Configure dspy.settings with the best provider according to priority/task chains
        and circuit breaker status. Traverses fallback chain automatically if a candidate fails.
        """
        if force_provider:
            # If forced provider's circuit is OPEN, warn and fall through to chain
            if not self.circuit_breaker.can_attempt(force_provider):
                logger.warning(
                    "Forced provider '%s' circuit is OPEN. Initiating fallback chain traversal.",
                    force_provider,
                )
            else:
                try:
                    logger.info("Attempting forced provider '%s'...", force_provider)
                    lm, label = self.create_lm(force_provider, cache=cache, num_ctx=num_ctx)
                    dspy.settings.configure(lm=lm, cache=cache)
                    self._configured_lm = lm
                    self._configured_label = label
                    self._active_provider = force_provider
                    self.circuit_breaker.record_success(force_provider)
                    logger.info("Configured forced LM: %s", label)
                    return lm, label
                except Exception as e:
                    logger.error(
                        "Failed to initialize forced provider '%s': %s",
                        force_provider,
                        e,
                    )
                    self.circuit_breaker.record_failure(force_provider, e)
                    # Fall through to fallback chain

        # Fallback chain selection
        available = self.get_available_providers(task_type=task_type)
        logger.info(
            "Evaluating fallback chain for task '%s': %s",
            task_type or "default",
            available,
        )

        for p in available:
            logger.info("Evaluating provider in fallback chain: '%s'...", p)
            try:
                lm, label = self.create_lm(p, cache=cache, num_ctx=num_ctx)
                dspy.settings.configure(lm=lm, cache=cache)
                self._configured_lm = lm
                self._configured_label = label
                self._active_provider = p
                self.circuit_breaker.record_success(p)
                logger.info("Configured LM: %s (selected from fallback chain)", label)
                return lm, label
            except Exception as e:
                logger.warning(
                    "Provider '%s' initialization failed: %s. Tripping breaker and advancing fallback chain...",
                    p,
                    e,
                )
                self.circuit_breaker.record_failure(p, e)
                continue

        # Ultimate fallback: try local llama.cpp directly if not already tried
        if self.circuit_breaker.can_attempt("llamacpp"):
            logger.warning(
                "No provider from fallback chain succeeded. Trying local llama.cpp safe fallback..."
            )
            try:
                lm, label = self.create_lm("llamacpp", cache=cache, num_ctx=num_ctx)
                dspy.settings.configure(lm=lm, cache=cache)
                self._configured_lm = lm
                self._configured_label = label
                self._active_provider = "llamacpp"
                self.circuit_breaker.record_success("llamacpp")
                return lm, label
            except Exception as e:
                self.circuit_breaker.record_failure("llamacpp", e)
                logger.critical("Local fallback llama.cpp failed: %s", e)

        raise RuntimeError(
            "No LLM provider available in fallback chain. All circuits OPEN or offline."
        )

    def execute_with_fallback(
        self,
        call_fn: Callable[[dspy.LM], Any],
        task_type: str | None = None,
        max_retries: int = 3,
    ) -> Any:
        """
        Execute an LM invocation with automated fallback failover across the chain.
        If the active provider throws at runtime, its circuit breaker records the failure,
        the next available provider is engaged, and the call is retried.
        """
        attempt = 0
        last_exception: Exception | None = None

        while attempt < max_retries:
            attempt += 1
            if not self._configured_lm or (
                self._active_provider
                and not self.circuit_breaker.can_attempt(self._active_provider)
            ):
                self.initialize_and_configure(task_type=task_type)

            active_p = self._active_provider or "unknown"
            try:
                result = call_fn(self._configured_lm)
                self.circuit_breaker.record_success(active_p)
                return result
            except Exception as e:
                last_exception = e
                logger.warning(
                    "Execution error on provider '%s' (attempt %d/%d): %s. Recording failure & falling back...",
                    active_p,
                    attempt,
                    max_retries,
                    e,
                )
                self.circuit_breaker.record_failure(active_p, e)
                # Invalidate configured LM to force failover to next provider
                self._configured_lm = None
                self._active_provider = None

        raise RuntimeError(
            f"Execution failed after {max_retries} fallback attempts: {last_exception}"
        ) from last_exception

    def get_current_lm(self) -> dspy.LM | None:
        return self._configured_lm

    def get_current_label(self) -> str | None:
        return self._configured_label

    def get_active_provider(self) -> str | None:
        return self._active_provider
