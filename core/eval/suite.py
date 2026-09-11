"""
Agent Engine - Model Evaluation Suite & Cost-per-Success Optimization (Task 1.9).

Implements Law 2 from docs/COST_OPTIMIZATION_GUIDE.md:
"Never compare models by price-per-million-tokens. Always compare by cost to
successfully complete a real task from your own eval suite."

Key Capabilities:
- Golden eval datasets covering classification, extraction, Q&A, code, and reasoning.
- Multi-metric verification (exact, contains, json_subset, regex, custom).
- Accurate cost and latency tracking per trial.
- Success-adjusted cost calculation:
    Cost per Success = Total Cost / Successful Tasks
- Comparative model ranking and optimal model recommendation.
- Historical benchmark persistence in SQLite/PostgreSQL storage.
- Cost regression detection (> 10% threshold).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Union

from core.context.builder import estimate_object_tokens
from core.storage import get_storage_backend
from core.storage.base import StorageBackend
from core.telemetry.cost import DEFAULT_PRICING, ModelPricing

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Standard task types evaluated in Agent Engine."""

    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    QA = "qa"
    CODE = "code"
    REASONING = "reasoning"


@dataclass
class EvalSample:
    """A single evaluation test case from a golden eval set."""

    task_id: str
    task_type: str
    inputs: Dict[str, Any]
    expected_output: Any
    metric: str = "exact"  # "exact" | "contains" | "json_subset" | "regex"
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvalResult:
    """The result of evaluating a single sample against a model."""

    task_id: str
    task_type: str
    model_name: str
    success: bool
    predicted_output: Any
    expected_output: Any
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelEvalReport:
    """Aggregated evaluation report for a model on a dataset or task type."""

    model_name: str
    task_type: str
    total_samples: int
    success_count: int
    failure_count: int
    success_rate: float
    total_cost_usd: float
    cost_per_success: float
    avg_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    sample_results: List[EvalResult] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    benchmark_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "task_type": self.task_type,
            "total_samples": self.total_samples,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "total_cost_usd": self.total_cost_usd,
            "cost_per_success": self.cost_per_success
            if self.cost_per_success != float("inf")
            else -1.0,
            "avg_latency_ms": self.avg_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "total_tokens": self.total_tokens,
            "benchmark_id": self.benchmark_id,
            "timestamp": self.timestamp,
            "sample_results": [r.to_dict() for r in self.sample_results],
        }


@dataclass
class ModelRanking:
    """Comparative success-adjusted cost rankings across evaluated models."""

    task_type: str
    ranked_models: List[Dict[str, Any]]
    recommended_model: Optional[str] = None
    frontier_baseline: Optional[str] = None
    savings_pct_vs_frontier: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RegressionCheckResult:
    """Cost regression evaluation result comparing against historical baselines."""

    model_name: str
    task_type: str
    current_cost_per_success: float
    baseline_cost_per_success: float
    change_pct: float
    has_regression: bool
    threshold_pct: float
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_prediction(expected: Any, predicted: Any, metric: str = "exact") -> bool:
    """
    Check if a model prediction satisfies the expected ground truth.
    Supports exact, contains, json_subset, and regex metrics.
    """
    if predicted is None:
        return False

    metric_lower = metric.lower().strip()

    if metric_lower == "exact":
        return str(expected).strip().lower() == str(predicted).strip().lower()

    if metric_lower == "contains":
        return str(expected).strip().lower() in str(predicted).strip().lower()

    if metric_lower == "regex":
        try:
            pattern = str(expected).strip()
            return bool(re.search(pattern, str(predicted).strip(), re.IGNORECASE))
        except Exception:
            return False

    if metric_lower == "json_subset":
        try:
            exp_dict = expected if isinstance(expected, dict) else json.loads(str(expected))
            if isinstance(predicted, dict):
                pred_dict = predicted
            else:
                # Try parsing JSON from predicted text (including code blocks)
                text = str(predicted).strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                pred_dict = json.loads(text)

            for k, v in exp_dict.items():
                if k not in pred_dict:
                    return False
                if str(pred_dict[k]).strip().lower() != str(v).strip().lower():
                    return False
            return True
        except Exception:
            return False

    # Default fallback to exact comparison
    return str(expected).strip().lower() == str(predicted).strip().lower()


def get_golden_dataset(task_type: Optional[Union[str, TaskType]] = None) -> List[EvalSample]:
    """
    Retrieve standard golden evaluation sets for Agent Engine tasks.
    Curated samples for classification, extraction, Q&A, code, and reasoning.
    """
    golden_samples: List[EvalSample] = [
        # --- 1. CLASSIFICATION ---
        EvalSample(
            task_id="cls-01",
            task_type="classification",
            inputs={"text": "I was billed twice for my subscription this month. Refund please!"},
            expected_output="billing_issue",
            metric="exact",
        ),
        EvalSample(
            task_id="cls-02",
            task_type="classification",
            inputs={"text": "My API key is returning 401 Unauthorized errors in production."},
            expected_output="technical_support",
            metric="exact",
        ),
        EvalSample(
            task_id="cls-03",
            task_type="classification",
            inputs={"text": "Can you add support for WebSocket streaming in the next release?"},
            expected_output="feature_request",
            metric="exact",
        ),
        EvalSample(
            task_id="cls-04",
            task_type="classification",
            inputs={"text": "How much does the enterprise multi-tenant plan cost per seat?"},
            expected_output="sales_inquiry",
            metric="exact",
        ),
        EvalSample(
            task_id="cls-05",
            task_type="classification",
            inputs={"text": "Your software crashed my entire staging Kubernetes cluster."},
            expected_output="incident_report",
            metric="exact",
        ),
        # --- 2. EXTRACTION ---
        EvalSample(
            task_id="ext-01",
            task_type="extraction",
            inputs={
                "document": "Invoice INV-2026-09A from Acme Corp for $4,500.00 due on 2026-10-15."
            },
            expected_output={
                "invoice_id": "INV-2026-09A",
                "vendor": "Acme Corp",
                "total_usd": "4500.00",
            },
            metric="json_subset",
        ),
        EvalSample(
            task_id="ext-02",
            task_type="extraction",
            inputs={
                "document": "Customer Sarah Connor (ID: CUST-8831) registered email sarah@skynet.org."
            },
            expected_output={
                "customer_id": "CUST-8831",
                "name": "Sarah Connor",
                "email": "sarah@skynet.org",
            },
            metric="json_subset",
        ),
        EvalSample(
            task_id="ext-03",
            task_type="extraction",
            inputs={
                "document": "Server alert on host us-east-4: CPU 98.4%, RAM 31.2GB/32GB at 14:32 UTC."
            },
            expected_output={"host": "us-east-4", "metric": "CPU", "status": "critical"},
            metric="json_subset",
        ),
        # --- 3. QA ---
        EvalSample(
            task_id="qa-01",
            task_type="qa",
            inputs={"question": "What is the 90/9/1 cost optimization rule in Agent Engine?"},
            expected_output="90% deterministic or small models, 9% mid-tier, 1% frontier",
            metric="contains",
        ),
        EvalSample(
            task_id="qa-02",
            task_type="qa",
            inputs={"question": "What is the recommended average context target per agent step?"},
            expected_output="8,000",
            metric="contains",
        ),
        EvalSample(
            task_id="qa-03",
            task_type="qa",
            inputs={
                "question": "What cosine similarity threshold does the semantic cache require?"
            },
            expected_output="0.95",
            metric="contains",
        ),
        # --- 4. CODE ---
        EvalSample(
            task_id="code-01",
            task_type="code",
            inputs={"instruction": "Write a Python function is_palindrome(s) returning a bool."},
            expected_output="def is_palindrome",
            metric="contains",
        ),
        EvalSample(
            task_id="code-02",
            task_type="code",
            inputs={
                "instruction": "Fix naked return in Python snippet: 'return a + b' inside script."
            },
            expected_output="def ",
            metric="contains",
        ),
        EvalSample(
            task_id="code-03",
            task_type="code",
            inputs={"instruction": "Write SQL to find duplicate user emails in users table."},
            expected_output="GROUP BY email HAVING COUNT(*) > 1",
            metric="contains",
        ),
        # --- 5. REASONING ---
        EvalSample(
            task_id="rsn-01",
            task_type="reasoning",
            inputs={
                "premise": "All servers in cluster A have SSDs. Host node-12 is in cluster A.",
                "question": "Does node-12 have an SSD?",
            },
            expected_output="yes",
            metric="contains",
        ),
        EvalSample(
            task_id="rsn-02",
            task_type="reasoning",
            inputs={
                "problem": "A car travels at 60 mph for 2.5 hours. What total distance did it cover in miles?"
            },
            expected_output="150",
            metric="contains",
        ),
        EvalSample(
            task_id="rsn-03",
            task_type="reasoning",
            inputs={
                "problem": "If model A has 60% success and costs $0.006/trial, what is cost per success in USD?"
            },
            expected_output="0.01",
            metric="contains",
        ),
    ]

    if task_type is None:
        return golden_samples

    tt_str = task_type.value if isinstance(task_type, TaskType) else str(task_type)
    return [s for s in golden_samples if s.task_type == tt_str]


class ModelEvalSuite:
    """
    Automated model evaluation engine computing success-adjusted costs,
    maintaining historical benchmarks, and ranking models for execution tiers.
    """

    def __init__(
        self,
        storage: Optional[StorageBackend] = None,
        pricing_catalog: Optional[Dict[str, ModelPricing]] = None,
    ):
        self.storage = storage or get_storage_backend()
        self.pricing_catalog = pricing_catalog or DEFAULT_PRICING

    def get_pricing(self, model_name: str) -> ModelPricing:
        """Lookup pricing for a model with sensible fallbacks."""
        if model_name in self.pricing_catalog:
            return self.pricing_catalog[model_name]
        # Check standard prefix matching (e.g. gpt-4o -> gpt-4o)
        for name, pricing in self.pricing_catalog.items():
            if model_name.startswith(name) or name in model_name:
                return pricing
        # Default conservative pricing ($1.00 / $3.00 per 1M)
        return ModelPricing(model_name=model_name, input_cost_per_1m=1.0, output_cost_per_1m=3.0)

    def evaluate_model(
        self,
        model_name: str,
        dataset: List[EvalSample],
        runner_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        record: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ModelEvalReport:
        """
        Evaluate a single model across a dataset of test cases.
        Calculates success rate, latency, token spend, and cost-per-success.
        Persists benchmark to storage if record=True.
        """
        if not dataset:
            raise ValueError("Evaluation dataset cannot be empty.")

        task_type = dataset[0].task_type
        pricing = self.get_pricing(model_name)
        results: List[EvalResult] = []
        latencies: List[float] = []
        total_cost = 0.0
        total_tokens = 0
        success_count = 0

        for sample in dataset:
            start_t = time.perf_counter()
            pred_output = None
            error_str = None
            prompt_toks = estimate_object_tokens(sample.inputs)
            completion_toks = 0

            try:
                if runner_fn is not None:
                    raw_res = runner_fn(sample.inputs)
                    if isinstance(raw_res, dict) and "output" in raw_res:
                        pred_output = raw_res["output"]
                        prompt_toks = raw_res.get("prompt_tokens", prompt_toks)
                        completion_toks = raw_res.get(
                            "completion_tokens", estimate_object_tokens(pred_output)
                        )
                    else:
                        pred_output = raw_res
                        completion_toks = estimate_object_tokens(pred_output)
                else:
                    # Simulation default: exact match to expected output
                    pred_output = sample.expected_output
                    completion_toks = estimate_object_tokens(pred_output)

                is_success = evaluate_prediction(sample.expected_output, pred_output, sample.metric)

            except Exception as e:
                logger.error(f"Error during eval sample {sample.task_id} on {model_name}: {e}")
                is_success = False
                error_str = str(e)
                completion_toks = 0

            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            latencies.append(elapsed_ms)

            trial_cost = pricing.calculate_cost(prompt_toks, completion_toks)
            total_cost += trial_cost
            total_tokens += prompt_toks + completion_toks

            if is_success:
                success_count += 1

            result = EvalResult(
                task_id=sample.task_id,
                task_type=sample.task_type,
                model_name=model_name,
                success=is_success,
                predicted_output=pred_output,
                expected_output=sample.expected_output,
                latency_ms=round(elapsed_ms, 2),
                prompt_tokens=prompt_toks,
                completion_tokens=completion_toks,
                cost_usd=round(trial_cost, 6),
                error=error_str,
            )
            results.append(result)

        total_samples = len(dataset)
        failure_count = total_samples - success_count
        success_rate = round(success_count / total_samples, 4)

        # Law 2: Success-adjusted cost
        # Cost per Success = Total Cost / Successful Tasks
        if success_count > 0:
            cost_per_success = round(total_cost / success_count, 6)
        else:
            cost_per_success = float("inf")

        avg_latency = round(sum(latencies) / len(latencies), 2)
        sorted_latencies = sorted(latencies)
        p95_idx = int(0.95 * len(sorted_latencies))
        p95_latency = round(sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)], 2)

        benchmark_id = None
        if record and self.storage is not None:
            try:
                meta = metadata.copy() if metadata else {}
                meta.update(
                    {
                        "total_samples": total_samples,
                        "success_count": success_count,
                        "total_tokens": total_tokens,
                        "total_cost_usd": round(total_cost, 6),
                    }
                )
                benchmark_id = self.storage.record_benchmark(
                    model_name=model_name,
                    task_type=task_type,
                    success_rate=success_rate,
                    latency_ms=avg_latency,
                    cost_per_success=cost_per_success
                    if cost_per_success != float("inf")
                    else 999.0,
                    metadata=meta,
                )
            except Exception as e:
                logger.warning(f"Failed recording benchmark to storage: {e}")

        report = ModelEvalReport(
            model_name=model_name,
            task_type=task_type,
            total_samples=total_samples,
            success_count=success_count,
            failure_count=failure_count,
            success_rate=success_rate,
            total_cost_usd=round(total_cost, 6),
            cost_per_success=cost_per_success,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            total_tokens=total_tokens,
            sample_results=results,
            benchmark_id=benchmark_id,
        )
        return report

    def evaluate_models(
        self,
        model_names: List[str],
        dataset_or_task_type: Union[str, TaskType, List[EvalSample]],
        runner_fn_factory: Optional[Callable[[str], Callable]] = None,
        record: bool = True,
    ) -> List[ModelEvalReport]:
        """
        Evaluate multiple models on the same task type or dataset.
        Returns list of evaluation reports.
        """
        if isinstance(dataset_or_task_type, (str, TaskType)):
            dataset = get_golden_dataset(dataset_or_task_type)
        else:
            dataset = dataset_or_task_type

        reports: List[ModelEvalReport] = []
        for model in model_names:
            runner_fn = runner_fn_factory(model) if runner_fn_factory else None
            report = self.evaluate_model(
                model_name=model,
                dataset=dataset,
                runner_fn=runner_fn,
                record=record,
            )
            reports.append(report)

        return reports

    def rank_models(
        self,
        reports: List[ModelEvalReport],
        min_success_rate: float = 0.80,
        frontier_reference: str = "gpt-4o",
    ) -> ModelRanking:
        """
        Rank models by success-adjusted cost (cost_per_success ascending).
        Filters out models failing to meet min_success_rate.
        Calculates savings percentage vs frontier baseline.
        """
        if not reports:
            raise ValueError("No reports provided for ranking.")

        task_type = reports[0].task_type

        # Sort models: models meeting quality bar first sorted by cost_per_success,
        # then disqualified models
        def sort_key(r: ModelEvalReport):
            qualified = r.success_rate >= min_success_rate
            cost = r.cost_per_success if r.cost_per_success != float("inf") else 999999.0
            return (not qualified, cost, -r.success_rate, r.avg_latency_ms)

        sorted_reports = sorted(reports, key=sort_key)

        ranked_list: List[Dict[str, Any]] = []
        for rank, r in enumerate(sorted_reports, start=1):
            qualified = r.success_rate >= min_success_rate
            ranked_list.append(
                {
                    "rank": rank,
                    "model_name": r.model_name,
                    "success_rate": r.success_rate,
                    "cost_per_success": r.cost_per_success
                    if r.cost_per_success != float("inf")
                    else -1.0,
                    "total_cost_usd": r.total_cost_usd,
                    "avg_latency_ms": r.avg_latency_ms,
                    "qualified": qualified,
                }
            )

        # Identify recommended model
        recommended = None
        for r in sorted_reports:
            if r.success_rate >= min_success_rate and r.cost_per_success != float("inf"):
                recommended = r.model_name
                break

        # Calculate savings vs frontier model
        savings_pct = 0.0
        frontier_report = next((r for r in reports if r.model_name == frontier_reference), None)
        recommended_report = next((r for r in reports if r.model_name == recommended), None)

        if frontier_report and recommended_report:
            f_cost = frontier_report.cost_per_success
            r_cost = recommended_report.cost_per_success
            if f_cost > 0 and f_cost != float("inf") and r_cost != float("inf"):
                savings_pct = round(((f_cost - r_cost) / f_cost) * 100.0, 2)

        return ModelRanking(
            task_type=task_type,
            ranked_models=ranked_list,
            recommended_model=recommended,
            frontier_baseline=frontier_reference if frontier_report else None,
            savings_pct_vs_frontier=max(0.0, savings_pct),
        )

    def check_cost_regression(
        self,
        report: ModelEvalReport,
        threshold_pct: float = 10.0,
    ) -> RegressionCheckResult:
        """
        Check if the model's cost-per-success has regressed by more than threshold_pct (> 10%)
        compared to previous historical benchmarks in storage.
        """
        if self.storage is None:
            return RegressionCheckResult(
                model_name=report.model_name,
                task_type=report.task_type,
                current_cost_per_success=report.cost_per_success,
                baseline_cost_per_success=report.cost_per_success,
                change_pct=0.0,
                has_regression=False,
                threshold_pct=threshold_pct,
                message="No storage backend configured for historical regression comparison.",
            )

        history = self.storage.get_benchmarks(task_type=report.task_type)
        # Filter for historical records of the same model, excluding the current run
        model_history = [
            b
            for b in history
            if b.get("model_name") == report.model_name
            and (report.benchmark_id is None or b.get("id") != report.benchmark_id)
        ]

        if not model_history:
            return RegressionCheckResult(
                model_name=report.model_name,
                task_type=report.task_type,
                current_cost_per_success=report.cost_per_success,
                baseline_cost_per_success=report.cost_per_success,
                change_pct=0.0,
                has_regression=False,
                threshold_pct=threshold_pct,
                message="No prior historical benchmark baseline found for this model and task.",
            )

        # Baseline is the most recent historical benchmark
        baseline = model_history[0]
        base_cost = baseline.get("cost_per_success", 0.0)

        if base_cost <= 0.0 or base_cost == float("inf"):
            return RegressionCheckResult(
                model_name=report.model_name,
                task_type=report.task_type,
                current_cost_per_success=report.cost_per_success,
                baseline_cost_per_success=base_cost,
                change_pct=0.0,
                has_regression=False,
                threshold_pct=threshold_pct,
                message="Historical baseline cost was zero or invalid.",
            )

        current_cost = report.cost_per_success
        change_pct = round(((current_cost - base_cost) / base_cost) * 100.0, 2)
        has_regression = change_pct > threshold_pct

        msg = (
            f"Cost regression detected (+{change_pct}% > {threshold_pct}%) "
            f"from baseline ${base_cost:.6f} to ${current_cost:.6f}."
            if has_regression
            else f"Cost within acceptable tolerance ({change_pct:+.2f}% vs baseline ${base_cost:.6f})."
        )

        return RegressionCheckResult(
            model_name=report.model_name,
            task_type=report.task_type,
            current_cost_per_success=current_cost,
            baseline_cost_per_success=base_cost,
            change_pct=change_pct,
            has_regression=has_regression,
            threshold_pct=threshold_pct,
            message=msg,
        )
