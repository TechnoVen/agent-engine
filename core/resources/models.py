"""core/resources/models.py

Canonical Host Resource Data Structures and Telemetry Schemas for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).

Design Invariants:
1. Factual and Timestamped: Every ResourceSnapshot carries captured_at and probe statuses.
2. Zero Fingerprinting: Strictly no hostname, username, machine serial number, or home paths.
3. Accurate Memory Semantics: Byte-valued total, available, used, and swap figures from OS.
4. Truthful Accelerator Model: 0 or more accelerators; missing facts remain UNKNOWN/None;
   Apple unified memory is never double-counted as separate dedicated VRAM.
5. No Invented Performance: Factual core counts and utilization; no fabricated tokens/sec or AI scores.
6. Decoupled from Routing/Recommendation: R3.3 reports host resource truth; R3.5 compares models.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class ProbeStatus(str, Enum):
    """Health and certainty status of hardware resource probes."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    STALE = "stale"
    PROBE_FAILED = "probe_failed"


class CpuResources(BaseModel):
    """Factual, unembellished CPU hardware and utilization facts."""

    architecture: str  # e.g., "x86_64", "arm64", "aarch64"
    logical_cores: int
    physical_cores: Optional[int] = None
    current_utilization_percent: Optional[float] = None  # [0.0, 100.0]
    load_average: Optional[Tuple[float, float, float]] = None  # (1m, 5m, 15m)
    frequency_mhz: Optional[float] = None
    status: ProbeStatus = ProbeStatus.KNOWN


class MemoryResources(BaseModel):
    """Byte-accurate physical system memory facts with explicit OS semantics."""

    total_bytes: int
    available_bytes: int  # OS-reported available memory without swapping
    used_bytes: int  # OS-reported used memory
    free_bytes: Optional[int] = None
    swap_total_bytes: Optional[int] = None
    swap_used_bytes: Optional[int] = None
    status: ProbeStatus = ProbeStatus.KNOWN

    @property
    def used_percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round((self.used_bytes / self.total_bytes) * 100.0, 1)


class AcceleratorType(str, Enum):
    """Classification of compute accelerator devices."""

    DISCRETE_GPU = "discrete_gpu"
    INTEGRATED_GPU = "integrated_gpu"
    NPU = "npu"
    UNKNOWN = "unknown"


class AcceleratorResources(BaseModel):
    """Factual hardware accelerator entry (0 or more per host)."""

    accelerator_id: str  # e.g. "gpu:0", "pci:0000:01:00.0"
    vendor: str  # "nvidia", "amd", "apple", "intel", "unknown"
    device_name: str  # e.g. "NVIDIA GeForce RTX 4090"
    type: AcceleratorType = AcceleratorType.UNKNOWN
    total_memory_bytes: Optional[int] = None  # Dedicated VRAM in bytes (None if unified or unknown)
    used_memory_bytes: Optional[int] = None
    available_memory_bytes: Optional[int] = None
    is_unified_memory: bool = False  # True for Apple Silicon or APUs sharing system RAM
    backend: str = "none"  # "nvml", "sysfs", "metal", "rocm", "directx", "none"
    probe_source: str = "unknown"  # "nvidia_smi", "sysfs_drm", "system_profiler", etc.
    status: ProbeStatus = ProbeStatus.KNOWN
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def memory_used_percent(self) -> Optional[float]:
        if (
            self.total_memory_bytes
            and self.total_memory_bytes > 0
            and self.used_memory_bytes is not None
        ):
            return round((self.used_memory_bytes / self.total_memory_bytes) * 100.0, 1)
        return None


class ResourceSnapshot(BaseModel):
    """Point-in-time factual host resource telemetry snapshot."""

    captured_at: float = Field(default_factory=time.time)
    platform: str  # "linux", "darwin", "windows"
    architecture: str
    cpu: CpuResources
    memory: MemoryResources
    accelerators: List[AcceleratorResources] = Field(default_factory=list)
    probe_status: Dict[str, ProbeStatus] = Field(default_factory=dict)
    stale: bool = False
    cache_age_seconds: float = 0.0

    @property
    def fresh(self) -> bool:
        return not self.stale
