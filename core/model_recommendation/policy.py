"""core/model_recommendation/policy.py

Safety reserves, memory headroom calculations, and unified memory policies.
Part of Milestone R3 Task R3.5 (Local Model Catalog and Recommendation).

Invariants:
1. Explicit Reserves: Allocates safety reserves for OS, Agent Engine, llama.cpp process overhead, and KV cache.
2. Available vs Total Memory: Never calculates feasibility against total installed RAM alone; calculates strictly
   against OS-reported available RAM minus safety reserves. Never consumes 100% of available memory on paper.
3. Unified Memory Single-Pool Invariant: On unified-memory devices (Apple Silicon or APUs), RAM and GPU memory
   share a single physical pool and must NEVER be summed together.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Default safety reserves in bytes
DEFAULT_OS_RESERVE_BYTES = int(1.5 * 1024 * 1024 * 1024)  # 1.5 GB
DEFAULT_AGENT_ENGINE_RESERVE_BYTES = 512 * 1024 * 1024  # 512 MB
DEFAULT_RUNTIME_BASE_RESERVE_BYTES = 512 * 1024 * 1024  # 512 MB
DEFAULT_DISCRETE_VRAM_RESERVE_BYTES = 256 * 1024 * 1024  # 256 MB


class ReservePolicy(BaseModel):
    """Policy governing host safety reserves and tier headroom thresholds."""

    os_reserve_bytes: int = Field(default=DEFAULT_OS_RESERVE_BYTES, ge=0)
    agent_engine_reserve_bytes: int = Field(default=DEFAULT_AGENT_ENGINE_RESERVE_BYTES, ge=0)
    runtime_base_reserve_bytes: int = Field(default=DEFAULT_RUNTIME_BASE_RESERVE_BYTES, ge=0)
    discrete_vram_reserve_bytes: int = Field(default=DEFAULT_DISCRETE_VRAM_RESERVE_BYTES, ge=0)

    # Minimum safe headroom ratios (headroom_bytes / safe_available_bytes)
    min_headroom_fast_ratio: float = 0.35  # >= 35% safe headroom for FAST tier
    min_headroom_balanced_ratio: float = 0.20  # >= 20% safe headroom for BALANCED tier
    min_headroom_best_ratio: float = 0.05  # >= 5% safe headroom for BEST_LOCAL tier


def calculate_kv_context_overhead(
    context_tokens: int,
    parameter_count_billions: float = 3.0,
) -> int:
    """Calculate conservative memory overhead in bytes for KV cache at given context length.

    Approximation based on FP16 KV cache scaling with context length and model width:
    Base ~100MB per 2048 tokens for 3B models, scaling with parameter size.
    """
    tokens = max(512, context_tokens)
    scale = max(0.5, parameter_count_billions / 3.0)
    # Approx 50KB per token scaled by model dimension
    overhead = int(tokens * 50 * 1024 * scale)
    # Bound minimum overhead to 64MB
    return max(64 * 1024 * 1024, overhead)


def calculate_safe_available_ram(
    available_ram_bytes: int,
    policy: Optional[ReservePolicy] = None,
) -> int:
    """Compute net RAM available for model execution after deducting OS and AE reserves."""
    p = policy or ReservePolicy()
    total_reserves = p.os_reserve_bytes + p.agent_engine_reserve_bytes
    return max(0, available_ram_bytes - total_reserves)


def calculate_safe_available_vram(
    available_vram_bytes: Optional[int],
    is_unified_memory: bool,
    policy: Optional[ReservePolicy] = None,
) -> Optional[int]:
    """Compute net dedicated VRAM available on discrete GPUs.

    For unified memory devices (Apple Silicon or APUs), dedicated VRAM is None
    because RAM and VRAM share the same physical pool and must never be added together.
    """
    if is_unified_memory or available_vram_bytes is None:
        return None

    p = policy or ReservePolicy()
    return max(0, available_vram_bytes - p.discrete_vram_reserve_bytes)
