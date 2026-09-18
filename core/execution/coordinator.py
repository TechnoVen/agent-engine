"""Canonical ExecutionCoordinator Service (Task R1.3).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.context.builder import ContextSpec, build_context, estimate_tokens
from core.execution.models import (
    Execution,
    ExecutionContext,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    RoutingTier,
    VerificationResult,
    generate_execution_id,
)
from core.execution.state import ExecutionStateMachine
from core.router.model_router import ModelRouter
from core.safety.pending import PendingOperationRegistry
from core.safety.policy import PolicyDecision, PolicyEngine
from core.storage import get_storage_backend
from core.storage.base import StorageBackend
from core.telemetry.cost import CostTracker

logger = logging.getLogger("agent_engine.execution.coordinator")


class ExecutionBlockedError(Exception):
    """Raised when safety policy or budget limits block execution pre-flight."""

    pass


class ExecutionCoordinator:
    """
    Authoritative service orchestrating the 10-phase execution lifecycle.
    All product surfaces (Chat, DSPy, Skills, Tools, Workflows, MCP, ACP)
    must dispatch through this coordinator. Direct model/tool invocation is forbidden.
    """

    def __init__(
        self,
        storage: Optional[StorageBackend] = None,
        policy_engine: Optional[PolicyEngine] = None,
        cost_tracker: Optional[CostTracker] = None,
        model_router: Optional[ModelRouter] = None,
        pending_registry: Optional[PendingOperationRegistry] = None,
        dispatch_override: Optional[
            Callable[[ExecutionContext, RoutingTier, str, str], Any]
        ] = None,
    ):
        self.storage = storage or get_storage_backend()
        self.policy_engine = policy_engine or PolicyEngine()
        self.cost_tracker = cost_tracker or CostTracker(storage=self.storage)
        self.model_router = model_router or ModelRouter()
        self.pending_registry = pending_registry or PendingOperationRegistry()
        self._dispatch_override = dispatch_override
        self._active_executions: Dict[str, Execution] = {}

    def _resolve_routing(self, request: ExecutionRequest) -> Tuple[RoutingTier, str, str]:
        """Resolve routing tier, provider, and concrete model name."""
        # 1. Respect explicit tier preference if supplied
        tier = request.target_tier or RoutingTier.MID

        # 2. Check if specific model was requested
        if request.model_preference:
            pref = request.model_preference.lower()
            if "gpt-4o-mini" in pref or "gemini-2.0-flash" in pref or "haiku" in pref:
                tier = RoutingTier.MID
            elif "gpt-4o" in pref or "sonnet" in pref or "opus" in pref or "gemini-1.5-pro" in pref:
                tier = RoutingTier.FRONTIER
            elif "qwen" in pref or "ollama" in pref or "llama" in pref:
                tier = RoutingTier.LOCAL

            provider = "ollama" if tier == RoutingTier.LOCAL else "openai"
            if "gemini" in pref:
                provider = "gemini"
            elif "claude" in pref or "anthropic" in pref:
                provider = "anthropic"
            elif "deepseek" in pref:
                provider = "deepseek"
            return tier, provider, request.model_preference

        # 3. Default tier models
        if tier == RoutingTier.LOCAL:
            return tier, "ollama", "qwen2.5-coder:3b"
        elif tier == RoutingTier.FRONTIER:
            return tier, "openai", "gpt-4o"
        elif tier == RoutingTier.CODE:
            return tier, "local", "deterministic_code"
        elif tier == RoutingTier.CACHE:
            return tier, "local", "semantic_cache"
        else:
            return RoutingTier.MID, "gemini", "gemini-2.0-flash"

    def _verify_output(
        self,
        task_type: str,
        outputs: Dict[str, Any],
        expected_schema: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """Apply verification checks on execution outputs."""
        checks = []

        # Check 1: Non-empty output presence
        has_content = bool(outputs and any(v is not None for v in outputs.values()))
        checks.append({"name": "non_empty", "passed": has_content})

        if not has_content:
            return VerificationResult(
                passed=False,
                strategy="basic_integrity",
                checks=checks,
                error="Execution yielded completely empty outputs",
            )

        # Check 2: Schema validation if expected schema provided
        if expected_schema:
            missing_keys = [k for k in expected_schema if k not in outputs]
            checks.append(
                {"name": "schema_keys", "passed": len(missing_keys) == 0, "missing": missing_keys}
            )
            if missing_keys:
                return VerificationResult(
                    passed=False,
                    strategy="schema",
                    checks=checks,
                    error=f"Output missing required schema keys: {missing_keys}",
                )

        return VerificationResult(
            passed=True,
            strategy="standard",
            checks=checks,
            error=None,
        )

    async def execute(
        self,
        request: ExecutionRequest,
        cancellation_token: Optional[asyncio.Event] = None,
        event_listener: Optional[Callable[[ExecutionEvent], None]] = None,
    ) -> ExecutionResult:
        """
        Universal 10-phase execution entry point.
        """
        start_time = time.perf_counter()

        # Phase 1: Request validation & Execution creation
        exec_id = generate_execution_id()
        execution = Execution(
            id=exec_id,
            project_id=request.project_id,
            session_id=request.session_id,
            request=request,
            status=ExecutionStatus.CREATED,
        )

        def combined_event_sink(event: ExecutionEvent) -> None:
            # Persist event to storage
            try:
                self.storage.record_execution_event(event.model_dump())
            except Exception as ex:
                logger.error("Failed to persist execution event: %s", ex)
            # Notify external listener
            if event_listener:
                try:
                    event_listener(event)
                except Exception as ex:
                    logger.error("Event listener error: %s", ex)

        state_machine = ExecutionStateMachine(execution, event_sink=combined_event_sink)
        self.storage.create_execution(execution.model_dump())
        self._active_executions[exec_id] = execution

        # Emit initial state event
        combined_event_sink(
            ExecutionEvent(
                execution_id=exec_id,
                sequence_num=0,
                event_type=ExecutionEventType.STATE_CHANGE,
                payload={"from_status": None, "to_status": ExecutionStatus.CREATED.value},
            )
        )
        state_machine.current_sequence_num = 1

        try:
            # Early cancellation check
            if cancellation_token and cancellation_token.is_set():
                state_machine.transition(
                    ExecutionStatus.CANCELLED, reason="Cancelled before context building"
                )
                self.storage.update_execution(exec_id, execution.model_dump())
                return ExecutionResult(
                    execution_id=exec_id,
                    status=ExecutionStatus.CANCELLED,
                    error="Execution cancelled by user",
                )

            # Phase 2: Context Assembly
            state_machine.transition(ExecutionStatus.CONTEXT_BUILDING)
            context_spec = ContextSpec(
                required_fields=["prompt"],
                optional_fields=["inputs", "project_id"],
                max_tokens=request.token_budget,
                hard_ceiling_tokens=request.token_budget * 2,
                strict_required=False,
            )
            built_ctx = build_context(
                spec=context_spec,
                available={
                    "prompt": request.prompt,
                    "inputs": request.inputs,
                    "project_id": request.project_id,
                },
            )
            exec_context = ExecutionContext(
                execution_id=exec_id,
                project_id=request.project_id,
                project_root=request.inputs.get("project_root", "/workspace"),
                project_instructions=request.inputs.get("project_instructions", ""),
                active_skills=request.inputs.get("skills", []),
                retrieved_passages=built_ctx.get("retrieved_passages", []),
                token_budget=request.token_budget,
            )

            # Phase 3: Routing & Tier Resolution
            state_machine.transition(ExecutionStatus.ROUTING)
            tier, provider, model_name = self._resolve_routing(request)
            execution.routing_tier = tier
            execution.provider = provider
            execution.model = model_name

            combined_event_sink(
                ExecutionEvent(
                    execution_id=exec_id,
                    sequence_num=state_machine.current_sequence_num,
                    event_type=ExecutionEventType.ROUTING_RESOLVED,
                    payload={"tier": tier.value, "provider": provider, "model": model_name},
                )
            )
            state_machine.current_sequence_num += 1

            # Phase 4: Policy Pre-Flight
            state_machine.transition(ExecutionStatus.POLICY_CHECK)
            tool_name = request.inputs.get("tool_name", request.task_type)
            policy_decision: PolicyDecision = self.policy_engine.evaluate(
                tool_name=tool_name,
                tool_args=request.inputs.get("tool_args", {"prompt": request.prompt}),
                context={"session_id": request.session_id},
            )

            if policy_decision.decision == "block":
                state_machine.transition(
                    ExecutionStatus.BLOCKED,
                    reason=policy_decision.reason,
                    error_code="POLICY_BLOCKED",
                    error_message=policy_decision.reason,
                )
                self.storage.update_execution(exec_id, execution.model_dump())
                return ExecutionResult(
                    execution_id=exec_id,
                    status=ExecutionStatus.BLOCKED,
                    error=policy_decision.reason,
                    routing_tier=tier,
                    model_used=model_name,
                    provider_used=provider,
                )

            # Phase 5: Budget Check
            state_machine.transition(ExecutionStatus.BUDGET_CHECK)
            alerts = self.cost_tracker.check_budget_alerts(request.project_id)
            critical_alerts = [a for a in alerts if a.level == "critical"]
            if critical_alerts:
                reason = f"Monthly budget limit reached for project '{request.project_id}'"
                state_machine.transition(
                    ExecutionStatus.BLOCKED,
                    reason=reason,
                    error_code="BUDGET_EXCEEDED",
                    error_message=reason,
                )
                self.storage.update_execution(exec_id, execution.model_dump())
                return ExecutionResult(
                    execution_id=exec_id,
                    status=ExecutionStatus.BLOCKED,
                    error=reason,
                    routing_tier=tier,
                    model_used=model_name,
                    provider_used=provider,
                )

            # Phase 6: Ready & Consequential Gate
            state_machine.transition(ExecutionStatus.READY)

            if policy_decision.decision == "stage":
                policy_id = (
                    policy_decision.violating_rules[0].id
                    if policy_decision.violating_rules
                    else None
                )
                state_machine.transition(
                    ExecutionStatus.WAITING_FOR_APPROVAL,
                    reason=policy_decision.reason,
                    payload={"policy_id": policy_id},
                )
                combined_event_sink(
                    ExecutionEvent(
                        execution_id=exec_id,
                        sequence_num=state_machine.current_sequence_num,
                        event_type=ExecutionEventType.APPROVAL_REQUIRED,
                        payload={
                            "reason": policy_decision.reason,
                            "policy_id": policy_id,
                            "suggestion": policy_decision.suggestion,
                        },
                    )
                )
                state_machine.current_sequence_num += 1
                self.storage.update_execution(exec_id, execution.model_dump())
                return ExecutionResult(
                    execution_id=exec_id,
                    status=ExecutionStatus.WAITING_FOR_APPROVAL,
                    outputs={"approval_required": True, "reason": policy_decision.reason},
                    routing_tier=tier,
                    model_used=model_name,
                    provider_used=provider,
                )

            # Cancellation check before running
            if cancellation_token and cancellation_token.is_set():
                state_machine.transition(
                    ExecutionStatus.CANCELLED, reason="Cancelled before dispatch"
                )
                self.storage.update_execution(exec_id, execution.model_dump())
                return ExecutionResult(
                    execution_id=exec_id,
                    status=ExecutionStatus.CANCELLED,
                    error="Execution cancelled by user",
                )

            # Phase 7: Execution Dispatch
            state_machine.transition(ExecutionStatus.RUNNING)

            prompt_tokens = estimate_tokens(request.prompt)
            outputs: Dict[str, Any] = {}
            completion_tokens = 0
            cache_hit = False

            if self._dispatch_override:
                res = self._dispatch_override(exec_context, tier, provider, model_name)
                if asyncio.iscoroutine(res):
                    outputs = await res
                else:
                    outputs = res
                completion_tokens = estimate_tokens(str(outputs.get("response", "")))
            elif tier == RoutingTier.CODE:
                outputs = {"response": "Executed deterministic code", "status": "ok"}
                completion_tokens = 10
            elif tier == RoutingTier.CACHE:
                outputs = {"response": "Retrieved from cache", "cached": True}
                completion_tokens = 5
                cache_hit = True
            else:
                # Default mock/stub dispatch response
                outputs = {
                    "response": f"Processed prompt with {provider}/{model_name}",
                    "echo_prompt": request.prompt,
                }
                completion_tokens = max(15, estimate_tokens(outputs["response"]))

            # Emit output chunk
            combined_event_sink(
                ExecutionEvent(
                    execution_id=exec_id,
                    sequence_num=state_machine.current_sequence_num,
                    event_type=ExecutionEventType.OUTPUT_CHUNK,
                    payload={"chunk": outputs.get("response", "")},
                )
            )
            state_machine.current_sequence_num += 1

            # Cancellation check during/after execution
            if cancellation_token and cancellation_token.is_set():
                state_machine.transition(
                    ExecutionStatus.CANCELLED, reason="Cancelled during dispatch"
                )
                self.storage.update_execution(exec_id, execution.model_dump())
                return ExecutionResult(
                    execution_id=exec_id,
                    status=ExecutionStatus.CANCELLED,
                    error="Execution cancelled during dispatch",
                )

            # Phase 8: Output Verification
            state_machine.transition(ExecutionStatus.VERIFYING)
            combined_event_sink(
                ExecutionEvent(
                    execution_id=exec_id,
                    sequence_num=state_machine.current_sequence_num,
                    event_type=ExecutionEventType.VERIFICATION_STARTED,
                    payload={"task_type": request.task_type},
                )
            )
            state_machine.current_sequence_num += 1

            verification = self._verify_output(
                task_type=request.task_type,
                outputs=outputs,
                expected_schema=request.inputs.get("expected_schema"),
            )

            combined_event_sink(
                ExecutionEvent(
                    execution_id=exec_id,
                    sequence_num=state_machine.current_sequence_num,
                    event_type=ExecutionEventType.VERIFICATION_COMPLETED,
                    payload=verification.model_dump(),
                )
            )
            state_machine.current_sequence_num += 1

            # Phase 9: Telemetry Recording & Final Transition
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            total_tokens = prompt_tokens + completion_tokens
            cost_usd = self.cost_tracker.calculate_cost(
                model_name, prompt_tokens, completion_tokens
            )

            execution.input_tokens = prompt_tokens
            execution.output_tokens = completion_tokens
            execution.total_cost_usd = cost_usd

            if verification.passed:
                state_machine.transition(ExecutionStatus.COMPLETED, verification=verification)
                final_status = ExecutionStatus.COMPLETED
            else:
                state_machine.transition(
                    ExecutionStatus.FAILED,
                    error_code="VERIFICATION_FAILED",
                    error_message=verification.error,
                )
                final_status = ExecutionStatus.FAILED

            # Record telemetry in cost records
            self.cost_tracker.record_spend(
                agent_name=request.task_type,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                task_id=exec_id,
                success=verification.passed,
                project=request.project_id,
            )

            self.storage.update_execution(exec_id, execution.model_dump())

            # Phase 10: Return ExecutionResult
            return ExecutionResult(
                execution_id=exec_id,
                status=final_status,
                outputs=outputs,
                error=verification.error if not verification.passed else None,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_cost_usd=cost_usd,
                duration_ms=duration_ms,
                model_used=model_name,
                provider_used=provider,
                routing_tier=tier,
                cache_hit=cache_hit,
                verification=verification,
            )

        except Exception as err:
            logger.exception("Execution '%s' encountered an unhandled error: %s", exec_id, err)
            if not state_machine.is_terminal:
                try:
                    state_machine.transition(
                        ExecutionStatus.FAILED,
                        error_code="EXECUTION_ERROR",
                        error_message=str(err),
                    )
                except Exception:
                    pass
            self.storage.update_execution(exec_id, execution.model_dump())
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionResult(
                execution_id=exec_id,
                status=ExecutionStatus.FAILED,
                error=str(err),
                duration_ms=duration_ms,
            )
        finally:
            self._active_executions.pop(exec_id, None)

    def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve execution by primary key."""
        return self.storage.get_execution(execution_id)

    def get_execution_events(
        self, execution_id: str, after_sequence_num: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve ordered stream of events for an execution."""
        return self.storage.get_execution_events(
            execution_id, after_sequence_num=after_sequence_num
        )
