"""
Unit & Integration Tests for Execution Router (Task 1.10).

Validates:
- 90/9/1 decision tree across all execution tiers (CODE, CACHE, SMALL, MID, FRONTIER, HUMAN).
- SemanticCache integration (sub-millisecond 0-token hit resolution).
- ContextBuilder integration (token budgeting & field whitelisting during step execution).
- Dynamic model resolution via ModelEvalSuite benchmark rankings.
- Step execution lifecycle (CODE, CACHE, MODEL, HUMAN).
- Law 1 (The 90/9/1 Rule) pipeline auditing (frontier ceiling <= 10%).
- @profiled_step decorator.
- REST API endpoints: POST /v1/router/route, POST /v1/router/audit, GET /v1/router/tiers.
"""

from fastapi.testclient import TestClient

from core.cache.semantic_cache import SemanticCache
from core.context.builder import ContextSpec
from core.eval.suite import ModelEvalSuite
from core.router.execution_router import (
    ExecutionRouter,
    ExecutionTier,
    StepProfile,
    audit_pipeline,
    profiled_step,
)
from core.storage.sqlite import SQLiteBackend
from services.python.server.api import app

client = TestClient(app)


def test_route_decision_tree_all_tiers():
    """Verify each tier is accurately classified according to the 90/9/1 decision tree."""
    router = ExecutionRouter()

    # 1. Deterministic -> CODE
    p_code = StepProfile(step_name="hash_calc", is_deterministic=True)
    assert router.route(p_code) == ExecutionTier.CODE

    # 2. No judgment -> CODE
    p_no_judge = StepProfile(step_name="copy_file", is_deterministic=False, requires_judgment=False)
    assert router.route(p_no_judge) == ExecutionTier.CODE

    # 3. Low complexity -> SMALL_MODEL
    p_small = StepProfile(step_name="classify", requires_judgment=True, complexity="low")
    assert router.route(p_small) == ExecutionTier.SMALL_MODEL

    # 4. High-stakes -> FRONTIER_MODEL
    p_frontier = StepProfile(step_name="sign_contract", requires_judgment=True, is_high_stakes=True)
    assert router.route(p_frontier) == ExecutionTier.FRONTIER_MODEL

    # 5. Medium complexity -> MID_MODEL
    p_mid = StepProfile(step_name="synthesize", requires_judgment=True, complexity="medium")
    assert router.route(p_mid) == ExecutionTier.MID_MODEL

    # 6. Fallback tier
    p_fallback = StepProfile(
        step_name="custom_step",
        requires_judgment=True,
        complexity="high",
        is_high_stakes=False,
        fallback_tier=ExecutionTier.HUMAN,
    )
    assert router.route(p_fallback) == ExecutionTier.HUMAN


def test_semantic_cache_integration(tmp_path):
    """Verify router checks SemanticCache and routes to CACHE on hit."""
    cache = SemanticCache(persist_directory=str(tmp_path / "cache"))
    cache.store(
        query="What is the refund policy?",
        response="Full refund within 30 days.",
        namespace="policy",
    )

    router = ExecutionRouter(cache=cache)
    step = StepProfile(
        step_name="faq_lookup",
        is_cacheable=True,
        requires_judgment=True,
        cache_namespace="policy",
    )

    # Cache hit query -> CACHE
    tier_hit = router.route(step, {"query": "What is the refund policy?"})
    assert tier_hit == ExecutionTier.CACHE

    # Cache miss query -> Falls back to small model (low complexity)
    tier_miss = router.route(step, {"query": "How do I launch a rocket?"})
    assert tier_miss == ExecutionTier.SMALL_MODEL


def test_context_builder_budget_integration():
    """Verify execute_step enforces ContextSpec budgeting and field filtering."""
    router = ExecutionRouter()
    spec = ContextSpec(
        required_fields=["customer_id"],
        optional_fields=["plan"],
        max_tokens=100,
    )
    step = StepProfile(
        step_name="account_check",
        requires_judgment=True,
        complexity="low",
        context_spec=spec,
    )

    captured_context = None

    def mock_executor(model, ctx):
        nonlocal captured_context
        captured_context = ctx
        return {"output": "Account is active", "prompt_tokens": 20, "completion_tokens": 10}

    inputs = {
        "customer_id": "CUST-100",
        "plan": "Enterprise",
        "unauthorized_secret": "sk_super_secret",
        "giant_blob": "x" * 10000,
    }

    result = router.execute_step(step, inputs, execute_fn=mock_executor)

    assert result.tier == ExecutionTier.SMALL_MODEL
    assert result.output == "Account is active"
    assert captured_context is not None
    assert "customer_id" in captured_context
    assert "plan" in captured_context
    assert "unauthorized_secret" not in captured_context
    assert "giant_blob" not in captured_context


def test_dynamic_model_resolution_via_eval_suite():
    """Verify router can resolve preferred model for tier using benchmark rankings."""
    storage = SQLiteBackend(db_path=":memory:")
    storage.record_benchmark(
        model_name="qwen2.5-coder",
        task_type="code",
        success_rate=0.95,
        latency_ms=250.0,
        cost_per_success=0.0001,
    )

    eval_suite = ModelEvalSuite(storage=storage)
    router = ExecutionRouter()

    # Should pick qwen2.5-coder from storage since it succeeded for code
    resolved = router.resolve_model(
        ExecutionTier.SMALL_MODEL,
        task_type="code",
        eval_suite=eval_suite,
    )
    assert resolved == "qwen2.5-coder"


def test_execute_step_code_tier():
    """Verify deterministic CODE tier execution consumes 0 tokens and $0.00."""
    router = ExecutionRouter()
    step = StepProfile(step_name="parse_json", is_deterministic=True)

    result = router.execute_step(
        step=step,
        inputs={"raw": '{"a": 1}'},
        execute_fn=lambda m, i: {"parsed": True},
    )

    assert result.tier == ExecutionTier.CODE
    assert result.tokens_used == 0
    assert result.cost_usd == 0.0
    assert result.output == {"parsed": True}
    assert result.model_used is None


def test_execute_step_cache_tier(tmp_path):
    """Verify CACHE tier execution returns cached output with 0 tokens."""
    cache = SemanticCache(persist_directory=str(tmp_path / "cache"))
    cache.store(
        query="Status report",
        response={"system": "ok", "latency": "12ms"},
        namespace="status",
    )

    router = ExecutionRouter(cache=cache)
    step = StepProfile(
        step_name="status_query",
        is_cacheable=True,
        requires_judgment=True,
        cache_namespace="status",
    )

    result = router.execute_step(
        step=step,
        inputs={"query": "Status report"},
    )

    assert result.tier == ExecutionTier.CACHE
    assert result.cache_hit is True
    assert result.tokens_used == 0
    assert result.cost_usd == 0.0
    assert result.output == {"system": "ok", "latency": "12ms"}


def test_execute_step_human_tier():
    """Verify HUMAN tier execution flags step for human confirmation with 0 token spend."""
    router = ExecutionRouter()
    step = StepProfile(
        step_name="drop_production_db",
        requires_judgment=True,
        complexity="high",
        fallback_tier=ExecutionTier.HUMAN,
    )

    result = router.execute_step(step=step, inputs={"action": "drop_all"})

    assert result.tier == ExecutionTier.HUMAN
    assert result.requires_human is True
    assert result.tokens_used == 0
    assert result.cost_usd == 0.0


def test_execute_step_model_tier_and_cache_store(tmp_path):
    """Verify model tier step executes, calculates cost, and stores in cache if cacheable."""
    cache = SemanticCache(persist_directory=str(tmp_path / "cache"))
    router = ExecutionRouter(cache=cache)

    step = StepProfile(
        step_name="summarize_notes",
        is_cacheable=True,
        requires_judgment=True,
        complexity="medium",  # -> MID_MODEL
        cache_namespace="notes",
    )

    def mock_runner(model, inp):
        return {
            "output": "Executive Summary: Q3 targets met.",
            "prompt_tokens": 150,
            "completion_tokens": 50,
        }

    result = router.execute_step(step, {"query": "Summarize Q3 notes"}, execute_fn=mock_runner)

    assert result.tier == ExecutionTier.MID_MODEL
    assert result.tokens_used == 200
    assert result.cost_usd > 0.0
    assert "Executive Summary" in result.output

    # Querying the exact same inputs should now hit cache
    cached_result = router.execute_step(step, {"query": "Summarize Q3 notes"})
    assert cached_result.tier == ExecutionTier.CACHE
    assert cached_result.cache_hit is True
    assert cached_result.tokens_used == 0


def test_law_1_ratio_audit_compliant():
    """Verify compliant 90/9/1 pipeline passes audit."""
    # 10 steps: 9 deterministic/small (90%), 1 mid-tier (10%), 0 frontier (0%)
    steps = [StepProfile(step_name=f"code_{i}", is_deterministic=True) for i in range(7)] + [
        StepProfile(step_name="classify_1", requires_judgment=True, complexity="low"),
        StepProfile(step_name="classify_2", requires_judgment=True, complexity="low"),
        StepProfile(step_name="rag_synthesis", requires_judgment=True, complexity="medium"),
    ]

    audit = audit_pipeline(steps)
    assert audit.complies_with_law_1 is True
    assert audit.deterministic_or_small_pct == 90.0
    assert audit.mid_tier_pct == 10.0
    assert audit.frontier_pct == 0.0
    assert len(audit.violations) == 0


def test_law_1_ratio_audit_frontier_violation():
    """Verify pipeline with > 10% frontier model steps fails audit with violation reason."""
    # 10 steps with 3 high-stakes frontier steps (30% > 10%)
    steps = [StepProfile(step_name=f"code_{i}", is_deterministic=True) for i in range(7)] + [
        StepProfile(step_name="frontier_1", requires_judgment=True, is_high_stakes=True),
        StepProfile(step_name="frontier_2", requires_judgment=True, is_high_stakes=True),
        StepProfile(step_name="frontier_3", requires_judgment=True, is_high_stakes=True),
    ]

    audit = audit_pipeline(steps)
    assert audit.complies_with_law_1 is False
    assert audit.frontier_pct == 30.0
    assert any("exceed the 10% allowable ceiling" in v for v in audit.violations)


def test_profiled_step_decorator():
    """Verify @profiled_step decorator wraps a function and attaches profile."""
    profile = StepProfile(
        step_name="compute_discount",
        is_deterministic=True,
    )

    @profiled_step(profile)
    def compute_discount(subtotal: float, discount_pct: float) -> float:
        return subtotal * (1.0 - discount_pct)

    assert hasattr(compute_discount, "step_profile")
    assert compute_discount.step_profile.step_name == "compute_discount"

    res = compute_discount(subtotal=100.0, discount_pct=0.2)
    assert res == 80.0


def test_rest_api_router_route():
    """Verify POST /v1/router/route endpoint."""
    payload = {
        "step": {
            "step_name": "classify_ticket",
            "is_deterministic": False,
            "requires_judgment": True,
            "complexity": "low",
        },
        "inputs": {"text": "My server is down"},
    }

    res = client.post("/v1/router/route", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["step_name"] == "classify_ticket"
    assert data["tier"] == "small_model"
    assert data["resolved_model"] is not None
    assert "rationale" in data


def test_rest_api_router_audit():
    """Verify POST /v1/router/audit endpoint."""
    payload = {
        "steps": [
            {"step_name": "clean_data", "is_deterministic": True},
            {"step_name": "extract_fields", "is_deterministic": True},
            {"step_name": "classify_intent", "requires_judgment": True, "complexity": "low"},
            {"step_name": "draft_response", "requires_judgment": True, "complexity": "medium"},
        ]
    }

    res = client.post("/v1/router/audit", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["total_steps"] == 4
    assert data["complies_with_law_1"] is True
    assert data["frontier_pct"] == 0.0


def test_rest_api_router_tiers():
    """Verify GET /v1/router/tiers endpoint returns tier definitions."""
    res = client.get("/v1/router/tiers")
    assert res.status_code == 200
    data = res.json()

    assert "tiers" in data
    assert "small_model" in data["tiers"]
    assert "mid_model" in data["tiers"]
    assert "frontier_model" in data["tiers"]
    assert "law_1_guidelines" in data
