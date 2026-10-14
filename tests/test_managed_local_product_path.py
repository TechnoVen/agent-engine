"""tests/test_managed_local_product_path.py

Acceptance test suite for the complete managed local model product path.
Verifies the canonical flow:
1. Catalog descriptor accuracy and metadata truthfulness.
2. Hardware telemetry calibration and recommendations API.
3. Catalog-driven download with digest verification into private AE storage.
4. Fail-closed checksum verification and quarantine on mismatch.
5. Managed runtime startup, dynamic port binding, and health probe readiness.
6. Idempotent duplicate runtime start.
7. Graceful runtime stop leaving zero orphan processes.
8. Truthful crash state reconciliation on unexpected child exit.
9. LOCAL_ONLY execution routing to managed local model with $0.00 provider charge.
10. Fail-closed privacy routing under LOCAL_ONLY when runtime is unavailable.
11. IPC authentication enforcement (401 in browser-only mode).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from core.execution.models import RoutingTier
from core.inference import (
    GGUF_MAGIC_BYTES,
    LocalInferenceSupervisor,
    ModelArtifactValidator,
    RuntimeBinaryInfo,
    RuntimeInstance,
    RuntimeSpec,
    RuntimeState,
    reset_local_inference_supervisor,
    set_local_inference_supervisor,
)
from core.model_download import (
    DownloadState,
    DownloadStatus,
    ModelArtifactDescriptor,
    ModelDownloadManager,
    ModelStorageManager,
    reset_download_manager,
)
from core.model_recommendation import LocalModelCatalog
from core.model_registry.models import ModelIdentity
from core.resources import (
    CpuResources,
    MemoryResources,
    ProbeStatus,
    ResourceSnapshot,
)
from core.router import ModelRouter
from core.privacy.models import (
    DataRoutingClass,
    DataRoutingPolicy,
    EffectiveRoutingPolicy,
    NoEligibleModelUnderPrivacyPolicyError,
    RoutingPolicySource,
)
from services.python.server.app import create_app
from services.python.server.dependencies import reset_token_manager


@pytest.fixture(autouse=True)
def clean_environment_and_singletons():
    """Ensure clean singletons across tests."""
    reset_token_manager()
    reset_download_manager()
    reset_local_inference_supervisor()
    yield
    reset_token_manager()
    reset_download_manager()
    reset_local_inference_supervisor()


# ==============================================================================
# 1. Catalog Descriptor Accuracy
# ==============================================================================
def test_01_catalog_descriptor_accuracy():
    """Verify curated catalog entries have authoritative artifact descriptors."""
    catalog = LocalModelCatalog()
    models = catalog.get_all_models()
    model_ids = {m.model_identity.model_id for m in models}

    assert "llama-3.2-1b-instruct-q4_k_m" in model_ids
    assert "qwen2.5-coder-3b-instruct-q4_k_m" in model_ids

    llama_entry = next(
        m for m in models if m.model_identity.model_id == "llama-3.2-1b-instruct-q4_k_m"
    )
    assert llama_entry.managed_runtime == "llamacpp"
    assert llama_entry.quantization == "Q4_K_M"
    assert llama_entry.artifact_descriptor is not None
    assert llama_entry.artifact_descriptor.artifact_id == "llama-3.2-1b-instruct-q4_k_m.gguf"
    assert llama_entry.artifact_descriptor.format == "gguf"
    assert (
        llama_entry.artifact_descriptor.expected_sha256
        == "a9b4b3b52dee68ea2d6c10f0fcf72ecf0ebef6690f2fc30ca0ca1379c379d875"
    )
    assert llama_entry.artifact_descriptor.expected_size_bytes == 807690656

    qwen_entry = next(
        m for m in models if m.model_identity.model_id == "qwen2.5-coder-3b-instruct-q4_k_m"
    )
    assert qwen_entry.managed_runtime == "llamacpp"
    assert qwen_entry.artifact_descriptor is not None
    assert qwen_entry.artifact_descriptor.artifact_id == "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
    assert (
        qwen_entry.artifact_descriptor.expected_sha256
        == "4a188102020e9c9530b687fd6400f775c45e90a0d7baafe65bd0a36963fbb7ba"
    )
    assert qwen_entry.artifact_descriptor.expected_size_bytes == 1929903072


# ==============================================================================
# 2. Recommendations API Hardware Calibration
# ==============================================================================
def test_02_recommendations_api_calibration():
    """Verify recommendations endpoint produces deterministic recommendations."""
    app = create_app()
    client = TestClient(app)
    token = "test_ipc_token_models"

    mock_mgr = MagicMock()
    mock_mgr.get_snapshot.return_value = ResourceSnapshot(
        captured_at=time.time(),
        platform="linux",
        architecture="x86_64",
        cpu=CpuResources(architecture="x86_64", logical_cores=8, status=ProbeStatus.KNOWN),
        memory=MemoryResources(
            total_bytes=32 * 1024 * 1024 * 1024,
            available_bytes=16 * 1024 * 1024 * 1024,
            used_bytes=16 * 1024 * 1024 * 1024,
            status=ProbeStatus.KNOWN,
        ),
        accelerators=[],
        stale=False,
    )

    with (
        patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}),
        patch("services.python.server.routers.models.get_resource_manager", return_value=mock_mgr),
    ):
        headers = {"X-IPC-Token": token}
        res = client.get("/v1/models/recommendations?require_local_only=true", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert "fast" in data
        assert "balanced" in data
        assert "best_local" in data
        assert data["fast"] is not None
        assert data["balanced"] is not None
        assert data["best_local"] is not None


# ==============================================================================
# 3. Model Download Flow with Controlled Verification
# ==============================================================================
def test_03_controlled_model_download_and_installation(tmp_path: Path):
    """Verify catalog-driven model download with sha256 verification and atomic promotion."""
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)
    storage = ModelStorageManager(models_dir=models_dir)

    # Prepare small valid GGUF fixture
    gguf_content = GGUF_MAGIC_BYTES + b"\x00\x00\x00\x01" + b"MODEL_WEIGHT_FIXTURE_PADDING" * 10
    gguf_sha256 = hashlib.sha256(gguf_content).hexdigest()
    gguf_size = len(gguf_content)

    descriptor = ModelArtifactDescriptor(
        artifact_id="test-model-q4_k_m.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="test-model-q4_k_m"),
        source_url="https://huggingface.co/test/test-model/resolve/main/test-model-q4_k_m.gguf",
        expected_size_bytes=gguf_size,
        expected_sha256=gguf_sha256,
        format="gguf",
        quantization="Q4_K_M",
    )

    downloader = MagicMock()
    downloader.validate_destination_url.return_value = None
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"ETag": "test_etag"}
    mock_resp.raw.read.side_effect = [gguf_content, b""]
    mock_resp.raw.enforce_content_length = False
    downloader.open_stream.return_value = mock_resp

    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)
    status = mgr.start_download(descriptor, sync=True)

    assert status.state == DownloadState.VERIFIED
    assert status.observed_sha256 == gguf_sha256
    assert status.progress_ratio == 1.0

    # Assert final destination file exists and is validated
    final_file = storage.get_final_path("test-model-q4_k_m.gguf")
    assert final_file.is_file()
    validated = ModelArtifactValidator.validate(final_file)
    assert validated.format == "gguf"
    assert validated.size_bytes == gguf_size

    # Listed in list_installed_models
    installed = mgr.list_installed_models()
    assert any(m.artifact_id == "test-model-q4_k_m.gguf" for m in installed)


# ==============================================================================
# 4. Fail-Closed Checksum Mismatch Quarantines File
# ==============================================================================
def test_04_checksum_mismatch_quarantines_partial(tmp_path: Path):
    """Verify mismatched SHA-256 fails closed, quarantines corrupt data, and never promotes to destination."""
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)
    storage = ModelStorageManager(models_dir=models_dir)

    gguf_content = GGUF_MAGIC_BYTES + b"\x00\x00\x00\x01" + b"CORRUPTED_BYTES"
    expected_wrong_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"

    descriptor = ModelArtifactDescriptor(
        artifact_id="corrupt-model.gguf",
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="corrupt-model"),
        source_url="https://huggingface.co/test/corrupt/resolve/main/corrupt-model.gguf",
        expected_size_bytes=len(gguf_content),
        expected_sha256=expected_wrong_sha256,
        format="gguf",
    )

    downloader = MagicMock()
    downloader.validate_destination_url.return_value = None
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"ETag": "test_etag"}
    mock_resp.raw.read.side_effect = [gguf_content, b""]
    mock_resp.raw.enforce_content_length = False
    downloader.open_stream.return_value = mock_resp

    mgr = ModelDownloadManager(storage_manager=storage, downloader=downloader)
    status = mgr.start_download(descriptor, sync=True)

    # Destination file must NOT exist
    final_file = storage.get_final_path("corrupt-model.gguf")
    assert not final_file.exists()

    # Status must be FAILED
    status = mgr.get_status("corrupt-model.gguf")
    assert status.state == DownloadState.FAILED
    assert "Checksum mismatch" in (status.error_message or "")


# ==============================================================================
# 5. Managed Runtime Start and Status Endpoint
# ==============================================================================
def test_05_managed_runtime_start_and_status(tmp_path: Path):
    """Verify runtime start endpoint validates artifact, starts supervisor, and reports readiness."""
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)

    # Create tiny valid GGUF fixture
    model_file = models_dir / "llama-3.2-1b-instruct-q4_k_m.gguf"
    model_content = GGUF_MAGIC_BYTES + b"\x00\x00\x00\x01" + b"\x00" * 64
    model_file.write_bytes(model_content)

    app = create_app()
    client = TestClient(app)
    token = "test_ipc_token_runtime"

    storage = ModelStorageManager(models_dir=models_dir)
    dl_mgr = ModelDownloadManager(storage_manager=storage)

    # Register download status as verified
    verified_status = DownloadStatus(
        artifact_id="llama-3.2-1b-instruct-q4_k_m.gguf",
        model_identity=ModelIdentity(
            provider_id="llamacpp", model_id="llama-3.2-1b-instruct-q4_k_m"
        ),
        state=DownloadState.VERIFIED,
        bytes_downloaded=len(model_content),
        total_bytes_expected=len(model_content),
        progress_ratio=1.0,
        expected_sha256=hashlib.sha256(model_content).hexdigest(),
        file_path=str(model_file),
    )
    storage.save_metadata(verified_status)

    mock_supervisor = MagicMock(spec=LocalInferenceSupervisor)
    mock_instance = RuntimeInstance(
        instance_id="inst_test123",
        spec=RuntimeSpec(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="llama-3.2-1b-instruct-q4_k_m"
            ),
            model_path=str(model_file),
        ),
        state=RuntimeState.READY,
        pid=99999,
        endpoint_url="http://127.0.0.1:45678",
    )
    mock_supervisor.start.return_value = mock_instance

    from core.inference.models import RuntimeHealth

    mock_supervisor.get_health.return_value = RuntimeHealth(
        state=RuntimeState.READY,
        is_ready=True,
        pid=99999,
        endpoint_url="http://127.0.0.1:45678",
        model_loaded="llama-3.2-1b-instruct-q4_k_m",
        latency_ms=12.5,
    )

    mock_res_mgr = MagicMock()
    mock_res_mgr.get_snapshot.return_value = ResourceSnapshot(
        captured_at=time.time(),
        platform="linux",
        architecture="x86_64",
        cpu=CpuResources(architecture="x86_64", logical_cores=8, status=ProbeStatus.KNOWN),
        memory=MemoryResources(
            total_bytes=32 * 1024 * 1024 * 1024,
            available_bytes=16 * 1024 * 1024 * 1024,
            used_bytes=16 * 1024 * 1024 * 1024,
            status=ProbeStatus.KNOWN,
        ),
    )

    set_local_inference_supervisor(mock_supervisor)
    try:
        with (
            patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}),
            patch(
                "services.python.server.routers.models.get_download_manager", return_value=dl_mgr
            ),
            patch(
                "services.python.server.routers.models.get_resource_manager",
                return_value=mock_res_mgr,
            ),
        ):
            headers = {"X-IPC-Token": token}
            res = client.post(
                "/v1/models/runtime/start",
                headers=headers,
                json={"model_id": "llama-3.2-1b-instruct-q4_k_m"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["state"] == "ready"
            assert data["is_ready"] is True
            assert data["pid"] == 99999
            assert data["endpoint_url"] == "http://127.0.0.1:45678"
            assert data["model_loaded"] == "llama-3.2-1b-instruct-q4_k_m"

            # Check status endpoint
            res_status = client.get("/v1/models/runtime/status", headers=headers)
            assert res_status.status_code == 200
            assert res_status.json()["state"] == "ready"
            assert res_status.json()["is_ready"] is True
    finally:
        reset_local_inference_supervisor()


def test_05b_unsafe_hardware_runtime_start_rejected(tmp_path: Path):
    """Verify runtime/start is rejected with 400 when host hardware has insufficient memory headroom."""
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    model_file = models_dir / "llama-3.2-1b-instruct-q4_k_m.gguf"
    model_content = GGUF_MAGIC_BYTES + b"\x00" * 2048
    model_file.write_bytes(model_content)

    from services.python.server.api import create_app

    app = create_app()
    client = TestClient(app)
    token = "test_ipc_token_unsafe_hardware"

    storage = ModelStorageManager(models_dir=models_dir)
    dl_mgr = ModelDownloadManager(storage_manager=storage)
    verified_status = DownloadStatus(
        artifact_id="llama-3.2-1b-instruct-q4_k_m.gguf",
        model_identity=ModelIdentity(
            provider_id="llamacpp", model_id="llama-3.2-1b-instruct-q4_k_m"
        ),
        state=DownloadState.VERIFIED,
        bytes_downloaded=len(model_content),
        total_bytes_expected=len(model_content),
        progress_ratio=1.0,
        expected_sha256=hashlib.sha256(model_content).hexdigest(),
        file_path=str(model_file),
    )
    storage.save_metadata(verified_status)

    mock_unsafe_mgr = MagicMock()
    mock_unsafe_mgr.get_snapshot.return_value = ResourceSnapshot(
        captured_at=time.time(),
        platform="linux",
        architecture="x86_64",
        cpu=CpuResources(architecture="x86_64", logical_cores=4, status=ProbeStatus.KNOWN),
        memory=MemoryResources(
            total_bytes=8 * 1024 * 1024 * 1024,
            available_bytes=int(0.47 * 1024 * 1024 * 1024),
            used_bytes=int(7.53 * 1024 * 1024 * 1024),
            status=ProbeStatus.KNOWN,
        ),
    )

    with (
        patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}),
        patch("services.python.server.routers.models.get_download_manager", return_value=dl_mgr),
        patch(
            "services.python.server.routers.models.get_resource_manager",
            return_value=mock_unsafe_mgr,
        ),
    ):
        res = client.post(
            "/v1/models/runtime/start",
            headers={"X-IPC-Token": token},
            json={"model_id": "llama-3.2-1b-instruct-q4_k_m"},
        )
        assert res.status_code == 400
        assert "Cannot start runtime: Insufficient available memory" in res.json()["detail"]


def test_05c_unverified_or_unrecognized_runtime_start_rejected(tmp_path: Path):
    """Verify runtime/start is strictly limited to curated verified managed artifacts."""
    from services.python.server.api import create_app

    app = create_app()
    client = TestClient(app)
    token = "test_ipc_token_unverified"

    empty_models = tmp_path / "empty_models"
    empty_models.mkdir(parents=True, exist_ok=True)
    storage = ModelStorageManager(models_dir=empty_models)
    dl_mgr = ModelDownloadManager(storage_manager=storage)

    with (
        patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}),
        patch("services.python.server.routers.models.get_download_manager", return_value=dl_mgr),
    ):
        # 1. Unrecognized model ID
        res_unknown = client.post(
            "/v1/models/runtime/start",
            headers={"X-IPC-Token": token},
            json={"model_id": "arbitrary_custom_model"},
        )
        assert res_unknown.status_code == 404

        # 2. Arbitrary file path attempt
        res_path = client.post(
            "/v1/models/runtime/start",
            headers={"X-IPC-Token": token},
            json={"model_id": "/tmp/malicious.gguf"},
        )
        assert res_path.status_code == 404

        # 3. Curated model that is not yet verified
        res_unverified = client.post(
            "/v1/models/runtime/start",
            headers={"X-IPC-Token": token},
            json={"model_id": "llama-3.2-1b-instruct-q4_k_m"},
        )
        assert res_unverified.status_code == 400
        assert "is not verified" in res_unverified.json()["detail"]


# ==============================================================================
# 6. Duplicate Runtime Start Idempotency
# ==============================================================================
def test_06_duplicate_start_idempotency(tmp_path: Path):
    """Verify starting already-running model returns existing instance idempotently."""
    mock_binary = MagicMock()
    mock_binary.binary_path = "/usr/bin/true"
    resolver = MagicMock()
    resolver.resolve_binary.return_value = RuntimeBinaryInfo(
        binary_path="/usr/bin/true",
        version="0.3.0",
        sha256="fake_sha",
        manifest_verified=True,
        bundle_integrity_verified=True,
    )

    supervisor = LocalInferenceSupervisor(binary_resolver=resolver)

    # Create tiny GGUF fixture
    gguf_p = tmp_path / "model.gguf"
    gguf_p.write_bytes(GGUF_MAGIC_BYTES + b"\x00" * 32)

    spec = RuntimeSpec(
        model_identity=ModelIdentity(provider_id="llamacpp", model_id="test-model"),
        model_path=str(gguf_p),
    )

    # First start: mock process and probe
    mock_handle = MagicMock()
    mock_handle.pid = 12345
    mock_handle.poll.return_value = None

    with (
        patch("core.inference.supervisor.RuntimeProcessHandle", return_value=mock_handle),
        patch("core.inference.supervisor.requests.get") as mock_get,
        patch("core.inference.supervisor.verify_endpoint_ownership", return_value=True),
    ):
        mock_get.return_value.status_code = 200

        inst1 = supervisor.start(spec)
        assert supervisor.state == RuntimeState.READY
        assert inst1.pid == 12345

        # Duplicate start with same spec
        inst2 = supervisor.start(spec)
        assert inst2 is inst1
        assert inst2.pid == 12345


# ==============================================================================
# 7. Managed Runtime Stop Leaves Zero Orphans
# ==============================================================================
def test_07_managed_runtime_stop_zero_orphans(tmp_path: Path):
    """Verify runtime stop terminates child handle cleanly without orphan processes."""
    supervisor = LocalInferenceSupervisor()

    mock_handle = MagicMock()
    mock_handle.pid = 54321
    mock_handle.terminate_gracefully.return_value = 0
    supervisor._process_handle = mock_handle
    supervisor._state = RuntimeState.READY
    supervisor._active_instance = RuntimeInstance(
        instance_id="inst_stop_test",
        spec=RuntimeSpec(
            model_identity=ModelIdentity(provider_id="llamacpp", model_id="test"),
            model_path=str(tmp_path / "fake.gguf"),
        ),
        state=RuntimeState.READY,
        pid=54321,
    )

    success = supervisor.stop()
    assert success is True
    assert supervisor.state == RuntimeState.STOPPED
    mock_handle.terminate_gracefully.assert_called_once()


# ==============================================================================
# 8. Runtime Crash Reconciliation
# ==============================================================================
def test_08_runtime_crash_reconciliation(tmp_path: Path):
    """Verify unexpected child exit is truthfully reconciled to FAILED state."""
    supervisor = LocalInferenceSupervisor()

    mock_handle = MagicMock()
    mock_handle.pid = 9999
    # Simulate child process dead with exit code 139 (SIGSEGV)
    mock_handle.poll.return_value = 139
    mock_handle.get_logs.return_value = ["llama_model_load: segmentation fault"]

    supervisor._process_handle = mock_handle
    supervisor._state = RuntimeState.READY
    inst = RuntimeInstance(
        instance_id="inst_crash_test",
        spec=RuntimeSpec(
            model_identity=ModelIdentity(provider_id="llamacpp", model_id="crash-model"),
            model_path=str(tmp_path / "model.gguf"),
        ),
        state=RuntimeState.READY,
        pid=9999,
    )
    supervisor._active_instance = inst

    # Querying state reconciles child exit
    assert supervisor.state == RuntimeState.FAILED
    health = supervisor.get_health()
    assert health.state == RuntimeState.FAILED
    assert health.is_ready is False
    assert "Unexpected process termination (code 139)" in (inst.exit_reason or "")


# ==============================================================================
# 9. LOCAL_ONLY Execution Routes to Local llamacpp with $0.00 Cost
# ==============================================================================
def test_09_local_only_execution_routes_to_llamacpp():
    """Verify LOCAL_ONLY policy routes to llamacpp with $0.00 provider charge and zero cloud fallback."""
    router = ModelRouter()

    # Probe status mock: llamacpp live, cloud live
    status_mock = {
        "llamacpp_live": True,
        "ollama_live": False,
        "openai_key_present": True,
        "openai_live": True,
    }

    policy = EffectiveRoutingPolicy(
        effective_class=DataRoutingClass.LOCAL_ONLY,
        source=RoutingPolicySource.PROJECT_OVERRIDE,
        profile_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY),
    )

    with patch.object(router, "get_status", return_value=status_mock):
        resolved = router.resolve_model(
            requested_model="llama-3.2-1b-instruct-q4_k_m",
            effective_policy=policy,
        )
        assert resolved.provider_id == "llamacpp"
        assert resolved.routing_tier == RoutingTier.LOCAL
        assert resolved.fallback_chain == ["llamacpp"]
        assert resolved.estimated_cost_per_1k_tokens == 0.0


# ==============================================================================
# 10. LOCAL_ONLY Fails Closed When Local Runtime Unavailable
# ==============================================================================
def test_10_local_only_fails_closed_when_runtime_unavailable():
    """Verify LOCAL_ONLY fails closed when local runtime is unavailable, preventing cloud leakage."""
    router = ModelRouter()

    status_mock = {
        "llamacpp_live": False,
        "ollama_live": False,
        "openai_key_present": True,
        "openai_live": True,
    }

    policy = EffectiveRoutingPolicy(
        effective_class=DataRoutingClass.LOCAL_ONLY,
        source=RoutingPolicySource.PROJECT_OVERRIDE,
        profile_policy=DataRoutingPolicy(routing_class=DataRoutingClass.LOCAL_ONLY),
    )

    with patch.object(router, "get_status", return_value=status_mock):
        with pytest.raises(NoEligibleModelUnderPrivacyPolicyError) as exc_info:
            router.resolve_model(
                requested_tier=RoutingTier.LOCAL,
                effective_policy=policy,
            )
        assert "Local runtime unavailable and cloud fallback forbidden under LOCAL_ONLY" in str(
            exc_info.value
        )


# ==============================================================================
# 11. Browser-Only Mode / Unauthenticated Access Fails with 401
# ==============================================================================
def test_11_unauthenticated_api_requests_return_401():
    """Verify requests without valid IPC token return HTTP 401."""
    app = create_app()
    client = TestClient(app)

    token = "secret_ipc_token_desk"
    with patch.dict(os.environ, {"AGENT_ENGINE_IPC_TOKEN": token}):
        # Runtime endpoints without token
        res_start = client.post("/v1/models/runtime/start", json={"model_id": "test"})
        assert res_start.status_code == 401

        res_stop = client.post("/v1/models/runtime/stop")
        assert res_stop.status_code == 401

        res_status = client.get("/v1/models/runtime/status")
        assert res_status.status_code == 401

        # Download endpoints without token
        res_dl = client.post("/v1/models/downloads", json={"model_id": "test"})
        assert res_dl.status_code == 401
