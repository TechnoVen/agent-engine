"""core/resources/probes/linux.py

Linux Platform Resource Probe for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).
"""

from __future__ import annotations

import glob
import logging
import os
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
from core.resources.probes.base import (
    BaseResourceProbe,
    deduplicate_accelerators,
    normalize_bus_id,
    safe_run_command,
)

logger = logging.getLogger("agent_engine.resources.probes.linux")


class LinuxResourceProbe(BaseResourceProbe):
    """Factual Linux hardware resource probe leveraging psutil, sysfs, and optional tools."""

    def __init__(self) -> None:
        self._cpu_baseline_initialized: bool = False

    def probe_cpu(self) -> CpuResources:
        arch = platform.machine() or "unknown"
        logical = psutil.cpu_count(logical=True) or 1
        physical = psutil.cpu_count(logical=False)

        # Utilization: psutil docs state the first non-blocking call returns meaningless 0.0.
        # Truthful semantics: first baseline sample returns None / UNKNOWN; subsequent samples
        # return the factual percentage elapsed since the previous call.
        if not self._cpu_baseline_initialized:
            psutil.cpu_percent(interval=None)
            self._cpu_baseline_initialized = True
            util = None
        else:
            raw_util = psutil.cpu_percent(interval=None)
            util = round(raw_util, 1)

        # Load average (1m, 5m, 15m)
        load_avg = None
        try:
            load_avg = os.getloadavg()
        except (AttributeError, OSError):
            pass

        # Frequency in MHz
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
            current_utilization_percent=util,
            load_average=load_avg,
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
        accelerators: List[AcceleratorResources] = []

        # 1. NVIDIA probe via bounded nvidia-smi
        nvidia_accels = self._probe_nvidia_smi()
        if nvidia_accels:
            accelerators.extend(nvidia_accels)

        # 2. DRM sysfs probe (AMD / Intel / NVIDIA sysfs nodes)
        sysfs_accels = self._probe_sysfs_drm()
        if sysfs_accels:
            accelerators.extend(sysfs_accels)

        # 3. Deduplicate physical devices across probe sources into single canonical records
        return deduplicate_accelerators(accelerators)

    def _probe_nvidia_smi(self) -> List[AcceleratorResources]:
        cmd = [
            "nvidia-smi",
            "--query-gpu=pci.bus_id,index,name,memory.total,memory.used,memory.free",
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
            if len(parts) >= 6:
                try:
                    raw_bus_id = parts[0]
                    idx = parts[1]
                    name = parts[2]
                    total_mb = float(parts[3])
                    used_mb = float(parts[4])
                    free_mb = float(parts[5])

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
                            metadata={"pci_bus_id": normalize_bus_id(raw_bus_id)},
                        )
                    )
                except (ValueError, IndexError) as e:
                    logger.debug("Failed to parse nvidia-smi line '%s': %s", line, e)
        return results

    def _probe_sysfs_drm(self) -> List[AcceleratorResources]:
        results: List[AcceleratorResources] = []
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

                    if total_bytes <= 0:
                        continue

                    avail_bytes = max(0, total_bytes - used_bytes)
                    card_name = os.path.basename(os.path.dirname(card))
                    raw_bus_id = os.path.basename(os.path.realpath(card))

                    vendor = "amd"
                    dev_name = "AMD Radeon Graphics"

                    # Resolve name and vendor from lspci if accessible
                    lspci_out = safe_run_command(["lspci"], timeout=1.0)
                    if lspci_out:
                        for line in lspci_out.splitlines():
                            low = line.lower()
                            if any(
                                k in low for k in ("vga compatible controller", "3d controller")
                            ):
                                parts = line.split(":", 2)
                                if len(parts) >= 3:
                                    dev_name = parts[2].strip()
                                    if "intel" in dev_name.lower():
                                        vendor = "intel"
                                    elif "nvidia" in dev_name.lower():
                                        vendor = "nvidia"
                                    break

                    results.append(
                        AcceleratorResources(
                            accelerator_id=f"drm:{card_name}",
                            vendor=vendor,
                            device_name=dev_name,
                            type=AcceleratorType.DISCRETE_GPU,
                            total_memory_bytes=total_bytes,
                            used_memory_bytes=used_bytes,
                            available_memory_bytes=avail_bytes,
                            is_unified_memory=False,
                            backend="sysfs",
                            probe_source="sysfs_drm",
                            status=ProbeStatus.KNOWN,
                            metadata={"pci_bus_id": normalize_bus_id(raw_bus_id)},
                        )
                    )
                except Exception as e:
                    logger.debug("Error probing DRM card %s: %s", card, e)

        return results
