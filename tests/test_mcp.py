import json

from server.mcp_server import (
    get_system_telemetry,
    ingest_agent_memory,
    list_staged_patches,
    mcp,
    query_agent_memory,
)


def test_mcp_tool_registration():
    """Verify all expected tools are exposed via FastMCP."""
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    expected_tools = [
        "analyze_and_fix_code",
        "query_agent_memory",
        "ingest_agent_memory",
        "execute_dynamic_blueprint",
        "list_staged_patches",
        "apply_staged_patch_by_id",
        "get_system_telemetry",
        "list_skill_templates",
        "execute_skill_template",
    ]
    for exp in expected_tools:
        assert exp in tool_names, f"Missing MCP tool: {exp}"


def test_system_telemetry_tool():
    """Verify get_system_telemetry outputs valid JSON and hardware stats."""
    res = get_system_telemetry()
    data = json.loads(res)
    assert "cpu_usage_percent" in data
    assert "ram_total_gb" in data
    assert "ram_available_gb" in data
    assert "indexed_memory_documents" in data
    assert data["ram_total_gb"] > 0


def test_mcp_memory_lifecycle():
    """Verify memory ingestion and query via MCP tool functions."""
    ingest_res = ingest_agent_memory(
        "MCP allows IDEs like VS Code to invoke external agent tools directly.",
        source_title="mcp_test",
    )
    assert "Successfully indexed" in ingest_res

    query_res = query_agent_memory("How does MCP connect to IDEs?", top_k=1)
    assert "VS Code" in query_res or "MCP allows" in query_res


def test_list_staged_patches_tool():
    """Verify list_staged_patches returns a string report."""
    res = list_staged_patches()
    assert isinstance(res, str)
