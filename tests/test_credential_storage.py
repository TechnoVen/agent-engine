"""tests/test_credential_storage.py

Comprehensive tests for Task 2.3 — Secure Credential Storage.
Validates:
- OS Keychain and AES-256-GCM Encrypted Vault storage (ADR-008).
- PBKDF2 key derivation and tamper resilience (GCM authentication tag verification).
- Secret masking across logs, APIs, and UI responses.
- CredentialManager lifecycle, fallback behavior, and provider helpers.
- ModelRouter / HealthProber integration.
- All 5 FastAPI REST endpoints under /v1/credentials.
"""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from core.router.health import HealthProber
from core.security import (
    CredentialManager,
    EncryptedVaultBackend,
    VaultIntegrityError,
    mask_secret,
    reset_credential_manager,
)
from services.python.server.api import app


# ---------------------------------------------------------------------------
# Unit Tests: Secret Masking
# ---------------------------------------------------------------------------


def test_mask_secret():
    """Verify sensitive keys are masked correctly and never leaked."""
    assert mask_secret(None) == ""
    assert mask_secret("") == ""
    assert mask_secret("12345") == "******"
    assert mask_secret("123456") == "******"

    # OpenAI-style keys
    masked_openai = mask_secret("sk-proj-abc123456789xyz9876")
    assert masked_openai == "sk-...9876"
    assert "abc123456789xyz" not in masked_openai

    # Gemini-style keys
    masked_gemini = mask_secret("AIzaSyB1234567890abcdef")
    assert masked_gemini.startswith("AIza...")
    assert masked_gemini.endswith("cdef")
    assert "1234567890" not in masked_gemini


# ---------------------------------------------------------------------------
# Unit Tests: Encrypted Vault Backend (AES-256-GCM + PBKDF2)
# ---------------------------------------------------------------------------


def test_encrypted_vault_crud(tmp_path):
    """Test full CRUD cycle using AES-256-GCM Encrypted Vault."""
    vault_file = tmp_path / "test_credentials.vault"
    vault = EncryptedVaultBackend(vault_path=vault_file)

    assert vault.name == "encrypted_vault"
    assert not vault_file.exists()

    # Initial get should return None
    assert vault.get("llm", "OPENAI_API_KEY") is None
    assert not vault.has("llm", "OPENAI_API_KEY")
    assert vault.list() == []

    # Store credentials
    vault.set("llm", "OPENAI_API_KEY", "sk-test-secret-value-123456")
    vault.set("llm", "ANTHROPIC_API_KEY", "sk-ant-test-secret-7890")
    vault.set("database", "PASSWORD", "super_secret_db_pass")

    assert vault_file.exists()
    assert vault.has("llm", "OPENAI_API_KEY")
    assert vault.get("llm", "OPENAI_API_KEY") == "sk-test-secret-value-123456"
    assert vault.get("llm", "ANTHROPIC_API_KEY") == "sk-ant-test-secret-7890"
    assert vault.get("database", "PASSWORD") == "super_secret_db_pass"

    # Verify vault file header
    with open(vault_file, "rb") as f:
        header = f.read(8)
    assert header == b"AEVAULT1"

    # List items (masked)
    items = vault.list()
    assert len(items) == 3
    for item in items:
        assert item["backend"] == "encrypted_vault"
        assert item["masked_value"].startswith("sk-...") or item["masked_value"].startswith(
            "supe..."
        )

    # Filtered list
    llm_items = vault.list(service="llm")
    assert len(llm_items) == 2

    # Delete
    assert vault.delete("llm", "ANTHROPIC_API_KEY") is True
    assert vault.get("llm", "ANTHROPIC_API_KEY") is None
    assert vault.delete("llm", "NON_EXISTENT") is False
    assert len(vault.list(service="llm")) == 1


def test_encrypted_vault_tamper_resilience(tmp_path):
    """Test that tampering with vault bytes raises VaultIntegrityError."""
    vault_file = tmp_path / "tamper_test.vault"
    vault = EncryptedVaultBackend(vault_path=vault_file)

    vault.set("service", "key", "secret-payload-data")
    assert vault.get("service", "key") == "secret-payload-data"

    # Read bytes and corrupt ciphertext/auth tag
    with open(vault_file, "rb") as f:
        content = bytearray(f.read())

    # Tamper with the last byte (part of the GCM auth tag)
    content[-1] ^= 0xFF
    with open(vault_file, "wb") as f:
        f.write(content)

    # Decryption must fail due to GCM authentication tag mismatch
    tampered_vault = EncryptedVaultBackend(vault_path=vault_file)
    with pytest.raises(VaultIntegrityError):
        tampered_vault.get("service", "key")


def test_encrypted_vault_custom_seed(tmp_path):
    """Test that custom AGENT_ENGINE_VAULT_KEY seed secures the vault."""
    vault_file = tmp_path / "custom_seed.vault"

    with patch.dict(os.environ, {"AGENT_ENGINE_VAULT_KEY": "passphrase-alpha"}):
        vault1 = EncryptedVaultBackend(vault_path=vault_file)
        vault1.set("service", "key", "secret-with-seed-alpha")
        assert vault1.get("service", "key") == "secret-with-seed-alpha"

    # Attempt to read with different key seed must fail
    with patch.dict(os.environ, {"AGENT_ENGINE_VAULT_KEY": "wrong-passphrase"}):
        vault2 = EncryptedVaultBackend(vault_path=vault_file)
        with pytest.raises(VaultIntegrityError):
            vault2.get("service", "key")


# ---------------------------------------------------------------------------
# Unit Tests: CredentialManager & Provider Helpers
# ---------------------------------------------------------------------------


def test_credential_manager_lifecycle(tmp_path):
    """Test CredentialManager operations with encrypted vault."""
    vault_file = tmp_path / "mgr_test.vault"
    mgr = CredentialManager(preferred_backend="vault", vault_path=vault_file)

    assert mgr.active_backend_name == "encrypted_vault"

    mgr.set_credential("channels", "SLACK_BOT_TOKEN", "xoxb-1234567890")
    assert mgr.get_credential("channels", "SLACK_BOT_TOKEN") == "xoxb-1234567890"

    items = mgr.list_credentials(service="channels")
    assert len(items) == 1
    assert items[0]["key"] == "SLACK_BOT_TOKEN"
    assert items[0]["masked_value"].startswith("xoxb...")

    assert mgr.delete_credential("channels", "SLACK_BOT_TOKEN") is True
    assert mgr.get_credential("channels", "SLACK_BOT_TOKEN") is None


def test_credential_manager_provider_helpers(tmp_path):
    """Test LLM provider API key resolution and aliases."""
    vault_file = tmp_path / "provider_helpers.vault"
    mgr = CredentialManager(preferred_backend="vault", vault_path=vault_file)

    # Set using provider name
    mgr.set_api_key("openai", "sk-test-openai-credential-key")
    mgr.set_api_key("gemini", "AIzaSyTestGeminiCredentialKey")

    # Get using alias or provider name
    assert mgr.get_api_key("openai") == "sk-test-openai-credential-key"
    assert mgr.get_api_key("OPENAI_API_KEY") == "sk-test-openai-credential-key"
    assert mgr.get_api_key("gemini") == "AIzaSyTestGeminiCredentialKey"
    assert mgr.get_api_key("google") == "AIzaSyTestGeminiCredentialKey"
    assert mgr.get_api_key("GEMINI_API_KEY") == "AIzaSyTestGeminiCredentialKey"

    # List LLM keys
    llm_keys = mgr.list_api_keys()
    assert len(llm_keys) == 2
    keys = {k["key"] for k in llm_keys}
    assert "OPENAI_API_KEY" in keys
    assert "GEMINI_API_KEY" in keys

    # Delete
    assert mgr.delete_api_key("openai") is True
    assert mgr.get_api_key("openai") is None

    # Fallback to os.getenv if not in vault
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-from-env-var"}):
        assert mgr.get_api_key("anthropic") == "sk-ant-from-env-var"
        assert mgr.get_api_key("ANTHROPIC_API_KEY") == "sk-ant-from-env-var"


# ---------------------------------------------------------------------------
# Integration Tests: ModelRouter & HealthProber
# ---------------------------------------------------------------------------


def test_model_router_health_prober_integration(tmp_path):
    """Verify HealthProber discovers credentials stored in CredentialManager without .env."""
    vault_file = tmp_path / "health_prober.vault"
    mgr = CredentialManager(preferred_backend="vault", vault_path=vault_file)

    # Inject into global singleton
    with patch("core.security.credentials._GLOBAL_CREDENTIAL_MANAGER", mgr):
        # Ensure env vars are cleared
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            prober = HealthProber()

            # Without key -> probe_cloud reports API key missing
            res = prober.probe_cloud("groq")
            assert not res.online
            assert res.error == "API key missing"

            # Set key in CredentialManager
            mgr.set_api_key("groq", "gsk_test_groq_credential_key_12345")

            # With key in secure storage -> online is True!
            res2 = prober.probe_cloud("groq")
            assert res2.online
            assert res2.error is None


# ---------------------------------------------------------------------------
# Integration Tests: FastAPI /v1/credentials Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def test_client(tmp_path):
    """Provide a TestClient with a fresh temporary CredentialManager."""
    vault_file = tmp_path / "api_test.vault"
    test_mgr = CredentialManager(preferred_backend="vault", vault_path=vault_file)

    with patch("services.python.server.api.get_credential_manager", return_value=test_mgr):
        with patch("core.security.get_credential_manager", return_value=test_mgr):
            client = TestClient(app)
            yield client
            reset_credential_manager()


def test_api_credentials_crud(test_client):
    """Test all 5 FastAPI credential endpoints."""
    # 1. Initial list should be empty
    res = test_client.get("/v1/credentials")
    assert res.status_code == 200
    assert res.json() == []

    # 2. Store a credential
    payload = {
        "service": "llm",
        "key": "OPENAI_API_KEY",
        "value": "sk-proj-supersecretkey9999",
    }
    post_res = test_client.post("/v1/credentials", json=payload)
    assert post_res.status_code == 201
    data = post_res.json()
    assert data["service"] == "llm"
    assert data["key"] == "OPENAI_API_KEY"
    assert data["masked_value"] == "sk-...9999"
    assert "supersecret" not in data["masked_value"]

    # 3. List credentials (must be masked)
    list_res = test_client.get("/v1/credentials")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 1
    assert items[0]["key"] == "OPENAI_API_KEY"
    assert items[0]["masked_value"] == "sk-...9999"

    # 4. Get credential without reveal (default)
    get_res = test_client.get("/v1/credentials/llm/OPENAI_API_KEY")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["masked_value"] == "sk-...9999"
    assert get_data["value"] is None
    assert get_data["revealed"] is False

    # 5. Get credential with reveal=true
    get_rev_res = test_client.get("/v1/credentials/llm/OPENAI_API_KEY?reveal=true")
    assert get_rev_res.status_code == 200
    rev_data = get_rev_res.json()
    assert rev_data["value"] == "sk-proj-supersecretkey9999"
    assert rev_data["revealed"] is True

    # 6. Delete credential
    del_res = test_client.delete("/v1/credentials/llm/OPENAI_API_KEY")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 7. Get deleted credential returns 404
    get_deleted = test_client.get("/v1/credentials/llm/OPENAI_API_KEY")
    assert get_deleted.status_code == 404

    # 8. Delete non-existent credential returns 404
    del_non_existent = test_client.delete("/v1/credentials/llm/NON_EXISTENT")
    assert del_non_existent.status_code == 404


def test_api_credentials_validation(test_client):
    """Test validation errors for credentials endpoints."""
    # Empty key
    res1 = test_client.post("/v1/credentials", json={"service": "llm", "key": "", "value": "val"})
    assert res1.status_code == 400

    # Empty value
    res2 = test_client.post(
        "/v1/credentials", json={"service": "llm", "key": "KEY", "value": "   "}
    )
    assert res2.status_code == 400


def test_api_credentials_test_endpoint(test_client):
    """Test /v1/credentials/test endpoint with mock responses."""
    # Test with custom provider format check
    res = test_client.post(
        "/v1/credentials/test", json={"provider": "custom_llm", "api_key": "valid_key_token_123"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "custom_llm"
    assert data["valid"] is True
    assert data["error"] is None

    # Test with missing key
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
        res_no_key = test_client.post("/v1/credentials/test", json={"provider": "openai"})
        assert res_no_key.status_code == 200
        data_no_key = res_no_key.json()
        assert data_no_key["valid"] is False
        assert "No API key configured" in data_no_key["error"]
