"""core/resources/probes/base.py

Base Resource Probe and Safe Execution Primitives for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).

Security & Reliability Invariants:
1. Strict Argv Execution: shell=True is forbidden; commands executed via validated argument lists.
2. Bounded Timeout: Probes default to <= 2.0s timeout to prevent thread starvation.
3. Bounded Output: Output reading is capped (default 64KB) to avoid memory exhaustion from runaway processes.
4. Fail-Safe Error Handling: Subprocess errors return None/safe fallbacks without raising unhandled exceptions.
5. Privacy Guarantee: Probe outputs stripped of hostnames, usernames, and user home paths.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import os
import platform
import subprocess
import threading
import time
from typing import List, Optional

from core.resources.models import (
    AcceleratorResources,
    AcceleratorType,
    CpuResources,
    MemoryResources,
    ProbeStatus,
)

logger = logging.getLogger("agent_engine.resources.probes")

TRUSTED_SYSTEM_DIRECTORIES = (
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
    "/usr/local/bin",
    "/opt/bin",
    "/usr/local/cuda/bin",
    "/opt/rocm/bin",
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/System/Library",
    r"C:\Windows\System32",
    r"C:\Windows",
    r"C:\Windows\System32\WindowsPowerShell\v1.0",
    r"C:\Program Files\NVIDIA Corporation\NVSMI",
)


def resolve_trusted_executable(
    name: str,
    trusted_dirs: Optional[List[str]] = None,
) -> Optional[str]:
    """Resolve an executable strictly from trusted system locations, preventing PATH-shadowing attacks.

    Invariants:
    1. Project-local or workspace executables CANNOT shadow system probes.
    2. Modified PATH cannot redirect probes to workspace or temporary directories.
    3. Executable must be a regular file with execute permissions.
    4. Missing executable returns None (probe unavailable), never fallback to arbitrary paths.
    """
    if not name or not isinstance(name, str):
        return None

    dirs_to_search = trusted_dirs if trusted_dirs is not None else list(TRUSTED_SYSTEM_DIRECTORIES)

    cwd = os.path.realpath(os.getcwd())
    untrusted_prefixes = [cwd, "/tmp", "/var/tmp", "/dev/shm"]

    # 1. If an absolute path is provided directly
    if os.path.isabs(name):
        real_p = os.path.realpath(name)
        for bad in untrusted_prefixes:
            if real_p == bad or real_p.startswith(bad + os.sep):
                logger.warning("Rejected probe executable in untrusted directory: %s", name)
                return None
        is_trusted = False
        for tdir in dirs_to_search:
            real_tdir = os.path.realpath(tdir)
            if real_p == real_tdir or real_p.startswith(real_tdir + os.sep):
                is_trusted = True
                break
        if not is_trusted:
            logger.warning("Rejected probe executable not in trusted directory whitelist: %s", name)
            return None
        if os.path.isfile(real_p) and os.access(real_p, os.X_OK):
            return real_p
        return None

    # 2. Search trusted directories only (completely ignoring untrusted PATH entries)
    names = [name]
    if platform.system() == "Windows" and not name.lower().endswith(".exe"):
        names.append(f"{name}.exe")

    for tdir in dirs_to_search:
        if not os.path.isdir(tdir):
            continue
        real_tdir = os.path.realpath(tdir)
        if any(
            real_tdir == bad or real_tdir.startswith(bad + os.sep) for bad in untrusted_prefixes
        ):
            continue

        for n in names:
            cand = os.path.join(tdir, n)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                real_cand = os.path.realpath(cand)
                if not any(
                    real_cand == bad or real_cand.startswith(bad + os.sep)
                    for bad in untrusted_prefixes
                ):
                    return real_cand

    return None


def safe_run_command(
    cmd: List[str],
    timeout: float = 2.0,
    max_bytes: int = 65536,
    trusted_dirs: Optional[List[str]] = None,
    refuse_oversized: bool = False,
) -> Optional[str]:
    """Execute a host command safely with strict argument lists, bounded timeout, and bounded memory capture.

    Security & Resource Protections:
    1. Executable is resolved exclusively from trusted system locations (PATH shadowing rejected).
    2. shell=False strictly enforced with discrete argv list.
    3. Output stream is drained concurrently with hard byte limit; child is terminated if oversized.
    4. Memory retained in parent process is strictly bounded by max_bytes.
    5. Outer execution timeout (<= 2.0s) strictly enforced.
    """
    if not cmd or not isinstance(cmd, list):
        return None

    exec_path = resolve_trusted_executable(cmd[0], trusted_dirs=trusted_dirs)
    if exec_path is None:
        logger.debug("Resource probe binary rejected or not found: %s", cmd[0])
        return None

    full_cmd = [exec_path] + cmd[1:]

    captured_stdout = bytearray()
    captured_stderr = bytearray()
    oversized = threading.Event()
    max_stderr_bytes = 4096

    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except FileNotFoundError:
        logger.debug("Resource probe binary not found on execution: %s", exec_path)
        return None
    except Exception as e:
        logger.debug("Error starting probe command %s: %s", exec_path, e)
        return None

    def read_stdout() -> None:
        assert proc.stdout is not None
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                if len(captured_stdout) + len(chunk) > max_bytes:
                    excess = max_bytes - len(captured_stdout)
                    if excess > 0:
                        captured_stdout.extend(chunk[:excess])
                    oversized.set()
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                captured_stdout.extend(chunk)
        except Exception:
            pass
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass

    def read_stderr() -> None:
        assert proc.stderr is not None
        try:
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                if len(captured_stderr) < max_stderr_bytes:
                    excess = max_stderr_bytes - len(captured_stderr)
                    captured_stderr.extend(chunk[:excess])
        except Exception:
            pass
        finally:
            try:
                proc.stderr.close()
            except Exception:
                pass

    t_out = threading.Thread(target=read_stdout, daemon=True)
    t_err = threading.Thread(target=read_stderr, daemon=True)
    t_out.start()
    t_err.start()

    start_time = time.time()
    timed_out = False

    while proc.poll() is None:
        if time.time() - start_time > timeout:
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass
            break
        if oversized.is_set():
            try:
                proc.kill()
            except Exception:
                pass
            break
        time.sleep(0.01)

    t_out.join(timeout=0.2)
    t_err.join(timeout=0.2)

    if timed_out:
        logger.warning("Resource probe command %s timed out after %.1fs", cmd[0], timeout)
        return None

    if oversized.is_set():
        logger.warning(
            "Resource probe command %s exceeded maximum output bound (%d bytes); terminated",
            cmd[0],
            max_bytes,
        )
        if refuse_oversized:
            return None

    if proc.returncode != 0 and not oversized.is_set():
        logger.debug(
            "Command %s exited with code %d: %s",
            cmd[0],
            proc.returncode,
            captured_stderr.decode("utf-8", errors="replace")[:200],
        )
        return None

    return captured_stdout.decode("utf-8", errors="replace").strip()


class BaseResourceProbe(ABC):
    """Abstract interface for platform-specific hardware telemetry probes."""

    @abstractmethod
    def probe_cpu(self) -> CpuResources:
        """Collect factual CPU resource information and utilization."""
        ...

    @abstractmethod
    def probe_memory(self) -> MemoryResources:
        """Collect factual system memory bytes (total, available, used, swap)."""
        ...

    @abstractmethod
    def probe_accelerators(self) -> List[AcceleratorResources]:
        """Detect zero or more GPU/NPU accelerators."""
        ...


def normalize_bus_id(bus_id: Optional[str]) -> Optional[str]:
    """Normalize a PCI bus identifier to standard format (e.g. '01:00.0')."""
    if not bus_id or not isinstance(bus_id, str):
        return None
    raw = bus_id.strip().lower()
    # Handle domain prefixes like 00000000:01:00.0 or 0000:01:00.0
    parts = raw.split(":")
    if len(parts) == 3:
        # domain:bus:slot.func -> bus:slot.func
        return f"{parts[1]}:{parts[2]}"
    elif len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    return raw


def deduplicate_accelerators(
    accelerators: List[AcceleratorResources],
) -> List[AcceleratorResources]:
    """Deduplicate and merge physical accelerators discovered across multiple probes.

    Invariants:
    1. A single physical GPU described by multiple probes (e.g. sysfs, nvidia-smi, lspci, CIM)
       is deduplicated into exactly one AcceleratorResources record.
    2. Higher-fidelity metrics (live VRAM from NVML/driver) take precedence over static sysfs data.
    3. Richer device names (e.g. marketing name from lspci/nvidia-smi) are retained.
    4. Probe sources are combined (e.g. 'nvidia_smi+sysfs_drm').
    5. Clean, non-sensitive, process-local IDs (gpu:0, gpu:1) are assigned; NO serial numbers or unique fingerprints.
    """
    if not accelerators:
        return []

    merged: List[AcceleratorResources] = []

    for incoming in accelerators:
        inc_bus_id = normalize_bus_id(incoming.metadata.get("pci_bus_id"))
        match_idx = -1

        for i, existing in enumerate(merged):
            ext_bus_id = normalize_bus_id(existing.metadata.get("pci_bus_id"))
            # 1. Match by non-sensitive PCI bus ID if present on both
            if inc_bus_id and ext_bus_id and inc_bus_id == ext_bus_id:
                match_idx = i
                break
            # 2. Fallback match by vendor and normalized device name
            if incoming.vendor == existing.vendor and incoming.vendor != "unknown":
                norm_inc = incoming.device_name.lower().replace(" ", "").replace("_", "")
                norm_ext = existing.device_name.lower().replace(" ", "").replace("_", "")
                if (
                    norm_inc in norm_ext
                    or norm_ext in norm_inc
                    or incoming.device_name.lower() == existing.device_name.lower()
                ):
                    match_idx = i
                    break

        if match_idx >= 0:
            existing = merged[match_idx]
            # Prefer official driver marketing name (e.g. from nvml / nvidia_smi) over raw PCI device string
            dev_name = existing.device_name
            if incoming.probe_source == "nvidia_smi" or incoming.backend in ("nvml", "metal"):
                dev_name = incoming.device_name
            elif existing.probe_source == "nvidia_smi" or existing.backend in ("nvml", "metal"):
                dev_name = existing.device_name
            elif (
                len(incoming.device_name) > len(existing.device_name)
                and "vga compatible" not in incoming.device_name.lower()
            ) or "vga compatible" in existing.device_name.lower():
                dev_name = incoming.device_name

            # Prefer non-zero VRAM from NVML or more specific probe
            total_vram = incoming.total_memory_bytes or existing.total_memory_bytes
            used_vram = (
                incoming.used_memory_bytes
                if incoming.used_memory_bytes is not None
                else existing.used_memory_bytes
            )
            avail_vram = (
                incoming.available_memory_bytes
                if incoming.available_memory_bytes is not None
                else existing.available_memory_bytes
            )
            # Preferred backend
            backend = (
                incoming.backend
                if incoming.backend in ("nvml", "metal", "rocm", "directx")
                else existing.backend
            )
            # Combine probe sources
            sources = set(existing.probe_source.split("+"))
            sources.update(incoming.probe_source.split("+"))
            merged_source = "+".join(sorted(sources))

            # Merge metadata without serials/fingerprints
            merged_meta = dict(existing.metadata)
            for k, v in incoming.metadata.items():
                if not any(bad in k.lower() for bad in ("serial", "uuid", "mac", "fingerprint")):
                    merged_meta[k] = v

            merged[match_idx] = AcceleratorResources(
                accelerator_id=existing.accelerator_id,
                device_name=dev_name,
                vendor=existing.vendor if existing.vendor != "generic" else incoming.vendor,
                type=existing.type if existing.type != AcceleratorType.UNKNOWN else incoming.type,
                total_memory_bytes=total_vram,
                used_memory_bytes=used_vram,
                available_memory_bytes=avail_vram,
                is_unified_memory=existing.is_unified_memory or incoming.is_unified_memory,
                backend=backend,
                probe_source=merged_source,
                status=ProbeStatus.KNOWN,
                metadata=merged_meta,
            )
        else:
            merged.append(incoming)

    # Re-index with clean, non-sensitive, process-local identifiers: gpu:0, gpu:1, ...
    deduped: List[AcceleratorResources] = []
    for idx, item in enumerate(merged):
        item_copy = item.model_copy()
        item_copy.accelerator_id = f"gpu:{idx}"
        deduped.append(item_copy)

    return deduped
