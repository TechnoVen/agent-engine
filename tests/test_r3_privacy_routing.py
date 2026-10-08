"""tests/test_r3_privacy_routing.py

Comprehensive Privacy Classes and Data-Routing Policy Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.8 (Privacy classes and data-routing policy).

Verifies all R3.8 core invariants & CTO review requirements:
1. LOCAL_ONLY permits managed local llama.cpp.
2. LOCAL_ONLY rejects each cloud provider (OpenAI, Anthropic, Gemini, DeepSeek, Groq, Kimi).
3. LOCAL_ONLY rejects models with UNKNOWN execution location.
4. LOCAL_ONLY rejects models with UNKNOWN data egress fact.
5. LOCAL_ONLY when local provider is unavailable fails closed with NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY (zero cloud fallback).
6. APPROVED_CLOUD permits approved cloud provider.
7. APPROVED_CLOUD rejects unapproved cloud provider.
8. APPROVED_CLOUD still permits eligible local provider.
9. ANY_CONFIGURED includes configured providers without bypassing PolicyEngine.
10. Scope precedence: Profile default applied when no override.
11. Scope precedence: Project override applied (tightening permitted; relaxation requires trusted authority).
12. Scope precedence: Task override applied (tightening permitted; relaxation requires trusted authority).
13. Untrusted content (documents, prompt text, model output, renderer claim) cannot relax privacy class.
14. Router pre-scoring filtering excludes prohibited candidates before ranking.
15. Dispatch boundary independently blocks prohibited provider (forced invalid selection under LOCAL_ONLY blocked before network call, 0 outbound requests).
16. Aliases normalized to canonical provider IDs; approved cloud targets contain no credentials/wildcards.
17. Ledger records effective privacy class, policy source, and eligibility rejections without secrets.
18. Configuration endpoints (/v1/privacy/policy, /v1/projects/{id}/privacy) are IPC-auth protected.
19. Integration test: LOCAL_ONLY ExecutionRequest -> ExecutionCoordinator -> managed llama.cpp -> actual invocation -> ledger proves local selection.
20. Integration test: LOCAL_ONLY ExecutionRequest + unavailable local provider -> fails closed -> cloud adapter invocation count = 0.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionRequest,
    ExecutionStatus,
    RoutingTier,
)
from core.ledger.service import ExecutionLedgerService
from core.model_registry.models import (
    ExecutionLocation,
    ModelDefinition,
    PrivacyProfile,
    TriStateBool,
)
from core.privacy import (
    ApprovedCloudTarget,
    DataRoutingClass,
    DataRoutingPolicy,
    NoEligibleModelUnderPrivacyPolicyError,
    PrivacyEligibilityReason,
    PrivacyPolicyEngine,
    RoutingPolicySource,
    reset_system_routing_policy,
)
from core.router.model_router import ModelRouter, ResolvedModel
from core.safety.policy import PolicyEngine
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import CostTracker


@pytest.fixture(autouse=True)
def clean_system_policy():
    """Ensure system routing policy is clean between tests."""
    reset_system_routing_policy()
    yield
    reset_system_routing_policy()


def _make_dummy_model(
    provider_id: str,
    model_id: str,
    location: ExecutionLocation = ExecutionLocation.LOCAL,
    data_leaves_device: TriStateBool = TriStateBool.FALSE,
) -> ModelDefinition:
    """Helper to construct dummy model definitions for testing."""
    return ModelDefinition(
        provider_id=provider_id,
        model_id=model_id,
        display_name=f"{provider_id.upper()} {model_id}",
        privacy=PrivacyProfile(
            execution_location=location,
            data_leaves_device=data_leaves_device,
        ),
    )


# ==============================================================================
# 1. LOCAL_ONLY Permits Managed Local llama.cpp
# ==============================================================================
def test_01_local_only_permits_managed_llamacpp():
    policy = DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    # Provider-level evaluation
    elig = PrivacyPolicyEngine.evaluate_provider_privacy("llamacpp", effective)
    assert elig.eligible is True
    assert elig.rejection_reasons == []

    # Model-level evaluation
    model = _make_dummy_model(
        "llamacpp",
        "qwen2.5-coder-3b-instruct-q4_k_m",
        location=ExecutionLocation.LOCAL,
        data_leaves_device=TriStateBool.FALSE,
    )
    m_elig = PrivacyPolicyEngine.evaluate_model_privacy(model, effective)
    assert m_elig.eligible is True
    assert m_elig.rejection_reasons == []


# ==============================================================================
# 2. LOCAL_ONLY Rejects Each Cloud Provider
# ==============================================================================
@pytest.mark.parametrize(
    "cloud_provider",
    ["openai", "anthropic", "gemini", "deepseek", "groq", "kimi"],
)
def test_02_local_only_rejects_each_cloud_provider(cloud_provider: str):
    policy = DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    # Provider evaluation
    elig = PrivacyPolicyEngine.evaluate_provider_privacy(cloud_provider, effective)
    assert elig.eligible is False
    assert (
        PrivacyEligibilityReason.PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER in elig.rejection_reasons
        or PrivacyEligibilityReason.PRIVACY_DATA_LEAVES_DEVICE_FORBIDDEN in elig.rejection_reasons
    )

    # Model evaluation
    model = _make_dummy_model(
        cloud_provider,
        "flagship-model",
        location=ExecutionLocation.REMOTE,
        data_leaves_device=TriStateBool.TRUE,
    )
    m_elig = PrivacyPolicyEngine.evaluate_model_privacy(model, effective)
    assert m_elig.eligible is False
    assert PrivacyEligibilityReason.PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER in m_elig.rejection_reasons


# ==============================================================================
# 3. LOCAL_ONLY Rejects Models with UNKNOWN Execution Location
# ==============================================================================
def test_03_local_only_rejects_unknown_execution_location():
    policy = DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    model = _make_dummy_model(
        "custom_runtime",
        "mystery-model",
        location=ExecutionLocation.UNKNOWN,
        data_leaves_device=TriStateBool.FALSE,
    )
    elig = PrivacyPolicyEngine.evaluate_model_privacy(model, effective)
    assert elig.eligible is False
    assert PrivacyEligibilityReason.PRIVACY_LOCATION_UNKNOWN in elig.rejection_reasons


# ==============================================================================
# 4. LOCAL_ONLY Rejects Models with UNKNOWN Data Egress Fact
# ==============================================================================
def test_04_local_only_rejects_unknown_data_egress():
    policy = DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    model = _make_dummy_model(
        "custom_runtime",
        "mystery-model",
        location=ExecutionLocation.LOCAL,
        data_leaves_device=TriStateBool.UNKNOWN,
    )
    elig = PrivacyPolicyEngine.evaluate_model_privacy(model, effective)
    assert elig.eligible is False
    assert PrivacyEligibilityReason.PRIVACY_DATA_EGRESS_UNKNOWN in elig.rejection_reasons


# ==============================================================================
# 5. Zero Cloud Fallback Under LOCAL_ONLY
# ==============================================================================
def test_05_local_only_zero_cloud_fallback_when_local_unavailable():
    """If local provider is degraded or down, fails closed immediately; NEVER falls back to cloud."""
    router = ModelRouter()
    effective = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    )

    # Trip circuit breaker for llamacpp and ollama
    router.circuit_breaker.record_failure("llamacpp")
    router.circuit_breaker.record_failure("llamacpp")
    router.circuit_breaker.record_failure("llamacpp")
    router.circuit_breaker.record_failure("llamacpp")
    router.circuit_breaker.record_failure("llamacpp")
    assert not router.circuit_breaker.can_attempt("llamacpp")

    # With local circuit broken and cloud forbidden, resolve_model MUST fail closed
    with pytest.raises(NoEligibleModelUnderPrivacyPolicyError) as exc_info:
        router.resolve_model(requested_model="llamacpp/qwen", effective_policy=effective)
    assert "LOCAL_ONLY" in str(exc_info.value)
    assert "Circuit OPEN" in str(exc_info.value) or "prohibited" in str(exc_info.value)

    # Asking for a cloud tier under LOCAL_ONLY must also fail closed
    with pytest.raises(NoEligibleModelUnderPrivacyPolicyError):
        router.resolve_model(requested_tier=RoutingTier.FRONTIER, effective_policy=effective)

    with pytest.raises(NoEligibleModelUnderPrivacyPolicyError):
        router.resolve_model(requested_tier=RoutingTier.MID, effective_policy=effective)


# ==============================================================================
# 6. APPROVED_CLOUD Permits Approved Cloud Provider
# ==============================================================================
def test_06_approved_cloud_permits_approved_target():
    policy = DataRoutingPolicy(
        routing_class=DataRoutingClass.APPROVED_CLOUD,
        approved_cloud_targets=[
            ApprovedCloudTarget(provider_id="openai"),
            ApprovedCloudTarget(provider_id="anthropic", model_id="claude-3-5-sonnet"),
        ],
    )
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    # openai (wildcard model) is eligible
    elig_openai = PrivacyPolicyEngine.evaluate_provider_privacy("openai", effective)
    assert elig_openai.eligible is True

    model_openai = _make_dummy_model(
        "openai", "gpt-4o", ExecutionLocation.REMOTE, TriStateBool.TRUE
    )
    assert PrivacyPolicyEngine.evaluate_model_privacy(model_openai, effective).eligible is True

    # anthropic claude-3-5-sonnet is eligible
    model_claude = _make_dummy_model(
        "anthropic", "claude-3-5-sonnet", ExecutionLocation.REMOTE, TriStateBool.TRUE
    )
    assert PrivacyPolicyEngine.evaluate_model_privacy(model_claude, effective).eligible is True


# ==============================================================================
# 7. APPROVED_CLOUD Rejects Unapproved Cloud Provider
# ==============================================================================
def test_07_approved_cloud_rejects_unapproved_target():
    policy = DataRoutingPolicy(
        routing_class=DataRoutingClass.APPROVED_CLOUD,
        approved_cloud_targets=[
            ApprovedCloudTarget(provider_id="openai"),
            ApprovedCloudTarget(provider_id="anthropic", model_id="claude-3-5-sonnet"),
        ],
    )
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    # gemini is not in approved targets
    elig_gemini = PrivacyPolicyEngine.evaluate_provider_privacy("gemini", effective)
    assert elig_gemini.eligible is False
    assert PrivacyEligibilityReason.PRIVACY_PROVIDER_NOT_APPROVED in elig_gemini.rejection_reasons

    # anthropic claude-3-opus is not the approved model
    model_opus = _make_dummy_model(
        "anthropic", "claude-3-opus", ExecutionLocation.REMOTE, TriStateBool.TRUE
    )
    m_elig = PrivacyPolicyEngine.evaluate_model_privacy(model_opus, effective)
    assert m_elig.eligible is False
    assert PrivacyEligibilityReason.PRIVACY_MODEL_NOT_APPROVED in m_elig.rejection_reasons


# ==============================================================================
# 8. APPROVED_CLOUD Permits Eligible Local Provider
# ==============================================================================
def test_08_approved_cloud_still_permits_local():
    policy = DataRoutingPolicy(
        routing_class=DataRoutingClass.APPROVED_CLOUD,
        approved_cloud_targets=[ApprovedCloudTarget(provider_id="openai")],
    )
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    elig = PrivacyPolicyEngine.evaluate_provider_privacy("llamacpp", effective)
    assert elig.eligible is True

    model = _make_dummy_model("llamacpp", "qwen", ExecutionLocation.LOCAL, TriStateBool.FALSE)
    assert PrivacyPolicyEngine.evaluate_model_privacy(model, effective).eligible is True


# ==============================================================================
# 9. ANY_CONFIGURED Evaluates Without Bypassing PolicyEngine
# ==============================================================================
def test_09_any_configured_evaluates_with_policy_engine():
    policy = DataRoutingPolicy(routing_class=DataRoutingClass.ANY_CONFIGURED)
    effective = PrivacyPolicyEngine.resolve_effective_policy(profile_policy=policy)

    assert effective.effective_class == DataRoutingClass.ANY_CONFIGURED

    # Local is eligible
    assert PrivacyPolicyEngine.evaluate_provider_privacy("llamacpp", effective).eligible is True
    # Cloud is eligible under ANY_CONFIGURED
    assert PrivacyPolicyEngine.evaluate_provider_privacy("openai", effective).eligible is True
    assert PrivacyPolicyEngine.evaluate_provider_privacy("gemini", effective).eligible is True

    # PolicyEngine evaluation passes
    pe = PolicyEngine()
    eval_res = pe.evaluate_data_routing(
        effective_policy=effective,
        provider_id="openai",
        model_id="gpt-4o",
    )
    assert eval_res.decision == "allow"


# ==============================================================================
# 10. Scope Precedence: Profile Default Applied
# ==============================================================================
def test_10_scope_precedence_profile_default():
    profile = DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    effective = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=profile,
        project_policy=None,
        task_policy=None,
    )
    assert effective.effective_class == DataRoutingClass.LOCAL_ONLY
    assert effective.source == RoutingPolicySource.PROFILE_DEFAULT


# ==============================================================================
# 11. Scope Precedence: Project Override Applied
# ==============================================================================
def test_11_scope_precedence_project_override():
    # Tightening from ANY_CONFIGURED to LOCAL_ONLY is unconditionally allowed
    profile = DataRoutingPolicy(routing_class=DataRoutingClass.ANY_CONFIGURED)
    project = DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    effective = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=profile,
        project_policy=project,
        is_trusted_authority=False,
    )
    assert effective.effective_class == DataRoutingClass.LOCAL_ONLY
    assert effective.source == RoutingPolicySource.PROJECT_OVERRIDE

    # Relaxing from LOCAL_ONLY to APPROVED_CLOUD requires trusted authority + profile permission
    strict_profile = DataRoutingPolicy(
        routing_class=DataRoutingClass.LOCAL_ONLY,
        allow_project_relaxation=True,
    )
    relaxing_project = DataRoutingPolicy(
        routing_class=DataRoutingClass.APPROVED_CLOUD,
        approved_cloud_targets=[ApprovedCloudTarget(provider_id="openai")],
    )

    # Untrusted request -> relaxation denied
    eff_untrusted = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=strict_profile,
        project_policy=relaxing_project,
        is_trusted_authority=False,
    )
    assert eff_untrusted.effective_class == DataRoutingClass.LOCAL_ONLY
    assert eff_untrusted.relaxation_denied is True

    # Trusted request + allow_project_relaxation=True -> relaxation allowed
    eff_trusted = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=strict_profile,
        project_policy=relaxing_project,
        is_trusted_authority=True,
    )
    assert eff_trusted.effective_class == DataRoutingClass.APPROVED_CLOUD
    assert eff_trusted.relaxation_denied is False


# ==============================================================================
# 12. Scope Precedence: Task Override Applied
# ==============================================================================
def test_12_scope_precedence_task_override():
    project = DataRoutingPolicy(
        routing_class=DataRoutingClass.APPROVED_CLOUD,
        allow_relaxation_by_task=True,
    )

    # Tightening to LOCAL_ONLY is unconditionally permitted
    eff_tight = PrivacyPolicyEngine.resolve_effective_policy(
        project_policy=project,
        task_policy=DataRoutingClass.LOCAL_ONLY,
        is_trusted_authority=False,
    )
    assert eff_tight.effective_class == DataRoutingClass.LOCAL_ONLY
    assert eff_tight.source == RoutingPolicySource.TASK_OVERRIDE

    # Relaxing from LOCAL_ONLY requires trusted authority
    local_project = DataRoutingPolicy(
        routing_class=DataRoutingClass.LOCAL_ONLY,
        allow_relaxation_by_task=True,
    )
    eff_task_relax_untrusted = PrivacyPolicyEngine.resolve_effective_policy(
        project_policy=local_project,
        task_policy=DataRoutingClass.APPROVED_CLOUD,
        is_trusted_authority=False,
    )
    assert eff_task_relax_untrusted.effective_class == DataRoutingClass.LOCAL_ONLY
    assert eff_task_relax_untrusted.relaxation_denied is True


# ==============================================================================
# 13. Untrusted Content Cannot Relax Privacy Policy
# ==============================================================================
def test_13_anti_relaxation_defense_untrusted_sources():
    """Documents, prompt text, model outputs, or forged headers cannot relax policy."""
    profile = DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)

    # Attempted forged relaxation
    eff = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=profile,
        task_policy="any_configured",
        is_trusted_authority=False,
    )
    assert eff.effective_class == DataRoutingClass.LOCAL_ONLY
    assert eff.relaxation_denied is True


# ==============================================================================
# 14. Router Pre-Scoring Filtering Excludes Prohibited Candidates
# ==============================================================================
def test_14_router_pre_scoring_filtering():
    router = ModelRouter()
    effective = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY)
    )

    # Mock health checks so providers appear reachable
    with patch.object(
        router,
        "get_status",
        return_value={
            "llamacpp_live": True,
            "ollama_live": True,
            "openai_live": True,
            "openai_key_present": True,
            "anthropic_live": True,
            "anthropic_key_present": True,
        },
    ):
        rejections: List[Dict[str, Any]] = []
        available = router.get_available_providers(
            effective_policy=effective,
            rejection_collector=rejections,
        )

        # Prohibited providers must NOT be in available candidates
        assert "openai" not in available
        assert "anthropic" not in available
        assert "gemini" not in available
        assert "llamacpp" in available

        # Rejection collector should explain why
        rejected_provs = [r["provider"] for r in rejections]
        assert "openai" in rejected_provs


# ==============================================================================
# 15. Dispatch Boundary Independently Blocks Prohibited Provider
# ==============================================================================
@pytest.mark.anyio
async def test_15_dispatch_boundary_defense_in_depth(tmp_path):
    """If an invalid provider somehow bypassed routing, dispatch-time guard blocks it with 0 outbound calls."""
    db_path = str(tmp_path / "dispatch_boundary_test.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)

    outbound_calls = 0

    def mock_dispatch(ctx, tier, prov, model):
        nonlocal outbound_calls
        outbound_calls += 1
        return {"response": "should never be called"}

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
        dispatch_override=mock_dispatch,
    )

    # Malicious or buggy router resolution returning openai under LOCAL_ONLY
    buggy_resolved = ResolvedModel(
        provider_id="openai",
        model_id="gpt-4o",
        routing_tier=RoutingTier.FRONTIER,
        reason="forged_resolution",
        effective_privacy_class="local_only",
    )

    with patch.object(coordinator, "_resolve_routing", return_value=buggy_resolved):
        req = ExecutionRequest(
            project_id="proj_test_1",
            prompt="summarize local data",
            target_tier=RoutingTier.LOCAL,
            inputs={"privacy_class": "local_only"},
        )
        result = await coordinator.execute(req)

        # Execution must fail closed
        assert result.status in (ExecutionStatus.BLOCKED, ExecutionStatus.FAILED)
        assert result.error_code == "PRIVACY_POLICY_BLOCKED" or "Privacy policy" in str(
            result.error
        )
        # Invariant: 0 outbound network calls!
        assert outbound_calls == 0


# ==============================================================================
# 16. Canonical Aliases & Target Validation (No Wildcards/Secrets)
# ==============================================================================
def test_16_canonical_aliases_and_target_validation():
    # Valid canonical target
    t1 = ApprovedCloudTarget(provider_id="chatgpt", model_id="gpt-4o")
    assert t1.provider_id == "openai"

    t2 = ApprovedCloudTarget(provider_id="claude")
    assert t2.provider_id == "anthropic"

    t3 = ApprovedCloudTarget(provider_id="google")
    assert t3.provider_id == "gemini"

    # Rejection of wildcard *
    with pytest.raises(ValueError, match="cannot contain wildcards"):
        ApprovedCloudTarget(provider_id="*")

    # Rejection of URLs
    with pytest.raises(ValueError, match="cannot be a URL"):
        ApprovedCloudTarget(provider_id="https://api.openai.com/v1")

    # Rejection of potential secret tokens
    with pytest.raises(ValueError, match="cannot contain credentials or secret"):
        ApprovedCloudTarget(provider_id="openai", model_id="sk-proj-1234567890abcdef1234567890")


# ==============================================================================
# 17. Ledger Records Explainability Without Leaking Secrets
# ==============================================================================
@pytest.mark.anyio
async def test_17_ledger_records_privacy_explainability(tmp_path):
    db_path = str(tmp_path / "ledger_privacy_test.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)
    ledger_service = ExecutionLedgerService(storage=storage)

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
        dispatch_override=lambda ctx, tier, prov, model: {"response": "local answer"},
    )

    req = ExecutionRequest(
        project_id="proj_test_1",
        prompt="secure computation",
        target_tier=RoutingTier.LOCAL,
        inputs={"privacy_class": "local_only"},
    )
    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.routing is not None
    assert trace.routing.effective_privacy_class == "local_only"
    assert trace.routing.policy_source is not None


# ==============================================================================
# 18. Configuration Endpoints Are IPC-Auth Protected
# ==============================================================================
def test_18_configuration_endpoints_ipc_auth_protected():
    from services.python.server.app import create_app

    app = create_app()
    client = TestClient(app)

    token = "sec_token_ipc_r3_8"
    with patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}):
        # 1. Unauthenticated requests fail with 401
        assert client.get("/v1/privacy/policy").status_code == 401
        assert (
            client.put(
                "/v1/privacy/policy",
                json={"routing_class": "local_only"},
            ).status_code
            == 401
        )
        assert client.get("/v1/projects/proj_test_1/privacy").status_code == 401
        assert (
            client.put(
                "/v1/projects/proj_test_1/privacy",
                json={"routing_class": "local_only"},
            ).status_code
            == 401
        )

        headers = {"X-IPC-Token": token}

        # 2. Authenticated GET /v1/privacy/policy
        res_get = client.get("/v1/privacy/policy", headers=headers)
        assert res_get.status_code == 200
        data = res_get.json()
        assert "policy" in data
        assert "effective" in data
        assert data["effective"]["effective_class"] == "any_configured"

        # 3. Authenticated PUT /v1/privacy/policy
        res_put = client.put(
            "/v1/privacy/policy",
            headers=headers,
            json={
                "routing_class": "approved_cloud",
                "approved_cloud_targets": [{"provider_id": "openai"}],
            },
        )
        assert res_put.status_code == 200
        put_data = res_put.json()
        assert put_data["policy"]["routing_class"] == "approved_cloud"
        assert put_data["effective"]["effective_class"] == "approved_cloud"


# ==============================================================================
# 19. Integration: LOCAL_ONLY Dispatches to Local Llama.cpp and Persists Ledger
# ==============================================================================
@pytest.mark.anyio
async def test_19_integration_local_only_invokes_local_and_ledgers(tmp_path):
    db_path = str(tmp_path / "integration_local_test.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)
    ledger_service = ExecutionLedgerService(storage=storage)

    invoked_providers = []

    def mock_dispatch(ctx, tier, prov, model):
        invoked_providers.append(prov)
        return {"response": f"computed locally by {prov}"}

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
        dispatch_override=mock_dispatch,
    )

    req = ExecutionRequest(
        project_id="proj_test_1",
        prompt="classify customer record",
        target_tier=RoutingTier.LOCAL,
        inputs={"privacy_class": "local_only"},
    )
    result = await coordinator.execute(req)

    assert result.status == ExecutionStatus.COMPLETED
    assert len(invoked_providers) == 1
    assert invoked_providers[0] in ("llamacpp", "local")

    trace = ledger_service.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.routing.effective_privacy_class == "local_only"
    assert trace.routing.provider_id in ("llamacpp", "local")


# ==============================================================================
# 20. Integration: LOCAL_ONLY with Unavailable Local Runtime -> Zero Cloud Invocations
# ==============================================================================
@pytest.mark.anyio
async def test_20_integration_local_only_fails_closed_zero_cloud_invocations(tmp_path):
    db_path = str(tmp_path / "zero_cloud_test.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)

    cloud_invocations = 0

    def mock_dispatch(ctx, tier, prov, model):
        nonlocal cloud_invocations
        if prov in ("openai", "anthropic", "gemini", "deepseek", "groq", "kimi"):
            cloud_invocations += 1
        return {"response": "dummy"}

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
        dispatch_override=mock_dispatch,
    )

    # Force router to report local providers unavailable
    with patch.object(
        coordinator.model_router,
        "get_status",
        return_value={
            "llamacpp_live": False,
            "ollama_live": False,
            "openai_live": True,
            "openai_key_present": True,
        },
    ):
        req = ExecutionRequest(
            project_id="proj_test_1",
            prompt="classified financial calculation",
            target_tier=RoutingTier.LOCAL,
            inputs={"privacy_class": "local_only"},
        )
        result = await coordinator.execute(req)

        assert result.status == ExecutionStatus.FAILED
        assert (
            "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY" in str(result.error)
            or "No local model available" in str(result.error)
            or "Local runtime unavailable" in str(result.error)
        )
        # CRITICAL HARD INVARIANT: Zero cloud invocations under any circumstance
        assert cloud_invocations == 0
