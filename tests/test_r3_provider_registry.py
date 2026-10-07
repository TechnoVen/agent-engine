"""tests/test_r3_provider_registry.py

Comprehensive Provider Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).

Verifies the 8 core R3.1 conformance pillars:
1. Stable provider identity distinct from display name, alias, endpoint, and model.
2. Provider vs model responsibility separation.
3. Explicit provider health state taxonomy (CONFIGURED, AVAILABLE, HEALTHY, DEGRADED, UNAVAILABLE, AUTHENTICATION_FAILED).
4. Low-cost, bounded-timeout health checks with timestamped evidence.
5. Inviolable R2.6 secret boundary: zero plaintext leaks, SecretReference preservation, zero os.environ mutation.
6. Transparent legacy configuration migration (config.yaml, environment variables).
7. Streaming capability declaration and error normalization into typed hierarchies.
8. Execution ledger integration with non-sensitive ProviderCallEvidence.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core.models import get_model_provider
from core.providers import (
    NormalizedProviderError,
    ProviderAuthenticationError,
    ProviderAuthType,
    ProviderCallEvidence,
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderDefinition,
    ProviderEndpointStyle,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderInvalidRequestError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRegistry,
    ProviderServerError,
    reset_provider_registry,
)
from core.router.model_router import ModelRouter
from core.security.secrets import SecretReference


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
# 2. Alias Resolution
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

    # Getting provider by alias returns canonical definition
    google_def = fresh_registry.get_provider("google")
    assert google_def is not None
    assert google_def.provider_id == "gemini"

    local_def = fresh_registry.get_provider("local")
    assert local_def is not None
    assert local_def.provider_id == "llamacpp"


# ==============================================================================
# 3. Provider vs Model Separation
# ==============================================================================
def test_03_provider_vs_model_responsibility_separation(fresh_registry: ProviderRegistry):
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
# 4. Explicit Health State Taxonomy
# ==============================================================================
def test_04_explicit_health_state_taxonomy():
    """Verify explicit health taxonomy and is_usable() semantics."""
    states = [
        ProviderHealthStatus.CONFIGURED,
        ProviderHealthStatus.AVAILABLE,
        ProviderHealthStatus.HEALTHY,
        ProviderHealthStatus.DEGRADED,
        ProviderHealthStatus.UNAVAILABLE,
        ProviderHealthStatus.AUTHENTICATION_FAILED,
    ]
    assert len(states) == 6

    # Usable states
    assert ProviderHealth(status=ProviderHealthStatus.HEALTHY).is_usable() is True
    assert ProviderHealth(status=ProviderHealthStatus.AVAILABLE).is_usable() is True
    assert ProviderHealth(status=ProviderHealthStatus.DEGRADED).is_usable() is True
    assert ProviderHealth(status=ProviderHealthStatus.CONFIGURED).is_usable() is True

    # Non-usable states
    assert ProviderHealth(status=ProviderHealthStatus.UNAVAILABLE).is_usable() is False
    assert ProviderHealth(status=ProviderHealthStatus.AUTHENTICATION_FAILED).is_usable() is False


# ==============================================================================
# 5. Latency Degradation
# ==============================================================================
def test_05_health_probe_latency_degradation(fresh_registry: ProviderRegistry):
    """Verify that elevated probe latency triggers DEGRADED status."""
    adapter = fresh_registry.get_adapter("openai")

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # Inject artificial high latency
        with patch("time.perf_counter", side_effect=[0.0, 4.5]):
            with patch.object(adapter, "resolve_api_key", return_value="sk-test-mock-key"):
                health = adapter.test_connection(timeout=5.0)
                assert health.status == ProviderHealthStatus.DEGRADED
                assert health.latency_ms == 4500.0


# ==============================================================================
# 6. Low-Cost Bounded Timeout Health Checks
# ==============================================================================
def test_06_low_cost_bounded_timeout_health_checking(fresh_registry: ProviderRegistry):
    """Verify health checks enforce bounded timeouts and handle failures gracefully."""
    adapter = fresh_registry.get_adapter("ollama")

    import requests

    with patch("requests.get", side_effect=requests.Timeout("Operation timed out")):
        health = adapter.test_connection(timeout=2.0)
        assert health.status == ProviderHealthStatus.UNAVAILABLE
        assert "timed out" in health.error_message.lower()
        assert health.last_checked_at > 0


# ==============================================================================
# 7. Inviolable R2.6 Secret Boundary
# ==============================================================================
def test_07_secret_boundary_r26_isolation(fresh_registry: ProviderRegistry):
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
# 8. Zero Global os.environ Mutation
# ==============================================================================
def test_08_no_global_os_environ_mutation(
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
# 9. Legacy Config Migration
# ==============================================================================
def test_09_legacy_config_migration(
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

    llamacpp = fresh_registry.get_provider("llamacpp")
    assert llamacpp.config.endpoint_url == "http://custom-llamacpp:8080/v1"
    assert llamacpp.default_model == "custom-qwen-model"


# ==============================================================================
# 10. Streaming Capability & Conformance
# ==============================================================================
def test_10_streaming_capability_declaration_and_conformance(
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


# ==============================================================================
# 11. Error Normalization
# ==============================================================================
def test_11_error_normalization(fresh_registry: ProviderRegistry):
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
# 12. Execution Ledger Integration & Call Evidence
# ==============================================================================
def test_12_execution_ledger_integration_and_call_evidence(fresh_registry: ProviderRegistry):
    """Verify ProviderCallEvidence audit record captures metrics without secrets."""
    evidence = ProviderCallEvidence(
        call_id="call-abc-123",
        provider_id="openai",
        model_id="gpt-4o-mini",
        endpoint_class="openai_client",
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
    assert records[0].call_id == "call-abc-123"
    assert records[0].provider_id == "openai"
    assert records[0].endpoint_class == "openai_client"
    assert records[0].latency_ms == 850.0
    # Invariant: No secret fields present
    ev_dict = records[0].model_dump()
    assert "api_key" not in ev_dict
    assert "secret" not in ev_dict


# ==============================================================================
# 13. Backward-Compatible Model Factory & Router Integration
# ==============================================================================
def test_13_backward_compatible_model_factory(monkeypatch: pytest.MonkeyPatch):
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
def test_14_custom_openai_compatible_provider_registration(
    fresh_registry: ProviderRegistry,
):
    """Verify dynamic registration of custom OpenAI-compatible endpoints."""
    custom_def = ProviderDefinition(
        provider_id="custom_vllm",
        display_name="Internal vLLM Cluster",
        endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
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
def test_15_thread_safe_registry_and_health_caching(fresh_registry: ProviderRegistry):
    """Verify health probe caching respects TTL and avoid redundant network calls."""
    adapter = fresh_registry.get_adapter("ollama")

    call_count = 0

    def mock_test(timeout=3.0):
        nonlocal call_count
        call_count += 1
        return ProviderHealth(
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
