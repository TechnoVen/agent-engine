"""core/resources/probes/darwin.py

macOS Platform Resource Probe for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).

Invariant:
Apple unified memory is never double-counted as both dedicated VRAM and system RAM.
"""

from __future__ import annotations

import logging
import os
import platform
import re
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

logger = logging.getLogger("agent_engine.resources.probes.darwin")


class DarwinResourceProbe(BaseResourceProbe):
    """Factual macOS hardware resource probe."""

    def probe_cpu(self) -> CpuResources:
        arch = platform.machine() or "arm64"
        logical = psutil.cpu_count(logical=True) or 1
        physical = psutil.cpu_count(logical=False)

        util = psutil.cpu_percent(interval=None)
        if util == 0.0:
            util = psutil.cpu_percent(interval=0.02)

        load_avg = None
        try:
            load_avg = os.getloadavg()
        except (AttributeError, OSError):
            pass

        return CpuResources(
            architecture=arch,
            logical_cores=logical,
            physical_cores=physical,
            current_utilization_percent=round(util, 1),
            load_average=load_avg,
            frequency_mhz=None,  # Not reliably reported on Apple Silicon without root
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
        out = safe_run_command(["system_profiler", "SPDisplaysDataType"], timeout=2.0)
        if not out:
            return []

        results: List[AcceleratorResources] = []
        model_name = "Apple Silicon GPU"
        match = re.search(r"Chipset Model:\s*(.+)", out)
        if match:
            model_name = match.group(1).strip()

        # Invariant: Apple unified memory is shared with host RAM; do NOT fabricate separate VRAM
        results.append(
            AcceleratorResources(
                accelerator_id="metal:0",
                vendor="apple",
                device_name=model_name,
                type=AcceleratorType.INTEGRATED_GPU,
                total_memory_bytes=None,  # Truthful: no dedicated VRAM pool; shares system RAM
                used_memory_bytes=None,
                available_memory_bytes=None,
                is_unified_memory=True,
                backend="metal",
                probe_source="system_profiler",
                status=ProbeStatus.KNOWN,
                metadata={"memory_architecture": "unified_system_memory"},
            )
        )
        return results
