"""
core/adapters/registry.py
Central registry for discovery, lifecycle management, and settings-gated execution of Agent Adapters.
Part of Phase 5 (Task 5.1).
"""

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from core.adapters.base import (
    AdapterExecutionRequest,
    AdapterExecutionResponse,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterStreamChunk,
    AgentAdapter,
)
from core.config.settings import get_settings_manager

logger = logging.getLogger("agent_engine.adapters")


class AdapterDisabledError(Exception):
    """Raised when an execution request targets a disabled adapter."""

    pass


class AdapterNotFoundError(Exception):
    """Raised when an adapter ID is not found in the registry."""

    pass


class AdapterRegistry:
    """
    Manages registered agent adapters and coordinates lifecycle, discovery,
    and invocation respecting local AppSettings flags.
    """

    def __init__(self):
        self._adapters: Dict[str, AgentAdapter] = {}

    def register(self, adapter: AgentAdapter) -> None:
        """Register an adapter instance."""
        if not isinstance(adapter, AgentAdapter):
            raise TypeError(f"Expected AgentAdapter instance, got {type(adapter)}")
        self._adapters[adapter.adapter_id] = adapter
        logger.info(f"Registered agent adapter: {adapter.adapter_id} ({adapter.name})")

    def unregister(self, adapter_id: str) -> Optional[AgentAdapter]:
        """Unregister and stop an adapter by ID."""
        adapter = self._adapters.pop(adapter_id, None)
        if adapter:
            adapter.stop()
            logger.info(f"Unregistered agent adapter: {adapter_id}")
        return adapter

    def get(self, adapter_id: str) -> Optional[AgentAdapter]:
        """Retrieve an adapter by ID."""
        return self._adapters.get(adapter_id)

    def is_enabled(self, adapter_id: str) -> bool:
        """Check if an adapter is enabled in AppSettings."""
        settings_mgr = get_settings_manager()
        settings = settings_mgr.get_settings()
        adapters_cfg = settings.adapters

        # Mapping of adapter IDs to AppSettings flags
        flag_map = {
            "claude-code": adapters_cfg.claude_code_adapter,
            "codex": adapters_cfg.codex_adapter,
            "openclaw": adapters_cfg.openclaw_adapter,
            "goose": adapters_cfg.goose_adapter,
            "cursor": adapters_cfg.cursor_adapter,
            "cursor-mcp": adapters_cfg.cursor_adapter and adapters_cfg.mcp_enabled,
            "windsurf": adapters_cfg.mcp_enabled,
            "hermes": adapters_cfg.mcp_enabled,
            "mcp": adapters_cfg.mcp_enabled,
        }

        return flag_map.get(adapter_id, True)

    def list_adapters(self, include_health: bool = False) -> List[Dict[str, Any]]:
        """
        List all registered adapters with enabled state, capabilities, and optional health check.
        """
        results = []
        for adapter_id, adapter in self._adapters.items():
            meta = adapter.to_metadata_dict()
            meta["enabled"] = self.is_enabled(adapter_id)
            if include_health:
                try:
                    health = adapter.health_check()
                    meta["health"] = health.to_dict()
                except Exception as e:
                    meta["health"] = AdapterHealth(
                        status=AdapterHealthStatus.UNAVAILABLE,
                        message=f"Health probe error: {e}",
                    ).to_dict()
            results.append(meta)
        return results

    async def execute(
        self, adapter_id: str, request: AdapterExecutionRequest
    ) -> AdapterExecutionResponse:
        """Execute a prompt through a registered, enabled adapter."""
        adapter = self.get(adapter_id)
        if not adapter:
            raise AdapterNotFoundError(f"Adapter '{adapter_id}' not found in registry")

        if not self.is_enabled(adapter_id):
            raise AdapterDisabledError(
                f"Adapter '{adapter_id}' is disabled in Settings > Tool Adapters"
            )

        if not adapter._initialized:
            adapter.initialize()

        return await adapter.execute(request)

    async def stream(
        self, adapter_id: str, request: AdapterExecutionRequest
    ) -> AsyncGenerator[AdapterStreamChunk, None]:
        """Stream chunks from a registered, enabled adapter."""
        adapter = self.get(adapter_id)
        if not adapter:
            raise AdapterNotFoundError(f"Adapter '{adapter_id}' not found in registry")

        if not self.is_enabled(adapter_id):
            raise AdapterDisabledError(
                f"Adapter '{adapter_id}' is disabled in Settings > Tool Adapters"
            )

        if not adapter._initialized:
            adapter.initialize()

        async for chunk in adapter.stream(request):
            yield chunk

    def clear(self) -> None:
        """Clear all registered adapters and stop their resources."""
        for adapter in self._adapters.values():
            adapter.stop()
        self._adapters.clear()


# Global Singleton Registry
_GLOBAL_ADAPTER_REGISTRY: Optional[AdapterRegistry] = None


def get_adapter_registry() -> AdapterRegistry:
    """Get or instantiate the global singleton AdapterRegistry."""
    global _GLOBAL_ADAPTER_REGISTRY
    if _GLOBAL_ADAPTER_REGISTRY is None:
        _GLOBAL_ADAPTER_REGISTRY = AdapterRegistry()
        from core.adapters.claude_code import ClaudeCodeAdapter
        from core.adapters.codex import CodexAdapter
        from core.adapters.goose import GooseAdapter
        from core.adapters.mcp_fallback import (
            CursorAdapter,
            HermesAdapter,
            MCPFallbackAdapter,
            WindsurfAdapter,
        )
        from core.adapters.openclaw import OpenClawAdapter
        from core.adapters.slack import SlackAdapter
        from core.adapters.teams import TeamsAdapter

        _GLOBAL_ADAPTER_REGISTRY.register(ClaudeCodeAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(CodexAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(OpenClawAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(GooseAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(CursorAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(WindsurfAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(HermesAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(MCPFallbackAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(SlackAdapter())
        _GLOBAL_ADAPTER_REGISTRY.register(TeamsAdapter())
    return _GLOBAL_ADAPTER_REGISTRY
