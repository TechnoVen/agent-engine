"""
core/router/execution_router.py

Execution Router implementing the 90/9/1 Cost Optimization Rule:
- 90% deterministic code, caching, or small local model.
- 9% mid-tier model.
- 1% frontier model.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class ExecutionTier(str, Enum):
    CODE = "code"
    CACHE = "cache"
    SMALL_MODEL = "small_model"
    MID_MODEL = "mid_model"
    FRONTIER_MODEL = "frontier_model"
    HUMAN = "human"


@dataclass
class StepProfile:
    step_name: str
    is_deterministic: bool = False
    is_cacheable: bool = False
    requires_judgment: bool = False
    complexity: str = "low"  # "low" | "medium" | "high"
    is_high_stakes: bool = False
    fallback_tier: ExecutionTier = ExecutionTier.MID_MODEL


class ExecutionRouter:
    """
    Classifies pipeline steps into the optimal execution tier following
    the 90/9/1 cost minimization decision tree.
    """

    def __init__(self, cache: Optional[Any] = None):
        self.cache = cache

    def route(self, step: StepProfile, inputs: Optional[Dict[str, Any]] = None) -> ExecutionTier:
        """
        Classify a step according to the 90/9/1 Decision Tree:
        1. Deterministic code logic -> CODE (0 tokens)
        2. Exact/semantic cache hit -> CACHE (0 tokens)
        3. No human-like judgment needed -> CODE (0 tokens)
        4. Low complexity reasoning/rewrite/classification -> SMALL_MODEL (local Gemma/Qwen)
        5. Medium complexity reasoning -> MID_MODEL
        6. High-stakes/novel reasoning -> FRONTIER_MODEL (or HUMAN if critical)
        """
        inputs = inputs or {}

        # 1. Deterministic by default
        if step.is_deterministic:
            return ExecutionTier.CODE

        # 2. Check cache
        if step.is_cacheable and self.cache is not None:
            if hasattr(self.cache, "has") and self.cache.has(step.step_name, inputs):
                return ExecutionTier.CACHE

        # 3. No judgment required -> Code
        if not step.requires_judgment:
            return ExecutionTier.CODE

        # 4. Low complexity judgment -> Small local model
        if step.complexity == "low":
            return ExecutionTier.SMALL_MODEL

        # 5. High-stakes critical reasoning -> Frontier model
        if step.is_high_stakes:
            return ExecutionTier.FRONTIER_MODEL

        # 6. Medium complexity reasoning -> Mid-tier model
        if step.complexity == "medium":
            return ExecutionTier.MID_MODEL

        return step.fallback_tier
