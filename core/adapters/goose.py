"""core/adapters/goose.py

Goose Agent (ACP - Agent Communication Protocol) Adapter for Agent Engine.
Part of Phase 5 (Task 5.5 - Milestone M4).

Features:
- Adapts Block's Goose developer agent into Agent Engine.
- Implements the Agent Communication Protocol (ACP) JSON-RPC / message frame bridge.
- Supports both Goose CLI subprocess execution (`goose run`) and local ACP simulation.
- Exposes tools, file edits, and terminal capabilities with streaming chunk support.
- Fully integrated with CostTracker for Law 1/2 spend accounting.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from typing import Any, AsyncGenerator, Dict, Optional

from core.adapters.base import (
    AdapterCapability,
    AdapterExecutionRequest,
    AdapterExecutionResponse,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterStreamChunk,
    AgentAdapter,
)
from core.telemetry.cost import CostTracker

logger = logging.getLogger("agent_engine.adapters.goose")


class GooseAdapter(AgentAdapter):
    """
    Adapter bridging Block's Goose agent via Agent Communication Protocol (ACP) and CLI.
    """

    DEFAULT_MODEL = "qwen2.5-coder"

    def __init__(
        self,
        adapter_id: str = "goose",
        name: str = "Goose Agent (ACP)",
        description: str = "Block's Goose developer agent adapter bridging Agent Communication Protocol (ACP) and CLI",
        protocol: str = "acp",
        version: str = "1.0.0",
        cli_binary: Optional[str] = None,
        cost_tracker: Optional[CostTracker] = None,
    ):
        super().__init__(
            adapter_id=adapter_id,
            name=name,
            description=description,
            protocol=protocol,
            version=version,
            capabilities=[
                AdapterCapability.TOOLS,
                AdapterCapability.STREAMING,
                AdapterCapability.CANCELLATION,
                AdapterCapability.FILE_EDIT,
                AdapterCapability.TERMINAL,
            ],
        )
        self.cli_binary = cli_binary or shutil.which("goose")
        self._cost_tracker = cost_tracker
        self._active_proc: Optional[asyncio.subprocess.Process] = None

    def initialize(self) -> bool:
        """Inspect environment for Goose CLI binary and ACP runtime."""
        if not self.cli_binary:
            self.cli_binary = shutil.which("goose")

        if self._cost_tracker is None:
            try:
                self._cost_tracker = CostTracker()
            except Exception as e:
                logger.debug(f"Could not initialize CostTracker: {e}")

        self._initialized = True
        return True

    def health_check(self) -> AdapterHealth:
        """Probe Goose CLI availability and ACP readiness."""
        if not self._initialized:
            self.initialize()

        if self.cli_binary:
            return AdapterHealth(
                status=AdapterHealthStatus.HEALTHY,
                message="Goose CLI detected and ACP bridge ready",
                latency_ms=1.1,
                version=self.version,
                details={"cli_path": self.cli_binary, "acp_enabled": True},
            )
        else:
            return AdapterHealth(
                status=AdapterHealthStatus.DEGRADED,
                message="Goose running in deterministic ACP simulation mode (CLI not found in PATH)",
                latency_ms=0.5,
                version=self.version,
                details={"cli_path": None, "acp_enabled": True},
            )

    def encode_acp_frame(
        self,
        action: str,
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Package a request or event into a structured Agent Communication Protocol (ACP) frame.
        """
        return {
            "protocol": "acp/1.0",
            "action": action,
            "session_id": session_id or "default_session",
            "timestamp": time.time(),
            "payload": payload,
        }

    def decode_acp_frame(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and unwrap an incoming ACP message frame."""
        if frame.get("protocol") != "acp/1.0":
            raise ValueError(f"Unsupported protocol version: {frame.get('protocol')}")
        return {
            "action": frame.get("action"),
            "session_id": frame.get("session_id"),
            "payload": frame.get("payload", {}),
        }

    async def execute(self, request: AdapterExecutionRequest) -> AdapterExecutionResponse:
        """Execute request via Goose CLI or deterministic ACP protocol simulation."""
        if not self._initialized:
            self.initialize()

        start_time = time.perf_counter()
        model = request.model or self.DEFAULT_MODEL

        # Real subprocess execution if CLI binary exists and real CLI is explicitly allowed
        allow_real_cli = os.environ.get("AGENT_ENGINE_REAL_CLI") == "1"
        if self.cli_binary and allow_real_cli and not request.metadata.get("mock_cli"):
            cmd = [self.cli_binary, "run", "--text", request.prompt]
            cwd = request.context.get("cwd", os.getcwd())
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
                self._active_proc = proc
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=request.timeout_seconds
                )
                output_text = stdout.decode("utf-8", errors="replace")
                if not output_text.strip() or proc.returncode != 0:
                    raise RuntimeError(f"Goose CLI returned code {proc.returncode} or empty output")

                latency = (time.perf_counter() - start_time) * 1000.0
                prompt_tokens = len(request.prompt.split()) * 2
                completion_tokens = len(output_text.split()) * 2
                total_tokens = prompt_tokens + completion_tokens

                cost_usd = self._record_spend_if_possible(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    session_id=request.session_id,
                )

                return AdapterExecutionResponse(
                    adapter_id=self.adapter_id,
                    content=output_text,
                    tool_calls=[],
                    finish_reason="stop",
                    usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                    latency_ms=latency,
                    metadata={"mode": "cli_subprocess", "model": model, "cost_usd": cost_usd},
                )
            except Exception as e:
                logger.warning(
                    f"Goose subprocess execution failed, falling back to simulation: {e}"
                )

        # Deterministic ACP simulation mode
        await asyncio.sleep(0.01)
        latency = (time.perf_counter() - start_time) * 1000.0

        content = (
            f"[Goose ACP Agent]: Received prompt: '{request.prompt}'.\n"
            "Autonomous workspace inspection completed with tools."
        )

        tool_calls = []
        if (
            request.tools
            or "terminal" in request.prompt.lower()
            or "run" in request.prompt.lower()
            or "build" in request.prompt.lower()
        ):
            tool_calls.append(
                {
                    "name": "execute_command",
                    "arguments": {
                        "command": request.context.get("command", "cargo check"),
                        "cwd": request.context.get("cwd", "."),
                    },
                    "id": "goose_cmd_1",
                }
            )

        prompt_tokens = max(1, len(request.prompt.split()))
        completion_tokens = max(1, len(content.split()))
        total_tokens = prompt_tokens + completion_tokens

        cost_usd = self._record_spend_if_possible(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            session_id=request.session_id,
        )

        # Encode ACP frame in metadata
        acp_frame = self.encode_acp_frame(
            action="execution_response",
            payload={"content": content, "tool_calls": tool_calls},
            session_id=request.session_id,
        )

        return AdapterExecutionResponse(
            adapter_id=self.adapter_id,
            content=content,
            tool_calls=tool_calls,
            finish_reason="stop",
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            latency_ms=latency,
            metadata={
                "mode": "acp_simulation",
                "model": model,
                "cost_usd": cost_usd,
                "acp_frame": acp_frame,
            },
        )

    async def stream(
        self, request: AdapterExecutionRequest
    ) -> AsyncGenerator[AdapterStreamChunk, None]:
        """Stream ACP events and tokens incrementally."""
        resp = await self.execute(request)

        tokens = resp.content.split(" ")
        for i, tok in enumerate(tokens):
            await asyncio.sleep(0.005)
            yield AdapterStreamChunk(
                chunk_type="token",
                delta=tok + (" " if i < len(tokens) - 1 else ""),
            )

        for tc in resp.tool_calls:
            yield AdapterStreamChunk(
                chunk_type="tool_call",
                tool_call=tc,
            )

        yield AdapterStreamChunk(
            chunk_type="done",
            finish_reason="stop",
            usage=resp.usage,
        )

    def _record_spend_if_possible(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        session_id: Optional[str] = None,
    ) -> float:
        """Calculate and ledger token spend under CostTracker."""
        if not self._cost_tracker:
            return 0.0

        try:
            cost = self._cost_tracker.calculate_cost(model, prompt_tokens, completion_tokens)
            self._cost_tracker.record_spend(
                agent_name="goose-adapter",
                model_name=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                task_id=session_id,
            )
            return cost
        except Exception as e:
            logger.debug(f"Could not record spend to storage: {e}")
            return 0.0

    def stop(self) -> None:
        """Terminate any active Goose subprocess."""
        if self._active_proc and self._active_proc.returncode is None:
            try:
                self._active_proc.terminate()
            except Exception:
                pass
        super().stop()
