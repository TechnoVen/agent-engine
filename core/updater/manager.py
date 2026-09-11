"""core/updater/manager.py

Auto-update management subsystem for Agent Engine (Task 2.4 - Milestone M2).
Satisfies ADR-001 (Hybrid Shell) and ADR-008 (Zero-Trust Local Integrity).

Features:
- Multi-channel support: stable, beta, nightly.
- SemVer 2.0.0 parsing and precedence comparison.
- Cryptographic Ed25519 signature verification on update manifests.
- Update feed resolution (HTTP/HTTPS, file://, and local manifest directories).
- Persistent channel configuration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import requests

logger = logging.getLogger("agent_engine.updater")

DEFAULT_CURRENT_VERSION = "0.1.0"
CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "updater_config.json"
KEYS_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "desktop" / "src-tauri" / "keys"


class UpdateChannel(str, Enum):
    STABLE = "stable"
    BETA = "beta"
    NIGHTLY = "nightly"

    @classmethod
    def from_str(cls, val: str) -> UpdateChannel:
        val_clean = val.strip().lower()
        for ch in cls:
            if ch.value == val_clean:
                return ch
        raise ValueError(f"Invalid update channel '{val}'. Choose from: {[c.value for c in cls]}")


@dataclass(frozen=True)
class SemVer:
    """Semantic version parser and comparator adhering to SemVer 2.0.0."""

    major: int
    minor: int
    patch: int
    prerelease: Tuple[Union[str, int], ...] = ()
    build: Tuple[str, ...] = ()
    raw: str = ""

    SEMVER_REGEX = re.compile(
        r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
        r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
        r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+(?P<build>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    )

    @classmethod
    def parse(cls, version_str: str) -> SemVer:
        clean = version_str.strip()
        match = cls.SEMVER_REGEX.match(clean)
        if not match:
            # Fallback for lenient numbers like "0.1"
            parts = clean.lstrip("v").split(".")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                return cls(int(parts[0]), int(parts[1]), 0, raw=clean)
            raise ValueError(f"Invalid semantic version: '{version_str}'")

        major = int(match.group("major"))
        minor = int(match.group("minor"))
        patch = int(match.group("patch"))

        prerelease: List[Union[str, int]] = []
        raw_pre = match.group("prerelease")
        if raw_pre:
            for ident in raw_pre.split("."):
                prerelease.append(int(ident) if ident.isdigit() else ident)

        build: List[str] = []
        raw_build = match.group("build")
        if raw_build:
            build = raw_build.split(".")

        return cls(
            major=major,
            minor=minor,
            patch=patch,
            prerelease=tuple(prerelease),
            build=tuple(build),
            raw=clean,
        )

    @property
    def is_prerelease(self) -> bool:
        return len(self.prerelease) > 0

    @property
    def prerelease_str(self) -> Optional[str]:
        return ".".join(str(p) for p in self.prerelease) if self.prerelease else None

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += f"-{'.'.join(str(p) for p in self.prerelease)}"
        if self.build:
            base += f"+{'.'.join(self.build)}"
        return base

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
            and self.prerelease == other.prerelease
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented

        # 1. Compare major.minor.patch
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

        # 2. Pre-release precedence rule: Normal version has higher precedence than prerelease
        if not self.prerelease and other.prerelease:
            return False
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and not other.prerelease:
            return False

        # 3. Both have pre-release identifiers: compare element by element
        for a, b in zip(self.prerelease, other.prerelease):
            if a == b:
                continue
            # Numeric identifiers have lower precedence than non-numeric
            if isinstance(a, int) and isinstance(b, int):
                return a < b
            if isinstance(a, int) and isinstance(b, str):
                return True
            if isinstance(a, str) and isinstance(b, int):
                return False
            return str(a) < str(b)

        return len(self.prerelease) < len(other.prerelease)

    def __le__(self, other: object) -> bool:
        return self < other or self == other

    def __gt__(self, other: object) -> bool:
        return not (self <= other)

    def __ge__(self, other: object) -> bool:
        return not (self < other)


@dataclass
class UpdateInfo:
    update_available: bool
    current_version: str
    latest_version: str
    channel: str
    release_notes: str = ""
    pub_date: Optional[str] = None
    download_url: Optional[str] = None
    signature: Optional[str] = None
    sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UpdateManager:
    """Manages update channel subscription, manifest checking, and payload validation."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        feed_base_url: Optional[str] = None,
        current_version: str = DEFAULT_CURRENT_VERSION,
    ):
        self.config_path = config_path or CONFIG_PATH
        self.current_version = os.environ.get("AGENT_ENGINE_VERSION", current_version)
        self.feed_base_url = feed_base_url or os.environ.get(
            "AGENT_ENGINE_UPDATE_FEED_URL",
            "https://releases.technoven.com/agent-engine",
        )
        self._cached_public_key: Optional[ed25519.Ed25519PublicKey] = None
        if not self.config_path.is_file():
            self._write_config(
                {
                    "channel": UpdateChannel.STABLE.value,
                    "auto_check": True,
                    "last_checked_at": None,
                }
            )

    def _read_config(self) -> Dict[str, Any]:
        if self.config_path.is_file():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read updater config: {e}")
        return {
            "channel": UpdateChannel.STABLE.value,
            "auto_check": True,
            "last_checked_at": None,
        }

    def _write_config(self, cfg: Dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write updater config: {e}")

    @property
    def channel(self) -> UpdateChannel:
        """Return the active update channel as UpdateChannel enum."""
        return UpdateChannel.from_str(self.get_channel())

    @property
    def feed_url(self) -> str:
        """Return the active feed manifest URL."""
        return f"{self.feed_base_url.rstrip('/')}/{self.get_channel()}.json"

    def get_channel(self) -> str:
        """Get the currently configured update channel."""
        cfg = self._read_config()
        return cfg.get("channel", UpdateChannel.STABLE.value)

    def set_channel(self, channel: Union[str, UpdateChannel]) -> None:
        """Set the active update channel (stable, beta, nightly)."""
        val = channel.value if isinstance(channel, UpdateChannel) else channel
        valid_ch = UpdateChannel.from_str(val)
        cfg = self._read_config()
        cfg["channel"] = valid_ch.value
        self._write_config(cfg)
        logger.info(f"Active update channel set to: {valid_ch.value}")

    def get_status(self) -> Dict[str, Any]:
        """Return the updater status and configuration."""
        cfg = self._read_config()
        return {
            "current_version": self.current_version,
            "channel": cfg.get("channel", UpdateChannel.STABLE.value),
            "auto_check": cfg.get("auto_check", True),
            "last_checked_at": cfg.get("last_checked_at"),
            "feed_url": self.feed_url,
        }

    def _load_public_key(self) -> ed25519.Ed25519PublicKey:
        if self._cached_public_key:
            return self._cached_public_key

        env_pub = os.environ.get("AGENT_ENGINE_PUBLIC_KEY")
        if env_pub:
            if Path(env_pub).is_file():
                data = Path(env_pub).read_bytes()
            else:
                data = env_pub.encode("utf-8")
            self._cached_public_key = serialization.load_pem_public_key(data)
            return self._cached_public_key

        default_pub = KEYS_DIR / "ed25519.pub"
        if default_pub.is_file():
            self._cached_public_key = serialization.load_pem_public_key(default_pub.read_bytes())
            return self._cached_public_key

        raise FileNotFoundError(f"Ed25519 public key not found in {KEYS_DIR}")

    def verify_update_payload(
        self,
        manifest_data: Dict[str, Any],
        public_key_pem: Optional[str] = None,
    ) -> bool:
        """Verify the cryptographic Ed25519 signature of an update manifest."""
        import base64

        sig_b64 = manifest_data.get("_manifest_signature")
        if not sig_b64:
            return False

        try:
            pub_key = (
                serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
                if public_key_pem
                else self._load_public_key()
            )
            canonical_bytes = json.dumps(
                {k: v for k, v in manifest_data.items() if not k.startswith("_")},
                sort_keys=True,
            ).encode("utf-8")
            sig = base64.b64decode(sig_b64)
            pub_key.verify(sig, canonical_bytes)
            return True
        except Exception as e:
            logger.warning(f"Manifest signature verification failed: {e}")
            return False

    def verify_manifest(
        self,
        manifest_data: Dict[str, Any],
        public_key_pem: Optional[str] = None,
    ) -> bool:
        """Alias for verify_update_payload."""
        return self.verify_update_payload(manifest_data, public_key_pem)

    def _resolve_platform_target(self) -> str:
        """Detect current OS platform identifier matching Tauri v2 targets."""
        import platform

        os_name = platform.system().lower()
        arch = platform.machine().lower()

        if os_name == "linux":
            return "linux-x86_64" if arch in ("x86_64", "amd64") else "linux-aarch64"
        elif os_name == "darwin":
            return "darwin-aarch64" if arch in ("arm64", "aarch64") else "darwin-x86_64"
        elif os_name == "windows":
            return "windows-x86_64"
        return "linux-x86_64"

    def _fetch_feed_json(self, channel: str) -> Optional[Dict[str, Any]]:
        """Fetch raw JSON for a given channel feed."""
        return self.fetch_manifest(channel)

    def fetch_manifest(self, channel: str) -> Optional[Dict[str, Any]]:
        """Fetch update manifest for a given channel from HTTP or local filesystem."""
        # 1. Local filesystem path or file:// URL
        if self.feed_base_url.startswith("file://") or os.path.exists(self.feed_base_url):
            base_dir = Path(self.feed_base_url.replace("file://", ""))
            channel_file = base_dir / f"{channel}.json"
            if channel_file.is_file():
                try:
                    with open(channel_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logger.error(f"Failed to read local manifest {channel_file}: {e}")
                    return None

        # 2. HTTP/HTTPS feed URL
        target_url = f"{self.feed_base_url.rstrip('/')}/{channel}.json"
        try:
            resp = requests.get(target_url, timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"Update feed returned HTTP {resp.status_code} for {target_url}")
        except Exception as e:
            logger.debug(f"Could not reach update feed {target_url}: {e}")

        # 3. Fallback: check project dist/updates directory
        dist_updates = (
            Path(__file__).resolve().parent.parent.parent / "dist" / "updates" / f"{channel}.json"
        )
        if dist_updates.is_file():
            try:
                with open(dist_updates, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        return None

    def check_for_updates(
        self,
        channel: Optional[str] = None,
        current_version: Optional[str] = None,
    ) -> UpdateInfo:
        """Check for updates against the configured or specified channel."""
        active_channel = channel or self.get_channel()
        curr_ver_str = current_version or self.current_version
        curr_semver = SemVer.parse(curr_ver_str)

        try:
            manifest = self._fetch_feed_json(active_channel)
        except Exception as e:
            logger.warning(f"Error fetching update manifest for channel '{active_channel}': {e}")
            return UpdateInfo(
                update_available=False,
                current_version=curr_ver_str,
                latest_version=curr_ver_str,
                channel=active_channel,
                release_notes=f"Error checking updates: {e}",
            )

        # Record check timestamp
        cfg = self._read_config()
        cfg["last_checked_at"] = time.time()
        self._write_config(cfg)

        if not manifest:
            return UpdateInfo(
                update_available=False,
                current_version=curr_ver_str,
                latest_version=curr_ver_str,
                channel=active_channel,
                release_notes="",
            )

        manifest_ver_str = manifest.get("version", "").lstrip("v")
        if not manifest_ver_str:
            return UpdateInfo(
                update_available=False,
                current_version=curr_ver_str,
                latest_version=curr_ver_str,
                channel=active_channel,
            )

        try:
            remote_semver = SemVer.parse(manifest_ver_str)
        except Exception as e:
            logger.warning(f"Invalid remote version string '{manifest_ver_str}': {e}")
            return UpdateInfo(
                update_available=False,
                current_version=curr_ver_str,
                latest_version=curr_ver_str,
                channel=active_channel,
            )

        # Cryptographically verify manifest if signed
        if "_manifest_signature" in manifest:
            is_valid = self.verify_manifest(manifest)
            if not is_valid:
                logger.error(
                    "Update manifest failed cryptographic signature verification. Rejecting update."
                )
                raise ValueError("Update manifest cryptographic signature verification failed.")

        target_platform = self._resolve_platform_target()
        platform_info = manifest.get("platforms", {}).get(target_platform, {})

        is_newer = remote_semver > curr_semver

        return UpdateInfo(
            update_available=is_newer,
            current_version=curr_ver_str,
            latest_version=manifest_ver_str,
            channel=active_channel,
            release_notes=manifest.get("notes", ""),
            pub_date=manifest.get("pub_date"),
            download_url=platform_info.get("url"),
            signature=platform_info.get("signature"),
            sha256=platform_info.get("sha256"),
        )


_GLOBAL_UPDATE_MANAGER: Optional[UpdateManager] = None


def get_update_manager() -> UpdateManager:
    """Get or initialize global UpdateManager singleton."""
    global _GLOBAL_UPDATE_MANAGER
    if _GLOBAL_UPDATE_MANAGER is None:
        _GLOBAL_UPDATE_MANAGER = UpdateManager()
    return _GLOBAL_UPDATE_MANAGER


def reset_update_manager() -> None:
    """Reset the global UpdateManager singleton (for tests)."""
    global _GLOBAL_UPDATE_MANAGER
    _GLOBAL_UPDATE_MANAGER = None
