"""
core/adapters/mock.py
Deterministic reference adapter for testing, contracts, and local verification.
Part of Phase 5 (Task 5.1).
"""

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

from core.adapters.base import (
    AdapterCapability,
    AdapterExecutionRequest,
    AdapterExecutionResponse,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterStreamChunk,
    AgentAdapter,
)


class MockAgentAdapter(AgentAdapter):
    """
    Reference/Mock adapter that produces deterministic echo output, tool calls, and streaming chunks.
    """

    def __init__(
        self,
        adapter_id: str = "mock-agent",
        name: str = "Mock Reference Agent",
        description: str = "Deterministic test adapter for contract verification",
        protocol: str = "direct",
        version: str = "1.0.0",
        capabilities: Optional[List[AdapterCapability]] = None,
        fail_health: bool = False,
    ):
        super().__init__(
            adapter_id=adapter_id,
            name=name,
            description=description,
            protocol=protocol,
            version=version,
            capabilities=capabilities,
        )
        self.fail_health = fail_health
        self.calls_count = 0

    def initialize(self) -> bool:
        self._initialized = True
        return True

    def health_check(self) -> AdapterHealth:
        if self.fail_health:
            return AdapterHealth(
                status=AdapterHealthStatus.UNAVAILABLE,
                message="Mock adapter simulated offline failure",
                latency_ms=0.5,
                version=self.version,
            )
        return AdapterHealth(
            status=AdapterHealthStatus.HEALTHY,
            message="Mock adapter ready",
            latency_ms=1.2,
            version=self.version,
            details={"calls_count": self.calls_count},
        )

    async def execute(self, request: AdapterExecutionRequest) -> AdapterExecutionResponse:
        self.calls_count += 1
        content = f"Echo [{self.adapter_id}]: {request.prompt}"

        # If tools requested, simulate tool execution call if prompt asks for calculation
        tool_calls: List[Dict[str, Any]] = []
        if "calculate" in request.prompt.lower():
            tool_calls.append(
                {
                    "name": "calculator",
                    "arguments": {"expression": "2 + 2"},
                    "id": f"call_{self.calls_count}",
                }
            )

        usage = {
            "prompt_tokens": len(request.prompt.split()),
            "completion_tokens": len(content.split()),
            "total_tokens": len(request.prompt.split()) + len(content.split()),
        }

        return AdapterExecutionResponse(
            adapter_id=self.adapter_id,
            content=content,
            tool_calls=tool_calls,
            finish_reason="stop",
            usage=usage,
            latency_ms=5.0,
            metadata={"mock": True, "call_index": self.calls_count},
        )

    async def stream(
        self, request: AdapterExecutionRequest
    ) -> AsyncGenerator[AdapterStreamChunk, None]:
        self.calls_count += 1
        tokens = [f"Echo [{self.adapter_id}]: ", *request.prompt.split()]

        for i, token in enumerate(tokens):
            await asyncio.sleep(0.005)
            yield AdapterStreamChunk(
                chunk_type="token",
                delta=token + (" " if i < len(tokens) - 1 else ""),
            )

        if "calculate" in request.prompt.lower():
            yield AdapterStreamChunk(
                chunk_type="tool_call",
                tool_call={
                    "name": "calculator",
                    "arguments": {"expression": "2 + 2"},
                    "id": f"call_{self.calls_count}",
                },
            )

        yield AdapterStreamChunk(
            chunk_type="done",
            finish_reason="stop",
            usage={"total_tokens": len(tokens)},
        )
