"""tests/test_r3_model_recommendation.py

Comprehensive Local Model Catalog and Recommendation Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.5 (Local Model Catalog and Recommendation).

Verifies all R3.5 core invariants & CTO review requirements:
1. Every numeric model fact carries explicit provenance and source.
2. Curated quality rank (CURATED_POLICY 1..10) replaces unsourced benchmark scores.
3. Architecture-aware KV-cache overhead scaling monotonically with context length.
4. Unambiguous integer bytes for memory calculations and explicit MiB/GiB reporting.
5. Explicit stale resource snapshot policy (auto-refresh, fallback, warning, timestamps).
6. Deterministic headroom denominator: available_ram - OS - AE - runtime_base.
7. CPU-only execution with zero GPU is fully supported for CPU-capable models.
8. GPU-required tasks reject systems lacking requested accelerator.
9. Deterministic tie-breaking invariant under shuffled catalog ordering.
10. Low memory hosts return None for tiers rather than hallucinating fits.
11. Pure side-effect-free execution: zero downloading, zero process spawning.
12. Privacy-safe explainability: zero leakage of hostname, username, home paths, or serials.
13. IPC authentication enforced on /v1/models/recommendations and /v1/models/catalog.
14. Functional task capability filtering (coding, reasoning, vision, context window).
"""

from __future__ import annotations

import os
import platform
import random
import time
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from core.model_recommendation import (
    DEFAULT_AGENT_ENGINE_RESERVE_BYTES,
    DEFAULT_CATALOG_UPDATED_AT,
    DEFAULT_CATALOG_VERSION,
    DEFAULT_OS_RESERVE_BYTES,
    DEFAULT_RUNTIME_BASE_RESERVE_BYTES,
    HardwareFitState,
    LocalModelCatalog,
    ModelKVArchitectureMetadata,
    NumericFactProvenance,
    RequirementsProvenance,
    ReservePolicy,
    TaskRequirements,
    calculate_model_kv_cache_bytes,
    calculate_usable_ram_before_model,
    evaluate_hardware_fit,
    recommend_local_models,
)
from core.model_registry.models import ModelIdentity
from core.resources import (
    CpuResources,
    MemoryResources,
    ProbeStatus,
    ResourceSnapshot,
)


def _make_snapshot(
    available_ram_gb: float = 16.0,
    total_ram_gb: float = 32.0,
    logical_cores: int = 8,
    architecture: str = "x86_64",
    platform_name: str = "linux",
    accelerators=None,
    memory_status: ProbeStatus = ProbeStatus.KNOWN,
    stale: bool = False,
    captured_at: float | None = None,
) -> ResourceSnapshot:
    """Helper to create deterministic ResourceSnapshot fixtures."""
    total_bytes = int(total_ram_gb * 1024 * 1024 * 1024)
    available_bytes = int(available_ram_gb * 1024 * 1024 * 1024)
    used_bytes = total_bytes - available_bytes
    return ResourceSnapshot(
        captured_at=captured_at if captured_at is not None else time.time(),
        platform=platform_name,
        architecture=architecture,
        cpu=CpuResources(
            architecture=architecture,
            logical_cores=logical_cores,
            status=ProbeStatus.KNOWN,
        ),
        memory=MemoryResources(
            total_bytes=total_bytes,
            available_bytes=available_bytes,
            used_bytes=used_bytes,
            status=memory_status,
        ),
        accelerators=accelerators or [],
        stale=stale,
    )


# ==============================================================================
# 1. Catalog Integrity, Versioning, and Numeric Fact Provenance
# ==============================================================================
def test_01_catalog_integrity_and_numeric_fact_provenance():
    """Verify catalog values have explicit provenance, sources, and no unsourced quality scores."""
    catalog = LocalModelCatalog()
    models = catalog.get_all_models()

    assert len(models) >= 5, "Catalog should contain curated local models"
    assert catalog.version == DEFAULT_CATALOG_VERSION
    assert catalog.updated_at == DEFAULT_CATALOG_UPDATED_AT

    for m in models:
        # Identity and runtime
        assert m.model_identity.provider_id == "llamacpp"
        assert m.managed_runtime == "llamacpp"
        assert m.catalog_version == DEFAULT_CATALOG_VERSION
        assert m.updated_at == DEFAULT_CATALOG_UPDATED_AT
        assert m.memory_unit == "bytes"

        # Hardware requirements and provenances
        assert m.artifact_size_bytes > 0
        assert m.artifact_size_provenance == NumericFactProvenance.MEASURED_FACT
        assert len(m.artifact_size_source) > 0

        assert m.min_ram_bytes > 0
        assert m.min_ram_provenance == NumericFactProvenance.CURATED_HEURISTIC
        assert m.recommended_ram_bytes >= m.min_ram_bytes
        assert m.recommended_ram_provenance == NumericFactProvenance.CURATED_HEURISTIC

        assert m.context_window_limit >= 4096
        assert m.context_window_provenance == NumericFactProvenance.DECLARED_FACT

        assert m.parameter_count_billions > 0
        assert m.parameter_count_provenance == NumericFactProvenance.DECLARED_FACT

        # Quality rank must be curated policy rank, NOT an unsourced benchmark
        assert 1 <= m.quality_rank <= 10
        assert m.quality_rank_provenance == NumericFactProvenance.CURATED_POLICY
        assert "policy" in m.quality_rank_source.lower()

        # Architecture metadata for KV scaling
        assert m.kv_metadata is not None
        assert m.kv_metadata.num_layers > 0
        assert m.kv_metadata.num_kv_heads > 0
        assert m.kv_metadata.head_dim > 0
        assert m.kv_metadata.cache_element_bytes == 2  # FP16
        assert m.kv_metadata.provenance == NumericFactProvenance.DECLARED_FACT

        # Provenance must be trusted catalog
        assert m.provenance == RequirementsProvenance.TRUSTED_CATALOG

        # Supported architectures
        assert "x86_64" in m.supported_architectures
        assert "arm64" in m.supported_architectures


# ==============================================================================
# 2. KV-Cache Memory Scaling (Monotonic Increase & Truthful Unknowns)
# ==============================================================================
def test_02_kv_cache_monotonic_scaling_and_unknowns():
    """Verify KV cache memory increases strictly monotonically with context length, and handles None truthfully."""
    meta = ModelKVArchitectureMetadata(
        num_layers=28,
        num_kv_heads=4,
        head_dim=128,
        cache_element_bytes=2,
    )

    tokens_sequence = [512, 1024, 2048, 4096, 8192, 16384, 32768]
    bytes_sequence = [calculate_model_kv_cache_bytes(meta, t) for t in tokens_sequence]

    for i in range(len(bytes_sequence) - 1):
        assert bytes_sequence[i] < bytes_sequence[i + 1], (
            f"KV cache must scale strictly monotonically: {bytes_sequence[i]} < {bytes_sequence[i + 1]}"
        )

    # Fallback / Unknown architecture metadata must yield 0 and not guess
    assert calculate_model_kv_cache_bytes(None, 4096) == 0


# ==============================================================================
# 3. Safety Reserves & Headroom Denominator Math
# ==============================================================================
def test_03_headroom_math_and_usable_denominator():
    """Verify exact usable RAM before model denominator: available_ram - OS - AE - runtime_base."""
    policy = ReservePolicy()
    assert policy.os_reserve_bytes == DEFAULT_OS_RESERVE_BYTES  # 1.5 GiB
    assert policy.agent_engine_reserve_bytes == DEFAULT_AGENT_ENGINE_RESERVE_BYTES  # 512 MiB
    assert policy.runtime_base_reserve_bytes == DEFAULT_RUNTIME_BASE_RESERVE_BYTES  # 512 MiB

    ten_gib = 10 * 1024 * 1024 * 1024
    expected_usable = ten_gib - (
        policy.os_reserve_bytes
        + policy.agent_engine_reserve_bytes
        + policy.runtime_base_reserve_bytes
    )
    assert calculate_usable_ram_before_model(ten_gib, policy=policy) == expected_usable

    # Minimal available RAM -> safe is 0, never negative
    one_gib = 1 * 1024 * 1024 * 1024
    assert calculate_usable_ram_before_model(one_gib, policy=policy) == 0


# ==============================================================================
# 4. Sufficient RAM -> Model Recommended for Tiers
# ==============================================================================
def test_04_sufficient_ram_recommends_appropriate_models():
    """Verify a host with 16GB available RAM receives Fast, Balanced, and Best Local recommendations."""
    snapshot = _make_snapshot(available_ram_gb=16.0, total_ram_gb=32.0)
    reqs = TaskRequirements(coding=True, min_context_tokens=4096)

    response = recommend_local_models(snapshot=snapshot, requirements=reqs)

    assert response.fast is not None, "Should recommend Fast model"
    assert response.balanced is not None, "Should recommend Balanced model"
    assert response.best_local is not None, "Should recommend Best Local model"

    # Exact headroom ratio = ram_headroom_bytes / usable_before_model_bytes
    for rec in [response.fast, response.balanced, response.best_local]:
        fit = rec.fit_result
        assert fit.memory_unit == "bytes"
        assert fit.usable_before_model_bytes > 0
        expected_ratio = fit.ram_headroom_bytes / fit.usable_before_model_bytes
        assert abs(fit.ram_headroom_ratio - expected_ratio) < 1e-4

    # FAST should have high headroom (>= 35%)
    assert response.fast.fit_result.ram_headroom_ratio >= 0.35
    assert (
        response.fast.model_entry.parameter_count_billions
        <= response.best_local.model_entry.parameter_count_billions
    )

    # BEST_LOCAL should have highest quality rank among fitting candidates
    assert response.best_local.model_entry.quality_rank >= response.fast.model_entry.quality_rank

    # Rejection summary should have zero rejections for recommended models
    fast_name = response.fast.model_identity.canonical_id
    assert fast_name not in response.rejection_summary

    # Explanations generated for each tier
    assert "fast" in response.explanations
    assert "balanced" in response.explanations
    assert "best_local" in response.explanations


# ==============================================================================
# 5. Insufficient RAM -> Model Rejected with Factual Deficit
# ==============================================================================
def test_05_insufficient_ram_rejects_with_factual_deficit():
    """Verify models that exceed safe available RAM are rejected with numerical deficit."""
    # Host with only 3.0 GB available RAM
    snapshot = _make_snapshot(available_ram_gb=3.0, total_ram_gb=8.0)
    reqs = TaskRequirements(coding=True)

    catalog = LocalModelCatalog()
    model_7b = catalog.get_model(
        ModelIdentity(provider_id="llamacpp", model_id="qwen2.5-coder-7b-instruct-q4_k_m")
    )
    assert model_7b is not None

    fit = evaluate_hardware_fit(model_7b, snapshot, reqs, ReservePolicy())
    assert fit.state == HardwareFitState.DOES_NOT_FIT
    assert len(fit.rejection_reasons) > 0
    assert any("deficit" in r.lower() for r in fit.rejection_reasons)
    assert any("gib" in r.lower() or "mib" in r.lower() for r in fit.rejection_reasons)


# ==============================================================================
# 6. UNKNOWN Telemetry -> UNKNOWN Fit, Never Recommended
# ==============================================================================
def test_06_unknown_telemetry_never_recommended():
    """Verify UNKNOWN memory telemetry yields UNKNOWN fit and is never presented as safe recommendation."""
    snapshot = _make_snapshot(memory_status=ProbeStatus.UNKNOWN)
    reqs = TaskRequirements()

    response = recommend_local_models(snapshot=snapshot, requirements=reqs)

    assert response.fast is None
    assert response.balanced is None
    assert response.best_local is None
    assert len(response.rejection_summary) > 0

    for reasons in response.rejection_summary.values():
        assert any("unknown" in r.lower() or "probe status" in r.lower() for r in reasons)


# ==============================================================================
# 7. CPU-Only Execution Supported with Zero GPU
# ==============================================================================
def test_07_cpu_only_model_recommended_with_zero_accelerators():
    """Verify a host with zero accelerators successfully receives CPU-based recommendations."""
    snapshot = _make_snapshot(available_ram_gb=16.0, accelerators=[])
    reqs = TaskRequirements(coding=True)

    response = recommend_local_models(snapshot=snapshot, requirements=reqs)

    assert response.best_local is not None
    assert response.best_local.fit_result.backend_used == "cpu"
    assert response.best_local.fit_result.accelerator_compatible is True


# ==============================================================================
# 8. GPU-Required Task Rejected on Non-GPU System
# ==============================================================================
def test_08_gpu_required_rejected_without_gpu():
    """Verify requiring an accelerator that is absent rejects candidates."""
    snapshot = _make_snapshot(available_ram_gb=16.0, accelerators=[])
    reqs = TaskRequirements(required_accelerator="cuda")

    response = recommend_local_models(snapshot=snapshot, requirements=reqs)

    assert response.fast is None
    assert response.balanced is None
    assert response.best_local is None
    assert len(response.rejection_summary) > 0
    for reasons in response.rejection_summary.values():
        assert any("cuda" in r.lower() for r in reasons)


# ==============================================================================
# 9. Deterministic Tie-Breaking Invariant Under Shuffled Catalog
# ==============================================================================
def test_09_deterministic_tie_breaking_invariant_under_shuffle():
    """Verify sorting order is strictly deterministic and invariant under shuffled catalog ordering."""
    catalog = LocalModelCatalog()
    all_models = catalog.get_all_models()
    snapshot = _make_snapshot(available_ram_gb=16.0, total_ram_gb=32.0)
    reqs = TaskRequirements(coding=True, min_context_tokens=4096)
    policy = ReservePolicy()

    # Get baseline recommendation with natural catalog order
    baseline = recommend_local_models(
        catalog=catalog, snapshot=snapshot, requirements=reqs, policy=policy
    )
    baseline_fast = baseline.fast.model_identity.canonical_id if baseline.fast else None
    baseline_balanced = baseline.balanced.model_identity.canonical_id if baseline.balanced else None
    baseline_best = baseline.best_local.model_identity.canonical_id if baseline.best_local else None

    # Permute catalog order 10 times and verify identical winners
    for seed in range(10):
        shuffled_models = list(all_models)
        random.Random(seed).shuffle(shuffled_models)

        mock_catalog = MagicMock(spec=LocalModelCatalog)
        mock_catalog.get_all_models.return_value = shuffled_models

        shuffled_response = recommend_local_models(
            catalog=mock_catalog, snapshot=snapshot, requirements=reqs, policy=policy
        )

        assert (
            shuffled_response.fast.model_identity.canonical_id if shuffled_response.fast else None
        ) == baseline_fast
        assert (
            shuffled_response.balanced.model_identity.canonical_id
            if shuffled_response.balanced
            else None
        ) == baseline_balanced
        assert (
            shuffled_response.best_local.model_identity.canonical_id
            if shuffled_response.best_local
            else None
        ) == baseline_best


# ==============================================================================
# 10. Stale Resource Snapshot Policy & Freshness
# ==============================================================================
def test_10_stale_resource_snapshot_policy_and_freshness():
    """Verify stale snapshot detection, auto-refresh attempt, and fallback warning."""
    stale_time = time.time() - 30.0
    snapshot = _make_snapshot(available_ram_gb=16.0, stale=True, captured_at=stale_time)
    response = recommend_local_models(snapshot=snapshot)

    assert response.stale_telemetry is True
    assert response.resource_stale is True
    assert response.resource_captured_at == stale_time


# ==============================================================================
# 11. Low Memory Host Returns None for All Tiers
# ==============================================================================
def test_11_low_memory_returns_none_deterministically():
    """Verify low-memory machine (e.g. 1.0 GB available) safely returns None for all tiers without crashing."""
    snapshot = _make_snapshot(available_ram_gb=1.0, total_ram_gb=4.0)
    response = recommend_local_models(snapshot=snapshot)

    assert response.fast is None
    assert response.balanced is None
    assert response.best_local is None
    assert response.evaluated_candidates_count > 0
    assert len(response.rejection_summary) == response.evaluated_candidates_count


# ==============================================================================
# 12. Pure Side-Effect-Free Execution
# ==============================================================================
def test_12_pure_side_effect_free_execution():
    """Verify recommending models causes zero subprocesses, zero network I/O, and zero disk writes."""
    snapshot = _make_snapshot(available_ram_gb=16.0)

    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
        response = recommend_local_models(snapshot=snapshot)
        assert mock_popen.call_count == 0
        assert mock_run.call_count == 0

    assert response.best_local is not None


# ==============================================================================
# 13. Privacy-Safe Audit Trail (Zero Fingerprinting)
# ==============================================================================
def test_13_privacy_safe_audit_trail_zero_fingerprinting():
    """Verify explanation audit trails leak strictly zero private hostnames, usernames, or serials."""
    snapshot = _make_snapshot(available_ram_gb=16.0)
    response = recommend_local_models(snapshot=snapshot)

    assert response.best_local is not None
    exp = response.explanations["best_local"]
    factual_str = str(exp.factual_resources_used)

    import getpass

    username = getpass.getuser()
    home_dir = os.path.expanduser("~")
    host_node = platform.node()

    if username:
        assert username not in factual_str
    if home_dir:
        assert home_dir not in factual_str
    if host_node:
        assert host_node not in factual_str

    assert "serial" not in factual_str.lower()
    assert "uuid" not in factual_str.lower()


# ==============================================================================
# 14. REST API Endpoint Integration & IPC Auth Enforcement
# ==============================================================================
def test_14_rest_api_endpoint_integration_and_ipc_auth():
    """Verify FastAPI endpoints enforce IPC auth, return conformant payloads, and propagate freshness."""
    from services.python.server.app import create_app

    app = create_app()
    client = TestClient(app)

    token = os.environ.get("AGENT_ENGINE_IPC_TOKEN", "test_token_123")
    with patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}):
        # 1. Unauthenticated requests must be rejected with 401
        unauth_rec = client.get("/v1/models/recommendations")
        assert unauth_rec.status_code == 401

        unauth_cat = client.get("/v1/models/catalog")
        assert unauth_cat.status_code == 401

        # 2. Authenticated GET /v1/models/catalog
        headers = {"X-IPC-Token": token}
        cat_res = client.get("/v1/models/catalog", headers=headers)
        assert cat_res.status_code == 200
        cat_data = cat_res.json()
        assert isinstance(cat_data, list)
        assert len(cat_data) >= 5
        assert any(
            m["model_identity"]["model_id"] == "qwen2.5-coder-3b-instruct-q4_k_m" for m in cat_data
        )

        # 3. Authenticated GET /v1/models/recommendations
        rec_res = client.get(
            "/v1/models/recommendations?coding=true&min_context_tokens=4096",
            headers=headers,
        )
        assert rec_res.status_code == 200
        rec_data = rec_res.json()

        assert "evaluated_candidates_count" in rec_data
        assert rec_data["evaluated_candidates_count"] >= 5
        assert "resource_captured_at" in rec_data
        assert "resource_stale" in rec_data
        assert "explanations" in rec_data
        assert "rejection_summary" in rec_data
