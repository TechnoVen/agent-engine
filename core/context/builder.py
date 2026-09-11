"""Agent Engine - Context Minimization & Budget Enforcement (Task 1.8).

Implements Law 3 (Keep Context Small) and Pattern 3.4 (Context Minimization):
- Average target < 8,000 tokens, absolute ceiling 32,000 tokens.
- Strict field whitelisting (required and optional fields).
- Priority-aware smart truncation.
- Retrieval (RAG) conditional gating and budgeting.
- Accurate token estimation via tiktoken with heuristic fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Cache the tiktoken encoding instance to avoid repeated initialization
_TIKTOKEN_ENCODER = None


class MissingContextFieldError(ValueError):
    """Raised when a required context field is missing from available data."""

    pass


class ContextBudgetExceededError(ValueError):
    """Raised when context cannot be brought within hard ceiling even after truncation."""

    pass


def _get_tiktoken_encoder():
    """Retrieve cl100k_base tokenizer if tiktoken is available."""
    global _TIKTOKEN_ENCODER
    if _TIKTOKEN_ENCODER is None:
        try:
            import tiktoken

            _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _TIKTOKEN_ENCODER = False
    return _TIKTOKEN_ENCODER if _TIKTOKEN_ENCODER is not False else None


def estimate_tokens(text: str) -> int:
    """
    Accurate token estimation using tiktoken (cl100k_base) with fast character-ratio fallback.
    Average ratio: ~4 characters per token.
    """
    if not text:
        return 0
    enc = _get_tiktoken_encoder()
    if enc is not None:
        try:
            return len(enc.encode(str(text), disallowed_special=()))
        except Exception:
            pass
    return max(1, len(str(text)) // 4)


def estimate_object_tokens(obj: Any) -> int:
    """Recursively estimate token count for any Python data structure."""
    if obj is None:
        return 0
    if isinstance(obj, str):
        return estimate_tokens(obj)
    if isinstance(obj, (int, float, bool)):
        return max(1, len(str(obj)) // 4)
    if isinstance(obj, (list, tuple, set)):
        return sum(estimate_object_tokens(item) for item in obj)
    if isinstance(obj, dict):
        return sum(estimate_tokens(str(k)) + estimate_object_tokens(v) for k, v in obj.items())
    return estimate_tokens(str(obj))


@dataclass
class ContextSpec:
    """
    Specification declaring the exact context requirements and budget for a model call or agent step.
    """

    required_fields: List[str]
    optional_fields: List[str] = field(default_factory=list)
    max_tokens: int = 4000
    hard_ceiling_tokens: int = 32000
    allow_retrieval: bool = False
    retrieval_budget_tokens: int = 2000
    truncation_strategy: str = "priority"  # "priority" | "largest_first" | "tail"
    field_priorities: Dict[str, int] = field(default_factory=dict)  # higher = preserve longest
    system_prompt: Optional[str] = None
    strict_required: bool = True


class BuiltContext(dict):
    """
    Sanitized, whitelisted, budgeted context payload.
    Subclasses dict for 100% backwards compatibility with standard dict indexing and iteration.
    """

    def __init__(
        self,
        data: Dict[str, Any],
        estimated_tokens: int = 0,
        original_tokens: int = 0,
        was_truncated: bool = False,
        truncated_fields: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ):
        super().__init__(data)
        self.data = data
        self.estimated_tokens = estimated_tokens
        self.original_tokens = original_tokens
        self.was_truncated = was_truncated
        self.truncated_fields = truncated_fields or []
        self.warnings = warnings or []

    def to_dict(self) -> Dict[str, Any]:
        """Serialize envelope into a standard dictionary."""
        return {
            "data": dict(self.data),
            "estimated_tokens": self.estimated_tokens,
            "original_tokens": self.original_tokens,
            "was_truncated": self.was_truncated,
            "truncated_fields": self.truncated_fields,
            "warnings": self.warnings,
        }


def truncate_to_budget(
    context: Dict[str, Any],
    max_tokens: int,
    priorities: Optional[Dict[str, int]] = None,
    hard_ceiling: int = 32000,
) -> Tuple[Dict[str, Any], bool, List[str], List[str]]:
    """
    Truncate fields in context if total estimated tokens exceed target budget or hard ceiling.
    Returns: (truncated_dict, was_truncated, truncated_fields, warnings)
    """
    budget = min(max_tokens, hard_ceiling)
    field_priorities = priorities or {}
    truncated_fields: List[str] = []
    warnings: List[str] = []
    was_truncated = False

    current_tokens = sum(estimate_object_tokens(v) for v in context.values())

    if current_tokens > 8000:
        msg = f"Context size ({current_tokens:,} tokens) exceeds recommended < 8,000 target. Context reduction active."
        warnings.append(msg)
        logger.info(msg)

    if current_tokens <= budget:
        return dict(context), False, [], warnings

    was_truncated = True
    truncated = dict(context)

    # Sort fields by priority ascending (lowest priority truncated first), then by size descending
    candidate_keys = sorted(
        truncated.keys(),
        key=lambda k: (field_priorities.get(k, 5), -estimate_object_tokens(truncated[k])),
    )

    suffix = " ...[truncated for token budget]"
    suffix_tokens = estimate_tokens(suffix)

    for k in candidate_keys:
        if current_tokens <= budget:
            break

        v = truncated[k]
        tokens_other = sum(estimate_object_tokens(truncated[ok]) for ok in truncated if ok != k)

        if isinstance(v, str) and len(v) > 30:
            if tokens_other < budget:
                # We can keep whatever fits within budget - tokens_other
                allowed_tokens = max(5, budget - tokens_other - suffix_tokens)
                # Cut characters conservatively (~3 chars/token) to guarantee token fit
                allowed_chars = max(10, allowed_tokens * 3)
                if len(v) > allowed_chars:
                    truncated[k] = v[:allowed_chars] + suffix
                    if k not in truncated_fields:
                        truncated_fields.append(k)
            else:
                # Other higher priority fields already meet/exceed budget, reduce this low-priority field aggressively
                truncated[k] = v[:20] + suffix
                if k not in truncated_fields:
                    truncated_fields.append(k)

            current_tokens = sum(estimate_object_tokens(val) for val in truncated.values())

        elif isinstance(v, list) and len(v) > 1:
            allowed_tokens = max(0, budget - tokens_other)
            kept_items = []
            running_tokens = 0
            for item in v:
                item_tok = estimate_object_tokens(item)
                if running_tokens + item_tok <= allowed_tokens:
                    kept_items.append(item)
                    running_tokens += item_tok
                else:
                    break

            dropped_count = len(v) - len(kept_items)
            if dropped_count > 0:
                kept_items.append(f"... [{dropped_count} items truncated for token budget]")
                truncated[k] = kept_items
                if k not in truncated_fields:
                    truncated_fields.append(k)
                current_tokens = sum(estimate_object_tokens(val) for val in truncated.values())

    # If still exceeding budget after priority pass, perform hard truncation on remaining fields
    if current_tokens > budget:
        for k in candidate_keys:
            if current_tokens <= budget:
                break
            v = truncated[k]
            if isinstance(v, str) and len(v) > 40:
                truncated[k] = v[:20] + suffix
                if k not in truncated_fields:
                    truncated_fields.append(k)
                current_tokens = sum(estimate_object_tokens(val) for val in truncated.values())

    return truncated, was_truncated, truncated_fields, warnings


def truncate_message_history(
    messages: List[Dict[str, Any]],
    max_tokens: int,
    preserve_system: bool = True,
) -> List[Dict[str, Any]]:
    """
    Compress a conversation message history into a target token budget.
    Preserves the initial system message (if present) and the latest user/assistant turn.
    Prunes intermediate messages from oldest to newest.
    """
    if not messages:
        return []

    total_tokens = sum(estimate_object_tokens(m) for m in messages)
    if total_tokens <= max_tokens:
        return list(messages)

    system_msg: Optional[Dict[str, Any]] = None
    work_messages = list(messages)

    if preserve_system and work_messages and work_messages[0].get("role") == "system":
        system_msg = work_messages.pop(0)

    # Always preserve the most recent message
    if not work_messages:
        return [system_msg] if system_msg else []

    latest_turn = work_messages.pop(-1)
    available_budget = max_tokens - estimate_object_tokens(latest_turn)
    if system_msg:
        available_budget -= estimate_object_tokens(system_msg)

    # Keep messages from the end moving backwards
    kept_intermediate: List[Dict[str, Any]] = []
    for msg in reversed(work_messages):
        msg_tokens = estimate_object_tokens(msg)
        if available_budget - msg_tokens >= 0:
            kept_intermediate.insert(0, msg)
            available_budget -= msg_tokens
        else:
            break

    result: List[Dict[str, Any]] = []
    if system_msg:
        result.append(system_msg)
    result.extend(kept_intermediate)
    result.append(latest_turn)

    return result


class ContextBuilder:
    """
    Context minimization engine enforcing field whitelisting, RAG retrieval gating,
    and token budget ceilings per step.
    """

    def __init__(self, default_hard_ceiling: int = 32000):
        self.default_hard_ceiling = default_hard_ceiling

    def build(
        self,
        spec: ContextSpec,
        available: Dict[str, Any],
        retrieval_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> BuiltContext:
        """
        Build a minimal, budgeted context according to ContextSpec:
        1. Validate presence of declared required fields.
        2. Filter only declared required and optional fields (whitelisting).
        3. Conditionally execute RAG retrieval only if allow_retrieval=True.
        4. Enforce token budget (<8,000 target, hard ceiling).
        """
        # 1. Validate required fields
        for k in spec.required_fields:
            if k not in available:
                if spec.strict_required:
                    raise MissingContextFieldError(
                        f"Required context field '{k}' is missing from input payload."
                    )

        # 2. Filter whitelisted fields
        ctx: Dict[str, Any] = {}
        for k in spec.required_fields:
            if k in available:
                ctx[k] = available[k]

        for k in spec.optional_fields:
            if k in available:
                ctx[k] = available[k]

        # Add system prompt if specified
        if spec.system_prompt:
            ctx["system_prompt"] = spec.system_prompt

        # 3. Conditional RAG retrieval
        if spec.allow_retrieval and retrieval_fn is not None:
            raw_rag = retrieval_fn(ctx)
            if raw_rag:
                # Enforce RAG budget
                rag_tokens = estimate_object_tokens(raw_rag)
                if spec.retrieval_budget_tokens and rag_tokens > spec.retrieval_budget_tokens:
                    if isinstance(raw_rag, str):
                        char_limit = spec.retrieval_budget_tokens * 4
                        raw_rag = raw_rag[:char_limit] + " ...[truncated RAG context]"
                    elif isinstance(raw_rag, list):
                        raw_rag = raw_rag[: max(1, spec.retrieval_budget_tokens // 100)]
                ctx["retrieved_context"] = raw_rag

        # Calculate original tokens before truncation
        original_tokens = sum(estimate_object_tokens(v) for v in ctx.values())

        # 4. Truncate to budget
        truncated_dict, was_truncated, truncated_fields, warnings = truncate_to_budget(
            context=ctx,
            max_tokens=spec.max_tokens,
            priorities=spec.field_priorities,
            hard_ceiling=spec.hard_ceiling_tokens or self.default_hard_ceiling,
        )

        final_tokens = sum(estimate_object_tokens(v) for v in truncated_dict.values())

        return BuiltContext(
            data=truncated_dict,
            estimated_tokens=final_tokens,
            original_tokens=original_tokens,
            was_truncated=was_truncated,
            truncated_fields=truncated_fields,
            warnings=warnings,
        )


def build_context(
    spec: ContextSpec,
    available: Dict[str, Any],
    retrieval_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> BuiltContext:
    """
    Public convenience function matching standard Agent Engine interface.
    Returns BuiltContext (which inherits from dict for 100% backward compatibility).
    """
    builder = ContextBuilder()
    return builder.build(spec=spec, available=available, retrieval_fn=retrieval_fn)
