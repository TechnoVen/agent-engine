"""core/diagnostics/redactor.py

Multi-layer redaction engine for Agent Engine diagnostics exports.
Part of Milestone R2 Task R2.12.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

from core.diagnostics.models import RedactionReport
from core.diagnostics.policy import RedactionPolicy
from core.security.secrets import SecretReference, SecretValue
from core.storage.paths import get_private_data_dir


class DiagnosticsRedactor:
    """Recursively redacts sensitive data, minimizing paths and preserving/minimizing identifiers at egress boundary."""

    def __init__(
        self,
        policy: Optional[RedactionPolicy] = None,
        project_root: Optional[Path | str] = None,
        home_dir: Optional[Path | str] = None,
        data_dir: Optional[Path | str] = None,
    ) -> None:
        self.policy = policy or RedactionPolicy()
        self.project_root_raw = str(project_root) if project_root else None
        try:
            self.project_root = Path(project_root).resolve() if project_root else None
        except Exception:
            self.project_root = None
        self.home_dir = Path(home_dir).resolve() if home_dir else Path.home().resolve()
        self.data_dir = Path(data_dir).resolve() if data_dir else get_private_data_dir().resolve()
        self.temp_dir = Path(tempfile.gettempdir()).resolve()

    def redact(self, data: Any) -> Tuple[Any, RedactionReport]:
        """Redact arbitrary structured or text data, returning transformed data and report."""
        report = RedactionReport()
        seen_ids: Set[int] = set()
        redacted_data = self._redact_recursive(data, report, depth=0, seen_ids=seen_ids)
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

    def _redact_recursive(
        self,
        obj: Any,
        report: RedactionReport,
        depth: int,
        seen_ids: Set[int],
    ) -> Any:
        # Layer 0: Depth & Cycle guards (CTO Review Items 9 & 10)
        if depth > self.policy.max_recursion_depth:
            report.record_recursion_limit()
            return {"<depth_limit_exceeded>": type(obj).__name__}

        # Handle primitive types immediately before cycle tracking
        if isinstance(obj, (int, float, bool)) or obj is None:
            return obj

        if isinstance(obj, str):
            # Check length bound
            if len(obj) > self.policy.max_string_length:
                report.record_truncation()
                obj = obj[: self.policy.max_string_length] + "...[TRUNCATED]"
            return self._redact_string(obj, report)

        if isinstance(obj, (bytes, bytearray)):
            try:
                decoded = obj.decode("utf-8")
                return self._redact_string(decoded, report)
            except Exception:
                return f"<binary_data:{len(obj)}_bytes>"

        if isinstance(obj, Path):
            return self._minimize_path(str(obj), report)

        # Cycle detection for compound structures
        obj_id = id(obj)
        if obj_id in seen_ids:
            return {"<recursion_cycle>": type(obj).__name__}

        # Add to seen set (for mutable compound containers)
        if isinstance(obj, (dict, list, tuple, set)) or hasattr(obj, "__dict__"):
            seen_ids = set(seen_ids)
            seen_ids.add(obj_id)

        # Layer 1: Structural Value Objects (SecretValue, SecretReference)
        if isinstance(obj, SecretValue):
            report.record_redaction("secret_value_omitted")
            return "[REDACTED_SECRET_VALUE]"

        if isinstance(obj, SecretReference):
            if self.policy.include_exact_secret_references:
                report.record_preserved_reference(str(obj))
                ref_dict = {
                    "provider": obj.provider,
                    "name": obj.name,
                    "scope": obj.scope,
                    "project_id": obj.project_id,
                }
                return {"secret_reference": ref_dict}
            else:
                # CTO Review Item 7: Minimize SecretReference in shareable diagnostics
                report.record_reference_minimized()
                return {
                    "credential_configured": True,
                    "provider": obj.provider,
                }

        # Check for SecretReference-like dictionary
        if isinstance(obj, dict):
            if ("secret_id" in obj and "provider" in obj) or (
                "provider" in obj and "name" in obj and "scope" in obj and len(obj) <= 5
            ):
                if not self.policy.include_exact_secret_references:
                    report.record_reference_minimized()
                    return {
                        "credential_configured": True,
                        "provider": str(obj.get("provider", "unknown")),
                    }
                else:
                    report.record_preserved_reference(str(obj.get("secret_id") or obj.get("name")))
                    return {
                        str(k): self._redact_recursive(v, report, depth + 1, seen_ids)
                        for k, v in obj.items()
                    }

            sanitized_dict: Dict[str, Any] = {}
            for k, v in obj.items():
                k_str = str(k)
                k_lower = k_str.lower()

                # Layer 1: Structural value objects take priority
                if isinstance(v, (SecretValue, SecretReference)):
                    sanitized_dict[k_str] = self._redact_recursive(v, report, depth + 1, seen_ids)
                # Layer 2: Key-based & Header scrubbing
                elif k_lower in self.policy.sensitive_headers:
                    report.record_redaction("sensitive_header")
                    sanitized_dict[k_str] = self.policy.default_placeholder
                elif any(sk in k_lower for sk in self.policy.sensitive_keys):
                    if isinstance(v, dict):
                        sanitized_dict[k_str] = self._redact_recursive(
                            v, report, depth + 1, seen_ids
                        )
                    else:
                        report.record_redaction("sensitive_key")
                        sanitized_dict[k_str] = self.policy.default_placeholder if v else None
                else:
                    sanitized_dict[k_str] = self._redact_recursive(v, report, depth + 1, seen_ids)

            return sanitized_dict

        if isinstance(obj, list):
            return [self._redact_recursive(item, report, depth + 1, seen_ids) for item in obj]

        if isinstance(obj, tuple):
            return tuple(self._redact_recursive(item, report, depth + 1, seen_ids) for item in obj)

        if isinstance(obj, set):
            # Sort safely
            items = list(obj)
            try:
                sorted_items = sorted(items, key=lambda x: str(type(x).__name__))
            except Exception:
                sorted_items = items
            return [
                self._redact_recursive(item, report, depth + 1, seen_ids) for item in sorted_items
            ]

        # Dataclass handling
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            try:
                return self._redact_recursive(dataclasses.asdict(obj), report, depth + 1, seen_ids)
            except Exception:
                pass

        # Check for safe to_dict()
        if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict", None)):
            try:
                d = obj.to_dict()
                if isinstance(d, dict):
                    return self._redact_recursive(d, report, depth + 1, seen_ids)
            except Exception:
                pass

        # CTO Review Item 9: NEVER call repr(obj), str(obj), or json.dumps(obj, default=str)!
        # A malicious custom object could embed secrets in __repr__ or __str__.
        report.record_unserializable_object()
        return {"<unserializable_type>": type(obj).__name__}

    def _minimize_path(self, path_str: str, report: RedactionReport) -> str:
        """Minimizes absolute host paths to standardized placeholders (CTO Review Item 11).

        Applies known-root mapping before generic path heuristics.
        Covers both POSIX and Windows path structures, while protecting URLs from corruption.
        """
        original = path_str
        res = path_str

        def get_variants(root_val: Any) -> List[str]:
            if not root_val:
                return []
            raw_s = str(root_val)
            v = {raw_s, raw_s.replace("\\", "/"), raw_s.replace("/", "\\")}
            if isinstance(root_val, Path):
                try:
                    res_s = str(root_val.resolve())
                    v.add(res_s)
                    v.add(res_s.replace("\\", "/"))
                    v.add(res_s.replace("/", "\\"))
                except Exception:
                    pass
            return [x for x in sorted(v, key=len, reverse=True) if len(x) > 2]

        known_roots = [
            (self.data_dir, "<DATA_DIR>"),
            (self.project_root_raw or self.project_root, "<PROJECT>"),
            (self.temp_dir, "<TEMP>"),
            (self.home_dir, "<HOME>"),
        ]

        for root_val, placeholder in known_roots:
            variants = get_variants(root_val)
            for var in variants:
                if var in res:
                    res = res.replace(var, placeholder)

        if res != original:
            report.record_path_minimization()
        return res

    def _redact_string(self, text: str, report: RedactionReport) -> str:
        """Apply path minimization and heuristic regex patterns to string."""
        # Step 1: Known-root path minimization first (CTO Review Item 11)
        s = self._minimize_path(text, report)

        # Step 2: Seeded canary scrub
        if "canary-" in s:
            canary_pattern = re.compile(r"\bcanary-[a-zA-Z0-9_\-]{8,}\b")
            matches = canary_pattern.findall(s)
            if matches:
                for _ in matches:
                    report.record_canary()
                s = canary_pattern.sub(self.policy.default_placeholder, s)

        # Step 3: Regex pattern heuristics
        for rule_name, pattern, replacement in self.policy.regex_rules:
            if rule_name == "seeded_canary":
                continue
            matches = pattern.findall(s)
            if matches:
                for _ in matches:
                    report.record_redaction(rule_name)
                s = pattern.sub(replacement, s)

        return s
