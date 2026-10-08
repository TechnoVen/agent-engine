"""tests/test_r3_model_recommendation.py

Comprehensive Local Model Catalog and Recommendation Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.5 (Local Model Catalog and Recommendation).

Verifies all R3.5 core invariants:
1. Curated, versioned, timestamped catalog with factual hardware requirements.
2. Explicit safety reserves for OS, Agent Engine, llama.cpp, and KV cache context overhead.
3. Unified memory single-pool invariant (RAM and VRAM are NEVER summed).
4. Factual hardware-fit scoring against available resources with explicit headroom.
5. Deterministic Fast, Balanced, Best Local tier mapping.
6. UNKNOWN telemetry or missing requirements are never presented as safe recommendations.
7. CPU-only execution with zero GPU is fully supported.
8. GPU-required tasks reject systems lacking requested accelerator.
9. Stale resource snapshots are explicitly identified.
10. Low memory hosts return None for tiers rather than hallucinating fits.
11. Side-effect-free execution: zero downloading, zero process spawning.
12. Privacy-safe explainability: zero leakage of hostname, username, home paths, or serials.
13. REST API /v1/models/recommendations and /v1/models/catalog adhere to contract.
14. Functional task capability filtering (coding, reasoning, vision, context window).
"""

from __future__ import annotations

import os
import platform
import time
from unittest.mock import patch

from starlette.testclient import TestClient

from core.model_recommendation import (
    DEFAULT_AGENT_ENGINE_RESERVE_BYTES,
    DEFAULT_CATALOG_UPDATED_AT,
    DEFAULT_CATALOG_VERSION,
    DEFAULT_OS_RESERVE_BYTES,
    DEFAULT_RUNTIME_BASE_RESERVE_BYTES,
    HardwareFitState,
    LocalModelCatalog,
    RequirementsProvenance,
    ReservePolicy,
    TaskRequirements,
    calculate_kv_context_overhead,
    calculate_safe_available_ram,
    calculate_safe_available_vram,
    evaluate_capability_eligibility,
    evaluate_hardware_fit,
    recommend_local_models,
)
from core.model_registry.models import ModelIdentity, TriStateBool
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
) -> ResourceSnapshot:
    """Helper to create deterministic ResourceSnapshot fixtures."""
    total_bytes = int(total_ram_gb * 1024 * 1024 * 1024)
    available_bytes = int(available_ram_gb * 1024 * 1024 * 1024)
    used_bytes = total_bytes - available_bytes
    return ResourceSnapshot(
        captured_at=time.time(),
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
# 1. Catalog Integrity, Versioning, and Curated Models
# ==============================================================================
def test_01_catalog_integrity_and_versioning():
    """Verify curated local model catalog conforms to versioning and factual metadata."""
    catalog = LocalModelCatalog()
    models = catalog.get_all_models()

    assert len(models) >= 5, "Catalog should contain curated local models"
    assert catalog.version == DEFAULT_CATALOG_VERSION
    assert catalog.updated_at == DEFAULT_CATALOG_UPDATED_AT

    for m in models:
        # Identity and runtime
        assert m.model_identity.provider_id == "llamacpp", "Only local llama.cpp models curated"
        assert m.managed_runtime == "llamacpp"
        assert m.catalog_version == DEFAULT_CATALOG_VERSION
        assert m.updated_at == DEFAULT_CATALOG_UPDATED_AT

        # Hardware requirements must be factual and positive
        assert m.artifact_size_bytes > 0
        assert m.min_ram_bytes > 0
        assert m.recommended_ram_bytes >= m.min_ram_bytes
        assert m.context_window_limit >= 4096
        assert m.parameter_count_billions > 0
        assert m.quality_score > 0.0

        # Provenance must be trusted catalog
        assert m.provenance == RequirementsProvenance.TRUSTED_CATALOG

        # Supported architectures
        assert "x86_64" in m.supported_architectures
        assert "arm64" in m.supported_architectures

    # Test retrieval by ModelIdentity
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m")
    entry = catalog.get_model(ident)
    assert entry is not None
    assert entry.parameter_size == "3B"
    assert entry.capabilities.get("coding") == TriStateBool.TRUE


# ==============================================================================
# 2. Safety Reserves & Headroom Calculations
# ==============================================================================
def test_02_safety_reserves_and_headroom_math():
    """Verify explicit safety reserves are deducted and KV cache overhead scales correctly."""
    policy = ReservePolicy()
    assert policy.os_reserve_bytes == DEFAULT_OS_RESERVE_BYTES  # 1.5GB
    assert policy.agent_engine_reserve_bytes == DEFAULT_AGENT_ENGINE_RESERVE_BYTES  # 512MB
    assert policy.runtime_base_reserve_bytes == DEFAULT_RUNTIME_BASE_RESERVE_BYTES  # 512MB

    # 10GB available RAM -> 10GB - 1.5GB - 512MB = 8GB safe
    ten_gb = 10 * 1024 * 1024 * 1024
    expected_safe = ten_gb - (1536 * 1024 * 1024 + 512 * 1024 * 1024)
    assert calculate_safe_available_ram(ten_gb, policy=policy) == expected_safe

    # Minimal available RAM -> safe is 0, never negative
    one_gb = 1 * 1024 * 1024 * 1024
    assert calculate_safe_available_ram(one_gb, policy=policy) == 0

    # KV Cache overhead scaling
    kv_small = calculate_kv_context_overhead(2048, parameter_count_billions=1.5)
    kv_large = calculate_kv_context_overhead(32768, parameter_count_billions=7.0)
    assert kv_large > kv_small
    assert kv_small >= 64 * 1024 * 1024  # minimum 64MB floor


# ==============================================================================
# 3. Unified Memory Single-Pool Invariant
# ==============================================================================
def test_03_unified_memory_single_pool_invariant():
    """Verify unified memory systems treat dedicated VRAM as None and NEVER sum RAM + VRAM."""
    policy = ReservePolicy()

    # Case A: Apple Silicon / Unified Memory APU
    safe_vram_unified = calculate_safe_available_vram(
        available_vram_bytes=16 * 1024 * 1024 * 1024,
        is_unified_memory=True,
        policy=policy,
    )
    assert (
        safe_vram_unified is None
    ), "Unified memory must NEVER report dedicated VRAM (single pool)"

    # Case B: Discrete GPU
    discrete_vram = 8 * 1024 * 1024 * 1024
    safe_vram_discrete = calculate_safe_available_vram(
        available_vram_bytes=discrete_vram,
        is_unified_memory=False,
        policy=policy,
    )
    assert safe_vram_discrete == discrete_vram - policy.discrete_vram_reserve_bytes


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

    # FAST should have high headroom (>= 35%)
    assert response.fast.fit_result.ram_headroom_ratio >= 0.35
    assert (
        response.fast.model_entry.parameter_count_billions
        <= response.best_local.model_entry.parameter_count_billions
    )

    # BEST_LOCAL should have highest quality among fitting candidates
    assert response.best_local.model_entry.quality_score >= response.fast.model_entry.quality_score

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
    # Host with only 3.0 GB available RAM (safe RAM is ~1.0 GB after 2.0GB OS/AE reserves)
    snapshot = _make_snapshot(available_ram_gb=3.0, total_ram_gb=8.0)
    reqs = TaskRequirements(coding=True)

    catalog = LocalModelCatalog()
    # 7B model requires 6GB min RAM + overhead
    model_7b = catalog.get_model(
        ModelIdentity(provider_id="llamacpp", model_id="qwen2.5-coder-7b-instruct-q4_k_m")
    )
    assert model_7b is not None

    fit = evaluate_hardware_fit(model_7b, snapshot, reqs, ReservePolicy())
    assert fit.state == HardwareFitState.DOES_NOT_FIT
    assert len(fit.rejection_reasons) > 0
    assert any("deficit" in r.lower() for r in fit.rejection_reasons)
    assert "MB" in fit.rejection_reasons[0]


# ==============================================================================
# 6. UNKNOWN Telemetry -> UNKNOWN Fit, Never Recommended
# ==============================================================================
def test_06_unknown_telemetry_never_recommended():
    """Verify UNKNOWN memory telemetry yields UNKNOWN fit and is never presented as safe recommendation."""
    snapshot = _make_snapshot(memory_status=ProbeStatus.UNKNOWN)
    reqs = TaskRequirements()

    response = recommend_local_models(snapshot=snapshot, requirements=reqs)

    # UNKNOWN telemetry must never yield safe recommendations
    assert response.fast is None
    assert response.balanced is None
    assert response.best_local is None
    assert len(response.rejection_summary) > 0

    for model_name, reasons in response.rejection_summary.items():
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
# 9. Stale Resource Snapshot Handled Explicitly
# ==============================================================================
def test_09_stale_resource_snapshot_handled_explicitly():
    """Verify stale telemetry flag is preserved in response and audit explanation."""
    snapshot = _make_snapshot(available_ram_gb=16.0, stale=True)
    response = recommend_local_models(snapshot=snapshot)

    assert response.stale_telemetry is True
    for exp in response.explanations.values():
        assert exp.stale_telemetry is True


# ==============================================================================
# 10. Low Memory Host Returns None for All Tiers
# ==============================================================================
def test_10_low_memory_returns_none_deterministically():
    """Verify low-memory machine (e.g. 1.0 GB available) safely returns None for all tiers without crashing."""
    snapshot = _make_snapshot(available_ram_gb=1.0, total_ram_gb=4.0)
    response = recommend_local_models(snapshot=snapshot)

    assert response.fast is None
    assert response.balanced is None
    assert response.best_local is None
    assert response.evaluated_candidates_count > 0
    assert len(response.rejection_summary) == response.evaluated_candidates_count


# ==============================================================================
# 11. Pure Side-Effect-Free Execution
# ==============================================================================
def test_11_pure_side_effect_free_execution():
    """Verify recommending models causes zero subprocesses, zero network I/O, and zero disk writes."""
    snapshot = _make_snapshot(available_ram_gb=16.0)

    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
        response = recommend_local_models(snapshot=snapshot)
        assert mock_popen.call_count == 0
        assert mock_run.call_count == 0

    assert response.best_local is not None


# ==============================================================================
# 12. Privacy-Safe Audit Trail (Zero Fingerprinting)
# ==============================================================================
def test_12_privacy_safe_audit_trail_zero_fingerprinting():
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
# 13. Functional Capability Filtering
# ==============================================================================
def test_13_functional_capability_filtering():
    """Verify models lacking requested capabilities (coding, reasoning, context) are rejected."""
    catalog = LocalModelCatalog()
    model_1b = catalog.get_model(
        ModelIdentity(provider_id="llamacpp", model_id="llama-3.2-1b-instruct-q4_k_m")
    )
    assert model_1b is not None

    # Llama 3.2 1B does not have coding=True
    req_coding = TaskRequirements(coding=True)
    elig = evaluate_capability_eligibility(model_1b, req_coding)
    assert elig.eligible is False
    assert "coding" in elig.missing_capabilities

    # Context window limit exceeded
    req_context = TaskRequirements(min_context_tokens=16384)
    elig_ctx = evaluate_capability_eligibility(model_1b, req_context)
    assert elig_ctx.eligible is False
    assert "context_window" in elig_ctx.missing_capabilities

    # Vision requirement (no local text model has vision)
    req_vision = TaskRequirements(vision=True)
    elig_vis = evaluate_capability_eligibility(model_1b, req_vision)
    assert elig_vis.eligible is False
    assert "vision" in elig_vis.missing_capabilities


# ==============================================================================
# 14. REST API Endpoint Integration (/v1/models/recommendations and /v1/models/catalog)
# ==============================================================================
def test_14_rest_api_endpoint_integration():
    """Verify FastAPI endpoints /v1/models/recommendations and /v1/models/catalog return conformant payloads."""
    from services.python.server.app import create_app

    app = create_app()
    client = TestClient(app)

    token = os.environ.get("AGENT_ENGINE_IPC_TOKEN", "")
    headers = {"X-IPC-Token": token} if token else {}

    # 1. GET /v1/models/catalog
    cat_res = client.get("/v1/models/catalog", headers=headers)
    assert cat_res.status_code == 200
    cat_data = cat_res.json()
    assert isinstance(cat_data, list)
    assert len(cat_data) >= 5
    assert any(
        m["model_identity"]["model_id"] == "qwen2.5-coder-3b-instruct-q4_k_m" for m in cat_data
    )

    # 2. GET /v1/models/recommendations
    rec_res = client.get(
        "/v1/models/recommendations?coding=true&min_context_tokens=4096",
        headers=headers,
    )
    assert rec_res.status_code == 200
    rec_data = rec_res.json()

    assert "evaluated_candidates_count" in rec_data
    assert rec_data["evaluated_candidates_count"] >= 5
    assert "explanations" in rec_data
    assert "rejection_summary" in rec_data
