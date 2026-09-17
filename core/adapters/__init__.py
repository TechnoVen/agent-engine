"""
core/adapters package.
Exposes AgentAdapter, AdapterRegistry, and associated data models.
Part of Phase 5 (Task 5.1).
"""

from core.adapters.base import (
    AdapterCapability,
    AdapterExecutionRequest,
    AdapterExecutionResponse,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterStreamChunk,
    AgentAdapter,
)
from core.adapters.claude_code import ClaudeCodeAdapter
from core.adapters.codex import CodexAdapter
from core.adapters.goose import GooseAdapter
from core.adapters.mcp_fallback import (
    CursorAdapter,
    HermesAdapter,
    MCPFallbackAdapter,
    WindsurfAdapter,
)
from core.adapters.mock import MockAgentAdapter
from core.adapters.openclaw import OpenClawAdapter
from core.adapters.registry import (
    AdapterDisabledError,
    AdapterNotFoundError,
    AdapterRegistry,
    get_adapter_registry,
)

__all__ = [
    "AgentAdapter",
    "MockAgentAdapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "GooseAdapter",
    "OpenClawAdapter",
    "CursorAdapter",
    "WindsurfAdapter",
    "HermesAdapter",
    "MCPFallbackAdapter",
    "AdapterCapability",
    "AdapterHealthStatus",
    "AdapterHealth",
    "AdapterExecutionRequest",
    "AdapterExecutionResponse",
    "AdapterStreamChunk",
    "AdapterRegistry",
    "AdapterDisabledError",
    "AdapterNotFoundError",
    "get_adapter_registry",
]
