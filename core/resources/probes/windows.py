"""core/resources/probes/windows.py

Windows Platform Resource Probe for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).
"""

from __future__ import annotations

import logging
import platform
from typing import List

import psutil

from core.resources.models import (
    AcceleratorResources,
    AcceleratorType,
    CpuResources,
    MemoryResources,
    ProbeStatus,
)
from core.resources.probes.base import BaseResourceProbe, safe_run_command

logger = logging.getLogger("agent_engine.resources.probes.windows")


class WindowsResourceProbe(BaseResourceProbe):
    """Factual Windows hardware resource probe."""

    def probe_cpu(self) -> CpuResources:
        arch = platform.machine() or "x86_64"
        logical = psutil.cpu_count(logical=True) or 1
        physical = psutil.cpu_count(logical=False)

        util = psutil.cpu_percent(interval=None)
        if util == 0.0:
            util = psutil.cpu_percent(interval=0.02)

        freq_mhz = None
        try:
            freq_stat = psutil.cpu_freq()
            if freq_stat and freq_stat.current:
                freq_mhz = round(freq_stat.current, 1)
        except Exception:
            pass

        return CpuResources(
            architecture=arch,
            logical_cores=logical,
            physical_cores=physical,
            current_utilization_percent=round(util, 1),
            load_average=None,  # Not supported on Windows
            frequency_mhz=freq_mhz,
            status=ProbeStatus.KNOWN,
        )

    def probe_memory(self) -> MemoryResources:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return MemoryResources(
            total_bytes=int(vm.total),
            available_bytes=int(vm.available),
            used_bytes=int(vm.used),
            free_bytes=int(vm.free),
            swap_total_bytes=int(swap.total) if swap else None,
            swap_used_bytes=int(swap.used) if swap else None,
            status=ProbeStatus.KNOWN,
        )

    def probe_accelerators(self) -> List[AcceleratorResources]:
        # NVIDIA check via nvidia-smi with bounded timeout and no shell
        cmd = [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ]
        out = safe_run_command(cmd, timeout=1.5)
        if not out:
            return []

        results: List[AcceleratorResources] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                try:
                    idx = parts[0]
                    name = parts[1]
                    total_mb = float(parts[2])
                    used_mb = float(parts[3])
                    free_mb = float(parts[4])

                    results.append(
                        AcceleratorResources(
                            accelerator_id=f"nvidia:{idx}",
                            vendor="nvidia",
                            device_name=name,
                            type=AcceleratorType.DISCRETE_GPU,
                            total_memory_bytes=int(total_mb * 1024 * 1024),
                            used_memory_bytes=int(used_mb * 1024 * 1024),
                            available_memory_bytes=int(free_mb * 1024 * 1024),
                            is_unified_memory=False,
                            backend="nvml",
                            probe_source="nvidia_smi",
                            status=ProbeStatus.KNOWN,
                        )
                    )
                except Exception as e:
                    logger.debug("Failed to parse Windows nvidia-smi line '%s': %s", line, e)

        return results
