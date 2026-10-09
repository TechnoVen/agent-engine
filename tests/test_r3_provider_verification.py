"""tests/test_r3_provider_verification.py

Comprehensive Provider Connection Verification Test Suite.
Part of Milestone R3 Task R3.11 (Provider Connection Verification).

Verifies all 18 requirements from Directive 24:
1. Valid config + successful real completion -> VERIFIED_CONNECTED
2. /models succeeds but completion fails -> NOT CONNECTED (False positive fixture)
3. health succeeds but completion fails -> NOT CONNECTED (False positive fixture)
4. Wrong API key / missing key -> AUTHENTICATION_FAILED
5. Network unreachable -> NETWORK_ERROR
6. Timeout -> TIMEOUT
7. Nonexistent model -> MODEL_NOT_FOUND
8. Rate limit classified distinctly (RATE_LIMITED)
9. Quota error classified distinctly (QUOTA_EXHAUSTED)
10. Verification pins requested provider/model (zero fallback substitution)
11. Synthetic canary contains no user content
12. Verification secrets never appear in ledger/log/result
13. Verification execution passes PolicyEngine (denied causes zero provider call)
14. Verification records last_verified_at; stale verification not shown as fresh connected
15. Verification execution excluded from R3.10 economics cohorts
16. Managed llama.cpp real completion verifies locally
17. API requires IPC auth
18. Desktop status maps typed verification result correctly
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from core.economics import (
    AttemptEconomicsRecord,
    EconomicsCohortKey,
    EconomicsService,
    LogicalTaskEconomicsRecord,
    Money,
    TaskOutcome,
)
from core.model_registry.models import ModelIdentity
from core.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderInvocationResult,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
)
from core.providers.models import (
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderDefinition,
    ProviderEndpointClass,
    ProviderEndpointStyle,
    ProviderHealth,
    ProviderHealthStatus,
)
from core.providers.registry import ProviderRegistry, reset_provider_registry
from core.providers.verification.models import (
    ConnectionVerificationStatus,
    ProviderConnectionVerification,
)
from core.providers.verification.service import (
    ProviderVerificationService,
    reset_provider_verification_service,
)
from core.safety.policy import PolicyDecision, PolicyEngine
from services.python.server.app import create_app


@pytest.fixture(autouse=True)
def cleanup_singletons():
    reset_provider_registry()
    reset_provider_verification_service()
    yield
    reset_provider_registry()
    reset_provider_verification_service()


def _create_mock_registry():
    reg = ProviderRegistry()
    # Mock openai adapter
    adapter = MagicMock()
    adapter.resolve_api_key.return_value = "sk-test-valid-key-12345"
    adapter.invoke.return_value = ProviderInvocationResult(
        content="AE_PROVIDER_OK",
        model="gpt-4o",
        provider_id="openai",
        latency_ms=120.0,
    )
    reg.register_provider(
        ProviderDefinition(
            provider_id="openai",
            display_name="OpenAI",
            endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
            endpoint_class=ProviderEndpointClass.CLOUD,
            default_model="gpt-4o",
            config=ProviderConfiguration(
                provider_id="openai",
                credential_key="OPENAI_API_KEY",
            ),
        ),
        adapter_factory=lambda defn, sec: adapter,
    )

    # Mock anthropic adapter
    anthropic_adapter = MagicMock()
    anthropic_adapter.resolve_api_key.return_value = "sk-ant-valid-key-67890"
    anthropic_adapter.invoke.return_value = ProviderInvocationResult(
        content="AE_PROVIDER_OK",
        model="claude-3-5-sonnet",
        provider_id="anthropic",
        latency_ms=150.0,
    )
    reg.register_provider(
        ProviderDefinition(
            provider_id="anthropic",
            display_name="Anthropic",
            endpoint_style=ProviderEndpointStyle.ANTHROPIC,
            endpoint_class=ProviderEndpointClass.CLOUD,
            default_model="claude-3-5-sonnet",
            config=ProviderConfiguration(
                provider_id="anthropic",
                credential_key="ANTHROPIC_API_KEY",
            ),
        ),
        adapter_factory=lambda defn, sec: anthropic_adapter,
    )

    return reg, adapter, anthropic_adapter


# 1. Valid config + successful real completion -> VERIFIED_CONNECTED
def test_01_valid_completion_yields_verified_connected():
    reg, adapter, _ = _create_mock_registry()
    svc = ProviderVerificationService(registry=reg)

    ver = svc.verify_provider("openai")
    assert ver.status == ConnectionVerificationStatus.VERIFIED_CONNECTED
    assert ver.is_fresh() is True
    assert ver.display_state() == "Connected"
    assert ver.provider_id == "openai"
    assert ver.model_identity is not None
    assert ver.model_identity.model_id == "gpt-4o"
    assert ver.latency_ms > 0
    assert adapter.invoke.call_count == 1


# 2. Canonical False-Positive Fixture: /models succeeds (200 OK) but completion fails -> NOT CONNECTED
def test_02_false_positive_models_succeeds_but_completion_fails():
    reg, adapter, _ = _create_mock_registry()
    # Adapter health /models probe returns 200 OK
    adapter.test_connection.return_value = ProviderHealth(
        status=ProviderHealthStatus.HEALTHY,
        latency_ms=45.0,
    )
    # But completion fails with 500 internal error!
    adapter.invoke.side_effect = ProviderServerError(
        "500 Internal Server Error: Model failed to load", provider_id="openai"
    )

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai")

    assert ver.status == ConnectionVerificationStatus.PROVIDER_ERROR
    assert ver.status != ConnectionVerificationStatus.VERIFIED_CONNECTED
    assert ver.display_state() == "Verification failed"
    assert "server error" in ver.sanitized_error.lower()


# 3. Canonical False-Positive Fixture: health succeeds (200 OK) but completion fails -> NOT CONNECTED
def test_03_false_positive_health_succeeds_but_completion_fails():
    reg, adapter, _ = _create_mock_registry()
    adapter.check_health.return_value = ProviderHealth(
        status=ProviderHealthStatus.HEALTHY,
        latency_ms=10.0,
    )
    # Completion fails with out of memory / runtime crash
    adapter.invoke.side_effect = Exception("CUDA out of memory during inference execution")

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai")

    assert ver.status == ConnectionVerificationStatus.UNKNOWN_FAILURE
    assert ver.is_fresh() is False
    assert ver.display_state() == "Verification failed"


# 4. Wrong API key / missing key -> AUTHENTICATION_FAILED
def test_04_wrong_api_key_or_missing_credentials():
    reg, adapter, _ = _create_mock_registry()

    # Case A: Missing credentials
    adapter.resolve_api_key.return_value = None
    svc = ProviderVerificationService(registry=reg)
    ver_missing = svc.verify_provider("openai")
    assert ver_missing.status == ConnectionVerificationStatus.NOT_CONFIGURED
    assert ver_missing.failure_class == "AUTHENTICATION_FAILED"
    assert adapter.invoke.call_count == 0  # Zero provider calls if credentials missing

    # Case B: Upstream 401 Authentication Error
    adapter.resolve_api_key.return_value = "sk-invalid-key"
    adapter.invoke.side_effect = ProviderAuthenticationError(
        "HTTP 401: Unauthorized API key", provider_id="openai"
    )
    ver_auth = svc.verify_provider("openai")
    assert ver_auth.status == ConnectionVerificationStatus.AUTHENTICATION_FAILED
    assert ver_auth.failure_class == "AUTHENTICATION_FAILED"
    assert "authentication failed" in ver_auth.sanitized_error.lower()


# 5. Network unreachable -> NETWORK_ERROR
def test_05_network_unreachable_classified_correctly():
    reg, adapter, _ = _create_mock_registry()
    adapter.invoke.side_effect = ProviderConnectionError(
        "Failed to establish a new connection: [Errno 111] Connection refused", provider_id="openai"
    )

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai")
    assert ver.status == ConnectionVerificationStatus.NETWORK_ERROR
    assert ver.failure_class == "NETWORK_ERROR"
    assert "network" in ver.sanitized_error.lower()


# 6. Timeout -> TIMEOUT
def test_06_timeout_classified_correctly():
    reg, adapter, _ = _create_mock_registry()
    adapter.invoke.side_effect = ProviderTimeoutError(
        "Request timed out after 5.0 seconds", provider_id="openai"
    )

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai")
    assert ver.status == ConnectionVerificationStatus.TIMEOUT
    assert ver.failure_class == "TIMEOUT"
    assert "timed out" in ver.sanitized_error.lower()


# 7. Nonexistent model -> MODEL_NOT_FOUND
def test_07_model_not_found_classified_correctly():
    reg, adapter, _ = _create_mock_registry()
    adapter.invoke.side_effect = ProviderNotFoundError(
        "The model 'gpt-nonexistent' does not exist", provider_id="openai"
    )

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai", model_id="gpt-nonexistent")
    assert ver.status == ConnectionVerificationStatus.MODEL_NOT_FOUND
    assert ver.failure_class == "MODEL_NOT_FOUND"
    assert "gpt-nonexistent" in ver.sanitized_error


# 8. Rate limit classified distinctly (RATE_LIMITED)
def test_08_rate_limit_classified_distinctly():
    reg, adapter, _ = _create_mock_registry()
    adapter.invoke.side_effect = ProviderRateLimitError(
        "Rate limit reached for requests per minute (RPM)", provider_id="openai"
    )

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai")
    assert ver.status == ConnectionVerificationStatus.RATE_LIMITED
    assert ver.failure_class == "RATE_LIMITED"
    assert "rate limit" in ver.sanitized_error.lower()


# 9. Quota error classified distinctly (QUOTA_EXHAUSTED)
def test_09_quota_exhausted_classified_distinctly():
    reg, adapter, _ = _create_mock_registry()
    adapter.invoke.side_effect = ProviderRateLimitError(
        "You exceeded your current quota, please check your plan and billing details.",
        provider_id="openai",
    )

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai")
    assert ver.status == ConnectionVerificationStatus.QUOTA_EXHAUSTED
    assert ver.failure_class == "QUOTA_EXHAUSTED"
    assert "quota" in ver.sanitized_error.lower()


# 10. Verification pins requested provider/model (zero fallback substitution)
def test_10_verification_pins_requested_provider_no_fallback():
    reg, openai_adapter, anthropic_adapter = _create_mock_registry()
    # Make anthropic fail
    anthropic_adapter.invoke.side_effect = ProviderServerError(
        "Anthropic server down", provider_id="anthropic"
    )

    svc = ProviderVerificationService(registry=reg)
    # Verification of anthropic MUST fail and NEVER fallback to OpenAI
    ver = svc.verify_provider("anthropic")

    assert ver.provider_id == "anthropic"
    assert ver.status == ConnectionVerificationStatus.PROVIDER_ERROR
    assert ver.display_state() == "Verification failed"
    # OpenAI was NOT called to substitute
    assert openai_adapter.invoke.call_count == 0


# 11. Synthetic canary contains no user content
def test_11_synthetic_canary_contains_zero_user_content():
    reg, adapter, _ = _create_mock_registry()
    svc = ProviderVerificationService(registry=reg)

    svc.verify_provider("openai")
    args, kwargs = adapter.invoke.call_args
    # The canary prompt MUST be exactly non-sensitive constant
    assert kwargs.get("prompt") == "Return exactly: AE_PROVIDER_OK"
    assert kwargs.get("temperature") == 0.0
    assert kwargs.get("max_tokens") == 10


# 12. Verification secrets never appear in ledger/log/result
def test_12_secrets_redaction_in_sanitized_errors():
    reg, adapter, _ = _create_mock_registry()
    # Raw exception contains secret token
    secret = "sk-live-secret-super-confidential-token-12345"
    adapter.invoke.side_effect = Exception(f"Failed call with key={secret} and Bearer {secret}")

    svc = ProviderVerificationService(registry=reg)
    ver = svc.verify_provider("openai")

    assert secret not in ver.sanitized_error
    assert "[REDACTED_CREDENTIAL]" in ver.sanitized_error


# 13. Verification execution passes PolicyEngine (denied causes zero provider call)
def test_13_policy_engine_denial_causes_zero_provider_calls():
    reg, adapter, _ = _create_mock_registry()
    mock_policy = MagicMock(spec=PolicyEngine)
    mock_policy.evaluate.return_value = PolicyDecision(
        decision="block",
        risk_score=1.0,
        risk_level="critical",
        reason="Network access blocked by security policy",
    )

    svc = ProviderVerificationService(registry=reg, policy_engine=mock_policy)
    ver = svc.verify_provider("openai")

    assert ver.status == ConnectionVerificationStatus.PROVIDER_ERROR
    assert ver.failure_class == "POLICY_BLOCKED"
    assert "blocked by active safety policy" in ver.sanitized_error
    # Invariant: ZERO provider calls when policy blocks!
    assert adapter.invoke.call_count == 0


# 14. Verification records last_verified_at; stale verification not shown as fresh connected
def test_14_freshness_boundaries_and_stale_semantics():
    ver = ProviderConnectionVerification(
        provider_id="openai",
        status=ConnectionVerificationStatus.VERIFIED_CONNECTED,
        last_verified_at=time.time() - 90000.0,  # > 24 hours ago
        latency_ms=100.0,
    )
    assert ver.is_fresh(max_age_seconds=86400.0) is False
    assert ver.display_state(max_age_seconds=86400.0) == "Verification stale"

    recent_ver = ProviderConnectionVerification(
        provider_id="openai",
        status=ConnectionVerificationStatus.VERIFIED_CONNECTED,
        last_verified_at=time.time() - 300.0,  # 5 minutes ago
        latency_ms=100.0,
    )
    assert recent_ver.is_fresh(max_age_seconds=86400.0) is True
    assert recent_ver.display_state() == "Connected"


# 15. Verification execution excluded from R3.10 economics cohorts
def test_15_verification_execution_excluded_from_economics():
    econ_svc = EconomicsService()
    model = ModelIdentity(provider_id="openai", model_id="gpt-4o")

    # A: AttemptEconomicsRecord with execution_purpose="PROVIDER_VERIFICATION" cannot enter production cohort
    ver_attempt = AttemptEconomicsRecord(
        execution_id="exec_ver_01",
        logical_task_id="task_ver_01",
        model_identity=model,
        provider_id="openai",
        cost=Money.from_usd(0.0001),
        outcome=TaskOutcome.SUCCESS,
        execution_purpose="PROVIDER_VERIFICATION",
    )
    with pytest.raises(
        ValueError, match="Verification attempt record cannot enter production cohort"
    ):
        econ_svc.record_attempt(ver_attempt)

    # B: LogicalTaskEconomicsRecord with execution_purpose="PROVIDER_VERIFICATION" is excluded from cohort calculations
    ver_task = LogicalTaskEconomicsRecord(
        logical_task_id="task_ver_02",
        task_family="general",
        initial_model_identity=model,
        initial_provider_id="openai",
        total_cost=Money.from_usd(0.0001),
        final_outcome=TaskOutcome.SUCCESS,
        execution_purpose="PROVIDER_VERIFICATION",
    )
    econ_svc.create_or_update_logical_task(ver_task)

    cohort_key = EconomicsCohortKey(
        initial_model_identity=model,
        task_family="general",
        evaluator_version="v1",
        routing_policy_version="v1",
        fallback_policy_version="v1",
        effective_privacy_class="ANY_CONFIGURED",
    )
    summary = econ_svc.compute_cohort_summary(cohort_key)
    # Must be 0 because verification task was excluded!
    assert summary.logical_tasks_count == 0
    assert summary.verified_successes == 0


# 16. Managed llama.cpp real completion verifies locally
def test_16_managed_llamacpp_local_verification():
    reg = ProviderRegistry()
    mock_llamacpp_adapter = MagicMock()
    mock_llamacpp_adapter.invoke.return_value = ProviderInvocationResult(
        content="AE_PROVIDER_OK",
        model="qwen-2.5-coder-7b",
        provider_id="llamacpp",
        latency_ms=35.0,
    )
    reg.register_provider(
        ProviderDefinition(
            provider_id="llamacpp",
            display_name="llama.cpp Managed Runtime",
            endpoint_style=ProviderEndpointStyle.LLAMACPP,
            endpoint_class=ProviderEndpointClass.LOCAL_MANAGED,
            default_model="qwen-2.5-coder-7b",
            config=ProviderConfiguration(
                provider_id="llamacpp",
                endpoint_url="http://127.0.0.1:8080",
            ),
            capabilities=ProviderCapabilities(
                is_local=True,
                requires_credentials=False,
            ),
        ),
        adapter_factory=lambda defn, sec: mock_llamacpp_adapter,
    )

    # Supervisor mock: READY
    with patch("core.inference.supervisor.get_local_inference_supervisor") as mock_sup_getter:
        mock_sup = MagicMock()
        mock_inst = MagicMock()
        mock_inst.state.value = "ready"
        mock_sup.get_active_instance.return_value = mock_inst
        mock_sup_getter.return_value = mock_sup

        svc = ProviderVerificationService(registry=reg)
        ver = svc.verify_provider("llamacpp")

        assert ver.status == ConnectionVerificationStatus.VERIFIED_CONNECTED
        assert ver.is_fresh() is True
        assert ver.latency_ms > 0
        assert mock_llamacpp_adapter.invoke.call_count == 1

    # Supervisor mock: NOT READY -> Fail
    with patch("core.inference.supervisor.get_local_inference_supervisor") as mock_sup_getter:
        mock_sup = MagicMock()
        mock_inst = MagicMock()
        mock_inst.state.value = "failed"
        mock_sup.get_active_instance.return_value = mock_inst
        mock_sup_getter.return_value = mock_sup

        ver_failed = svc.verify_provider("llamacpp")
        assert ver_failed.status == ConnectionVerificationStatus.PROVIDER_ERROR
        assert ver_failed.failure_class == "SUPERVISOR_NOT_READY"


# 17. API requires IPC auth
def test_17_api_endpoints_require_ipc_auth():
    from services.python.server.dependencies import (
        get_token_manager,
        reset_token_manager,
    )

    tm = get_token_manager()
    tm.set_enforced(True)
    try:
        app = create_app()
        client = TestClient(app)

        # Unauthenticated requests MUST fail with 401 Unauthorized
        res_verify_no_auth = client.post("/v1/providers/openai/verify", json={})
        assert res_verify_no_auth.status_code == 401

        res_get_no_auth = client.get("/v1/providers/openai/verification")
        assert res_get_no_auth.status_code == 401

        res_list_no_auth = client.get("/v1/providers")
        assert res_list_no_auth.status_code == 401

        # Authenticated requests with IPC token succeed
        token = tm.get_token()
        headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "services.python.server.routers.models.get_provider_verification_service"
        ) as mock_svc_getter:
            mock_svc = MagicMock()
            mock_svc.verify_provider.return_value = ProviderConnectionVerification(
                provider_id="openai",
                status=ConnectionVerificationStatus.VERIFIED_CONNECTED,
                latency_ms=50.0,
            )
            mock_svc.get_verification.return_value = ProviderConnectionVerification(
                provider_id="openai",
                status=ConnectionVerificationStatus.VERIFIED_CONNECTED,
                latency_ms=50.0,
            )
            mock_svc_getter.return_value = mock_svc

            res_verify = client.post("/v1/providers/openai/verify", json={}, headers=headers)
            assert res_verify.status_code == 200
            data = res_verify.json()
            assert data["provider_id"] == "openai"
            assert data["status"] == "VERIFIED_CONNECTED"

            res_get = client.get("/v1/providers/openai/verification", headers=headers)
            assert res_get.status_code == 200
            assert res_get.json()["status"] == "VERIFIED_CONNECTED"
    finally:
        tm.set_enforced(None)
        reset_token_manager()


# 18. Desktop status maps typed verification result correctly
def test_18_desktop_status_mapping():
    ver_connected = ProviderConnectionVerification(
        provider_id="openai",
        status=ConnectionVerificationStatus.VERIFIED_CONNECTED,
        last_verified_at=time.time(),
        latency_ms=88.0,
    )
    safe = ver_connected.to_safe_dict()
    assert safe["display_state"] == "Connected"
    assert safe["is_fresh"] is True

    ver_not_config = ProviderConnectionVerification(
        provider_id="openai",
        status=ConnectionVerificationStatus.NOT_CONFIGURED,
        last_verified_at=0.0,
    )
    assert ver_not_config.to_safe_dict()["display_state"] == "Not configured"

    ver_failed = ProviderConnectionVerification(
        provider_id="openai",
        status=ConnectionVerificationStatus.AUTHENTICATION_FAILED,
        last_verified_at=time.time(),
    )
    assert ver_failed.to_safe_dict()["display_state"] == "Verification failed"
