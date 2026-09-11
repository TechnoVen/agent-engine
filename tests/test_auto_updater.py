"""tests/test_auto_updater.py - Comprehensive test suite for Task 2.4 Auto-Update Channel.

Verifies:
1. SemVer 2.0.0 parsing, precedence, and pre-release comparison.
2. Cryptographic update manifest generation, Ed25519 signing, and platform structure.
3. Tamper detection (manifest signature invalidation upon payload modification).
4. UpdateManager channel switching, persistence, and update detection.
5. FastAPI /v1/updater endpoints (GET /status, POST /channel, POST /check).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from core.updater.manager import SemVer, UpdateChannel, UpdateManager
from scripts.generate_update_manifest import (
    canonical_manifest_bytes,
    generate_all_channel_manifests,
    sign_manifest_dict,
    verify_manifest_dict,
)
from services.python.server.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. SemVer 2.0.0 Tests
# ---------------------------------------------------------------------------


def test_semver_basic_parsing() -> None:
    v = SemVer.parse("1.2.3")
    assert v.major == 1
    assert v.minor == 2
    assert v.patch == 3
    assert v.prerelease == ()
    assert v.prerelease_str is None
    assert str(v) == "1.2.3"


def test_semver_prerelease_parsing() -> None:
    v = SemVer.parse("0.2.0-beta.1")
    assert v.major == 0
    assert v.minor == 2
    assert v.patch == 0
    assert v.prerelease == ("beta", 1)
    assert v.prerelease_str == "beta.1"
    assert str(v) == "0.2.0-beta.1"


def test_semver_comparisons() -> None:
    # Major / Minor / Patch comparison
    assert SemVer.parse("0.1.0") < SemVer.parse("0.2.0")
    assert SemVer.parse("0.1.0") < SemVer.parse("0.1.1")
    assert SemVer.parse("1.0.0") > SemVer.parse("0.9.9")
    assert SemVer.parse("1.2.3") == SemVer.parse("1.2.3")

    # Pre-release comparison per SemVer 2.0.0 specification:
    # A normal version has higher precedence than a pre-release version for same (major, minor, patch)
    assert SemVer.parse("0.2.0-alpha.1") < SemVer.parse("0.2.0-beta.1")
    assert SemVer.parse("0.2.0-beta.1") < SemVer.parse("0.2.0-beta.2")
    assert SemVer.parse("0.2.0-beta.2") < SemVer.parse("0.2.0-rc.1")
    assert SemVer.parse("0.2.0-rc.1") < SemVer.parse("0.2.0")

    # Normal lower version is still lower than higher pre-release
    assert SemVer.parse("0.1.0") < SemVer.parse("0.2.0-beta.1")


def test_semver_invalid_string() -> None:
    with pytest.raises(ValueError, match="Invalid semantic version"):
        SemVer.parse("not-a-version")


# ---------------------------------------------------------------------------
# 2. Manifest Generation & Cryptographic Signing Tests
# ---------------------------------------------------------------------------


def test_generate_and_sign_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "updates"
    priv_key_file = tmp_path / "update_priv.key"
    pub_key_file = tmp_path / "update_pub.key"

    # Generate keypair
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_key_file.write_bytes(priv.private_bytes_raw())
    pub_key_file.write_bytes(pub.public_bytes_raw())

    manifests = generate_all_channel_manifests(
        version="0.2.0",
        base_url="https://updates.example.com",
        out_dir=out_dir,
        private_key_path=priv_key_file,
    )

    # Check channels created
    assert "stable" in manifests
    assert "beta" in manifests
    assert "nightly" in manifests
    assert "latest" in manifests

    stable = manifests["stable"]
    assert stable["version"] == "0.2.0"
    assert "_manifest_signature" in stable
    assert stable["_signature_algorithm"] == "ed25519"
    assert "platforms" in stable

    # Verify platform entries
    for platform_key in [
        "linux-x86_64",
        "darwin-aarch64",
        "darwin-x86_64",
        "windows-x86_64",
    ]:
        assert platform_key in stable["platforms"]
        platform_info = stable["platforms"][platform_key]
        assert "url" in platform_info
        assert "signature" in platform_info
        assert "sha256" in platform_info

    # Verify cryptographic signature
    assert verify_manifest_dict(stable, pub_key_file) is True


def test_manifest_tamper_detection(tmp_path: Path) -> None:
    priv_key_file = tmp_path / "update_priv.key"
    pub_key_file = tmp_path / "update_pub.key"

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_key_file.write_bytes(priv.private_bytes_raw())
    pub_key_file.write_bytes(pub.public_bytes_raw())

    manifest = {
        "version": "0.2.0",
        "notes": "Legitimate release notes",
        "pub_date": "2026-09-11T12:00:00Z",
        "platforms": {
            "linux-x86_64": {
                "url": "https://updates.example.com/agent-engine-0.2.0.AppImage",
                "signature": "mock-sig",
                "sha256": "abcdef0123456789",
            }
        },
    }

    signed_manifest = sign_manifest_dict(manifest, priv_key_file)
    assert verify_manifest_dict(signed_manifest, pub_key_file) is True

    # Tamper with version
    tampered_manifest = dict(signed_manifest)
    tampered_manifest["version"] = "9.9.9"
    assert verify_manifest_dict(tampered_manifest, pub_key_file) is False

    # Tamper with notes
    tampered_notes = dict(signed_manifest)
    tampered_notes["notes"] = "Malicious altered release notes"
    assert verify_manifest_dict(tampered_notes, pub_key_file) is False

    # Tamper with platform download URL
    tampered_url = json.loads(json.dumps(signed_manifest))
    tampered_url["platforms"]["linux-x86_64"]["url"] = "https://evil.com/malware.bin"
    assert verify_manifest_dict(tampered_url, pub_key_file) is False


def test_canonical_manifest_bytes_determinism() -> None:
    manifest_a = {"version": "0.1.0", "notes": "test", "_manifest_signature": "sig1"}
    manifest_b = {"notes": "test", "version": "0.1.0", "_manifest_signature": "sig2"}

    # Underscore fields are excluded and keys are sorted
    bytes_a = canonical_manifest_bytes(manifest_a)
    bytes_b = canonical_manifest_bytes(manifest_b)
    assert bytes_a == bytes_b
    assert b"_manifest_signature" not in bytes_a


# ---------------------------------------------------------------------------
# 3. UpdateManager Core Tests
# ---------------------------------------------------------------------------


def test_update_manager_persistence(tmp_path: Path) -> None:
    cfg_file = tmp_path / "updater_config.json"
    mgr = UpdateManager(
        current_version="0.1.0",
        config_path=cfg_file,
    )

    # Initial defaults
    status = mgr.get_status()
    assert status["channel"] == UpdateChannel.STABLE.value
    assert status["current_version"] == "0.1.0"
    assert cfg_file.exists()

    # Change channel to BETA
    mgr.set_channel(UpdateChannel.BETA)
    assert mgr.channel == UpdateChannel.BETA
    assert "beta" in mgr.feed_url

    # Re-instantiate from same config file
    mgr2 = UpdateManager(
        current_version="0.1.0",
        config_path=cfg_file,
    )
    assert mgr2.channel == UpdateChannel.BETA


def test_update_manager_check_newer_version(tmp_path: Path) -> None:
    cfg_file = tmp_path / "updater_config.json"
    mgr = UpdateManager(
        current_version="0.1.0",
        config_path=cfg_file,
    )

    mock_manifest = {
        "version": "0.2.0",
        "notes": "Added cool features",
        "pub_date": "2026-09-11T12:00:00Z",
        "platforms": {
            "linux-x86_64": {
                "url": "https://updates.example.com/bin",
                "signature": "sig-abc",
                "sha256": "hash-123",
            }
        },
    }

    with patch.object(mgr, "_fetch_feed_json", return_value=mock_manifest):
        with patch.object(mgr, "verify_manifest", return_value=True):
            info = mgr.check_for_updates()
            assert info.update_available is True
            assert info.latest_version == "0.2.0"
            assert info.current_version == "0.1.0"
            assert info.release_notes == "Added cool features"
            assert info.download_url == "https://updates.example.com/bin"
            assert info.sha256 == "hash-123"


def test_update_manager_check_same_or_older_version(tmp_path: Path) -> None:
    cfg_file = tmp_path / "updater_config.json"
    mgr = UpdateManager(
        current_version="0.2.0",
        config_path=cfg_file,
    )

    mock_manifest = {
        "version": "0.2.0",
        "notes": "No new updates",
        "platforms": {},
    }

    with patch.object(mgr, "_fetch_feed_json", return_value=mock_manifest):
        with patch.object(mgr, "verify_manifest", return_value=True):
            info = mgr.check_for_updates()
            assert info.update_available is False
            assert info.latest_version == "0.2.0"


def test_update_manager_rejects_unverified_manifest(tmp_path: Path) -> None:
    cfg_file = tmp_path / "updater_config.json"
    mgr = UpdateManager(
        current_version="0.1.0",
        config_path=cfg_file,
    )

    mock_manifest = {
        "version": "0.3.0",
        "notes": "Untrusted update",
        "_manifest_signature": "invalid_sig",
    }

    with patch.object(mgr, "_fetch_feed_json", return_value=mock_manifest):
        with patch.object(mgr, "verify_manifest", return_value=False):
            with pytest.raises(ValueError, match="Update manifest cryptographic signature"):
                mgr.check_for_updates()


def test_update_manager_network_error_graceful_handling(tmp_path: Path) -> None:
    cfg_file = tmp_path / "updater_config.json"
    mgr = UpdateManager(
        current_version="0.1.0",
        config_path=cfg_file,
    )

    with patch.object(mgr, "_fetch_feed_json", side_effect=RuntimeError("Network timeout")):
        info = mgr.check_for_updates()
        assert info.update_available is False
        assert "Network timeout" in info.release_notes


# ---------------------------------------------------------------------------
# 4. Sidecar REST API Endpoints Tests (/v1/updater/*)
# ---------------------------------------------------------------------------


def test_api_updater_status() -> None:
    res = client.get("/v1/updater/status")
    assert res.status_code == 200
    data = res.json()
    assert "current_version" in data
    assert "channel" in data
    assert "feed_url" in data
    assert data["channel"] in ["stable", "beta", "nightly"]


def test_api_updater_set_channel() -> None:
    # Switch to beta
    res = client.post("/v1/updater/channel", json={"channel": "beta"})
    assert res.status_code == 200
    data = res.json()
    assert data["channel"] == "beta"

    # Switch back to stable
    res2 = client.post("/v1/updater/channel", json={"channel": "stable"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["channel"] == "stable"


def test_api_updater_set_invalid_channel() -> None:
    res = client.post("/v1/updater/channel", json={"channel": "invalid_channel"})
    assert res.status_code in [400, 422]


def test_api_updater_check() -> None:
    # Mock manager check_for_updates for deterministic API response
    from core.updater.manager import UpdateInfo

    mock_info = UpdateInfo(
        update_available=True,
        current_version="0.1.0",
        latest_version="0.2.0",
        channel="stable",
        release_notes="Brand new release",
        pub_date="2026-09-11T12:00:00Z",
        download_url="https://updates.example.com/asset",
        signature="sig-123",
        sha256="sha-456",
    )

    with patch("services.python.server.api.get_update_manager") as mock_get_mgr:
        mock_mgr = mock_get_mgr.return_value
        mock_mgr.check_for_updates.return_value = mock_info
        res = client.post("/v1/updater/check", json={"channel": "stable"})
        assert res.status_code == 200
        data = res.json()
        assert data["update_available"] is True
        assert data["latest_version"] == "0.2.0"
        assert data["current_version"] == "0.1.0"
        assert data["release_notes"] == "Brand new release"
        assert data["download_url"] == "https://updates.example.com/asset"
