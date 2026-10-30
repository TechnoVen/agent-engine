"""core/model_download/__init__.py

Managed Model Download and Verification subsystem for Agent Engine.
Part of Milestone R3 Task R3.6 (Managed Model Download and Verification).
"""

from core.model_download.manager import (
    ChecksumMismatchError,
    DownloadManagerError,
    ModelDownloadManager,
    get_download_manager,
    reset_download_manager,
)
from core.model_download.models import (
    DownloadState,
    DownloadStatus,
    ModelArtifactDescriptor,
)
from core.model_download.network import (
    InvalidURLError,
    NetworkSecurityError,
    SafeStreamingDownloader,
    SSRFProtection,
    SSRFSecurityError,
)
from core.model_download.storage import (
    DEFAULT_MODELS_DIR,
    InsufficientDiskSpaceError,
    ModelStorageManager,
    StorageSecurityError,
)

__all__ = [
    # Models
    "DownloadState",
    "DownloadStatus",
    "ModelArtifactDescriptor",
    # Manager
    "ModelDownloadManager",
    "get_download_manager",
    "reset_download_manager",
    "DownloadManagerError",
    "ChecksumMismatchError",
    # Network
    "SSRFProtection",
    "SafeStreamingDownloader",
    "NetworkSecurityError",
    "SSRFSecurityError",
    "InvalidURLError",
    # Storage
    "ModelStorageManager",
    "DEFAULT_MODELS_DIR",
    "StorageSecurityError",
    "InsufficientDiskSpaceError",
]
