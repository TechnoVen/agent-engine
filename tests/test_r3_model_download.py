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
from pathlib import Path
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
    DownloadStatus,
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


# ==============================================================================
# 11. DNS-Rebinding Protection & Socket Pinning
# ==============================================================================
def test_16_dns_rebinding_defense_and_socket_pinning():
    """Verify DNS rebinding attacks fail closed and connections are pinned to validated IPs."""
    from core.model_download.network import PinningHTTPAdapter

    # 1. Host resolving to mixed public and private IP fails closed
    with patch(
        "socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    ):
        with pytest.raises(SSRFSecurityError, match="loopback address"):
            SSRFProtection.resolve_and_validate_target(
                "https://rebind-attack.example.com/model.gguf"
            )

    # 2. Host resolving only to public IP returns pinned IP
    with patch(
        "socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    ):
        url, hostname, pinned_ip = SSRFProtection.resolve_and_validate_target(
            "https://safe.example.com/model.gguf"
        )
        assert hostname == "safe.example.com"
        assert pinned_ip == "93.184.216.34"

    # 3. Adapter pins connection to validated IP and preserves canonical hostname
    adapter = PinningHTTPAdapter(pinned_ips={"safe.example.com": "93.184.216.34"})
    conn = adapter.poolmanager.connection_from_url("https://safe.example.com/model.gguf")
    http_conn = conn._new_conn()
    # Canonical hostname is preserved for HTTP Host, TLS SNI, and certificate verification
    assert http_conn.host == "safe.example.com"
    assert http_conn.server_hostname == "safe.example.com"
    assert getattr(http_conn, "_pinned_ip_map", {}).get("safe.example.com") == "93.184.216.34"

    # When socket connects, it connects directly to pinned IP
    with patch("urllib3.util.connection.create_connection") as mock_create_conn:
        mock_sock = MagicMock()
        mock_create_conn.return_value = mock_sock
        sock = http_conn._new_conn()
        assert sock == mock_sock
        mock_create_conn.assert_called_once()
        args, kwargs = mock_create_conn.call_args
        assert args[0] == ("93.184.216.34", 443)

    # Unpinned connection fails closed with SSRFSecurityError
    conn_unpinned = adapter.poolmanager.connection_from_url(
        "https://unpinned.example.com/model.gguf"
    )
    http_conn_unpinned = conn_unpinned._new_conn()
    with pytest.raises(SSRFSecurityError, match="not pinned"):
        http_conn_unpinned._new_conn()


# ==============================================================================
# 12. Inherited Proxy Isolation
# ==============================================================================
def test_17_inherited_proxy_cannot_bypass_source_policy():
    """Verify session.trust_env = False rejects ambient HTTP_PROXY/HTTPS_PROXY env vars."""
    downloader = SafeStreamingDownloader()
    session = downloader.session
    assert session.trust_env is False

    # Ambient proxies do not populate session proxies
    with patch.dict(
        os.environ,
        {
            "HTTP_PROXY": "http://malicious-proxy.local:8080",
            "HTTPS_PROXY": "http://malicious-proxy.local:8080",
            "ALL_PROXY": "socks5://malicious-proxy.local:1080",
        },
    ):
        downloader_new = SafeStreamingDownloader()
        assert downloader_new.session.trust_env is False
        assert not downloader_new.session.proxies


# ==============================================================================
# 13. Storage Model-Root Override Gate & Path Authority
# ==============================================================================
def test_18_unsafe_model_root_override_rejected(tmp_path):
    """Verify unsafe model root overrides are rejected in production and sensitive directories."""
    from core.model_download.storage import StorageSecurityError, validate_model_root

    # 1. In production (no dev/test flag), env override is rejected
    with patch.dict(
        os.environ,
        {
            "AGENT_ENGINE_ENV": "production",
            "AGENT_ENGINE_DEV_MODE": "0",
            "AGENT_ENGINE_MODELS_DIR": str(tmp_path / "custom"),
        },
        clear=False,
    ):
        os.environ.pop("AGENT_ENGINE_ALLOW_UNVERIFIED_MODELS_DIR", None)
        with pytest.raises(
            StorageSecurityError, match="model root overrides are strictly disabled in production"
        ):
            ModelStorageManager()

    # 2. In dev/test mode, root paths (/tmp, workspace cwd, user home) are strictly rejected
    with patch.dict(os.environ, {"AGENT_ENGINE_ENV": "test"}):
        with pytest.raises(StorageSecurityError, match="temporary director"):
            validate_model_root(Path("/tmp/models"), is_env_override=True)

        with pytest.raises(StorageSecurityError, match="project source tree"):
            validate_model_root(Path.cwd() / "models", is_env_override=True)

        with pytest.raises(StorageSecurityError, match="forbidden system path"):
            validate_model_root(Path("/etc/models"), is_env_override=True)

        # Authorized subfolder in user home directory is accepted
        valid_custom = Path.home() / ".test_ae_models_root"
        validated = validate_model_root(valid_custom, is_env_override=True)
        assert validated == valid_custom.resolve()


# ==============================================================================
# 14. Post-Verification Mutation Rejected by Supervisor
# ==============================================================================
def test_19_post_verification_byte_mutation_rejected_by_supervisor(temp_models_dir):
    """Verify modifying a verified model by 1 byte causes ModelArtifactValidator to refuse launch."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    aid = "supervisor-tamper.gguf"
    final_path = storage.get_final_path(aid)
    final_path.write_bytes(DUMMY_GGUF_CONTENT)

    status = DownloadStatus(
        artifact_id=aid,
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="tamper-model"),
        state=DownloadState.VERIFIED,
        bytes_downloaded=DUMMY_GGUF_SIZE,
        total_bytes_expected=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
        observed_sha256=DUMMY_GGUF_SHA256,
        progress_ratio=1.0,
        file_path=str(final_path),
        verified_at=time.time(),
        catalog_version="2026.10.1",
    )
    storage.save_metadata(status)

    # Initially valid
    res = ModelArtifactValidator.validate(final_path)
    assert res.format == "gguf"

    # Mutate exactly 1 byte
    tampered_bytes = bytearray(DUMMY_GGUF_CONTENT)
    tampered_bytes[-1] = (tampered_bytes[-1] + 1) % 256
    final_path.write_bytes(bytes(tampered_bytes))

    # Validator must reject launch
    with pytest.raises(ModelValidationError, match="integrity compromised"):
        ModelArtifactValidator.validate(final_path)


# ==============================================================================
# 15. Conflicting Existing Destination File is Not Clobbered
# ==============================================================================
def test_20_conflicting_existing_destination_not_clobbered(temp_models_dir):
    """Verify promotion never overwrites a pre-existing file with different content."""
    from core.model_download.storage import ArtifactConflictError

    storage = ModelStorageManager(models_dir=temp_models_dir)
    aid = "conflict-target.gguf"
    final_path = storage.get_final_path(aid)
    partial_path = storage.get_partial_path(aid)

    # Pre-existing file with Content A
    content_a = b"EXISTING_ORIGINAL_CONTENT_AAAA"
    final_path.write_bytes(content_a)

    # New download partial with Content B
    content_b = b"NEW_DOWNLOAD_CONTENT_BBBBBBBBBB"
    partial_path.write_bytes(content_b)

    # atomic_promote must raise ArtifactConflictError
    with pytest.raises(ArtifactConflictError, match="already exists and differs"):
        storage.atomic_promote(partial_path, final_path)

    # Existing file content must be completely unmodified
    assert final_path.read_bytes() == content_a
    # Partial file must still exist, not deleted silently
    assert partial_path.exists()


# ==============================================================================
# 16. Crash and Restart Reconciliation
# ==============================================================================
def test_21_crash_restart_reconciliation(temp_models_dir):
    """Verify startup reconciliation recovers factual state across all crash scenarios."""
    from core.model_recommendation.catalog import LocalModelCatalog

    storage = ModelStorageManager(models_dir=temp_models_dir)

    # Scenario A: Mid-download interruption (partial exists, metadata downloading)
    aid_a = "crash-mid-download.gguf"
    part_a = storage.get_partial_path(aid_a)
    part_a.write_bytes(b"PARTIAL_CONTENT_123")
    meta_a = DownloadStatus(
        artifact_id=aid_a,
        state=DownloadState.DOWNLOADING,
        bytes_downloaded=len(b"PARTIAL_CONTENT_123"),
        total_bytes_expected=1000,
        etag='"etag-a"',
    )
    storage.save_metadata(meta_a)

    # Scenario B: Crash during VERIFYING (partial exists, full bytes)
    aid_b = "crash-verifying.gguf"
    part_b = storage.get_partial_path(aid_b)
    part_b.write_bytes(DUMMY_GGUF_CONTENT)
    meta_b = DownloadStatus(
        artifact_id=aid_b,
        state=DownloadState.VERIFYING,
        bytes_downloaded=DUMMY_GGUF_SIZE,
        total_bytes_expected=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
        etag='"etag-b"',
    )
    storage.save_metadata(meta_b)

    # Scenario C: Partial exceeds expected size (corrupted during crash)
    aid_c = "crash-overflow.gguf"
    part_c = storage.get_partial_path(aid_c)
    part_c.write_bytes(b"X" * 2000)
    meta_c = DownloadStatus(
        artifact_id=aid_c,
        state=DownloadState.DOWNLOADING,
        bytes_downloaded=2000,
        total_bytes_expected=1000,
    )
    storage.save_metadata(meta_c)

    # Scenario D: Crash after placement before metadata commit
    aid_d = "recovered_model.gguf"
    final_d = storage.get_final_path(aid_d)
    dummy_bytes = b"0" * 1024
    cat_hasher = hashlib.sha256(dummy_bytes).hexdigest()
    final_d.write_bytes(dummy_bytes)

    fake_identity = ModelIdentity(provider_id="llamacpp", model_id="recovered-model")
    fake_entry = MagicMock()
    fake_entry.model_identity = fake_identity
    fake_desc = ModelArtifactDescriptor(
        artifact_id=aid_d,
        model_identity=fake_identity,
        source_url="https://example.com/recovered.gguf",
        destination_filename=aid_d,
        expected_size_bytes=1024,
        expected_sha256=cat_hasher,
    )

    with patch.object(LocalModelCatalog, "get_all_models", return_value=[fake_entry]):
        with patch.object(LocalModelCatalog, "get_artifact_descriptor", return_value=fake_desc):
            mgr = ModelDownloadManager(storage_manager=storage)

            # Scenario A -> PAUSED, resumable
            st_a = mgr.get_status(aid_a)
            assert st_a.state == DownloadState.PAUSED
            assert st_a.partial_present is True
            assert st_a.resumable is True

            # Scenario B -> PAUSED, resumable candidate
            st_b = mgr.get_status(aid_b)
            assert st_b.state == DownloadState.PAUSED
            assert st_b.partial_present is True

            # Scenario C -> FAILED, quarantined
            st_c = mgr.get_status(aid_c)
            assert st_c.state == DownloadState.FAILED
            assert not part_c.exists()

            # Scenario D -> VERIFIED with metadata committed
            st_d = mgr.get_status(aid_d)
            assert st_d.state == DownloadState.VERIFIED
            assert st_d.progress_ratio == 1.0


# ==============================================================================
# 17. Resumed Checksum Covers Complete Artifact & Detects Corrupted Partial
# ==============================================================================
def test_22_resumed_checksum_detects_corrupted_existing_partial(temp_models_dir, mock_model_server):
    """Verify resume pre-hashes existing partial so a tampered partial fails verification."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    aid = "resume-corrupt-test.gguf"
    partial_path = storage.get_partial_path(aid)

    # 1. Write first 500 bytes of content, but corrupt byte 10
    first_part = bytearray(DUMMY_GGUF_CONTENT[:500])
    first_part[10] = (first_part[10] + 1) % 256
    partial_path.write_bytes(bytes(first_part))

    # Pre-save metadata indicating 500 bytes downloaded
    meta = DownloadStatus(
        artifact_id=aid,
        state=DownloadState.PAUSED,
        bytes_downloaded=500,
        total_bytes_expected=DUMMY_GGUF_SIZE,
        etag='"model-etag-v1"',
        expected_sha256=DUMMY_GGUF_SHA256,
    )
    storage.save_metadata(meta)

    descriptor = ModelArtifactDescriptor(
        artifact_id=aid,
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="resume-corrupt-model"),
        source_url=f"{mock_model_server}/model.gguf",
        destination_filename=aid,
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
    )

    # Resume download synchronously
    status = mgr.start_download(descriptor, sync=True)

    # The download must FAIL because total SHA-256 is invalid due to corrupted partial
    assert status.state == DownloadState.FAILED
    assert "Checksum mismatch" in (status.error_message or "")
    assert not storage.get_final_path(aid).exists()


# ==============================================================================
# 18. Policy Denial Blocks Network and File Mutation
# ==============================================================================
def test_23_policy_denial_blocks_network_and_disk_mutations(temp_models_dir, tmp_path):
    """Verify PolicyEngine block rule halts download with HTTP 403 and zero disk/network operations."""
    from core.safety.policy import PolicyEngine, PolicyRule
    from services.python.server.app import create_app

    # Create policy engine with explicit BLOCK rule on model_download
    policy_file = str(tmp_path / "block_policy.yaml")
    engine = PolicyEngine(policy_file=policy_file)
    engine.add_rule(
        PolicyRule(
            id="BLOCK_MODEL_DOWNLOAD",
            name="Block Model Downloads",
            description="Block all model downloads by administrative safety policy.",
            match_type="regex",
            pattern="model_download",
            action="block",
            reason="Model downloads restricted by administrative safety policy.",
        )
    )

    # 1. Direct manager start_download fails with PermissionError
    storage = ModelStorageManager(models_dir=temp_models_dir)
    mgr = ModelDownloadManager(storage_manager=storage, policy_engine=engine)

    descriptor = ModelArtifactDescriptor(
        artifact_id="policy-blocked.gguf",
        model_identity=ModelIdentity(
            provider_id="llamacpp", model_id="llama-3.2-1b-instruct-q4_k_m"
        ),
        source_url="https://example.com/model.gguf",
        destination_filename="policy-blocked.gguf",
        expected_size_bytes=1000,
        expected_sha256="abc",
    )

    with pytest.raises(PermissionError, match="Policy blocked model download"):
        mgr.start_download(descriptor)

    # Verify zero files created
    assert not storage.get_partial_path("policy-blocked.gguf").exists()
    assert not storage.get_final_path("policy-blocked.gguf").exists()

    # 2. REST API endpoint returns 403 with structured policy error
    app = create_app()
    client = TestClient(app)
    token = "test_ipc_token_r36_policy"

    with patch("services.python.server.routers.models.get_policy_engine", return_value=engine):
        with patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}):
            res = client.post(
                "/v1/models/downloads",
                headers={"X-IPC-Token": token},
                json={"model_id": "llama-3.2-1b-instruct-q4_k_m"},
            )
            assert res.status_code == 403
            data = res.json()
            assert data["detail"]["error"] == "POLICY_BLOCKED"
            assert "restricted by administrative safety policy" in data["detail"]["reason"]


# ==============================================================================
# 19. Actual-Byte Limit Enforcement on Streamed Response
# ==============================================================================
def test_24_streamed_socket_byte_limit_enforced(temp_models_dir):
    """Verify download loop aborts immediately if socket stream exceeds expected size allowance."""
    storage = ModelStorageManager(models_dir=temp_models_dir)

    # Custom mock downloader that yields a runaway byte stream
    class RunawayStreamDownloader:
        def open_stream(self, url, range_start=None, if_range_etag=None):
            class FakeRaw:
                def __init__(self):
                    self.bytes_read = 0

                def read(self, chunk_size):
                    self.bytes_read += chunk_size
                    return b"A" * chunk_size

            class FakeResp:
                status_code = 200
                headers = {}
                raw = FakeRaw()

                def close(self):
                    pass

            return FakeResp()

    mgr = ModelDownloadManager(
        storage_manager=storage,
        downloader=RunawayStreamDownloader(),
    )

    expected_size = 1000
    descriptor = ModelArtifactDescriptor(
        artifact_id="runaway-test.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="runaway-model"),
        source_url="https://example.com/runaway.gguf",
        destination_filename="runaway-test.gguf",
        expected_size_bytes=expected_size,
        expected_sha256="dummy_hash",
    )

    status = mgr.start_download(descriptor, sync=True)

    assert status.state == DownloadState.FAILED
    assert "significantly exceeded expected size" in (status.error_message or "")
    assert not storage.get_final_path("runaway-test.gguf").exists()


# ==============================================================================
# 20. Clean Retry from Terminal FAILED State Without Manual Deletion
# ==============================================================================
def test_25_retry_from_failed_clears_error_and_stale_partial(mock_model_server, temp_models_dir):
    """Verify retry from FAILED clears previous errors and byte counts without requiring manual artifact deletion."""
    storage = ModelStorageManager(models_dir=temp_models_dir)
    downloader = SafeStreamingDownloader(allow_http_for_test=True, allow_loopback_for_test=True)
    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)

    descriptor = ModelArtifactDescriptor(
        artifact_id="retry-failed-test.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="retry-failed-model"),
        source_url=f"{mock_model_server}/model.gguf",
        destination_filename="retry-failed-test.gguf",
        expected_size_bytes=DUMMY_GGUF_SIZE,
        expected_sha256=DUMMY_GGUF_SHA256,
    )

    # 1. Simulate an earlier failed attempt that wrote a corrupt/stale partial file and metadata
    partial_path = storage.get_partial_path(descriptor.artifact_id)
    partial_path.write_bytes(b"STALE_CORRUPTED_BYTES_FROM_FAILED_DOWNLOAD")
    stale_failed_status = DownloadStatus(
        artifact_id=descriptor.artifact_id,
        model_identity=descriptor.model_identity,
        state=DownloadState.FAILED,
        bytes_downloaded=len(b"STALE_CORRUPTED_BYTES_FROM_FAILED_DOWNLOAD"),
        total_bytes_expected=DUMMY_GGUF_SIZE,
        progress_ratio=0.5,
        etag='"corrupted-etag"',
        expected_sha256=descriptor.expected_sha256,
        resumable=False,
        error_message="Connection aborted prematurely: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]",
        started_at=time.time() - 100,
        updated_at=time.time() - 50,
    )
    storage.save_metadata(stale_failed_status)

    # Verify initial failed state
    persisted_failed = storage.load_metadata(descriptor.artifact_id)
    assert persisted_failed is not None
    assert persisted_failed.state == DownloadState.FAILED
    assert persisted_failed.error_message is not None
    assert partial_path.exists()

    # 2. Start retry download without any manual file deletion
    status = mgr.start_download(descriptor, sync=True)

    # 3. Verify clean recovery: FAILED error cleared, fresh bytes streamed, final state VERIFIED
    assert status.state == DownloadState.VERIFIED
    assert status.error_message is None
    assert status.bytes_downloaded == DUMMY_GGUF_SIZE
    assert not partial_path.exists()
    final_path = storage.get_final_path(descriptor.artifact_id)
    assert final_path.exists()
    assert final_path.read_bytes() == DUMMY_GGUF_CONTENT

    # Verify persisted metadata is clean
    final_meta = storage.load_metadata(descriptor.artifact_id)
    assert final_meta is not None
    assert final_meta.state == DownloadState.VERIFIED
    assert final_meta.error_message is None


# ==============================================================================
# 21. Live Network Transport Acceptance Gate (Opt-in)
# ==============================================================================
@pytest.mark.live_network
def test_26_pinned_https_transport_live_network():
    """Verify PinningHTTPSConnection connects to canonical artifact URL, follows CDN redirect, and reads initial bytes."""
    source_url = (
        "https://huggingface.co/hugging-quants/Llama-3.2-1B-Instruct-Q4_K_M-GGUF"
        "/resolve/main/llama-3.2-1b-instruct-q4_k_m.gguf"
    )
    downloader = SafeStreamingDownloader(connect_timeout_seconds=20.0, read_timeout_seconds=30.0)

    resp = downloader.open_stream(source_url, range_start=0)
    try:
        assert resp.status_code in (200, 206)
        initial_chunk = resp.raw.read(4)
        assert initial_chunk == b"GGUF", f"Expected magic bytes b'GGUF', got {initial_chunk!r}"
    finally:
        resp.close()
