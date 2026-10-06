"""core/diagnostics/models.py

Data models for Agent Engine Diagnostics subsystem.
Part of Milestone R2 Task R2.12 (Diagnostics Redaction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional


@dataclass
class RedactionReport:
    """Telemetry report recording redaction actions taken at egress boundary."""

    redactions_count: int = 0
    paths_minimized_count: int = 0
    preserved_references: List[str] = field(default_factory=list)
    redacted_patterns: Dict[str, int] = field(default_factory=dict)
    canaries_scrubbed_count: int = 0

    def record_redaction(self, category: str = "generic") -> None:
        self.redactions_count += 1
        self.redacted_patterns[category] = self.redacted_patterns.get(category, 0) + 1

    def record_path_minimization(self) -> None:
        self.paths_minimized_count += 1

    def record_preserved_reference(self, ref_str: str) -> None:
        self.preserved_references.append(ref_str)

    def record_canary(self) -> None:
        self.canaries_scrubbed_count += 1
        self.record_redaction("seeded_canary")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "redactions_count": self.redactions_count,
            "paths_minimized_count": self.paths_minimized_count,
            "preserved_references": self.preserved_references,
            "redacted_patterns": self.redacted_patterns,
            "canaries_scrubbed_count": self.canaries_scrubbed_count,
        }


@dataclass
class ExportManifest:
    """Cryptographically verifiable manifest for an exported diagnostic bundle."""

    bundle_id: str
    created_at: float = field(default_factory=time.time)
    format: str = "zip"
    files: List[str] = field(default_factory=list)
    total_bytes: int = 0
    sha256_hash: str = ""
    redaction_summary: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "created_at": self.created_at,
            "format": self.format,
            "files": self.files,
            "total_bytes": self.total_bytes,
            "sha256_hash": self.sha256_hash,
            "redaction_summary": self.redaction_summary,
            "metadata": self.metadata,
        }


@dataclass
class DiagnosticBundle:
    """Packaged bundle containing manifest and archive payload ready for export."""

    manifest: ExportManifest
    payload_bytes: bytes
    content_type: str
    filename: str
    redaction_report: Optional[RedactionReport] = None
