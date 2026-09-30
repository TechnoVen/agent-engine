"""core/patch/models.py

Data models, enums, hashing primitives, and audit records for Safe Staged Patch Application.
Part of Milestone R2 Task R2.10.

Invariants (CTO Review Sections 10-22):
1. Never overwrite newer human edits: Agent Engine must never overwrite a newer human edit
   merely because an older AI-generated patch was previously valid.
2. Canonical PatchOperation: Explicitly captures expected state (exists + content_hash) and
   proposed state (content_hash + content reference) with exact approval digest binding.
3. Cryptographic byte hashing: SHA-256 over exact file bytes on disk without normalization
   (no whitespace, encoding, or line-ending tampering).
4. Absence vs Empty: An absent file (exists=False, hash=None) is distinct from an empty file
   (exists=True, hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855").
5. Pre-commit revalidation: Target file state is re-verified immediately before atomic commit.
6. Durable crash recovery: Journal and backup persisted before mutation.
7. Audit-safe ledger: Hashes and references only; no full file bodies or secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from pathlib import Path
import time
from typing import Any, Dict, Optional
import uuid


class PatchOperationType(str, Enum):
    """Supported atomic patch operations."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class PatchConflictReason(str, Enum):
    """Canonical reasons for rejecting or aborting a patch proposal."""

    STALE_PATCH = "stale_patch"
    TARGET_EXISTS = "target_exists"
    TARGET_ABSENT = "target_absent"
    APPROVAL_MISMATCH = "approval_mismatch"
    CONTAINMENT_VIOLATION = "containment_violation"
    HASH_VERIFICATION_FAILED = "hash_verification_failed"
    RECOVERY_REQUIRED = "recovery_required"
    INTERNAL_ERROR = "internal_error"


class PatchJournalState(str, Enum):
    """Lifecycle states of a patch journal entry during atomic staging and recovery."""

    PREPARED = "prepared"
    APPLYING = "applying"
    COMMITTED = "committed"
    ABORTED = "aborted"
    RECOVERY_REQUIRED = "recovery_required"


def compute_content_hash(data: bytes) -> str:
    """Compute exact SHA-256 hash over raw file bytes.

    Invariants:
    - Never normalizes line endings (LF vs CRLF).
    - Never trims whitespace or alters Unicode encoding.
    """
    return hashlib.sha256(data).hexdigest()


def compute_file_hash(path: Path) -> Optional[str]:
    """Compute exact SHA-256 hash of an existing file on disk.

    Returns None if the file does not exist (Absence is distinct from empty file).
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_patch_approval_digest(
    project_id: str,
    canonical_relative_path: str,
    operation_type: PatchOperationType,
    expected_content_hash: Optional[str],
    proposed_content_hash: Optional[str],
) -> str:
    """Compute exact cryptographic approval digest binding patch parameters.

    Invariants (CTO Review Section 13):
    An approval token binds project, target path, operation type, expected original
    hash, and proposed content hash. Changing any parameter invalidates the approval.
    """
    raw = (
        f"patch_approval:{project_id}:"
        f"{canonical_relative_path}:"
        f"{operation_type.value}:"
        f"{expected_content_hash or 'ABSENT'}:"
        f"{proposed_content_hash or 'ABSENT'}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_patch_operation_id() -> str:
    """Generate a unique patch operation identifier."""
    return f"patch-{uuid.uuid4().hex[:12]}"


@dataclass
class PatchOperation:
    """Canonical representation of an untrusted proposed patch operation (CTO Review Section 10)."""

    operation_id: str
    project_id: str
    operation_type: PatchOperationType
    canonical_relative_path: Path
    expected_exists: bool
    expected_content_hash: Optional[str] = None
    proposed_content: Optional[bytes] = None
    proposed_content_hash: Optional[str] = None
    proposed_content_artifact_id: Optional[str] = None
    approval_id: Optional[str] = None
    approval_digest: Optional[str] = None

    def __post_init__(self) -> None:
        self.canonical_relative_path = Path(self.canonical_relative_path)
        if self.canonical_relative_path.is_absolute():
            raise ValueError(
                f"Patch canonical_relative_path must be relative, got: {self.canonical_relative_path}"
            )

        # Enforce Section 10 absence vs empty semantics
        if not self.expected_exists and self.expected_content_hash is not None:
            raise ValueError(
                "When expected_exists is False (ABSENT), expected_content_hash must be None."
            )
        if self.expected_exists and self.expected_content_hash is None:
            raise ValueError(
                "When expected_exists is True, expected_content_hash must be explicitly declared."
            )

        # Automatically compute proposed_content_hash from proposed_content if not provided
        if self.proposed_content is not None and self.proposed_content_hash is None:
            self.proposed_content_hash = compute_content_hash(self.proposed_content)

        if self.operation_type == PatchOperationType.DELETE:
            if self.proposed_content is not None or self.proposed_content_hash is not None:
                raise ValueError("DELETE operation must not declare proposed content or hash.")
        elif self.operation_type in (PatchOperationType.CREATE, PatchOperationType.UPDATE):
            if self.proposed_content is None and self.proposed_content_artifact_id is None:
                raise ValueError(
                    f"{self.operation_type.value.upper()} operation requires proposed_content or proposed_content_artifact_id."
                )


@dataclass
class PatchResult:
    """Outcome of attempting to apply a staged patch operation."""

    operation_id: str
    project_id: str
    canonical_relative_path: str
    operation_type: PatchOperationType
    success: bool
    conflict_reason: Optional[PatchConflictReason] = None
    message: str = ""
    initial_hash: Optional[str] = None
    resulting_hash: Optional[str] = None
    backup_id: Optional[str] = None
    journal_id: Optional[str] = None
    duration_seconds: float = 0.0

    @property
    def is_conflict(self) -> bool:
        return not self.success and self.conflict_reason is not None


@dataclass
class PatchJournalEntry:
    """Durable crash recovery journal entry (CTO Review Section 16 & 18)."""

    operation_id: str
    project_id: str
    canonical_relative_path: str
    operation_type: str
    expected_exists: bool
    expected_content_hash: Optional[str]
    proposed_content_hash: Optional[str]
    backup_path: Optional[str] = None
    staged_path: Optional[str] = None
    target_path: Optional[str] = None
    state: PatchJournalState = PatchJournalState.PREPARED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "project_id": self.project_id,
            "canonical_relative_path": self.canonical_relative_path,
            "operation_type": self.operation_type,
            "expected_exists": self.expected_exists,
            "expected_content_hash": self.expected_content_hash,
            "proposed_content_hash": self.proposed_content_hash,
            "backup_path": self.backup_path,
            "staged_path": self.staged_path,
            "target_path": self.target_path,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PatchJournalEntry:
        return cls(
            operation_id=data["operation_id"],
            project_id=data["project_id"],
            canonical_relative_path=data["canonical_relative_path"],
            operation_type=data["operation_type"],
            expected_exists=data["expected_exists"],
            expected_content_hash=data.get("expected_content_hash"),
            proposed_content_hash=data.get("proposed_content_hash"),
            backup_path=data.get("backup_path"),
            staged_path=data.get("staged_path"),
            target_path=data.get("target_path"),
            state=PatchJournalState(data.get("state", PatchJournalState.PREPARED.value)),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class PatchExecutionRecord:
    """Audit ledger evidence record for patch application (CTO Review Section 22).

    Guarantees: Hashes and references only; no full file contents or secrets.
    """

    operation_id: str
    project_id: str
    canonical_relative_path: str
    operation_type: str
    expected_content_hash: Optional[str]
    resulting_hash: Optional[str]
    approval_id: Optional[str]
    success: bool
    conflict_reason: Optional[str]
    journal_state: str
    duration_seconds: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "project_id": self.project_id,
            "canonical_relative_path": self.canonical_relative_path,
            "operation_type": self.operation_type,
            "expected_content_hash": self.expected_content_hash,
            "resulting_hash": self.resulting_hash,
            "approval_id": self.approval_id,
            "success": self.success,
            "conflict_reason": self.conflict_reason,
            "journal_state": self.journal_state,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
        }
