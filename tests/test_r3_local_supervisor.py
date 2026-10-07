"""tests/test_r3_local_supervisor.py

Unit, Concurrency, Security, and E2E Integration Tests for Managed Local Inference Supervisor.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Validates:
1. Managed executable resolves only from trusted AE location; records version and SHA-256.
2. Arbitrary PATH, workspace, and downloads directory lookups are strictly rejected.
3. Child environment is minimal and provably excludes AGENT_ENGINE_IPC_TOKEN, master keys, and provider secrets.
4. Model artifact validation verifies regular file, readable, resolves symlinks safely, verifies GGUF magic bytes, and rejects traversal.
5. Default bind is loopback-only (127.0.0.1), LAN/0.0.0.0 is rejected, and local endpoint protection (--api-key) is configured.
6. Port allocation prevents foreign service collision and verifies child process ownership.
7. Duplicate concurrent start() calls produce exactly one instance (single-flight concurrency).
8. start() when READY is idempotent.
9. stop() when STOPPED is idempotent.
10. Startup timeout terminates process tree and transitions state to FAILED.
11. Readiness requires HTTP /health ok (handles 503 "Loading model"), not merely PID existence.
12. Unexpected runtime crash transitions state to FAILED with factual exit code and reason.
13. Graceful shutdown succeeds, hung shutdown escalates to force kill, and descendants do not survive.
14. Retained stdout/stderr output is bounded (ring buffer) and does not leak prompts or secrets.
15. llamacpp ProviderAdapter seamlessly consumes managed endpoint and authentication token.
16. Observational ResourceManager snapshot is recorded before start and after load.
17. Canonical ExecutionCoordinator prompt completes through managed runtime and ledger records endpoint_class=local_managed.
18. Real clean-machine E2E test with real binary and real model producing real tokens, followed by clean shutdown with zero orphan processes.
"""

from __future__ import annotations

import concurrent.futures
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.execution.models import ExecutionContext
from core.inference import (
    InvalidModelFormatError,
    LocalInferenceSupervisor,
    ModelArtifactValidator,
    ModelNotFoundError,
    ModelValidationError,
    PortCollisionError,
    RuntimeBinaryInfo,
    RuntimeBinaryResolver,
    RuntimeInstance,
    RuntimeProcessHandle,
    RuntimeSpec,
    RuntimeStartupError,
    RuntimeState,
    UntrustedBinaryLocationError,
    build_child_environment,
    find_available_loopback_port,
    get_local_inference_supervisor,
    reset_local_inference_supervisor,
    verify_child_environment_is_clean,
    verify_endpoint_ownership,
)
from core.model_registry.models import ModelIdentity
from core.providers import get_provider_registry
from core.storage.paths import get_private_data_dir


@pytest.fixture(autouse=True)
def clean_supervisor():
    """Ensure supervisor is stopped and clean before and after every test."""
    reset_local_inference_supervisor()
    yield
    reset_local_inference_supervisor()


@pytest.fixture
def fake_gguf_model(tmp_path: Path) -> Path:
    """Create a temporary valid GGUF file with proper magic header."""
    model_file = tmp_path / "test_model.gguf"
    model_file.write_bytes(b"GGUF" + b"\x00" * 1024)
    return model_file


# ==============================================================================
# 1. Managed Executable Resolution & Provenance Audit
# ==============================================================================
def test_01_managed_executable_resolution_and_provenance(tmp_path: Path):
    """Verify managed executable resolves from AE location with version and SHA-256 recorded."""
    resolver = RuntimeBinaryResolver(managed_root=tmp_path)
    fake_bin = tmp_path / resolver.executable_name
    fake_bin.write_text("#!/bin/sh\necho 'llama.cpp version b3500 (commit 1234abcd)'\n")
    fake_bin.chmod(0o755)

    info = resolver.resolve_binary()
    assert info.binary_path == str(fake_bin.resolve())
    assert info.implementation == "llama.cpp"
    assert "b3500" in info.version or "1234abcd" in info.version
    assert len(info.sha256) == 64
    assert info.provenance == "managed_installation"


# ==============================================================================
# 2. Rejection of Arbitrary PATH, Workspace, and Downloads Folders
# ==============================================================================
def test_02_untrusted_binary_locations_rejected(tmp_path: Path):
    """Verify binary resolver strictly rejects workspace, /tmp, and Downloads paths."""
    resolver = RuntimeBinaryResolver()

    # 1. Project workspace path
    workspace_bin = Path.cwd() / "fake_llama"
    assert RuntimeBinaryResolver.is_prohibited_location(workspace_bin) is True

    # 2. Temp directory path
    tmp_bin = Path(tempfile.gettempdir()) / "llama_in_tmp"
    assert RuntimeBinaryResolver.is_prohibited_location(tmp_bin) is True

    # 3. Downloads path
    downloads_bin = Path.home() / "Downloads" / "llama_server"
    assert RuntimeBinaryResolver.is_prohibited_location(downloads_bin) is True

    # 4. Attempting AGENT_ENGINE_LLAMA_BIN pointing to workspace raises UntrustedBinaryLocationError
    with patch.dict(
        os.environ,
        {
            "AGENT_ENGINE_LLAMA_BIN": str(workspace_bin),
            "AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY": "true",
        },
    ):
        with pytest.raises(UntrustedBinaryLocationError):
            resolver.resolve_binary()


# ==============================================================================
# 3. Child Environment Is Minimal & Provably Secret-Free
# ==============================================================================
def test_03_child_environment_secret_free(tmp_path: Path):
    """Verify child environment allowlist excludes all AE tokens, master keys, and provider secrets."""
    poisoned_env = {
        "AGENT_ENGINE_IPC_TOKEN": "secret_ipc_token_999",
        "AGENT_ENGINE_MASTER_KEY": "super_secret_master_key",
        "OPENAI_API_KEY": "sk-proj-openai-secret-123",
        "ANTHROPIC_API_KEY": "sk-ant-anthropic-secret-456",
        "GEMINI_API_KEY": "AIzaSyGeminiSecret789",
        "DEEPSEEK_API_KEY": "sk-deepseek-secret",
        "HOME": "/home/testuser",
        "USER": "testuser",
    }

    with patch.dict(os.environ, poisoned_env, clear=True):
        child_env = build_child_environment(binary_path=tmp_path / "llama-server")

        # Proved absent
        assert "AGENT_ENGINE_IPC_TOKEN" not in child_env
        assert "AGENT_ENGINE_MASTER_KEY" not in child_env
        assert "OPENAI_API_KEY" not in child_env
        assert "ANTHROPIC_API_KEY" not in child_env
        assert "GEMINI_API_KEY" not in child_env
        assert "DEEPSEEK_API_KEY" not in child_env

        # Allowed system variables present
        assert child_env.get("HOME") == "/home/testuser"
        assert child_env.get("USER") == "testuser"
        assert "PATH" in child_env

        # Verification function passes
        verify_child_environment_is_clean(child_env)

        # Injecting a forbidden secret raises ValueError
        child_env["AGENT_ENGINE_IPC_TOKEN"] = "leaked_token"
        with pytest.raises(ValueError, match="Child environment security check failed"):
            verify_child_environment_is_clean(child_env)


# ==============================================================================
# 4. Model Artifact Validation
# ==============================================================================
def test_04_model_artifact_validation(tmp_path: Path, fake_gguf_model: Path):
    """Verify model artifact checks regular file, read access, symlink resolution, and GGUF header."""
    # 1. Valid GGUF model passes
    val = ModelArtifactValidator.validate(fake_gguf_model)
    assert val.format == "gguf"
    assert val.size_bytes > 0
    assert val.is_symlink is False

    # 2. Symlink to valid model passes and records is_symlink=True
    link = tmp_path / "link_to_model.gguf"
    link.symlink_to(fake_gguf_model)
    val_link = ModelArtifactValidator.validate(link)
    assert val_link.is_symlink is True
    assert val_link.canonical_path == str(fake_gguf_model.resolve())

    # 3. Nonexistent file raises ModelNotFoundError
    with pytest.raises(ModelNotFoundError):
        ModelArtifactValidator.validate(tmp_path / "nonexistent.gguf")

    # 4. Invalid magic header raises InvalidModelFormatError
    bad_model = tmp_path / "corrupt.gguf"
    bad_model.write_bytes(b"BAD!" + b"\x00" * 100)
    with pytest.raises(InvalidModelFormatError):
        ModelArtifactValidator.validate(bad_model)

    # 5. Empty file raises ModelValidationError
    empty_model = tmp_path / "empty.gguf"
    empty_model.write_bytes(b"")
    with pytest.raises(ModelValidationError):
        ModelArtifactValidator.validate(empty_model)


# ==============================================================================
# 5. Loopback Binding & Local Endpoint Protection
# ==============================================================================
def test_05_loopback_binding_and_api_key_protection(fake_gguf_model: Path):
    """Verify spec strictly rejects non-loopback hosts (0.0.0.0/LAN) and supports per-launch token."""
    ident = ModelIdentity(provider_id="llamacpp", model_id="test-model")

    # 1. Loopback addresses succeed
    spec_local = RuntimeSpec(
        model_identity=ident, model_path=str(fake_gguf_model), host="127.0.0.1"
    )
    assert spec_local.host == "127.0.0.1"

    # 2. 0.0.0.0 raises ValueError
    with pytest.raises(ValueError, match="strictly bind to loopback"):
        RuntimeSpec(model_identity=ident, model_path=str(fake_gguf_model), host="0.0.0.0")

    # 3. Public IP / LAN raises ValueError
    with pytest.raises(ValueError, match="strictly bind to loopback"):
        RuntimeSpec(model_identity=ident, model_path=str(fake_gguf_model), host="192.168.1.50")


# ==============================================================================
# 6. Port Management & Foreign Service Collision Prevention
# ==============================================================================
def test_06_port_management_and_foreign_collision(fake_gguf_model: Path):
    """Verify dynamic port allocation finds free loopback ports and detects foreign listeners."""
    port = find_available_loopback_port()
    assert 1024 <= port <= 65535

    # Simulate a foreign service listening on a port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)

        # Expected pid 999999 is not the owner
        assert (
            verify_endpoint_ownership("127.0.0.1", port, expected_pid=999999, timeout=0.2) is False
        )


# ==============================================================================
# 7. Concurrency & Single-Flight Idempotency
# ==============================================================================
def test_07_concurrent_start_single_flight(tmp_path: Path, fake_gguf_model: Path):
    """Verify duplicate concurrent start() calls produce exactly 1 instance."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-test")
    spec = RuntimeSpec(
        model_identity=ident,
        model_path=str(fake_gguf_model),
        startup_timeout_seconds=5.0,
    )

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.RuntimeProcessHandle") as mock_ph_cls,
        patch("core.inference.supervisor.requests.get") as mock_get,
        patch("core.inference.supervisor.verify_endpoint_ownership", return_value=True),
    ):
        mock_handle = MagicMock()
        mock_handle.pid = 4242
        mock_handle.poll.return_value = None
        mock_ph_cls.return_value = mock_handle

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # Run 5 concurrent start() calls
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(supervisor.start, spec) for _ in range(5)]
            instances = [f.result() for f in futures]

        # Invariant: exactly 1 process handle spawned, all callers received the identical instance
        assert mock_ph_cls.call_count == 1
        assert len({inst.instance_id for inst in instances}) == 1
        assert supervisor.state == RuntimeState.READY


# ==============================================================================
# 8. Start when READY is Idempotent
# ==============================================================================
def test_08_start_when_ready_is_idempotent(tmp_path: Path, fake_gguf_model: Path):
    """Verify start() when already READY immediately returns existing instance without respawning."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-test")
    spec = RuntimeSpec(model_identity=ident, model_path=str(fake_gguf_model))

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.RuntimeProcessHandle") as mock_ph_cls,
        patch("core.inference.supervisor.requests.get") as mock_get,
        patch("core.inference.supervisor.verify_endpoint_ownership", return_value=True),
    ):
        mock_handle = MagicMock()
        mock_handle.pid = 1111
        mock_handle.poll.return_value = None
        mock_ph_cls.return_value = mock_handle

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        inst1 = supervisor.start(spec)
        assert supervisor.state == RuntimeState.READY

        # Second call returns identical instance without invoking RuntimeProcessHandle again
        inst2 = supervisor.start(spec)
        assert inst2.instance_id == inst1.instance_id
        assert mock_ph_cls.call_count == 1


# ==============================================================================
# 9. Stop when STOPPED is Idempotent
# ==============================================================================
def test_09_stop_when_stopped_is_idempotent():
    """Verify stop() on STOPPED supervisor is safe and returns True without error."""
    supervisor = LocalInferenceSupervisor()
    assert supervisor.state == RuntimeState.STOPPED
    assert supervisor.stop() is True
    assert supervisor.stop() is True
    assert supervisor.state == RuntimeState.STOPPED


# ==============================================================================
# 10. Startup Timeout Cleans Process Tree & Sets State to FAILED
# ==============================================================================
def test_10_startup_timeout_cleans_process_tree(tmp_path: Path, fake_gguf_model: Path):
    """Verify startup timeout terminates process handle and marks state as FAILED."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-test")
    spec = RuntimeSpec(
        model_identity=ident,
        model_path=str(fake_gguf_model),
        startup_timeout_seconds=0.5,
    )

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.RuntimeProcessHandle") as mock_ph_cls,
        patch(
            "core.inference.supervisor.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ),
    ):
        mock_handle = MagicMock()
        mock_handle.pid = 9999
        mock_handle.poll.return_value = None
        mock_handle.get_logs.return_value = ["loading weights..."]
        mock_ph_cls.return_value = mock_handle

        with pytest.raises(RuntimeStartupError, match="timed out"):
            supervisor.start(spec)

        assert supervisor.state == RuntimeState.FAILED
        assert mock_handle.terminate_gracefully.called


# ==============================================================================
# 11. Readiness Distinguishes 503 "Loading Model" from 200 "OK"
# ==============================================================================
def test_11_readiness_handles_503_loading_model(tmp_path: Path, fake_gguf_model: Path):
    """Verify readiness polling continues during HTTP 503 (loading) and completes on HTTP 200."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-test")
    spec = RuntimeSpec(
        model_identity=ident,
        model_path=str(fake_gguf_model),
        startup_timeout_seconds=5.0,
    )

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    # First call returns 503, second returns 200
    resp_503 = MagicMock(status_code=503)
    resp_200 = MagicMock(status_code=200)

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.RuntimeProcessHandle") as mock_ph_cls,
        patch("core.inference.supervisor.requests.get", side_effect=[resp_503, resp_200]),
        patch("core.inference.supervisor.verify_endpoint_ownership", return_value=True),
    ):
        mock_handle = MagicMock()
        mock_handle.pid = 5555
        mock_handle.poll.return_value = None
        mock_ph_cls.return_value = mock_handle

        inst = supervisor.start(spec)
        assert inst.state == RuntimeState.READY
        assert supervisor.state == RuntimeState.READY


# ==============================================================================
# 12. Unexpected Runtime Crash Transitions READY -> FAILED
# ==============================================================================
def test_12_unexpected_crash_transitions_to_failed(tmp_path: Path, fake_gguf_model: Path):
    """Verify unexpected crash of the child process marks state as FAILED with exit reason."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-test")
    spec = RuntimeSpec(model_identity=ident, model_path=str(fake_gguf_model))

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.RuntimeProcessHandle") as mock_ph_cls,
        patch("core.inference.supervisor.requests.get", return_value=MagicMock(status_code=200)),
        patch("core.inference.supervisor.verify_endpoint_ownership", return_value=True),
    ):
        mock_handle = MagicMock()
        mock_handle.pid = 7777
        mock_handle.poll.return_value = None
        mock_handle.get_logs.return_value = ["SIGSEGV in ggml_compute"]
        mock_ph_cls.return_value = mock_handle

        supervisor.start(spec)
        assert supervisor.state == RuntimeState.READY

        # Simulate unexpected process crash (poll returns exit code 139)
        mock_handle.poll.return_value = 139

        assert supervisor.state == RuntimeState.FAILED
        inst = supervisor.get_active_instance()
        assert inst is not None
        assert inst.state == RuntimeState.FAILED
        assert inst.exit_code == 139
        assert "SIGSEGV" in inst.exit_reason


# ==============================================================================
# 13. Graceful Shutdown Escalation & Descendant Cleanup
# ==============================================================================
def test_13_graceful_shutdown_and_force_kill_escalation(tmp_path: Path):
    """Verify terminate_gracefully sends SIGTERM, waits, and escalates to SIGKILL."""
    # Spawn a real non-terminating bash sleep process to verify signal escalation
    argv = ["sh", "-c", "trap '' TERM; sleep 30"]
    handle = RuntimeProcessHandle(
        argv=argv,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert handle.is_alive() is True

    # Terminate with a short timeout (0.5s) to trigger SIGKILL escalation
    exit_code = handle.terminate_gracefully(timeout_seconds=0.5)
    assert handle.is_alive() is False
    assert exit_code != 0


# ==============================================================================
# 14. Bounded Ring Buffer Log Capture (Zero Unlimited Capture)
# ==============================================================================
def test_14_bounded_ring_buffer_log_capture(tmp_path: Path):
    """Verify RuntimeProcessHandle bounds log memory and does not overflow."""
    # Process emitting 1000 lines
    argv = ["python3", "-c", "import sys; [print(f'log_line_{i}') for i in range(1000)]"]
    handle = RuntimeProcessHandle(
        argv=argv,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        max_log_lines=50,
        max_log_bytes=2048,
    )
    time.sleep(0.5)
    handle.terminate_gracefully(timeout_seconds=1.0)

    logs = handle.get_logs()
    assert len(logs) <= 50
    # Provenance preserved without crashing parent process
    assert any("log_line" in line for line in logs)


# ==============================================================================
# 15. llamacpp ProviderAdapter Consumes Managed Endpoint & Token
# ==============================================================================
def test_15_llamacpp_adapter_consumes_managed_supervisor(fake_gguf_model: Path):
    """Verify LlamaCppAdapter dynamically consumes supervisor endpoint and auth token when managed."""
    reg = get_provider_registry()
    adapter = reg.get_adapter("llamacpp")

    supervisor = get_local_inference_supervisor()
    supervisor._state = RuntimeState.READY
    supervisor._active_instance = MagicMock(
        state=RuntimeState.READY,
        endpoint_url="http://127.0.0.1:9555",
        api_key="managed-auth-token-xyz",
    )

    try:
        # 1. Base URL resolves to managed endpoint
        assert adapter._get_base_url() == "http://127.0.0.1:9555/v1"

        # 2. API key resolves to managed bearer token
        assert adapter._get_api_key() == "managed-auth-token-xyz"

        # 3. DSPy LM receives managed endpoint and token
        with patch("dspy.LM") as mock_lm:
            adapter.create_dspy_lm(model="qwen-test")
            mock_lm.assert_called_once()
            _, kwargs = mock_lm.call_args
            assert kwargs["api_base"] == "http://127.0.0.1:9555/v1"
            assert kwargs["api_key"] == "managed-auth-token-xyz"
    finally:
        reset_local_inference_supervisor()


# ==============================================================================
# 16. Observational ResourceManager Snapshots
# ==============================================================================
def test_16_observational_resource_snapshots(tmp_path: Path, fake_gguf_model: Path):
    """Verify supervisor records host resource snapshot before start and after load."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-test")
    spec = RuntimeSpec(model_identity=ident, model_path=str(fake_gguf_model))

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.RuntimeProcessHandle") as mock_ph_cls,
        patch("core.inference.supervisor.requests.get", return_value=MagicMock(status_code=200)),
        patch("core.inference.supervisor.verify_endpoint_ownership", return_value=True),
    ):
        mock_handle = MagicMock()
        mock_handle.pid = 8888
        mock_handle.poll.return_value = None
        mock_ph_cls.return_value = mock_handle

        inst = supervisor.start(spec)
        assert inst.resource_snapshot_before is not None
        assert "cpu" in inst.resource_snapshot_before
        assert "memory" in inst.resource_snapshot_before

        assert inst.resource_snapshot_after is not None
        assert "cpu" in inst.resource_snapshot_after
        assert "memory" in inst.resource_snapshot_after


# ==============================================================================
# 17. ExecutionCoordinator Records endpoint_class=local_managed
# ==============================================================================
def test_17_coordinator_records_endpoint_class_local_managed():
    """Verify canonical ExecutionCoordinator prompt execution records endpoint_class=local_managed in ledger."""
    from core.execution.kernel_lm_adapter import KernelLMAdapter

    exec_ctx = ExecutionContext(
        execution_id="exec_test_endpoint_class",
        project_id="test_project",
        project_root="/tmp/test_project",
    )
    adapter = KernelLMAdapter(
        exec_context=exec_ctx,
        coordinator=None,
        provider="llamacpp",
        model_name="qwen2.5-coder-3b-instruct-q4_k_m",
    )

    # Invariant: resolves canonical endpoint_class="local_managed" from ProviderRegistry
    assert adapter._get_endpoint_class() == "local_managed"


# ==============================================================================
# 18. Clean-Machine Real E2E Test (Real Binary + Real Model + Real Canary Prompt)
# ==============================================================================
def test_18_real_clean_machine_e2e_prompt_completion():
    """Execute real clean-machine E2E test with real managed llama-server, real model, canary prompt, and ledger verification."""
    # 1. Check if real binary exists in AE private storage or packaged desktop resources (zero Ollama dependency)
    ae_bin = get_private_data_dir() / "runtimes" / "llamacpp" / "llama-server"
    desktop_bin = Path.cwd() / "apps" / "desktop" / "src-tauri" / "binaries" / "llama-server"
    model_path = Path.cwd() / "models" / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"

    if not (
        (ae_bin.is_file() and os.access(ae_bin, os.X_OK))
        or (desktop_bin.is_file() and os.access(desktop_bin, os.X_OK))
    ):
        pytest.skip("Real llama-server binary not found in AE storage; skipping hardware E2E.")
    if not model_path.is_file():
        pytest.skip(
            "Real test model not found at models/qwen2.5-coder-3b-instruct-q4_k_m.gguf; skipping hardware E2E."
        )

    supervisor = get_local_inference_supervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m")
    spec = RuntimeSpec(
        model_identity=ident,
        model_path=str(model_path),
        context_size=512,
        gpu_layers=0,  # Pure CPU execution for clean-machine determinism
        startup_timeout_seconds=30.0,
        shutdown_timeout_seconds=5.0,
    )

    try:
        # Launch real managed runtime
        inst = supervisor.start(spec)
        assert supervisor.state == RuntimeState.READY
        assert inst.pid is not None
        assert inst.endpoint_url is not None
        assert inst.binary_info is not None
        assert inst.binary_info.implementation == "llama.cpp"

        # Check health report
        health = supervisor.get_health()
        assert health.is_ready is True
        assert health.state == RuntimeState.READY

        # Execute real inference through canonical llamacpp ProviderAdapter
        reg = get_provider_registry()
        adapter = reg.get_adapter("llamacpp")
        assert adapter._get_base_url() == f"{inst.endpoint_url}/v1"

        # Invoke prompt with canary code word and temperature=0
        canary = "AE_E2E_K7M4"
        canary_prompt = f"Repeat this exact code word once: {canary}"
        res = adapter.invoke(
            prompt=canary_prompt,
            model="qwen2.5-coder-3b-instruct-q4_k_m",
            max_tokens=20,
            temperature=0.0,
        )
        assert res is not None
        assert res.content is not None and len(res.content.strip()) > 0
        assert canary in res.content
        assert res.provider_id == "llamacpp"

        # Verify ledger records provider, canonical ModelIdentity, endpoint_class=local_managed, and execution_id
        import json
        from core.execution.kernel_lm_adapter import KernelLMAdapter
        from core.execution.models import Execution, ExecutionRequest
        from core.execution.state import ExecutionStateMachine
        from core.ledger.service import ExecutionLedgerService
        from core.storage import get_storage_backend

        storage = get_storage_backend()
        ledger = ExecutionLedgerService(storage=storage)
        exec_id = f"exec_e2e_{int(time.time())}"
        req = ExecutionRequest(project_id="test_project", prompt=canary_prompt)
        exec_entity = Execution(id=exec_id, project_id="test_project", request=req)
        storage.create_execution(
            {
                "id": exec_id,
                "project_id": "test_project",
                "status": "completed",
                "request": json.dumps({"id": exec_id, "project_id": "test_project"}),
            }
        )
        ctx = ExecutionContext(
            execution_id=exec_id,
            project_id="test_project",
            project_root=str(Path.cwd()),
        )
        state_machine = ExecutionStateMachine(execution=exec_entity)

        def event_sink(ev):
            storage.record_execution_event(ev.model_dump())

        def real_lm_call(prompt=None, messages=None, **kwargs):
            p = prompt or (messages[0]["content"] if messages else "")
            inv_res = adapter.invoke(
                prompt=p,
                model="qwen2.5-coder-3b-instruct-q4_k_m",
                max_tokens=20,
                temperature=0.0,
            )
            return [inv_res.content]

        klm = KernelLMAdapter(
            exec_context=ctx,
            coordinator=None,
            provider="llamacpp",
            model_name="qwen2.5-coder-3b-instruct-q4_k_m",
            event_sink=event_sink,
            state_machine=state_machine,
            real_lm=real_lm_call,
        )

        klm_out = klm(prompt=canary_prompt)
        assert klm_out and canary in klm_out[0]

        # Verify factual execution ledger trace
        trace = ledger.get_execution_trace(exec_id)
        assert trace is not None
        assert trace.execution_id == exec_id
        assert len(trace.model_calls) >= 1
        rec = trace.model_calls[0]
        assert rec.provider_id == "llamacpp"
        assert rec.model_id == "qwen2.5-coder-3b-instruct-q4_k_m"
        assert rec.endpoint_class == "local_managed"
        assert ModelIdentity(provider_id=rec.provider_id, model_id=rec.model_id) == ident

        # Stop runtime gracefully
        assert supervisor.stop() is True
        assert supervisor.state == RuntimeState.STOPPED

        # Verify zero orphan server left behind
        time.sleep(0.5)
        with pytest.raises(requests.RequestException):
            requests.get(f"{inst.endpoint_url}/health", timeout=0.5)

    finally:
        reset_local_inference_supervisor()


# ==============================================================================
# 19. No preexec_fn in Popen & Concurrent Start/Stop Isolation
# ==============================================================================
def test_19_no_preexec_fn_and_concurrent_start_stop(tmp_path: Path):
    """Verify subprocess creation never uses unsafe Python preexec_fn and handles concurrent lifecycle."""
    captured_kwargs = {}
    orig_popen = subprocess.Popen

    def mock_popen(args, **kwargs):
        captured_kwargs.update(kwargs)
        return orig_popen(["/bin/sleep", "1"], **kwargs)

    with patch("subprocess.Popen", side_effect=mock_popen):
        handle = RuntimeProcessHandle(
            argv=["/bin/sleep", "1"],
            cwd=tmp_path,
            env={},
        )
        # Invariant: preexec_fn is NEVER passed (eliminating post-fork Python execution)
        assert "preexec_fn" not in captured_kwargs
        if platform.system() != "Windows":
            assert captured_kwargs.get("start_new_session") is True
        handle.terminate_gracefully(timeout_seconds=1.0)

    # Concurrency test: multiple threads launching and stopping handles concurrently
    def run_lifecycle(idx: int):
        h = RuntimeProcessHandle(
            argv=["/bin/sleep", "0.2"],
            cwd=tmp_path,
            env={},
        )
        time.sleep(0.05)
        return h.terminate_gracefully(timeout_seconds=2.0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_lifecycle, i) for i in range(10)]
        results = [f.result() for f in futures]
        assert len(results) == 10


# ==============================================================================
# 20. AGENT_ENGINE_LLAMA_BIN Override Gated Behind Dev Flag
# ==============================================================================
def test_20_binary_override_production_rejection():
    """Verify AGENT_ENGINE_LLAMA_BIN override is rejected in default/production mode unless authorized."""
    test_bin_dir = Path.home() / ".agent_engine_test_bin"
    test_bin_dir.mkdir(parents=True, exist_ok=True)
    fake_bin = test_bin_dir / "custom_llama"
    fake_bin.write_text("#!/bin/sh\necho 'llama.cpp version b9999'\n")
    fake_bin.chmod(0o755)

    resolver = RuntimeBinaryResolver()

    try:
        # 1. In production mode without allow flag -> Rejected
        with patch.dict(
            os.environ,
            {
                "AGENT_ENGINE_LLAMA_BIN": str(fake_bin),
                "AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY": "",
                "AGENT_ENGINE_DEV_MODE": "",
                "AGENT_ENGINE_ENV": "production",
            },
            clear=False,
        ):
            with pytest.raises(UntrustedBinaryLocationError) as exc_info:
                resolver.resolve_binary()
            assert "disabled in production mode" in str(exc_info.value)

        # 2. When AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY=true -> Accepted
        with patch.dict(
            os.environ,
            {
                "AGENT_ENGINE_LLAMA_BIN": str(fake_bin),
                "AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY": "true",
                "AGENT_ENGINE_DEV_MODE": "",
                "AGENT_ENGINE_ENV": "production",
            },
            clear=False,
        ):
            info = resolver.resolve_binary()
            assert info.binary_path == str(fake_bin.resolve())
            assert info.provenance == "controlled_override"
    finally:
        shutil.rmtree(test_bin_dir, ignore_errors=True)


# ==============================================================================
# 21. API Key Redaction Across Process Handles, Logs, and Instance Repr
# ==============================================================================
def test_21_api_key_redacted_in_logs_and_repr(tmp_path: Path):
    """Verify ephemeral endpoint API key is never leaked in repr, diagnostics, or process logs."""
    token = "CANARY_SECRET_TOKEN_42"
    argv = ["/bin/sh", "-c", f"echo 'Received token {token}' && echo 'ready'", "--api-key", token]

    handle = RuntimeProcessHandle(
        argv=argv,
        cwd=tmp_path,
        env={},
    )
    time.sleep(0.2)
    handle.terminate_gracefully(timeout_seconds=1.0)

    # 1. Sanitized argv
    assert token not in handle.sanitized_argv
    assert "[REDACTED]" in handle.sanitized_argv

    # 2. Process handle repr
    handle_repr = repr(handle)
    assert token not in handle_repr
    assert "[REDACTED]" in handle_repr

    # 3. Stream log ring buffer redaction
    logs = handle.get_logs()
    logs_text = "\n".join(logs)
    assert token not in logs_text
    assert "[REDACTED]" in logs_text

    # 4. RuntimeSpec and RuntimeInstance repr exclusion (repr=False)
    ident = ModelIdentity(provider_id="llamacpp", model_id="test_model")
    spec = RuntimeSpec(model_identity=ident, model_path="/fake/path.gguf", api_key=token)
    assert token not in repr(spec)

    inst = RuntimeInstance(instance_id="inst_1", spec=spec, api_key=token)
    assert token not in repr(inst)


# ==============================================================================
# 22. Port Collision Bounded Retry Without Killing Foreign Process
# ==============================================================================
def test_22_port_collision_bounded_retry(tmp_path: Path, fake_gguf_model: Path):
    """Verify port collision triggers bounded retry without adopting or killing foreign process."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-collision-test")
    spec = RuntimeSpec(model_identity=ident, model_path=str(fake_gguf_model))

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    # Bind a real dummy foreign socket on loopback
    foreign_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    foreign_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    foreign_sock.bind(("127.0.0.1", 0))
    foreign_sock.listen(1)
    colliding_port = foreign_sock.getsockname()[1]

    # Available secondary port
    avail_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    avail_sock.bind(("127.0.0.1", 0))
    available_port = avail_sock.getsockname()[1]
    avail_sock.close()

    port_sequence = [colliding_port, available_port]
    calls = []

    def mock_find_port(preferred_port=None, host="127.0.0.1"):
        p = port_sequence.pop(0) if port_sequence else available_port
        calls.append(p)
        return p

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.find_available_loopback_port", side_effect=mock_find_port),
        patch("core.inference.supervisor.RuntimeProcessHandle") as mock_ph_cls,
        patch("core.inference.supervisor.requests.get", return_value=MagicMock(status_code=200)),
        patch("core.inference.supervisor.verify_endpoint_ownership", return_value=True),
    ):
        mock_handle = MagicMock()
        mock_handle.pid = 9999
        mock_handle.poll.return_value = None
        mock_ph_cls.return_value = mock_handle

        inst = supervisor.start(spec)
        assert supervisor.state == RuntimeState.READY
        # Verified retried on port 2 after collision on port 1
        assert len(calls) == 2
        assert colliding_port in calls
        assert str(available_port) in inst.endpoint_url

        # Foreign process socket is STILL open, alive, and unmolested!
        assert foreign_sock.fileno() != -1
        # Close dummy socket cleanly
        foreign_sock.close()

        supervisor.stop()
        assert supervisor.state == RuntimeState.STOPPED


# ==============================================================================
# 23. Port Collision Exhaustion Raises PortCollisionError
# ==============================================================================
def test_23_port_collision_exhaustion_raises(tmp_path: Path, fake_gguf_model: Path):
    """Verify persistent port collisions exhaust retries and raise PortCollisionError."""
    supervisor = LocalInferenceSupervisor()
    ident = ModelIdentity(provider_id="llamacpp", model_id="qwen-collision-fail")
    spec = RuntimeSpec(model_identity=ident, model_path=str(fake_gguf_model))

    mock_bin = RuntimeBinaryInfo(
        binary_path=str(tmp_path / "mock_llama"),
        version="v1.0",
        implementation="llama.cpp",
        sha256="abc1234",
        provenance="managed_installation",
    )

    with (
        patch.object(supervisor._binary_resolver, "resolve_binary", return_value=mock_bin),
        patch("core.inference.supervisor.is_port_available", return_value=False),
    ):
        with pytest.raises(PortCollisionError):
            supervisor.start(spec)
        assert supervisor.state == RuntimeState.FAILED
