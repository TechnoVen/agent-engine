"""tests/test_workflows.py

Unit & integration tests for Workflow Engine (Phase 7 - Milestone M5).
Covers:
- Task 7.1: Workflow Schema, Lossless Parser & DAG Runtime Engine
"""

import asyncio
from fastapi.testclient import TestClient

from core.workflows import (
    StepResult,
    SwarmAgentSpec,
    SwarmCoordinator,
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


def test_swarm_featured_cases_listing():
    """Verify built-in featured swarm team cases are available and well-formed."""
    coordinator = SwarmCoordinator()
    cases = coordinator.list_cases()
    assert len(cases) >= 3
    case_ids = [c.id for c in cases]
    assert "build_deploy_api" in case_ids
    assert "deep_code_review" in case_ids
    assert "market_research" in case_ids

    for case in cases:
        assert case.title
        assert case.tagline
        assert case.default_prompt
        assert len(case.agents) >= 3
        for agent in case.agents:
            assert agent.id
            assert agent.name
            assert agent.role
            assert agent.model_tier
            assert agent.estimated_cost_usd > 0.0


def test_swarm_cost_estimator():
    """Verify SwarmCoordinator cost estimator adheres to model tier multipliers and 90/9/1 rules."""
    coordinator = SwarmCoordinator()
    c = coordinator.get_case("build_deploy_api")
    assert c is not None

    # instant tier
    cost_instant = coordinator.estimate_cost(c.agents, model_tier="instant")
    base_sum = sum(a.estimated_cost_usd for a in c.agents)
    assert cost_instant == round(base_sum, 4)

    # reasoning tier (2.5x multiplier)
    cost_reasoning = coordinator.estimate_cost(c.agents, model_tier="reasoning")
    assert cost_reasoning == round(base_sum * 2.5, 4)
    assert cost_reasoning > cost_instant


def test_swarm_parallel_execution():
    """Verify concurrent agent execution, timing, and attribution markdown synthesis."""
    coordinator = SwarmCoordinator()
    prompt = "Create a real-time event telemetry gateway"
    result = asyncio.run(
        coordinator.run_swarm(prompt=prompt, case_id="build_deploy_api", model_tier="instant")
    )

    assert result.status == "completed"
    assert result.prompt == prompt
    assert result.model_tier == "instant"
    assert len(result.agent_results) == 4
    assert result.total_cost_usd > 0.0
    assert result.total_time_ms > 0.0

    # Verify each agent's execution details
    for agent_res in result.agent_results:
        assert agent_res.status == "completed"
        assert agent_res.progress_percent == 100
        assert agent_res.output != ""
        assert agent_res.execution_time_ms > 0.0

    # Verify synthesized aggregated markdown contains attribution sections
    assert "# 🐝 Swarm Execution Synthesis" in result.aggregated_output
    assert "Architect" in result.aggregated_output
    assert "Coder" in result.aggregated_output
    assert "Tester" in result.aggregated_output
    assert "Deployer" in result.aggregated_output


def test_swarm_partial_failure_tolerance():
    """Verify swarm coordinator isolates agent failures and returns partial synthesis."""
    coordinator = SwarmCoordinator()
    agents = [
        SwarmAgentSpec(
            id="ok_agent",
            name="Reliable Agent",
            role="Data Processor",
            estimated_cost_usd=0.001,
        ),
        SwarmAgentSpec(
            id="err_agent",
            name="Failing Agent",
            role="Fault Injection",
            estimated_cost_usd=0.001,
        ),
    ]

    # Mock _execute_single_agent to simulate failure on err_agent
    orig_exec = coordinator._execute_single_agent

    async def mock_execute(agent, prompt, model_tier):
        if agent.id == "err_agent":
            raise RuntimeError("Simulated network timeout during inference")
        return await orig_exec(agent, prompt, model_tier)

    coordinator._execute_single_agent = mock_execute

    result = asyncio.run(coordinator.run_swarm(prompt="Process event pipeline", agents=agents))
    assert result.status == "partial_failure"
    assert len(result.agent_results) == 2

    # Check first agent succeeded
    res_ok = next(r for r in result.agent_results if r.agent_id == "ok_agent")
    assert res_ok.status == "completed"

    # Check second agent failed gracefully
    res_err = next(r for r in result.agent_results if r.agent_id == "err_agent")
    assert res_err.status == "failed"
    assert "Simulated network timeout" in (res_err.error or "")

    # Aggregated output mentions the failure
    assert "Failing Agent" in result.aggregated_output
    assert "Failed" in result.aggregated_output


def test_swarm_api_endpoints():
    """Verify REST API endpoints for /v1/swarm/cases, /v1/swarm/estimate, and /v1/swarm/run."""
    client = TestClient(app)

    # 1. GET /v1/swarm/cases
    cases_res = client.get("/v1/swarm/cases")
    assert cases_res.status_code == 200
    cases_data = cases_res.json()
    assert len(cases_data) >= 3
    assert any(c["id"] == "deep_code_review" for c in cases_data)

    # 2. POST /v1/swarm/estimate
    est_res = client.post(
        "/v1/swarm/estimate",
        json={"case_id": "deep_code_review", "model_tier": "instant"},
    )
    assert est_res.status_code == 200
    est_data = est_res.json()
    assert est_data["estimated_cost_usd"] > 0.0
    assert est_data["agent_count"] >= 3
    assert est_data["model_tier"] == "instant"

    # 3. POST /v1/swarm/run
    run_res = client.post(
        "/v1/swarm/run",
        json={
            "prompt": "Audit user auth flows for security vulnerabilities",
            "case_id": "deep_code_review",
            "model_tier": "instant",
        },
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    assert run_data["status"] == "completed"
    assert len(run_data["agent_results"]) >= 3
    assert "Swarm Execution Synthesis" in run_data["aggregated_output"]
    assert run_data["total_cost_usd"] > 0.0


def test_workflow_builder_canvas_payload_roundtrip():
    """Verify lossless round-trip serialization between desktop canvas JSON and WorkflowDefinition."""
    canvas_payload = {
        "id": "wf_canvas_sample_roundtrip",
        "name": "Canvas Interactive Pipeline",
        "description": "Orchestrates prompt analysis, security check, and approval gate",
        "version": "1.2.0",
        "status": "active",
        "nodes": [
            {
                "id": "node_input",
                "type": "agent",
                "name": "Input Analyzer",
                "description": "Extracts intentions",
                "position": {"x": 80.0, "y": 140.0},
                "config": {"model_tier": "instant"},
                "inputs": {"query": "$workflow.input.query"},
                "outputs": ["parsed_plan"],
            },
            {
                "id": "node_gate",
                "type": "gate",
                "name": "Operator Review",
                "description": "Pauses for human approval",
                "position": {"x": 360.0, "y": 140.0},
                "config": {"timeout_seconds": 1200},
                "inputs": {"plan": "{{node_input.parsed_plan}}"},
                "outputs": ["approved", "reviewer"],
            },
            {
                "id": "node_remediate",
                "type": "skill",
                "name": "Apply Fix",
                "description": "Applies verified patch",
                "position": {"x": 640.0, "y": 80.0},
                "config": {"skill_id": "code_refactor"},
                "inputs": {"plan": "{{node_input.parsed_plan}}"},
                "outputs": ["diff"],
            },
            {
                "id": "node_abort",
                "type": "skill",
                "name": "Audit Abort",
                "description": "Logs rejection event",
                "position": {"x": 640.0, "y": 240.0},
                "inputs": {"reason": "Rejected by operator"},
                "outputs": ["log_id"],
            },
        ],
        "edges": [
            {"id": "e_in_gate", "source": "node_input", "target": "node_gate"},
            {
                "id": "e_gate_rem",
                "source": "node_gate",
                "target": "node_remediate",
                "condition": "approved",
            },
            {
                "id": "e_gate_abort",
                "source": "node_gate",
                "target": "node_abort",
                "condition": "false",
            },
        ],
        "tags": ["canvas", "interactive", "safety"],
    }

    # 1. Parse into WorkflowDefinition
    wf = WorkflowDefinition.model_validate(canvas_payload)
    assert wf.id == "wf_canvas_sample_roundtrip"
    assert len(wf.nodes) == 4
    assert len(wf.edges) == 3
    assert wf.nodes[0].position.x == 80.0
    assert wf.nodes[0].position.y == 140.0
    assert wf.edges[1].condition == "approved"

    # 2. Serialize to YAML and back
    yaml_str = WorkflowParser.to_yaml(wf)
    assert "wf_canvas_sample_roundtrip" in yaml_str
    assert "node_gate" in yaml_str
    assert "approved" in yaml_str

    wf_from_yaml = WorkflowParser.from_yaml(yaml_str)
    assert wf_from_yaml.id == wf.id
    assert len(wf_from_yaml.nodes) == len(wf.nodes)
    assert len(wf_from_yaml.edges) == len(wf.edges)

    # 3. Re-convert to dict
    reconstructed = wf_from_yaml.to_dict()
    assert reconstructed["id"] == canvas_payload["id"]
    assert len(reconstructed["nodes"]) == len(canvas_payload["nodes"])
    assert reconstructed["nodes"][0]["position"]["x"] == 80.0


def test_workflow_builder_complex_dag_validation():
    """Verify validation and topological ordering on complex multi-branch DAG graphs."""
    nodes = [
        WorkflowNode(
            id="n_start",
            type=WorkflowNodeType.AGENT,
            name="Start Agent",
            position=WorkflowPosition(x=50, y=100),
        ),
        WorkflowNode(
            id="n_par1",
            type=WorkflowNodeType.PARALLEL,
            name="Parallel Fan-Out",
            position=WorkflowPosition(x=250, y=100),
        ),
        WorkflowNode(
            id="n_work_a",
            type=WorkflowNodeType.SKILL,
            name="Worker A",
            position=WorkflowPosition(x=450, y=50),
        ),
        WorkflowNode(
            id="n_work_b",
            type=WorkflowNodeType.SKILL,
            name="Worker B",
            position=WorkflowPosition(x=450, y=150),
        ),
        WorkflowNode(
            id="n_merge",
            type=WorkflowNodeType.MERGE,
            name="State Merge",
            position=WorkflowPosition(x=650, y=100),
        ),
        WorkflowNode(
            id="n_end",
            type=WorkflowNodeType.SKILL,
            name="Finalize",
            position=WorkflowPosition(x=850, y=100),
        ),
    ]
    edges = [
        WorkflowEdge(id="e1", source="n_start", target="n_par1"),
        WorkflowEdge(id="e2", source="n_par1", target="n_work_a"),
        WorkflowEdge(id="e3", source="n_par1", target="n_work_b"),
        WorkflowEdge(id="e4", source="n_work_a", target="n_merge"),
        WorkflowEdge(id="e5", source="n_work_b", target="n_merge"),
        WorkflowEdge(id="e6", source="n_merge", target="n_end"),
    ]
    wf = WorkflowDefinition(
        id="wf_complex_fanout_merge",
        name="Complex Fan-Out and Merge Pipeline",
        nodes=nodes,
        edges=edges,
    )

    is_valid, errors = WorkflowParser.validate(wf)
    assert is_valid is True
    assert errors == []

    # Topological sort starts at n_start and ends at n_end
    order = WorkflowParser.get_topological_sort(wf)
    order_ids = [n.id for n in order]
    assert order_ids[0] == "n_start"
    assert order_ids[-1] == "n_end"
    assert order_ids.index("n_merge") > order_ids.index("n_work_a")
    assert order_ids.index("n_merge") > order_ids.index("n_work_b")


def test_workflow_builder_malformed_dag_detection():
    """Verify validation detects self-loops, duplicate node IDs, and missing node references."""
    # 1. Self loop (node -> itself)
    node_self = WorkflowNode(id="loop_node", type=WorkflowNodeType.AGENT, name="Looping Node")
    edge_self = WorkflowEdge(id="e_self", source="loop_node", target="loop_node")
    wf_self = WorkflowDefinition(
        id="wf_self_loop", name="Self Loop WF", nodes=[node_self], edges=[edge_self]
    )

    is_valid_self, errors_self = WorkflowParser.validate(wf_self)
    assert is_valid_self is False
    assert any("Cycle detected" in err or "entry node" in err for err in errors_self)

    # 2. Duplicate node IDs
    dup_node1 = WorkflowNode(id="same_id", type=WorkflowNodeType.AGENT, name="First Instance")
    dup_node2 = WorkflowNode(id="same_id", type=WorkflowNodeType.SKILL, name="Duplicate Instance")
    wf_dup = WorkflowDefinition(
        id="wf_dup", name="Duplicate Node WF", nodes=[dup_node1, dup_node2], edges=[]
    )

    is_valid_dup, errors_dup = WorkflowParser.validate(wf_dup)
    assert is_valid_dup is False
    assert any("Duplicate node ID detected" in err for err in errors_dup)


def test_workflow_builder_end_to_end_api_lifecycle():
    """Verify full end-to-end REST lifecycle for builder canvas workflows."""
    client = TestClient(app)

    builder_wf = {
        "id": "wf_e2e_builder_lifecycle",
        "name": "Lifecycle Pipeline",
        "description": "Full lifecycle validation for interactive canvas",
        "version": "2.0.0",
        "status": "active",
        "nodes": [
            {
                "id": "prep",
                "type": "agent",
                "name": "Data Preparer",
                "position": {"x": 100.0, "y": 100.0},
                "inputs": {"query": "$workflow.input.query"},
                "outputs": ["clean_data"],
            },
            {
                "id": "process",
                "type": "skill",
                "name": "Data Processor",
                "position": {"x": 350.0, "y": 100.0},
                "inputs": {"data": "{{prep.clean_data}}"},
                "outputs": ["processed_result"],
            },
        ],
        "edges": [{"id": "e_prep_proc", "source": "prep", "target": "process"}],
        "tags": ["lifecycle", "e2e"],
    }

    # 1. Validate
    val_res = client.post("/v1/workflows/validate", json={"definition_json": builder_wf})
    assert val_res.status_code == 200
    assert val_res.json()["valid"] is True

    # 2. Create / Save
    save_res = client.post("/v1/workflows", json=builder_wf)
    assert save_res.status_code == 200
    assert save_res.json()["id"] == "wf_e2e_builder_lifecycle"

    # 3. Dry Run Simulation
    dry_res = client.post(
        f"/v1/workflows/{builder_wf['id']}/dry-run",
        json={"inputs": {"query": "Test dry run query"}},
    )
    assert dry_res.status_code == 200
    dry_data = dry_res.json()
    assert dry_data["status"] == "completed"
    assert dry_data["total_cost_usd"] == 0.0
    assert "prep" in dry_data["step_results"]
    assert "process" in dry_data["step_results"]

    # 4. Live Execution
    run_res = client.post(
        f"/v1/workflows/{builder_wf['id']}/run",
        json={"inputs": {"query": "Live production query"}, "dry_run": False},
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "completed"
    assert run_data["total_cost_usd"] > 0.0

    # 5. List and Get Runs
    runs_res = client.get(f"/v1/workflows/{builder_wf['id']}/runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert any(r["run_id"] == run_id for r in runs)

    # 6. Cleanup
    del_res = client.delete(f"/v1/workflows/{builder_wf['id']}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True


def test_workflow_builder_gate_interactive_flow():
    """Verify builder workflow containing an approval gate correctly pauses and is queryable."""
    client = TestClient(app)

    gated_wf = {
        "id": "wf_builder_gated_demo",
        "name": "Builder Gate Demo",
        "description": "Demonstrates interactive gate controls",
        "nodes": [
            {
                "id": "start_agent",
                "type": "agent",
                "name": "Generate Draft",
                "position": {"x": 100.0, "y": 100.0},
                "inputs": {"prompt": "$workflow.input.prompt"},
                "outputs": ["draft"],
            },
            {
                "id": "gate_review",
                "type": "gate",
                "name": "Sign Off",
                "position": {"x": 350.0, "y": 100.0},
                "config": {"timeout_seconds": 900},
                "inputs": {"draft": "{{start_agent.draft}}"},
                "outputs": ["approved"],
            },
            {
                "id": "publish",
                "type": "skill",
                "name": "Publish Post",
                "position": {"x": 600.0, "y": 100.0},
                "inputs": {"content": "{{start_agent.draft}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start_agent", "target": "gate_review"},
            {"id": "e2", "source": "gate_review", "target": "publish", "condition": "approved"},
        ],
    }

    # Save
    client.post("/v1/workflows", json=gated_wf)

    # Run -> pauses at gate
    run_res = client.post(
        f"/v1/workflows/{gated_wf['id']}/run",
        json={"inputs": {"prompt": "New article draft"}, "dry_run": False},
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    assert run_data["status"] == "waiting_approval"
    assert run_data["current_node_id"] == "gate_review"

    # Pending gates listing
    gates_res = client.get("/v1/workflows/gates/pending")
    assert gates_res.status_code == 200
    gates = gates_res.json()
    assert any(g["run_id"] == run_data["run_id"] for g in gates)

    # Approve
    approve_res = client.post(
        f"/v1/workflows/{gated_wf['id']}/runs/{run_data['run_id']}/approve",
        json={"reviewer": "chief_editor"},
    )
    assert approve_res.status_code == 200
    resumed = approve_res.json()
    assert resumed["status"] == "completed"
    assert "publish" in resumed["step_results"]

    # Cleanup
    client.delete(f"/v1/workflows/{gated_wf['id']}")
