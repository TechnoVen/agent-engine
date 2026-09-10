"""
core/context/builder.py

Context Minimization Builder implementing Law 3:
- Every model call includes only what the step needs.
- Average target < 8,000 tokens, absolute ceiling 32,000 tokens.
- Never pass raw, un-filtered objects.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ContextSpec:
    required_fields: List[str]
    optional_fields: List[str] = field(default_factory=list)
    max_tokens: int = 4000
    allow_retrieval: bool = False


def estimate_tokens(text: str) -> int:
    """Rough token estimation (approx 4 chars per token for English/code)."""
    return max(1, len(text) // 4)


def truncate_to_budget(context: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
    """Truncate fields in context if total estimated tokens exceed budget."""
    hard_ceiling = min(max_tokens, 32000)
    current_tokens = sum(estimate_tokens(str(v)) for v in context.values())

    if current_tokens <= hard_ceiling:
        return context

    # Truncate largest text fields until within budget
    truncated = dict(context)
    for k, v in truncated.items():
        if isinstance(v, str) and len(v) > 200:
            excess = current_tokens - hard_ceiling
            char_cut = excess * 4
            truncated[k] = v[: max(100, len(v) - char_cut)] + " ...[truncated for token budget]"
            current_tokens = sum(estimate_tokens(str(val)) for val in truncated.values())
            if current_tokens <= hard_ceiling:
                break

    return truncated


def build_context(
    spec: ContextSpec,
    available: Dict[str, Any],
    retrieval_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """
    Build a minimal context dictionary according to ContextSpec:
    1. Filter only declared required and optional fields.
    2. Add RAG retrieval only if explicitly allowed.
    3. Enforce token budget (< 8,000 target, hard ceiling 32,000).
    """
    ctx: Dict[str, Any] = {}

    for k in spec.required_fields:
        if k in available:
            ctx[k] = available[k]

    for k in spec.optional_fields:
        if k in available:
            ctx[k] = available[k]

    if spec.allow_retrieval and retrieval_fn is not None:
        ctx["retrieved_context"] = retrieval_fn(ctx)

    budgeted_ctx = truncate_to_budget(ctx, spec.max_tokens)
    return budgeted_ctx
