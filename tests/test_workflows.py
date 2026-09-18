"""tests/test_workflows.py

Unit & integration tests for Workflow Engine (Phase 7 - Milestone M5).
Covers:
- Task 7.1: Workflow Schema, Lossless Parser & DAG Runtime Engine
"""

from fastapi.testclient import TestClient

from core.workflows import (
    StepResult,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowGateManager,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowParser,
    WorkflowPosition,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStorage,
)
from services.python.server.api import app


def _build_sample_workflow() -> WorkflowDefinition:
    """Helper to build a 3-node linear DAG workflow."""
    node_extract = WorkflowNode(
        id="extract_step",
        type=WorkflowNodeType.AGENT,
        name="Extract Entities",
        description="Extracts structured entities from user query",
        config={"model_tier": "instant", "system_prompt": "Entity extraction"},
        inputs={"query": "$workflow.input.query"},
        outputs=["entities", "response"],
        position=WorkflowPosition(x=100.0, y=150.0),
    )
    node_review = WorkflowNode(
        id="review_step",
        type=WorkflowNodeType.SKILL,
        name="Review Compliance",
        description="Scans extracted entities for policy compliance",
        config={"skill_id": "python_security_audit"},
        inputs={"content": "{{extract_step.response}}"},
        outputs=["compliance_score", "status"],
        position=WorkflowPosition(x=350.0, y=150.0),
    )
    node_decide = WorkflowNode(
        id="decide_step",
        type=WorkflowNodeType.CONDITION,
        name="Route Outcome",
        description="Routes based on compliance status",
        config={"expression": "{{review_step.status}} == 'success'"},
        inputs={"status": "{{review_step.status}}"},
        outputs=["branch"],
        position=WorkflowPosition(x=600.0, y=150.0),
    )
    node_pass = WorkflowNode(
        id="notify_approved",
        type=WorkflowNodeType.SKILL,
        name="Notify Approved",
        description="Emits approved status notification",
        inputs={"msg": "Compliance passed"},
        outputs=["notified"],
        position=WorkflowPosition(x=850.0, y=100.0),
    )
    node_fail = WorkflowNode(
        id="notify_rejected",
        type=WorkflowNodeType.SKILL,
        name="Notify Rejected",
        description="Emits rejection status notification",
        inputs={"msg": "Compliance failed"},
        outputs=["notified"],
        position=WorkflowPosition(x=850.0, y=200.0),
    )

    edge_1 = WorkflowEdge(id="e1", source="extract_step", target="review_step")
    edge_2 = WorkflowEdge(id="e2", source="review_step", target="decide_step")
    edge_3 = WorkflowEdge(id="e3", source="decide_step", target="notify_approved", condition="true")
    edge_4 = WorkflowEdge(
        id="e4", source="decide_step", target="notify_rejected", condition="false"
    )

    return WorkflowDefinition(
        id="compliance_pipeline",
        name="Compliance Evaluation Pipeline",
        description="Automated entity extraction and compliance verification pipeline",
        version="1.2.0",
        status=WorkflowStatus.READY,
        nodes=[node_extract, node_review, node_decide, node_pass, node_fail],
        edges=[edge_1, edge_2, edge_3, edge_4],
        inputs_schema={"query": {"type": "string"}},
        outputs_schema={"status": {"type": "string"}},
        tags=["compliance", "nlp", "automation"],
    )


def test_workflow_node_and_edge_models():
    """Verify domain models, enums, and dict/JSON serialization."""
    wf = _build_sample_workflow()
    assert wf.id == "compliance_pipeline"
    assert len(wf.nodes) == 5
    assert len(wf.edges) == 4

    # Check node types
    assert wf.nodes[0].type == WorkflowNodeType.AGENT
    assert wf.nodes[1].type == WorkflowNodeType.SKILL
    assert wf.nodes[2].type == WorkflowNodeType.CONDITION

    # Check position
    assert wf.nodes[0].position.x == 100.0

    # Serialization to dict
    d = wf.to_dict()
    assert d["id"] == "compliance_pipeline"
    assert d["version"] == "1.2.0"
    assert len(d["nodes"]) == 5
    assert d["nodes"][0]["type"] == "agent"


def test_workflow_parser_yaml_lossless_roundtrip():
    """Verify lossless YAML <-> JSON <-> WorkflowDefinition round-trip parsing."""
    original_wf = _build_sample_workflow()

    # 1. To YAML
    yaml_content = WorkflowParser.to_yaml(original_wf)
    assert "compliance_pipeline" in yaml_content
    assert "extract_step" in yaml_content
    assert "review_step" in yaml_content

    # 2. From YAML
    restored_wf = WorkflowParser.from_yaml(yaml_content)
    assert restored_wf.id == original_wf.id
    assert restored_wf.name == original_wf.name
    assert len(restored_wf.nodes) == len(original_wf.nodes)
    assert len(restored_wf.edges) == len(original_wf.edges)

    for orig_node, rest_node in zip(original_wf.nodes, restored_wf.nodes):
        assert orig_node.id == rest_node.id
        assert orig_node.type == rest_node.type
        assert orig_node.inputs == rest_node.inputs

    # 3. Validation
    is_valid, errors = WorkflowParser.validate(restored_wf)
    assert is_valid is True
    assert len(errors) == 0


def test_workflow_parser_cycle_detection():
    """Verify Kahn's algorithm in WorkflowParser detects cycles and missing nodes."""
    wf = _build_sample_workflow()

    # Create cycle: decide_step -> extract_step
    cycle_edge = WorkflowEdge(id="e_cycle", source="decide_step", target="extract_step")
    wf.edges.append(cycle_edge)

    is_valid, errors = WorkflowParser.validate(wf)
    assert is_valid is False
    assert any("Cycle detected" in err or "entry node" in err for err in errors)

    # Missing node reference
    broken_edge_wf = _build_sample_workflow()
    broken_edge_wf.edges.append(
        WorkflowEdge(id="e_bad", source="extract_step", target="phantom_node")
    )
    is_valid_broken, errors_broken = WorkflowParser.validate(broken_edge_wf)
    assert is_valid_broken is False
    assert any("phantom_node" in err for err in errors_broken)


def test_workflow_engine_topological_execution():
    """Verify live DAG execution, step dependency resolution, and state parameter binding."""
    wf = _build_sample_workflow()
    engine = WorkflowEngine()

    run = engine.run(wf, inputs={"query": "Customer data export to S3"})
    assert run.status == WorkflowRunStatus.COMPLETED
    assert run.workflow_id == "compliance_pipeline"
    assert len(run.step_results) == 4

    # Step 1 (Agent)
    step_1 = run.step_results["extract_step"]
    assert step_1.status == "completed"
    assert "Customer data export" in step_1.outputs["response"]

    # Step 2 (Skill) - parameter binding {{extract_step.response}} resolved
    step_2 = run.step_results["review_step"]
    assert step_2.status == "completed"
    assert "Customer data export" in step_2.inputs["content"]
    assert step_2.outputs["status"] == "success"

    # Step 3 (Condition) - evaluate success condition
    step_3 = run.step_results["decide_step"]
    assert step_3.status == "completed"
    assert step_3.outputs["condition_result"] is True
    assert step_3.outputs["branch"] == "true"

    # Step 4 (Notify approved - active branch taken)
    step_4 = run.step_results["notify_approved"]
    assert step_4.status == "completed"
    assert "notify_rejected" not in run.step_results

    # Total cost tracked
    assert run.total_cost_usd > 0.0
    assert run.completed_at is not None


def test_workflow_engine_dry_run_simulation():
    """Verify dry-run simulation produces mock step outputs and computes trace without costs."""
    wf = _build_sample_workflow()
    engine = WorkflowEngine()

    run = engine.run(wf, inputs={"query": "Simulated query"}, dry_run=True)
    assert run.status == WorkflowRunStatus.COMPLETED
    assert len(run.step_results) == 4

    for nid, step in run.step_results.items():
        assert step.status == "completed"
        assert step.outputs.get("simulated") is True
        assert step.cost_usd == 0.0

    assert run.total_cost_usd == 0.0


def test_workflow_storage_crud_and_runs():
    """Verify SQLite storage CRUD operations and run persistence with cascade deletion."""
    storage = WorkflowStorage(db_path=":memory:")

    # Default seeded workflow exists
    default_wf = storage.get_workflow("wf_code_audit_and_fix")
    assert default_wf is not None
    assert default_wf.name == "Automated Code Audit & Remediation"

    # Save custom workflow
    wf = _build_sample_workflow()
    saved = storage.save_workflow(wf)
    assert saved.id == "compliance_pipeline"

    # Fetch custom workflow
    fetched = storage.get_workflow("compliance_pipeline")
    assert fetched is not None
    assert len(fetched.nodes) == 5

    # List workflows
    all_wfs = storage.list_workflows()
    assert len(all_wfs) >= 2
    tagged = storage.list_workflows(tag="compliance")
    assert len(tagged) == 1
    assert tagged[0].id == "compliance_pipeline"

    # Save execution run
    run = WorkflowRun(
        run_id="run_test_123",
        workflow_id=wf.id,
        status=WorkflowRunStatus.COMPLETED,
        inputs={"query": "test query"},
        outputs={"status": "success"},
        step_results={
            "extract_step": StepResult(
                node_id="extract_step",
                node_type=WorkflowNodeType.AGENT,
                status="completed",
                outputs={"response": "extracted"},
            )
        },
        total_cost_usd=0.005,
    )
    storage.save_run(run)

    # Get run
    fetched_run = storage.get_run("run_test_123")
    assert fetched_run is not None
    assert fetched_run.status == WorkflowRunStatus.COMPLETED
    assert fetched_run.total_cost_usd == 0.005
    assert "extract_step" in fetched_run.step_results

    # List runs
    runs = storage.list_runs(workflow_id=wf.id)
    assert len(runs) == 1
    assert runs[0].run_id == "run_test_123"

    # Delete workflow cascades to its runs
    deleted = storage.delete_workflow(wf.id)
    assert deleted is True
    assert storage.get_workflow(wf.id) is None
    assert storage.get_run("run_test_123") is None


def test_workflow_api_validate():
    """Verify POST /v1/workflows/validate for valid/invalid YAML and JSON definitions."""
    client = TestClient(app)
    wf = _build_sample_workflow()
    yaml_str = WorkflowParser.to_yaml(wf)

    # Validate valid YAML
    res = client.post("/v1/workflows/validate", json={"definition_yaml": yaml_str})
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["errors"] == []
    assert data["node_count"] == 5
    assert data["edge_count"] == 4

    # Validate valid JSON
    res_json = client.post("/v1/workflows/validate", json={"definition_json": wf.to_dict()})
    assert res_json.status_code == 200
    assert res_json.json()["valid"] is True

    # Validate cyclic invalid JSON
    bad_wf = _build_sample_workflow()
    bad_wf.edges.append(WorkflowEdge(id="e_cycle", source="decide_step", target="extract_step"))
    res_bad = client.post("/v1/workflows/validate", json={"definition_json": bad_wf.to_dict()})
    assert res_bad.status_code == 200
    data_bad = res_bad.json()
    assert data_bad["valid"] is False
    assert len(data_bad["errors"]) > 0


def test_workflow_api_crud():
    """Verify REST API CRUD endpoints for workflow definitions."""
    client = TestClient(app)

    # 1. List
    res = client.get("/v1/workflows")
    assert res.status_code == 200
    wfs = res.json()
    assert len(wfs) >= 1
    assert any(w["id"] == "wf_code_audit_and_fix" for w in wfs)

    # 2. Create
    custom_wf = _build_sample_workflow()
    custom_wf.id = "api_test_crud_pipeline"
    create_res = client.post("/v1/workflows", json=custom_wf.to_dict())
    assert create_res.status_code == 200
    created = create_res.json()
    assert created["id"] == "api_test_crud_pipeline"

    # 3. Get
    get_res = client.get(f"/v1/workflows/{custom_wf.id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == custom_wf.name

    # 4. Update
    custom_wf.name = "Updated Pipeline Name"
    put_res = client.put(f"/v1/workflows/{custom_wf.id}", json=custom_wf.to_dict())
    assert put_res.status_code == 200
    assert put_res.json()["name"] == "Updated Pipeline Name"

    # 5. Delete
    del_res = client.delete(f"/v1/workflows/{custom_wf.id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # Verify 404 after deletion
    get_del_res = client.get(f"/v1/workflows/{custom_wf.id}")
    assert get_del_res.status_code == 404


def test_workflow_api_dry_run():
    """Verify POST /v1/workflows/{id}/dry-run simulates execution correctly."""
    client = TestClient(app)
    wf = _build_sample_workflow()
    wf.id = "api_dry_run_test_wf"
    client.post("/v1/workflows", json=wf.to_dict())

    res = client.post(
        f"/v1/workflows/{wf.id}/dry-run",
        json={"inputs": {"query": "Dry run verification"}},
    )
    assert res.status_code == 200
    run_data = res.json()
    assert run_data["workflow_id"] == wf.id
    assert run_data["status"] == "completed"
    assert len(run_data["step_results"]) == 4
    assert run_data["total_cost_usd"] == 0.0

    # Cleanup
    client.delete(f"/v1/workflows/{wf.id}")


def test_workflow_api_run_history():
    """Verify POST /v1/workflows/{id}/run and GET /v1/workflows/{id}/runs history."""
    client = TestClient(app)
    wf = _build_sample_workflow()
    wf.id = "api_run_history_test_wf"
    client.post("/v1/workflows", json=wf.to_dict())

    # Execute live run
    run_res = client.post(
        f"/v1/workflows/{wf.id}/run",
        json={"inputs": {"query": "Live run audit test"}, "dry_run": False},
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "completed"

    # List runs for workflow
    list_res = client.get(f"/v1/workflows/{wf.id}/runs")
    assert list_res.status_code == 200
    runs = list_res.json()
    assert len(runs) >= 1
    assert any(r["run_id"] == run_id for r in runs)

    # Get specific run details
    get_run_res = client.get(f"/v1/workflows/{wf.id}/runs/{run_id}")
    assert get_run_res.status_code == 200
    detail = get_run_res.json()
    assert detail["run_id"] == run_id
    assert "extract_step" in detail["step_results"]
    assert detail["total_cost_usd"] > 0.0

    # Cleanup
    client.delete(f"/v1/workflows/{wf.id}")


def _build_gated_workflow() -> WorkflowDefinition:
    """Helper to build a workflow containing an interactive human approval gate with branch edges."""
    node_prep = WorkflowNode(
        id="prep_step",
        type=WorkflowNodeType.AGENT,
        name="Prepare Action",
        description="Prepares a high risk operation",
        config={"model_tier": "instant"},
        inputs={"target": "$workflow.input.target"},
        outputs=["plan", "risk_score"],
    )
    node_gate = WorkflowNode(
        id="human_gate",
        type=WorkflowNodeType.GATE,
        name="Review & Approval",
        description="Requires operator approval before deployment",
        config={"timeout_seconds": 1800},
        inputs={"plan": "{{prep_step.plan}}"},
        outputs=["approved", "reviewer"],
    )
    node_deploy = WorkflowNode(
        id="deploy_step",
        type=WorkflowNodeType.SKILL,
        name="Deploy Change",
        description="Applies approved change",
        inputs={"plan": "{{prep_step.plan}}"},
        outputs=["deployed"],
    )
    node_rollback = WorkflowNode(
        id="rollback_step",
        type=WorkflowNodeType.SKILL,
        name="Rollback Plan",
        description="Rolls back on rejection",
        inputs={"plan": "{{prep_step.plan}}"},
        outputs=["rolled_back"],
    )
    node_sandbox = WorkflowNode(
        id="sandbox_step",
        type=WorkflowNodeType.SKILL,
        name="Sandbox Test",
        description="Alternative redirected target node",
        inputs={"plan": "{{prep_step.plan}}"},
        outputs=["sandboxed"],
    )

    edges = [
        WorkflowEdge(id="e1", source="prep_step", target="human_gate"),
        WorkflowEdge(id="e2", source="human_gate", target="deploy_step", condition="approved"),
        WorkflowEdge(id="e3", source="human_gate", target="rollback_step", condition="false"),
        WorkflowEdge(id="e4", source="human_gate", target="sandbox_step", condition="redirect"),
    ]

    return WorkflowDefinition(
        id="gated_deploy_pipeline",
        name="Gated Deployment Pipeline",
        description="Pipeline requiring manual review before production execution",
        version="1.0.0",
        status=WorkflowStatus.ACTIVE,
        nodes=[node_prep, node_gate, node_deploy, node_rollback, node_sandbox],
        edges=edges,
        inputs_schema={"target": {"type": "string"}},
        tags=["deployment", "safety", "human-gate"],
    )


def test_workflow_gate_pausing():
    """Verify workflow execution pauses at GATE node and collects pending gate metadata."""
    wf = _build_gated_workflow()
    engine = WorkflowEngine()

    run = engine.run(wf, inputs={"target": "prod-database-cluster"}, dry_run=False)
    assert run.status == WorkflowRunStatus.WAITING_APPROVAL
    assert run.current_node_id == "human_gate"
    assert run.pending_gate is not None
    assert run.pending_gate["node_id"] == "human_gate"
    assert "prod-database-cluster" in str(run.pending_gate["inputs"])
    assert "prep_step" in run.step_results
    assert "deploy_step" not in run.step_results


def test_workflow_gate_manager_list_pending():
    """Verify WorkflowGateManager queries and lists active pending gates across runs."""
    storage = WorkflowStorage(db_path=":memory:")
    wf = _build_gated_workflow()
    storage.save_workflow(wf)

    engine = WorkflowEngine(storage=storage)
    run = engine.run(wf, inputs={"target": "staging-host"}, dry_run=False)
    assert run.status == WorkflowRunStatus.WAITING_APPROVAL

    gate_mgr = WorkflowGateManager(storage=storage, engine=engine)
    pending_list = gate_mgr.list_pending_gates()
    assert len(pending_list) == 1

    entry = pending_list[0]
    assert entry["run_id"] == run.run_id
    assert entry["workflow_id"] == wf.id
    assert entry["workflow_name"] == "Gated Deployment Pipeline"
    assert entry["node_id"] == "human_gate"
    assert entry["timeout_seconds"] == 1800


def test_workflow_gate_approval_and_resumption():
    """Verify approval of paused gate executes downstream approved branch."""
    storage = WorkflowStorage(db_path=":memory:")
    wf = _build_gated_workflow()
    storage.save_workflow(wf)

    engine = WorkflowEngine(storage=storage)
    run = engine.run(wf, inputs={"target": "eu-central-1"}, dry_run=False)

    gate_mgr = WorkflowGateManager(storage=storage, engine=engine)
    resumed = gate_mgr.approve_gate(
        workflow_id=wf.id,
        run_id=run.run_id,
        reviewer="senior_devops",
    )

    assert resumed.status == WorkflowRunStatus.COMPLETED
    assert "human_gate" in resumed.step_results
    assert resumed.step_results["human_gate"].status == "completed"
    assert resumed.step_results["human_gate"].outputs["approved"] is True
    assert resumed.step_results["human_gate"].outputs["reviewer"] == "senior_devops"

    # Approved edge led to deploy_step
    assert "deploy_step" in resumed.step_results
    assert resumed.step_results["deploy_step"].status == "completed"
    assert "rollback_step" not in resumed.step_results


def test_workflow_gate_rejection_and_branching():
    """Verify rejection of paused gate executes conditional rejection branch."""
    storage = WorkflowStorage(db_path=":memory:")
    wf = _build_gated_workflow()
    storage.save_workflow(wf)

    engine = WorkflowEngine(storage=storage)
    run = engine.run(wf, inputs={"target": "unverified-env"}, dry_run=False)

    gate_mgr = WorkflowGateManager(storage=storage, engine=engine)
    resumed = gate_mgr.reject_gate(
        workflow_id=wf.id,
        run_id=run.run_id,
        reviewer="compliance_officer",
        reason="Security audit failed",
    )

    assert resumed.status == WorkflowRunStatus.COMPLETED
    assert "human_gate" in resumed.step_results
    assert resumed.step_results["human_gate"].status == "rejected"
    assert resumed.step_results["human_gate"].outputs["approved"] is False

    # Rejected edge (condition="false") led to rollback_step
    assert "rollback_step" in resumed.step_results
    assert resumed.step_results["rollback_step"].status == "completed"
    assert "deploy_step" not in resumed.step_results


def test_workflow_gate_api_redirect_and_endpoints():
    """Verify REST API gate management, approval listing, and DAG redirection."""
    client = TestClient(app)
    wf = _build_gated_workflow()
    wf.id = "api_gated_test_wf"
    client.post("/v1/workflows", json=wf.to_dict())

    # 1. Trigger execution -> pauses at gate
    run_res = client.post(
        f"/v1/workflows/{wf.id}/run",
        json={"inputs": {"target": "critical-zone"}, "dry_run": False},
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "waiting_approval"

    # 2. Query pending gates
    pending_res = client.get("/v1/workflows/gates/pending")
    assert pending_res.status_code == 200
    pending_gates = pending_res.json()
    assert any(g["run_id"] == run_id for g in pending_gates)

    # 3. Redirect to alternate node (sandbox_step)
    redir_res = client.post(
        f"/v1/workflows/{wf.id}/runs/{run_id}/redirect",
        json={
            "target_node_id": "sandbox_step",
            "reviewer": "qa_lead",
            "input_overrides": {"isolation_level": "strict"},
        },
    )
    assert redir_res.status_code == 200
    resumed = redir_res.json()
    assert resumed["status"] == "completed"
    assert "human_gate" in resumed["step_results"]
    assert resumed["step_results"]["human_gate"]["status"] == "redirected"
    assert resumed["step_results"]["human_gate"]["outputs"]["redirected_to"] == "sandbox_step"
    assert "sandbox_step" in resumed["step_results"]

    # Cleanup
    client.delete(f"/v1/workflows/{wf.id}")
