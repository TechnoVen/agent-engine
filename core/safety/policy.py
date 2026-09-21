import fnmatch
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
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
        # Direct exact or pattern match on tool_name itself
        if self.pattern.strip().lower() == tool_name.strip().lower():
            return True

        # Extract target text candidates from tool args and tool name
        args_values = [tool_name] + [str(v) for v in tool_args.values()]
        full_text = f"{tool_name} " + " ".join(str(v) for v in tool_args.values())

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


from core.skills.models import SkillPermission

# Canonical permission vocabulary re-export
Permission = SkillPermission


class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class PolicyDecision:
    """The authoritative result of evaluating a prospective tool call against active guardrails."""

    decision: str  # allow, block/deny, stage/require_approval
    risk_score: float  # 0.0 to 1.0
    risk_level: str  # low, medium, high, critical
    violating_rules: List[PolicyRule] = field(default_factory=list)
    suggestion: Optional[str] = None
    reason: Optional[str] = None
    audit_id: Optional[int] = None
    matched_rule: Optional[str] = None
    required_permissions: List[SkillPermission] = field(default_factory=list)

    @property
    def is_allowed(self) -> bool:
        return self.decision.lower() == "allow"

    @property
    def is_denied(self) -> bool:
        return self.decision.lower() in ("deny", "block")

    @property
    def requires_approval(self) -> bool:
        return self.decision.lower() in ("require_approval", "stage")

    @property
    def risk(self) -> str:
        return self.risk_level

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "risk_score": round(self.risk_score, 2),
            "risk_level": self.risk_level,
            "risk": self.risk_level,
            "matched_rule": self.matched_rule,
            "required_permissions": [
                p.value if hasattr(p, "value") else str(p) for p in self.required_permissions
            ],
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

    def get_yaml_content(self) -> str:
        """Retrieve raw policy YAML content from disk."""
        if os.path.exists(self.policy_file):
            try:
                with open(self.policy_file, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.error("Failed to read policy file %s: %s", self.policy_file, e)
                return ""
        return ""

    def update_yaml_content(self, content: str) -> Dict[str, Any]:
        """Validate, persist, and hot-reload policy rules from raw YAML content."""
        if not content or not content.strip():
            raise ValueError("Policy YAML content cannot be empty.")

        try:
            parsed = yaml.safe_load(content)
        except Exception as e:
            raise ValueError(f"Invalid YAML syntax: {e}")

        if not isinstance(parsed, dict):
            raise ValueError("YAML root must be a mapping/dictionary.")

        rules_raw = parsed.get("rules")
        if rules_raw is None or not isinstance(rules_raw, list):
            raise ValueError("Policy YAML must define a 'rules' list.")

        new_rules: Dict[str, PolicyRule] = {}
        for idx, r in enumerate(rules_raw):
            if not isinstance(r, dict):
                raise ValueError(f"Rule at index {idx} must be a dictionary.")
            if not r.get("id"):
                raise ValueError(f"Rule at index {idx} missing required 'id' field.")
            if not r.get("pattern"):
                raise ValueError(f"Rule '{r.get('id')}' missing required 'pattern' field.")

            # Validate regex pattern compilation if match_type is regex
            match_type = r.get("match_type", "regex")
            if match_type.lower() == "regex":
                try:
                    re.compile(r["pattern"])
                except re.error as err:
                    raise ValueError(f"Invalid regex in rule '{r['id']}': {err}")

            rule = PolicyRule(
                id=r["id"],
                name=r.get("name", r["id"]),
                description=r.get("description", ""),
                match_type=match_type,
                pattern=r["pattern"],
                action=r.get("action", "block"),
                risk_level=r.get("risk_level", "high"),
                reason=r.get("reason"),
                suggestion=r.get("suggestion"),
            )
            new_rules[rule.id] = rule

        # Persist to policy file
        os.makedirs(os.path.dirname(os.path.abspath(self.policy_file)), exist_ok=True)
        with open(self.policy_file, "w", encoding="utf-8") as f:
            f.write(content)

        # Hot reload in-memory rules
        self._rules = new_rules
        logger.info("Successfully hot-reloaded %d safety guardrail rules.", len(self._rules))

        return {
            "success": True,
            "rules_count": len(new_rules),
            "message": f"Successfully updated and hot-reloaded {len(new_rules)} safety rules.",
        }

    @staticmethod
    def infer_required_permissions(
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[SkillPermission]:
        """Infer canonical permissions required for the requested operation."""
        ctx = context or {}
        declared = ctx.get("declared_permissions")
        if declared:
            perms = []
            for p in declared:
                if isinstance(p, SkillPermission):
                    perms.append(p)
                elif isinstance(p, str):
                    try:
                        perms.append(SkillPermission(p.lower()))
                    except ValueError:
                        pass
            if perms:
                return perms

        t_lower = tool_name.lower()
        perms_set = set()

        # Check tool args and commandline
        all_text = (t_lower + " " + " ".join(str(v) for v in tool_args.values())).lower()

        if any(
            k in t_lower
            for k in (
                "bash",
                "shell",
                "exec",
                "terminal",
                "command",
                "run_command",
                "sql",
                "db",
                "admin",
            )
        ):
            perms_set.add(SkillPermission.EXECUTE)

        if any(
            k in t_lower for k in ("write", "edit", "create_file", "replace", "patch", "modify")
        ):
            perms_set.add(SkillPermission.WRITE_LOCAL)

        elif any(k in t_lower for k in ("read", "view", "list_dir", "cat", "search")):
            perms_set.add(SkillPermission.READ)

        elif any(k in t_lower for k in ("http", "fetch", "curl", "download", "network", "url")):
            perms_set.add(SkillPermission.NETWORK)

        elif any(k in t_lower for k in ("slack", "teams", "discord", "message", "chat")):
            perms_set.add(SkillPermission.COMMUNICATE)

        elif any(
            k in t_lower for k in ("pay", "billing", "credit", "subscription", "cost", "monetary")
        ):
            perms_set.add(SkillPermission.FINANCIAL)

        # Consequential permission inference: check all command arguments for dangerous/admin actions
        if any(
            danger in all_text
            for danger in (
                "rm -rf",
                "drop table",
                "drop database",
                "truncate ",
                "truncate table",
                "mkfs",
                "dd ",
                "format ",
            )
        ):
            perms_set.add(SkillPermission.DESTRUCTIVE)
            perms_set.add(SkillPermission.EXECUTE)

        if "admin" in t_lower or any(
            admin in all_text
            for admin in ("sudo ", "chmod 777", "systemctl", "apt ", "pacman", "dnf")
        ):
            perms_set.add(SkillPermission.ADMIN)
            perms_set.add(SkillPermission.EXECUTE)

        return sorted(list(perms_set), key=lambda p: p.value)

    def evaluate(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> PolicyDecision:
        """
        Authoritatively evaluate a prospective tool call against active guardrail policies.
        Enforces blocking rules, computes risk scores, applies Conflict C6 staging,
        infers canonical permissions, and fails closed upon any evaluation failure.
        """
        try:
            ctx = context or {}
            session_id = ctx.get("session_id")
            allow_high_risk = ctx.get("allow_high_risk", False)
            auto_apply = ctx.get("auto_apply", False)

            # 1. Infer required canonical permissions
            required_permissions = self.infer_required_permissions(tool_name, tool_args, context)

            # 2. Compute dynamic risk score
            risk_score, risk_level, _ = RiskScorer.score_tool_call(tool_name, tool_args)

            # 3. Check all active rules
            violating_rules: List[PolicyRule] = []
            for rule in self._rules.values():
                if rule.matches(tool_name, tool_args):
                    violating_rules.append(rule)

            # 4. Determine final decision
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
                reason = (
                    primary_rule.reason or f"Action blocked by policy rule '{primary_rule.name}'."
                )
                suggestion = primary_rule.suggestion
                primary_policy_id = primary_rule.id
                risk_score = max(risk_score, 0.90)
                risk_level = RiskLevel.CRITICAL
            elif staging_rules:
                decision = "stage"
                primary_rule = staging_rules[0]
                reason = (
                    primary_rule.reason
                    or f"Action requires staging per rule '{primary_rule.name}'."
                )
                suggestion = primary_rule.suggestion
                primary_policy_id = primary_rule.id
            elif any(
                p in (SkillPermission.DESTRUCTIVE, SkillPermission.FINANCIAL, SkillPermission.ADMIN)
                for p in required_permissions
            ) and not (allow_high_risk or auto_apply):
                # Consequential permissions require human approval by policy
                decision = "stage"
                primary_policy_id = "CONSEQUENTIAL_PERMISSION_GATE"
                consequential_names = [
                    p.value
                    for p in required_permissions
                    if p
                    in (
                        SkillPermission.DESTRUCTIVE,
                        SkillPermission.FINANCIAL,
                        SkillPermission.ADMIN,
                    )
                ]
                reason = f"Consequential operation requires human approval for permissions: {consequential_names}"
                suggestion = "Review and confirm consequential operation before execution."
            elif risk_score >= 0.70 and not (allow_high_risk or auto_apply):
                # Conflict Resolution C6: Staged by default for high risk
                decision = "stage"
                primary_policy_id = "C6_HIGH_RISK_STAGING"
                reason = (
                    f"Action staged by default due to high risk score ({risk_score:.2f} >= 0.70) "
                    "requiring explicit confirmation (Conflict C6)."
                )
                suggestion = "Review staged action parameters before manual approval."
            else:
                decision = "allow"
                reason = "Action complies with all active safety guardrails."

            # 5. Record event in persistent audit log (skip if dry run)
            audit_id = None
            if not dry_run:
                audit_id = self.audit_logger.log_evaluation(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    decision=decision,
                    risk_level=risk_level.value
                    if isinstance(risk_level, RiskLevel)
                    else str(risk_level),
                    risk_score=risk_score,
                    policy_id=primary_policy_id,
                    reason=reason,
                    suggestion=suggestion,
                    session_id=session_id,
                )

            return PolicyDecision(
                decision=decision,
                risk_score=risk_score,
                risk_level=risk_level.value
                if isinstance(risk_level, RiskLevel)
                else str(risk_level),
                violating_rules=violating_rules,
                suggestion=suggestion,
                reason=reason,
                audit_id=audit_id if (audit_id and audit_id > 0) else None,
                matched_rule=primary_policy_id,
                required_permissions=required_permissions,
            )
        except Exception as err:
            logger.error(
                "PolicyEngine evaluation error on tool '%s': %s (failing closed)", tool_name, err
            )
            # Fail closed: never allow consequential operations upon evaluation error
            return PolicyDecision(
                decision="block",
                risk_score=1.0,
                risk_level=RiskLevel.CRITICAL.value
                if isinstance(RiskLevel.CRITICAL, RiskLevel)
                else "critical",
                violating_rules=[],
                suggestion="Investigate policy evaluation error; execution blocked fail-closed.",
                reason=f"Policy evaluation failure: {err}. Action blocked fail-closed.",
                audit_id=None,
                matched_rule="POLICY_EVALUATION_ERROR_FAIL_CLOSED",
                required_permissions=[SkillPermission.EXECUTE],
            )
