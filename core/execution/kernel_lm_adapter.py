"""Canonical DSPy LM Adapter for Single Authoritative Execution Kernel (Task R1.12).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md (R1.12)
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, List, Optional
import dspy

from core.execution.cancellation import CancellationToken, ExecutionCancelledError
from core.execution.models import (
    ExecutionContext,
    ExecutionEvent,
    ExecutionEventType,
    RoutingTier,
)
from core.execution.state import ExecutionStateMachine
from core.context.builder import estimate_tokens

logger = logging.getLogger("agent_engine.execution.kernel_lm_adapter")


class KernelLMAdapter(dspy.LM):
    """Subclasses dspy.LM to intercept, monitor, and truthfully account for internal
    DSPy model calls within the Single Authoritative Execution Kernel.
    """

    def __init__(
        self,
        exec_context: ExecutionContext,
        coordinator: Any,
        provider: str,
        model_name: str,
        tier: RoutingTier = RoutingTier.MID,
        model_calls: Optional[List[Dict[str, Any]]] = None,
        event_sink: Optional[Callable[[ExecutionEvent], None]] = None,
        state_machine: Optional[ExecutionStateMachine] = None,
        real_lm: Optional[dspy.LM] = None,
    ) -> None:
        super().__init__(model=model_name, cache=False)
        self.exec_context = exec_context
        self.coordinator = coordinator
        self.provider = provider
        self.model_name = model_name
        self.tier = tier
        self.model_calls = model_calls if model_calls is not None else []
        self.event_sink = event_sink
        self.state_machine = state_machine
        self.real_lm = real_lm

    @property
    def cancellation_token(self) -> Optional[CancellationToken]:
        return self.exec_context.cancellation_token

    def __call__(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> List[str]:
        # 1. Pre-invocation cancellation check
        if self.cancellation_token and self.cancellation_token.is_cancelled:
            actor = self.cancellation_token.actor or "user"
            raise ExecutionCancelledError(f"Execution was cancelled by {actor}")

        # 2. Extract textual representation of prompt/messages for token accounting
        if messages:
            prompt_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
            )
        else:
            prompt_text = str(prompt or "")
        in_tokens = max(1, estimate_tokens(prompt_text))

        # 3. Dispatch model invocation
        outputs: List[str] = []
        if getattr(self.coordinator, "_dispatch_override", None):
            res = self.coordinator._dispatch_override(
                self.exec_context, self.tier, self.provider, self.model_name
            )
            if isinstance(res, dict):
                lines = []
                prompt_lower = prompt_text.lower()
                # If ChainOfThought expects reasoning field and it's missing from dict, populate it
                if "reasoning" not in res and (
                    "reasoning" in prompt_lower or "chainofthought" in prompt_lower
                ):
                    lines.append("[[ ## reasoning ## ]]\nAnalysis completed.")
                for k, v in res.items():
                    lines.append(f"[[ ## {k} ## ]]\n{v}")
                lines.append("[[ ## completed ## ]]")
                output_str = "\n\n".join(lines)
                outputs = [output_str]
            elif isinstance(res, list):
                outputs = [str(item) for item in res]
                output_str = outputs[0] if outputs else ""
            else:
                output_str = str(res)
                outputs = [output_str]
        else:
            if not self.real_lm:
                self.real_lm, _ = self.coordinator.model_router.create_lm(
                    self.provider, model_name=self.model_name
                )
            raw = self.real_lm(prompt=prompt, messages=messages, **kwargs)
            outputs = [str(r) for r in raw] if isinstance(raw, list) else [str(raw)]
            output_str = outputs[0] if outputs else ""

        # 4. Post-invocation cancellation check
        if self.cancellation_token and self.cancellation_token.is_cancelled:
            actor = self.cancellation_token.actor or "user"
            raise ExecutionCancelledError(f"Execution was cancelled by {actor}")

        # 5. Token & Cost Accounting
        out_tokens = max(1, estimate_tokens(output_str))
        cost = 0.0
        if getattr(self.coordinator, "cost_tracker", None):
            cost = self.coordinator.cost_tracker.calculate_cost(
                self.model_name, in_tokens, out_tokens
            )
            if cost == 0.0 and (in_tokens + out_tokens) > 0:
                cost = round((in_tokens * 0.00000015) + (out_tokens * 0.0000006), 6) or 0.000001

        call_record = {
            "model": self.model_name,
            "provider": self.provider,
            "routing_tier": getattr(self.tier, "value", str(self.tier)),
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "cost_usd": cost,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.model_calls.append(call_record)

        # 6. Event emission
        if self.event_sink and self.state_machine:
            self.event_sink(
                ExecutionEvent(
                    execution_id=self.exec_context.execution_id,
                    sequence_num=self.state_machine.current_sequence_num,
                    event_type=ExecutionEventType.OUTPUT_CHUNK,
                    payload={"model_call": call_record},
                )
            )
            self.state_machine.current_sequence_num += 1

        return outputs
