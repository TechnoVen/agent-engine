"""tests/test_r3_model_registry.py

Comprehensive Model Capability Registry Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry - Final Capability-Truth Closure).

Verifies all R3.2 core invariants:
1. Structured model identity (ModelIdentity) and round-trip serialization with colons, slashes, Unicode.
2. 3-Valued Logic (TRUE, FALSE, UNKNOWN) - UNKNOWN strictly fails hard capability and privacy requirements.
3. Multi-dimensional context token filtering (input, output, total).
4. Unit-explicit and time-aware price filtering; missing price remains UNKNOWN, never zero.
5. Latency separation: catalog baseline classification is preserved separately from live telemetry.
6. Privacy constraints (local only, zero egress, zero retention) reject UNKNOWN.
7. Local hardware metadata filtering (RAM, VRAM).
8. Provenance preservation: USER_OVERRIDE remains visible and never masquerades as provider-certified.
9. Security restriction: user override cannot downgrade authoritative cloud data_leaves_device=TRUE to FALSE.
10. Untrusted discovery/callers cannot invoke precedence-force (raises PermissionError).
11. Field-level provenance merging: sparse higher-precedence records do not erase known facts;
    FALSE and UNKNOWN merge differently.
12. Generic 'compatible' provider defaults unsupported facts conservatively to UNKNOWN.
13. Candidate score represents deterministic metadata completeness, not premature winner routing.
14. Concurrency safety under multithreaded operations.
"""

from __future__ import annotations

import threading
import time

import pytest

from core.model_registry import (
    ExecutionLocation,
    LatencyClass,
    ModelCapabilities,
    ModelDefinition,
    ModelIdentity,
    ModelRegistry,
    ModelRequirements,
    ProvenanceType,
    TriStateBool,
    parse_model_identifier,
    reset_model_registry,
)


@pytest.fixture(autouse=True)
def fresh_model_registry():
    """Ensure a clean model registry for each test."""
    reg = reset_model_registry()
    yield reg
    reset_model_registry()


# ==============================================================================
# 1. Structured Model Identity & Normalization
# ==============================================================================
def test_01_scoped_canonical_identity_parsing(fresh_model_registry: ModelRegistry):
    """Verify provider_id:model_id format and alias normalization via structured identity."""
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


def test_01b_structured_identity_roundtrip_colons_and_unicode():
    """Verify structured ModelIdentity round-trips model IDs containing colons, slashes, spaces, and Unicode."""
    # 1. Model ID with colons and provider-native tags
    tag_ident = ModelIdentity(provider_id="ollama", model_id="llama3.2:3b-instruct-q4_K_M")
    serialized = tag_ident.to_serialized_id()
    assert serialized.startswith("v1:ollama:")
    parsed = ModelIdentity.from_serialized_id(serialized)
    assert parsed == tag_ident
    assert parsed.model_id == "llama3.2:3b-instruct-q4_K_M"

    # 2. Model ID with slashes and revision syntax
    slash_ident = ModelIdentity(provider_id="compatible", model_id="meta-llama/Llama-3-8B@rev12")
    parsed_slash = ModelIdentity.from_serialized_id(slash_ident.to_serialized_id())
    assert parsed_slash == slash_ident
    assert parsed_slash.model_id == "meta-llama/Llama-3-8B@rev12"

    # 3. Model ID with spaces and Unicode
    unicode_ident = ModelIdentity(provider_id="llamacpp", model_id="日本語モデル:7b 高速版 v1.0")
    parsed_unicode = ModelIdentity.from_serialized_id(unicode_ident.to_serialized_id())
    assert parsed_unicode == unicode_ident
    assert parsed_unicode.model_id == "日本語モデル:7b 高速版 v1.0"

    # 4. Compact string parsing splits strictly on the first colon only (never unrestricted split(':'))
    compact_parsed = parse_model_identifier("ollama:llama3.2:3b")
    assert compact_parsed.provider_id == "ollama"
    assert compact_parsed.model_id == "llama3.2:3b"


# ==============================================================================
# 2. 3-Valued Logic Truth Table & Hard Requirements
# ==============================================================================
def test_02_tristate_bool_logic():
    """Verify 3-valued logic truth table: UNKNOWN cannot satisfy hard requirements."""
    t = TriStateBool.TRUE
    f = TriStateBool.FALSE
    u = TriStateBool.UNKNOWN

    assert TriStateBool.from_bool(True) == TriStateBool.TRUE
    assert TriStateBool.from_bool(False) == TriStateBool.FALSE
    assert TriStateBool.from_bool(None) == TriStateBool.UNKNOWN

    # UNKNOWN fails hard requirements (required=True)
    assert t.satisfies(required=True) is True
    assert f.satisfies(required=True) is False
    assert u.satisfies(required=True) is False

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

    sat, _ = caps.satisfies_requirement("reasoning", True)
    assert sat is True

    sat, reason = caps.satisfies_requirement("coding", True)
    assert sat is False
    assert "UNKNOWN" in reason
    assert "cannot satisfy hard requirement" in reason

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
    large_context = fresh_model_registry.query_eligible_models(
        ModelRequirements(min_input_tokens=500000)
    )
    lc_ids = [c.canonical_id for c in large_context]
    assert "gemini:gemini-2.5-flash" in lc_ids
    assert "gemini:gemini-2.5-pro" in lc_ids
    assert "openai:gpt-4o" not in lc_ids
    assert "anthropic:claude-3-5-sonnet-20241022" not in lc_ids

    high_output = fresh_model_registry.query_eligible_models(
        ModelRequirements(min_output_tokens=10000)
    )
    ho_ids = [c.canonical_id for c in high_output]
    assert "openai:gpt-4o" in ho_ids
    assert "openai:gpt-4o-mini" in ho_ids
    assert "anthropic:claude-3-5-sonnet-20241022" not in ho_ids


# ==============================================================================
# 5. Pricing Metadata & Absent Pricing Stays Unknown (Never Zero)
# ==============================================================================
def test_06_pricing_budget_filtering_and_absent_pricing_unknown(
    fresh_model_registry: ModelRegistry,
):
    """Verify price filtering and ensure missing pricing is UNKNOWN, never zero."""
    # Budget filter: max input $0.20 / million
    budget_models = fresh_model_registry.query_eligible_models(
        ModelRequirements(max_input_cost_per_million=0.20)
    )
    bm_ids = [c.canonical_id for c in budget_models]
    assert "openai:gpt-4o-mini" in bm_ids
    assert "gemini:gemini-2.5-flash" in bm_ids
    assert "deepseek:deepseek-chat" in bm_ids
    assert "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m" in bm_ids
    assert "openai:gpt-4o" not in bm_ids

    # Critical invariant: compatible:default has absent pricing; must NOT be treated as zero / free
    compat = fresh_model_registry.get_model("compatible:default")
    assert compat is not None
    assert compat.pricing.input_cost_per_million is None
    assert compat.pricing.output_cost_per_million is None

    # When budget constraint is set, missing price model is rejected with UNKNOWN reason
    eval_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(max_input_cost_per_million=1.00),
        eligible_only=False,
    )
    compat_candidate = next(c for c in eval_candidates if c.canonical_id == "compatible:default")
    assert compat_candidate.eligible is False
    assert any("UNKNOWN" in r for r in compat_candidate.rejection_reasons)


# ==============================================================================
# 6. Latency Separation: Catalog Baseline vs Live Observed Telemetry
# ==============================================================================
def test_07_latency_separation_and_telemetry(fresh_model_registry: ModelRegistry):
    """Verify static catalog latency class is preserved separately from live telemetry."""
    model = fresh_model_registry.get_model("openai:gpt-4o")
    assert model is not None
    assert model.latency.catalog_latency_class == LatencyClass.MEDIUM
    assert model.latency.catalog_latency_ms == 1200.0
    assert model.latency.observed_metrics is None

    # Inject observed telemetry
    updated = fresh_model_registry.update_telemetry("openai:gpt-4o", latency_ms=450.0)
    assert updated is True

    # Critical invariant: catalog latency class is NOT mutated to FAST!
    assert model.latency.catalog_latency_class == LatencyClass.MEDIUM
    assert model.latency.observed_metrics is not None
    assert model.latency.observed_metrics.last_observed_ms == 450.0
    assert model.latency.observed_metrics.sample_count == 1
    assert model.latency.effective_latency_ms == 450.0

    # Querying by catalog latency class respects the preserved catalog baseline
    candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(allowed_latency_classes=[LatencyClass.MEDIUM])
    )
    assert "openai:gpt-4o" in [c.canonical_id for c in candidates]


# ==============================================================================
# 7. Privacy Constraints & UNKNOWN Fails Strict Privacy
# ==============================================================================
def test_08_privacy_constraints_and_unknown_fails(fresh_model_registry: ModelRegistry):
    """Verify local-only, zero-egress, and zero-retention constraints; UNKNOWN fails strictly."""
    # 1. Require strictly local execution
    local_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(require_local_only=True)
    )
    assert len(local_candidates) > 0
    for c in local_candidates:
        assert c.model_definition.privacy.execution_location == ExecutionLocation.LOCAL
        assert c.model_definition.privacy.data_leaves_device == TriStateBool.FALSE

    l_ids = [c.canonical_id for c in local_candidates]
    assert "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m" in l_ids
    assert "openai:gpt-4o" not in l_ids

    # 2. Critical Invariant: compatible:default has UNKNOWN privacy and must FAIL require_local_only
    all_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(require_local_only=True),
        eligible_only=False,
    )
    compat = next(c for c in all_candidates if c.canonical_id == "compatible:default")
    assert compat.eligible is False
    assert any("unknown" in r.lower() for r in compat.rejection_reasons)

    # 3. Explicit ExecutionLocation Enum Verification
    from core.model_registry.models import ModelDefinition, ModelIdentity, PrivacyProfile

    # UNKNOWN execution location fails LOCAL-only
    unknown_model = ModelDefinition(
        identity=ModelIdentity(provider_id="custom", model_id="unknown-loc"),
        display_name="Unknown Loc",
        privacy=PrivacyProfile(
            execution_location=ExecutionLocation.UNKNOWN, data_leaves_device=TriStateBool.FALSE
        ),
    )
    fresh_model_registry.register_model(unknown_model)

    # REMOTE execution location fails LOCAL-only
    remote_model = ModelDefinition(
        identity=ModelIdentity(provider_id="custom", model_id="remote-loc"),
        display_name="Remote Loc",
        privacy=PrivacyProfile(
            execution_location=ExecutionLocation.REMOTE, data_leaves_device=TriStateBool.FALSE
        ),
    )
    fresh_model_registry.register_model(remote_model)

    # LOCAL execution location satisfies LOCAL-only
    local_model = ModelDefinition(
        identity=ModelIdentity(provider_id="custom", model_id="local-loc"),
        display_name="Local Loc",
        privacy=PrivacyProfile(
            execution_location=ExecutionLocation.LOCAL, data_leaves_device=TriStateBool.FALSE
        ),
    )
    fresh_model_registry.register_model(local_model)

    test_eval = {
        c.canonical_id: c
        for c in fresh_model_registry.query_eligible_models(
            ModelRequirements(require_local_only=True), eligible_only=False
        )
    }
    assert test_eval["custom:unknown-loc"].eligible is False
    assert any(
        "violates require_local_only" in r
        for r in test_eval["custom:unknown-loc"].rejection_reasons
    )

    assert test_eval["custom:remote-loc"].eligible is False
    assert any(
        "violates require_local_only" in r for r in test_eval["custom:remote-loc"].rejection_reasons
    )

    assert test_eval["custom:local-loc"].eligible is True


# ==============================================================================
# 8. Declarative Hardware Constraints
# ==============================================================================
def test_09_hardware_constraints(fresh_model_registry: ModelRegistry):
    """Verify local model hardware resource filtering."""
    low_ram_candidates = fresh_model_registry.query_eligible_models(
        ModelRequirements(
            require_local_only=True,
            max_available_ram_bytes=int(2.0 * 1024 * 1024 * 1024),
        )
    )
    lr_ids = [c.canonical_id for c in low_ram_candidates]
    assert "llamacpp:llama-3.2-1b-instruct-q4_k_m" in lr_ids
    assert "llamacpp:qwen2.5-coder-3b-instruct-q4_k_m" not in lr_ids


# ==============================================================================
# 9. Provenance Precedence & USER_OVERRIDE Visibility
# ==============================================================================
def test_10_provenance_precedence_and_user_override_visibility(
    fresh_model_registry: ModelRegistry,
):
    """Verify USER_OVERRIDE remains visible and cannot downgrade authoritative cloud privacy."""
    cid = "openai:gpt-4o"
    orig = fresh_model_registry.get_model(cid)
    assert orig is not None
    assert orig.provenance == ProvenanceType.BUILTIN

    # 1. Higher precedence REMOTE_DISCOVERY succeeds
    discovered_model = orig.model_copy(deep=True)
    discovered_model.provenance = ProvenanceType.REMOTE_DISCOVERY
    discovered_model.display_name = "GPT-4o (Discovered)"
    assert fresh_model_registry.register_model(discovered_model) is True

    # 2. User override records exact provenance without becoming provider-certified
    user_override = orig.model_copy(deep=True)
    user_override.provenance = ProvenanceType.USER_OVERRIDE
    user_override.display_name = "My Custom GPT-4o"
    user_override.capabilities.set_fact("tools", TriStateBool.TRUE, ProvenanceType.USER_OVERRIDE)
    assert fresh_model_registry.register_model(user_override) is True

    updated = fresh_model_registry.get_model(cid)
    assert updated.display_name == "My Custom GPT-4o"
    # Fact source explicitly retains USER_OVERRIDE
    fact = updated.capabilities.get_fact("tools")
    assert fact.value == TriStateBool.TRUE
    assert fact.source == ProvenanceType.USER_OVERRIDE
    assert fact.verified is False

    # 3. Security invariant: user override cannot convert authoritative cloud data_leaves_device=TRUE to FALSE
    hostile_override = updated.model_copy(deep=True)
    hostile_override.provenance = ProvenanceType.USER_OVERRIDE
    hostile_override.privacy.data_leaves_device = TriStateBool.FALSE
    with pytest.raises(ValueError, match="cannot convert authoritative data_leaves_device=TRUE"):
        fresh_model_registry.register_model(hostile_override)


# ==============================================================================
# 10. Restricted Access to Precedence Force (Untrusted Discovery Cannot Invoke)
# ==============================================================================
def test_11_untrusted_discovery_cannot_invoke_force(fresh_model_registry: ModelRegistry):
    """Verify force=True is strictly forbidden for untrusted discovery and ordinary callers."""
    cid = "openai:gpt-4o"
    orig = fresh_model_registry.get_model(cid)
    assert orig is not None

    lower_model = orig.model_copy(deep=True)
    lower_model.provenance = ProvenanceType.BUILTIN
    lower_model.display_name = "Hostile Builtin Overwrite"

    # Ordinary caller cannot pass force=True
    with pytest.raises(PermissionError, match="cannot invoke precedence-force"):
        fresh_model_registry.register_model(lower_model, force=True, caller_role=None)

    # Discovery adapter cannot pass force=True
    with pytest.raises(PermissionError, match="cannot invoke precedence-force"):
        fresh_model_registry.register_model(lower_model, force=True, caller_role="discovery")

    # Only admin / trusted_internal can pass force=True
    assert fresh_model_registry.register_model(lower_model, force=True, caller_role="admin") is True
    assert fresh_model_registry.get_model(cid).display_name == "Hostile Builtin Overwrite"


# ==============================================================================
# 11. Field-Level Provenance Merging (Sparse Discovery & FALSE vs UNKNOWN)
# ==============================================================================
def test_12_field_level_provenance_merge_sparse_and_false_vs_unknown(
    fresh_model_registry: ModelRegistry,
):
    """Verify sparse higher-precedence records do not erase known facts; FALSE overrides TRUE while UNKNOWN does not."""
    # Setup test model with rich builtin metadata
    test_model = ModelDefinition(
        provider_id="openai",
        model_id="test-merge-model",
        display_name="Test Merge Model",
        capabilities=ModelCapabilities(
            reasoning=TriStateBool.TRUE,
            coding=TriStateBool.TRUE,
            vision=TriStateBool.TRUE,
            tools=TriStateBool.TRUE,
        ),
        max_input_tokens=128000,
        max_total_context_tokens=128000,
        provenance=ProvenanceType.BUILTIN,
    )
    fresh_model_registry.register_model(test_model)

    # 1. Sparse REMOTE_DISCOVERY (precedence 2 > 1) with only coding=FALSE and tools=UNKNOWN
    sparse_discovery = ModelDefinition(
        provider_id="openai",
        model_id="test-merge-model",
        display_name="Test Merge Model (Discovered)",
        capabilities=ModelCapabilities(
            reasoning=TriStateBool.UNKNOWN,
            coding=TriStateBool.FALSE,  # Authoritative negative fact
            vision=TriStateBool.UNKNOWN,  # Sparse unknown
            tools=TriStateBool.UNKNOWN,  # Sparse unknown
        ),
        max_input_tokens=None,  # Sparse unknown
        provenance=ProvenanceType.REMOTE_DISCOVERY,
    )
    assert fresh_model_registry.register_model(sparse_discovery) is True

    merged = fresh_model_registry.get_model("openai:test-merge-model")
    assert merged is not None
    # coding was explicitly FALSE in discovery -> overridden to FALSE
    assert merged.capabilities.coding == TriStateBool.FALSE
    # reasoning was UNKNOWN in discovery -> preserved TRUE from BUILTIN!
    assert merged.capabilities.reasoning == TriStateBool.TRUE
    # vision was UNKNOWN in discovery -> preserved TRUE from BUILTIN!
    assert merged.capabilities.vision == TriStateBool.TRUE
    # max_input_tokens was None in discovery -> preserved 128000 from BUILTIN!
    assert merged.max_input_tokens == 128000


# ==============================================================================
# 12. Generic 'compatible' Provider Conservative Defaults
# ==============================================================================
def test_13_compatible_provider_conservative_defaults(fresh_model_registry: ModelRegistry):
    """Verify generic compatible provider defaults unsupported facts conservatively to UNKNOWN."""
    compat = fresh_model_registry.get_model("compatible:default")
    assert compat is not None
    assert compat.capabilities.reasoning == TriStateBool.UNKNOWN
    assert compat.capabilities.coding == TriStateBool.UNKNOWN
    assert compat.capabilities.vision == TriStateBool.UNKNOWN
    assert compat.capabilities.tools == TriStateBool.UNKNOWN
    assert compat.capabilities.structured_output == TriStateBool.UNKNOWN
    assert compat.capabilities.embeddings == TriStateBool.UNKNOWN
    assert compat.capabilities.streaming == TriStateBool.UNKNOWN
    assert compat.privacy.execution_location == ExecutionLocation.UNKNOWN
    assert compat.privacy.data_leaves_device == TriStateBool.UNKNOWN
    assert compat.pricing.input_cost_per_million is None


# ==============================================================================
# 13. Candidate Score Semantics (No Premature Winner Ranking)
# ==============================================================================
def test_14_candidate_score_no_winner_ranking(fresh_model_registry: ModelRegistry):
    """Verify candidate score represents deterministic metadata completeness, not winner ranking."""
    candidates = fresh_model_registry.query_eligible_models(ModelRequirements(require_coding=True))
    assert len(candidates) > 0
    # Scores are completeness ratios in [0.0, 1.0]
    for c in candidates:
        assert 0.0 <= c.score <= 1.0

    # Candidates are returned in alphabetical canonical order among eligible models
    c_ids = [c.canonical_id for c in candidates]
    assert c_ids == sorted(c_ids)


# ==============================================================================
# 14. Concurrency Safety
# ==============================================================================
def test_15_concurrent_queries_and_registrations(fresh_model_registry: ModelRegistry):
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
                fresh_model_registry.register_model(m, force=True, caller_role="admin")
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
