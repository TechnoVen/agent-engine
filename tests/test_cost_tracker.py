"""Unit and integration tests for CostTracker, BudgetAlerts, Storage, and Telemetry API."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

# Ensure numpy pre-imported
import numpy  # noqa: F401

from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import (
    BudgetConfig,
    CostTracker,
    ModelPricing,
)
from services.python.server.api import app


@pytest.fixture
def memory_storage():
    """Provides an isolated in-memory SQLite storage repository."""
    backend = SQLiteBackend(db_path=":memory:")
    yield backend
    backend.close()


@pytest.fixture
def cost_tracker(memory_storage):
    """Provides a fresh CostTracker wired to in-memory storage."""
    return CostTracker(storage=memory_storage)


# ==============================================================================
# 1. ModelPricing Tests
# ==============================================================================


def test_model_pricing_calculation():
    """Verify standard model pricing math."""
    pricing = ModelPricing(model_name="test-gpt", input_cost_per_1m=2.50, output_cost_per_1m=10.00)
    # 10,000 prompt tokens = 10k/1M * 2.50 = 0.025
    # 5,000 completion tokens = 5k/1M * 10.00 = 0.050
    # Total = 0.075 USD
    cost = pricing.calculate_cost(prompt_tokens=10_000, completion_tokens=5_000)
    assert cost == 0.075


def test_local_model_pricing_zero():
    """Local models (Ollama, llama.cpp, qwen) must cost 0.00 USD."""
    pricing = ModelPricing(
        model_name="qwen2.5-coder", input_cost_per_1m=0.0, output_cost_per_1m=0.0
    )
    cost = pricing.calculate_cost(prompt_tokens=500_000, completion_tokens=100_000)
    assert cost == 0.0


# ==============================================================================
# 2. CostTracker Spend Recording & Summaries
# ==============================================================================


def test_record_spend_with_catalog_lookup(cost_tracker):
    """Recording spend without explicit cost should auto-calculate from catalog."""
    rec_id = cost_tracker.record_spend(
        agent_name="code_sentry",
        model_name="gpt-4o",
        prompt_tokens=100_000,
        completion_tokens=20_000,
        project="proj_alpha",
    )
    assert rec_id >= 1

    summary = cost_tracker.get_summary(project="proj_alpha")
    assert summary["total_calls"] == 1
    assert summary["total_prompt_tokens"] == 100_000
    assert summary["total_completion_tokens"] == 20_000
    assert summary["total_tokens"] == 120_000
    # gpt-4o: 100k * 2.50/1M = 0.25; 20k * 10/1M = 0.20 -> 0.45 USD
    assert abs(summary["total_cost_usd"] - 0.45) < 1e-4


def test_record_spend_explicit_cost(cost_tracker):
    """Explicit cost should override catalog calculation."""
    cost_tracker.record_spend(
        agent_name="summarizer",
        model_name="custom-model",
        prompt_tokens=1_000,
        completion_tokens=500,
        cost_usd=0.1234,
        project="proj_beta",
    )
    summary = cost_tracker.get_summary(project="proj_beta")
    assert summary["total_calls"] == 1
    assert summary["total_cost_usd"] == 0.1234


# ==============================================================================
# 3. Spend Breakdown Grouping (Agent, Model, Project, Day)
# ==============================================================================


def test_get_breakdown_groupings(cost_tracker):
    """Verify breakdown grouping across agent, model, project, and day dimensions."""
    # Insert 3 records
    cost_tracker.record_spend(
        agent_name="agent_a",
        model_name="gpt-4o",
        prompt_tokens=10_000,
        completion_tokens=2_000,
        cost_usd=0.05,
        project="proj_1",
    )
    cost_tracker.record_spend(
        agent_name="agent_a",
        model_name="claude-3-5-sonnet",
        prompt_tokens=20_000,
        completion_tokens=4_000,
        cost_usd=0.10,
        project="proj_1",
    )
    cost_tracker.record_spend(
        agent_name="agent_b",
        model_name="gpt-4o",
        prompt_tokens=5_000,
        completion_tokens=1_000,
        cost_usd=0.02,
        project="proj_2",
    )

    # 1. Group by agent
    by_agent = cost_tracker.get_breakdown(group_by="agent")
    assert len(by_agent) == 2
    agent_names = [row["group"] for row in by_agent]
    assert "agent_a" in agent_names
    assert "agent_b" in agent_names
    agent_a_row = next(r for r in by_agent if r["group"] == "agent_a")
    assert agent_a_row["calls"] == 2
    assert abs(agent_a_row["cost_usd"] - 0.15) < 1e-4

    # 2. Group by model
    by_model = cost_tracker.get_breakdown(group_by="model")
    assert len(by_model) == 2
    models = [row["group"] for row in by_model]
    assert "gpt-4o" in models
    assert "claude-3-5-sonnet" in models

    # 3. Group by project
    by_proj = cost_tracker.get_breakdown(group_by="project")
    assert len(by_proj) == 2
    projs = [row["group"] for row in by_proj]
    assert "proj_1" in projs
    assert "proj_2" in projs

    # 4. Group by day
    by_day = cost_tracker.get_breakdown(group_by="day")
    assert len(by_day) >= 1
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert by_day[0]["group"] == today_iso
    assert by_day[0]["calls"] == 3


# ==============================================================================
# 4. Budget Alert Triggers
# ==============================================================================


def test_budget_alerts_healthy(cost_tracker):
    """Spend within limits should trigger zero alerts."""
    cost_tracker.set_budget(
        BudgetConfig(
            monthly_budget_usd=100.0,
            daily_budget_usd=10.0,
            warning_threshold_pct=80.0,
            critical_threshold_pct=100.0,
            project="team_x",
        )
    )
    cost_tracker.record_spend(
        agent_name="bot",
        model_name="gpt-4o",
        prompt_tokens=1_000,
        completion_tokens=500,
        cost_usd=2.00,
        project="team_x",
    )
    alerts = cost_tracker.check_budget_alerts(project="team_x")
    assert len(alerts) == 0


def test_budget_alerts_warning_and_critical(cost_tracker):
    """Spend >= 80% should trigger warning; spend >= 100% should trigger critical."""
    cost_tracker.set_budget(
        BudgetConfig(
            monthly_budget_usd=50.0,
            daily_budget_usd=10.0,
            warning_threshold_pct=80.0,
            critical_threshold_pct=100.0,
            project="team_y",
        )
    )

    # Spend $8.50 today -> 85% of daily budget ($10) -> Warning!
    cost_tracker.record_spend(
        agent_name="bot",
        model_name="gpt-4o",
        prompt_tokens=1_000,
        completion_tokens=500,
        cost_usd=8.50,
        project="team_y",
    )

    alerts = cost_tracker.check_budget_alerts(project="team_y")
    assert len(alerts) == 1
    assert alerts[0].level == "warning"
    assert alerts[0].period == "daily"
    assert alerts[0].percentage == 85.0

    # Spend another $2.00 today -> total $10.50 -> 105% of daily budget -> Critical!
    cost_tracker.record_spend(
        agent_name="bot",
        model_name="gpt-4o",
        prompt_tokens=1_000,
        completion_tokens=500,
        cost_usd=2.00,
        project="team_y",
    )

    alerts = cost_tracker.check_budget_alerts(project="team_y")
    daily_alerts = [a for a in alerts if a.period == "daily"]
    assert len(daily_alerts) == 1
    assert daily_alerts[0].level == "critical"
    assert daily_alerts[0].percentage == 105.0


# ==============================================================================
# 5. API Endpoints Integration Tests
# ==============================================================================


def test_api_telemetry_cost_endpoints():
    """Verify HTTP endpoints for recording spend, querying breakdown, and managing budgets."""
    client = TestClient(app)

    # 1. Record spend via API
    rec_res = client.post(
        "/v1/telemetry/cost/record",
        json={
            "agent_name": "qa_agent",
            "model_name": "gpt-4o",
            "prompt_tokens": 10_000,
            "completion_tokens": 2_000,
            "project": "api_test_project",
        },
    )
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["success"] is True
    assert rec_data["id"] >= 1

    # 2. Query cost breakdown
    cost_res = client.get("/v1/telemetry/cost?group_by=agent&project=api_test_project")
    assert cost_res.status_code == 200
    cost_data = cost_res.json()
    assert "total_cost_usd" in cost_data
    assert "breakdown" in cost_data
    assert len(cost_data["breakdown"]) >= 1

    # 3. Configure budget via API
    budget_post_res = client.post(
        "/v1/telemetry/budget",
        json={
            "monthly_budget_usd": 200.0,
            "daily_budget_usd": 20.0,
            "warning_threshold_pct": 75.0,
            "critical_threshold_pct": 100.0,
            "project": "api_test_project",
        },
    )
    assert budget_post_res.status_code == 200
    budget_post_data = budget_post_res.json()
    assert budget_post_data["monthly_budget_usd"] == 200.0
    assert budget_post_data["daily_budget_usd"] == 20.0

    # 4. Get budget via API
    budget_get_res = client.get("/v1/telemetry/budget?project=api_test_project")
    assert budget_get_res.status_code == 200
    budget_get_data = budget_get_res.json()
    assert budget_get_data["project"] == "api_test_project"
    assert budget_get_data["monthly_budget_usd"] == 200.0
    assert "alerts" in budget_get_data
