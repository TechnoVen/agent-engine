"""
core/router/execution_router.py

Execution Router implementing the 90/9/1 Cost Optimization Rule (Task 1.10):
- 90% deterministic code, caching, or small local model.
- 9% mid-tier model.
- 1% frontier model.

Integrates with:
- Law 1: The 90/9/1 Rule & pipeline audit checks.
- SemanticCache: 0-token L1/L2 cache hits.
- ContextBuilder: <8,000 token budget enforcement.
- CostTracker: per-task spend tracking.
- ModelEvalSuite: dynamic model ranking resolution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import functools
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from core.context.builder import ContextSpec, build_context, estimate_object_tokens
from core.telemetry.cost import DEFAULT_PRICING, ModelPricing

logger = logging.getLogger(__name__)


class ExecutionTier(str, Enum):
    """Execution tiers defined by the 90/9/1 cost optimization framework."""

    CODE = "code"
    CACHE = "cache"
    SMALL_MODEL = "small_model"
    MID_MODEL = "mid_model"
    FRONTIER_MODEL = "frontier_model"
    HUMAN = "human"


DEFAULT_TIER_MODELS: Dict[ExecutionTier, List[str]] = {
    ExecutionTier.CODE: [],
    ExecutionTier.CACHE: [],
    ExecutionTier.SMALL_MODEL: ["qwen2.5-coder", "gemma-2-9b", "gemini-1.5-flash", "deepseek-chat"],
    ExecutionTier.MID_MODEL: ["gemini-2.0-flash", "gpt-4o-mini", "claude-3-5-haiku"],
    ExecutionTier.FRONTIER_MODEL: ["gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro"],
    ExecutionTier.HUMAN: [],
}


@dataclass
class StepProfile:
    """
    Profile declaring the execution characteristics, complexity, and safety
    stakes of a specific agent or pipeline step.
    """

    step_name: str
    is_deterministic: bool = False
    is_cacheable: bool = False
    requires_judgment: bool = False
    complexity: str = "low"  # "low" | "medium" | "high"
    is_high_stakes: bool = False
    fallback_tier: ExecutionTier = ExecutionTier.MID_MODEL
    description: str = ""
    task_type: Optional[str] = None
    cache_namespace: str = "default"
    context_spec: Optional[ContextSpec] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["fallback_tier"] = (
            self.fallback_tier.value
            if isinstance(self.fallback_tier, ExecutionTier)
            else str(self.fallback_tier)
        )
        if self.context_spec:
            d["context_spec"] = asdict(self.context_spec)
        return d


@dataclass
class StepExecutionResult:
    """Detailed result of executing an agent step through the Execution Router."""

    step_name: str
    tier: ExecutionTier
    model_used: Optional[str]
    output: Any
    tokens_used: int
    cost_usd: float
    latency_ms: float
    cache_hit: bool = False
    requires_human: bool = False
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_name": self.step_name,
            "tier": self.tier.value if isinstance(self.tier, ExecutionTier) else str(self.tier),
            "model_used": self.model_used,
            "output": self.output,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "requires_human": self.requires_human,
            "rationale": self.rationale,
            "metadata": self.metadata,
        }


@dataclass
class RatioAudit:
    """Audit report evaluating a sequence of steps against Law 1 (The 90/9/1 Rule)."""

    total_steps: int
    deterministic_or_small_count: int
    mid_tier_count: int
    frontier_count: int
    human_count: int
    deterministic_or_small_pct: float
    mid_tier_pct: float
    frontier_pct: float
    complies_with_law_1: bool
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def audit_pipeline(steps: List[StepProfile]) -> RatioAudit:
    """
    Enforce Law 1 (The 90/9/1 Rule):
    - 90% deterministic code, caching, or small local model.
    - 9% mid-tier model.
    - 1% frontier model (hard ceiling: <= 10%).
    If a pipeline proposes sending > 10% of steps to frontier models, it violates Law 1.
    """
    if not steps:
        return RatioAudit(
            total_steps=0,
            deterministic_or_small_count=0,
            mid_tier_count=0,
            frontier_count=0,
            human_count=0,
            deterministic_or_small_pct=100.0,
            mid_tier_pct=0.0,
            frontier_pct=0.0,
            complies_with_law_1=True,
            violations=[],
        )

    router = ExecutionRouter()
    det_or_small = 0
    mid_count = 0
    frontier_count = 0
    human_count = 0

    for step in steps:
        tier = router.route(step)
        if tier in (ExecutionTier.CODE, ExecutionTier.CACHE, ExecutionTier.SMALL_MODEL):
            det_or_small += 1
        elif tier == ExecutionTier.MID_MODEL:
            mid_count += 1
        elif tier == ExecutionTier.FRONTIER_MODEL:
            frontier_count += 1
        elif tier == ExecutionTier.HUMAN:
            human_count += 1

    total = len(steps)
    det_pct = round((det_or_small / total) * 100.0, 1)
    mid_pct = round((mid_count / total) * 100.0, 1)
    frontier_pct = round((frontier_count / total) * 100.0, 1)

    violations = []
    # Law 1 enforcement: frontier model steps must not exceed 10%
    if frontier_pct > 10.0:
        violations.append(
            f"Frontier model steps ({frontier_pct}%) exceed the 10% allowable ceiling (Law 1)."
        )
    # Ideally, deterministic or small model should handle >= 80% of steps
    if det_pct < 80.0 and total >= 5:
        violations.append(
            f"Deterministic/small model steps ({det_pct}%) below target 80-90% baseline."
        )

    complies = len(violations) == 0

    return RatioAudit(
        total_steps=total,
        deterministic_or_small_count=det_or_small,
        mid_tier_count=mid_count,
        frontier_count=frontier_count,
        human_count=human_count,
        deterministic_or_small_pct=det_pct,
        mid_tier_pct=mid_pct,
        frontier_pct=frontier_pct,
        complies_with_law_1=complies,
        violations=violations,
    )


class ExecutionRouter:
    """
    Classifies pipeline steps into the optimal execution tier following
    the 90/9/1 cost minimization decision tree.
    """

    def __init__(
        self,
        cache: Optional[Any] = None,
        tier_models: Optional[Dict[ExecutionTier, List[str]]] = None,
        cost_tracker: Optional[Any] = None,
    ):
        self.cache = cache
        self.tier_models = tier_models or DEFAULT_TIER_MODELS
        self.cost_tracker = cost_tracker

    def route(self, step: StepProfile, inputs: Optional[Dict[str, Any]] = None) -> ExecutionTier:
        """
        Classify a step according to the 90/9/1 Decision Tree:
        1. Deterministic code logic -> CODE (0 tokens)
        2. Exact/semantic cache hit -> CACHE (0 tokens)
        3. No human-like judgment needed -> CODE (0 tokens)
        4. Low complexity reasoning/rewrite/classification -> SMALL_MODEL (local Gemma/Qwen)
        5. High-stakes/novel reasoning -> FRONTIER_MODEL (or HUMAN if critical)
        6. Medium complexity reasoning -> MID_MODEL
        7. Fallback tier
        """
        inputs = inputs or {}

        # 1. Deterministic by default
        if step.is_deterministic:
            return ExecutionTier.CODE

        # 2. Check cache
        if step.is_cacheable and self.cache is not None:
            # Direct has check (e.g. MockCache or key-based caches)
            if hasattr(self.cache, "has") and self.cache.has(step.step_name, inputs):
                return ExecutionTier.CACHE
            # Semantic cache lookup
            if hasattr(self.cache, "lookup"):
                query = inputs.get("query") or inputs.get("text") or inputs.get("prompt")
                if query is not None:
                    res = self.cache.lookup(
                        query=str(query),
                        namespace=step.cache_namespace,
                        task_type=step.task_type,
                    )
                    if res.hit:
                        return ExecutionTier.CACHE

        # 3. No judgment required -> Code
        if not step.requires_judgment:
            return ExecutionTier.CODE

        # 4. High-stakes critical reasoning -> Frontier model
        if step.is_high_stakes:
            return ExecutionTier.FRONTIER_MODEL

        # 5. Low complexity judgment -> Small local model
        if step.complexity == "low":
            return ExecutionTier.SMALL_MODEL

        # 6. Medium complexity reasoning -> Mid-tier model
        if step.complexity == "medium":
            return ExecutionTier.MID_MODEL

        return step.fallback_tier

    def resolve_model(
        self,
        tier: ExecutionTier,
        task_type: Optional[str] = None,
        eval_suite: Optional[Any] = None,
    ) -> Optional[str]:
        """
        Resolve the best model for a given tier.
        Optionally consults ModelEvalSuite success-adjusted rankings.
        """
        if tier in (ExecutionTier.CODE, ExecutionTier.CACHE, ExecutionTier.HUMAN):
            return None

        # Check eval suite rankings if available
        if eval_suite is not None and hasattr(eval_suite, "storage") and task_type:
            try:
                benchmarks = eval_suite.storage.get_benchmarks(task_type=task_type)
                candidate_models = self.tier_models.get(tier, [])
                # Find matching benchmarked model in this tier
                for b in benchmarks:
                    m = b.get("model_name")
                    if m in candidate_models and b.get("success_rate", 0) >= 0.80:
                        return m
            except Exception as e:
                logger.debug(f"Eval suite resolution failed, falling back to default: {e}")

        # Default model for this tier
        models = self.tier_models.get(tier, [])
        return models[0] if models else None

    def execute_step(
        self,
        step: StepProfile,
        inputs: Dict[str, Any],
        execute_fn: Optional[Callable[[Optional[str], Dict[str, Any]], Any]] = None,
        context_spec: Optional[ContextSpec] = None,
        eval_suite: Optional[Any] = None,
    ) -> StepExecutionResult:
        """
        Execute an agent step through the complete 90/9/1 optimization lifecycle:
        1. Classify execution tier.
        2. If CACHE hit -> return cached response (0 tokens, $0.00).
        3. If CODE -> execute deterministically (0 tokens, $0.00).
        4. If HUMAN -> return staging flag for human approval.
        5. Apply ContextBuilder budget enforcement (<8k tokens target).
        6. Resolve optimal model for tier.
        7. Execute via execute_fn and track tokens/cost.
        8. If cacheable and successful -> store in SemanticCache.
        """
        start_t = time.perf_counter()
        tier = self.route(step, inputs)
        query = inputs.get("query") or inputs.get("text") or inputs.get("prompt") or str(inputs)

        # 1. Cache Tier
        if tier == ExecutionTier.CACHE:
            cached_output = None
            if hasattr(self.cache, "lookup"):
                res = self.cache.lookup(
                    query=str(query),
                    namespace=step.cache_namespace,
                    task_type=step.task_type,
                )
                if res.hit:
                    if res.entry is not None:
                        cached_output = res.entry.response
                    elif hasattr(res, "cached_response"):
                        cached_output = res.cached_response
            elif hasattr(self.cache, "cached"):
                cached_output = self.cache.cached.get((step.step_name, inputs.get("query")))

            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return StepExecutionResult(
                step_name=step.step_name,
                tier=ExecutionTier.CACHE,
                model_used=None,
                output=cached_output or "cached_result",
                tokens_used=0,
                cost_usd=0.0,
                latency_ms=round(elapsed_ms, 2),
                cache_hit=True,
                rationale=f"Resolved via semantic/exact cache for '{step.step_name}' (0 tokens, $0.00).",
            )

        # 2. Code Tier
        if tier == ExecutionTier.CODE:
            output = None
            if execute_fn is not None:
                output = execute_fn(None, inputs)
            else:
                output = {"status": "success", "step": step.step_name, "mode": "deterministic"}

            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return StepExecutionResult(
                step_name=step.step_name,
                tier=ExecutionTier.CODE,
                model_used=None,
                output=output,
                tokens_used=0,
                cost_usd=0.0,
                latency_ms=round(elapsed_ms, 2),
                cache_hit=False,
                rationale="Executed deterministically via code logic (0 tokens, $0.00).",
            )

        # 3. Human Tier
        if tier == ExecutionTier.HUMAN:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return StepExecutionResult(
                step_name=step.step_name,
                tier=ExecutionTier.HUMAN,
                model_used=None,
                output=None,
                tokens_used=0,
                cost_usd=0.0,
                latency_ms=round(elapsed_ms, 2),
                requires_human=True,
                rationale="Critical high-stakes step staged for human operator approval.",
            )

        # 4. Model Tiers (SMALL_MODEL, MID_MODEL, FRONTIER_MODEL)
        # Apply Context Builder if spec declared
        spec = context_spec or step.context_spec
        processed_inputs = inputs
        tokens_in = estimate_object_tokens(inputs)

        if spec is not None:
            built = build_context(spec=spec, available=inputs)
            processed_inputs = dict(built)
            tokens_in = built.estimated_tokens

        model_name = self.resolve_model(tier, task_type=step.task_type, eval_suite=eval_suite)

        # Execute step
        output = None
        prompt_tokens = tokens_in
        completion_tokens = 0

        if execute_fn is not None:
            exec_res = execute_fn(model_name, processed_inputs)
            if isinstance(exec_res, dict) and "output" in exec_res:
                output = exec_res["output"]
                prompt_tokens = exec_res.get("prompt_tokens", prompt_tokens)
                completion_tokens = exec_res.get(
                    "completion_tokens", estimate_object_tokens(output)
                )
            else:
                output = exec_res
                completion_tokens = estimate_object_tokens(output)
        else:
            output = f"Simulated output from {model_name} for step {step.step_name}"
            completion_tokens = estimate_object_tokens(output)

        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        total_tokens = prompt_tokens + completion_tokens

        # Calculate cost
        pricing = DEFAULT_PRICING.get(model_name or "") or ModelPricing(
            model_name=model_name or "unknown", input_cost_per_1m=1.0, output_cost_per_1m=3.0
        )
        cost_usd = pricing.calculate_cost(prompt_tokens, completion_tokens)

        # Store in cache if cacheable
        if step.is_cacheable and self.cache is not None and hasattr(self.cache, "store"):
            try:
                self.cache.store(
                    query=str(query),
                    response=output,
                    namespace=step.cache_namespace,
                    task_type=step.task_type or "qa",
                    tokens_saved=total_tokens,
                    cost_saved_usd=cost_usd,
                )
            except Exception as e:
                logger.warning(f"Failed storing step result in cache: {e}")

        # Track with cost tracker if available
        if self.cost_tracker is not None and hasattr(self.cost_tracker, "record_call"):
            try:
                self.cost_tracker.record_call(
                    model_name=model_name or "unknown",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    agent_id=step.step_name,
                )
            except Exception as e:
                logger.warning(f"Failed logging spend to cost tracker: {e}")

        return StepExecutionResult(
            step_name=step.step_name,
            tier=tier,
            model_used=model_name,
            output=output,
            tokens_used=total_tokens,
            cost_usd=cost_usd,
            latency_ms=round(elapsed_ms, 2),
            cache_hit=False,
            requires_human=False,
            rationale=f"Routed to {tier.value} tier using model '{model_name}'.",
        )


def profiled_step(profile: StepProfile, router: Optional[ExecutionRouter] = None):
    """
    Decorator for pipeline steps declaring a StepProfile.
    Routes execution through the ExecutionRouter automatically.
    """

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            r = router or ExecutionRouter()
            inputs = kwargs if kwargs else {"args": args}
            tier = r.route(profile, inputs)
            if tier == ExecutionTier.CODE:
                return fn(*args, **kwargs)
            # Route with wrapper execution
            result = r.execute_step(profile, inputs, execute_fn=lambda m, i: fn(*args, **kwargs))
            return result.output

        wrapper.step_profile = profile
        return wrapper

    return decorator
