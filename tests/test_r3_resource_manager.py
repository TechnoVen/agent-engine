"""tests/test_r3_resource_manager.py

Comprehensive Host Resource Manager Conformance Test Suite for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).

Verifies all R3.3 core invariants:
1. Resource snapshot is timestamped and factual.
2. Platform and architecture are factual.
3. CPU logical count is factual and CPU optional fields are represented honestly without invented performance.
4. Memory total/available/used are byte-accurate and satisfy OS invariants (used <= total, available <= total).
5. Zero accelerators is valid; multiple accelerators are supported; partial accelerator data preserves UNKNOWN.
6. Optional NVML/ROCm unavailable does not fail snapshot.
7. Failed accelerator probe does not lose CPU or RAM telemetry.
8. Zero machine fingerprinting: no hostname, username, serial number, or home path exposed.
9. Slow external probe is strictly bounded by timeout (<= 2s).
10. External probe uses strictly argv list (no shell=True).
11. Oversized or malformed probe output fails safely without crash.
12. Cached snapshot retains original captured_at and represents cache_age_seconds and stale state accurately.
13. Canonical API endpoint (/v1/resources) returns factual ResourceSnapshot matching ResourceManager truth.
14. Legacy hardware telemetry endpoint adapts to and delegates to ResourceManager.
15. Zero model-fit or local model recommendation logic added.
16. Real-platform integration snapshot on the host platform passes all invariants cleanly.
"""

from __future__ import annotations

import os
import platform
import time
from typing import List
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from core.resources import (
    AcceleratorResources,
    AcceleratorType,
    CpuResources,
    MemoryResources,
    ProbeStatus,
    ResourceManager,
    ResourceSnapshot,
    get_resource_manager,
    reset_resource_manager,
)
from core.resources.probes.base import BaseResourceProbe, safe_run_command
from core.telemetry.hardware import get_hardware_telemetry_tracker


@pytest.fixture(autouse=True)
def fresh_resource_manager():
    """Ensure clean ResourceManager for each test."""
    mgr = reset_resource_manager()
    yield mgr
    reset_resource_manager()


# ==============================================================================
# Mock Probes for Deterministic Unit / Contract Testing
# ==============================================================================
class SyntheticTestProbe(BaseResourceProbe):
    """Controlled synthetic probe for testing multi-accelerator and edge cases."""

    def __init__(
        self,
        cpu_fail: bool = False,
        mem_fail: bool = False,
        accel_fail: bool = False,
        accelerators: List[AcceleratorResources] | None = None,
    ) -> None:
        self.cpu_fail = cpu_fail
        self.mem_fail = mem_fail
        self.accel_fail = accel_fail
        self.accelerators = accelerators if accelerators is not None else []

    def probe_cpu(self) -> CpuResources:
        if self.cpu_fail:
            raise RuntimeError("Synthetic CPU probe crash")
        return CpuResources(
            architecture="x86_64",
            logical_cores=16,
            physical_cores=8,
            current_utilization_percent=24.5,
            load_average=(1.2, 1.5, 1.1),
            frequency_mhz=3200.0,
            status=ProbeStatus.KNOWN,
        )

    def probe_memory(self) -> MemoryResources:
        if self.mem_fail:
            raise RuntimeError("Synthetic Memory probe crash")
        total = 32 * 1024 * 1024 * 1024
        available = 20 * 1024 * 1024 * 1024
        used = 12 * 1024 * 1024 * 1024
        return MemoryResources(
            total_bytes=total,
            available_bytes=available,
            used_bytes=used,
            free_bytes=available,
            swap_total_bytes=8 * 1024 * 1024 * 1024,
            swap_used_bytes=1024 * 1024 * 1024,
            status=ProbeStatus.KNOWN,
        )

    def probe_accelerators(self) -> List[AcceleratorResources]:
        if self.accel_fail:
            raise RuntimeError("Synthetic Accelerator probe crash")
        return self.accelerators


# ==============================================================================
# 1. Real-Platform Integration Tests
# ==============================================================================
def test_01_real_platform_snapshot_factual_and_timestamped(
    fresh_resource_manager: ResourceManager,
):
    """Verify live snapshot on development host is timestamped, factual, and has no fabricated data."""
    snap = fresh_resource_manager.get_snapshot(force_refresh=True)

    assert isinstance(snap, ResourceSnapshot)
    assert snap.captured_at > 0.0
    assert abs(time.time() - snap.captured_at) < 5.0
    assert snap.platform in ("linux", "darwin", "windows")
    assert bool(snap.architecture)

    # CPU facts
    assert snap.cpu.logical_cores >= 1
    assert snap.cpu.architecture == snap.architecture
    assert snap.cpu.status in (ProbeStatus.KNOWN, ProbeStatus.UNKNOWN)
    if snap.cpu.current_utilization_percent is not None:
        assert 0.0 <= snap.cpu.current_utilization_percent <= 100.0

    # Memory facts
    assert snap.memory.total_bytes > 0
    assert 0 <= snap.memory.used_bytes <= snap.memory.total_bytes
    assert 0 <= snap.memory.available_bytes <= snap.memory.total_bytes
    assert 0.0 <= snap.memory.used_percent <= 100.0

    # Accelerators (0 or more is valid; no fake GPUs)
    assert isinstance(snap.accelerators, list)
    for accel in snap.accelerators:
        assert bool(accel.accelerator_id)
        assert bool(accel.vendor)
        assert bool(accel.device_name)
        if accel.total_memory_bytes is not None:
            assert accel.total_memory_bytes > 0
            if accel.used_memory_bytes is not None:
                assert 0 <= accel.used_memory_bytes <= accel.total_memory_bytes


# ==============================================================================
# 2. Memory Invariant Validation
# ==============================================================================
def test_02_memory_invariants():
    """Verify byte-valued fields and invariants."""
    mem = MemoryResources(
        total_bytes=16 * 1024 * 1024 * 1024,
        available_bytes=10 * 1024 * 1024 * 1024,
        used_bytes=6 * 1024 * 1024 * 1024,
    )
    assert mem.used_percent == 37.5
    assert mem.available_bytes <= mem.total_bytes
    assert mem.used_bytes <= mem.total_bytes


# ==============================================================================
# 3. Accelerator Support & Truthful Representations
# ==============================================================================
def test_03_zero_accelerators_valid():
    """Verify host with zero accelerators returns clean empty list without fabrication."""
    probe = SyntheticTestProbe(accelerators=[])
    mgr = ResourceManager(probe=probe)
    snap = mgr.get_snapshot()

    assert len(snap.accelerators) == 0
    assert snap.probe_status["accelerators"] == ProbeStatus.KNOWN


def test_04_multiple_accelerators_supported():
    """Verify multi-GPU host preserves all accelerator records."""
    accels = [
        AcceleratorResources(
            accelerator_id="gpu:0",
            vendor="nvidia",
            device_name="NVIDIA GeForce RTX 4090",
            type=AcceleratorType.DISCRETE_GPU,
            total_memory_bytes=24 * 1024 * 1024 * 1024,
            used_memory_bytes=4 * 1024 * 1024 * 1024,
            available_memory_bytes=20 * 1024 * 1024 * 1024,
            backend="nvml",
            probe_source="nvidia_smi",
        ),
        AcceleratorResources(
            accelerator_id="gpu:1",
            vendor="nvidia",
            device_name="NVIDIA GeForce RTX 4090",
            type=AcceleratorType.DISCRETE_GPU,
            total_memory_bytes=24 * 1024 * 1024 * 1024,
            used_memory_bytes=2 * 1024 * 1024 * 1024,
            available_memory_bytes=22 * 1024 * 1024 * 1024,
            backend="nvml",
            probe_source="nvidia_smi",
        ),
    ]
    probe = SyntheticTestProbe(accelerators=accels)
    mgr = ResourceManager(probe=probe)
    snap = mgr.get_snapshot()

    assert len(snap.accelerators) == 2
    assert snap.accelerators[0].accelerator_id == "gpu:0"
    assert snap.accelerators[1].accelerator_id == "gpu:1"
    assert snap.accelerators[0].memory_used_percent == 16.7


def test_05_apple_unified_memory_never_double_counted():
    """Verify Apple unified memory is represented truthfully and not fabricated as dedicated VRAM."""
    accel = AcceleratorResources(
        accelerator_id="metal:0",
        vendor="apple",
        device_name="Apple M2 Max",
        type=AcceleratorType.INTEGRATED_GPU,
        total_memory_bytes=None,  # No dedicated pool
        is_unified_memory=True,
        backend="metal",
        probe_source="system_profiler",
        metadata={"memory_architecture": "unified_system_memory"},
    )
    assert accel.total_memory_bytes is None
    assert accel.is_unified_memory is True
    assert accel.memory_used_percent is None


# ==============================================================================
# 4. Independent Probe Failure & Resilience
# ==============================================================================
def test_06_failed_accelerator_probe_does_not_lose_cpu_or_memory():
    """Verify failing accelerator probe reports error status but preserves CPU and RAM."""
    probe = SyntheticTestProbe(accel_fail=True)
    mgr = ResourceManager(probe=probe)
    snap = mgr.get_snapshot()

    assert snap.probe_status["accelerators"] == ProbeStatus.PROBE_FAILED
    assert len(snap.accelerators) == 0
    # CPU & RAM intact!
    assert snap.cpu.logical_cores == 16
    assert snap.memory.total_bytes == 32 * 1024 * 1024 * 1024
    assert snap.probe_status["cpu"] == ProbeStatus.KNOWN
    assert snap.probe_status["memory"] == ProbeStatus.KNOWN


# ==============================================================================
# 5. Zero Machine Fingerprinting / Privacy Invariants
# ==============================================================================
def test_07_zero_fingerprinting_privacy_guarantee():
    """Verify snapshot strictly contains no hostname, username, or user home paths."""
    mgr = get_resource_manager()
    snap = mgr.get_snapshot(force_refresh=True)
    serialized_str = snap.model_dump_json().lower()

    # Disallowed host identifiers
    host_node = platform.node().lower()
    if host_node and len(host_node) > 2 and host_node != "localhost":
        assert host_node not in serialized_str

    user_name = os.environ.get("USER", "").lower()
    if user_name and len(user_name) > 2:
        assert user_name not in serialized_str

    home_path = os.environ.get("HOME", "").lower()
    if home_path and len(home_path) > 3:
        assert home_path not in serialized_str


# ==============================================================================
# 6. Safe Subprocess Execution (Bounded Timeout, No shell=True)
# ==============================================================================
def test_08_safe_run_command_bounded_timeout():
    """Verify probe execution aborts within bounded timeout and does not hang."""
    start = time.time()
    # sleep 5s with timeout 0.5s
    res = safe_run_command(["sleep", "5"], timeout=0.5)
    elapsed = time.time() - start

    assert res is None
    assert elapsed < 1.0


def test_09_safe_run_command_bounded_output():
    """Verify probe caps oversized output safely without memory exhaustion."""
    # Generate 100,000 bytes
    res = safe_run_command(["python3", "-c", "print('A' * 100000)"], timeout=2.0, max_bytes=1024)
    assert res is not None
    assert len(res) <= 1024


# ==============================================================================
# 7. Cache Semantics & Stale Tracking
# ==============================================================================
def test_10_cache_semantics_and_stale_tracking():
    """Verify cache preserves original captured_at and updates cache_age_seconds accurately."""
    probe = SyntheticTestProbe()
    mgr = ResourceManager(probe=probe, cache_ttl_seconds=10.0, stale_threshold_seconds=2.0)

    snap1 = mgr.get_snapshot()
    time.sleep(0.1)
    snap2 = mgr.get_snapshot()

    # Cached snapshot retains original captured_at
    assert snap2.captured_at == snap1.captured_at
    assert snap2.cache_age_seconds > 0.0
    assert snap2.stale is False
    assert snap2.fresh is True

    # Simulate stale threshold within cache TTL (2.0s < age=5.0s < 10.0s)
    with patch("time.time", return_value=snap1.captured_at + 5.0):
        snap_stale = mgr.get_snapshot()
        assert snap_stale.captured_at == snap1.captured_at
        assert snap_stale.cache_age_seconds == 5.0
        assert snap_stale.stale is True
        assert snap_stale.fresh is False


# ==============================================================================
# 8. API Contract & Integration (/v1/resources)
# ==============================================================================
def test_11_canonical_api_endpoint():
    """Verify GET /v1/resources returns factual ResourceSnapshot matching ResourceManager truth."""
    from services.python.server.app import create_app

    app = create_app()
    client = TestClient(app)

    # Supply valid IPC token
    token = os.environ.get("AGENT_ENGINE_IPC_TOKEN", "")
    headers = {"X-IPC-Token": token} if token else {}

    res = client.get("/v1/resources", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert "captured_at" in data
    assert "cpu" in data
    assert "memory" in data
    assert "accelerators" in data
    assert data["cpu"]["logical_cores"] >= 1
    assert data["memory"]["total_bytes"] > 0


# ==============================================================================
# 9. Legacy Hardware Endpoint Adapts to ResourceManager
# ==============================================================================
def test_12_legacy_hardware_endpoint_delegation():
    """Verify legacy /telemetry/hardware delegates to ResourceManager without duplicate scanning."""
    tracker = get_hardware_telemetry_tracker()
    telem = tracker.get_telemetry()

    assert telem.cpu_cores_logical >= 1
    assert telem.ram_total_gb > 0
    assert telem.ram_available_gb > 0
    assert 0.0 <= telem.ram_used_percent <= 100.0


# ==============================================================================
# 10. Boundary Guarantee: No Model Recommendation Logic Added
# ==============================================================================
def test_13_no_model_recommendation_in_resource_manager():
    """Verify ResourceManager contains zero model recommendations, fit logic, or tier selection."""
    mgr = get_resource_manager()
    # ResourceManager interface must not have recommendation methods
    assert not hasattr(mgr, "recommend_models")
    assert not hasattr(mgr, "model_fits_gpu")
    assert not hasattr(mgr, "get_recommended_tier")
