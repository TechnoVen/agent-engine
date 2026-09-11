"""
core/router package.
Exposes:
- ModelRouter (hardened multi-provider health, circuit breaker & fallback chains)
- CircuitBreaker, CircuitState, CircuitBreakerConfig
- HealthProber, ProbeResult
- load_router_config, RouterConfigFile
- ExecutionRouter (90/9/1 cost minimization step router)
"""

from core.router.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)
from core.router.config import (
    CostCeilingConfig,
    HealthCheckConfig,
    RouterConfigFile,
    load_router_config,
)
from core.router.execution_router import (
    DEFAULT_TIER_MODELS,
    ExecutionRouter,
    ExecutionTier,
    RatioAudit,
    StepExecutionResult,
    StepProfile,
    audit_pipeline,
    profiled_step,
)
from core.router.health import HealthProber, ProbeResult
from core.router.model_router import ModelRouter

__all__ = [
    "ModelRouter",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "HealthProber",
    "ProbeResult",
    "RouterConfigFile",
    "CostCeilingConfig",
    "HealthCheckConfig",
    "load_router_config",
    "ExecutionRouter",
    "ExecutionTier",
    "StepProfile",
    "StepExecutionResult",
    "RatioAudit",
    "audit_pipeline",
    "profiled_step",
    "DEFAULT_TIER_MODELS",
]
