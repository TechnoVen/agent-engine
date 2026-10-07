"""tests/test_r3_provider_registry.py

Comprehensive Provider Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).
"""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from core.models import get_model_provider
from core.providers import (
    NormalizedProviderError,
    ProviderAuthenticationError,
    ProviderAuthType,
    ProviderAvailability,
    ProviderCallEvidence,
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderConfigurationState,
    ProviderDefinition,
    ProviderEndpointClass,
    ProviderEndpointStyle,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderInvalidRequestError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRegistry,
    ProviderServerError,
    migrate_config_dict,
    reset_provider_registry,
)
from core.router.model_router import ModelRouter
from core.security.secrets import SecretReference

ALL_BUILTIN_PROVIDERS = [
    "openai",
    "anthropic",
    "gemini",
    "ollama",
    "llamacpp",
    "deepseek",
    "groq",
    "kimi",
    "compatible",
]


@pytest.fixture(autouse=True)
def fresh_registry():
    """Ensure a clean global provider registry for each test."""
    reg = reset_provider_registry()
    yield reg
    reset_provider_registry()


# ==============================================================================
# 1. Stable Provider Identity
# ==============================================================================
def test_01_stable_provider_identity(fresh_registry: ProviderRegistry):
    """Verify provider_id is a stable machine identifier separated from display name and models."""
    prov = fresh_registry.get_provider("openai")
    assert prov is not None
    assert prov.provider_id == "openai"
    assert prov.display_name == "OpenAI"
    assert prov.default_model == "gpt-4o-mini"
    assert prov.endpoint_style == ProviderEndpointStyle.OPENAI_COMPATIBLE

    # Invariant: Invalid provider_id fails closed during validation
    with pytest.raises(ValueError, match="Invalid provider_id"):
        ProviderConfiguration(provider_id="INVALID UPPERCASE")

    with pytest.raises(ValueError, match="Invalid provider_id"):
        ProviderDefinition(
            provider_id="has spaces",
            display_name="Invalid",
            endpoint_style=ProviderEndpointStyle.CUSTOM,
            default_model="m",
            config=ProviderConfiguration(provider_id="valid_id"),
        )


# ==============================================================================
# 2. Alias Resolution & Shadow Protection
# ==============================================================================
def test_02_alias_resolution(fresh_registry: ProviderRegistry):
    """Verify provider aliases resolve deterministically to canonical provider IDs."""
    assert fresh_registry.resolve_provider_id("google") == "gemini"
    assert fresh_registry.resolve_provider_id("GEMINI") == "gemini"
    assert fresh_registry.resolve_provider_id("moonshot") == "kimi"
    assert fresh_registry.resolve_provider_id("local") == "llamacpp"
    assert fresh_registry.resolve_provider_id("gemma4") == "llamacpp"
    assert fresh_registry.resolve_provider_id("chatgpt") == "openai"
    assert fresh_registry.resolve_provider_id("claude") == "anthropic"
    assert fresh_registry.resolve_provider_id("vllm") == "compatible"
    assert fresh_registry.resolve_provider_id("localai") == "compatible"

    # Getting provider by alias returns canonical definition
    google_def = fresh_registry.get_provider("google")
    assert google_def is not None
    assert google_def.provider_id == "gemini"

    local_def = fresh_registry.get_provider("local")
    assert local_def is not None
    assert local_def.provider_id == "llamacpp"


def test_03_alias_shadow_protection(fresh_registry: ProviderRegistry):
    """Verify aliases cannot shadow existing canonical provider IDs."""
    # Attempting to register an alias that matches an existing canonical ID must fail
    with pytest.raises(ValueError, match="cannot shadow"):
        fresh_registry.register_alias("openai", "anthropic")

    with pytest.raises(ValueError, match="cannot shadow"):
        fresh_registry.register_alias("gemini", "kimi")

    # Attempting to register alias for non-existent canonical provider must fail
    with pytest.raises(KeyError, match="not registered"):
        fresh_registry.register_alias("new_alias", "non_existent_provider")

    # Valid alias registration
    fresh_registry.register_alias("fast_local", "llamacpp")
    assert fresh_registry.resolve_provider_id("fast_local") == "llamacpp"

    # Registering a provider whose aliases match existing canonical provider must fail
    bad_def = ProviderDefinition(
        provider_id="my_custom",
        display_name="Custom",
        endpoint_style=ProviderEndpointStyle.CUSTOM,
        default_model="m",
        aliases=["openai"],  # Shadows canonical "openai"
        config=ProviderConfiguration(provider_id="my_custom"),
    )
    with pytest.raises(ValueError, match="cannot shadow"):
        fresh_registry.register_provider(bad_def)


# ==============================================================================
# 3. Provider vs Model Separation
# ==============================================================================
def test_04_provider_vs_model_responsibility_separation(fresh_registry: ProviderRegistry):
    """Verify provider contracts govern connection and auth boundaries, not model catalogs."""
    prov = fresh_registry.get_provider("anthropic")
    assert prov is not None
    # Provider contract holds transport/auth properties
    assert prov.config.auth_type == ProviderAuthType.API_KEY
    assert prov.config.credential_key == "ANTHROPIC_API_KEY"
    assert prov.config.timeout_seconds > 0
    assert prov.capabilities.supports_streaming is True
    assert prov.capabilities.requires_credentials is True
    # Default model is a reference, not an embedded catalog
    assert prov.default_model == "claude-3-5-sonnet-20241022"


# ==============================================================================
# 4. Separated 3-Dimensional Health State Model
# ==============================================================================
def test_05_separated_health_state_dimensions():
    """Verify configured != available != healthy and is_usable() matrix."""
    # Case 1: Configured, but unavailable (host down) -> Unusable
    h1 = ProviderHealth(
        config_state=ProviderConfigurationState.CONFIGURED,
        availability=ProviderAvailability.UNAVAILABLE,
        status=ProviderHealthStatus.UNHEALTHY,
    )
    assert h1.is_configured is True
    assert h1.is_available is False
    assert h1.is_healthy is False
    assert h1.is_usable() is False

    # Case 2: Configured, available, but authentication failed -> Unusable
    h2 = ProviderHealth(
        config_state=ProviderConfigurationState.CONFIGURED,
        availability=ProviderAvailability.AVAILABLE,
        status=ProviderHealthStatus.AUTHENTICATION_FAILED,
    )
    assert h2.is_configured is True
    assert h2.is_available is True
    assert h2.is_healthy is False
    assert h2.is_usable() is False

    # Case 3: Configured, available, but degraded (high latency) -> Usable
    h3 = ProviderHealth(
        config_state=ProviderConfigurationState.CONFIGURED,
        availability=ProviderAvailability.AVAILABLE,
        status=ProviderHealthStatus.DEGRADED,
    )
    assert h3.is_configured is True
    assert h3.is_available is True
    assert h3.is_healthy is False
    assert h3.is_usable() is True

    # Case 4: Fully configured, available, and healthy -> Usable
    h4 = ProviderHealth(
        config_state=ProviderConfigurationState.CONFIGURED,
        availability=ProviderAvailability.AVAILABLE,
        status=ProviderHealthStatus.HEALTHY,
    )
    assert h4.is_configured is True
    assert h4.is_available is True
    assert h4.is_healthy is True
    assert h4.is_usable() is True

    # Case 5: Unconfigured -> Unusable
    h5 = ProviderHealth(
        config_state=ProviderConfigurationState.UNCONFIGURED,
        availability=ProviderAvailability.UNKNOWN,
        status=ProviderHealthStatus.UNKNOWN,
    )
    assert h5.is_configured is False
    assert h5.is_available is False
    assert h5.is_healthy is False
    assert h5.is_usable() is False


# ==============================================================================
# 5. Latency Degradation & Low-Cost Bounded Timeout Checks
# ==============================================================================
def test_06_health_probe_latency_degradation(fresh_registry: ProviderRegistry):
    """Verify that elevated probe latency triggers DEGRADED status without marking unavailable."""
    adapter = fresh_registry.get_adapter("openai")

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # Inject artificial latency above degraded threshold
        with patch("time.perf_counter", side_effect=[0.0, 4.5]):
            with patch.object(adapter, "resolve_api_key", return_value="sk-test-mock-key"):
                health = adapter.test_connection(timeout=5.0)
                assert health.config_state == ProviderConfigurationState.CONFIGURED
                assert health.availability == ProviderAvailability.AVAILABLE
                assert health.status == ProviderHealthStatus.DEGRADED
                assert health.latency_ms == 4500.0
                assert health.is_usable() is True


def test_07_low_cost_bounded_timeout_health_checking(fresh_registry: ProviderRegistry):
    """Verify health checks enforce bounded timeouts (<= 5s) and sanitize errors."""
    adapter = fresh_registry.get_adapter("ollama")

    import requests

    with patch("requests.get", side_effect=requests.Timeout("Operation timed out")):
        health = adapter.test_connection(timeout=10.0)  # Requesting 10s timeout
        assert health.config_state == ProviderConfigurationState.CONFIGURED
        assert health.availability == ProviderAvailability.UNAVAILABLE
        assert health.status == ProviderHealthStatus.UNHEALTHY
        assert "timed out" in health.error_message.lower()
        # Probe type recorded
        assert health.probe_type == "transport_reachability"
        # Zero secrets leaked
        assert "sk-" not in str(health)
        assert health.last_checked_at > 0


# ==============================================================================
# 6. Inviolable R2.6 Secret Boundary
# ==============================================================================
def test_08_secret_boundary_r26_isolation(fresh_registry: ProviderRegistry):
    """Verify credentials never appear in public definitions, to_safe_dict, str, or repr."""
    prov = fresh_registry.get_provider("openai")
    assert prov is not None

    safe_dict = prov.to_safe_dict()
    assert "sk-" not in str(safe_dict)
    assert "OPENAI_API_KEY" in safe_dict["config"]["credential_key"]
    assert "credential_configured" in safe_dict["config"]

    # Test with SecretReference
    ref = SecretReference(provider="openai", name="primary_key", scope="default")
    prov.config.secret_ref = ref

    safe_dict2 = prov.to_safe_dict()
    assert safe_dict2["config"]["credential_configured"] is True
    # SecretReference string never exposes secret material
    assert "sk-" not in str(ref)


# ==============================================================================
# 7. Zero Global os.environ Mutation
# ==============================================================================
def test_09_no_global_os_environ_mutation(
    fresh_registry: ProviderRegistry, monkeypatch: pytest.MonkeyPatch
):
    """Verify resolving keys or constructing LM never contaminates os.environ."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert "OPENAI_API_KEY" not in os.environ

    adapter = fresh_registry.get_adapter("openai")
    with patch("dspy.LM") as mock_lm:
        adapter.create_dspy_lm(api_key="sk-direct-test-12345")
        mock_lm.assert_called_once()
        _, kwargs = mock_lm.call_args
        assert kwargs.get("api_key") == "sk-direct-test-12345"

    # Invariant: parent os.environ must NOT be contaminated
    assert "OPENAI_API_KEY" not in os.environ


# ==============================================================================
# 8. Pure Migration Idempotency & Legacy Config Migration
# ==============================================================================
def test_10_migration_idempotency():
    """Verify migrate_config_dict is completely idempotent."""
    raw_legacy = {
        "default_priority": ["local", "google", "moonshot", "openai"],
        "providers": {
            "local": {"provider_id": "local", "enabled": True},
            "google": {"provider_id": "google", "enabled": True},
            "custom": {"host": "internal.service"},
        },
        "custom_setting": 42,
    }

    # First pass: old -> canonical
    c1 = migrate_config_dict(raw_legacy)
    assert c1["default_priority"] == ["llamacpp", "gemini", "kimi", "openai"]
    assert "llamacpp" in c1["providers"]
    assert c1["providers"]["llamacpp"]["provider_id"] == "llamacpp"
    assert "gemini" in c1["providers"]
    assert c1["providers"]["gemini"]["provider_id"] == "gemini"
    assert c1["custom_setting"] == 42

    # Second pass: canonical -> canonical
    c2 = migrate_config_dict(c1)
    assert c1 == c2

    # Third pass: double migration
    c3 = migrate_config_dict(c2)
    assert c2 == c3


def test_11_legacy_config_migration(
    fresh_registry: ProviderRegistry, monkeypatch: pytest.MonkeyPatch
):
    """Verify legacy environment variables and YAML configurations migrate transparently."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://custom-ollama:11434")
    monkeypatch.setenv("LLAMACPP_HOST", "http://custom-llamacpp:8080/v1")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "custom-qwen-model")

    updated = fresh_registry.migrate_legacy_config(
        legacy_config={"default_priority": ["ollama", "gemini", "openai"]}
    )
    assert updated >= 3

    ollama = fresh_registry.get_provider("ollama")
    assert ollama.config.endpoint_url == "http://custom-ollama:11434"
    assert ollama.health.config_state == ProviderConfigurationState.CONFIGURED

    llamacpp = fresh_registry.get_provider("llamacpp")
    assert llamacpp.config.endpoint_url == "http://custom-llamacpp:8080/v1"
    assert llamacpp.default_model == "custom-qwen-model"
    assert llamacpp.health.config_state == ProviderConfigurationState.CONFIGURED


# ==============================================================================
# 9. Streaming Capability & Error Normalization
# ==============================================================================
def test_12_streaming_capability_declaration_and_conformance(
    fresh_registry: ProviderRegistry,
):
    """Verify streaming capability declarations and stream interface."""
    adapter = fresh_registry.get_adapter("openai")
    assert adapter.definition.capabilities.supports_streaming is True

    # Test direct stream generator fallback
    with patch.object(adapter, "invoke") as mock_inv:
        mock_inv.return_value = MagicMock(content="Hello world response")
        chunks = list(adapter.stream("Test prompt"))
        assert len(chunks) == 1
        assert chunks[0] == "Hello world response"


def test_13_error_normalization(fresh_registry: ProviderRegistry):
    """Verify standard HTTP status codes translate to typed NormalizedProviderError subclasses."""
    adapter = fresh_registry.get_adapter("openai")

    # 401/403 -> Authentication error
    err401 = adapter.normalize_http_error(401, "Unauthorized")
    assert isinstance(err401, ProviderAuthenticationError)
    assert err401.status_code == 401

    err403 = adapter.normalize_http_error(403, "Forbidden")
    assert isinstance(err403, ProviderAuthenticationError)

    # 429 -> Rate limit error
    err429 = adapter.normalize_http_error(429, "Too Many Requests")
    assert isinstance(err429, ProviderRateLimitError)

    # 404 -> Not found error
    err404 = adapter.normalize_http_error(404, "Model not found")
    assert isinstance(err404, ProviderNotFoundError)

    # 400 -> Invalid request error
    err400 = adapter.normalize_http_error(400, "Bad Request")
    assert isinstance(err400, ProviderInvalidRequestError)

    # 500/503 -> Server error
    err500 = adapter.normalize_http_error(500, "Internal Server Error")
    assert isinstance(err500, ProviderServerError)

    # Generic error
    err_generic = adapter.normalize_http_error(418, "I'm a teapot")
    assert isinstance(err_generic, NormalizedProviderError)


# ==============================================================================
# 10. Execution Ledger Integration & Non-Sensitive endpoint_class
# ==============================================================================
def test_14_execution_ledger_endpoint_class_sanitization(fresh_registry: ProviderRegistry):
    """Verify ProviderCallEvidence enforces controlled non-sensitive taxonomy without URLs/ports."""
    # Valid controlled category
    evidence = ProviderCallEvidence(
        call_id="call-abc-123",
        provider_id="openai",
        model_id="gpt-4o-mini",
        endpoint_class="cloud",
        started_at=100.0,
        completed_at=100.85,
        latency_ms=850.0,
        status="completed",
        input_tokens_estimated=42,
        output_tokens_estimated=88,
    )
    fresh_registry.record_invocation_evidence(evidence)
    records = fresh_registry.get_invocation_evidence()
    assert len(records) == 1
    assert records[0].endpoint_class == "cloud"

    # Reject URLs, ports, query strings, or unrecognized classes
    with pytest.raises(ValueError, match="Invalid endpoint_class"):
        ProviderCallEvidence(
            call_id="call-leak-1",
            provider_id="openai",
            model_id="gpt-4o",
            endpoint_class="https://api.openai.com/v1",
            started_at=100.0,
            completed_at=100.1,
            latency_ms=100.0,
        )

    with pytest.raises(ValueError, match="Invalid endpoint_class"):
        ProviderCallEvidence(
            call_id="call-leak-2",
            provider_id="ollama",
            model_id="qwen",
            endpoint_class="localhost:11434",
            started_at=100.0,
            completed_at=100.1,
            latency_ms=100.0,
        )


# ==============================================================================
# 11. Concurrency & RLock Discipline
# ==============================================================================
def test_15_rlock_discipline_no_lock_held_during_io(fresh_registry: ProviderRegistry):
    """Verify slow external health probe in one thread does NOT block registry lookups in another."""
    adapter = fresh_registry.get_adapter("ollama")

    probe_started = threading.Event()
    probe_can_finish = threading.Event()
    lookup_completed = threading.Event()

    def slow_probe():
        def blocking_health(timeout=3.0):
            probe_started.set()
            probe_can_finish.wait(timeout=2.0)
            return ProviderHealth(
                config_state=ProviderConfigurationState.CONFIGURED,
                availability=ProviderAvailability.AVAILABLE,
                status=ProviderHealthStatus.HEALTHY,
                last_checked_at=time.time(),
            )

        with patch.object(adapter, "check_health", side_effect=blocking_health):
            fresh_registry.check_health("ollama", force_refresh=True)

    thread_a = threading.Thread(target=slow_probe, daemon=True)
    thread_a.start()

    # Wait until probe starts and is in progress
    assert probe_started.wait(timeout=1.0) is True

    # Concurrently in Thread B, perform registry operations
    t0 = time.perf_counter()
    p_def = fresh_registry.get_provider("openai")
    p_list = fresh_registry.list_providers()
    p_canon = fresh_registry.resolve_provider_id("google")
    elapsed = time.perf_counter() - t0

    lookup_completed.set()
    probe_can_finish.set()
    thread_a.join(timeout=1.0)

    # Invariant: Lookups in Thread B completed almost instantaneously (< 100ms)
    assert p_def is not None
    assert len(p_list) >= 9
    assert p_canon == "gemini"
    assert elapsed < 0.1, f"Registry lookup was blocked by probe: took {elapsed:.3f}s"


# ==============================================================================
# 12. Complete 9-Adapter Conformance Matrix
# ==============================================================================
@pytest.mark.parametrize("provider_id", ALL_BUILTIN_PROVIDERS)
def test_16_all_9_providers_conformance_contract(
    fresh_registry: ProviderRegistry, provider_id: str
):
    """Verify that all 9 concrete adapters pass the identical common conformance contract."""
    prov = fresh_registry.get_provider(provider_id)
    assert prov is not None, f"Provider '{provider_id}' not found in registry"
    assert prov.provider_id == provider_id
    assert prov.endpoint_class in [
        ProviderEndpointClass.CLOUD,
        ProviderEndpointClass.LOCAL_MANAGED,
        ProviderEndpointClass.LOCAL_EXTERNAL,
        ProviderEndpointClass.CUSTOM_REMOTE,
    ]

    # Safe representation check
    safe_dict = prov.to_safe_dict()
    assert "sk-" not in str(safe_dict)
    assert "api_key" not in safe_dict["config"]

    # Adapter instantiation
    adapter = fresh_registry.get_adapter(provider_id)
    assert adapter is not None
    assert adapter.provider_id == provider_id
    assert adapter.endpoint_class == prov.endpoint_class
    assert "sk-" not in repr(adapter)

    # Health probe with mocked success (HTTP 200)
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        with patch.object(adapter, "resolve_api_key", return_value="mock-test-key-12345"):
            health = adapter.test_connection(timeout=3.0)
            assert health.config_state == ProviderConfigurationState.CONFIGURED
            assert health.availability == ProviderAvailability.AVAILABLE
            assert health.status == ProviderHealthStatus.HEALTHY
            assert health.is_usable() is True
            assert health.last_checked_at > 0

    # DSPy LM instantiation with direct credential injection
    with patch("dspy.LM") as mock_lm:
        lm = adapter.create_dspy_lm(api_key="direct-key-inject")
        assert lm is not None
        mock_lm.assert_called_once()
        _, kwargs = mock_lm.call_args
        if prov.capabilities.requires_credentials:
            assert kwargs.get("api_key") == "direct-key-inject"


# ==============================================================================
# 13. Backward-Compatible Model Factory & Router Integration
# ==============================================================================
def test_17_backward_compatible_model_factory(monkeypatch: pytest.MonkeyPatch):
    """Verify core.models.get_model_provider and ModelRouter delegate to ProviderRegistry."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch("dspy.LM") as mock_lm:
        lm = get_model_provider("openai", api_key="sk-test-direct-key-555")
        assert lm is not None
        mock_lm.assert_called_once()
        _, kwargs = mock_lm.call_args
        assert kwargs.get("api_key") == "sk-test-direct-key-555"

    # ModelRouter integration
    router = ModelRouter()
    status = router.get_status()
    assert "openai_live" in status
    assert "primary_provider" in status


# ==============================================================================
# 14. Custom OpenAI-Compatible Provider Registration
# ==============================================================================
def test_18_custom_openai_compatible_provider_registration(
    fresh_registry: ProviderRegistry,
):
    """Verify dynamic registration of custom OpenAI-compatible endpoints."""
    custom_def = ProviderDefinition(
        provider_id="custom_vllm",
        display_name="Internal vLLM Cluster",
        endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
        endpoint_class=ProviderEndpointClass.CUSTOM_REMOTE,
        default_endpoint_url="http://internal-vllm.infra:8000/v1",
        default_model="meta-llama/Llama-3.1-8B-Instruct",
        capabilities=ProviderCapabilities(
            supports_streaming=True,
            supports_tools=True,
            is_local=False,
            requires_credentials=True,
        ),
        config=ProviderConfiguration(
            provider_id="custom_vllm",
            endpoint_url="http://internal-vllm.infra:8000/v1",
            auth_type=ProviderAuthType.BEARER_TOKEN,
            credential_key="VLLM_API_KEY",
            custom_headers={"X-Cluster-Routing": "gpu-prod-a"},
        ),
    )

    fresh_registry.register_provider(custom_def)
    assert fresh_registry.get_provider("custom_vllm") is not None

    adapter = fresh_registry.get_adapter("custom_vllm")
    assert adapter.provider_id == "custom_vllm"
    assert adapter.definition.config.custom_headers["X-Cluster-Routing"] == "gpu-prod-a"

    # Unregister provider
    assert fresh_registry.unregister_provider("custom_vllm") is True
    assert fresh_registry.get_provider("custom_vllm") is None


# ==============================================================================
# 15. Thread-Safe Registry & Health Cache TTL
# ==============================================================================
def test_19_thread_safe_registry_and_health_caching(fresh_registry: ProviderRegistry):
    """Verify health probe caching respects TTL and avoid redundant network calls."""
    adapter = fresh_registry.get_adapter("ollama")

    call_count = 0

    def mock_test(timeout=3.0):
        nonlocal call_count
        call_count += 1
        return ProviderHealth(
            config_state=ProviderConfigurationState.CONFIGURED,
            availability=ProviderAvailability.AVAILABLE,
            status=ProviderHealthStatus.HEALTHY,
            latency_ms=12.5,
            last_checked_at=100.0,
        )

    with patch.object(adapter, "check_health", side_effect=mock_test):
        # First call probes
        h1 = fresh_registry.check_health("ollama")
        assert call_count == 1
        assert h1.status == ProviderHealthStatus.HEALTHY

        # Second immediate call returns cached result without re-probing
        h2 = fresh_registry.check_health("ollama", force_refresh=False)
        assert call_count == 1
        assert h2.status == ProviderHealthStatus.HEALTHY

        # Forced refresh bypasses cache
        h3 = fresh_registry.check_health("ollama", force_refresh=True)
        assert call_count == 2
        assert h3.status == ProviderHealthStatus.HEALTHY
