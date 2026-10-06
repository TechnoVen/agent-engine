"""core/diagnostics/redactor.py

Multi-layer redaction engine for Agent Engine diagnostics exports.
Part of Milestone R2 Task R2.12.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Optional, Tuple

from core.diagnostics.models import RedactionReport
from core.diagnostics.policy import RedactionPolicy
from core.security.secrets import SecretReference, SecretValue
from core.storage.paths import get_private_data_dir


class DiagnosticsRedactor:
    """Recursively redacts sensitive data, minimizing paths and preserving identifiers at egress boundary."""

    def __init__(
        self,
        policy: Optional[RedactionPolicy] = None,
        project_root: Optional[Path | str] = None,
        home_dir: Optional[Path | str] = None,
        data_dir: Optional[Path | str] = None,
    ) -> None:
        self.policy = policy or RedactionPolicy()
        self.project_root = Path(project_root).resolve() if project_root else None
        self.home_dir = Path(home_dir).resolve() if home_dir else Path.home().resolve()
        self.data_dir = Path(data_dir).resolve() if data_dir else get_private_data_dir().resolve()
        self.temp_dir = Path(tempfile.gettempdir()).resolve()

    def redact(self, data: Any) -> Tuple[Any, RedactionReport]:
        """Redact arbitrary structured or text data, returning transformed data and report."""
        report = RedactionReport()
        redacted_data = self._redact_recursive(data, report)
        return redacted_data, report

    def redact_text(self, text: str, report: Optional[RedactionReport] = None) -> str:
        """Sanitize text by applying path minimization and token regex heuristics."""
        rep = report if report is not None else RedactionReport()
        return self._redact_string(text, rep)

    def redact_env(
        self, env_dict: Dict[str, str], report: Optional[RedactionReport] = None
    ) -> Dict[str, str]:
        """Scrub environment variables dictionary according to allowlist (Closure Item 15)."""
        rep = report if report is not None else RedactionReport()
        sanitized: Dict[str, str] = {}
        for k, v in env_dict.items():
            if k in self.policy.allowed_env_vars:
                sanitized[k] = self.redact_text(str(v), rep)
            else:
                rep.record_redaction("disallowed_env_var")
        return sanitized

    def _redact_recursive(self, obj: Any, report: RedactionReport) -> Any:
        # Layer 1: Structural Value Objects
        if isinstance(obj, SecretValue):
            report.record_redaction("secret_value_omitted")
            return "[REDACTED_SECRET_VALUE]"

        if isinstance(obj, SecretReference):
            ref_dict = {
                "provider": obj.provider,
                "name": obj.name,
                "scope": obj.scope,
                "project_id": obj.project_id,
            }
            report.record_preserved_reference(str(obj))
            return {"secret_reference": ref_dict}

        # Check for SecretReference-like dictionary
        if isinstance(obj, dict):
            # Check if dict represents SecretReference
            if ("secret_id" in obj and "provider" in obj) or (
                "provider" in obj and "name" in obj and "scope" in obj and len(obj) <= 5
            ):
                report.record_preserved_reference(str(obj.get("secret_id") or obj.get("name")))
                # Safe public metadata preserved, but values sanitized
                return {k: self._redact_recursive(v, report) for k, v in obj.items()}

            sanitized_dict: Dict[str, Any] = {}
            for k, v in obj.items():
                k_str = str(k)
                k_lower = k_str.lower()

                # Layer 1: Structural value objects take priority
                if isinstance(v, (SecretValue, SecretReference)):
                    sanitized_dict[k_str] = self._redact_recursive(v, report)
                # Layer 2: Key-based & Header scrubbing
                elif k_lower in self.policy.sensitive_headers:
                    report.record_redaction("sensitive_header")
                    sanitized_dict[k_str] = self.policy.default_placeholder
                elif any(sk in k_lower for sk in self.policy.sensitive_keys):
                    if isinstance(v, dict):
                        sanitized_dict[k_str] = self._redact_recursive(v, report)
                    else:
                        report.record_redaction("sensitive_key")
                        sanitized_dict[k_str] = self.policy.default_placeholder if v else None
                else:
                    sanitized_dict[k_str] = self._redact_recursive(v, report)

            return sanitized_dict

        if isinstance(obj, list):
            return [self._redact_recursive(item, report) for item in obj]

        if isinstance(obj, tuple):
            return tuple(self._redact_recursive(item, report) for item in obj)

        if isinstance(obj, set):
            return [self._redact_recursive(item, report) for item in sorted(list(obj), key=str)]

        if isinstance(obj, str):
            # Layer 4: String scrubbing (Path minimization + Regex heuristics)
            return self._redact_string(obj, report)

        if isinstance(obj, (int, float, bool)) or obj is None:
            return obj

        if isinstance(obj, Path):
            return self._minimize_path(str(obj), report)

        # Dataclass handling
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return self._redact_recursive(dataclasses.asdict(obj), report)

        # Check for safe to_dict()
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            try:
                d = obj.to_dict()
                if isinstance(d, dict):
                    return self._redact_recursive(d, report)
            except Exception:
                pass

        # Layer 16 Safe Object Serialization (Unknown/unserializable objects)
        # Invariant: Unknown objects serialized WITHOUT invoking repr() indiscriminately
        report.record_redaction("unserializable_object")
        return {"<unserializable_type>": type(obj).__name__}

    def _minimize_path(self, path_str: str, report: RedactionReport) -> str:
        """Minimizes absolute host paths to standardized placeholders (Closure Item 17)."""
        original = path_str
        res = path_str

        # Order: Most specific to least specific
        if self.data_dir and str(self.data_dir) in res:
            res = res.replace(str(self.data_dir), "<DATA_DIR>")
        if self.project_root and str(self.project_root) in res:
            res = res.replace(str(self.project_root), "<PROJECT>")
        if self.temp_dir and str(self.temp_dir) in res:
            res = res.replace(str(self.temp_dir), "<TEMP>")
        if self.home_dir and str(self.home_dir) in res:
            res = res.replace(str(self.home_dir), "<HOME>")

        if res != original:
            report.record_path_minimization()
        return res

    def _redact_string(self, text: str, report: RedactionReport) -> str:
        """Apply path minimization and heuristic regex patterns to string."""
        s = self._minimize_path(text, report)

        # Check for seeded canaries first
        if "canary-" in s:
            canary_pattern = re.compile(r"\bcanary-[a-zA-Z0-9_\-]{8,}\b")
            matches = canary_pattern.findall(s)
            if matches:
                for _ in matches:
                    report.record_canary()
                s = canary_pattern.sub(self.policy.default_placeholder, s)

        # Apply regex rules
        for rule_name, pattern, replacement in self.policy.regex_rules:
            if rule_name == "seeded_canary":
                continue  # already handled above
            matches = pattern.findall(s)
            if matches:
                for _ in matches:
                    report.record_redaction(rule_name)
                s = pattern.sub(replacement, s)

        return s
