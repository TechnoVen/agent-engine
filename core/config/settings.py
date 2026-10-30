"""Encrypted Local Application Settings Module.

Manages persistent configuration across:
- Providers & Keys
- Models & Routing
- Local Runtime (Ollama / llama.cpp / GPU layers)
- Adapters (MCP, Claude Code, Codex, OpenClaw)
- Channels (Slack, Discord, Telegram, WhatsApp)
- Storage (SQLite, Postgres, ChromaDB)
- Security (Zero-Trust, 60s Approval Timeout, Keychain, Sandbox)
- Appearance (Theme, Font Size, UI Density)

Settings are securely encrypted at rest using AES-256-GCM via EncryptedVaultBackend.
"""

from dataclasses import asdict, dataclass, field
import datetime
import json
import logging
import pathlib
from typing import Any, Dict, Optional

from core.security.credentials import EncryptedVaultBackend

logger = logging.getLogger(__name__)


@dataclass
class ModelSettings:
    default_tier: str = "instant"  # "instant" | "swarm" | "reasoning"
    fallback_tier: str = "swarm"
    temperature: float = 0.7
    max_context_tokens: int = 4000
    hard_ceiling_tokens: int = 32000
    bypass_cache: bool = False


@dataclass
class LocalRuntimeSettings:
    ollama_base_url: str = "http://localhost:11434"
    llamacpp_base_url: str = "http://localhost:8080"
    gpu_layers: int = 33
    cpu_threads: int = 4
    context_length: int = 8192
    auto_detect_gpu: bool = True


@dataclass
class AdapterSettings:
    mcp_enabled: bool = True
    claude_code_adapter: bool = True
    codex_adapter: bool = False
    openclaw_adapter: bool = False
    goose_adapter: bool = False
    cursor_adapter: bool = False


@dataclass
class ChannelSettings:
    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_app_token: Optional[str] = None
    teams_enabled: bool = False
    teams_app_id: Optional[str] = None
    teams_app_password: Optional[str] = None
    teams_tenant_id: Optional[str] = None
    teams_webhook_url: Optional[str] = None
    discord_enabled: bool = False
    discord_webhook_url: Optional[str] = None
    discord_bot_token: Optional[str] = None
    discord_application_id: Optional[str] = None
    discord_public_key: Optional[str] = None
    mattermost_enabled: bool = False
    mattermost_url: Optional[str] = None
    mattermost_bot_token: Optional[str] = None
    mattermost_webhook_secret: Optional[str] = None
    telegram_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    whatsapp_enabled: bool = False


@dataclass
class StorageSettings:
    database_backend: str = "sqlite"  # "sqlite" | "postgres"
    sqlite_path: str = "data/agent_engine.db"
    postgres_url: Optional[str] = None
    chroma_path: str = "data/chroma"
    retention_days: int = 90


@dataclass
class SecuritySettings:
    zero_trust_eval: str = "strict"  # "strict" | "permissive"
    approval_timeout_seconds: int = 60
    ipc_token_enabled: bool = True
    sandbox_mode: str = "standard"  # "standard" | "isolated"
    keychain_backend: str = "auto"  # "auto" | "keychain" | "secretservice" | "vault"


@dataclass
class AppearanceSettings:
    theme: str = "dark"  # "dark" | "light" | "system"
    font_size: str = "base"  # "sm" | "base" | "lg"
    ui_density: str = "comfortable"  # "comfortable" | "compact"
    code_font_family: str = "monospace"


@dataclass
class AppSettings:
    models: ModelSettings = field(default_factory=ModelSettings)
    local_runtime: LocalRuntimeSettings = field(default_factory=LocalRuntimeSettings)
    adapters: AdapterSettings = field(default_factory=AdapterSettings)
    channels: ChannelSettings = field(default_factory=ChannelSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    version: str = "0.1.0"
    updated_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        return cls(
            models=ModelSettings(**data.get("models", {})),
            local_runtime=LocalRuntimeSettings(**data.get("local_runtime", {})),
            adapters=AdapterSettings(**data.get("adapters", {})),
            channels=ChannelSettings(**data.get("channels", {})),
            storage=StorageSettings(**data.get("storage", {})),
            security=SecuritySettings(**data.get("security", {})),
            appearance=AppearanceSettings(**data.get("appearance", {})),
            version=data.get("version", "0.1.0"),
            updated_at=data.get("updated_at", datetime.datetime.now().isoformat()),
        )


class SettingsManager:
    """Manages reading and writing application settings to an encrypted vault."""

    SERVICE_NAME = "app"
    KEY_NAME = "config"

    def __init__(self, vault_path: Optional[pathlib.Path | str] = None) -> None:
        if vault_path is None:
            base_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "data"
            base_dir.mkdir(parents=True, exist_ok=True)
            self.vault_path = base_dir / "settings.encrypted.vault"
        else:
            self.vault_path = pathlib.Path(vault_path)

        self._backend = EncryptedVaultBackend(vault_path=self.vault_path)
        self._cached_settings: Optional[AppSettings] = None

    def load_settings(self) -> AppSettings:
        """Load and decrypt settings. If uninitialized, returns defaults."""
        if self._cached_settings is not None:
            return self._cached_settings

        raw = self._backend.get(self.SERVICE_NAME, self.KEY_NAME)
        if not raw:
            self._cached_settings = AppSettings()
            return self._cached_settings

        try:
            data = json.loads(raw)
            self._cached_settings = AppSettings.from_dict(data)
            return self._cached_settings
        except Exception as e:
            logger.warning(f"Failed to parse encrypted settings ({e}), returning defaults.")
            self._cached_settings = AppSettings()
            return self._cached_settings

    def save_settings(self, updates: Dict[str, Any] | AppSettings) -> AppSettings:
        """Update and persist encrypted settings."""
        current = self.load_settings().to_dict()

        if isinstance(updates, AppSettings):
            new_data = updates.to_dict()
        else:
            new_data = dict(current)
            for section, values in updates.items():
                if isinstance(values, dict) and section in new_data:
                    new_data[section].update(values)
                else:
                    new_data[section] = values

        new_data["updated_at"] = datetime.datetime.now().isoformat()
        settings_obj = AppSettings.from_dict(new_data)

        # Encrypt and persist to vault
        serialized = json.dumps(settings_obj.to_dict())
        self._backend.set(self.SERVICE_NAME, self.KEY_NAME, serialized)
        self._cached_settings = settings_obj
        logger.info("Application settings encrypted and saved successfully.")
        return settings_obj

    def reset_settings(self) -> AppSettings:
        """Reset settings to default."""
        defaults = AppSettings()
        serialized = json.dumps(defaults.to_dict())
        self._backend.set(self.SERVICE_NAME, self.KEY_NAME, serialized)
        self._cached_settings = defaults
        return defaults

    get_settings = load_settings
    update_settings = save_settings


_settings_manager_instance: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    """Singleton getter for SettingsManager."""
    global _settings_manager_instance
    if _settings_manager_instance is None:
        _settings_manager_instance = SettingsManager()
    return _settings_manager_instance
