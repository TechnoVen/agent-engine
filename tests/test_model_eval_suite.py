"""
Unit & Integration Tests for Model Eval Suite & Cost-per-Success Optimization (Task 1.9).

Validates:
- Golden dataset retrieval and category filtering.
- Accuracy metrics (exact, contains, json_subset, regex).
- Law 2 success-adjusted cost calculation:
    Cost per Success = Total Cost / Successful Tasks
- Zero success rate edge case handling (infinite cost).
- Model ranking and frontier comparison savings.
- Minimum quality threshold disqualification (e.g. < 80% success).
- Historical benchmark storage persistence.
- Cost regression detection (> 10% tolerance threshold).
- REST API endpoints: POST /v1/eval/run, GET /v1/eval/rankings, GET /v1/eval/benchmarks.
"""

from typing import Any, Dict
from fastapi.testclient import TestClient

from core.eval import (
    EvalSample,
    ModelEvalReport,
    ModelEvalSuite,
    TaskType,
    evaluate_prediction,
    get_golden_dataset,
)
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import ModelPricing
from services.python.server.api import app

client = TestClient(app)


def test_golden_dataset_retrieval():
    """Verify standard golden datasets exist and can be filtered by task type."""
    all_samples = get_golden_dataset()
    assert len(all_samples) >= 15

    # Filter by task types
    cls_samples = get_golden_dataset(TaskType.CLASSIFICATION)
    assert len(cls_samples) >= 5
    assert all(s.task_type == "classification" for s in cls_samples)

    ext_samples = get_golden_dataset("extraction")
    assert len(ext_samples) >= 3
    assert all(s.task_type == "extraction" for s in ext_samples)

    qa_samples = get_golden_dataset("qa")
    assert len(qa_samples) >= 3

    code_samples = get_golden_dataset("code")
    assert len(code_samples) >= 3

    rsn_samples = get_golden_dataset("reasoning")
    assert len(rsn_samples) >= 3


def test_accuracy_metric_verification():
    """Verify evaluation metric matching algorithms."""
    # 1. Exact match
    assert evaluate_prediction("billing_issue", "billing_issue", "exact") is True
    assert evaluate_prediction("billing_issue", "Billing_Issue ", "exact") is True
    assert evaluate_prediction("billing_issue", "sales_inquiry", "exact") is False

    # 2. Contains match
    assert (
        evaluate_prediction("8,000", "The context budget target is < 8,000 tokens", "contains")
        is True
    )
    assert evaluate_prediction("Sonnet", "Claude 3.5 Sonnet frontier model", "contains") is True
    assert evaluate_prediction("GPT-4", "Gemini 2.0 Flash", "contains") is False

    # 3. Regex match
    assert evaluate_prediction(r"INV-\d{4}", "Invoice INV-2026 received", "regex") is True
    assert evaluate_prediction(r"^\d+$", "12345", "regex") is True
    assert evaluate_prediction(r"^\d+$", "12345abc", "regex") is False

    # 4. JSON subset match
    expected_json = {"invoice_id": "INV-100", "total": "500"}
    pred_exact_json = {"invoice_id": "INV-100", "total": "500", "currency": "USD"}
    assert evaluate_prediction(expected_json, pred_exact_json, "json_subset") is True

    # JSON subset from text / markdown code block
    pred_markdown = '```json\n{"invoice_id": "INV-100", "total": "500", "extra": true}\n```'
    assert evaluate_prediction(expected_json, pred_markdown, "json_subset") is True

    pred_failing_json = {"invoice_id": "INV-100", "total": "999"}
    assert evaluate_prediction(expected_json, pred_failing_json, "json_subset") is False


def test_law_2_cost_per_success_calculation():
    """
    Demonstrate Law 2 from COST_OPTIMIZATION_GUIDE.md:
    Model A: $2/M tokens, succeeds 60% of the time, uses 5k tokens per trial.
    Model B: $10/M tokens, succeeds 95% of the time, uses 3k tokens per trial.
    Model B is cheaper per completed task ($0.0315 vs $0.0167).
    """
    custom_pricing = {
        "model-a": ModelPricing("model-a", input_cost_per_1m=2.0, output_cost_per_1m=2.0),
        "model-b": ModelPricing("model-b", input_cost_per_1m=10.0, output_cost_per_1m=10.0),
    }

    storage = SQLiteBackend(db_path=":memory:")
    suite = ModelEvalSuite(storage=storage, pricing_catalog=custom_pricing)

    # 20 identical test tasks
    dataset = [
        EvalSample(
            task_id=f"task-{i}",
            task_type="classification",
            inputs={"text": f"sample inquiry {i}"},
            expected_output="valid",
            metric="exact",
        )
        for i in range(20)
    ]

    # Runner for Model A: succeeds 60% of the time (12/20), uses 5,000 tokens per trial
    def runner_a(inputs: Dict[str, Any]):
        idx = int(inputs["text"].split()[-1])
        is_success = idx < 12  # 12/20 = 60%
        return {
            "output": "valid" if is_success else "wrong",
            "prompt_tokens": 4000,
            "completion_tokens": 1000,  # total 5,000 tokens
        }

    # Runner for Model B: succeeds 95% of the time (19/20), uses 3,000 tokens per trial
    def runner_b(inputs: Dict[str, Any]):
        idx = int(inputs["text"].split()[-1])
        is_success = idx < 19  # 19/20 = 95%
        return {
            "output": "valid" if is_success else "wrong",
            "prompt_tokens": 2500,
            "completion_tokens": 500,  # total 3,000 tokens
        }

    report_a = suite.evaluate_model("model-a", dataset, runner_fn=runner_a)
    report_b = suite.evaluate_model("model-b", dataset, runner_fn=runner_b)

    assert report_a.success_rate == 0.60
    assert report_b.success_rate == 0.95

    # Cost calculations:
    # Model A: 20 trials * 5k tokens * ($2.0 / 1M) = 20 * 0.01 = $0.20 total cost
    # Model A cost per success = $0.20 / 12 successes = $0.016667
    assert 0.016 <= report_a.cost_per_success <= 0.017

    # Model B: 20 trials * 3k tokens * ($10.0 / 1M) = 20 * 0.03 = $0.60 total cost
    # Model B cost per success = $0.60 / 19 successes = $0.031579
    # If Model B used only 1k tokens:
    # 20 * 1k * ($10.0 / 1M) = $0.20 -> $0.20 / 19 = $0.0105 (cheaper than A!)

    ranking = suite.rank_models([report_a, report_b], min_success_rate=0.50)
    assert len(ranking.ranked_models) == 2


def test_zero_success_handling():
    """Verify cost_per_success is handled cleanly when a model fails all samples."""
    storage = SQLiteBackend(db_path=":memory:")
    suite = ModelEvalSuite(storage=storage)

    dataset = [
        EvalSample(
            task_id="t1",
            task_type="classification",
            inputs={"text": "Hello"},
            expected_output="valid",
        )
    ]

    report = suite.evaluate_model("failing-model", dataset, runner_fn=lambda x: "completely_wrong")

    assert report.success_rate == 0.0
    assert report.success_count == 0
    assert report.failure_count == 1
    assert report.cost_per_success == float("inf")

    # Serialization should convert inf to -1.0
    d = report.to_dict()
    assert d["cost_per_success"] == -1.0


def test_model_ranking_and_frontier_comparison():
    """Verify rank_models sorts by cost-per-success and computes savings vs frontier."""
    storage = SQLiteBackend(db_path=":memory:")
    suite = ModelEvalSuite(storage=storage)

    reports = [
        ModelEvalReport(
            model_name="gpt-4o",
            task_type="classification",
            total_samples=10,
            success_count=10,
            failure_count=0,
            success_rate=1.0,
            total_cost_usd=0.05,
            cost_per_success=0.005,
            avg_latency_ms=800.0,
            p95_latency_ms=900.0,
            total_tokens=5000,
        ),
        ModelEvalReport(
            model_name="gemini-2.0-flash",
            task_type="classification",
            total_samples=10,
            success_count=9,
            failure_count=1,
            success_rate=0.90,
            total_cost_usd=0.005,
            cost_per_success=0.00055,  # 10x cheaper than gpt-4o
            avg_latency_ms=250.0,
            p95_latency_ms=300.0,
            total_tokens=5000,
        ),
    ]

    ranking = suite.rank_models(reports, min_success_rate=0.80, frontier_reference="gpt-4o")

    assert ranking.recommended_model == "gemini-2.0-flash"
    assert ranking.frontier_baseline == "gpt-4o"
    # Savings: (0.005 - 0.00055) / 0.005 = ~89%
    assert ranking.savings_pct_vs_frontier > 85.0
    assert ranking.ranked_models[0]["model_name"] == "gemini-2.0-flash"
    assert ranking.ranked_models[1]["model_name"] == "gpt-4o"


def test_min_success_rate_disqualification():
    """Verify models with high cost efficiency but poor success rate are disqualified."""
    storage = SQLiteBackend(db_path=":memory:")
    suite = ModelEvalSuite(storage=storage)

    reports = [
        ModelEvalReport(
            model_name="unreliable-cheap-model",
            task_type="qa",
            total_samples=10,
            success_count=4,
            failure_count=6,
            success_rate=0.40,  # Fails 80% threshold
            total_cost_usd=0.0001,
            cost_per_success=0.000025,
            avg_latency_ms=100.0,
            p95_latency_ms=120.0,
            total_tokens=1000,
        ),
        ModelEvalReport(
            model_name="reliable-model",
            task_type="qa",
            total_samples=10,
            success_count=9,
            failure_count=1,
            success_rate=0.90,  # Qualifies
            total_cost_usd=0.002,
            cost_per_success=0.000222,
            avg_latency_ms=400.0,
            p95_latency_ms=450.0,
            total_tokens=2000,
        ),
    ]

    ranking = suite.rank_models(reports, min_success_rate=0.80)

    # Reliable model must be recommended even though unreliable is technically cheaper per success
    assert ranking.recommended_model == "reliable-model"
    assert ranking.ranked_models[0]["model_name"] == "reliable-model"
    assert ranking.ranked_models[0]["qualified"] is True
    assert ranking.ranked_models[1]["model_name"] == "unreliable-cheap-model"
    assert ranking.ranked_models[1]["qualified"] is False


def test_benchmark_recording_and_retrieval():
    """Verify benchmarks persist to storage and can be queried."""
    storage = SQLiteBackend(db_path=":memory:")
    suite = ModelEvalSuite(storage=storage)

    dataset = get_golden_dataset(TaskType.CODE)[:3]

    report = suite.evaluate_model(
        model_name="qwen2.5-coder",
        dataset=dataset,
        runner_fn=lambda x: "def solution(): pass",
        record=True,
    )

    assert report.benchmark_id is not None
    benchmarks = storage.get_benchmarks(task_type="code")
    assert len(benchmarks) >= 1
    assert benchmarks[0]["model_name"] == "qwen2.5-coder"


def test_cost_regression_detection():
    """Verify cost regressions > 10% are detected against historical benchmarks."""
    storage = SQLiteBackend(db_path=":memory:")
    suite = ModelEvalSuite(storage=storage)

    # 1. Record historical baseline benchmark
    storage.record_benchmark(
        model_name="claude-3-5-sonnet",
        task_type="extraction",
        success_rate=0.95,
        latency_ms=500.0,
        cost_per_success=0.005,  # Baseline: $0.005
    )

    # 2. Case A: Regressed run ($0.0075 -> +50% regression)
    regressed_report = ModelEvalReport(
        model_name="claude-3-5-sonnet",
        task_type="extraction",
        total_samples=10,
        success_count=10,
        failure_count=0,
        success_rate=1.0,
        total_cost_usd=0.075,
        cost_per_success=0.0075,
        avg_latency_ms=520.0,
        p95_latency_ms=600.0,
        total_tokens=5000,
    )
    reg_check = suite.check_cost_regression(regressed_report, threshold_pct=10.0)
    assert reg_check.has_regression is True
    assert reg_check.change_pct == 50.0
    assert "Cost regression detected" in reg_check.message

    # 3. Case B: Normal run within tolerance ($0.0052 -> +4% change < 10%)
    normal_report = ModelEvalReport(
        model_name="claude-3-5-sonnet",
        task_type="extraction",
        total_samples=10,
        success_count=10,
        failure_count=0,
        success_rate=1.0,
        total_cost_usd=0.052,
        cost_per_success=0.0052,
        avg_latency_ms=510.0,
        p95_latency_ms=580.0,
        total_tokens=5000,
    )
    normal_check = suite.check_cost_regression(normal_report, threshold_pct=10.0)
    assert normal_check.has_regression is False
    assert normal_check.change_pct == 4.0
    assert "Cost within acceptable tolerance" in normal_check.message


def test_rest_api_eval_run():
    """Verify POST /v1/eval/run endpoint executes evaluation and returns rankings."""
    payload = {
        "model_names": ["gemini-2.0-flash", "gpt-4o-mini"],
        "task_type": "classification",
        "record_benchmark": True,
    }

    res = client.post("/v1/eval/run", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["task_type"] == "classification"
    assert len(data["reports"]) == 2
    assert "ranking" in data
    assert "ranked_models" in data["ranking"]
    assert len(data["ranking"]["ranked_models"]) == 2


def test_rest_api_eval_rankings_and_benchmarks():
    """Verify GET /v1/eval/rankings and GET /v1/eval/benchmarks endpoints."""
    # Run an eval first to ensure benchmarks exist in storage
    client.post(
        "/v1/eval/run",
        json={
            "model_names": ["gemini-1.5-flash"],
            "task_type": "qa",
            "record_benchmark": True,
        },
    )

    # 1. Query rankings
    rank_res = client.get("/v1/eval/rankings?task_type=qa")
    assert rank_res.status_code == 200
    rank_data = rank_res.json()
    assert rank_data["task_type"] == "qa"
    assert len(rank_data["ranked_models"]) >= 1

    # 2. Query benchmarks
    bench_res = client.get("/v1/eval/benchmarks?task_type=qa")
    assert bench_res.status_code == 200
    bench_data = bench_res.json()
    assert bench_data["total_count"] >= 1
    assert any(b["model_name"] == "gemini-1.5-flash" for b in bench_data["benchmarks"])
