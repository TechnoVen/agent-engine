import os
from core.router.execution_router import ExecutionRouter, ExecutionTier, StepProfile
from core.context.builder import ContextSpec, build_context

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class MockCache:
    def __init__(self, cached_items=None):
        self.cached = cached_items or {}

    def has(self, step_name, inputs):
        return (step_name, inputs.get("query")) in self.cached


def test_execution_router_deterministic_step():
    """Verify deterministic steps route to CODE (0 tokens)."""
    router = ExecutionRouter()
    step = StepProfile(
        step_name="check_file_exists",
        is_deterministic=True,
        requires_judgment=False,
    )
    tier = router.route(step, {"path": "/tmp/test.txt"})
    assert tier == ExecutionTier.CODE


def test_execution_router_cache_hit():
    """Verify cacheable steps with matching cache hit route to CACHE (0 tokens)."""
    mock_cache = MockCache({("faq_lookup", "What are the hours?"): "9am-5pm"})
    router = ExecutionRouter(cache=mock_cache)
    step = StepProfile(
        step_name="faq_lookup",
        is_deterministic=False,
        is_cacheable=True,
        requires_judgment=True,
        complexity="low",
    )
    tier = router.route(step, {"query": "What are the hours?"})
    assert tier == ExecutionTier.CACHE


def test_execution_router_small_model():
    """Verify low-complexity reasoning routes to SMALL_MODEL (Gemma/Qwen)."""
    router = ExecutionRouter()
    step = StepProfile(
        step_name="classify_intent",
        is_deterministic=False,
        is_cacheable=False,
        requires_judgment=True,
        complexity="low",
    )
    tier = router.route(step, {"query": "I want a refund"})
    assert tier == ExecutionTier.SMALL_MODEL


def test_execution_router_mid_model():
    """Verify medium-complexity reasoning routes to MID_MODEL."""
    router = ExecutionRouter()
    step = StepProfile(
        step_name="rag_synthesis",
        is_deterministic=False,
        is_cacheable=False,
        requires_judgment=True,
        complexity="medium",
    )
    tier = router.route(step, {"query": "Summarize policy"})
    assert tier == ExecutionTier.MID_MODEL


def test_execution_router_frontier_model():
    """Verify high-stakes reasoning routes to FRONTIER_MODEL."""
    router = ExecutionRouter()
    step = StepProfile(
        step_name="legal_contract_audit",
        is_deterministic=False,
        is_cacheable=False,
        requires_judgment=True,
        complexity="high",
        is_high_stakes=True,
    )
    tier = router.route(step, {"document": "40-page contract"})
    assert tier == ExecutionTier.FRONTIER_MODEL


def test_context_builder_field_filtering():
    """Verify ContextSpec only includes declared required and optional fields."""
    spec = ContextSpec(
        required_fields=["invoice_id", "total_amount"],
        optional_fields=["vendor"],
        max_tokens=4000,
    )
    raw_payload = {
        "invoice_id": "INV-100",
        "total_amount": "$500",
        "vendor": "Acme Corp",
        "internal_secret_db_creds": "pass123",
        "full_customer_history_10k_lines": "..." * 1000,
    }
    built = build_context(spec, raw_payload)
    assert "invoice_id" in built
    assert "total_amount" in built
    assert "vendor" in built
    assert "internal_secret_db_creds" not in built
    assert "full_customer_history_10k_lines" not in built


def test_context_builder_truncation():
    """Verify context is truncated when exceeding declared max_tokens budget."""
    spec = ContextSpec(
        required_fields=["long_text"],
        max_tokens=100,  # ~400 characters
    )
    raw_payload = {"long_text": "A" * 2000}
    built = build_context(spec, raw_payload)
    assert len(built["long_text"]) < 1000
    assert "[truncated for token budget]" in built["long_text"]


def test_cost_optimization_guide_and_adr_exist():
    """Verify docs/COST_OPTIMIZATION_GUIDE.md and ADR-015 exist and contain 90/9/1 rule."""
    guide_path = os.path.join(PROJECT_ROOT, "docs", "COST_OPTIMIZATION_GUIDE.md")
    assert os.path.isfile(guide_path), "docs/COST_OPTIMIZATION_GUIDE.md missing"
    with open(guide_path, "r", encoding="utf-8") as f:
        guide = f.read()
    assert "The 90/9/1 Rule" in guide
    assert "Execution Router" in guide

    adr_path = os.path.join(PROJECT_ROOT, "docs", "ADR", "README.md")
    with open(adr_path, "r", encoding="utf-8") as f:
        adr = f.read()
    assert "ADR-015" in adr
    assert "90/9/1" in adr
