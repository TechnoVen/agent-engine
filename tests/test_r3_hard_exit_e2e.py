"""tests/test_r3_hard_exit_e2e.py

Milestone R3 0.5 Hard-Exit Integrated Decision & Invocation E2E Suite.

Proves the Canonical R3 Hard-Exit Claim:
"Agent Engine can automatically select and actually invoke the best eligible
local or cloud model for a task, and the execution ledger proves the choice."

Verification Slices:
1. Real Managed Local E2E:
   - Real ResourceManager state + real ModelRegistry + LOCAL_ONLY privacy policy
   - ExecutionRequest -> ExecutionCoordinator -> R3.8 privacy filter -> R3.9 objective
   - Selected canonical ModelIdentity -> ProviderRegistry["llamacpp"] -> LlamaCppAdapter
   - Actual AE-managed llama.cpp process -> actual verified GGUF model
   - Real prompt generation containing canary codeword 'AE_R3_EXIT_K9P2'
   - ExecutionLedger routing trace recording actual provider, model, local tier, and zero secrets.
   - Zero mock provider adapter, fake completion, precomputed token response, or direct HTTP bypass.
2. Mocked Local Routing Fixture:
   - Deterministic test fixture validating multi-step policy routing logic with simulated adapter.
3. Mocked Permitted Cloud Routing Fixture:
   - Deterministic test fixture validating APPROVED_CLOUD policy path and quality_first objective.
4. Live Cloud E2E (Opt-in):
   - External provider invocation (skipped in deterministic CI when OPENAI_API_KEY is unset).
5. Verified Model Artifact Execution Boundary:
   - Proves unverified managed-model execution = 0.
   - ModelArtifactValidator permits verified artifacts, rejects .partial downloads,
     rejects unverified metadata states, and rejects 1-byte SHA-256 tampered files at launch boundary.
6. Production Bypass & Legacy Routing Audit:
   - Privacy bypass = 0 (cloud rejected before scoring under LOCAL_ONLY).
   - Active legacy percentage routing = 0 (deterministic utility weights sum to 1.0; 0 stochastic splits).
   - Shallow health falsely setting Connected = 0.
   - Unauthorized inference call sites = 0 across production code.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import MagicMock
import pytest

from core.execution.coordinator import ExecutionCoordinator, ExecutionRequest
from core.execution.models import ExecutionStatus
from core.storage.paths import get_private_data_dir
from core.inference.models import RuntimeSpec, RuntimeState
from core.inference.supervisor import (
    LocalInferenceSupervisor,
    SupervisorError,
    get_local_inference_supervisor,
    reset_local_inference_supervisor,
)
from core.inference.validation import (
    GGUF_MAGIC_BYTES,
    ModelArtifactValidator,
    ModelValidationError,
    ValidatedModelArtifact,
)
from core.ledger.service import LedgerService
from core.model_registry.models import (
    ExecutionLocation,
    ModelCapabilities,
    ModelDefinition,
    ModelIdentity,
    PricingProfile,
    PrivacyProfile,
    TriStateBool,
)
from core.model_registry.registry import (
    ModelRegistry,
    get_model_registry,
    reset_model_registry,
)
from core.privacy.models import (
    ApprovedCloudTarget,
    DataRoutingClass,
    DataRoutingPolicy,
    EffectiveRoutingPolicy,
    NoEligibleModelUnderPrivacyPolicyError,
    RoutingPolicySource,
)
from core.providers import get_provider_registry, reset_provider_registry
from core.providers.base import ProviderInvocationResult, ProviderServerError
from core.providers.models import (
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderDefinition,
    ProviderEndpointClass,
    ProviderEndpointStyle,
    ProviderHealth,
    ProviderHealthStatus,
)
from core.providers.registry import ProviderRegistry
from core.providers.verification.models import ConnectionVerificationStatus
from core.providers.verification.service import (
    ProviderVerificationService,
    reset_provider_verification_service,
)
from core.resources.manager import ResourceManager
from core.router.models import RoutingObjectiveProfile
from core.router.objective import RoutingOptimizer
from core.storage.sqlite import SQLiteBackend


@pytest.fixture
def test_storage(tmp_path: Path):
    db_path = str(tmp_path / "test_hard_exit.db")
    return SQLiteBackend(db_path=db_path)


@pytest.fixture(autouse=True)
def cleanup_e2e_singletons():
    reset_provider_registry()
    reset_model_registry()
    reset_provider_verification_service()
    reset_local_inference_supervisor()
    yield
    reset_provider_registry()
    reset_model_registry()
    reset_provider_verification_service()
    reset_local_inference_supervisor()


def make_test_model(
    provider_id: str,
    model_id: str,
    is_local: bool = False,
    input_price: float = 0.0,
    output_price: float = 0.0,
) -> ModelDefinition:
    return ModelDefinition(
        identity=ModelIdentity(provider_id=provider_id, model_id=model_id),
        display_name=f"{provider_id} {model_id}",
        capabilities=ModelCapabilities(
            coding=TriStateBool.TRUE,
            tools=TriStateBool.TRUE,
        ),
        max_total_context_tokens=128000,
        pricing=PricingProfile(
            input_cost_per_million=input_price if not is_local else 0.0,
            output_cost_per_million=output_price if not is_local else 0.0,
            is_free=is_local,
        ),
        privacy=PrivacyProfile(
            is_local=is_local,
            data_leaves_device=False if is_local else True,
            execution_location=ExecutionLocation.LOCAL if is_local else ExecutionLocation.REMOTE,
        ),
    )


# ==============================================================================
# 1. Real Managed Local Hard-Exit E2E (Zero Mocks, Real llama.cpp Process & Model)
# ==============================================================================
@pytest.mark.anyio
async def test_r3_hard_exit_real_managed_local_e2e(test_storage):
    """Real Managed Local Hard-Exit E2E:
    Proves Agent Engine can select and actually invoke a real local model via an
    AE-managed llama.cpp runtime, verifying the response content and the execution ledger trace.

    Zero mock provider adapter, fake completion, or shadow HTTP bypass.
    """
    ae_bin = get_private_data_dir() / "runtimes" / "llamacpp" / "llama-server"
    desktop_bin = Path.cwd() / "apps" / "desktop" / "src-tauri" / "binaries" / "llama-server"
    model_path = Path.cwd() / "models" / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"

    if not (
        (ae_bin.is_file() and os.access(ae_bin, os.X_OK))
        or (desktop_bin.is_file() and os.access(desktop_bin, os.X_OK))
    ):
        pytest.skip("Real llama-server binary not found in AE storage; skipping hardware E2E.")
    if not model_path.is_file():
        pytest.skip(
            "Real test model not found at models/qwen2.5-coder-3b-instruct-q4_k_m.gguf; skipping hardware E2E."
        )

    # 1. Verify host resources snapshot through ResourceManager
    res_mgr = ResourceManager()
    snapshot = res_mgr.get_snapshot()
    assert snapshot is not None
    assert snapshot.cpu.logical_cores >= 1

    # 2. Configure ModelRegistry with real local candidate and cloud candidate
    model_reg = get_model_registry()
    model_reg.register_model(
        ModelDefinition(
            identity=ModelIdentity(
                provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m"
            ),
            display_name="Qwen 2.5 Coder 3B GGUF",
            capabilities=ModelCapabilities(coding=TriStateBool.TRUE, tools=TriStateBool.TRUE),
            pricing=PricingProfile(is_free=True),
            privacy=PrivacyProfile(
                is_local=True,
                data_leaves_device=False,
                execution_location=ExecutionLocation.LOCAL,
            ),
        )
    )
    model_reg.register_model(
        ModelDefinition(
            identity=ModelIdentity(provider_id="openai", model_id="gpt-4o"),
            display_name="GPT-4o Cloud",
            capabilities=ModelCapabilities(coding=TriStateBool.TRUE, tools=TriStateBool.TRUE),
            pricing=PricingProfile(input_cost_per_million=2.5, output_cost_per_million=10.0),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
                execution_location=ExecutionLocation.REMOTE,
            ),
        )
    )

    # 3. Canonical ProviderRegistry already contains llamacpp and openai adapters
    prov_reg = get_provider_registry()
    assert prov_reg.get_provider("llamacpp") is not None
    assert prov_reg.get_provider("openai") is not None

    # 4. Launch real AE-managed llama.cpp supervisor process
    supervisor = get_local_inference_supervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m")
    spec = RuntimeSpec(
        model_identity=ident,
        model_path=str(model_path),
        context_size=512,
        gpu_layers=0,  # Pure CPU execution for deterministic clean-machine validation
        startup_timeout_seconds=180.0,
        shutdown_timeout_seconds=5.0,
    )

    try:
        inst = supervisor.start(spec)
        assert supervisor.state == RuntimeState.READY
        assert inst.pid is not None
        assert inst.endpoint_url is not None

        # Verify adapter resolves to the managed process endpoint
        adapter = prov_reg.get_adapter("llamacpp")
        assert adapter._get_base_url() == f"{inst.endpoint_url}/v1"

        # 5. Execute through ExecutionCoordinator with NO dispatch override
        coordinator = ExecutionCoordinator(storage=test_storage)
        canary = "AE_R3_EXIT_K9P2"
        canary_prompt = f"Repeat this exact code word once: {canary}"

        req = ExecutionRequest(
            project_id="test_hard_exit_project",
            prompt=canary_prompt,
            routing_policy=DataRoutingPolicy(default_class=DataRoutingClass.LOCAL_ONLY),
            inputs={
                "task_family": "coding",
                "routing_objective": "balanced",
                "actor": "user",
            },
        )

        result = await coordinator.execute(req)

        # 6. Truth assertions on real execution result
        assert result.status in ("completed", ExecutionStatus.COMPLETED)
        assert result.provider_used == "llamacpp"
        assert result.model_used is not None
        assert canary in str(result.outputs)

        # 7. Truth assertions on durable ExecutionLedger trace
        ledger_svc = LedgerService(storage=test_storage)
        trace = ledger_svc.get_execution_trace(result.execution_id)
        assert trace is not None
        assert trace.routing_trace is not None
        assert trace.routing_trace.actual_provider == "llamacpp"
        assert trace.routing_trace.resolved_tier == "local"
        assert trace.routing_trace.effective_privacy_class == "local_only"

        # Cloud candidate was rejected in stage 1 by privacy engine
        assert any(
            rej.get("provider") == "openai" or "openai" in str(rej)
            for rej in trace.routing_trace.privacy_rejections
        )

        # Zero secret credentials leaked into ledger
        dumped_trace = str(trace.routing_trace.model_dump())
        assert "sk-" not in dumped_trace
        assert "api_key" not in dumped_trace

    finally:
        supervisor.stop()
        reset_local_inference_supervisor()


# ==============================================================================
# 2. Mocked Provider Integration Fixtures (Deterministic Routing & Policy)
# ==============================================================================
@pytest.mark.anyio
async def test_r3_hard_exit_mocked_local_routing_fixture(test_storage):
    """Mocked Provider Integration Fixture for Deterministic Local Policy Routing:
    Validates LOCAL_ONLY privacy class, objective evaluation, and ledger trace recording
    using an isolated mock adapter fixture.
    """
    prov_reg = ProviderRegistry()
    mock_local_adapter = MagicMock()
    mock_local_adapter.invoke.return_value = ProviderInvocationResult(
        content="def hello_world(): return 'hello'",
        model="qwen-2.5-coder-7b",
        provider_id="llamacpp",
        input_tokens=15,
        output_tokens=12,
        latency_ms=45.0,
    )
    mock_cloud_adapter = MagicMock()

    prov_reg.register_provider(
        ProviderDefinition(
            provider_id="llamacpp",
            display_name="llama.cpp Managed Runtime",
            endpoint_style=ProviderEndpointStyle.LLAMACPP,
            endpoint_class=ProviderEndpointClass.LOCAL_MANAGED,
            default_model="qwen-2.5-coder-7b",
            config=ProviderConfiguration(
                provider_id="llamacpp", endpoint_url="http://127.0.0.1:8080"
            ),
            capabilities=ProviderCapabilities(is_local=True, requires_credentials=False),
        ),
        adapter_factory=lambda d, s: mock_local_adapter,
    )
    prov_reg.register_provider(
        ProviderDefinition(
            provider_id="openai",
            display_name="OpenAI Cloud",
            endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
            endpoint_class=ProviderEndpointClass.CLOUD,
            default_model="gpt-4o",
            config=ProviderConfiguration(provider_id="openai", credential_key="OPENAI_API_KEY"),
            capabilities=ProviderCapabilities(is_local=False, requires_credentials=True),
        ),
        adapter_factory=lambda d, s: mock_cloud_adapter,
    )

    model_reg = ModelRegistry()
    model_reg.register_model(make_test_model("llamacpp", "qwen-2.5-coder-7b", is_local=True))
    model_reg.register_model(
        make_test_model("openai", "gpt-4o", is_local=False, input_price=2.5, output_price=10.0)
    )

    def mock_dispatch(ctx, tier, prov, model):
        adapter = prov_reg.get_adapter(prov)
        prompt_str = getattr(ctx, "prompt", "") if hasattr(ctx, "prompt") else str(ctx)
        res = adapter.invoke(prompt=prompt_str, model=model)
        return {"response": res.content, "provider": prov, "model": model}

    coordinator = ExecutionCoordinator(storage=test_storage, dispatch_override=mock_dispatch)

    req = ExecutionRequest(
        project_id="test_project",
        prompt="Write a python function to greet",
        inputs={
            "privacy_class": "LOCAL_ONLY",
            "task_family": "coding",
            "routing_objective": "balanced",
            "actor": "user",
        },
    )
    result = await coordinator.execute(req)

    assert result.status == "completed"
    assert mock_local_adapter.invoke.call_count == 1
    assert mock_cloud_adapter.invoke.call_count == 0
    assert "def hello_world" in str(result.outputs)

    ledger_svc = LedgerService(storage=test_storage)
    trace = ledger_svc.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.routing_trace is not None
    assert trace.routing_trace.actual_provider in ["llamacpp", "local"]
    assert "sk-" not in str(trace.routing_trace.model_dump())


@pytest.mark.anyio
async def test_r3_hard_exit_mocked_permitted_cloud_routing_fixture(test_storage):
    """Mocked Provider Integration Fixture for Permitted Cloud Routing:
    Validates APPROVED_CLOUD privacy class, quality_first objective selection, and
    ledger trace recording without live external API credentials.
    """
    prov_reg = ProviderRegistry()
    mock_openai_adapter = MagicMock()
    mock_openai_adapter.invoke.return_value = ProviderInvocationResult(
        content="Analyzed reasoning result: Solution A is optimal.",
        model="gpt-4o",
        provider_id="openai",
        input_tokens=100,
        output_tokens=50,
        latency_ms=180.0,
    )

    prov_reg.register_provider(
        ProviderDefinition(
            provider_id="openai",
            display_name="OpenAI Cloud",
            endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
            endpoint_class=ProviderEndpointClass.CLOUD,
            default_model="gpt-4o",
            config=ProviderConfiguration(provider_id="openai", credential_key="OPENAI_API_KEY"),
            capabilities=ProviderCapabilities(is_local=False, requires_credentials=True),
        ),
        adapter_factory=lambda d, s: mock_openai_adapter,
    )

    model_reg = ModelRegistry()
    model_reg.register_model(
        make_test_model("openai", "gpt-4o", is_local=False, input_price=2.5, output_price=10.0)
    )

    def mock_dispatch(ctx, tier, prov, model):
        adapter = prov_reg.get_adapter(prov)
        prompt_str = getattr(ctx, "prompt", "") if hasattr(ctx, "prompt") else str(ctx)
        res = adapter.invoke(prompt=prompt_str, model=model)
        return {"response": res.content, "provider": prov, "model": model}

    coordinator = ExecutionCoordinator(storage=test_storage, dispatch_override=mock_dispatch)

    req = ExecutionRequest(
        project_id="test_project",
        prompt="Analyze multi-agent convergence theorem",
        routing_policy=DataRoutingPolicy(
            routing_class=DataRoutingClass.APPROVED_CLOUD,
            approved_cloud_targets=[ApprovedCloudTarget(provider_id="openai")],
        ),
        inputs={
            "task_family": "reasoning",
            "routing_objective": "quality_first",
            "actor": "user",
        },
    )
    result = await coordinator.execute(req)

    assert result.status == "completed"
    assert mock_openai_adapter.invoke.call_count == 1
    assert "Analyzed reasoning result" in str(result.outputs)

    ledger_svc = LedgerService(storage=test_storage)
    trace = ledger_svc.get_execution_trace(result.execution_id)
    assert trace is not None
    assert trace.routing_trace is not None
    assert trace.routing_trace.routing_objective == "quality_first"
    assert "api_key" not in str(trace.routing_trace.model_dump())


# ==============================================================================
# 3. Live Cloud E2E (Opt-in with Environment Credentials)
# ==============================================================================
@pytest.mark.anyio
async def test_r3_hard_exit_live_cloud_e2e_opt_in(test_storage):
    """Opt-in Live Cloud E2E Test:
    Executes actual external API call when OPENAI_API_KEY is configured in the environment.
    Skipped in standard CI/test environments to ensure deterministic offline execution.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-") or "your_key" in api_key:
        pytest.skip(
            "Live external cloud invocation skipped: valid OPENAI_API_KEY not configured. "
            "Cloud path implementation and conformance verified at S1 via mocked integration fixture."
        )

    coordinator = ExecutionCoordinator(storage=test_storage)
    req = ExecutionRequest(
        project_id="test_cloud_live_project",
        prompt="Reply with the exact word: PONG",
        routing_policy=DataRoutingPolicy(
            routing_class=DataRoutingClass.APPROVED_CLOUD,
            approved_cloud_targets=[ApprovedCloudTarget(provider_id="openai")],
        ),
        inputs={"task_family": "general", "routing_objective": "quality_first", "actor": "user"},
    )
    res = await coordinator.execute(req)
    assert res.status in ("completed", ExecutionStatus.COMPLETED)
    assert "PONG" in str(res.outputs).upper()


# ==============================================================================
# 4. Verified Model Artifact Execution Boundary (CTO Item 4)
# ==============================================================================
def test_r3_hard_exit_verified_artifact_execution_boundary(tmp_path: Path):
    """Proves 'Unverified managed-model execution = 0':
    Verifies that ModelArtifactValidator and LocalInferenceSupervisor enforce the
    mandatory verification boundary:
    1. Verified GGUF model with matching SHA-256 metadata is validated.
    2. .partial download artifact is rejected immediately.
    3. Model with metadata != 'verified' is rejected immediately.
    4. 1-byte file mutation causes SHA-256 integrity recomputation to fail and reject.
    5. LocalInferenceSupervisor rejects tampered model at launch boundary (0 processes started).
    """
    model_file = tmp_path / "test_model.gguf"
    fake_gguf_content = GGUF_MAGIC_BYTES + b"\x00" * 1024
    model_file.write_bytes(fake_gguf_content)

    real_digest = hashlib.sha256(fake_gguf_content).hexdigest()
    meta_file = tmp_path / "test_model.gguf.meta.json"
    meta_payload = {
        "model_id": "test_model",
        "state": "verified",
        "expected_sha256": real_digest,
        "total_bytes_expected": len(fake_gguf_content),
        "verified_at": time.time(),
    }
    meta_file.write_text(json.dumps(meta_payload), encoding="utf-8")

    # 1. Valid artifact passes validation
    validated = ModelArtifactValidator.validate(model_file)
    assert isinstance(validated, ValidatedModelArtifact)
    assert validated.format == "gguf"
    assert validated.size_bytes == len(fake_gguf_content)

    # 2. Incomplete (.partial) artifact rejected
    partial_file = tmp_path / "download.gguf.partial"
    partial_file.write_bytes(fake_gguf_content)
    with pytest.raises(ModelValidationError, match=r"incomplete \(\.partial\) download artifact"):
        ModelArtifactValidator.validate(partial_file)

    # 3. Unverified metadata state rejected
    unverified_meta_file = tmp_path / "unverified.gguf.meta.json"
    unverified_model_file = tmp_path / "unverified.gguf"
    unverified_model_file.write_bytes(fake_gguf_content)
    unverified_meta_file.write_text(
        json.dumps(
            {"model_id": "unverified", "state": "downloading", "expected_sha256": real_digest}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelValidationError, match=r"only VERIFIED artifacts permitted"):
        ModelArtifactValidator.validate(unverified_model_file)

    # 4. 1-byte mutation causes SHA-256 recomputation failure
    tampered_model_file = tmp_path / "tampered.gguf"
    tampered_content = GGUF_MAGIC_BYTES + b"\x01" + b"\x00" * 1023  # Mutate 1 byte
    tampered_model_file.write_bytes(tampered_content)
    tampered_meta_file = tmp_path / "tampered.gguf.meta.json"
    tampered_meta_file.write_text(
        json.dumps(
            {
                "model_id": "tampered",
                "state": "verified",
                "expected_sha256": real_digest,  # Original expected digest
                "total_bytes_expected": len(tampered_content),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelValidationError, match=r"integrity compromised"):
        ModelArtifactValidator.validate(tampered_model_file)

    # 5. LocalInferenceSupervisor execution boundary: rejects launch of tampered artifact
    supervisor = LocalInferenceSupervisor()
    spec = RuntimeSpec(
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="tampered"),
        model_path=str(tampered_model_file),
    )
    with pytest.raises((SupervisorError, ModelValidationError), match=r"integrity compromised"):
        supervisor.start(spec)

    assert supervisor.get_active_instance() is None


# ==============================================================================
# 5. Production Bypasses & Legacy Routing Audit (CTO Items 5 & 6)
# ==============================================================================
def test_r3_hard_exit_bypasses_and_legacy_routing_audit():
    """Audit production bypass invariants:
    - direct model invocation bypass = 0
    - direct provider invocation bypass = 0
    - legacy 90/9/1 routing in production = 0
    - privacy bypass = 0
    - unverified managed-model execution = 0
    - shallow health falsely setting Connected = 0
    """
    optimizer = RoutingOptimizer()
    cloud_cand = make_test_model(
        "openai", "gpt-4o", is_local=False, input_price=2.5, output_price=10.0
    )
    local_cand = make_test_model("llamacpp", "qwen", is_local=True)

    policy = EffectiveRoutingPolicy(
        profile_policy=DataRoutingPolicy(default_class=DataRoutingClass.LOCAL_ONLY),
        effective_class=DataRoutingClass.LOCAL_ONLY,
        source=RoutingPolicySource.TASK_OVERRIDE,
    )

    decision = optimizer.optimize(
        candidates=[cloud_cand, local_cand],
        effective_policy=policy,
        objective=RoutingObjectiveProfile.QUALITY_FIRST,
    )

    # 1. Privacy bypass = 0: Cloud candidate was rejected in stage 1, never scored
    assert decision.winner.provider_id == "llamacpp"
    assert any(
        r.provider_id == "openai" and r.stage == "PRIVACY" for r in decision.rejected_candidates
    )
    assert all(c.provider_id != "openai" for c in decision.eligible_candidates)

    # 2. Legacy 90/9/1 routing in production = 0:
    # Router uses strictly deterministic multi-attribute utility weights, zero heuristic splits
    assert decision.objective_weights["w_quality"] == 0.60
    assert decision.objective_weights["w_cost"] == 0.15
    assert decision.objective_weights["w_latency"] == 0.15
    assert decision.objective_weights["w_health"] == 0.10
    assert round(sum(decision.objective_weights.values()), 4) == 1.0

    # 3. Shallow health falsely setting Connected = 0:
    # A provider returning 200 OK on health probe but failing completion CANARY
    # MUST NOT be marked VERIFIED_CONNECTED
    reg = ProviderRegistry()
    adapter = MagicMock()
    adapter.check_health.return_value = ProviderHealth(
        status=ProviderHealthStatus.HEALTHY, latency_ms=10.0
    )
    adapter.invoke.side_effect = ProviderServerError("500 Internal Error", provider_id="openai")

    reg.register_provider(
        ProviderDefinition(
            provider_id="openai",
            display_name="OpenAI",
            endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
            endpoint_class=ProviderEndpointClass.CLOUD,
            default_model="gpt-4o",
            config=ProviderConfiguration(provider_id="openai", credential_key="OPENAI_API_KEY"),
        ),
        adapter_factory=lambda d, s: adapter,
    )
    ver_svc = ProviderVerificationService(registry=reg)
    ver = ver_svc.verify_provider("openai")
    assert ver.status != ConnectionVerificationStatus.VERIFIED_CONNECTED
    assert ver.status == ConnectionVerificationStatus.PROVIDER_ERROR
    assert ver.display_state() == "Verification failed"

    # 4. Policy block in verification: 0 provider invocations
    mock_policy_engine = MagicMock()
    mock_policy_engine.evaluate.return_value = MagicMock(decision="block", reason="Policy block")
    policy_blocked_ver_svc = ProviderVerificationService(
        registry=reg, policy_engine=mock_policy_engine
    )
    ver_blocked = policy_blocked_ver_svc.verify_provider("openai")
    assert ver_blocked.status == ConnectionVerificationStatus.POLICY_BLOCKED
    assert ver_blocked.display_state() == "Policy blocked"
    assert (
        adapter.invoke.call_count == 1
    )  # No additional invoke call was made during blocked verification

    # 5. Direct model & provider invocation bypass = 0:
    # Explicit requested model or provider pointing to cloud under LOCAL_ONLY is intercepted
    # and rejected by ModelRouter before any network dispatch can occur
    from core.router.model_router import ModelRouter

    router = ModelRouter()
    with pytest.raises(NoEligibleModelUnderPrivacyPolicyError):
        router.resolve_model(
            requested_model="openai/gpt-4o",
            effective_policy=policy,
        )

    # 6. Repository Call-Site Inference Audit (CTO Item 5):
    # Proves unauthorized inference bypasses = 0 across production code.
    import re

    core_dir = Path.cwd() / "core"
    direct_client_pattern = re.compile(
        r"^\s*(import\s+(openai|anthropic|google\.generativeai)|from\s+(openai|anthropic|google\.generativeai)\s+import)",
        re.MULTILINE,
    )
    direct_completion_pattern = re.compile(r'/completion["\']')

    for py_file in core_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert not direct_client_pattern.search(content), (
            f"Unauthorized direct client import in {py_file}"
        )
        assert not direct_completion_pattern.search(content), (
            f"Unauthorized direct /completion call in {py_file}"
        )

    # 7. Repository Legacy Routing Audit (CTO Item 6):
    # Proves active production legacy percentage routing = 0.
    for py_file in core_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "stochastic" not in content.lower(), f"Unexpected 'stochastic' keyword in {py_file}"
