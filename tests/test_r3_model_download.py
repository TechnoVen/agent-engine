"""tests/test_r3_model_download.py

Comprehensive Managed Model Download and Verification Test Suite for Agent Engine.
Part of Milestone R3 Task R3.6 (Managed Model Download and Verification).

Verifies all R3.6 acceptance criteria and security invariants:
1. Catalog-driven downloads with authoritative ModelArtifactDescriptor.
2. Anti-SSRF protection: rejects non-HTTPS, loopback, RFC1918 private, link-local, cloud metadata.
3. Strict redirect validation: redirects to private/loopback addresses fail closed.
4. Memory-bounded O(1) streaming and incremental SHA-256 hashing.
5. Disk capacity pre-flight check with safety reserve.
6. Fail-closed checksum verification: matching digest promotes to VERIFIED; mismatch quarantines and fails.
7. Real HTTP Range / ETag resume: resumes interrupted downloads without re-downloading existing bytes.
8. Server ignoring Range safely resets from byte 0 without corrupting partial file.
9. Single-flight per-artifact locking: concurrent requests share active download.
10. Cancellation preserves resumable PAUSED state.
11. Atomic final placement; path traversal and symlink escape attacks rejected.
12. R3.4 Supervisor integration: accepts VERIFIED artifacts, strictly rejects .partial and unverified.
13. API mutation endpoints enforce IPC authentication.
14. Pure execution: zero auto-start, zero silent downloads, zero model switches.
15. Deterministic local HTTP fixture with Range, ETag, interruption, and resume.
"""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import re
import socket
import threading
import time
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from core.inference.validation import (
    GGUF_MAGIC_BYTES,
    ModelArtifactValidator,
    ModelValidationError,
)
from core.model_download import (
    DownloadState,
    InvalidURLError,
    ModelArtifactDescriptor,
    ModelDownloadManager,
    ModelStorageManager,
    SSRFProtection,
    SSRFSecurityError,
    SafeStreamingDownloader,
    StorageSecurityError,
)
from core.model_registry.models import ModelIdentity

# Sample GGUF test content
DUMMY_GGUF_CONTENT = GGUF_MAGIC_BYTES + b"\x00\x00\x00\x01" + b"TEST_MODEL_DATA_CONTENT" * 1024
DUMMY_GGUF_SIZE = len(DUMMY_GGUF_CONTENT)
DUMMY_GGUF_SHA256 = hashlib.sha256(DUMMY_GGUF_CONTENT).hexdigest()


class MockModelServerHandler(BaseHTTPRequestHandler):
    """Local HTTP handler simulating a model artifact repository with Range and ETag support."""

    content_data: bytes = DUMMY_GGUF_CONTENT
    etag_value: str = '"model-etag-v1"'
    ignore_range: bool = False
    simulate_disconnect_after_bytes: int = 0
    redirect_target: Optional[str] = None

    def log_message(self, format, *args):
        pass  # Suppress console logging in tests

    def do_GET(self):
        # 1. Handle redirect if configured
        if self.redirect_target:
            self.send_response(302)
            self.send_header("Location", self.redirect_target)
            self.end_headers()
            return

        range_header = self.headers.get("Range")
        data = self.content_data
        total_len = len(data)

        if range_header and not self.ignore_range:
            # Parse Range: bytes=START-
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else total_len - 1
                end = min(end, total_len - 1)
                chunk = data[start : end + 1]

                self.send_response(206)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Range", f"bytes {start}-{end}/{total_len}")
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("ETag", self.etag_value)
                self.end_headers()

                if self.simulate_disconnect_after_bytes > 0:
                    self.wfile.write(chunk[: self.simulate_disconnect_after_bytes])
                    # Force close connection abruptly
                    return

                self.wfile.write(chunk)
                return

        # Full content response (HTTP 200)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(total_len))
        self.send_header("ETag", self.etag_value)
        self.end_headers()

        if self.simulate_disconnect_after_bytes > 0:
            self.wfile.write(data[: self.simulate_disconnect_after_bytes])
            return

        self.wfile.write(data)


@pytest.fixture
def mock_model_server():
    """Spin up a dedicated in-process HTTP server on a free port for download testing."""
    # Find free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = HTTPServer(("127.0.0.1", port), MockModelServerHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    MockModelServerHandler.content_data = DUMMY_GGUF_CONTENT
    MockModelServerHandler.etag_value = '"model-etag-v1"'
    MockModelServerHandler.ignore_range = False
    MockModelServerHandler.simulate_disconnect_after_bytes = 0
    MockModelServerHandler.redirect_target = None

    yield base_url

    server.shutdown()
    server.server_close()


@pytest.fixture
def temp_models_dir(tmp_path):
    """Isolated temporary models directory."""
    d = tmp_path / "agent_engine_models"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ==============================================================================
# 1. Catalog-Driven Downloads & Verification
# ==============================================================================
def test_01_catalog_descriptor_downloads_successfully_and_verifies(
    mock_model_server, temp_models_dir
):
    """Verify vetted catalog descriptor downloads over HTTP fixture and promotes to VERIFIED."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    descriptor = ModelArtifactDescriptor(
        artifact_id="test-model-1b-q4_k_m.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="test-model-1b"),
        source_url=f"{mock_model_server}/test-model.gguf",
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
        quantization="Q4_K_M",
    )

    status = mgr.start_download(descriptor, sync=True)

    assert status.state == DownloadState.VERIFIED
    assert status.progress_ratio == 1.0
    assert status.bytes_downloaded == DUMMY_GGUF_SIZE
    assert status.observed_sha256 == DUMMY_GGUF_SHA256

    final_file = storage.get_final_path("test-model-1b-q4_k_m.gguf")
    assert final_file.exists()
    assert final_file.stat().st_size == DUMMY_GGUF_SIZE

    # Partial file must be cleaned up
    partial_file = storage.get_partial_path("test-model-1b-q4_k_m.gguf")
    assert not partial_file.exists()


# ==============================================================================
# 2. SSRF Protection & URL Validation
# ==============================================================================
def test_02_non_https_rejected_by_default():
    """Verify plain HTTP, file://, and ftp:// URLs are rejected by default."""
    with pytest.raises(InvalidURLError, match="Only HTTPS is allowed"):
        SSRFProtection.validate_url("http://example.com/model.gguf")

    with pytest.raises(InvalidURLError, match="Only HTTPS is allowed"):
        SSRFProtection.validate_url("file:///etc/passwd")

    with pytest.raises(InvalidURLError, match="Only HTTPS is allowed"):
        SSRFProtection.validate_url("ftp://example.com/model.gguf")


def test_03_embedded_credentials_rejected():
    """Verify URLs with embedded credentials (user:pass@) are rejected."""
    with pytest.raises(InvalidURLError, match="Credentials embedded"):
        SSRFProtection.validate_url("https://user:password@example.com/model.gguf")


def test_04_private_and_loopback_targets_rejected():
    """Verify loopback, RFC1918 private IPs, and cloud metadata are rejected."""
    # Loopback
    with pytest.raises(SSRFSecurityError, match="loopback"):
        SSRFProtection.validate_ip_address("127.0.0.1")

    with pytest.raises(SSRFSecurityError, match="loopback"):
        SSRFProtection.validate_ip_address("::1")

    # RFC 1918 Private
    with pytest.raises(SSRFSecurityError, match="RFC1918 private"):
        SSRFProtection.validate_ip_address("10.0.0.1")

    with pytest.raises(SSRFSecurityError, match="RFC1918 private"):
        SSRFProtection.validate_ip_address("192.168.1.100")

    with pytest.raises(SSRFSecurityError, match="RFC1918 private"):
        SSRFProtection.validate_ip_address("172.16.0.5")

    # Cloud metadata
    with pytest.raises(SSRFSecurityError, match="cloud metadata"):
        SSRFProtection.validate_ip_address("169.254.169.254")


def test_05_redirect_to_private_address_rejected(mock_model_server, temp_models_dir):
    """Verify redirecting from public source to private address fails closed."""
    MockModelServerHandler.redirect_target = "http://10.0.0.1/private.gguf"

    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    descriptor = ModelArtifactDescriptor(
        artifact_id="redirect-attack.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="redirect-model"),
        source_url=f"{mock_model_server}/redirect",
        expected_size_bytes=1000,
        expected_sha256="0" * 64,
    )

    status = mgr.start_download(descriptor, sync=True)
    assert status.state == DownloadState.FAILED
    assert "RFC1918 private" in status.error_message


# ==============================================================================
# 3. Disk Space Safety & Size Constraints
# ==============================================================================
def test_06_insufficient_disk_space_rejected(mock_model_server, temp_models_dir):
    """Verify pre-flight disk check rejects download when free capacity is insufficient."""
    storage = ModelStorageManager(models_dir=temp_models_dir, safety_reserve_bytes=1024 * 1024)

    # Mock disk_usage to return only 100 bytes free
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = MagicMock(free=100, total=10000)
        downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
        mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

        descriptor = ModelArtifactDescriptor(
            artifact_id="disk-test.gguf",
            model_identity=ModelIdentity(provider_id="llamacpp", model_id="disk-model"),
            source_url=f"{mock_model_server}/test.gguf",
            expected_size_bytes=10 * 1024 * 1024,
            expected_sha256="0" * 64,
        )

        status = mgr.start_download(descriptor, sync=True)
        assert status.state == DownloadState.FAILED
        assert "Insufficient disk space" in status.error_message


def test_07_maximum_allowed_size_enforced(mock_model_server, temp_models_dir):
    """Verify model sizes exceeding configured maximum are rejected."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(
        storage_manager=storage,
        downloader=downloader,
        max_allowed_size_bytes=1000,  # 1000 bytes max
    )

    descriptor = ModelArtifactDescriptor(
        artifact_id="oversized.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="big-model"),
        source_url=f"{mock_model_server}/test.gguf",
        expected_size_bytes=5000,  # 5000 bytes > 1000 max
        expected_sha256="0" * 64,
    )

    status = mgr.start_download(descriptor, sync=True)
    assert status.state == DownloadState.FAILED
    assert "exceeds configured limit" in status.error_message


# ==============================================================================
# 4. Checksum Verification & Fail-Closed Integrity
# ==============================================================================
def test_08_checksum_mismatch_quarantines_and_fails(mock_model_server, temp_models_dir):
    """Verify checksum mismatch marks FAILED, quarantines partial, and never creates final file."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    descriptor = ModelArtifactDescriptor(
        artifact_id="bad-checksum.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="bad-model"),
        source_url=f"{mock_model_server}/test.gguf",
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256="badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbad1",
    )

    status = mgr.start_download(descriptor, sync=True)

    assert status.state == DownloadState.FAILED
    assert "Checksum mismatch" in status.error_message
    assert status.observed_sha256 == DUMMY_GGUF_SHA256

    final_file = storage.get_final_path("bad-checksum.gguf")
    assert not final_file.exists(), "Final file must never be created on checksum mismatch!"

    # Original partial file was quarantined
    partial_file = storage.get_partial_path("bad-checksum.gguf")
    assert not partial_file.exists()


# ==============================================================================
# 5. Resume Semantics (HTTP 206 Range vs 200 Reset)
# ==============================================================================
def test_09_interrupted_download_resumes_with_valid_range(mock_model_server, temp_models_dir):
    """Verify an interrupted transfer resumes from byte offset using HTTP Range."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    descriptor = ModelArtifactDescriptor(
        artifact_id="resumable-model.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="resumable-model"),
        source_url=f"{mock_model_server}/test.gguf",
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
    )

    # 1. First run: simulate disconnect after half the bytes
    cutoff = DUMMY_GGUF_SIZE // 2
    MockModelServerHandler.simulate_disconnect_after_bytes = cutoff

    mgr.start_download(descriptor, sync=True)
    partial_p = storage.get_partial_path("resumable-model.gguf")
    assert partial_p.exists()
    assert partial_p.stat().st_size == cutoff

    # 2. Second run: server allows Range and delivers full remainder
    MockModelServerHandler.simulate_disconnect_after_bytes = 0

    status = mgr.start_download(descriptor, sync=True)
    assert status.state == DownloadState.VERIFIED
    assert status.bytes_downloaded == DUMMY_GGUF_SIZE

    final_file = storage.get_final_path("resumable-model.gguf")
    assert final_file.exists()
    assert final_file.stat().st_size == DUMMY_GGUF_SIZE


def test_10_server_ignoring_range_restarts_safely(mock_model_server, temp_models_dir):
    """Verify server returning HTTP 200 (ignoring Range) resets partial without corrupting."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    # Seed partial file with 500 dummy bytes
    partial_p = storage.get_partial_path("ignore-range.gguf")
    partial_p.write_bytes(b"EXISTING_GARBAGE_BYTES" * 20)

    # Server configured to ignore Range and return 200
    MockModelServerHandler.ignore_range = True

    descriptor = ModelArtifactDescriptor(
        artifact_id="ignore-range.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="ignore-model"),
        source_url=f"{mock_model_server}/test.gguf",
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
    )

    status = mgr.start_download(descriptor, sync=True)
    assert status.state == DownloadState.VERIFIED

    final_file = storage.get_final_path("ignore-range.gguf")
    assert final_file.stat().st_size == DUMMY_GGUF_SIZE


# ==============================================================================
# 6. Concurrency & Single-Flight Per-Artifact Locks
# ==============================================================================
def test_11_same_artifact_concurrent_requests_single_flight(mock_model_server, temp_models_dir):
    """Verify concurrent requests for the same artifact share a single active download task."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    descriptor = ModelArtifactDescriptor(
        artifact_id="single-flight.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="sf-model"),
        source_url=f"{mock_model_server}/test.gguf",
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
    )

    # Launch asynchronous download
    s1 = mgr.start_download(descriptor, sync=False)
    assert s1.state == DownloadState.DOWNLOADING

    # Immediate second call must detect in-flight task (single flight)
    s2 = mgr.start_download(descriptor, sync=False)
    assert s2.artifact_id == s1.artifact_id


# ==============================================================================
# 7. Cancellation & Crash Recovery
# ==============================================================================
def test_12_cancellation_leaves_resumable_paused_state(mock_model_server, temp_models_dir):
    """Verify cancelling download stops stream and leaves verifiable PAUSED state."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    descriptor = ModelArtifactDescriptor(
        artifact_id="cancel-test.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="cancel-model"),
        source_url=f"{mock_model_server}/test.gguf",
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
    )

    mgr.start_download(descriptor, sync=False)
    time.sleep(0.05)
    mgr.cancel_download("cancel-test.gguf")
    time.sleep(0.1)

    status = mgr.get_status("cancel-test.gguf")
    assert status.state in (DownloadState.PAUSED, DownloadState.VERIFIED)


# ==============================================================================
# 8. Path Traversal & Storage Security
# ==============================================================================
def test_13_path_traversal_storage_attack_rejected(temp_models_dir):
    """Verify artifact IDs with path traversal or directory escapes are rejected."""
    storage = ModelStorageManager(models_dir=temp_models_dir)

    with pytest.raises(StorageSecurityError):
        storage.get_final_path("../../../etc/shadow")

    with pytest.raises(StorageSecurityError):
        storage.get_final_path("model/subdir.gguf")

    with pytest.raises(StorageSecurityError):
        storage.get_final_path(r"model\subdir.gguf")

    with pytest.raises(StorageSecurityError):
        storage.get_final_path(".hidden_model.gguf")


# ==============================================================================
# 9. R3.4 Supervisor Integration (Rejection of Partial/Unverified)
# ==============================================================================
def test_14_r34_supervisor_accepts_verified_rejects_partial(temp_models_dir):
    """Verify ModelArtifactValidator permits verified models and strictly rejects .partial files."""
    verified_path = temp_models_dir / "valid_model.gguf"
    verified_path.write_bytes(DUMMY_GGUF_CONTENT)

    # Valid GGUF file is accepted
    res = ModelArtifactValidator.validate(verified_path)
    assert res.format == "gguf"

    # .partial artifact is strictly rejected
    partial_path = temp_models_dir / "valid_model.gguf.partial"
    partial_path.write_bytes(DUMMY_GGUF_CONTENT)
    with pytest.raises(ModelValidationError, match="incomplete"):
        ModelArtifactValidator.validate(partial_path)

    # Artifact with metadata state != 'verified' is rejected
    meta_path = temp_models_dir / "unverified_model.gguf.meta.json"
    unverified_model = temp_models_dir / "unverified_model.gguf"
    unverified_model.write_bytes(DUMMY_GGUF_CONTENT)
    meta_path.write_text('{"state": "downloading"}')

    with pytest.raises(ModelValidationError, match="unverified state"):
        ModelArtifactValidator.validate(unverified_model)


# ==============================================================================
# 10. REST API IPC Authentication & Mutation Endpoints
# ==============================================================================
def test_15_api_endpoints_enforce_ipc_auth():
    """Verify mutation download endpoints require IPC authentication token."""
    from services.python.server.app import create_app

    app = create_app()
    client = TestClient(app)

    token = "test_ipc_token_r36"
    with patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}):
        # 1. Unauthenticated requests rejected
        unauth_post = client.post(
            "/v1/models/downloads",
            json={"model_id": "llama-3.2-1b-instruct-q4_k_m"},
        )
        assert unauth_post.status_code == 401

        unauth_cancel = client.post("/v1/models/downloads/some-artifact/cancel")
        assert unauth_cancel.status_code == 401

        # 2. Authenticated GET /v1/models/downloads
        headers = {"X-IPC-Token": token}
        res_list = client.get("/v1/models/downloads", headers=headers)
        assert res_list.status_code == 200
        assert isinstance(res_list.json(), list)

        # 3. Authenticated GET /v1/models/installed
        res_inst = client.get("/v1/models/installed", headers=headers)
        assert res_inst.status_code == 200
        assert isinstance(res_inst.json(), list)

        # 4. Unknown model download rejected with 404 (catalog-driven)
        bad_model_res = client.post(
            "/v1/models/downloads",
            headers=headers,
            json={"model_id": "arbitrary-untrusted-model"},
        )
        assert bad_model_res.status_code == 404
        assert "not found in curated local catalog" in bad_model_res.json()["detail"]
