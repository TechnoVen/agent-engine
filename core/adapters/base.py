"""
core/adapters/base.py
Abstract Base Class and data models for Agent Adapters.
Part of Phase 5 (Task 5.1).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional


class AdapterCapability(str, Enum):
    """Declared capabilities supported by an agent adapter."""

    TOOLS = "tools"
    STREAMING = "streaming"
    CANCELLATION = "cancellation"
    FILE_EDIT = "file_edit"
    TERMINAL = "terminal"
    VISION = "vision"
    BROWSER = "browser"


class AdapterHealthStatus(str, Enum):
    """Health status reported by an adapter probe."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class AdapterHealth:
    """Status probe results for an adapter."""

    status: AdapterHealthStatus
    message: str = "Ready"
    latency_ms: float = 0.0
    version: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "version": self.version,
            "details": self.details,
        }


@dataclass
class AdapterExecutionRequest:
    """Standardized input payload for agent adapters."""

    prompt: str
    session_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    timeout_seconds: float = 60.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterExecutionResponse:
    """Standardized output payload from agent adapters."""

    adapter_id: str
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "latency_ms": round(self.latency_ms, 2),
            "metadata": self.metadata,
        }


@dataclass
class AdapterStreamChunk:
    """Standardized incremental token / tool call event in an SSE stream."""

    chunk_type: str = "token"  # "token", "tool_call", "error", "done"
    delta: str = ""
    tool_call: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.chunk_type}
        if self.delta:
            data["delta"] = self.delta
        if self.tool_call:
            data["tool_call"] = self.tool_call
        if self.finish_reason:
            data["finish_reason"] = self.finish_reason
        if self.usage:
            data["usage"] = self.usage
        if self.error:
            data["error"] = self.error
        return data


class AgentAdapter(ABC):
    """
    Abstract Base Class for all external coding agents and protocol bridges.
    Concrete adapters implement invocation, tool translation, and streaming.
    """

    def __init__(
        self,
        adapter_id: str,
        name: str,
        description: str,
        protocol: str,
        version: str = "1.0.0",
        capabilities: Optional[List[AdapterCapability]] = None,
    ):
        self.adapter_id = adapter_id
        self.name = name
        self.description = description
        self.protocol = protocol
        self.version = version
        self.capabilities = capabilities or [
            AdapterCapability.TOOLS,
            AdapterCapability.STREAMING,
            AdapterCapability.CANCELLATION,
        ]
        self._initialized = False

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize adapter environment, inspect local tools, and load configuration."""
        pass

    @abstractmethod
    def health_check(self) -> AdapterHealth:
        """Probe the adapter's runtime prerequisites and connectivity."""
        pass

    @abstractmethod
    async def execute(self, request: AdapterExecutionRequest) -> AdapterExecutionResponse:
        """Execute a prompt synchronously/asynchronously and return full response."""
        pass

    @abstractmethod
    async def stream(
        self, request: AdapterExecutionRequest
    ) -> AsyncGenerator[AdapterStreamChunk, None]:
        """Stream response tokens and tool calls incrementally."""
        pass

    def stop(self) -> None:
        """Gracefully terminate any active subprocesses or daemon channels."""
        self._initialized = False

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Serialize adapter metadata for API discovery."""
        return {
            "adapter_id": self.adapter_id,
            "name": self.name,
            "description": self.description,
            "protocol": self.protocol,
            "version": self.version,
            "capabilities": [c.value for c in self.capabilities],
            "initialized": self._initialized,
        }
