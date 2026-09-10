import numpy  # noqa: F401
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import dspy

from core.pipelines import (
    PipelineMetadata,
    PipelineRegistry,
    get_pipeline_registry,
    register_pipeline,
)
from services.python.server.api import app

client = TestClient(app)


def test_pipeline_metadata_model():
    """Verify PipelineMetadata dataclass serialization."""
    meta = PipelineMetadata(
        name="custom_pipeline",
        description="A test pipeline",
        inputs=["text"],
        outputs=["result"],
        tools=["search"],
        guardrails=["safety"],
        category="testing",
        version="1.2.0",
        author="Unit Tester",
    )
    d = meta.to_dict()
    assert d["name"] == "custom_pipeline"
    assert d["inputs"] == ["text"]
    assert d["outputs"] == ["result"]
    assert d["tools"] == ["search"]
    assert d["guardrails"] == ["safety"]
    assert d["category"] == "testing"
    assert d["version"] == "1.2.0"
    assert d["author"] == "Unit Tester"


def test_pipeline_registry_and_decorator():
    """Verify registration via decorator and registry operations."""
    test_reg = PipelineRegistry()

    @register_pipeline(
        name="demo_evaluator",
        description="Evaluates demo inputs",
        inputs=["prompt"],
        outputs=["score"],
        category="evaluation",
        registry=test_reg,
    )
    class DemoPipeline(dspy.Module):
        def forward(self, prompt: str):
            return {"score": 95}

    # Verify retrieval
    cls = test_reg.get("demo_evaluator")
    assert cls is DemoPipeline

    meta = test_reg.get_metadata("demo_evaluator")
    assert meta is not None
    assert meta.name == "demo_evaluator"
    assert meta.category == "evaluation"

    # Verify instantiation and run
    instance = test_reg.instantiate("demo_evaluator")
    assert isinstance(instance, DemoPipeline)

    out = test_reg.run("demo_evaluator", prompt="Hello")
    assert out == {"score": 95}

    # Verify unregister
    assert test_reg.unregister("demo_evaluator") is True
    assert test_reg.get("demo_evaluator") is None


def test_six_standard_pipelines_registered():
    """Verify that all 6 standard pipelines are pre-registered with correct metadata."""
    registry = get_pipeline_registry()
    pipelines = {p.name: p for p in registry.list_pipelines()}

    expected_pipelines = [
        "security_audit",
        "code_lint",
        "code_fix",
        "email_draft",
        "finance_extract",
        "chapter_write",
    ]

    for name in expected_pipelines:
        assert name in pipelines, f"Expected standard pipeline '{name}' to be registered"

    # Verify security_audit metadata
    sec = pipelines["security_audit"]
    assert "code" in sec.inputs
    assert "vulnerabilities" in sec.outputs
    assert sec.category == "code"
    assert "code_injection_check" in sec.guardrails

    # Verify code_lint metadata
    lint = pipelines["code_lint"]
    assert "code" in lint.inputs
    assert "lint_issues" in lint.outputs
    assert lint.category == "code"

    # Verify code_fix metadata
    fix = pipelines["code_fix"]
    assert "code" in fix.inputs
    assert "diff_patch" in fix.outputs
    assert "patch_sanitizer" in fix.guardrails

    # Verify email_draft metadata
    email = pipelines["email_draft"]
    assert "brief" in email.inputs
    assert "subject" in email.outputs
    assert email.category == "business"

    # Verify finance_extract metadata
    fin = pipelines["finance_extract"]
    assert "document_text" in fin.inputs
    assert "total_amount" in fin.outputs
    assert fin.category == "finance"

    # Verify chapter_write metadata
    chap = pipelines["chapter_write"]
    assert "outline" in chap.inputs
    assert "prose" in chap.outputs
    assert chap.category == "creative"


def test_api_list_pipelines_endpoint():
    """Verify GET /v1/pipelines returns registered pipelines."""
    resp = client.get("/v1/pipelines")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    names = [p["name"] for p in data]
    for expected in [
        "security_audit",
        "code_lint",
        "code_fix",
        "email_draft",
        "finance_extract",
        "chapter_write",
    ]:
        assert expected in names


def test_api_get_pipeline_details_endpoint():
    """Verify GET /v1/pipelines/{name} returns metadata or 404."""
    resp = client.get("/v1/pipelines/security_audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "security_audit"
    assert "vulnerabilities" in data["outputs"]

    # 404 for unknown pipeline
    not_found = client.get("/v1/pipelines/unknown_pipeline_xyz")
    assert not_found.status_code == 404


def test_api_run_pipeline_endpoint():
    """Verify POST /v1/pipelines/{name}/run executes registered pipeline."""
    registry = get_pipeline_registry()

    # Mock the pipeline instance forward method
    mock_instance = MagicMock()
    mock_instance.return_value = {
        "vulnerabilities": "None detected",
        "risk_level": "LOW",
        "fix_recommendation": "Code is secure",
    }

    original_get = registry.get
    try:
        mock_cls = MagicMock(return_value=mock_instance)
        registry._registry["security_audit"] = (
            mock_cls,
            registry.get_metadata("security_audit"),
        )

        resp = client.post(
            "/v1/pipelines/security_audit/run",
            json={"inputs": {"code": "print('hello')", "language": "python"}},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["pipeline"] == "security_audit"
        assert result["outputs"]["risk_level"] == "LOW"
    finally:
        # Restore
        registry._registry["security_audit"] = (
            original_get("security_audit"),
            registry.get_metadata("security_audit"),
        )

    # 404 for unknown pipeline
    not_found = client.post("/v1/pipelines/unknown_pipeline_xyz/run", json={"inputs": {}})
    assert not_found.status_code == 404
