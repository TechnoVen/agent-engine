from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from core.router.circuit_breaker import CircuitBreakerConfig

logger = logging.getLogger("agent_engine.router.config")

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


@dataclass
class HealthCheckConfig:
    timeout_seconds: float = 2.0
    cache_ttl_seconds: float = 5.0


@dataclass
class CostCeilingConfig:
    max_request_cost_dollars: float = 0.10
    enforce_ceiling: bool = False


@dataclass
class RouterConfigFile:
    default_priority: list[str] = field(
        default_factory=lambda: [
            "ollama",
            "llamacpp",
            "gemini",
            "openai",
            "deepseek",
            "groq",
            "kimi",
        ]
    )
    task_preferences: dict[str, list[str]] = field(
        default_factory=lambda: {
            "code_generation": ["ollama", "llamacpp", "gemini", "openai"],
            "quick_classification": ["llamacpp", "ollama", "groq", "gemini"],
            "deep_reasoning": ["gemini", "openai", "deepseek", "groq"],
            "general_chat": ["ollama", "llamacpp", "gemini", "openai"],
        }
    )
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    health_check: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    cost_ceiling: CostCeilingConfig = field(default_factory=CostCeilingConfig)


def load_router_config(config_path: Path | str | None = None) -> RouterConfigFile:
    """Load router configuration from YAML file and apply environment variable overrides."""
    target_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}

    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                if isinstance(content, dict):
                    data = content
        except Exception as e:
            logger.warning("Failed to load %s: %s. Using default router config.", target_path, e)

    # Defaults
    default_priority = data.get(
        "default_priority",
        ["ollama", "llamacpp", "gemini", "openai", "deepseek", "groq", "kimi"],
    )

    # Allow env var PROVIDER_PRIORITY override
    env_priority = os.getenv("PROVIDER_PRIORITY")
    if env_priority:
        default_priority = [p.strip() for p in env_priority.split(",") if p.strip()]

    task_prefs = data.get("task_preferences", {})
    if not task_prefs:
        task_prefs = {
            "code_generation": ["ollama", "llamacpp", "gemini", "openai"],
            "quick_classification": ["llamacpp", "ollama", "groq", "gemini"],
            "deep_reasoning": ["gemini", "openai", "deepseek", "groq"],
            "general_chat": ["ollama", "llamacpp", "gemini", "openai"],
        }

    # Circuit breaker
    cb_data = data.get("circuit_breaker", {})
    cb_threshold = int(
        os.getenv(
            "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
            str(cb_data.get("failure_threshold", 3)),
        )
    )
    cb_recovery = float(
        os.getenv(
            "CIRCUIT_BREAKER_RECOVERY_TIMEOUT",
            str(cb_data.get("recovery_timeout", 30.0)),
        )
    )
    cb_config = CircuitBreakerConfig(
        failure_threshold=cb_threshold,
        recovery_timeout=cb_recovery,
        half_open_success_threshold=int(cb_data.get("half_open_success_threshold", 1)),
    )

    # Health check
    hc_data = data.get("health_check", {})
    hc_timeout = float(os.getenv("REQUEST_TIMEOUT", str(hc_data.get("timeout_seconds", 2.0))))
    hc_config = HealthCheckConfig(
        timeout_seconds=hc_timeout,
        cache_ttl_seconds=float(hc_data.get("cache_ttl_seconds", 5.0)),
    )

    # Cost ceiling
    cc_data = data.get("cost_ceiling", {})
    cc_config = CostCeilingConfig(
        max_request_cost_dollars=float(cc_data.get("max_request_cost_dollars", 0.10)),
        enforce_ceiling=bool(cc_data.get("enforce_ceiling", False)),
    )

    return RouterConfigFile(
        default_priority=default_priority,
        task_preferences=task_prefs,
        circuit_breaker=cb_config,
        health_check=hc_config,
        cost_ceiling=cc_config,
    )
