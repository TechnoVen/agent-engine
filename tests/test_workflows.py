"""tests/test_workflows.py

Unit & integration tests for Workflow Engine (Phase 7 - Milestone M5).
Covers:
- Task 7.1: Workflow Schema, Lossless Parser & DAG Runtime Engine
"""

from core.workflows import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowParser,
    WorkflowPosition,
    WorkflowRunStatus,
    WorkflowStatus,
)


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
