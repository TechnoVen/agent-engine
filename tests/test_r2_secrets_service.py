"""tests/test_r2_secrets_service.py

Comprehensive test suite for Task R2.6: Secrets Service & Runtime Injection.
Covers:
1. Strong value object isolation (SecretReference, SecretMetadata, SecretValue).
2. SecretValue masking across str(), repr(), formatting.
3. SecretValue reveal and use() context manager.
4. SecretsService CRUD lifecycle (create, get_metadata, list_metadata, delete).
5. Keyring backend priority when usable.
6. Encrypted vault fallback when keyring fails or is unavailable.
7. High-entropy key generation and persistence.
8. Vault key file permissions enforcement (0600 on POSIX).
9. AGENT_ENGINE_VAULT_KEY environment override.
10. Rejection of empty/blank AGENT_ENGINE_VAULT_KEY.
11. Vault tamper detection (AES-256-GCM authentication failure).
12. Corrupted key file rejection (< 16 bytes).
13. Elimination of plaintext reveal in FastAPI endpoint (403 Forbidden).
14. GET credential metadata returns masked_value, value=None, revealed=False.
15. Backend-only connection test executes securely without echoing secrets.
16. get_model_provider injects direct API keys without mutating os.environ.
17. ModelRouter.create_lm injects direct API keys without mutating os.environ.
18. CapabilityBoundary.run_subprocess injects env into child without polluting parent os.environ.
19. Project isolation enforced (cross-project resolution rejected).
20. Consumer authorization enforced (unauthorized consumer rejected).
21. Fail-closed on missing secrets.
22. Provider API key resolution hierarchy (scoped -> legacy -> env var read-only).
23. Invalid placeholder keys filtered out.
24. SecretsService singleton lifecycle and reset.
25. Context and ledger scrubbing (no plaintext secret leakage in logs/errors).
"""

from __future__ import annotations

import os
import pathlib
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from core.models import get_model_provider
from core.router.model_router import ModelRouter
from core.security import (
    EncryptedVaultBackend,
    KeyringBackend,
    SecretMetadata,
    SecretReference,
    SecretValue,
    SecretsService,
    VaultIntegrityError,
    get_secrets_service,
    reset_secrets_service,
)
from core.skills.boundary import CapabilityBoundary, SkillPermission
from services.python.server.api import app


# ---------------------------------------------------------------------------
# Test 1: Value Object Isolation (SecretReference & SecretMetadata)
# ---------------------------------------------------------------------------
def test_01_secret_reference_and_metadata_isolation():
    ref = SecretReference(
        provider="openai",
        name="OPENAI_API_KEY",
        scope="production",
        project_id="proj_alpha",
    )
    assert ref.canonical_id == "proj_alpha:production:openai:OPENAI_API_KEY"
    assert ref.to_tuple() == ("proj_alpha", "production", "openai", "OPENAI_API_KEY")
    ref_dict = ref.to_dict()
    assert ref_dict["canonical_id"] == "proj_alpha:production:openai:OPENAI_API_KEY"
    assert "value" not in ref_dict

    # Delimiter injection and path traversal prevention
    with pytest.raises(ValueError, match="Invalid SecretReference"):
        SecretReference(provider="open:ai", name="KEY")
    with pytest.raises(ValueError, match="Invalid SecretReference"):
        SecretReference(provider="openai", name="KEY/../../traversal")
    with pytest.raises(ValueError, match="Invalid SecretReference"):
        SecretReference(provider="openai", name="KEY", scope="scope:with:colons")

    meta = SecretMetadata(
        reference=ref,
        backend="encrypted_vault",
        masked_value="sk-...9999",
        created_at=1000.0,
        updated_at=1005.0,
    )
    meta_dict = meta.to_dict()
    assert meta_dict["masked_value"] == "sk-...9999"
    assert meta_dict["backend"] == "encrypted_vault"
    assert "value" not in meta_dict
    assert not hasattr(meta, "value")


# ---------------------------------------------------------------------------
# Test 2: SecretValue Masking (str, repr, format)
# ---------------------------------------------------------------------------
def test_02_secret_value_masking_str_repr_format():
    secret_str = "sk-super-secret-key-abc123xyz"
    sv = SecretValue(secret_str)

    # Invariants: never leaks via str, repr, or format
    assert str(sv) == "***"
    assert repr(sv) == "<SecretValue: ***>"
    assert f"{sv}" == "***"
    assert f"Authorization: Bearer {sv}" == "Authorization: Bearer ***"
    assert "{!s}".format(sv) == "***"
    assert "{!r}".format(sv) == "<SecretValue: ***>"

    # Secret value cannot be instantiated with non-string
    with pytest.raises(TypeError):
        SecretValue(12345)  # type: ignore


# ---------------------------------------------------------------------------
# Test 3: SecretValue Reveal and use() Context Manager
# ---------------------------------------------------------------------------
def test_03_secret_value_reveal_and_use_context():
    secret_str = "top-secret-token"

    # 1. Unbound SecretValue
    sv_unbound = SecretValue(secret_str)
    assert sv_unbound.reveal() == secret_str
    with sv_unbound.use() as val:
        assert val == secret_str

    # 2. Consumer-bound SecretValue
    sv_bound = SecretValue(secret_str, authorized_consumer="secure_worker")
    assert sv_bound.reveal("secure_worker") == secret_str
    with sv_bound.use("secure_worker") as val:
        assert val == secret_str

    # Consumer mismatch fails closed
    with pytest.raises(PermissionError, match="Consumer mismatch"):
        sv_bound.reveal("intruder")
    with pytest.raises(PermissionError, match="Consumer mismatch"):
        sv_bound.reveal()

    # Explicit wiping clears reference and fails closed
    sv_bound.wipe()
    with pytest.raises(ValueError, match="destroyed or wiped"):
        sv_bound.reveal("secure_worker")


# ---------------------------------------------------------------------------
# Test 4: SecretsService CRUD Lifecycle
# ---------------------------------------------------------------------------
def test_04_secrets_service_crud_lifecycle(tmp_path: pathlib.Path):
    vault_file = tmp_path / "credentials.vault"
    key_file = tmp_path / "vault.key"

    svc = SecretsService(
        preferred_backend_name="vault",
        vault_path=vault_file,
        key_file_path=key_file,
    )

    ref = SecretReference(
        provider="anthropic",
        name="ANTHROPIC_API_KEY",
        scope="default",
        project_id="proj_test",
    )

    # 1. Create
    meta = svc.create(ref, "sk-ant-test-secret-value-12345")
    assert meta.reference == ref
    assert meta.masked_value == "sk-...2345"

    # 2. Get Metadata
    retrieved_meta = svc.get_metadata(ref)
    assert retrieved_meta is not None
    assert retrieved_meta.masked_value == "sk-...2345"
    assert not hasattr(retrieved_meta, "value")

    # 3. List Metadata
    all_meta = svc.list_metadata(project_id="proj_test")
    assert len(all_meta) == 1
    assert all_meta[0].reference.name == "ANTHROPIC_API_KEY"

    # 4. Delete
    deleted = svc.delete(ref)
    assert deleted is True

    # 5. Get Metadata returns None after deletion
    assert svc.get_metadata(ref) is None


# ---------------------------------------------------------------------------
# Test 5: Keyring Backend Priority
# ---------------------------------------------------------------------------
def test_05_keyring_priority_over_vault(tmp_path: pathlib.Path):
    mock_keyring = MagicMock(spec=KeyringBackend)
    mock_keyring.name = "keyring"
    mock_keyring.is_usable.return_value = True

    mock_vault = MagicMock(spec=EncryptedVaultBackend)
    mock_vault.name = "encrypted_vault"

    svc = SecretsService(primary_backend=mock_keyring, fallback_backend=mock_vault)
    assert svc.active_backend_name == "keyring"

    ref = SecretReference(provider="openai", name="OPENAI_API_KEY")
    svc.create(ref, "sk-proj-testkey")

    mock_keyring.set.assert_called_once()
    mock_vault.set.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: Vault Fallback When Keyring Fails
# ---------------------------------------------------------------------------
def test_06_vault_fallback_when_keyring_fails(tmp_path: pathlib.Path):
    mock_keyring = MagicMock(spec=KeyringBackend)
    mock_keyring.name = "keyring"
    mock_keyring.set.side_effect = RuntimeError("Keyring locked or unavailable")

    mock_vault = MagicMock(spec=EncryptedVaultBackend)
    mock_vault.name = "encrypted_vault"

    svc = SecretsService(primary_backend=mock_keyring, fallback_backend=mock_vault)
    ref = SecretReference(provider="gemini", name="GEMINI_API_KEY")

    # Setting secret should catch keyring error and fall back to vault
    meta = svc.create(ref, "AIzaSyTestKey12345")
    assert meta.backend == "encrypted_vault"
    mock_vault.set.assert_called_once()


# ---------------------------------------------------------------------------
# Test 7: High-Entropy Key Generation & Persistence
# ---------------------------------------------------------------------------
def test_07_high_entropy_key_generation_persisted(tmp_path: pathlib.Path):
    vault_file = tmp_path / "vault" / "credentials.vault"
    key_file = tmp_path / "vault" / "vault.key"

    assert not key_file.exists()
    backend = EncryptedVaultBackend(vault_path=vault_file, key_file_path=key_file)
    backend.set("srv", "k", "v")
    assert backend.get("srv", "k") == "v"

    assert key_file.exists()
    with open(key_file, "rb") as f:
        key_data = f.read().strip()

    # Must be 256 bits (64 hex characters)
    assert len(key_data) == 64
    if os.name != "nt":
        mode = key_file.stat().st_mode & 0o777
        assert mode == 0o600


# ---------------------------------------------------------------------------
# Test 8: Vault Key Permissions Enforced (0600 on POSIX)
# ---------------------------------------------------------------------------
def test_08_vault_key_file_permissions_enforced(tmp_path: pathlib.Path):
    if os.name == "nt":
        pytest.skip("POSIX permission checks do not apply on Windows")

    key_file = tmp_path / "insecure_vault.key"
    key_file.write_bytes(b"a" * 64)
    os.chmod(key_file, 0o644)  # Insecure: group/world readable

    with pytest.raises(VaultIntegrityError, match="too permissive; must be 0600"):
        EncryptedVaultBackend(vault_path=tmp_path / "test.vault", key_file_path=key_file)


# ---------------------------------------------------------------------------
# Test 9: AGENT_ENGINE_VAULT_KEY Override
# ---------------------------------------------------------------------------
def test_09_vault_key_env_override(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "pass:env-supplied-high-entropy-master-key-32b")
    vault_file = tmp_path / "env_vault.vault"
    key_file = tmp_path / "should_not_be_created.key"

    backend = EncryptedVaultBackend(vault_path=vault_file, key_file_path=key_file)
    assert not key_file.exists()

    backend.set("srv", "k1", "v1")
    assert backend.get("srv", "k1") == "v1"


# ---------------------------------------------------------------------------
# Test 10: Blank AGENT_ENGINE_VAULT_KEY Rejected
# ---------------------------------------------------------------------------
def test_10_vault_key_env_blank_rejected(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "   \t\n  ")
    vault_file = tmp_path / "blank_env.vault"

    with pytest.raises(VaultIntegrityError, match="empty or blank"):
        EncryptedVaultBackend(vault_path=vault_file)


# ---------------------------------------------------------------------------
# Test 11: Vault Tamper Detection (GCM Authentication Failure)
# ---------------------------------------------------------------------------
def test_11_vault_tamper_detection(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "pass:tamper-proof-seed-key-12345678")
    vault_file = tmp_path / "tamper.vault"
    backend = EncryptedVaultBackend(vault_path=vault_file)

    backend.set("service", "token", "super-confidential-val")
    assert backend.get("service", "token") == "super-confidential-val"

    # Corrupt ciphertext byte
    raw_data = bytearray(vault_file.read_bytes())
    raw_data[-5] ^= 0xFF  # Flip bits in authentication tag / ciphertext
    vault_file.write_bytes(bytes(raw_data))

    # Read must fail closed with VaultIntegrityError
    with pytest.raises(VaultIntegrityError):
        backend.get("service", "token")


# ---------------------------------------------------------------------------
# Test 12: Corrupted Key File Rejected (< 16 bytes)
# ---------------------------------------------------------------------------
def test_12_corrupted_key_file_rejected(tmp_path: pathlib.Path):
    key_file = tmp_path / "short.key"
    key_file.write_bytes(b"short-5b")
    if os.name != "nt":
        os.chmod(key_file, 0o600)

    with pytest.raises(VaultIntegrityError, match="insufficient key material"):
        EncryptedVaultBackend(vault_path=tmp_path / "short.vault", key_file_path=key_file)


# ---------------------------------------------------------------------------
# Test 13: Reveal Query Rejected with 403 Forbidden
# ---------------------------------------------------------------------------
def test_13_reveal_query_rejected_403():
    test_client = TestClient(app)
    # Store a credential first
    set_res = test_client.post(
        "/v1/credentials",
        json={"service": "llm", "key": "REVEAL_TEST_KEY", "value": "sk-reveal-fail-key"},
    )
    assert set_res.status_code == 201

    # Request with reveal=true MUST be permanently blocked with 403 Forbidden
    rev_res = test_client.get("/v1/credentials/llm/REVEAL_TEST_KEY?reveal=true")
    assert rev_res.status_code == 403
    assert "disabled" in rev_res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test 14: GET Credential Metadata Returns Masked Value & No Plaintext
# ---------------------------------------------------------------------------
def test_14_get_credential_metadata_returns_masked():
    test_client = TestClient(app)
    set_res = test_client.post(
        "/v1/credentials",
        json={"service": "llm", "key": "MASK_TEST_KEY", "value": "sk-secret123456789"},
    )
    assert set_res.status_code == 201

    get_res = test_client.get("/v1/credentials/llm/MASK_TEST_KEY")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["masked_value"] == "sk-...6789"
    assert data["value"] is None
    assert data["revealed"] is False


# ---------------------------------------------------------------------------
# Test 15: Backend-Only Connection Testing (Zero Leaks)
# ---------------------------------------------------------------------------
def test_15_backend_only_test_connection_no_leak():
    test_client = TestClient(app)
    raw_secret = "sk-live-supersecrettestkey-donotleak"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"data": []}

        test_res = test_client.post(
            "/v1/credentials/test",
            json={"provider": "openai", "api_key": raw_secret},
        )
        assert test_res.status_code == 200
        resp_data = test_res.json()

        assert resp_data["valid"] is True
        assert resp_data["latency_ms"] >= 0.0
        # The raw secret string must never be returned in response payload
        assert raw_secret not in str(resp_data)


# ---------------------------------------------------------------------------
# Test 16: get_model_provider Injects Keys Directly Without os.environ Pollution
# ---------------------------------------------------------------------------
def test_16_get_model_provider_no_environ_pollution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert "OPENAI_API_KEY" not in os.environ

    with patch("dspy.LM") as mock_lm:
        get_model_provider("openai", api_key="sk-injected-direct-key-888")
        mock_lm.assert_called_once()
        _, kwargs = mock_lm.call_args
        assert kwargs.get("api_key") == "sk-injected-direct-key-888"

    # Critical invariant: parent os.environ must NOT be contaminated
    assert "OPENAI_API_KEY" not in os.environ


# ---------------------------------------------------------------------------
# Test 17: ModelRouter.create_lm Injects Keys Directly Without os.environ Pollution
# ---------------------------------------------------------------------------
def test_17_model_router_create_lm_no_environ_pollution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert "DEEPSEEK_API_KEY" not in os.environ

    router = ModelRouter()
    with patch("dspy.LM") as mock_lm:
        router.create_lm("deepseek", api_key="sk-deepseek-direct-key-999")
        mock_lm.assert_called_once()
        _, kwargs = mock_lm.call_args
        assert kwargs.get("api_key") == "sk-deepseek-direct-key-999"

    # Invariant: os.environ remained clean
    assert "DEEPSEEK_API_KEY" not in os.environ


# ---------------------------------------------------------------------------
# Test 18: Subprocess Env Injection Leaves Parent Environment Clean
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_18_subprocess_env_injection_clean_environment(tmp_path: pathlib.Path):
    workspace = tmp_path / "subproc_ws"
    workspace.mkdir()

    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.EXECUTE],
    )

    secret_key = "TRANSIENT_SUBPROC_SECRET"
    secret_val = "secret_child_value_777"
    assert secret_key not in os.environ

    # Run Python one-liner in subprocess to read child environment
    code = f"import os; print(os.environ.get('{secret_key}', 'MISSING'))"
    returncode, stdout, stderr = await boundary.run_subprocess(
        cmd=["python3", "-c", code],
        cwd=workspace,
        env={**os.environ, secret_key: secret_val},
    )

    assert returncode == 0
    assert stdout.strip() == secret_val

    # Invariant: parent process os.environ is NOT polluted
    assert secret_key not in os.environ


# ---------------------------------------------------------------------------
# Test 19: Project Isolation Enforced
# ---------------------------------------------------------------------------
def test_19_project_isolation_enforced(tmp_path: pathlib.Path):
    vault_file = tmp_path / "proj.vault"
    key_file = tmp_path / "proj.key"
    svc = SecretsService(
        preferred_backend_name="vault", vault_path=vault_file, key_file_path=key_file
    )

    ref = SecretReference(provider="openai", name="OPENAI_API_KEY", project_id="project_alpha")
    svc.create(ref, "sk-alpha-key-12345")

    # Access by matching project succeeds
    val = svc.resolve_for_consumer("worker", ref, context={"project_id": "project_alpha"})
    assert val.reveal("worker") == "sk-alpha-key-12345"

    # Mismatched consumer on reveal fails closed
    with pytest.raises(PermissionError, match="Consumer mismatch"):
        val.reveal("other_consumer")
    with pytest.raises(PermissionError, match="Consumer mismatch"):
        val.reveal()

    # Access by foreign project fails closed with PermissionError
    with pytest.raises(PermissionError, match="Project isolation violation"):
        svc.resolve_for_consumer("worker", ref, context={"project_id": "project_beta"})


# ---------------------------------------------------------------------------
# Test 20: Consumer Authorization Enforced
# ---------------------------------------------------------------------------
def test_20_consumer_authorization_enforced(tmp_path: pathlib.Path):
    vault_file = tmp_path / "auth.vault"
    key_file = tmp_path / "auth.key"
    svc = SecretsService(
        preferred_backend_name="vault", vault_path=vault_file, key_file_path=key_file
    )

    ref = SecretReference(provider="anthropic", name="ANTHROPIC_API_KEY")
    svc.create(ref, "sk-ant-auth-key-12345")

    ctx = {"authorized_consumers": ["executor_main", "pipeline_agent"]}

    # Authorized consumer succeeds
    val = svc.resolve_for_consumer("executor_main", ref, context=ctx)
    assert val.reveal("executor_main") == "sk-ant-auth-key-12345"

    # Mismatched reveal call fails closed
    with pytest.raises(PermissionError, match="Consumer mismatch"):
        val.reveal("unauthorized_agent")

    # Unauthorized consumer fails closed with PermissionError
    with pytest.raises(PermissionError, match="not authorized to resolve secret"):
        svc.resolve_for_consumer("untrusted_plugin", ref, context=ctx)


# ---------------------------------------------------------------------------
# Test 21: Fail-Closed on Missing Secret
# ---------------------------------------------------------------------------
def test_21_fail_closed_on_missing_secret(tmp_path: pathlib.Path):
    vault_file = tmp_path / "missing.vault"
    key_file = tmp_path / "missing.key"
    svc = SecretsService(
        preferred_backend_name="vault", vault_path=vault_file, key_file_path=key_file
    )

    ref = SecretReference(provider="nonexistent", name="MISSING_KEY")
    with pytest.raises(KeyError, match="not found"):
        svc.resolve_for_consumer("worker", ref)


# ---------------------------------------------------------------------------
# Test 22: Provider API Key Resolution Hierarchy
# ---------------------------------------------------------------------------
def test_22_provider_api_key_resolution_hierarchy(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    vault_file = tmp_path / "hierarchy.vault"
    key_file = tmp_path / "hierarchy.key"
    svc = SecretsService(
        preferred_backend_name="vault", vault_path=vault_file, key_file_path=key_file
    )

    monkeypatch.setenv("OPENAI_API_KEY", "env-level-key-555")

    # 1. Fallback resolves from environment (read-only)
    assert svc.get_api_key("openai") == "env-level-key-555"

    # 2. Scoped secret in vault takes precedence over environment
    ref = SecretReference(provider="openai", name="OPENAI_API_KEY")
    svc.create(ref, "vault-level-key-777")
    assert svc.get_api_key("openai") == "vault-level-key-777"


# ---------------------------------------------------------------------------
# Test 23: Invalid Placeholder Keys Filtered Out
# ---------------------------------------------------------------------------
def test_23_invalid_placeholder_keys_filtered(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    vault_file = tmp_path / "filter.vault"
    key_file = tmp_path / "filter.key"
    svc = SecretsService(
        preferred_backend_name="vault", vault_path=vault_file, key_file_path=key_file
    )

    for placeholder in ("changeme", "TODO", "your_key_here", "<your-api-key>", "none", "null"):
        monkeypatch.setenv("OPENAI_API_KEY", placeholder)
        assert svc.get_api_key("openai") is None


# ---------------------------------------------------------------------------
# Test 24: SecretsService Singleton Lifecycle
# ---------------------------------------------------------------------------
def test_24_secrets_service_singleton_lifecycle():
    reset_secrets_service()
    svc1 = get_secrets_service()
    svc2 = get_secrets_service()
    assert svc1 is svc2

    reset_secrets_service()
    svc3 = get_secrets_service()
    assert svc3 is not svc1
    reset_secrets_service()


# ---------------------------------------------------------------------------
# Test 25: Context and Ledger Scrubbing (No Raw Secret Leaks)
# ---------------------------------------------------------------------------
def test_25_context_and_ledger_scrubbing(tmp_path: pathlib.Path):
    raw_secret = "sk-super-secret-must-not-appear-in-trace-999"
    sv = SecretValue(raw_secret)

    # In logging, error strings, repr, or string interpolations, raw_secret must never appear
    log_record = f"Execution context payload: {sv}"
    assert raw_secret not in log_record
    assert log_record == "Execution context payload: ***"

    try:
        raise ValueError(f"Secret operation failed: {sv}")
    except ValueError as e:
        err_msg = str(e)
        assert raw_secret not in err_msg
        assert "***" in err_msg


# ---------------------------------------------------------------------------
# Test 26: AGENT_ENGINE_VAULT_KEY Strict Entropy Contracts
# ---------------------------------------------------------------------------
def test_26_vault_key_entropy_contracts(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    import base64

    # 1. Valid 64-hex key (256-bit raw)
    key_hex = "0123456789abcdef" * 4
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", key_hex)
    b1 = EncryptedVaultBackend(vault_path=tmp_path / "v1.vault")
    b1.set("s", "k", "v1")
    assert b1.get("s", "k") == "v1"

    # 2. Valid 44-character base64 key (32 bytes raw)
    key_b64 = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", key_b64)
    b2 = EncryptedVaultBackend(vault_path=tmp_path / "v2.vault")
    b2.set("s", "k", "v2")
    assert b2.get("s", "k") == "v2"

    # 3. Valid exactly 32 raw bytes key
    key_32b = "x" * 32
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", key_32b)
    b3 = EncryptedVaultBackend(vault_path=tmp_path / "v3.vault")
    b3.set("s", "k", "v3")
    assert b3.get("s", "k") == "v3"

    # 4. Valid human passphrase with 'pass:' prefix
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "pass:correct-horse-battery-staple")
    b4 = EncryptedVaultBackend(vault_path=tmp_path / "v4.vault")
    b4.set("s", "k", "v4")
    assert b4.get("s", "k") == "v4"

    # 5. Valid human passphrase with 'passphrase:' prefix
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "passphrase:another-strong-user-passphrase")
    b5 = EncryptedVaultBackend(vault_path=tmp_path / "v5.vault")
    b5.set("s", "k", "v5")
    assert b5.get("s", "k") == "v5"

    # 6. Rejection of bare 8-char key (fail-closed)
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "12345678")
    with pytest.raises(VaultIntegrityError, match="must be a 256-bit key"):
        EncryptedVaultBackend(vault_path=tmp_path / "fail1.vault")

    # 7. Rejection of arbitrary non-256-bit string without pass: prefix
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "a" * 40)
    with pytest.raises(VaultIntegrityError, match="must be a 256-bit key"):
        EncryptedVaultBackend(vault_path=tmp_path / "fail2.vault")

    # 8. Rejection of empty passphrase
    monkeypatch.setenv("AGENT_ENGINE_VAULT_KEY", "pass:")
    with pytest.raises(VaultIntegrityError, match="passphrase component cannot be empty"):
        EncryptedVaultBackend(vault_path=tmp_path / "fail3.vault")


# ---------------------------------------------------------------------------
# Test 27: Key File Symlink Rejection & Windows ACL Enforcement
# ---------------------------------------------------------------------------
def test_27_key_file_symlink_rejection_and_windows_acl(tmp_path: pathlib.Path):
    # 1. Symlink on key file rejected
    real_key = tmp_path / "real.key"
    real_key.write_bytes(os.urandom(32).hex().encode("utf-8"))
    if os.name != "nt":
        os.chmod(real_key, 0o600)
    symlink_key = tmp_path / "symlink.key"
    try:
        symlink_key.symlink_to(real_key)
        with pytest.raises(VaultIntegrityError, match="Symlink detected at vault key path"):
            EncryptedVaultBackend(vault_path=tmp_path / "s1.vault", key_file_path=symlink_key)
    except OSError:
        pass  # Platform does not permit symlink creation

    # 2. Symlink on parent directory rejected
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir(parents=True, exist_ok=True)
    symlink_dir = tmp_path / "symlink_dir"
    try:
        symlink_dir.symlink_to(real_dir)
        with pytest.raises(VaultIntegrityError, match="Symlink detected at parent directory"):
            EncryptedVaultBackend(
                vault_path=tmp_path / "s2.vault", key_file_path=symlink_dir / "vault.key"
            )
    except OSError:
        pass

    # 3. Windows user-only ACL enforcement verification
    with (
        patch.dict("os.environ", {"USERNAME": "test_agent_user"}, clear=False),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        win_tmp = tmp_path / "win_vault" / ".vault.key.tmp"
        EncryptedVaultBackend._apply_windows_acl(win_tmp)
        assert mock_run.called
        call_args, call_kwargs = mock_run.call_args
        cmd = call_args[0]
        assert cmd[0] == "icacls"
        assert "/inheritance:r" in cmd
        assert "/grant:r" in cmd
        assert "test_agent_user:(R,W)" in cmd
        assert call_kwargs.get("shell") is not True

    # 4. Windows icacls failure raises VaultIntegrityError
    with (
        patch.dict("os.environ", {"USERNAME": "test_agent_user"}, clear=False),
        patch("subprocess.run") as mock_run_fail,
    ):
        mock_run_fail.return_value = MagicMock(returncode=1, stderr="Access denied")
        with pytest.raises(VaultIntegrityError, match="Failed to apply Windows user ACLs"):
            EncryptedVaultBackend._apply_windows_acl(tmp_path / "win_fail.tmp")


# ---------------------------------------------------------------------------
# Test 28: Crash-Safe Legacy Vault Migration
# ---------------------------------------------------------------------------
def test_28_crash_safe_legacy_vault_migration(tmp_path: pathlib.Path):
    import hashlib
    import json
    import platform
    import uuid
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    # Synthesize legacy machine-derived vault
    components = [
        str(uuid.getnode()),
        os.environ.get("USER", os.environ.get("USERNAME", "agent_engine")),
        platform.node(),
        platform.machine(),
    ]
    for mid_path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            if os.path.exists(mid_path):
                with open(mid_path, "r", encoding="utf-8") as f:
                    components.append(f.read().strip())
                break
        except Exception:
            pass

    combined = ":".join(components)
    legacy_seed = hashlib.sha256(combined.encode("utf-8")).digest()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    legacy_key = kdf.derive(legacy_seed)
    payload = {
        "migrated_service": {
            "api_token": {"value": "secret_legacy_migrated_token_12345", "updated_at": 5000.0}
        }
    }
    ciphertext = AESGCM(legacy_key).encrypt(nonce, json.dumps(payload).encode("utf-8"), b"AEVAULT1")

    vault_file = tmp_path / "legacy_migration.vault"
    vault_file.write_bytes(b"AEVAULT1" + salt + nonce + ciphertext)
    bytes_before = vault_file.read_bytes()

    # 1. Failure/interruption during atomic replacement leaves original vault file intact
    k_fail = tmp_path / "k_fail.key"
    k_fail.write_bytes(os.urandom(32).hex().encode("utf-8"))
    if os.name != "nt":
        os.chmod(k_fail, 0o600)
    b_fail = EncryptedVaultBackend(vault_path=vault_file, key_file_path=k_fail)

    with patch("os.replace", side_effect=OSError("Interrupted power loss simulation")):
        with pytest.raises(VaultIntegrityError):
            b_fail.get("migrated_service", "api_token")
        # Ensure file was not corrupted or deleted
        assert vault_file.read_bytes() == bytes_before

    # 2. Successful crash-safe migration re-encrypts with hardened 256-bit key
    b_ok = EncryptedVaultBackend(vault_path=vault_file, key_file_path=tmp_path / "k_ok.key")
    val = b_ok.get("migrated_service", "api_token")
    assert val == "secret_legacy_migrated_token_12345"

    # Vault was rewritten with the new 256-bit key
    bytes_after = vault_file.read_bytes()
    assert bytes_after != bytes_before
    # Can still read correctly using the new hardened key
    assert b_ok.get("migrated_service", "api_token") == "secret_legacy_migrated_token_12345"


# ---------------------------------------------------------------------------
# Test 29: Ambient Environment Fallback Control
# ---------------------------------------------------------------------------
def test_29_ambient_env_fallback_control(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    vault_file = tmp_path / "env_ctl.vault"
    key_file = tmp_path / "env_ctl.key"
    svc = SecretsService(
        preferred_backend_name="vault", vault_path=vault_file, key_file_path=key_file
    )

    monkeypatch.setenv("OPENAI_API_KEY", "env-only-openai-key")

    # 1. Explicit allow_env_fallback=False returns None
    assert svc.get_api_key("openai", allow_env_fallback=False) is None

    # 2. Explicit allow_env_fallback=True resolves key
    assert svc.get_api_key("openai", allow_env_fallback=True) == "env-only-openai-key"

    # 3. In production mode without override, fallback defaults to False
    monkeypatch.setenv("ENV_MODE", "production")
    monkeypatch.delenv("AGENT_ENGINE_ALLOW_ENV_CREDENTIALS", raising=False)
    assert svc.get_api_key("openai") is None

    # 4. AGENT_ENGINE_ALLOW_ENV_CREDENTIALS=1 allows fallback even in production
    monkeypatch.setenv("AGENT_ENGINE_ALLOW_ENV_CREDENTIALS", "1")
    assert svc.get_api_key("openai") == "env-only-openai-key"


# ---------------------------------------------------------------------------
# Test 30: Comprehensive Canary Leak Check Across All Evidence Surfaces
# ---------------------------------------------------------------------------
def test_30_comprehensive_canary_leak_check(tmp_path: pathlib.Path):
    import io
    import logging
    import uuid

    canary = f"CANARY_TOKEN_LEAK_CHECK_{uuid.uuid4().hex}"
    vault_file = tmp_path / "canary.vault"
    key_file = tmp_path / "canary.key"
    svc = SecretsService(
        preferred_backend_name="vault", vault_path=vault_file, key_file_path=key_file
    )

    ref = SecretReference(provider="openai", name="OPENAI_API_KEY", project_id="canary_proj")
    svc.create(ref, canary)

    # 1. SecretReference and SecretMetadata evidence surfaces
    ref_dict = ref.to_dict()
    meta = svc.get_metadata(ref)
    assert meta is not None
    meta_dict = meta.to_dict()
    assert canary not in str(ref_dict)
    assert canary not in str(meta_dict)

    # 2. SecretValue container evidence surfaces
    sec_val = svc.resolve_for_consumer("canary_worker", ref, context={"project_id": "canary_proj"})
    assert canary not in str(sec_val)
    assert canary not in repr(sec_val)
    assert canary not in f"{sec_val}"

    # 3. Logging evidence surface
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    logger = logging.getLogger("canary_test_logger")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.info("Processing execution request for %s with value: %s", ref.canonical_id, sec_val)
    logger.debug("Debug metadata payload: %s", meta_dict)
    handler.flush()
    log_output = log_stream.getvalue()
    assert canary not in log_output

    # 4. Exception / Error evidence surfaces
    try:
        raise RuntimeError(f"Simulated execution failure involving secret: {sec_val}")
    except RuntimeError as ex:
        assert canary not in str(ex)

    # 5. FastAPI HTTP API response evidence surfaces
    client = TestClient(app)
    response = client.get(f"/api/credentials/{ref.provider}")
    assert canary not in response.text

    reveal_response = client.get(f"/api/credentials/{ref.provider}?reveal=true")
    assert canary not in reveal_response.text

    # 6. Wiped SecretValue containment
    sec_val.wipe()
    with pytest.raises(ValueError):
        sec_val.reveal("canary_worker")
