"""
Agent Engine Safety & Guardrail Policy Subsystem.

Provides:
- PolicyEngine: Central guardrail policy engine evaluating tools against declarative YAML rules.
- PolicyRule: Declarative rule dataclass supporting regex, glob, and keyword matchers.
- PolicyDecision: Evaluated decision (allow, block, stage) with risk scores and remediation suggestions.
- RiskScorer, RiskLevel: Dynamic risk scoring engine.
- AuditLogger: Persistent audit log recorder integrated with the Storage repository.
"""

from core.safety.audit import AuditLogger
from core.safety.policy import PolicyDecision, PolicyEngine, PolicyRule
from core.safety.risk import RiskLevel, RiskScorer

_GLOBAL_POLICY_ENGINE = None


def get_policy_engine() -> PolicyEngine:
    """Retrieve or initialize the global singleton PolicyEngine."""
    global _GLOBAL_POLICY_ENGINE
    if _GLOBAL_POLICY_ENGINE is None:
        _GLOBAL_POLICY_ENGINE = PolicyEngine()
    return _GLOBAL_POLICY_ENGINE


__all__ = [
    "PolicyEngine",
    "PolicyRule",
    "PolicyDecision",
    "RiskScorer",
    "RiskLevel",
    "AuditLogger",
    "get_policy_engine",
]
