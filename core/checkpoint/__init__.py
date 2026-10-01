"""core/checkpoint

Checkpoint and Rollback Service package.
Part of Milestone R2 Task R2.11.
"""

from core.checkpoint.backends import (
    BaseCheckpointBackend,
    ConfigCheckpointBackend,
    DatabaseCheckpointBackend,
    FileCheckpointBackend,
    GitCheckpointBackend,
)
from core.checkpoint.models import (
    Checkpoint,
    CheckpointCreationError,
    CheckpointError,
    CheckpointExecutionRecord,
    CheckpointNotFoundError,
    CheckpointResource,
    CheckpointResourceType,
    CheckpointStatus,
    ResourceRestoreResult,
    ResourceRestoreStatus,
    RestorePlan,
    RestoreResult,
    RestoreStatus,
    RestoreVerificationError,
    RollbackConflictError,
    UnsupportedDatabaseBackendError,
    compute_rollback_approval_digest,
    generate_checkpoint_id,
    generate_restore_id,
)
from core.checkpoint.service import CheckpointService

__all__ = [
    "Checkpoint",
    "CheckpointCreationError",
    "CheckpointError",
    "CheckpointExecutionRecord",
    "CheckpointNotFoundError",
    "CheckpointResource",
    "CheckpointResourceType",
    "CheckpointStatus",
    "ResourceRestoreResult",
    "ResourceRestoreStatus",
    "RestorePlan",
    "RestoreResult",
    "RestoreStatus",
    "RestoreVerificationError",
    "RollbackConflictError",
    "UnsupportedDatabaseBackendError",
    "compute_rollback_approval_digest",
    "generate_checkpoint_id",
    "generate_restore_id",
    "CheckpointService",
    "BaseCheckpointBackend",
    "FileCheckpointBackend",
    "GitCheckpointBackend",
    "DatabaseCheckpointBackend",
    "ConfigCheckpointBackend",
]
