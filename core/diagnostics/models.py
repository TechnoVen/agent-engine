"""core/diagnostics/models.py

Data models for Agent Engine Diagnostics subsystem.
Part of Milestone R2 Task R2.12 (Diagnostics Redaction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Any, Dict, List, Optional


class EgressClassification(str, Enum):
    """Classification of diagnostic and operational data egress surfaces (CTO Review Item 8)."""

    INTERNAL_ONLY = "INTERNAL_ONLY"
    SHAREABLE_REDACTED = "SHAREABLE_REDACTED"
    NOT_EXPORTABLE = "NOT_EXPORTABLE"


@dataclass
class RedactionReport:
    """Telemetry report recording redaction actions taken at egress boundary."""

    redactions_count: int = 0
    paths_minimized_count: int = 0
    preserved_references: List[str] = field(default_factory=list)
    references_minimized_count: int = 0
    redacted_patterns: Dict[str, int] = field(default_factory=dict)
    canaries_scrubbed_count: int = 0
    unserializable_objects_omitted: int = 0
    recursion_depth_exceeded_count: int = 0
    bytes_truncated_count: int = 0

    def record_redaction(self, category: str = "generic") -> None:
        self.redactions_count += 1
        self.redacted_patterns[category] = self.redacted_patterns.get(category, 0) + 1

    def record_path_minimization(self) -> None:
        self.paths_minimized_count += 1

    def record_preserved_reference(self, ref_str: str) -> None:
        self.preserved_references.append(ref_str)

    def record_reference_minimized(self) -> None:
        self.references_minimized_count += 1
        self.record_redaction("secret_reference_minimized")

    def record_canary(self) -> None:
        self.canaries_scrubbed_count += 1
        self.record_redaction("seeded_canary")

    def record_unserializable_object(self) -> None:
        self.unserializable_objects_omitted += 1
        self.record_redaction("unserializable_object")

    def record_recursion_limit(self) -> None:
        self.recursion_depth_exceeded_count += 1
        self.record_redaction("recursion_depth_exceeded")

    def record_truncation(self) -> None:
        self.bytes_truncated_count += 1
        self.record_redaction("string_length_truncated")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "redactions_count": self.redactions_count,
            "paths_minimized_count": self.paths_minimized_count,
            "preserved_references": self.preserved_references,
            "references_minimized_count": self.references_minimized_count,
            "redacted_patterns": self.redacted_patterns,
            "canaries_scrubbed_count": self.canaries_scrubbed_count,
            "unserializable_objects_omitted": self.unserializable_objects_omitted,
            "recursion_depth_exceeded_count": self.recursion_depth_exceeded_count,
            "bytes_truncated_count": self.bytes_truncated_count,
        }


@dataclass
class ExportManifest:
    """Verifiable integrity manifest for an exported diagnostic bundle (CTO Review Item 6).

    Note: Provides integrity metadata over canonical members, not signer authenticity (R2.13).
    Acyclic scheme: Hashes each exported member file independently and excludes manifest itself.
    """

    bundle_id: str
    created_at: float = field(default_factory=time.time)
    export_format_version: int = 1
    redaction_policy_version: int = 1
    format: str = "zip"
    hash_algorithm: str = "sha256"
    hash_scope: str = "canonical_exported_members"
    files: List[str] = field(default_factory=list)
    member_hashes: Dict[str, str] = field(default_factory=dict)
    sections_included: List[str] = field(default_factory=list)
    sections_omitted: List[str] = field(default_factory=list)
    total_bytes: int = 0
    sha256_hash: str = ""
    redaction_summary: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def verify_member_integrity(self, bundle_members: Dict[str, bytes]) -> bool:
        """Verify the integrity of decompressed archive members against the manifest.

        Ensures:
        1. All members declared in member_hashes match their sha256 checksums exactly.
        2. manifest.json itself is excluded from member_hashes (acyclic integrity).
        """
        if "manifest.json" in self.member_hashes:
            return False
        for fname, expected_hash in self.member_hashes.items():
            if fname not in bundle_members:
                return False
            actual_hash = hashlib.sha256(bundle_members[fname]).hexdigest()
            if actual_hash != expected_hash:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "created_at": self.created_at,
            "export_format_version": self.export_format_version,
            "redaction_policy_version": self.redaction_policy_version,
            "format": self.format,
            "hash_algorithm": self.hash_algorithm,
            "hash_scope": self.hash_scope,
            "files": self.files,
            "member_hashes": self.member_hashes,
            "sections_included": self.sections_included,
            "sections_omitted": self.sections_omitted,
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
