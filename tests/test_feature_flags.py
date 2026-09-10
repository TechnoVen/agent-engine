import pytest
from fastapi.testclient import TestClient

from core.config import (
    FeatureFlags,
    TenantMode,
    get_feature_flags,
    is_flag_enabled,
    reset_flag_overrides,
    set_flag_override,
)
from services.python.server.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_flags():
    """Reset feature flag overrides before and after each test."""
    reset_flag_overrides()
    yield
    reset_flag_overrides()


def test_default_feature_flags():
    """Verify single-user local-first defaults."""
    flags = get_feature_flags()
    assert isinstance(flags, FeatureFlags)
    assert flags.tenant_mode == TenantMode.SINGLE
    assert flags.enable_multi_user is False
    assert flags.enable_registry is True
    assert flags.enable_cloud_sync is False
    assert flags.enable_acp is False
    assert flags.enable_auto_patch_apply is False

    assert is_flag_enabled("enable_registry") is True
    assert is_flag_enabled("enable_multi_user") is False
    assert is_flag_enabled("tenant_mode") is False  # single is not multi


def test_env_var_feature_flags(monkeypatch):
    """Verify that environment variables correctly override flag values."""
    monkeypatch.setenv("TENANT_MODE", "multi")
    monkeypatch.setenv("ENABLE_MULTI_USER", "true")
    monkeypatch.setenv("ENABLE_REGISTRY", "false")
    monkeypatch.setenv("ENABLE_CLOUD_SYNC", "1")
    monkeypatch.setenv("ENABLE_ACP", "yes")
    monkeypatch.setenv("ENABLE_AUTO_PATCH_APPLY", "on")

    flags = get_feature_flags()
    assert flags.tenant_mode == TenantMode.MULTI
    assert flags.enable_multi_user is True
    assert flags.enable_registry is False
    assert flags.enable_cloud_sync is True
    assert flags.enable_acp is True
    assert flags.enable_auto_patch_apply is True

    assert is_flag_enabled("tenant_mode") is True
    assert is_flag_enabled("enable_registry") is False


def test_runtime_flag_overrides():
    """Verify in-memory runtime overrides take precedence over defaults."""
    assert is_flag_enabled("enable_cloud_sync") is False

    set_flag_override("enable_cloud_sync", True)
    assert is_flag_enabled("enable_cloud_sync") is True

    set_flag_override("tenant_mode", "multi")
    flags = get_feature_flags()
    assert flags.tenant_mode == TenantMode.MULTI

    reset_flag_overrides()
    flags_reset = get_feature_flags()
    assert flags_reset.tenant_mode == TenantMode.SINGLE
    assert is_flag_enabled("enable_cloud_sync") is False


def test_api_flags_endpoint():
    """Verify GET /v1/flags exposes flag configuration."""
    res = client.get("/v1/flags")
    assert res.status_code == 200
    data = res.json()
    assert "flags" in data
    flags = data["flags"]
    assert flags["tenant_mode"] == "single"
    assert flags["enable_registry"] is True


def test_api_flag_override_endpoint():
    """Verify POST /v1/flags/{name} sets runtime override via HTTP."""
    res = client.post("/v1/flags/enable_cloud_sync", json={"value": True})
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Verify reflected in GET /v1/flags
    res2 = client.get("/v1/flags")
    assert res2.json()["flags"]["enable_cloud_sync"] is True


def test_api_endpoint_gating():
    """Verify endpoint is gated when feature flag is disabled."""
    # 1. Enabled by default
    res_enabled = client.get("/v1/registry/search?q=SQL")
    assert res_enabled.status_code == 200

    # 2. Disable flag via runtime override
    set_flag_override("enable_registry", False)
    res_disabled = client.get("/v1/registry/search?q=SQL")
    assert res_disabled.status_code == 404
    assert "disabled" in res_disabled.json()["detail"].lower()

    # 3. Re-enable flag
    set_flag_override("enable_registry", True)
    res_re_enabled = client.get("/v1/registry/search?q=SQL")
    assert res_re_enabled.status_code == 200
