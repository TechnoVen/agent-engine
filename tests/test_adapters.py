"""
Unit & Integration Tests for Agent Adapter Layer (Phase 5 - Task 5.1).

Validates:
1. AgentAdapter ABC contracts and data models (capabilities, requests, responses, streaming chunks).
2. MockAgentAdapter reference implementation (initialize, health_check, execute, stream, stop).
3. AdapterRegistry lifecycle, dynamic registration, discovery, and AppSettings gating.
4. Error handling: AdapterNotFoundError and AdapterDisabledError.
5. FastAPI sidecar endpoints:
   - GET /v1/adapters
   - GET /v1/adapters/{id}
   - POST /v1/adapters/{id}/execute
   - POST /v1/adapters/{id}/stream
   - POST /v1/adapters/{id}/test
6. OpenAPI schema definitions and TypeScript desktop client integration.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.adapters import (
    AdapterCapability,
    AdapterDisabledError,
    AdapterExecutionRequest,
    AdapterHealthStatus,
    AdapterRegistry,
    AgentAdapter,
    MockAgentAdapter,
    get_adapter_registry,
)
from core.config import get_settings_manager
from services.python.server.api import app

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_agent_adapter_abc_contract():
    """Verify AgentAdapter ABC raises TypeError when instantiated without required methods."""

    class IncompleteAdapter(AgentAdapter):
        pass

    with pytest.raises(TypeError):
        IncompleteAdapter(
            adapter_id="incomplete",
            name="Incomplete",
            description="Test",
            protocol="cli",
        )


def test_mock_adapter_lifecycle():
    """Verify MockAgentAdapter lifecycle, health checking, and execution."""
    adapter = MockAgentAdapter(
        adapter_id="test-mock",
        name="Test Mock Agent",
        description="A deterministic mock agent for unit tests",
        capabilities=[AdapterCapability.TOOLS, AdapterCapability.STREAMING],
    )

    # 1. Metadata check
    meta = adapter.to_metadata_dict()
    assert meta["adapter_id"] == "test-mock"
    assert meta["name"] == "Test Mock Agent"
    assert "tools" in meta["capabilities"]
    assert "streaming" in meta["capabilities"]
    assert meta["initialized"] is False

    # 2. Initialization & Health
    assert adapter.initialize() is True
    assert adapter._initialized is True
    health = adapter.health_check()
    assert health.status == AdapterHealthStatus.HEALTHY
    assert "ready" in health.message.lower()

    # 3. Simulate failure probe
    fail_adapter = MockAgentAdapter(adapter_id="fail-mock", fail_health=True)
    fail_health = fail_adapter.health_check()
    assert fail_health.status == AdapterHealthStatus.UNAVAILABLE
    assert "offline" in fail_health.message


@pytest.mark.anyio
async def test_mock_adapter_execute_and_stream():
    """Verify MockAgentAdapter async execution and SSE streaming chunk emission."""
    adapter = MockAgentAdapter(adapter_id="exec-mock")
    adapter.initialize()

    # Normal execution
    req = AdapterExecutionRequest(prompt="Hello external agent", model="mock-v1")
    resp = await adapter.execute(req)
    assert resp.adapter_id == "exec-mock"
    assert "Echo [exec-mock]: Hello external agent" in resp.content
    assert resp.finish_reason == "stop"
    assert resp.usage["total_tokens"] > 0
    assert resp.metadata["mock"] is True

    # Tool invocation request
    calc_req = AdapterExecutionRequest(prompt="Please calculate this expression")
    calc_resp = await adapter.execute(calc_req)
    assert len(calc_resp.tool_calls) == 1
    assert calc_resp.tool_calls[0]["name"] == "calculator"
    assert calc_resp.tool_calls[0]["arguments"] == {"expression": "2 + 2"}

    # Streaming chunks
    chunks = []
    async for chunk in adapter.stream(calc_req):
        chunks.append(chunk)

    assert len(chunks) >= 4
    token_chunks = [c for c in chunks if c.chunk_type == "token"]
    assert len(token_chunks) > 0
    tool_chunks = [c for c in chunks if c.chunk_type == "tool_call"]
    assert len(tool_chunks) == 1
    done_chunks = [c for c in chunks if c.chunk_type == "done"]
    assert len(done_chunks) == 1
    assert done_chunks[0].finish_reason == "stop"


def test_adapter_registry_lifecycle():
    """Verify AdapterRegistry registration, unregistration, and discovery."""
    registry = AdapterRegistry()
    adapter1 = MockAgentAdapter(adapter_id="agent-1", name="Agent One")
    adapter2 = MockAgentAdapter(adapter_id="agent-2", name="Agent Two")

    registry.register(adapter1)
    registry.register(adapter2)

    assert registry.get("agent-1") is adapter1
    assert registry.get("agent-2") is adapter2
    assert registry.get("unknown") is None

    adapters_list = registry.list_adapters(include_health=True)
    assert len(adapters_list) == 2
    ids = [a["adapter_id"] for a in adapters_list]
    assert "agent-1" in ids
    assert "agent-2" in ids
    assert adapters_list[0]["health"]["status"] == "healthy"

    # Unregister
    removed = registry.unregister("agent-1")
    assert removed is adapter1
    assert registry.get("agent-1") is None
    assert len(registry.list_adapters()) == 1


@pytest.mark.anyio
async def test_adapter_registry_settings_gating():
    """Verify that disabled adapters in AppSettings reject execution with AdapterDisabledError."""
    registry = AdapterRegistry()
    claude_mock = MockAgentAdapter(adapter_id="claude-code", name="Claude Code")
    registry.register(claude_mock)

    # Disable claude_code_adapter in settings
    settings_mgr = get_settings_manager()
    original_settings = settings_mgr.get_settings().to_dict()

    try:
        updated_settings = dict(original_settings)
        updated_settings["adapters"] = dict(updated_settings.get("adapters", {}))
        updated_settings["adapters"]["claude_code_adapter"] = False
        settings_mgr.save_settings(updated_settings)

        assert registry.is_enabled("claude-code") is False

        # Execution should fail closed
        req = AdapterExecutionRequest(prompt="Test prompt")
        with pytest.raises(AdapterDisabledError):
            await registry.execute("claude-code", req)

        # Stream should also fail closed
        with pytest.raises(AdapterDisabledError):
            async for _ in registry.stream("claude-code", req):
                pass

        # Re-enable
        updated_settings["adapters"]["claude_code_adapter"] = True
        settings_mgr.save_settings(updated_settings)

        assert registry.is_enabled("claude-code") is True
        resp = await registry.execute("claude-code", req)
        assert resp.adapter_id == "claude-code"

    finally:
        settings_mgr.save_settings(original_settings)


def test_adapters_fastapi_endpoints():
    """Test FastAPI endpoints for adapter discovery, inspection, execution, streaming, and testing."""
    client = TestClient(app)
    reg = get_adapter_registry()

    test_adapter = MockAgentAdapter(
        adapter_id="api-test-mock",
        name="API Test Mock",
        description="Sidecar test adapter",
    )
    reg.register(test_adapter)

    try:
        # 1. GET /v1/adapters
        res = client.get("/v1/adapters?include_health=true")
        assert res.status_code == 200
        adapters = res.json()
        assert isinstance(adapters, list)
        mock_entry = next((a for a in adapters if a["adapter_id"] == "api-test-mock"), None)
        assert mock_entry is not None
        assert mock_entry["name"] == "API Test Mock"
        assert mock_entry["health"]["status"] == "healthy"

        # 2. GET /v1/adapters/{id}
        res_single = client.get("/v1/adapters/api-test-mock")
        assert res_single.status_code == 200
        data = res_single.json()
        assert data["adapter_id"] == "api-test-mock"
        assert data["enabled"] is True

        # 404 for nonexistent adapter
        res_404 = client.get("/v1/adapters/non-existent-adapter")
        assert res_404.status_code == 404

        # 3. POST /v1/adapters/{id}/execute
        exec_payload = {
            "prompt": "Hello from FastAPI client",
            "model": "instant",
            "temperature": 0.5,
        }
        res_exec = client.post("/v1/adapters/api-test-mock/execute", json=exec_payload)
        assert res_exec.status_code == 200
        exec_data = res_exec.json()
        assert exec_data["adapter_id"] == "api-test-mock"
        assert "Hello from FastAPI client" in exec_data["content"]
        assert exec_data["finish_reason"] == "stop"

        # 4. POST /v1/adapters/{id}/stream
        res_stream = client.post("/v1/adapters/api-test-mock/stream", json=exec_payload)
        assert res_stream.status_code == 200
        assert "text/event-stream" in res_stream.headers["content-type"]
        assert "data: " in res_stream.text

        # 5. POST /v1/adapters/{id}/test
        res_test = client.post("/v1/adapters/api-test-mock/test")
        assert res_test.status_code == 200
        test_data = res_test.json()
        assert test_data["status"] == "healthy"
        assert "latency_ms" in test_data

    finally:
        reg.unregister("api-test-mock")


def test_adapters_schema_and_client_integration():
    """Verify OpenAPI frozen schema contracts and desktop TypeScript API client implementation."""
    schema_file = REPO_ROOT / "packages" / "shared-schema" / "openapi.yaml"
    assert schema_file.exists()
    schema_content = schema_file.read_text()

    # Routes must be registered in OpenAPI
    assert "/adapters:" in schema_content
    assert "/adapters/{adapter_id}:" in schema_content
    assert "/adapters/{adapter_id}/execute:" in schema_content
    assert "/adapters/{adapter_id}/stream:" in schema_content
    assert "/adapters/{adapter_id}/test:" in schema_content

    # Schemas must be defined
    assert "AdapterMetadata:" in schema_content
    assert "AdapterExecutionPayload:" in schema_content
    assert "AdapterExecutionResponse:" in schema_content

    # Client integration
    client_ts = (
        REPO_ROOT / "apps" / "desktop" / "src" / "renderer" / "api" / "client.ts"
    ).read_text()
    assert "getAdapters(" in client_ts
    assert "getAdapter(" in client_ts
    assert "executeAdapter(" in client_ts
    assert "testAdapter(" in client_ts

    types_ts = (
        REPO_ROOT / "apps" / "desktop" / "src" / "renderer" / "types" / "index.ts"
    ).read_text()
    assert "interface AdapterMetadata" in types_ts
    assert "interface AdapterHealth" in types_ts
    assert "interface AdapterExecutionRequest" in types_ts
    assert "interface AdapterExecutionResponse" in types_ts
