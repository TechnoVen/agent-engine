"""tests/test_r3_model_registry.py

Comprehensive Model Capability Registry Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).

Verifies core R3.2 capabilities:
1. Scoped canonical identity (provider_id:model_id) parsing and alias normalization.
2. 3-Valued Logic (TRUE, FALSE, UNKNOWN) - UNKNOWN fails hard requirements.
3. Roadmap capability filtering (reasoning, coding, vision, tools, structured output, embeddings, streaming).
4. Multi-dimensional context token filtering (input, output, total).
5. Price metadata filtering and freshness tracking.
6. Latency classification and live telemetry updates.
7. Privacy constraints (local only, data leaves device = False, zero retention).
8. Declarative local hardware metadata filtering (RAM, VRAM, quantization).
9. Provenance precedence rules (USER_OVERRIDE > LOCAL_INSPECTED > REMOTE_DISCOVERY > BUILTIN).
10. Deterministic candidate ranking and explainable rejection reasons.
11. Provider filtering and ProviderRegistry integration.
12. Thread-safe concurrent operations.
"""

from __future__ import annotations

import threading
import time

import pytest

from core.model_registry import (
    LatencyClass,
    ModelCapabilities,
    ModelDefinition,
    ModelRegistry,
    ModelRequirements,
    ProvenanceType,
    TriStateBool,
    reset_model_registry,
)


@pytest.fixture(autouse=True)
def fresh_model_registry():
    """Ensure a clean model registry for each test."""
    reg = reset_model_registry()
    yield reg
    reset_model_registry()


# ==============================================================================
# 1. Scoped Canonical Identity Parsing & Normalization
# ==============================================================================
def test_01_scoped_canonical_identity_parsing(fresh_model_registry: ModelRegistry):
    """Verify provider_id:model_id format and alias normalization."""
    pid, mid = ModelRegistry.parse_canonical_id("openai:gpt-4o")
    assert pid == "openai"
    assert mid == "gpt-4o"

    pid, mid = ModelRegistry.parse_canonical_id("anthropic:claude-3-5-sonnet-20241022")
    assert pid == "anthropic"
    assert mid == "claude-3-5-sonnet-20241022"

    # Alias resolution via ProviderRegistry (google -> gemini, local -> llamacpp)
    resolved = fresh_model_registry.resolve_canonical_id("google:gemini-2.5-flash")
    assert resolved == "gemini:gemini-2.5-flash"

    resolved_local = fresh_model_registry.resolve_canonical_id(
        "local:qwen2.5-coder-3b-instruct-q4_k_m"
    )
    assert resolved_local == "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m"

    # Invalid identifiers fail closed
    with pytest.raises(ValueError, match="expected 'provider_id:model_id'"):
        ModelRegistry.parse_canonical_id("no_colon_model_id")

    with pytest.raises(ValueError, match="neither provider_id nor model_id may be empty"):
        ModelRegistry.parse_canonical_id(":empty_provider")

    with pytest.raises(ValueError, match="neither provider_id nor model_id may be empty"):
        ModelRegistry.parse_canonical_id("empty_model:")


# ==============================================================================
# 2. 3-Valued Logic Truth Table & Hard Requirements
# ==============================================================================
def test_02_tristate_bool_logic():
    """Verify 3-valued logic truth table: UNKNOWN cannot satisfy hard requirements."""
    t = TriStateBool.TRUE
    f = TriStateBool.FALSE
    u = TriStateBool.UNKNOWN

    # Conversion helpers
    assert TriStateBool.from_bool(True) == TriStateBool.TRUE
    assert TriStateBool.from_bool(False) == TriStateBool.FALSE
    assert TriStateBool.from_bool(None) == TriStateBool.UNKNOWN

    # Core Invariant: UNKNOWN fails hard requirements (required=True)
    assert t.satisfies(required=True) is True
    assert f.satisfies(required=True) is False
    assert u.satisfies(required=True) is False  # CRITICAL INVARIANT

    # Soft / optional requirements (required=False)
    assert t.satisfies(required=False) is True
    assert f.satisfies(required=False) is True
    assert u.satisfies(required=False) is True


def test_03_unknown_capability_fails_hard_requirements():
    """Verify ModelCapabilities rejects hard requirements when a capability is UNKNOWN."""
    caps = ModelCapabilities(
        reasoning=TriStateBool.TRUE,
        coding=TriStateBool.UNKNOWN,
        vision=TriStateBool.FALSE,
        tools=TriStateBool.UNKNOWN,
    )

    # TRUE satisfies
    sat, _ = caps.satisfies_requirement("reasoning", True)
    assert sat is True

    # UNKNOWN fails hard requirement with explicit reason
    sat, reason = caps.satisfies_requirement("coding", True)
    assert sat is False
    assert "UNKNOWN" in reason
    assert "cannot satisfy hard requirement" in reason

    # FALSE fails hard requirement with explicit reason
    sat, reason = caps.satisfies_requirement("vision", True)
    assert sat is False
    assert "FALSE" in reason


# ==============================================================================
# 3. Capability Dimension Filtering
# ==============================================================================
def test_04_query_by_capability_constraints(fresh_model_registry: ModelRegistry):
    """Verify router can filter models by specific capability flags."""
    # 1. Require Vision
    candidates = fresh_model_registry.query_eligible_models(ModelRequirements(require_vision=True))
    assert len(candidates) > 0
    for c in candidates:
        assert c.model_definition.capabilities.vision == TriStateBool.TRUE
    ids = [c.canonical_id for c in candidates]
    assert "openai:gpt-4o" in ids
    assert "gemini:gemini-2.5-flash" in ids
    assert "anthropic:claude-3-5-sonnet-20241022" in ids
    assert "deepseek:deepseek-chat" not in ids

    # 2. Require Embeddings
    emb_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(require_embeddings=True)
    )
    assert len(emb_candidates) == 1
    assert emb_candidates[0].canonical_id == "openai:text-embedding-3-small"

    # 3. Require Deep Reasoning
    reasoning_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(require_reasoning=True)
    )
    r_ids = [c.canonical_id for c in reasoning_candidates]
    assert "deepseek:deepseek-reasoner" in r_ids
    assert "openai:gpt-4o" in r_ids
    assert "gemini:gemini-2.5-pro" in r_ids
    assert "deepseek:deepseek-chat" not in r_ids


# ==============================================================================
# 4. Context Window Token Dimensions
# ==============================================================================
def test_05_context_window_filtering(fresh_model_registry: ModelRegistry):
    """Verify multi-dimensional context constraints (input, output, total)."""
    # Require 500,000+ input tokens (Gemini 1M/2M territory)
    large_context = fresh_model_registry.query_eligible_models(
        ModelRequirements(min_input_tokens=500000)
    )
    lc_ids = [c.canonical_id for c in large_context]
    assert "gemini:gemini-2.5-flash" in lc_ids
    assert "gemini:gemini-2.5-pro" in lc_ids
    assert "openai:gpt-4o" not in lc_ids  # 128k < 500k
    assert "anthropic:claude-3-5-sonnet-20241022" not in lc_ids  # 200k < 500k

    # Require 10,000+ output tokens
    high_output = fresh_model_registry.query_eligible_models(
        ModelRequirements(min_output_tokens=10000)
    )
    ho_ids = [c.canonical_id for c in high_output]
    assert "openai:gpt-4o" in ho_ids
    assert "openai:gpt-4o-mini" in ho_ids
    assert "anthropic:claude-3-5-sonnet-20241022" not in ho_ids  # 8192 < 10000


# ==============================================================================
# 5. Pricing Metadata & Budget Filtering
# ==============================================================================
def test_06_pricing_budget_filtering(fresh_model_registry: ModelRegistry):
    """Verify price filtering respects upper budget limits."""
    # Cheap models budget: max input $0.20 / million
    budget_models = fresh_model_registry.query_eligible_models(
        ModelRequirements(max_input_cost_per_million=0.20)
    )
    bm_ids = [c.canonical_id for c in budget_models]
    assert "openai:gpt-4o-mini" in bm_ids  # $0.15
    assert "gemini:gemini-2.5-flash" in bm_ids  # $0.075
    assert "deepseek:deepseek-chat" in bm_ids  # $0.14
    assert "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m" in bm_ids  # $0.0
    assert "openai:gpt-4o" not in bm_ids  # $2.50 > $0.20
    assert "anthropic:claude-3-5-sonnet-20241022" not in bm_ids  # $3.00 > $0.20


# ==============================================================================
# 6. Latency Metadata & Live Telemetry Updates
# ==============================================================================
def test_07_latency_classification_and_telemetry(fresh_model_registry: ModelRegistry):
    """Verify latency class filtering and runtime telemetry updates."""
    # Filter for FAST models
    fast_models = fresh_model_registry.query_eligible_models(
        ModelRequirements(allowed_latency_classes=[LatencyClass.FAST])
    )
    fast_ids = [c.canonical_id for c in fast_models]
    assert "groq:llama-3.3-70b-specdec" in fast_ids
    assert "openai:gpt-4o-mini" in fast_ids

    # Update telemetry for a medium model and verify effective latency
    model = fresh_model_registry.get_model("openai:gpt-4o")
    assert model is not None
    assert model.latency.catalog_latency_ms == 1200.0

    # Inject observed telemetry
    updated = fresh_model_registry.update_telemetry("openai:gpt-4o", latency_ms=450.0)
    assert updated is True
    assert model.latency.effective_latency_ms == 450.0
    assert model.latency.latency_class == LatencyClass.FAST

    # Now it qualifies for fast filter
    fast_now = fresh_model_registry.query_eligible_models(
        ModelRequirements(allowed_latency_classes=[LatencyClass.FAST])
    )
    assert "openai:gpt-4o" in [c.canonical_id for c in fast_now]


# ==============================================================================
# 7. Privacy & Data Sovereignty Constraints
# ==============================================================================
def test_08_privacy_constraints(fresh_model_registry: ModelRegistry):
    """Verify local-only and zero-egress data privacy filtering."""
    # Require strictly local execution
    local_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(require_local_only=True)
    )
    assert len(local_candidates) > 0
    for c in local_candidates:
        assert c.model_definition.privacy.is_local is True
        assert c.model_definition.privacy.data_leaves_device is False

    l_ids = [c.canonical_id for c in local_candidates]
    assert "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m" in l_ids
    assert "ollama:qwen2.5-coder:3b" in l_ids
    assert "openai:gpt-4o" not in l_ids

    # Require allow_data_leaves_device=False
    no_egress = fresh_model_registry.query_eligible_models(
        ModelRequirements(allow_data_leaves_device=False)
    )
    for c in no_egress:
        assert c.model_definition.privacy.data_leaves_device is False


# ==============================================================================
# 8. Declarative Hardware Constraints
# ==============================================================================
def test_09_hardware_constraints(fresh_model_registry: ModelRegistry):
    """Verify local model hardware resource filtering."""
    # System with only 2.0 GB RAM available
    low_ram_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(
            require_local_only=True,
            max_available_ram_bytes=int(2.0 * 1024 * 1024 * 1024),
        )
    )
    lr_ids = [c.canonical_id for c in low_ram_candidates]
    # 1B models fit in 2GB
    assert "llamacpp:llama-3.2-1b-instruct-q4_k_m" in lr_ids
    # 3B models need >= 3GB and are excluded
    assert "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m" not in lr_ids


# ==============================================================================
# 9. Provenance Precedence Rules
# ==============================================================================
def test_10_provenance_precedence(fresh_model_registry: ModelRegistry):
    """Verify USER_OVERRIDE > LOCAL_INSPECTED > REMOTE_DISCOVERY > BUILTIN."""
    cid = "openai:gpt-4o"
    orig = fresh_model_registry.get_model(cid)
    assert orig is not None
    assert orig.provenance == ProvenanceType.BUILTIN

    # 1. Higher precedence (REMOTE_DISCOVERY > BUILTIN) succeeds
    discovered_model = orig.model_copy(deep=True)
    discovered_model.provenance = ProvenanceType.REMOTE_DISCOVERY
    discovered_model.display_name = "GPT-4o (Discovered)"
    assert fresh_model_registry.register_model(discovered_model) is True
    assert fresh_model_registry.get_model(cid).display_name == "GPT-4o (Discovered)"

    # 2. Lower precedence (BUILTIN < REMOTE_DISCOVERY) is rejected
    builtin_attempt = orig.model_copy(deep=True)
    builtin_attempt.provenance = ProvenanceType.BUILTIN
    builtin_attempt.display_name = "GPT-4o (Builtin Re-assert)"
    assert fresh_model_registry.register_model(builtin_attempt) is False
    # Remains discovered name
    assert fresh_model_registry.get_model(cid).display_name == "GPT-4o (Discovered)"

    # 3. User override (highest precedence) succeeds
    user_override = orig.model_copy(deep=True)
    user_override.provenance = ProvenanceType.USER_OVERRIDE
    user_override.display_name = "My Custom GPT-4o"
    assert fresh_model_registry.register_model(user_override) is True
    assert fresh_model_registry.get_model(cid).display_name == "My Custom GPT-4o"

    # 4. Local inspected cannot overwrite User override (3 < 4)
    inspected = orig.model_copy(deep=True)
    inspected.provenance = ProvenanceType.LOCAL_INSPECTED
    assert fresh_model_registry.register_model(inspected) is False
    assert fresh_model_registry.get_model(cid).display_name == "My Custom GPT-4o"


# ==============================================================================
# 10. Explainable Rejection Reasons
# ==============================================================================
def test_11_explainable_rejection_reasons(fresh_model_registry: ModelRegistry):
    """Verify disqualified models provide transparent, deterministic rejection reasons."""
    all_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(
            require_vision=True,
            require_local_only=True,
            min_input_tokens=100000,
        ),
        eligible_only=False,
    )
    assert len(all_candidates) > 0

    # OpenAI GPT-4o is rejected because it is not local
    gpt4o = next(c for c in all_candidates if c.canonical_id == "openai:gpt-4o")
    assert gpt4o.eligible is False
    assert any("not local" in r for r in gpt4o.rejection_reasons)

    # Local llama.cpp 3b is rejected because it has no vision and input context < 100k
    llama = next(
        c for c in all_candidates if c.canonical_id == "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m"
    )
    assert llama.eligible is False
    assert any("vision" in r.lower() for r in llama.rejection_reasons)
    assert any("context" in r.lower() for r in llama.rejection_reasons)


# ==============================================================================
# 11. Provider Filtering & Registry Lookups
# ==============================================================================
def test_12_provider_filtering(fresh_model_registry: ModelRegistry):
    """Verify allowed_providers and excluded_providers constrain selection."""
    only_anthropic = fresh_model_registry.query_eligible_models(
        ModelRequirements(allowed_providers=["anthropic"])
    )
    for c in only_anthropic:
        assert c.provider_id == "anthropic"

    no_openai = fresh_model_registry.query_eligible_models(
        ModelRequirements(excluded_providers=["openai"])
    )
    for c in no_openai:
        assert c.provider_id != "openai"


# ==============================================================================
# 12. Concurrency Safety
# ==============================================================================
def test_13_concurrent_queries_and_registrations(fresh_model_registry: ModelRegistry):
    """Verify thread safety under concurrent model registrations and queries."""
    errors = []

    def writer_thread():
        for i in range(20):
            try:
                m = ModelDefinition(
                    provider_id="openai",
                    model_id=f"dynamic-model-{i}",
                    display_name=f"Dynamic {i}",
                    max_total_context_tokens=8192,
                    provenance=ProvenanceType.USER_OVERRIDE,
                )
                fresh_model_registry.register_model(m, force=True)
                time.sleep(0.005)
            except Exception as e:
                errors.append(e)

    def reader_thread():
        for _ in range(20):
            try:
                fresh_model_registry.query_eligible_models(ModelRequirements(require_coding=True))
                fresh_model_registry.list_models()
                time.sleep(0.005)
            except Exception as e:
                errors.append(e)

    t1 = threading.Thread(target=writer_thread)
    t2 = threading.Thread(target=reader_thread)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0
