"""core/model_download/models.py

Domain models and state machine for Agent Engine Managed Model Download and Verification.
Part of Milestone R3 Task R3.6 (Managed Model Download and Verification).

Invariants:
1. Catalog-Driven: Downloads originate from vetted ModelArtifactDescriptor specifications.
2. Explicit State Machine: NOT_PRESENT -> DOWNLOADING -> PAUSED/PARTIAL -> VERIFYING -> VERIFIED / FAILED.
3. Fail-Closed Integrity: Only artifacts with matching SHA-256 are ever marked VERIFIED.
4. Non-Destructive Resumability: Paused or interrupted downloads preserve verifiable partial progress.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Optional

from pydantic import BaseModel, Field

from core.model_registry.models import ModelIdentity


class DownloadState(str, Enum):
    """Lifecycle states for managed model artifact downloads."""

    NOT_PRESENT = "not_present"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"


class ModelArtifactDescriptor(BaseModel):
    """Authoritative catalog specification for a downloadable model artifact."""

    artifact_id: str  # e.g., "llama-3.2-1b-instruct-q4_k_m.gguf"
    model_identity: ModelIdentity
    source_url: str
    expected_size_bytes: int
    expected_sha256: str
    expected_etag: Optional[str] = None
    expected_xet_hash: Optional[str] = None
    format: str = "gguf"
    quantization: str = "Q4_K_M"
    provenance: str = "curated_catalog"
    catalog_version: str = "2026.10.1"


class DownloadStatus(BaseModel):
    """Runtime snapshot of an artifact's download and verification status."""

    artifact_id: str
    model_identity: Optional[ModelIdentity] = None
    state: DownloadState = DownloadState.NOT_PRESENT
    bytes_downloaded: int = 0
    total_bytes_expected: int = 0
    progress_ratio: float = 0.0  # [0.0, 1.0]
    etag: Optional[str] = None
    expected_sha256: str = ""
    observed_sha256: Optional[str] = None
    error_message: Optional[str] = None
    partial_present: bool = False
    resumable: bool = False
    file_path: Optional[str] = None
    started_at: Optional[float] = None
    updated_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    verified_at: Optional[float] = None
    catalog_version: str = "2026.10.1"
