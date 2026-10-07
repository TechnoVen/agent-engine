"""Hardware Telemetry Module for Agent Engine.

Provides real-time hardware resource consumption monitoring (CPU, RAM, VRAM, GPU model detection)
and local LLM inference throughput tracking (tokens/sec for Ollama / llama.cpp).
Enforces the 95% VRAM saturation warning threshold.
"""

from dataclasses import asdict, dataclass, field
import datetime
import glob
import os
import platform
import re
import subprocess
from typing import Any, Dict, List, Optional
import psutil


@dataclass
class HardwareTelemetry:
    """Hardware telemetry snapshot model."""

    cpu_usage_percent: float
    cpu_cores_logical: int
    cpu_cores_physical: int
    ram_used_percent: float
    ram_used_gb: float
    ram_total_gb: float
    ram_available_gb: float
    gpu_detected: bool
    gpu_model: str
    gpu_vendor: str  # "nvidia" | "amd" | "apple" | "intel" | "generic"
    vram_used_percent: float
    vram_used_gb: float
    vram_total_gb: float
    vram_free_gb: float
    vram_warning: bool  # True if vram_used_percent >= 95.0
    vram_warning_threshold: float = 95.0
    tokens_per_second: float = 0.0
    recent_inference_runtime: Optional[str] = None
    recent_inference_model: Optional[str] = None
    ollama_active: bool = False
    llamacpp_active: bool = False
    local_runtime_active: bool = False
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HardwareTelemetryTracker:
    """Singleton tracker for hardware telemetry and local model throughput."""

    def __init__(self) -> None:
        self._cached_gpu_info: Optional[Dict[str, Any]] = None
        self._last_gpu_probe_time: float = 0.0
        self._vram_override_total: Optional[float] = None
        self._vram_override_used: Optional[float] = None
        self._recent_tokens: int = 0
        self._recent_elapsed: float = 0.0
        self._recent_tps: float = 0.0
        self._recent_model: Optional[str] = None
        self._recent_runtime: Optional[str] = None
        self._last_inference_time: float = 0.0
        self._speed_history: List[float] = []

    def set_vram_override(self, total_gb: Optional[float], used_gb: Optional[float]) -> None:
        """Override VRAM values for testing and deterministic threshold verification."""
        self._vram_override_total = total_gb
        self._vram_override_used = used_gb

    def reset_override(self) -> None:
        """Reset test overrides."""
        self._vram_override_total = None
        self._vram_override_used = None

    def record_inference_speed(
        self,
        tokens: int,
        elapsed_seconds: float,
        model: str = "qwen2.5-coder:7b",
        runtime: str = "ollama",
    ) -> float:
        """Record local model generation throughput and compute tokens/sec."""
        safe_elapsed = max(elapsed_seconds, 0.001)
        tps = round(tokens / safe_elapsed, 1)

        self._recent_tokens = tokens
        self._recent_elapsed = round(safe_elapsed, 3)
        self._recent_tps = tps
        self._recent_model = model
        self._recent_runtime = runtime
        import time

        self._last_inference_time = time.time()

        self._speed_history.append(tps)
        if len(self._speed_history) > 20:
            self._speed_history.pop(0)

        return tps

    def probe_gpu(self) -> Dict[str, Any]:
        """Detect GPU vendor, model name, and VRAM capacity with cross-platform probes."""
        # 1. NVIDIA via nvidia-smi
        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if res.returncode == 0 and res.stdout.strip():
                lines = res.stdout.strip().splitlines()
                if lines:
                    parts = [p.strip() for p in lines[0].split(",")]
                    if len(parts) >= 3:
                        total_mb = float(parts[1])
                        used_mb = float(parts[2])
                        total_gb = round(total_mb / 1024.0, 2)
                        used_gb = round(used_mb / 1024.0, 2)
                        free_gb = round(max(0.0, total_gb - used_gb), 2)
                        used_pct = round((used_gb / max(total_gb, 0.001)) * 100.0, 1)
                        return {
                            "detected": True,
                            "vendor": "nvidia",
                            "model": parts[0],
                            "vram_total_gb": total_gb,
                            "vram_used_gb": used_gb,
                            "vram_free_gb": free_gb,
                            "vram_used_percent": min(100.0, used_pct),
                        }
        except Exception:
            pass

        # 2. Linux DRM /sys/class/drm (AMD / Intel GPU)
        if platform.system() == "Linux":
            cards = glob.glob("/sys/class/drm/card*/device")
            for card in cards:
                vram_total_p = os.path.join(card, "mem_info_vram_total")
                vram_used_p = os.path.join(card, "mem_info_vram_used")
                if os.path.exists(vram_total_p) and os.path.exists(vram_used_p):
                    try:
                        with open(vram_total_p) as f:
                            total_bytes = int(f.read().strip())
                        with open(vram_used_p) as f:
                            used_bytes = int(f.read().strip())

                        total_gb = round(total_bytes / (1024**3), 2)
                        used_gb = round(used_bytes / (1024**3), 2)
                        free_gb = round(max(0.0, total_gb - used_gb), 2)
                        used_pct = round((used_gb / max(total_gb, 0.001)) * 100.0, 1)

                        # Resolve model name via lspci
                        model_name = "AMD Radeon Graphics"
                        vendor = "amd"
                        try:
                            lsp = subprocess.run(
                                ["lspci"], capture_output=True, text=True, timeout=1.0
                            )
                            for line in lsp.stdout.splitlines():
                                if any(
                                    k in line.lower()
                                    for k in [
                                        "vga compatible controller",
                                        "3d controller",
                                        "display controller",
                                    ]
                                ):
                                    parts = line.split(":", 2)
                                    if len(parts) >= 3:
                                        model_name = parts[2].strip()
                                        if "intel" in model_name.lower():
                                            vendor = "intel"
                                        break
                        except Exception:
                            pass

                        return {
                            "detected": True,
                            "vendor": vendor,
                            "model": model_name,
                            "vram_total_gb": total_gb,
                            "vram_used_gb": used_gb,
                            "vram_free_gb": free_gb,
                            "vram_used_percent": min(100.0, used_pct),
                        }
                    except Exception:
                        pass

        # 3. macOS Apple Silicon via system_profiler
        if platform.system() == "Darwin":
            try:
                res = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                if res.returncode == 0 and "Chipset Model:" in res.stdout:
                    match = re.search(r"Chipset Model:\s*(.+)", res.stdout)
                    model_name = match.group(1).strip() if match else "Apple M-Series GPU"
                    # Apple unified memory: approximate from virtual memory
                    vm = psutil.virtual_memory()
                    unified_total = round(vm.total / (1024**3), 2)
                    unified_used = round(vm.used / (1024**3), 2)
                    unified_free = round(vm.available / (1024**3), 2)
                    return {
                        "detected": True,
                        "vendor": "apple",
                        "model": model_name,
                        "vram_total_gb": unified_total,
                        "vram_used_gb": unified_used,
                        "vram_free_gb": unified_free,
                        "vram_used_percent": vm.percent,
                    }
            except Exception:
                pass

        # 4. Fallback: Host CPU / Integrated fallback
        return {
            "detected": False,
            "vendor": "generic",
            "model": "System Integrated / CPU Inference",
            "vram_total_gb": 0.0,
            "vram_used_gb": 0.0,
            "vram_free_gb": 0.0,
            "vram_used_percent": 0.0,
        }

    def get_telemetry(self, router_status: Optional[Dict[str, Any]] = None) -> HardwareTelemetry:
        """Compile a full snapshot of hardware utilization and throughput via canonical ResourceManager."""
        import time
        from core.resources import get_resource_manager

        now = time.time()
        res_mgr = get_resource_manager()
        snap = res_mgr.get_snapshot()

        # Map CPU
        cpu_usage_pct = snap.cpu.current_utilization_percent or 0.0
        cpu_logical = snap.cpu.logical_cores
        cpu_physical = snap.cpu.physical_cores or cpu_logical

        # Map RAM
        ram_total_gb = round(snap.memory.total_bytes / (1024**3), 2)
        ram_used_gb = round(snap.memory.used_bytes / (1024**3), 2)
        ram_avail_gb = round(snap.memory.available_bytes / (1024**3), 2)
        ram_used_pct = snap.memory.used_percent

        # Map Accelerators
        gpu_detected = len(snap.accelerators) > 0
        gpu_model = "System Integrated / CPU Inference"
        gpu_vendor = "generic"
        vram_total_gb = 0.0
        vram_used_gb = 0.0
        vram_free_gb = 0.0
        vram_used_pct = 0.0

        if gpu_detected:
            first = snap.accelerators[0]
            gpu_model = first.device_name
            gpu_vendor = first.vendor
            if first.total_memory_bytes:
                vram_total_gb = round(first.total_memory_bytes / (1024**3), 2)
            if first.used_memory_bytes:
                vram_used_gb = round(first.used_memory_bytes / (1024**3), 2)
            if first.available_memory_bytes:
                vram_free_gb = round(first.available_memory_bytes / (1024**3), 2)
            vram_used_pct = first.memory_used_percent or 0.0

        # Apply testing overrides if set
        if self._vram_override_total is not None and self._vram_override_used is not None:
            vram_total_gb = self._vram_override_total
            vram_used_gb = self._vram_override_used
            vram_free_gb = max(0.0, self._vram_override_total - self._vram_override_used)
            vram_used_pct = round(
                (self._vram_override_used / max(self._vram_override_total, 0.001)) * 100.0, 1
            )
            gpu_detected = True

        vram_warn = vram_used_pct >= 95.0

        # Runtime status
        ollama_live = False
        llamacpp_live = False
        if router_status:
            ollama_live = bool(router_status.get("ollama_live", False))
            llamacpp_live = bool(router_status.get("llamacpp_live", False))

        is_recent_inference = (now - self._last_inference_time) < 60.0
        local_runtime_active = ollama_live or llamacpp_live or is_recent_inference

        return HardwareTelemetry(
            cpu_usage_percent=cpu_usage_pct,
            cpu_cores_logical=cpu_logical,
            cpu_cores_physical=cpu_physical,
            ram_used_percent=ram_used_pct,
            ram_used_gb=ram_used_gb,
            ram_total_gb=ram_total_gb,
            ram_available_gb=ram_avail_gb,
            gpu_detected=gpu_detected,
            gpu_model=gpu_model,
            gpu_vendor=gpu_vendor,
            vram_used_percent=vram_used_pct,
            vram_used_gb=vram_used_gb,
            vram_total_gb=vram_total_gb,
            vram_free_gb=vram_free_gb,
            vram_warning=vram_warn,
            vram_warning_threshold=95.0,
            tokens_per_second=self._recent_tps,
            recent_inference_runtime=self._recent_runtime,
            recent_inference_model=self._recent_model,
            ollama_active=ollama_live,
            llamacpp_active=llamacpp_live,
            local_runtime_active=local_runtime_active,
            timestamp=datetime.datetime.now().isoformat(),
        )


_tracker_instance: Optional[HardwareTelemetryTracker] = None


def get_hardware_telemetry_tracker() -> HardwareTelemetryTracker:
    """Singleton getter for HardwareTelemetryTracker."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = HardwareTelemetryTracker()
    return _tracker_instance
