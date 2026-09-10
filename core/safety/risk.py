import re
from enum import Enum
from typing import Any, Dict, List, Tuple


class RiskLevel(str, Enum):
    """Risk tier classifications for tool execution."""

    LOW = "low"  # 0.0 - 0.29
    MEDIUM = "medium"  # 0.30 - 0.59
    HIGH = "high"  # 0.60 - 0.84
    CRITICAL = "critical"  # 0.85 - 1.00

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        if score >= 0.85:
            return cls.CRITICAL
        elif score >= 0.60:
            return cls.HIGH
        elif score >= 0.30:
            return cls.MEDIUM
        return cls.LOW


class RiskScorer:
    """
    Evaluates tool calls and parameters to calculate dynamic risk scores.
    Enforces safe defaults and staging thresholds (Conflict C6).
    """

    # Baseline risks for different tool categories
    TOOL_BASE_RISKS: Dict[str, float] = {
        # Read-only tools
        "read_file": 0.1,
        "view_file": 0.1,
        "list_files": 0.1,
        "list_dir": 0.1,
        "grep_search": 0.1,
        "read_url_content": 0.1,
        # Modification tools
        "write_to_file": 0.4,
        "replace_file_content": 0.4,
        "multi_replace_file_content": 0.45,
        "delete_file": 0.65,
        # Shell / execution tools
        "run_command": 0.5,
        "execute_command": 0.5,
        "bash": 0.5,
        # Database / system tools
        "sql_query": 0.45,
        "execute_sql": 0.5,
        "apply_patch": 0.55,
    }

    # High-risk string / regex heuristics
    SYSTEM_PATHS_PATTERN = re.compile(
        r"(?:/etc/|/usr/|/bin/|/sbin/|/boot/|/var/|/dev/|C:\\Windows|C:\\Program Files)",
        re.IGNORECASE,
    )
    PRODUCTION_KEYWORDS_PATTERN = re.compile(
        r"\b(?:production|prod|prod-[a-zA-Z0-9_-]+|live-cluster)\b",
        re.IGNORECASE,
    )
    CREDENTIAL_PATTERN = re.compile(
        r"(?:\.env|\.pem|\.key|id_rsa|id_ecdsa|\.aws/credentials|\.kube/config|api_key|password)",
        re.IGNORECASE,
    )
    PRIVILEGE_ESCALATION_PATTERN = re.compile(
        r"\b(?:sudo|su\s|chmod\s+[0-7]{3,4}|chown\s|setuid)\b",
        re.IGNORECASE,
    )
    DESTRUCTIVE_CMDS_PATTERN = re.compile(
        r"\b(?:rm\s+-[a-zA-Z]*r|mkfs|fdisk|dd\s+if=|drop\s+database|truncate\s+table|delete\s+from\s+[a-zA-Z0-9_]+\s*;)\b",
        re.IGNORECASE,
    )
    CLUSTER_DESTRUCTION_PATTERN = re.compile(
        r"\b(?:kubectl\s+delete|helm\s+uninstall|terraform\s+destroy)\b",
        re.IGNORECASE,
    )

    @classmethod
    def score_tool_call(
        cls, tool_name: str, tool_args: Dict[str, Any]
    ) -> Tuple[float, RiskLevel, List[str]]:
        """
        Calculate the risk score [0.0, 1.0] and RiskLevel for a tool call.
        Returns (score, level, list_of_risk_factors).
        """
        tool_clean = tool_name.lower().strip()
        score = cls.TOOL_BASE_RISKS.get(tool_clean, 0.3)
        factors: List[str] = [f"Base tool score for {tool_clean}: {score:.2f}"]

        # Flatten args to searchable string
        args_str = " ".join(str(v) for v in tool_args.values())

        # 1. Cluster / Infrastructure Deletion
        if cls.CLUSTER_DESTRUCTION_PATTERN.search(args_str):
            score += 0.4
            factors.append("Cluster destruction command detected (+0.40)")

        # 2. Destructive Commands
        if cls.DESTRUCTIVE_CMDS_PATTERN.search(args_str):
            score += 0.35
            factors.append("Destructive filesystem or database command detected (+0.35)")

        # 3. Production environment reference
        if cls.PRODUCTION_KEYWORDS_PATTERN.search(args_str):
            score += 0.25
            factors.append("Production environment target detected (+0.25)")

        # 4. Credential / Secret exposure
        if cls.CREDENTIAL_PATTERN.search(args_str):
            score += 0.3
            factors.append("Sensitive credential or secret key reference detected (+0.30)")

        # 5. System paths
        if cls.SYSTEM_PATHS_PATTERN.search(args_str):
            score += 0.25
            factors.append("System/OS directory path targeted (+0.25)")

        # 6. Privilege escalation
        if cls.PRIVILEGE_ESCALATION_PATTERN.search(args_str):
            score += 0.2
            factors.append("Privilege escalation pattern detected (+0.20)")

        # Clamp score between 0.0 and 1.0
        final_score = max(0.0, min(1.0, score))
        risk_level = RiskLevel.from_score(final_score)

        return round(final_score, 2), risk_level, factors
