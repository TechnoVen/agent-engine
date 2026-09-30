"""core/patch/__init__.py

Safe Staged Patch Application Subsystem.
Part of Milestone R2 Task R2.10.
"""

from core.patch.models import (
    PatchConflictReason,
    PatchExecutionRecord,
    PatchJournalEntry,
    PatchJournalState,
    PatchOperation,
    PatchOperationType,
    PatchResult,
    compute_content_hash,
    compute_file_hash,
    compute_patch_approval_digest,
    generate_patch_operation_id,
)
from core.patch.service import PatchLockManager, PatchService

__all__ = [
    "PatchConflictReason",
    "PatchExecutionRecord",
    "PatchJournalEntry",
    "PatchJournalState",
    "PatchLockManager",
    "PatchOperation",
    "PatchOperationType",
    "PatchResult",
    "PatchService",
    "compute_content_hash",
    "compute_file_hash",
    "compute_patch_approval_digest",
    "generate_patch_operation_id",
]
