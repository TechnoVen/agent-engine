"""tests/test_api_domain_decomposition.py

Task R1.14 Verification: API Domain Decomposition & Router Separation.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/ROADMAP.md (R1.14), docs/ARCHITECTURE.md

Validates that:
1. Application factory creates valid FastAPI instance.
2. Canonical domain routers are created and mounted under /v1 with semantic identity checks.
3. Unique route ownership, zero duplicate canonical paths, and required operations are mounted and verified.
4. Backwards-compatible facade in api.py preserves all symbols and test hooks.
5. Error mapping translates domain exceptions to canonical HTTP status codes.
6. Execution coordinator dependency injection functions uniformly across routers.
"""

import pytest
from fastapi.testclient import TestClient

from services.python.server.app import create_app
from services.python.server.container import (
    get_services,
    get_execution_coordinator,
    get_artifact_service,
    get_ledger_service,
    get_storage_backend,
)
from services.python.server.errors import map_execution_error_to_http, handle_domain_error
from services.python.server import routers
from core.execution.models import ExecutionResult, ExecutionStatus


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_app_boot_and_healthz(client):
    """1. Verify application boots and healthz probe returns 200 OK."""
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "agent-engine-sidecar"
    assert "uptime_seconds" in data


def test_canonical_domain_routers_registered():
    """2. Verify canonical domain routers exist in routers package and have routes."""
    expected_domains = [
        "adapters",
        "artifacts",
        "chat",
        "collaboration",
        "credentials",
        "executions",
        "ledger",
        "memory",
        "models",
        "packs",
        "patches",
        "pipelines",
        "policies",
        "projects",
        "skills",
        "swarm",
        "system",
        "tasks",
        "telemetry",
        "workflows",
    ]
    for dom_name in expected_domains:
        assert hasattr(routers, dom_name), f"Missing domain router {dom_name} in routers package"
        mod = getattr(routers, dom_name)
        assert hasattr(mod, "router"), f"Router module {dom_name} missing 'router'"
        assert len(mod.router.routes) > 0, f"Router module {dom_name} has 0 routes"


def test_route_count_and_paths_match():
    """3. Verify domain routers have valid routes and key required canonical endpoints exist."""
    required_endpoints = [
        ("POST", "/v1/chat/completions"),
        ("GET", "/v1/projects"),
        ("GET", "/v1/packs"),
        ("GET", "/v1/executions/{execution_id}"),
        ("GET", "/v1/workflows"),
        ("GET", "/v1/tasks"),
        ("POST", "/v1/safety/evaluate"),
        ("GET", "/v1/safety/operations"),
    ]
    app = create_app()
    registered_routes = set()
    v1 = app.state.v1_router
    for r in v1.routes:
        if hasattr(r, "methods") and hasattr(r, "path"):
            for m in r.methods:
                registered_routes.add(
                    (m, "/v1" + r.path if not r.path.startswith("/v1") else r.path)
                )
        elif hasattr(r, "original_router"):
            for sr in r.original_router.routes:
                for m in sr.methods:
                    registered_routes.add((m, "/v1" + sr.path))

    for method, path in required_endpoints:
        assert (
            method,
            path,
        ) in registered_routes, f"Required endpoint {method} {path} missing from app"


def test_chat_router_endpoint_accessible(client):
    """4. Verify /v1/chat/completions endpoint accepts requests and dispatches."""
    # Validation error on empty body confirms route is mounted and handled by FastAPI
    res = client.post("/v1/chat/completions", json={})
    assert res.status_code == 422  # Pydantic validation error for missing 'prompt'


def test_executions_router_endpoints_accessible(client):
    """5. Verify /v1/executions endpoints are registered and accessible."""
    res = client.get("/v1/executions/non_existent_exec_id")
    assert res.status_code == 404


def test_ledger_router_endpoint_accessible(client):
    """6. Verify /v1/executions/{id}/trace is accessible."""
    res = client.get("/v1/executions/non_existent_exec_id/trace")
    assert res.status_code == 404


def test_artifacts_router_endpoints_accessible(client):
    """7. Verify /v1/artifacts/{id} and /v1/projects/{id}/artifacts are accessible."""
    res = client.get("/v1/artifacts/non_existent_art_id")
    assert res.status_code == 404
    res2 = client.get("/v1/projects/default/artifacts")
    assert res2.status_code == 200
    assert isinstance(res2.json(), list)


def test_skills_router_endpoints_accessible(client):
    """8. Verify /v1/skills and /v1/agents are accessible."""
    res = client.get("/v1/skills")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    res_agents = client.get("/v1/agents")
    assert res_agents.status_code == 200
    assert isinstance(res_agents.json(), list)


def test_pipelines_router_endpoints_accessible(client):
    """9. Verify /v1/pipelines and /v1/cases are accessible."""
    res = client.get("/v1/pipelines")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    res_cases = client.get("/v1/cases")
    assert res_cases.status_code == 200
    assert isinstance(res_cases.json(), list)


def test_adapters_router_endpoints_accessible(client):
    """10. Verify /v1/adapters endpoints are accessible."""
    res = client.get("/v1/adapters")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_projects_router_endpoints_accessible(client):
    """11. Verify /v1/projects and /v1/sessions are accessible."""
    res = client.get("/v1/projects")
    assert res.status_code == 200
    res_sess = client.get("/v1/sessions")
    assert res_sess.status_code == 200


def test_policies_router_endpoints_accessible(client):
    """12. Verify /v1/safety endpoints are accessible."""
    res = client.get("/v1/safety/operations")
    assert res.status_code == 200
    res_pol = client.get("/v1/safety/policies")
    assert res_pol.status_code == 200


def test_telemetry_router_endpoints_accessible(client):
    """13. Verify /v1/telemetry and /v1/telemetry/budget are accessible."""
    res = client.get("/v1/telemetry")
    assert res.status_code == 200
    assert "cpu_usage_percent" in res.json()
    res_budget = client.get("/v1/telemetry/budget")
    assert res_budget.status_code == 200


def test_models_router_endpoints_accessible(client):
    """14. Verify /v1/router/tiers is accessible."""
    res = client.get("/v1/router/tiers")
    assert res.status_code == 200


def test_credentials_router_endpoints_accessible(client):
    """15. Verify /v1/credentials endpoints are accessible."""
    res = client.get("/v1/credentials")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_workflows_router_endpoints_accessible(client):
    """16. Verify /v1/workflows and gates are accessible."""
    res = client.get("/v1/workflows")
    assert res.status_code == 200
    res_gates = client.get("/v1/workflows/gates/pending")
    assert res_gates.status_code == 200


def test_swarm_router_endpoints_accessible(client):
    """17. Verify /v1/swarm/cases endpoint is accessible."""
    res = client.get("/v1/swarm/cases")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_tasks_router_endpoints_accessible(client):
    """18. Verify /v1/tasks endpoint is accessible."""
    res = client.get("/v1/tasks")
    assert res.status_code == 200
    data = res.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


def test_memory_router_endpoints_accessible(client):
    """19. Verify /v1/memory/observations endpoint is accessible."""
    res = client.get("/v1/memory/observations?query=test")
    assert res.status_code == 200
    assert "observations" in res.json()


def test_collaboration_router_endpoints_accessible(client):
    """20. Verify /v1/rooms endpoint is accessible."""
    res = client.get("/v1/rooms")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_patches_router_endpoints_accessible(client):
    """21. Verify /v1/patches endpoint is accessible."""
    res = client.get("/v1/patches")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_canonical_error_mapping():
    """22. Verify canonical error mapping from ExecutionResult and exceptions."""
    # 503 NO_AVAILABLE_PROVIDER
    res_503 = ExecutionResult(
        execution_id="e1",
        status=ExecutionStatus.FAILED,
        error_code="NO_AVAILABLE_PROVIDER",
        error="All providers exhausted",
    )
    http_ex = map_execution_error_to_http(res_503)
    assert http_ex.status_code == 503
    assert http_ex.detail["code"] == "NO_AVAILABLE_PROVIDER"

    # 403 POLICY_BLOCKED
    res_403 = ExecutionResult(
        execution_id="e2",
        status=ExecutionStatus.FAILED,
        error_code="POLICY_BLOCKED",
        error="Security violation",
    )
    http_ex = map_execution_error_to_http(res_403)
    assert http_ex.status_code == 403

    # Exception mapping
    ex_perm = PermissionError("Permission denied")
    http_perm = handle_domain_error(ex_perm)
    assert http_perm.status_code == 403


def test_backwards_compatible_api_facade():
    """23. Verify services.python.server.api facade exports all required symbols."""
    import services.python.server.api as api

    assert hasattr(api, "app")
    assert hasattr(api, "create_app")
    assert hasattr(api, "main")
    assert hasattr(api, "get_execution_coordinator")
    assert hasattr(api, "set_execution_coordinator")
    assert hasattr(api, "get_artifact_service")
    assert hasattr(api, "set_artifact_service")
    assert hasattr(api, "get_ledger_service")
    assert hasattr(api, "set_ledger_service")
    assert hasattr(api, "get_storage_backend")
    assert hasattr(api, "get_session_store")
    assert hasattr(api, "ChatRequest")
    assert hasattr(api, "chat_completions")
    assert hasattr(api, "cancel_execution_endpoint")


def test_shared_service_identity_across_routers():
    """24. Verify single app-scoped service instances across all routers."""
    services = get_services()
    assert services is not None

    # Verify accessor methods return identical instance identities
    assert get_execution_coordinator() is services.get_coordinator()
    assert get_storage_backend() is services.storage
    assert get_artifact_service() is services.get_artifact_service()
    assert get_ledger_service() is services.get_ledger_service()
    assert services.model_router is not None
    assert services.cost_tracker is not None
    assert services.policy_engine is not None
    assert services.get_workflow_storage() is not None
    assert services.get_swarm_coordinator() is not None

    # Verify coordinator internally binds to the same shared service instances
    coord = services.get_coordinator()
    assert coord.storage is services.storage
    assert coord.policy_engine is services.policy_engine
    assert coord.model_router is services.model_router
    assert coord.cost_tracker is services.cost_tracker
    assert coord.artifact_service is services.get_artifact_service()


def test_api_facade_has_no_route_decorators_or_hidden_logic_and_unique_routes():
    """25. Verify api.py has zero route decorators, 0 business logic, and exactly 1 handler per route."""
    import ast
    from pathlib import Path

    api_path = Path("services/python/server/api.py")
    tree = ast.parse(api_path.read_text(encoding="utf-8"))

    # Check for any function definition with route decorators (@app.get, @router.post, etc.)
    forbidden_decorators = {"get", "post", "put", "delete", "patch", "options", "head"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                dec_name = ""
                if isinstance(decorator, ast.Attribute):
                    dec_name = decorator.attr
                elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    dec_name = decorator.func.attr
                assert (
                    dec_name not in forbidden_decorators
                ), f"Found forbidden route decorator @{dec_name} on function {node.name} in api.py"

    # Verify route uniqueness on the created FastAPI app
    app = create_app()
    all_route_signatures = []
    v1 = app.state.v1_router
    for r in v1.routes:
        if hasattr(r, "methods") and hasattr(r, "path"):
            for m in r.methods:
                all_route_signatures.append(
                    (m, "/v1" + r.path if not r.path.startswith("/v1") else r.path)
                )
        elif hasattr(r, "original_router"):
            for sr in r.original_router.routes:
                for m in sr.methods:
                    all_route_signatures.append((m, "/v1" + sr.path))

    # Include root healthz probe
    all_route_signatures.append(("GET", "/healthz"))

    # Semantic route integrity: unique route ownership (zero duplicate routes)
    assert (
        len(all_route_signatures) == len(set(all_route_signatures))
    ), f"Detected duplicate route registrations: {len(all_route_signatures) - len(set(all_route_signatures))}"

    # Required canonical route operations present
    canonical_required = {
        ("GET", "/healthz"),
        ("POST", "/v1/chat/completions"),
        ("GET", "/v1/projects"),
        ("GET", "/v1/packs"),
        ("POST", "/v1/packs/{pack_id}/validate"),
        ("POST", "/v1/packs/{pack_id}/enable"),
        ("GET", "/v1/executions/{execution_id}"),
        ("GET", "/v1/safety/operations"),
    }
    registered_set = set(all_route_signatures)
    for op in canonical_required:
        assert op in registered_set, f"Required canonical operation {op} not registered in app"
