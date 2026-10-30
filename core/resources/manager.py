"""core/resources/manager.py

Canonical Host Resource Manager for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).

Concurrency & Architecture Invariants:
1. Lock Discipline: RLock is strictly held for cache state updates only; NEVER held across probe I/O.
2. Independent Probe Failure: If an accelerator probe fails, CPU and RAM facts are fully preserved.
3. Timestamped & Factual: Snapshots record captured_at, freshness, and cache_age_seconds.
4. Zero Fingerprinting: Zero hostnames, usernames, serial numbers, or home paths in snapshots.
"""

from __future__ import annotations

import logging
import platform
from threading import RLock
import time
from typing import Optional

from core.resources.models import ProbeStatus, ResourceSnapshot
from core.resources.probes.base import BaseResourceProbe
from core.resources.probes.darwin import DarwinResourceProbe
from core.resources.probes.linux import LinuxResourceProbe
from core.resources.probes.windows import WindowsResourceProbe

logger = logging.getLogger("agent_engine.resources.manager")

_GLOBAL_RESOURCE_MANAGER: Optional[ResourceManager] = None
_RESOURCE_MANAGER_LOCK = RLock()


class ResourceManager:
    """Thread-safe host resource telemetry and hardware discovery service."""

    def __init__(
        self,
        probe: Optional[BaseResourceProbe] = None,
        cache_ttl_seconds: float = 10.0,
        stale_threshold_seconds: float = 2.0,
    ) -> None:
        self._lock = RLock()
        self._cache_ttl = cache_ttl_seconds
        self._stale_threshold = stale_threshold_seconds
        self._cached_snapshot: Optional[ResourceSnapshot] = None
        self._cache_time: float = 0.0

        if probe is not None:
            self._probe = probe
        else:
            sys_name = platform.system()
            if sys_name == "Linux":
                self._probe = LinuxResourceProbe()
            elif sys_name == "Darwin":
                self._probe = DarwinResourceProbe()
            elif sys_name == "Windows":
                self._probe = WindowsResourceProbe()
            else:
                self._probe = LinuxResourceProbe()

    def get_snapshot(self, force_refresh: bool = False) -> ResourceSnapshot:
        """Obtain a factual ResourceSnapshot with bounded caching and lock-free I/O."""
        now = time.time()

        # 1. Fast cache check under lock
        with self._lock:
            if not force_refresh and self._cached_snapshot is not None:
                age = now - self._cache_time
                if age < self._cache_ttl:
                    cached_copy = self._cached_snapshot.model_copy(deep=True)
                    cached_copy.cache_age_seconds = round(age, 2)
                    cached_copy.stale = age > self._stale_threshold
                    return cached_copy

        # 2. Execute probes OUTSIDE of lock (network/subprocess I/O never holds lock)
        probe_status = {}
        try:
            cpu_data = self._probe.probe_cpu()
            probe_status["cpu"] = cpu_data.status
        except Exception as e:
            logger.error("Failed to probe CPU: %s", e)
            from core.resources.models import CpuResources

            cpu_data = CpuResources(
                architecture=platform.machine() or "unknown",
                logical_cores=1,
                status=ProbeStatus.PROBE_FAILED,
            )
            probe_status["cpu"] = ProbeStatus.PROBE_FAILED

        try:
            mem_data = self._probe.probe_memory()
            probe_status["memory"] = mem_data.status
        except Exception as e:
            logger.error("Failed to probe Memory: %s", e)
            from core.resources.models import MemoryResources

            mem_data = MemoryResources(
                total_bytes=0,
                available_bytes=0,
                used_bytes=0,
                status=ProbeStatus.PROBE_FAILED,
            )
            probe_status["memory"] = ProbeStatus.PROBE_FAILED

        try:
            accel_data = self._probe.probe_accelerators()
            probe_status["accelerators"] = ProbeStatus.KNOWN
        except Exception as e:
            logger.error("Failed to probe Accelerators: %s", e)
            accel_data = []
            probe_status["accelerators"] = ProbeStatus.PROBE_FAILED

        captured_timestamp = time.time()
        fresh_snapshot = ResourceSnapshot(
            captured_at=captured_timestamp,
            platform=platform.system().lower(),
            architecture=cpu_data.architecture,
            cpu=cpu_data,
            memory=mem_data,
            accelerators=accel_data,
            probe_status=probe_status,
            stale=False,
            cache_age_seconds=0.0,
        )

        # 3. Store in cache under lock
        with self._lock:
            self._cached_snapshot = fresh_snapshot
            self._cache_time = captured_timestamp
            return fresh_snapshot.model_copy(deep=True)


def get_resource_manager() -> ResourceManager:
    """Singleton getter for process-wide ResourceManager."""
    global _GLOBAL_RESOURCE_MANAGER
    with _RESOURCE_MANAGER_LOCK:
        if _GLOBAL_RESOURCE_MANAGER is None:
            _GLOBAL_RESOURCE_MANAGER = ResourceManager()
        return _GLOBAL_RESOURCE_MANAGER


def reset_resource_manager(probe: Optional[BaseResourceProbe] = None) -> ResourceManager:
    """Reset the singleton ResourceManager (used for test isolation)."""
    global _GLOBAL_RESOURCE_MANAGER
    with _RESOURCE_MANAGER_LOCK:
        _GLOBAL_RESOURCE_MANAGER = ResourceManager(probe=probe)
        return _GLOBAL_RESOURCE_MANAGER
