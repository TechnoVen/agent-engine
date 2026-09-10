import fnmatch
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from core.safety.audit import AuditLogger
from core.safety.risk import RiskLevel, RiskScorer

logger = logging.getLogger("agent_engine.safety.policy")

DEFAULT_POLICY_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "policies", "default.yaml")
)


@dataclass
class PolicyRule:
    """A declarative safety guardrail rule."""

    id: str
    name: str
    description: str
    match_type: str  # regex, glob, keyword
    pattern: str
    action: str = "block"  # block, stage, warn, allow
    risk_level: str = "high"  # low, medium, high, critical
    reason: Optional[str] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "match_type": self.match_type,
            "pattern": self.pattern,
            "action": self.action,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "suggestion": self.suggestion,
        }

    def matches(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        """Evaluate whether this rule matches the given tool call arguments."""
        # Extract target text candidates from tool args
        args_values = [str(v) for v in tool_args.values()]
        full_text = " ".join(args_values)

        # File paths specifically (for glob matching)
        path_keys = {
            "path",
            "file_path",
            "targetfile",
            "target_file",
            "absolutepath",
            "absolute_path",
            "filename",
        }
        path_candidates = [str(v) for k, v in tool_args.items() if k.lower() in path_keys]

        if self.match_type.lower() == "regex":
            try:
                rx = re.compile(self.pattern, re.IGNORECASE)
                if rx.search(full_text):
                    return True
                # Also check each argument individually
                for v in args_values:
                    if rx.search(v):
                        return True
            except re.error as e:
                logger.error("Invalid regex pattern in rule '%s': %s", self.id, e)
                return False

        elif self.match_type.lower() == "glob":
            # Test against identified file paths or individual arguments
            candidates_to_test = path_candidates if path_candidates else args_values
            for target in candidates_to_test:
                if fnmatch.fnmatch(target, self.pattern) or fnmatch.fnmatch(
                    os.path.basename(target), self.pattern
                ):
                    return True
                # Handle comma-separated glob lists like **/{.env*,*.pem}
                if "{" in self.pattern and "}" in self.pattern:
                    sub_patterns = self._expand_braces(self.pattern)
                    for sub in sub_patterns:
                        if fnmatch.fnmatch(target, sub) or fnmatch.fnmatch(
                            os.path.basename(target), sub
                        ):
                            return True

        elif self.match_type.lower() in ("keyword", "semantic"):
            kw_clean = self.pattern.lower().strip()
            if kw_clean in full_text.lower():
                return True

        return False

    @staticmethod
    def _expand_braces(pattern: str) -> List[str]:
        """Expand bash-style brace patterns e.g. **/{.env*,*.key} -> [**/.env*, **/*.key]."""
        m = re.search(r"\{([^}]+)\}", pattern)
        if not m:
            return [pattern]
        prefix = pattern[: m.start()]
        suffix = pattern[m.end() :]
        choices = m.group(1).split(",")
        return [f"{prefix}{c.strip()}{suffix}" for c in choices]


@dataclass
class PolicyDecision:
    """The result of evaluating a prospective tool call against active guardrails."""

    decision: str  # allow, block, stage, warn
    risk_score: float  # 0.0 to 1.0
    risk_level: str  # low, medium, high, critical
    violating_rules: List[PolicyRule]
    suggestion: Optional[str] = None
    reason: Optional[str] = None
    audit_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "risk_score": round(self.risk_score, 2),
            "risk_level": self.risk_level,
            "violating_rules": [r.to_dict() for r in self.violating_rules],
            "suggestion": self.suggestion,
            "reason": self.reason,
            "audit_id": self.audit_id,
        }


class PolicyEngine:
    """
    Central Guardrail Policy Engine.
    Enforces declarative YAML policies, calculates dynamic risk scores,
    enforces Conflict C6 (safety-first staging), and writes to the audit log.
    """

    def __init__(
        self,
        policy_file: Optional[str] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.policy_file = policy_file or DEFAULT_POLICY_FILE
        self.audit_logger = audit_logger or AuditLogger()
        self._rules: Dict[str, PolicyRule] = {}
        self.load_policies()

    def load_policies(self) -> None:
        """Load safety rules from the policy YAML file."""
        if os.path.exists(self.policy_file):
            try:
                with open(self.policy_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                rules_list = data.get("rules", [])
                for r in rules_list:
                    rule = PolicyRule(
                        id=r["id"],
                        name=r.get("name", r["id"]),
                        description=r.get("description", ""),
                        match_type=r.get("match_type", "regex"),
                        pattern=r["pattern"],
                        action=r.get("action", "block"),
                        risk_level=r.get("risk_level", "high"),
                        reason=r.get("reason"),
                        suggestion=r.get("suggestion"),
                    )
                    self._rules[rule.id] = rule
                logger.info("Loaded %d safety rules from %s", len(self._rules), self.policy_file)
            except Exception as e:
                logger.error("Failed to load policy file %s: %s", self.policy_file, e)

    def add_rule(self, rule: PolicyRule) -> None:
        """Add or update an in-memory safety rule."""
        self._rules[rule.id] = rule

    def get_rule(self, rule_id: str) -> Optional[PolicyRule]:
        return self._rules.get(rule_id)

    def list_rules(self) -> List[PolicyRule]:
        return list(self._rules.values())

    def evaluate(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        """
        Evaluate a prospective tool call against active guardrail policies.
        Enforces blocking rules, computes risk scores, applies Conflict C6 staging,
        and logs the outcome to the persistent audit log.
        """
        ctx = context or {}
        session_id = ctx.get("session_id")
        allow_high_risk = ctx.get("allow_high_risk", False)
        auto_apply = ctx.get("auto_apply", False)

        # 1. Compute dynamic risk score
        risk_score, risk_level, _ = RiskScorer.score_tool_call(tool_name, tool_args)

        # 2. Check all active rules
        violating_rules: List[PolicyRule] = []
        for rule in self._rules.values():
            if rule.matches(tool_name, tool_args):
                violating_rules.append(rule)

        # 3. Determine final decision
        decision = "allow"
        reason = None
        suggestion = None
        primary_policy_id = None

        # Check for blocking rules first
        blocking_rules = [r for r in violating_rules if r.action.lower() == "block"]
        staging_rules = [r for r in violating_rules if r.action.lower() == "stage"]

        if blocking_rules:
            decision = "block"
            primary_rule = blocking_rules[0]
            reason = primary_rule.reason or f"Action blocked by policy rule '{primary_rule.name}'."
            suggestion = primary_rule.suggestion
            primary_policy_id = primary_rule.id
            # Escalate risk level if blocked
            risk_score = max(risk_score, 0.90)
            risk_level = RiskLevel.CRITICAL
        elif staging_rules:
            decision = "stage"
            primary_rule = staging_rules[0]
            reason = (
                primary_rule.reason or f"Action requires staging per rule '{primary_rule.name}'."
            )
            suggestion = primary_rule.suggestion
            primary_policy_id = primary_rule.id
        elif risk_score >= 0.70 and not (allow_high_risk or auto_apply):
            # Conflict Resolution C6: Staged by default for high risk
            decision = "stage"
            reason = (
                f"Action staged by default due to high risk score ({risk_score:.2f} >= 0.70) "
                "requiring explicit confirmation (Conflict C6)."
            )
            suggestion = "Review staged action parameters before manual approval."
        else:
            decision = "allow"
            reason = "Action complies with all active safety guardrails."

        # 4. Record event in persistent audit log
        audit_id = self.audit_logger.log_evaluation(
            tool_name=tool_name,
            tool_args=tool_args,
            decision=decision,
            risk_level=risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level),
            risk_score=risk_score,
            policy_id=primary_policy_id,
            reason=reason,
            suggestion=suggestion,
            session_id=session_id,
        )

        return PolicyDecision(
            decision=decision,
            risk_score=risk_score,
            risk_level=risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level),
            violating_rules=violating_rules,
            suggestion=suggestion,
            reason=reason,
            audit_id=audit_id if audit_id > 0 else None,
        )
