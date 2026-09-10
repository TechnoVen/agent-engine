import os
import yaml
from fastapi.testclient import TestClient

from services.python.server.api import app

client = TestClient(app)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_api_healthz():
    """Verify sidecar liveness probe."""
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "agent-engine-sidecar"


def test_api_telemetry():
    """Verify GET /v1/telemetry returns system and router metrics."""
    res = client.get("/v1/telemetry")
    assert res.status_code == 200
    data = res.json()
    assert "cpu_usage_percent" in data
    assert "ram_used_percent" in data
    assert "primary_provider" in data
    assert "active_model" in data
    assert "indexed_memory_documents" in data


def test_api_telemetry_cost():
    """Verify GET /v1/telemetry/cost returns cost metrics structure."""
    res = client.get("/v1/telemetry/cost?group_by=agent")
    assert res.status_code == 200
    data = res.json()
    assert "total_cost_usd" in data
    assert "breakdown" in data
    assert len(data["breakdown"]) > 0


def test_api_memory_lifecycle():
    """Verify POST /v1/memory and GET /v1/memory vector persistence."""
    unique_text = "FastAPI sidecar contract test document for memory"
    ingest_res = client.post(
        "/v1/memory",
        json={"content": unique_text, "source": "test_contract"},
    )
    assert ingest_res.status_code == 200
    ingest_data = ingest_res.json()
    assert "document_id" in ingest_data
    assert ingest_data["count"] > 0

    query_res = client.get("/v1/memory?query=FastAPI+contract&top_k=3")
    assert query_res.status_code == 200
    query_data = query_res.json()
    assert query_data["query"] == "FastAPI contract"
    assert len(query_data["passages"]) > 0


def test_api_skills_listing():
    """Verify GET /v1/skills returns catalog of pre-built templates."""
    res = client.get("/v1/skills")
    assert res.status_code == 200
    skills = res.json()
    assert isinstance(skills, list)
    assert len(skills) >= 1
    sample = skills[0]
    assert "id" in sample
    assert "name" in sample
    assert "inputs" in sample
    assert "outputs" in sample


def test_api_agents_listing():
    """Verify GET /v1/agents returns registered agents."""
    res = client.get("/v1/agents")
    assert res.status_code == 200
    agents = res.json()
    assert len(agents) >= 1
    assert any(a["id"] == "agent_code_sentry" for a in agents)


def test_api_workflows():
    """Verify GET /v1/workflows and POST /v1/workflows."""
    get_res = client.get("/v1/workflows")
    assert get_res.status_code == 200
    wfs = get_res.json()
    assert len(wfs) >= 1
    assert "steps" in wfs[0]

    post_res = client.post(
        "/v1/workflows",
        json={"workflow_id": wfs[0]["id"], "inputs": {"target": "snippet.py"}},
    )
    assert post_res.status_code == 200
    exec_data = post_res.json()
    assert "execution_id" in exec_data
    assert exec_data["status"] == "queued"


def test_api_patches_listing():
    """Verify GET /v1/patches returns list of staged patches."""
    res = client.get("/v1/patches")
    assert res.status_code == 200
    patches = res.json()
    assert isinstance(patches, list)


def test_api_auth_session():
    """Verify GET /v1/auth/session returns local owner session."""
    res = client.get("/v1/auth/session")
    assert res.status_code == 200
    session = res.json()
    assert session["role"] == "Owner"
    assert "user_id" in session


def test_api_registry_search():
    """Verify GET /v1/registry/search filters packages."""
    res = client.get("/v1/registry/search?q=SQL")
    assert res.status_code == 200
    packages = res.json()
    assert len(packages) >= 1
    assert any("SQL" in p["name"] for p in packages)


def test_api_chat_completions_non_streaming():
    """Verify POST /v1/chat/completions with stream=False."""
    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Ping", "stream": False},
    )
    assert res.status_code == 200
    data = res.json()
    assert "response" in data
    assert "session_id" in data
    assert "cost_usd" in data


def test_api_chat_completions_streaming():
    """Verify POST /v1/chat/completions with stream=True returns SSE text/event-stream."""
    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Ping stream", "stream": True},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
    content = res.text
    assert "data: " in content
    assert '"event": "token"' in content
    assert '"event": "cost_update"' in content


def test_api_openapi_matches_frozen_spec():
    """Verify that all endpoints declared in packages/shared-schema/openapi.yaml exist in FastAPI app."""
    spec_path = os.path.join(PROJECT_ROOT, "packages", "shared-schema", "openapi.yaml")
    with open(spec_path, "r", encoding="utf-8") as f:
        frozen_spec = yaml.safe_load(f)

    app_schema = app.openapi()
    for path, methods in frozen_spec["paths"].items():
        v1_path = f"/v1{path}" if not path.startswith("/v1") else path
        assert (
            v1_path in app_schema["paths"]
        ), f"FastAPI app missing route from frozen spec: {v1_path}"
        for method in methods.keys():
            assert (
                method.lower() in app_schema["paths"][v1_path]
            ), f"FastAPI app missing method {method.upper()} on route {v1_path}"
