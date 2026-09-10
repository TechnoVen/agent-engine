"""Agent Engine - Cost Tracking & Budget Alerts.

Provides per-request, per-agent, per-model, and per-project spend tracking,
standard model pricing catalogs, dynamic budget evaluation, and alert generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

from core.storage import get_storage_backend
from core.storage.base import StorageBackend


@dataclass
class ModelPricing:
    """Pricing configuration for a model (USD per 1M tokens)."""

    model_name: str
    input_cost_per_1m: float
    output_cost_per_1m: float

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate USD cost for the given token count."""
        prompt_cost = (prompt_tokens * self.input_cost_per_1m) / 1_000_000.0
        completion_cost = (completion_tokens * self.output_cost_per_1m) / 1_000_000.0
        return round(prompt_cost + completion_cost, 6)


DEFAULT_PRICING: Dict[str, ModelPricing] = {
    # OpenAI
    "gpt-4o": ModelPricing("gpt-4o", input_cost_per_1m=2.50, output_cost_per_1m=10.00),
    "gpt-4o-mini": ModelPricing("gpt-4o-mini", input_cost_per_1m=0.15, output_cost_per_1m=0.60),
    "o1": ModelPricing("o1", input_cost_per_1m=15.00, output_cost_per_1m=60.00),
    "o3-mini": ModelPricing("o3-mini", input_cost_per_1m=1.10, output_cost_per_1m=4.40),
    # Anthropic
    "claude-3-5-sonnet": ModelPricing(
        "claude-3-5-sonnet", input_cost_per_1m=3.00, output_cost_per_1m=15.00
    ),
    "claude-3-5-haiku": ModelPricing(
        "claude-3-5-haiku", input_cost_per_1m=0.80, output_cost_per_1m=4.00
    ),
    "claude-3-opus": ModelPricing(
        "claude-3-opus", input_cost_per_1m=15.00, output_cost_per_1m=75.00
    ),
    # Google
    "gemini-1.5-pro": ModelPricing(
        "gemini-1.5-pro", input_cost_per_1m=3.50, output_cost_per_1m=10.50
    ),
    "gemini-1.5-flash": ModelPricing(
        "gemini-1.5-flash", input_cost_per_1m=0.075, output_cost_per_1m=0.30
    ),
    "gemini-2.0-flash": ModelPricing(
        "gemini-2.0-flash", input_cost_per_1m=0.10, output_cost_per_1m=0.40
    ),
    # DeepSeek
    "deepseek-chat": ModelPricing("deepseek-chat", input_cost_per_1m=0.14, output_cost_per_1m=0.28),
    "deepseek-r1": ModelPricing("deepseek-r1", input_cost_per_1m=0.55, output_cost_per_1m=2.19),
    # Local models (Ollama, vLLM, llama.cpp) -> Zero dollar inference
    "qwen2.5-coder": ModelPricing("qwen2.5-coder", input_cost_per_1m=0.0, output_cost_per_1m=0.0),
    "llama3.2": ModelPricing("llama3.2", input_cost_per_1m=0.0, output_cost_per_1m=0.0),
    "local": ModelPricing("local", input_cost_per_1m=0.0, output_cost_per_1m=0.0),
}


@dataclass
class BudgetConfig:
    """Budget limits and alert thresholds for a project."""

    monthly_budget_usd: float = 100.0
    daily_budget_usd: float = 10.0
    warning_threshold_pct: float = 80.0
    critical_threshold_pct: float = 100.0
    project: str = "default"


@dataclass
class BudgetAlert:
    """Alert triggered when spend exceeds budget thresholds."""

    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    level: str = "warning"  # "warning" | "critical"
    message: str = ""
    current_spend: float = 0.0
    budget_limit: float = 0.0
    percentage: float = 0.0
    period: str = "monthly"  # "monthly" | "daily"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    project: str = "default"


class CostTracker:
    """Tracks token spend across agents, models, and projects, with budget threshold alerts."""

    def __init__(
        self,
        storage: Optional[StorageBackend] = None,
        pricing_catalog: Optional[Dict[str, ModelPricing]] = None,
    ):
        self.storage = storage or get_storage_backend()
        self.pricing_catalog: Dict[str, ModelPricing] = dict(DEFAULT_PRICING)
        if pricing_catalog:
            self.pricing_catalog.update(pricing_catalog)
        self._budgets: Dict[str, BudgetConfig] = {"default": BudgetConfig()}

    def register_pricing(self, pricing: ModelPricing) -> None:
        """Register or update model pricing."""
        self.pricing_catalog[pricing.model_name.lower()] = pricing

    def get_pricing(self, model_name: str) -> Optional[ModelPricing]:
        """Look up pricing by exact model name or prefix match."""
        lower = model_name.lower()
        if lower in self.pricing_catalog:
            return self.pricing_catalog[lower]
        for name, pricing in self.pricing_catalog.items():
            if name in lower:
                return pricing
        return None

    def calculate_cost(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate USD cost based on catalog, or return 0.0 if local/unknown."""
        pricing = self.get_pricing(model_name)
        if pricing:
            return pricing.calculate_cost(prompt_tokens, completion_tokens)
        return 0.0

    def record_spend(
        self,
        agent_name: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: Optional[float] = None,
        task_id: Optional[str] = None,
        success: bool = True,
        project: str = "default",
    ) -> int:
        """Record spend into storage.

        If cost_usd is not provided, computes from pricing catalog.
        """
        if cost_usd is None:
            cost_usd = self.calculate_cost(model_name, prompt_tokens, completion_tokens)

        return self.storage.record_cost(
            agent_name=agent_name,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            task_id=task_id,
            success=success,
            project=project,
        )

    def get_summary(
        self,
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregate spend summary."""
        return self.storage.get_cost_summary(
            agent_name=agent_name, model_name=model_name, project=project
        )

    def get_breakdown(
        self,
        group_by: str = "day",
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get spend breakdown grouped by agent, model, project, or day."""
        return self.storage.get_cost_breakdown(
            group_by=group_by,
            agent_name=agent_name,
            model_name=model_name,
            project=project,
        )

    def set_budget(self, budget: BudgetConfig) -> None:
        """Set budget configuration for a project."""
        self._budgets[budget.project] = budget

    def get_budget(self, project: str = "default") -> BudgetConfig:
        """Get budget configuration for a project."""
        return self._budgets.get(project, BudgetConfig(project=project))

    def check_budget_alerts(self, project: str = "default") -> List[BudgetAlert]:
        """Evaluate project spend against budget limits and return active alerts."""
        budget = self.get_budget(project)
        now = datetime.now(timezone.utc)
        current_month = now.strftime("%Y-%m")
        current_day = now.strftime("%Y-%m-%d")

        # Get day-by-day breakdown for project
        daily_breakdown = self.storage.get_cost_breakdown(group_by="day", project=project)

        month_spend = 0.0
        day_spend = 0.0

        for row in daily_breakdown:
            day_str = str(row.get("group", ""))
            row_cost = float(row.get("cost_usd", 0.0))
            if day_str.startswith(current_month):
                month_spend += row_cost
            if day_str == current_day:
                day_spend += row_cost

        alerts: List[BudgetAlert] = []

        # 1. Evaluate Monthly Budget
        if budget.monthly_budget_usd > 0:
            pct_month = (month_spend / budget.monthly_budget_usd) * 100.0
            if pct_month >= budget.critical_threshold_pct:
                alerts.append(
                    BudgetAlert(
                        level="critical",
                        message=(
                            f"Project '{project}' monthly spend (${month_spend:.2f}) "
                            f"exceeds limit (${budget.monthly_budget_usd:.2f}) at {pct_month:.1f}%"
                        ),
                        current_spend=round(month_spend, 4),
                        budget_limit=budget.monthly_budget_usd,
                        percentage=round(pct_month, 1),
                        period="monthly",
                        project=project,
                    )
                )
            elif pct_month >= budget.warning_threshold_pct:
                alerts.append(
                    BudgetAlert(
                        level="warning",
                        message=(
                            f"Project '{project}' monthly spend (${month_spend:.2f}) "
                            f"reached warning threshold ({pct_month:.1f}% of ${budget.monthly_budget_usd:.2f})"
                        ),
                        current_spend=round(month_spend, 4),
                        budget_limit=budget.monthly_budget_usd,
                        percentage=round(pct_month, 1),
                        period="monthly",
                        project=project,
                    )
                )

        # 2. Evaluate Daily Budget
        if budget.daily_budget_usd > 0:
            pct_day = (day_spend / budget.daily_budget_usd) * 100.0
            if pct_day >= budget.critical_threshold_pct:
                alerts.append(
                    BudgetAlert(
                        level="critical",
                        message=(
                            f"Project '{project}' daily spend (${day_spend:.2f}) "
                            f"exceeds daily limit (${budget.daily_budget_usd:.2f}) at {pct_day:.1f}%"
                        ),
                        current_spend=round(day_spend, 4),
                        budget_limit=budget.daily_budget_usd,
                        percentage=round(pct_day, 1),
                        period="daily",
                        project=project,
                    )
                )
            elif pct_day >= budget.warning_threshold_pct:
                alerts.append(
                    BudgetAlert(
                        level="warning",
                        message=(
                            f"Project '{project}' daily spend (${day_spend:.2f}) "
                            f"reached warning threshold ({pct_day:.1f}% of ${budget.daily_budget_usd:.2f})"
                        ),
                        current_spend=round(day_spend, 4),
                        budget_limit=budget.daily_budget_usd,
                        percentage=round(pct_day, 1),
                        period="daily",
                        project=project,
                    )
                )

        return alerts


_GLOBAL_COST_TRACKER: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """Get or create singleton CostTracker."""
    global _GLOBAL_COST_TRACKER
    if _GLOBAL_COST_TRACKER is None:
        _GLOBAL_COST_TRACKER = CostTracker()
    return _GLOBAL_COST_TRACKER
