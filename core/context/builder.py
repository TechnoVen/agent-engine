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

from core.context.models import (
    ContentAuthority,
    ContentTrust,
    ContextItem,
    classify_ingress_content,
)

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
    untrusted_fields: List[str] = field(default_factory=list)
    enforce_untrusted_envelopes: bool = True
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
        items: Optional[Dict[str, ContextItem]] = None,
    ):
        super().__init__(data)
        self.data = data
        self.estimated_tokens = estimated_tokens
        self.original_tokens = original_tokens
        self.was_truncated = was_truncated
        self.truncated_fields = truncated_fields or []
        self.warnings = warnings or []
        self.items: Dict[str, ContextItem] = items or {}

    def get_item(self, key: str) -> Optional[ContextItem]:
        """Retrieve the typed ContextItem for a given field key."""
        return self.items.get(key)

    @property
    def has_untrusted_content(self) -> bool:
        """True if any context item contains untrusted external data."""
        return any(item.is_untrusted for item in self.items.values())

    def get_untrusted_items(self) -> List[ContextItem]:
        """Return all items labeled as untrusted external content."""
        return [item for item in self.items.values() if item.is_untrusted]

    def format_prompt_block(self, key: str) -> str:
        """Format an item for prompt rendering, wrapping in envelopes if untrusted."""
        if key in self.items:
            return self.items[key].format_envelope()
        return str(self.get(key, ""))

    def render_full_prompt(self) -> str:
        """Render all context items sequentially into an envelope-isolated prompt string."""
        blocks = []
        for k, v in self.items.items():
            blocks.append(f"### {k.upper()}\n{v.format_envelope()}")
        return "\n\n".join(blocks)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize envelope into a standard dictionary."""
        return {
            "data": dict(self.data),
            "estimated_tokens": self.estimated_tokens,
            "original_tokens": self.original_tokens,
            "was_truncated": self.was_truncated,
            "truncated_fields": self.truncated_fields,
            "warnings": self.warnings,
            "has_untrusted_content": self.has_untrusted_content,
            "untrusted_fields": [k for k, v in self.items.items() if v.is_untrusted],
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

    # -----------------------------------------------------------------------
    # Preferred Backend Ingestion Methods (Derived Ingestion Authority)
    # -----------------------------------------------------------------------
    def add_system_policy(
        self,
        content: str,
        label: str = "system_policy",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextItem:
        return ContextItem.from_system_policy(content=content, label=label, metadata=metadata)

    def add_project_instruction(
        self,
        content: str,
        project_id: Optional[str] = None,
        label: str = "project_instruction",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextItem:
        return ContextItem.from_project_instruction(
            content=content, project_id=project_id, label=label, metadata=metadata
        )

    def add_user_directive(
        self,
        content: str,
        label: str = "user_directive",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextItem:
        return ContextItem.from_user_directive(content=content, label=label, metadata=metadata)

    def add_internal_state(
        self,
        content: str,
        label: str = "internal_state",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextItem:
        return ContextItem.from_internal_state(content=content, label=label, metadata=metadata)

    def add_external_content(
        self,
        content: str,
        source_id: str,
        source_type: str = "external",
        metadata: Optional[Dict[str, Any]] = None,
        raw_content: Optional[str] = None,
    ) -> ContextItem:
        return ContextItem.from_external_content(
            content=content,
            source_id=source_id,
            source_type=source_type,
            metadata=metadata,
            raw_content=raw_content,
        )

    def add_tool_result(
        self,
        tool_name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        raw_content: Optional[str] = None,
    ) -> ContextItem:
        return ContextItem.from_tool_result(
            tool_name=tool_name,
            content=content,
            metadata=metadata,
            raw_content=raw_content,
        )

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
        3. Enforce backend ingress trust boundaries (data may downgrade, never self-upgrade).
        4. Conditionally execute RAG retrieval only if allow_retrieval=True.
        5. Enforce token budget (<8,000 target, hard ceiling) while preserving provenance.
        """
        # 1. Validate required fields
        for k in spec.required_fields:
            if k not in available:
                if spec.strict_required:
                    raise MissingContextFieldError(
                        f"Required context field '{k}' is missing from input payload."
                    )

        # 2. Filter whitelisted fields and construct typed ContextItem objects
        ctx: Dict[str, Any] = {}
        context_items: Dict[str, ContextItem] = {}

        candidate_keys = list(spec.required_fields) + [
            k for k in spec.optional_fields if k not in spec.required_fields
        ]
        for k in candidate_keys:
            if k in available:
                val = available[k]
                is_untrusted_field = k in spec.untrusted_fields or k.startswith(
                    ("untrusted_", "external_", "third_party_", "tool_", "retrieved_")
                )

                if isinstance(val, ContextItem):
                    # Ingress boundary check: untrusted fields or callers cannot self-upgrade
                    if is_untrusted_field:
                        # Downgrade to UNTRUSTED_CONTENT / EVIDENCE fail-closed
                        item = ContextItem.from_external_content(
                            content=val.content,
                            source_id=val.provenance.source_id if val.provenance else k,
                            source_type=val.provenance.source_type
                            if val.provenance
                            else "untrusted_field",
                            metadata=val.provenance.metadata if val.provenance else {},
                            raw_content=val.raw_content,
                        )
                    elif k in ("prompt", "user_prompt", "query", "user_directive", "goal"):
                        # User directive ingress
                        item = val
                    elif k == "system_prompt":
                        item = val
                    else:
                        # External payloads claiming SYSTEM or USER_DIRECTIVE on arbitrary fields are downgraded
                        if val.trust in (
                            ContentTrust.SYSTEM,
                            ContentTrust.TRUSTED_USER,
                        ) and val.authority in (
                            ContentAuthority.SYSTEM_POLICY,
                            ContentAuthority.USER_DIRECTIVE,
                        ):
                            item = ContextItem.from_external_content(
                                content=val.content,
                                source_id=val.provenance.source_id if val.provenance else k,
                                source_type="unauthorized_authority_claim",
                                metadata={
                                    "claimed_trust": val.trust.value,
                                    "claimed_authority": val.authority.value,
                                },
                                raw_content=val.raw_content,
                            )
                        else:
                            item = val
                elif isinstance(val, dict) and (
                    "content" in val or "trust" in val or "authority" in val
                ):
                    # Caller-supplied DTO claiming trust/authority: classify via ingress boundary
                    content_str = str(val.get("content", ""))
                    if is_untrusted_field:
                        item = ContextItem.from_external_content(
                            content=content_str,
                            source_id=k,
                            source_type="untrusted_dto",
                            metadata=val.get("metadata", {}),
                        )
                    else:
                        item = classify_ingress_content(
                            content=content_str,
                            ingress_channel="user"
                            if k in ("prompt", "user_prompt", "query", "user_directive", "goal")
                            else "external_api",
                            claimed_trust=val.get("trust"),
                            claimed_authority=val.get("authority"),
                            source_id=k,
                            metadata=val.get("metadata"),
                        )
                else:
                    if is_untrusted_field:
                        item = ContextItem.from_external_content(
                            content=str(val) if not isinstance(val, str) else val,
                            source_id=k,
                            source_type="untrusted_field",
                        )
                    elif k in ("prompt", "user_prompt", "query", "user_directive", "goal"):
                        item = ContextItem.from_user_directive(
                            content=str(val) if not isinstance(val, str) else val,
                            label=k,
                        )
                    else:
                        item = ContextItem.from_internal_state(
                            content=str(val) if not isinstance(val, str) else val,
                            label=k,
                        )

                context_items[k] = item
                if spec.enforce_untrusted_envelopes and item.is_untrusted:
                    ctx[k] = item.format_envelope()
                elif isinstance(val, ContextItem):
                    ctx[k] = item.format_envelope() if item.is_untrusted else item.content
                else:
                    ctx[k] = val

        # Add system prompt if specified
        if spec.system_prompt:
            sys_item = ContextItem.from_system_policy(
                content=spec.system_prompt,
                label="system_prompt",
            )
            context_items["system_prompt"] = sys_item
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

                rag_str = str(raw_rag) if not isinstance(raw_rag, str) else raw_rag
                rag_item = ContextItem.from_external_content(
                    content=rag_str,
                    source_id="rag_retrieval",
                    source_type="retrieval",
                )
                context_items["retrieved_context"] = rag_item
                if spec.enforce_untrusted_envelopes:
                    ctx["retrieved_context"] = rag_item.format_envelope()
                else:
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

        # Update items with child derivations preserving trust, authority, and raw provenance
        final_items: Dict[str, ContextItem] = {}
        for k, item in context_items.items():
            if k in truncated_fields and k in truncated_dict:
                truncated_text = str(truncated_dict[k])
                derived = item.derive_child(
                    new_content=truncated_text,
                    transformation_type="truncated",
                    metadata_update={
                        "truncated_tokens": estimate_object_tokens(truncated_text),
                    },
                )
                final_items[k] = derived
                if spec.enforce_untrusted_envelopes and derived.is_untrusted:
                    truncated_dict[k] = derived.format_envelope()
            else:
                final_items[k] = item

        return BuiltContext(
            data=truncated_dict,
            estimated_tokens=final_tokens,
            original_tokens=original_tokens,
            was_truncated=was_truncated,
            truncated_fields=truncated_fields,
            warnings=warnings,
            items=final_items,
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
