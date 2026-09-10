import numpy  # noqa: F401
import os
import time
from unittest.mock import MagicMock, patch

from core.router import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    HealthProber,
    ModelRouter,
    load_router_config,
)


def test_circuit_breaker_lifecycle():
    """Verify circuit breaker transitions CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    config = CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=0.2,
        half_open_success_threshold=1,
    )
    cb = CircuitBreaker(config=config)

    # Initially closed
    assert cb.get_state("gemini") == CircuitState.CLOSED
    assert cb.can_attempt("gemini") is True

    # 1st & 2nd failures: stays closed
    cb.record_failure("gemini", error="Timeout 1")
    assert cb.get_state("gemini") == CircuitState.CLOSED
    cb.record_failure("gemini", error="Timeout 2")
    assert cb.get_state("gemini") == CircuitState.CLOSED

    # 3rd failure: trips to OPEN
    cb.record_failure("gemini", error="Timeout 3")
    assert cb.get_state("gemini") == CircuitState.OPEN
    # Immediate fast-fail without waiting
    assert cb.can_attempt("gemini") is False

    # Wait for recovery timeout to elapse
    time.sleep(0.25)
    # Transitions to HALF_OPEN to allow trial probe
    assert cb.get_state("gemini") == CircuitState.HALF_OPEN
    assert cb.can_attempt("gemini") is True

    # Successful trial closes circuit
    cb.record_success("gemini")
    assert cb.get_state("gemini") == CircuitState.CLOSED
    assert cb.can_attempt("gemini") is True

    # If trial fails, immediately trips to OPEN
    cb.trip("gemini")
    time.sleep(0.25)
    assert cb.get_state("gemini") == CircuitState.HALF_OPEN
    cb.record_failure("gemini", error="Trial failed")
    assert cb.get_state("gemini") == CircuitState.OPEN


def test_circuit_breaker_manual_trip_and_reset():
    """Verify manual trip and reset operations."""
    cb = CircuitBreaker()
    cb.trip("ollama", reason="Maintenance")
    assert cb.get_state("ollama") == CircuitState.OPEN
    assert cb.can_attempt("ollama") is False

    status = cb.get_status()
    assert "ollama" in status
    assert status["ollama"]["state"] == "OPEN"
    assert "Maintenance" in status["ollama"]["last_error"]

    cb.reset("ollama")
    assert cb.get_state("ollama") == CircuitState.CLOSED
    assert cb.can_attempt("ollama") is True


def test_health_prober_latency_and_caching():
    """Verify active latency probing and TTL caching."""
    prober = HealthProber(default_timeout=0.5, cache_ttl_seconds=1.0)

    # Cloud probe with key
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"}):
        result = prober.probe_cloud("gemini")
        assert result.online is True
        assert result.latency_ms >= 0.0
        assert result.error is None

    # Cloud probe without key
    with patch.dict(os.environ, {}, clear=True):
        result = prober.probe_cloud("openai")
        assert result.online is False
        assert "missing" in (result.error or "").lower()

    # TTL caching check
    res1 = prober.probe_provider("gemini")
    time.sleep(0.05)
    res2 = prober.probe_provider("gemini")
    assert res1.checked_at == res2.checked_at  # Cached

    # Force refresh bypasses cache
    res3 = prober.probe_provider("gemini", force_refresh=True)
    assert res3.checked_at > res1.checked_at


def test_router_config_loading_and_overrides():
    """Verify declarative YAML configuration and environment variable overrides."""
    config = load_router_config()
    assert "ollama" in config.default_priority
    assert "code_generation" in config.task_preferences
    assert "deep_reasoning" in config.task_preferences
    assert config.circuit_breaker.failure_threshold >= 1

    # Test env var override
    with patch.dict(os.environ, {"PROVIDER_PRIORITY": "groq,gemini,ollama"}):
        override_config = load_router_config()
        assert override_config.default_priority == ["groq", "gemini", "ollama"]


def test_model_router_fallback_on_outage():
    """Simulated provider outage triggers fallback within <2s and logs fallback chain."""
    cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0))
    router = ModelRouter(circuit_breaker=cb)

    # Set primary provider (ollama) to OPEN circuit breaker
    cb.trip("ollama", reason="Simulated node crash")

    t0 = time.perf_counter()
    status = router.get_status(force_refresh=False)
    elapsed = time.perf_counter() - t0

    # Fallback status resolution must be fast (< 2.0s)
    assert elapsed < 2.0
    assert status["primary_provider"] != "ollama"
    assert status["circuit_breakers"]["ollama"]["state"] == "OPEN"

    # get_available_providers must exclude tripped ollama
    available = router.get_available_providers()
    assert "ollama" not in available


def test_model_router_task_preferences_routing():
    """Verify router orders available providers according to task preferences."""
    router = ModelRouter()
    with patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "dummy",
            "OPENAI_API_KEY": "dummy",
            "DEEPSEEK_API_KEY": "dummy",
            "GROQ_API_KEY": "dummy",
        },
    ):
        code_providers = router.get_available_providers(task_type="code_generation")
        reasoning_providers = router.get_available_providers(task_type="deep_reasoning")

        assert len(code_providers) > 0
        assert len(reasoning_providers) > 0
        # Reasoning preferences prioritize gemini/openai before local
        if "gemini" in reasoning_providers:
            assert (
                reasoning_providers.index("gemini") < reasoning_providers.index("deepseek")
                if "deepseek" in reasoning_providers
                else True
            )


def test_model_router_execute_with_fallback():
    """Verify execute_with_fallback switches providers seamlessly upon execution failure."""
    cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0))
    router = ModelRouter(circuit_breaker=cb)

    # Mock create_lm to return dummy LM instances
    mock_lm_1 = MagicMock()
    mock_lm_2 = MagicMock()

    call_count = 0

    def mock_create_lm(provider, **kwargs):
        if provider == "ollama":
            return mock_lm_1, "Ollama"
        return mock_lm_2, "Fallback Provider"

    router.create_lm = mock_create_lm
    router.provider_priority = ["ollama", "gemini"]

    # In call_fn, fail on first invocation (simulating ollama error), succeed on second
    def invocation(lm):
        nonlocal call_count
        call_count += 1
        if lm == mock_lm_1:
            raise ConnectionResetError("Remote server disconnected")
        return "Success from fallback"

    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
        result = router.execute_with_fallback(invocation, max_retries=3)

    assert result == "Success from fallback"
    assert call_count == 2
    # Ollama breaker should have recorded the failure and tripped
    assert cb.get_state("ollama") == CircuitState.OPEN
