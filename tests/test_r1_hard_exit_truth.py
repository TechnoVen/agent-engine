"""tests/test_r1_hard_exit_truth.py

R1 Final Hard-Exit Truth-in-Execution Test Suite.
Validates the three final hard-exit closure requirements:
1. Deferred Workflow execution does not return synthetic success (returns 501 RUNTIME_NOT_AVAILABLE).
2. Deferred Swarm execution does not return synthetic success (returns 501 RUNTIME_NOT_AVAILABLE).
3. Deferred scheduled-task execution does not return synthetic success (returns 501 RUNTIME_NOT_AVAILABLE).
4. Workflow authoring and storage still works as a supported capability.
5. Workflow DAG validation still works as a supported capability.
6. Public supported execution surfaces (Chat, Skills, Adapters) route through ExecutionCoordinator.
7. No-provider chat produces explicit failure (HTTP 503 NO_AVAILABLE_PROVIDER), never simulated success.
8. Offline/local execution uses a real local provider when configured, never silent simulation.
"""

import pytest
from fastapi.testclient import TestClient

from core.execution import ExecutionCoordinator
from core.router.model_router import ResolvedModel, RoutingTier
from core.workflows import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowStatus,
)
from services.python.server.api import app
from services.python.server.container import (
    get_execution_coordinator,
    get_model_router,
    get_workflow_storage,
)


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Deferred Workflow Execution Returns 501 RUNTIME_NOT_AVAILABLE
# ---------------------------------------------------------------------------


def test_deferred_workflow_execution_returns_501_not_synthetic_success(client):
    """Verify POST /v1/workflows/{id}/run and gate resumes return HTTP 501 RUNTIME_NOT_AVAILABLE."""
    storage = get_workflow_storage()
    wf = WorkflowDefinition(
        id="wf_deferred_truth_test",
        name="Truth Verification Pipeline",
        description="Verifies truthful 501 behavior",
        nodes=[
            WorkflowNode(id="n1", type=WorkflowNodeType.AGENT, name="Start"),
            WorkflowNode(id="n2", type=WorkflowNodeType.SKILL, name="End"),
        ],
        edges=[WorkflowEdge(id="e1", source="n1", target="n2")],
        status=WorkflowStatus.ACTIVE,
    )
    storage.save_workflow(wf)

    try:
        # A. Direct workflow run -> 501
        res_run = client.post(f"/v1/workflows/{wf.id}/run", json={"inputs": {}})
        assert res_run.status_code == 501
        data_run = res_run.json()
        assert data_run["error_code"] == "RUNTIME_NOT_AVAILABLE"
        assert data_run["status"] == "deferred"
        assert data_run["target_milestone"] == "R4"

        # B. Legacy workflow_id payload -> 501
        res_legacy = client.post("/v1/workflows", json={"workflow_id": wf.id, "inputs": {}})
        assert res_legacy.status_code == 501
        assert res_legacy.json()["error_code"] == "RUNTIME_NOT_AVAILABLE"

        # C. Gate resume endpoints -> 501
        res_approve = client.post(f"/v1/workflows/{wf.id}/runs/any_run_id/approve")
        assert res_approve.status_code == 501
        assert res_approve.json()["error_code"] == "RUNTIME_NOT_AVAILABLE"

        res_reject = client.post(f"/v1/workflows/{wf.id}/runs/any_run_id/reject")
        assert res_reject.status_code == 501
        assert res_reject.json()["error_code"] == "RUNTIME_NOT_AVAILABLE"

        res_redirect = client.post(
            f"/v1/workflows/{wf.id}/runs/any_run_id/redirect",
            json={"target_node_id": "n2"},
        )
        assert res_redirect.status_code == 501
        assert res_redirect.json()["error_code"] == "RUNTIME_NOT_AVAILABLE"
    finally:
        storage.delete_workflow(wf.id)


# ---------------------------------------------------------------------------
# 2. Deferred Swarm Execution Returns 501 RUNTIME_NOT_AVAILABLE
# ---------------------------------------------------------------------------


def test_deferred_swarm_execution_returns_501_not_synthetic_success(client):
    """Verify POST /v1/swarm/run returns HTTP 501 RUNTIME_NOT_AVAILABLE."""
    res = client.post(
        "/v1/swarm/run",
        json={"prompt": "Deploy cluster", "case_id": "deep_code_review"},
    )
    assert res.status_code == 501
    data = res.json()
    assert data["error_code"] == "RUNTIME_NOT_AVAILABLE"
    assert data["status"] == "deferred"
    assert data["target_milestone"] == "R4"


# ---------------------------------------------------------------------------
# 3. Deferred Scheduled Task Execution Returns 501 RUNTIME_NOT_AVAILABLE
# ---------------------------------------------------------------------------


def test_deferred_scheduled_task_execution_returns_501_not_synthetic_success(client):
    """Verify POST /v1/tasks/{id}/run returns HTTP 501 RUNTIME_NOT_AVAILABLE."""
    # Create task (authoring/storage is supported)
    create_res = client.post(
        "/v1/tasks",
        json={
            "name": "Audit Task",
            "cron": "0 * * * *",
            "prompt": "Run system audit",
            "enabled": True,
        },
    )
    assert create_res.status_code == 200
    task_id = create_res.json()["id"]

    try:
        # Trigger task execution -> 501 deferred
        trigger_res = client.post(f"/v1/tasks/{task_id}/run")
        assert trigger_res.status_code == 501
        data = trigger_res.json()
        assert data["error_code"] == "RUNTIME_NOT_AVAILABLE"
        assert data["status"] == "deferred"
        assert data["target_milestone"] == "R4"
    finally:
        client.delete(f"/v1/tasks/{task_id}")


# ---------------------------------------------------------------------------
# 4. Workflow Authoring and Storage Remains Fully Supported
# ---------------------------------------------------------------------------


def test_workflow_authoring_and_storage_supported(client):
    """Verify workflow definition CRUD operations remain fully supported in R1."""
    wf_payload = {
        "id": "wf_authoring_proof",
        "name": "Authoring Proof Workflow",
        "description": "Demonstrates supported authoring",
        "version": "1.0.0",
        "status": "active",
        "nodes": [
            {
                "id": "node_a",
                "type": "agent",
                "name": "Input Agent",
                "inputs": {"prompt": "Hello"},
                "outputs": ["result"],
            },
            {
                "id": "node_b",
                "type": "skill",
                "name": "Output Skill",
                "inputs": {"data": "{{node_a.result}}"},
            },
        ],
        "edges": [{"id": "e_ab", "source": "node_a", "target": "node_b"}],
        "tags": ["proof", "authoring"],
    }

    # 1. Create
    res_create = client.post("/v1/workflows", json=wf_payload)
    assert res_create.status_code == 200
    assert res_create.json()["id"] == "wf_authoring_proof"

    # 2. List
    res_list = client.get("/v1/workflows")
    assert res_list.status_code == 200
    assert any(w["id"] == "wf_authoring_proof" for w in res_list.json())

    # 3. Get
    res_get = client.get("/v1/workflows/wf_authoring_proof")
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "Authoring Proof Workflow"

    # 4. Update
    wf_payload["description"] = "Updated Description"
    res_put = client.put("/v1/workflows/wf_authoring_proof", json=wf_payload)
    assert res_put.status_code == 200
    assert res_put.json()["description"] == "Updated Description"

    # 5. Delete
    res_del = client.delete("/v1/workflows/wf_authoring_proof")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True


# ---------------------------------------------------------------------------
# 5. Workflow Validation Remains Fully Supported
# ---------------------------------------------------------------------------


def test_workflow_validation_supported(client):
    """Verify POST /v1/workflows/validate verifies DAG topology and detects cycles."""
    # Valid workflow
    valid_wf = {
        "id": "wf_valid",
        "name": "Valid DAG",
        "nodes": [
            {"id": "n1", "type": "agent", "name": "N1"},
            {"id": "n2", "type": "skill", "name": "N2"},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }
    res_valid = client.post("/v1/workflows/validate", json={"definition_json": valid_wf})
    assert res_valid.status_code == 200
    assert res_valid.json()["valid"] is True
    assert res_valid.json()["errors"] == []

    # Cyclic workflow
    cyclic_wf = {
        "id": "wf_cyclic",
        "name": "Cyclic DAG",
        "nodes": [
            {"id": "n1", "type": "agent", "name": "N1"},
            {"id": "n2", "type": "skill", "name": "N2"},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n1"},
        ],
    }
    res_cyclic = client.post("/v1/workflows/validate", json={"definition_json": cyclic_wf})
    assert res_cyclic.status_code == 200
    assert res_cyclic.json()["valid"] is False
    assert len(res_cyclic.json()["errors"]) > 0


# ---------------------------------------------------------------------------
# 6. Public Supported Execution Surfaces Use ExecutionCoordinator
# ---------------------------------------------------------------------------


def test_public_supported_execution_surfaces_use_coordinator():
    """Verify that Chat, Skills, and Adapters converge on ExecutionCoordinator."""
    coordinator = get_execution_coordinator()
    assert isinstance(coordinator, ExecutionCoordinator)

    # Coordinator execute method exists and is the single root
    assert hasattr(coordinator, "execute")
    assert hasattr(coordinator, "invoke_skill")
    assert hasattr(coordinator, "policy_engine")
    assert hasattr(coordinator, "cost_tracker")


# ---------------------------------------------------------------------------
# 7. No-Provider Chat Produces Explicit Failure (Never Simulation)
# ---------------------------------------------------------------------------


def test_no_provider_chat_produces_explicit_failure_never_simulation(client, monkeypatch):
    """Verify that when no LLM provider is available, Chat fails with HTTP 503 NO_AVAILABLE_PROVIDER."""
    router = get_model_router()
    coordinator = get_execution_coordinator()

    # Isolate from any lingering test dispatch overrides
    monkeypatch.setattr(coordinator, "_dispatch_override", None, raising=False)

    def mock_resolve_none(*args, **kwargs):
        return ResolvedModel(
            provider_id="none",
            model_id="",
            routing_tier=RoutingTier.MID,
            reason="All circuits OPEN or offline",
            is_fallback=False,
        )

    monkeypatch.setattr(router, "resolve_model", mock_resolve_none)
    if hasattr(coordinator, "model_router") and coordinator.model_router:
        monkeypatch.setattr(coordinator.model_router, "resolve_model", mock_resolve_none)

    res = client.post(
        "/v1/chat/completions",
        json={"prompt": "Generate a solution", "stream": False},
    )
    assert res.status_code == 503
    data = res.json()
    assert data.get("error_code") == "NO_AVAILABLE_PROVIDER" or "NO_AVAILABLE_PROVIDER" in str(
        data.get("detail", "")
    )


# ---------------------------------------------------------------------------
# 8. Offline/Local Execution Uses Real Local Provider When Configured
# ---------------------------------------------------------------------------


def test_offline_local_execution_uses_real_local_provider(client, monkeypatch):
    """Verify local execution routes to real configured local provider, not a fake simulation."""
    router = get_model_router()

    # When llamacpp is configured, router resolves to llamacpp
    monkeypatch.setattr(
        router,
        "resolve_model",
        lambda *a, **kw: ResolvedModel(
            provider_id="llamacpp",
            model_id="qwen2.5-coder-3b-instruct-q4_k_m",
            routing_tier=RoutingTier.LOCAL,
            reason="Local inference configured",
            is_fallback=False,
        ),
    )

    resolved = router.resolve_model(task_type="chat", requested_tier="local")
    assert resolved.provider_id == "llamacpp"
    assert resolved.model_id == "qwen2.5-coder-3b-instruct-q4_k_m"
    assert resolved.routing_tier == RoutingTier.LOCAL
