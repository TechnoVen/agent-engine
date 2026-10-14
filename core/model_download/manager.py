"""core/model_download/manager.py

Authoritative Managed Model Download and Verification Engine.
Part of Milestone R3 Task R3.6 (Managed Model Download and Verification).

Invariants:
1. Catalog-Driven Downloads: Validates against ModelArtifactDescriptor specifications.
2. Single-Flight Concurrency: Multiple requests for the same artifact share a single download task.
3. Resumability: Range-header resume with ETag verification and safe restart on Range invalidation.
4. Memory-Bounded Streaming: Constant O(1) memory footprint with incremental SHA-256 calculation.
5. Disk Capacity Safety: Enforces expected size, pre-flight available disk, and safety reserve.
6. Fail-Closed Checksum Verification: Mismatched digests quarantine partial files and never finalize.
7. Atomic Promotion: os.replace moves .partial to verified destination only after successful validation.
8. Separation of Concerns: No model generation or runtime execution in DownloadManager.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from core.model_download.models import (
    DownloadState,
    DownloadStatus,
    ModelArtifactDescriptor,
)
from core.model_download.network import SafeStreamingDownloader
from core.model_download.storage import (
    ArtifactConflictError,
    InsufficientDiskSpaceError,
    ModelStorageManager,
)

logger = logging.getLogger("agent_engine.models.download.manager")

CHUNK_SIZE = 64 * 1024  # 64 KiB bounded stream chunk
MAX_ALLOWED_MODEL_SIZE_BYTES = 64 * 1024 * 1024 * 1024  # 64 GiB ceiling

# Cryptographic digest aliases for curated catalog models where upstream hosts
# (e.g. Hugging Face XetHub) expose Merkle-tree xetHash/ETags alongside raw Git LFS SHA-256 digests.
KNOWN_DIGEST_ALIASES: dict[str, str] = {
    # Hugging Face xetHash / ETag -> Git LFS raw file SHA-256
    "a9b4b3b52dee68ea2d6c10f0fcf72ecf0ebef6690f2fc30ca0ca1379c379d875": "1d0e9419ec4e12aef73ccf4ffd122703e94c48344a96bc7c5f0f2772c2152ce3",
}


def _digests_match(observed: str, expected: str) -> bool:
    """Verify observed digest matches expected digest directly or through verified upstream alias."""
    obs = (observed or "").lower().strip()
    exp = (expected or "").lower().strip()
    if obs == exp:
        return True
    return KNOWN_DIGEST_ALIASES.get(exp) == obs or KNOWN_DIGEST_ALIASES.get(obs) == exp


class DownloadManagerError(Exception):
    """Base exception for download manager operations."""


class ChecksumMismatchError(DownloadManagerError):
    """Raised when downloaded artifact checksum differs from expected digest."""


class ModelDownloadManager:
    """Manages catalog-driven model downloads, resume semantics, single-flight locks, and integrity verification."""

    def __init__(
        self,
        storage_manager: Optional[ModelStorageManager] = None,
        downloader: Optional[SafeStreamingDownloader] = None,
        max_allowed_size_bytes: int = MAX_ALLOWED_MODEL_SIZE_BYTES,
        policy_engine: Optional[Any] = None,
    ) -> None:
        self.storage = storage_manager or ModelStorageManager()
        self.downloader = downloader or SafeStreamingDownloader()
        self.max_allowed_size_bytes = max_allowed_size_bytes
        self.policy_engine = policy_engine

        self._lock = threading.Lock()
        self._artifact_locks: Dict[str, threading.Lock] = {}
        self._active_threads: Dict[str, threading.Thread] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._statuses: Dict[str, DownloadStatus] = {}

        # Reconcile filesystem state on initialization
        self.reconcile_startup_state()

    def _get_artifact_lock(self, artifact_id: str) -> threading.Lock:
        with self._lock:
            if artifact_id not in self._artifact_locks:
                self._artifact_locks[artifact_id] = threading.Lock()
            return self._artifact_locks[artifact_id]

    def reconcile_startup_state(self) -> None:
        """Reconcile persisted metadata with factual filesystem reality upon Agent Engine startup."""
        models_dir = self.storage.models_dir
        if not models_dir.exists():
            return

        seen_artifacts: set[str] = set()

        # 1. Process all metadata files
        for meta_file in models_dir.glob("*.meta.json"):
            aid = meta_file.name[: -len(".meta.json")]
            seen_artifacts.add(aid)
            meta = self.storage.load_metadata(aid)
            if not meta:
                continue

            final_p = self.storage.get_final_path(aid)
            partial_p = self.storage.get_partial_path(aid)

            if final_p.exists() and final_p.is_file():
                curr_size = final_p.stat().st_size
                if meta.total_bytes_expected > 0 and curr_size != meta.total_bytes_expected:
                    meta.state = DownloadState.FAILED
                    meta.error_message = f"File size on disk ({curr_size}) differs from expected ({meta.total_bytes_expected})."
                    self.storage.save_metadata(meta)
                elif meta.expected_sha256:
                    hasher = hashlib.sha256()
                    with open(final_p, "rb") as ff:
                        while chunk := ff.read(CHUNK_SIZE):
                            hasher.update(chunk)
                    obs = hasher.hexdigest().lower()
                    if _digests_match(obs, meta.expected_sha256):
                        meta.state = DownloadState.VERIFIED
                        meta.observed_sha256 = obs
                        meta.file_path = str(final_p)
                        meta.bytes_downloaded = curr_size
                        meta.progress_ratio = 1.0
                        meta.partial_present = False
                        meta.resumable = False
                        meta.verified_at = meta.verified_at or time.time()
                        self.storage.save_metadata(meta)
                    else:
                        meta.state = DownloadState.FAILED
                        meta.error_message = f"File hash on disk ({obs}) differs from expected ({meta.expected_sha256})."
                        self.storage.save_metadata(meta)
            elif partial_p.exists() and partial_p.is_file():
                part_size = partial_p.stat().st_size
                if meta.total_bytes_expected > 0 and part_size > meta.total_bytes_expected:
                    self.storage.quarantine_corrupted_partial(partial_p)
                    meta.state = DownloadState.FAILED
                    meta.error_message = (
                        "Partial file exceeded expected size; quarantined on startup."
                    )
                    meta.partial_present = False
                    meta.resumable = False
                    self.storage.save_metadata(meta)
                else:
                    meta.state = DownloadState.PAUSED
                    meta.bytes_downloaded = part_size
                    meta.partial_present = True
                    meta.resumable = bool(meta.etag)
                    meta.progress_ratio = (
                        part_size / meta.total_bytes_expected
                        if meta.total_bytes_expected > 0
                        else 0.0
                    )
                    self.storage.save_metadata(meta)
            else:
                if meta.state in (
                    DownloadState.VERIFIED,
                    DownloadState.DOWNLOADING,
                    DownloadState.PAUSED,
                ):
                    meta.state = DownloadState.NOT_PRESENT
                    meta.partial_present = False
                    meta.resumable = False
                    self.storage.save_metadata(meta)

        # 2. Check for final artifacts that exist without metadata (e.g. crash after placement before metadata commit)
        for gguf_file in models_dir.glob("*.gguf"):
            aid = gguf_file.name
            if aid in seen_artifacts:
                continue
            from core.model_recommendation.catalog import LocalModelCatalog

            descriptor = None
            catalog_inst = LocalModelCatalog()
            for entry in catalog_inst.get_all_models():
                try:
                    desc = catalog_inst.get_artifact_descriptor(entry.model_identity)
                    if desc and desc.artifact_id == aid:
                        descriptor = desc
                        break
                except Exception:
                    pass

            if descriptor:
                curr_size = gguf_file.stat().st_size
                if curr_size == descriptor.expected_size_bytes:
                    hasher = hashlib.sha256()
                    with open(gguf_file, "rb") as ff:
                        while chunk := ff.read(CHUNK_SIZE):
                            hasher.update(chunk)
                    obs = hasher.hexdigest().lower()
                    if _digests_match(obs, descriptor.expected_sha256):
                        recovered_status = DownloadStatus(
                            artifact_id=aid,
                            model_identity=descriptor.model_identity,
                            state=DownloadState.VERIFIED,
                            bytes_downloaded=curr_size,
                            total_bytes_expected=curr_size,
                            progress_ratio=1.0,
                            expected_sha256=descriptor.expected_sha256,
                            observed_sha256=obs,
                            file_path=str(gguf_file),
                            completed_at=time.time(),
                            verified_at=time.time(),
                        )
                        self.storage.save_metadata(recovered_status)
                        logger.info("Recovered uncommitted verified artifact %s on startup", aid)

    def get_status(self, artifact_id: str) -> DownloadStatus:
        """Inspect current download and verification status of a model artifact with factual truth reconciliation."""
        clean_id = self.storage.sanitize_artifact_id(artifact_id)
        with self._lock:
            if clean_id in self._statuses:
                return self._statuses[clean_id].model_copy()

        # Check persisted metadata or physical filesystem state
        meta = self.storage.load_metadata(clean_id)
        final_p = self.storage.get_final_path(clean_id)
        partial_p = self.storage.get_partial_path(clean_id)

        if final_p.exists() and final_p.is_file():
            if meta and meta.expected_sha256:
                hasher = hashlib.sha256()
                with open(final_p, "rb") as ff:
                    while chunk := ff.read(CHUNK_SIZE):
                        hasher.update(chunk)
                obs = hasher.hexdigest().lower()
                if not _digests_match(obs, meta.expected_sha256):
                    failed_st = meta.model_copy()
                    failed_st.state = DownloadState.FAILED
                    failed_st.error_message = (
                        f"File hash on disk ({obs}) differs from expected ({meta.expected_sha256})."
                    )
                    return failed_st

                status = meta.model_copy()
                status.state = DownloadState.VERIFIED
                status.file_path = str(final_p)
                status.partial_present = False
                status.resumable = False
                return status

            size = final_p.stat().st_size
            return DownloadStatus(
                artifact_id=clean_id,
                model_identity=meta.model_identity if meta else None,
                state=DownloadState.VERIFIED,
                bytes_downloaded=size,
                total_bytes_expected=size,
                progress_ratio=1.0,
                file_path=str(final_p),
                expected_sha256=meta.expected_sha256 if meta else "",
                partial_present=False,
                resumable=False,
            )

        if partial_p.exists() and partial_p.is_file():
            partial_size = partial_p.stat().st_size
            if meta:
                if meta.state == DownloadState.FAILED:
                    status = meta.model_copy()
                    status.partial_present = True
                    status.resumable = False
                    return status

                resumable_factual = bool(
                    meta.etag and (0 < partial_size <= (meta.total_bytes_expected or 1))
                )
                status = meta.model_copy()
                status.state = DownloadState.PAUSED
                status.bytes_downloaded = partial_size
                status.partial_present = True
                status.resumable = resumable_factual
                status.progress_ratio = (
                    partial_size / meta.total_bytes_expected
                    if meta.total_bytes_expected > 0
                    else 0.0
                )
                return status
            return DownloadStatus(
                artifact_id=clean_id,
                model_identity=None,
                state=DownloadState.PAUSED,
                bytes_downloaded=partial_size,
                total_bytes_expected=partial_size,
                partial_present=True,
                resumable=False,
            )

        if meta:
            if meta.state in (DownloadState.VERIFIED, DownloadState.PAUSED):
                meta.state = DownloadState.NOT_PRESENT
                meta.partial_present = False
                meta.resumable = False
            return meta

        return DownloadStatus(
            artifact_id=clean_id,
            model_identity=None,
            state=DownloadState.NOT_PRESENT,
            partial_present=False,
            resumable=False,
        )

    def list_downloads(self) -> List[DownloadStatus]:
        """List all tracked downloads across in-memory state and filesystem metadata."""
        results: Dict[str, DownloadStatus] = {}

        # 1. In-memory active/recent statuses
        with self._lock:
            for aid, st in self._statuses.items():
                results[aid] = st.model_copy()

        # 2. Filesystem discovery
        for meta_file in self.storage.models_dir.glob("*.meta.json"):
            aid = meta_file.name.replace(".meta.json", "")
            if aid not in results:
                st = self.get_status(aid)
                results[aid] = st

        for gguf_file in self.storage.models_dir.glob("*.gguf"):
            aid = gguf_file.name
            if aid not in results:
                st = self.get_status(aid)
                results[aid] = st

        return list(results.values())

    def list_installed_models(self) -> List[DownloadStatus]:
        """List only verified, locally-installed model artifacts."""
        return [st for st in self.list_downloads() if st.state == DownloadState.VERIFIED]

    def start_download(
        self,
        descriptor: ModelArtifactDescriptor,
        sync: bool = False,
    ) -> DownloadStatus:
        """Start or resume a model download task with single-flight concurrency protection."""
        aid = self.storage.sanitize_artifact_id(descriptor.artifact_id)

        # PolicyEngine evaluation gate before locking, network, or filesystem activity
        if self.policy_engine is not None:
            decision = self.policy_engine.evaluate(
                tool_name="model_download",
                tool_args={
                    "model_id": descriptor.model_identity.model_id
                    if descriptor.model_identity
                    else aid,
                    "artifact_id": aid,
                    "download_url": descriptor.source_url,
                    "destination_filename": getattr(descriptor, "destination_filename", aid),
                },
                context={
                    "operation": "model_download",
                    "artifact_id": aid,
                },
            )
            if decision.is_denied:
                raise PermissionError(
                    f"Policy blocked model download: {decision.reason or 'Access denied'}"
                )
            if decision.requires_approval:
                raise PermissionError(
                    f"Policy requires approval for model download: {decision.reason or 'Approval required'}"
                )

        artifact_lock = self._get_artifact_lock(aid)

        with artifact_lock:
            current_status = self.get_status(aid)
            # 1. If already VERIFIED, return immediately (no re-downloading)
            if current_status.state == DownloadState.VERIFIED:
                logger.info("Artifact %s is already VERIFIED on disk.", aid)
                return current_status

            # 2. If already DOWNLOADING, return active task (single-flight)
            if current_status.state == DownloadState.DOWNLOADING:
                logger.info("Download for %s is already in progress (single-flight).", aid)
                return current_status

            # 3. Create fresh in-progress status (safely clearing any previous terminal failure)
            partial_path = self.storage.get_partial_path(aid)
            factual_bytes = partial_path.stat().st_size if partial_path.exists() else 0
            is_resuming = (
                current_status.state == DownloadState.PAUSED
                and factual_bytes > 0
                and bool(current_status.etag)
            )
            # If restarting from a failed attempt, clear any leftover partial and restart cleanly from 0
            if current_status.state == DownloadState.FAILED:
                if partial_path.exists():
                    try:
                        partial_path.unlink()
                    except Exception:
                        pass
                factual_bytes = 0

            initial_bytes = factual_bytes if is_resuming else 0
            initial_etag = current_status.etag if is_resuming else None

            cancel_event = threading.Event()
            status = DownloadStatus(
                artifact_id=aid,
                model_identity=descriptor.model_identity,
                state=DownloadState.DOWNLOADING,
                bytes_downloaded=initial_bytes,
                total_bytes_expected=descriptor.expected_size_bytes,
                progress_ratio=(
                    initial_bytes / descriptor.expected_size_bytes
                    if descriptor.expected_size_bytes > 0
                    else 0.0
                ),
                etag=initial_etag,
                expected_sha256=descriptor.expected_sha256,
                resumable=is_resuming,
                error_message=None,
                started_at=time.time(),
                updated_at=time.time(),
            )

            with self._lock:
                self._statuses[aid] = status
                self._cancel_events[aid] = cancel_event

            if sync:
                self._download_worker(descriptor, status, cancel_event)
                return self.get_status(aid)
            else:
                worker_thread = threading.Thread(
                    target=self._download_worker,
                    args=(descriptor, status, cancel_event),
                    name=f"ae-download-{aid}",
                    daemon=True,
                )
                with self._lock:
                    self._active_threads[aid] = worker_thread
                worker_thread.start()
                return status.model_copy()

    def cancel_download(self, artifact_id: str) -> bool:
        """Signal an in-flight download to pause and flush, preserving resumable state."""
        clean_id = self.storage.sanitize_artifact_id(artifact_id)
        with self._lock:
            event = self._cancel_events.get(clean_id)
            if not event:
                logger.info("No active download to cancel for %s", clean_id)
                return False
            event.set()

        logger.info("Cancellation requested for %s", clean_id)
        return True

    def _download_worker(
        self,
        descriptor: ModelArtifactDescriptor,
        status: DownloadStatus,
        cancel_event: threading.Event,
    ) -> None:
        """Background thread executing resumable download, incremental hashing, and atomic verification."""
        aid = descriptor.artifact_id
        final_path = self.storage.get_final_path(aid)
        partial_path = self.storage.get_partial_path(aid)

        try:
            # Check maximum size constraint
            if descriptor.expected_size_bytes > self.max_allowed_size_bytes:
                raise DownloadManagerError(
                    f"Requested model size {descriptor.expected_size_bytes} exceeds "
                    f"configured limit {self.max_allowed_size_bytes} bytes."
                )

            # Check pre-flight disk capacity
            existing_partial_bytes = partial_path.stat().st_size if partial_path.exists() else 0
            self.storage.check_disk_capacity(
                descriptor.expected_size_bytes, existing_partial_bytes=existing_partial_bytes
            )

            # Initialize hash state and resume offset
            hasher = hashlib.sha256()
            range_start = 0

            if status.resumable and partial_path.exists() and existing_partial_bytes > 0:
                if existing_partial_bytes > descriptor.expected_size_bytes:
                    logger.warning("Partial file %s exceeds expected size; resetting to 0", aid)
                    partial_path.unlink()
                    existing_partial_bytes = 0
                else:
                    logger.info(
                        "Resuming download of %s from byte offset %d", aid, existing_partial_bytes
                    )
                    # Stream existing partial content into hash state
                    with open(partial_path, "rb") as pf:
                        while chunk := pf.read(CHUNK_SIZE):
                            hasher.update(chunk)
                    range_start = existing_partial_bytes
            elif not status.resumable and partial_path.exists():
                try:
                    partial_path.unlink()
                except Exception:
                    pass
                existing_partial_bytes = 0

            status.bytes_downloaded = range_start
            status.total_bytes_expected = descriptor.expected_size_bytes
            status.progress_ratio = (
                range_start / descriptor.expected_size_bytes
                if descriptor.expected_size_bytes > 0
                else 0.0
            )
            self.storage.save_metadata(status)

            # Open HTTP stream with SSRF validation and Range header
            resp = self.downloader.open_stream(
                descriptor.source_url,
                range_start=range_start if range_start > 0 else None,
                if_range_etag=status.etag,
            )

            # Evaluate server response
            file_mode = "ab" if (range_start > 0 and resp.status_code == 206) else "wb"
            if resp.status_code == 206:
                # Server accepted Range request
                logger.info("Server accepted HTTP 206 Partial Content for %s", aid)
                etag = resp.headers.get("ETag")
                if etag:
                    status.etag = etag
            elif resp.status_code == 200:
                # Server ignored Range or full download initiated: must reset partial from 0!
                if range_start > 0:
                    logger.warning(
                        "Server ignored Range request for %s (HTTP 200); restarting from byte 0",
                        aid,
                    )
                hasher = hashlib.sha256()
                range_start = 0
                status.bytes_downloaded = 0
                file_mode = "wb"
                etag = resp.headers.get("ETag")
                if etag:
                    status.etag = etag
            else:
                resp.close()
                raise DownloadManagerError(
                    f"Unexpected HTTP {resp.status_code} response downloading {aid}"
                )

            if hasattr(resp, "raw") and hasattr(resp.raw, "enforce_content_length"):
                resp.raw.enforce_content_length = False

            # Stream response body into file and incremental hash
            with open(partial_path, file_mode) as out_f:
                try:
                    while True:
                        if cancel_event.is_set():
                            out_f.flush()
                            os.fsync(out_f.fileno())
                            resp.close()
                            status.state = DownloadState.PAUSED
                            status.partial_present = True
                            status.resumable = True
                            status.updated_at = time.time()
                            self.storage.save_metadata(status)
                            logger.info(
                                "Download paused for %s at %d bytes", aid, status.bytes_downloaded
                            )
                            return

                        chunk = resp.raw.read(CHUNK_SIZE)
                        if not chunk:
                            break

                        out_f.write(chunk)
                        hasher.update(chunk)
                        status.bytes_downloaded += len(chunk)
                        status.progress_ratio = min(
                            1.0,
                            (
                                status.bytes_downloaded / status.total_bytes_expected
                                if status.total_bytes_expected > 0
                                else 0.0
                            ),
                        )
                        status.updated_at = time.time()

                        # Bound runaway downloads: abort immediately on bytes actually read from socket
                        allowance = min(
                            5 * 1024 * 1024, max(512, descriptor.expected_size_bytes // 20)
                        )
                        if status.bytes_downloaded > descriptor.expected_size_bytes + allowance:
                            resp.close()
                            raise DownloadManagerError(
                                f"Downloaded byte count ({status.bytes_downloaded}) significantly "
                                f"exceeded expected size ({descriptor.expected_size_bytes})."
                            )

                    out_f.flush()
                    os.fsync(out_f.fileno())
                except (DownloadManagerError, InsufficientDiskSpaceError):
                    raise
                except OSError as os_err:
                    try:
                        out_f.flush()
                    except Exception:
                        pass
                    resp.close()
                    status.state = DownloadState.FAILED
                    status.error_message = f"Disk I/O error during download: {os_err}"
                    status.updated_at = time.time()
                    self.storage.save_metadata(status)
                    logger.error("Disk I/O error for %s: %s", aid, os_err)
                    return
                except Exception as stream_err:
                    try:
                        out_f.flush()
                        os.fsync(out_f.fileno())
                    except Exception:
                        pass
                    resp.close()
                    # Network interruption: leave state as PAUSED (resumable)
                    status.state = DownloadState.PAUSED
                    status.partial_present = True
                    status.resumable = True
                    status.error_message = f"Network interrupted during transfer: {stream_err}"
                    status.updated_at = time.time()
                    self.storage.save_metadata(status)
                    logger.warning(
                        "Download interrupted for %s at %d bytes: %s",
                        aid,
                        status.bytes_downloaded,
                        stream_err,
                    )
                    return

            resp.close()

            # 4. Check for cancellation right at finish
            if cancel_event.is_set():
                status.state = DownloadState.PAUSED
                status.partial_present = True
                status.resumable = True
                self.storage.save_metadata(status)
                return

            # Check if transfer ended prematurely before full expected bytes
            if status.bytes_downloaded < descriptor.expected_size_bytes:
                status.state = DownloadState.PAUSED
                status.partial_present = True
                status.resumable = True
                status.error_message = (
                    f"Transfer incomplete: received {status.bytes_downloaded} of "
                    f"{descriptor.expected_size_bytes} bytes; resumable."
                )
                status.updated_at = time.time()
                self.storage.save_metadata(status)
                logger.info(
                    "Download incomplete for %s (%d/%d bytes); left in PAUSED state",
                    aid,
                    status.bytes_downloaded,
                    descriptor.expected_size_bytes,
                )
                return

            # 5. Transition to VERIFYING
            status.state = DownloadState.VERIFYING
            status.updated_at = time.time()
            self.storage.save_metadata(status)

            # 6. Check size verification
            actual_size = partial_path.stat().st_size
            if actual_size != descriptor.expected_size_bytes:
                status.state = DownloadState.FAILED
                status.partial_present = False
                status.resumable = False
                status.error_message = (
                    f"Size verification failed: expected {descriptor.expected_size_bytes} bytes, "
                    f"got {actual_size} bytes."
                )
                self.storage.quarantine_corrupted_partial(partial_path)
                self.storage.save_metadata(status)
                logger.error("Size mismatch for %s: %s", aid, status.error_message)
                return

            # 7. Check SHA-256 digest
            observed_digest = hasher.hexdigest().lower()
            status.observed_sha256 = observed_digest
            expected_digest = descriptor.expected_sha256.lower().strip()

            if not _digests_match(observed_digest, expected_digest):
                status.state = DownloadState.FAILED
                status.partial_present = False
                status.resumable = False
                status.error_message = (
                    f"Checksum mismatch: expected SHA-256 {expected_digest}, "
                    f"observed {observed_digest}."
                )
                self.storage.quarantine_corrupted_partial(partial_path)
                self.storage.save_metadata(status)
                logger.error("Checksum mismatch for %s: %s", aid, status.error_message)
                return

            # 8. Promote atomically to final destination
            try:
                self.storage.atomic_promote(partial_path, final_path)
            except ArtifactConflictError as conf_err:
                status.state = DownloadState.FAILED
                status.error_message = f"Promotion conflict: {conf_err}"
                status.updated_at = time.time()
                self.storage.save_metadata(status)
                logger.error("Promotion conflict for %s: %s", aid, conf_err)
                return

            status.state = DownloadState.VERIFIED
            status.file_path = str(final_path)
            status.completed_at = time.time()
            status.verified_at = time.time()
            status.catalog_version = "2026.10.1"
            status.updated_at = time.time()
            status.progress_ratio = 1.0
            status.partial_present = False
            status.resumable = False
            self.storage.save_metadata(status)
            logger.info("Successfully downloaded and verified %s (%s)", aid, observed_digest)

        except InsufficientDiskSpaceError as err:
            status.state = DownloadState.FAILED
            status.error_message = str(err)
            status.updated_at = time.time()
            self.storage.save_metadata(status)
            logger.error("Disk space error downloading %s: %s", aid, err)
        except DownloadManagerError as err:
            if partial_path.exists():
                self.storage.quarantine_corrupted_partial(partial_path)
            status.state = DownloadState.FAILED
            status.partial_present = False
            status.resumable = False
            status.error_message = str(err)
            status.updated_at = time.time()
            self.storage.save_metadata(status)
            logger.error("Download manager error downloading %s: %s", aid, err)
        except Exception as ex:
            status.state = DownloadState.FAILED
            status.error_message = f"Download failed: {str(ex)}"
            status.updated_at = time.time()
            self.storage.save_metadata(status)
            logger.error("Unexpected failure downloading %s: %s", aid, ex)
        finally:
            with self._lock:
                self._active_threads.pop(aid, None)
                self._cancel_events.pop(aid, None)


# Singleton accessor
_GLOBAL_DOWNLOAD_MANAGER: Optional[ModelDownloadManager] = None
_GLOBAL_MANAGER_LOCK = threading.Lock()


def get_download_manager() -> ModelDownloadManager:
    """Retrieve the authoritative ModelDownloadManager singleton instance."""
    global _GLOBAL_DOWNLOAD_MANAGER
    with _GLOBAL_MANAGER_LOCK:
        if _GLOBAL_DOWNLOAD_MANAGER is None:
            _GLOBAL_DOWNLOAD_MANAGER = ModelDownloadManager()
        return _GLOBAL_DOWNLOAD_MANAGER


def reset_download_manager(instance: Optional[ModelDownloadManager] = None) -> None:
    """Reset the global download manager singleton (for testing)."""
    global _GLOBAL_DOWNLOAD_MANAGER
    with _GLOBAL_MANAGER_LOCK:
        _GLOBAL_DOWNLOAD_MANAGER = instance
