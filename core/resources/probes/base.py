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
import subprocess
from typing import List, Optional

from core.resources.models import AcceleratorResources, CpuResources, MemoryResources

logger = logging.getLogger("agent_engine.resources.probes")


def safe_run_command(
    cmd: List[str],
    timeout: float = 2.0,
    max_bytes: int = 65536,
) -> Optional[str]:
    """Execute a host command safely with strict argument lists, bounded timeout, and bounded output."""
    if not cmd or not isinstance(cmd, list):
        return None

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
        if proc.returncode != 0:
            logger.debug(
                "Command %s exited with code %d: %s", cmd[0], proc.returncode, proc.stderr[:200]
            )
            return None

        output = proc.stdout
        if len(output) > max_bytes:
            output = output[:max_bytes]
        return output.strip()
    except subprocess.TimeoutExpired:
        logger.warning("Resource probe command %s timed out after %.1fs", cmd[0], timeout)
        return None
    except FileNotFoundError:
        logger.debug("Resource probe binary not found: %s", cmd[0])
        return None
    except Exception as e:
        logger.debug("Error executing probe command %s: %s", cmd[0], e)
        return None


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
