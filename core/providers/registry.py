"""core/providers/registry.py

Canonical Provider Registry Implementation for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).

Design Invariants:
1. Single authoritative registry for all LLM providers (cloud & local).
2. Stable machine-level provider_id distinct from display names, aliases, and models.
3. Thread-safe operations with deterministic registration, unregistration, and resolution.
4. Legacy configuration migration without breaking existing setups or user configs.
5. Inviolable R2.6 secret isolation: credentials resolved via SecretsService;
   zero global os.environ mutation.
6. Execution ledger integration: records ProviderCallEvidence containing provider_id,
   endpoint class, model, latency, and status with 0 plaintext secrets.
"""

from __future__ import annotations

import logging
import os
import pathlib
from threading import RLock
import time
from typing import Any, Callable, Dict, List, Optional

import yaml

from core.providers.adapters import (
    AnthropicAdapter,
    DeepSeekAdapter,
    GeminiAdapter,
    GroqAdapter,
    KimiAdapter,
    LlamaCppAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    OpenAICompatibleAdapter,
)
from core.providers.base import ProviderAdapter
from core.providers.models import (
    ProviderAuthType,
    ProviderAvailability,
    ProviderCallEvidence,
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderConfigurationState,
    ProviderDefinition,
    ProviderEndpointClass,
    ProviderEndpointStyle,
    ProviderHealth,
    ProviderHealthStatus,
)

logger = logging.getLogger("agent_engine.providers.registry")

_GLOBAL_REGISTRY: Optional[ProviderRegistry] = None
_REGISTRY_LOCK = RLock()

_CANONICAL_ALIAS_MAP: Dict[str, str] = {
    "local": "llamacpp",
    "gemma4": "llamacpp",
    "google": "gemini",
    "moonshot": "kimi",
    "chatgpt": "openai",
    "openai_chat": "openai",
    "claude": "anthropic",
    "ollama_chat": "ollama",
    "openai_compatible": "compatible",
    "vllm": "compatible",
    "localai": "compatible",
}


def migrate_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """Pure transformation function migrating legacy configuration structures into canonical schema.

    Invariants:
    1. Idempotency: migrate(old) == migrate(canonical) == migrate(migrate(old)).
    2. Legacy aliases ('local', 'google', 'moonshot', etc.) normalize to canonical provider IDs.
    3. Generic 'local' is strictly scoped as a legacy migration alias mapping to 'llamacpp'.
    4. Preserves arbitrary user custom properties safely.
    """
    result = dict(config)

    # 1. Normalize default_priority list
    if "default_priority" in result and isinstance(result["default_priority"], list):
        normalized_priority = []
        for item in result["default_priority"]:
            clean = str(item).strip().lower()
            canon = _CANONICAL_ALIAS_MAP.get(clean, clean)
            if canon not in normalized_priority:
                normalized_priority.append(canon)
        result["default_priority"] = normalized_priority

    # 2. Normalize providers dictionary keys if present
    if "providers" in result and isinstance(result["providers"], dict):
        normalized_providers: Dict[str, Any] = {}
        for k, v in result["providers"].items():
            clean_k = str(k).strip().lower()
            canon_k = _CANONICAL_ALIAS_MAP.get(clean_k, clean_k)
            if isinstance(v, dict) and "provider_id" in v:
                v_copy = dict(v)
                v_clean = str(v_copy["provider_id"]).strip().lower()
                v_copy["provider_id"] = _CANONICAL_ALIAS_MAP.get(v_clean, v_clean)
                normalized_providers[canon_k] = v_copy
            else:
                normalized_providers[canon_k] = v
        result["providers"] = normalized_providers

    return result


class ProviderRegistry:
    """Thread-safe authoritative registry managing LLM providers, adapters, and health."""

    def __init__(self, secrets_service: Optional[Any] = None) -> None:
        self._lock = RLock()
        self._providers: Dict[str, ProviderDefinition] = {}
        self._adapters: Dict[str, ProviderAdapter] = {}
        self._adapter_factories: Dict[
            str, Callable[[ProviderDefinition, Optional[Any]], ProviderAdapter]
        ] = {}
        self._aliases: Dict[str, str] = {}
        self._secrets_service = secrets_service
        self._evidence_log: List[ProviderCallEvidence] = []
        self._health_cache_ttl: float = 5.0
        self._last_probe_time: Dict[str, float] = {}

        # Register standard built-in providers
        self._register_builtin_providers()

    def _get_secrets_service(self) -> Optional[Any]:
        if self._secrets_service is not None:
            return self._secrets_service
        try:
            from core.security import get_secrets_service

            self._secrets_service = get_secrets_service()
            return self._secrets_service
        except Exception:
            return None

    def _register_builtin_providers(self) -> None:
        """Register default canonical providers supported by Agent Engine."""

        # 1. OpenAI
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="openai",
                display_name="OpenAI",
                endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
                endpoint_class=ProviderEndpointClass.CLOUD,
                default_endpoint_url="https://api.openai.com/v1",
                default_model="gpt-4o-mini",
                aliases=["chatgpt", "openai_chat"],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=True,
                    supports_json_mode=True,
                    is_local=False,
                    requires_credentials=True,
                    max_context_window=128000,
                ),
                config=ProviderConfiguration(
                    provider_id="openai",
                    endpoint_url="https://api.openai.com/v1",
                    auth_type=ProviderAuthType.API_KEY,
                    credential_key="OPENAI_API_KEY",
                    timeout_seconds=60.0,
                ),
            ),
            adapter_factory=lambda defn, sec: OpenAIAdapter(defn, secrets_service=sec),
        )

        # 2. Anthropic
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="anthropic",
                display_name="Anthropic",
                endpoint_style=ProviderEndpointStyle.ANTHROPIC,
                endpoint_class=ProviderEndpointClass.CLOUD,
                default_endpoint_url="https://api.anthropic.com",
                default_model="claude-3-5-sonnet-20241022",
                aliases=["claude"],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=True,
                    supports_json_mode=True,
                    is_local=False,
                    requires_credentials=True,
                    max_context_window=200000,
                ),
                config=ProviderConfiguration(
                    provider_id="anthropic",
                    endpoint_url="https://api.anthropic.com",
                    auth_type=ProviderAuthType.API_KEY,
                    credential_key="ANTHROPIC_API_KEY",
                    timeout_seconds=60.0,
                ),
            ),
            adapter_factory=lambda defn, sec: AnthropicAdapter(defn, secrets_service=sec),
        )

        # 3. Google Gemini
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="gemini",
                display_name="Google Gemini",
                endpoint_style=ProviderEndpointStyle.GEMINI,
                endpoint_class=ProviderEndpointClass.CLOUD,
                default_endpoint_url="https://generativelanguage.googleapis.com",
                default_model="gemini-2.5-flash",
                aliases=["google"],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=True,
                    supports_json_mode=True,
                    is_local=False,
                    requires_credentials=True,
                    max_context_window=1000000,
                ),
                config=ProviderConfiguration(
                    provider_id="gemini",
                    endpoint_url="https://generativelanguage.googleapis.com",
                    auth_type=ProviderAuthType.API_KEY,
                    credential_key="GEMINI_API_KEY",
                    timeout_seconds=60.0,
                ),
            ),
            adapter_factory=lambda defn, sec: GeminiAdapter(defn, secrets_service=sec),
        )

        # 4. Ollama (Local)
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="ollama",
                display_name="Ollama",
                endpoint_style=ProviderEndpointStyle.OLLAMA,
                endpoint_class=ProviderEndpointClass.LOCAL_EXTERNAL,
                default_endpoint_url="http://localhost:11434",
                default_model="qwen2.5-coder:3b",
                aliases=["ollama_chat"],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=False,
                    supports_json_mode=True,
                    is_local=True,
                    requires_credentials=False,
                    max_context_window=32768,
                    degraded_latency_threshold_ms=5000.0,
                ),
                config=ProviderConfiguration(
                    provider_id="ollama",
                    endpoint_url="http://localhost:11434",
                    auth_type=ProviderAuthType.NONE,
                    timeout_seconds=120.0,
                ),
            ),
            adapter_factory=lambda defn, sec: OllamaAdapter(defn, secrets_service=sec),
        )

        # 5. llama.cpp (Local)
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="llamacpp",
                display_name="llama.cpp",
                endpoint_style=ProviderEndpointStyle.LLAMACPP,
                endpoint_class=ProviderEndpointClass.LOCAL_MANAGED,
                default_endpoint_url="http://localhost:8080/v1",
                default_model="qwen2.5-coder-3b-instruct-q4_k_m",
                aliases=["local", "gemma4"],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=False,
                    supports_vision=False,
                    supports_json_mode=False,
                    is_local=True,
                    requires_credentials=False,
                    max_context_window=32768,
                    degraded_latency_threshold_ms=5000.0,
                ),
                config=ProviderConfiguration(
                    provider_id="llamacpp",
                    endpoint_url="http://localhost:8080/v1",
                    auth_type=ProviderAuthType.NONE,
                    timeout_seconds=120.0,
                ),
            ),
            adapter_factory=lambda defn, sec: LlamaCppAdapter(defn, secrets_service=sec),
        )

        # 6. DeepSeek
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="deepseek",
                display_name="DeepSeek",
                endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
                endpoint_class=ProviderEndpointClass.CLOUD,
                default_endpoint_url="https://api.deepseek.com",
                default_model="deepseek-chat",
                aliases=[],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=False,
                    supports_json_mode=True,
                    is_local=False,
                    requires_credentials=True,
                    max_context_window=64000,
                ),
                config=ProviderConfiguration(
                    provider_id="deepseek",
                    endpoint_url="https://api.deepseek.com",
                    auth_type=ProviderAuthType.API_KEY,
                    credential_key="DEEPSEEK_API_KEY",
                    timeout_seconds=60.0,
                ),
            ),
            adapter_factory=lambda defn, sec: DeepSeekAdapter(defn, secrets_service=sec),
        )

        # 7. Groq
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="groq",
                display_name="Groq",
                endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
                endpoint_class=ProviderEndpointClass.CLOUD,
                default_endpoint_url="https://api.groq.com/openai/v1",
                default_model="llama-3.3-70b-specdec",
                aliases=[],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=False,
                    supports_json_mode=True,
                    is_local=False,
                    requires_credentials=True,
                    max_context_window=128000,
                ),
                config=ProviderConfiguration(
                    provider_id="groq",
                    endpoint_url="https://api.groq.com/openai/v1",
                    auth_type=ProviderAuthType.API_KEY,
                    credential_key="GROQ_API_KEY",
                    timeout_seconds=45.0,
                ),
            ),
            adapter_factory=lambda defn, sec: GroqAdapter(defn, secrets_service=sec),
        )

        # 8. Moonshot Kimi
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="kimi",
                display_name="Moonshot Kimi",
                endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
                endpoint_class=ProviderEndpointClass.CLOUD,
                default_endpoint_url="https://api.moonshot.cn/v1",
                default_model="moonshot-v1-8k",
                aliases=["moonshot"],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=False,
                    supports_json_mode=True,
                    is_local=False,
                    requires_credentials=True,
                    max_context_window=128000,
                ),
                config=ProviderConfiguration(
                    provider_id="kimi",
                    endpoint_url="https://api.moonshot.cn/v1",
                    auth_type=ProviderAuthType.API_KEY,
                    credential_key="KIMI_API_KEY",
                    timeout_seconds=60.0,
                ),
            ),
            adapter_factory=lambda defn, sec: KimiAdapter(defn, secrets_service=sec),
        )

        # 9. Generic OpenAI-Compatible Gateway
        self.register_provider(
            definition=ProviderDefinition(
                provider_id="compatible",
                display_name="OpenAI-Compatible Gateway",
                endpoint_style=ProviderEndpointStyle.OPENAI_COMPATIBLE,
                endpoint_class=ProviderEndpointClass.CUSTOM_REMOTE,
                default_endpoint_url="http://localhost:8080/v1",
                default_model="default",
                aliases=["openai_compatible", "vllm", "localai"],
                capabilities=ProviderCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_vision=False,
                    supports_json_mode=True,
                    is_local=False,
                    requires_credentials=False,
                    max_context_window=32768,
                ),
                config=ProviderConfiguration(
                    provider_id="compatible",
                    endpoint_url="http://localhost:8080/v1",
                    auth_type=ProviderAuthType.NONE,
                    timeout_seconds=60.0,
                ),
            ),
            adapter_factory=lambda defn, sec: OpenAICompatibleAdapter(defn, secrets_service=sec),
        )

    def register_alias(self, alias: str, canonical_id: str) -> None:
        """Register a compatibility alias mapping to a canonical provider ID.

        Enforces shadow protection: an alias cannot shadow an existing canonical provider ID.
        """
        with self._lock:
            alias_clean = alias.strip().lower()
            canon_clean = canonical_id.strip().lower()
            if not alias_clean:
                raise ValueError("Alias cannot be empty")
            if alias_clean in self._providers:
                raise ValueError(
                    f"Alias '{alias_clean}' cannot shadow existing canonical provider ID '{alias_clean}'"
                )
            if canon_clean not in self._providers:
                raise KeyError(
                    f"Canonical provider '{canon_clean}' is not registered in ProviderRegistry"
                )
            self._aliases[alias_clean] = canon_clean

    def register_provider(
        self,
        definition: ProviderDefinition,
        adapter_factory: Optional[
            Callable[[ProviderDefinition, Optional[Any]], ProviderAdapter]
        ] = None,
    ) -> None:
        """Register a provider definition and optional adapter factory."""
        with self._lock:
            pid = definition.provider_id
            # Canonical provider ID takes precedence: remove any stale alias pointing here
            self._aliases.pop(pid, None)

            # Shadow protection: aliases must not shadow existing canonical providers
            for alias in definition.aliases:
                alias_clean = alias.strip().lower()
                if not alias_clean:
                    continue
                if alias_clean in self._providers and alias_clean != pid:
                    raise ValueError(
                        f"Alias '{alias_clean}' cannot shadow existing canonical provider '{alias_clean}'"
                    )

            self._providers[pid] = definition

            # Register valid aliases
            for alias in definition.aliases:
                alias_clean = alias.strip().lower()
                if alias_clean and alias_clean != pid:
                    self._aliases[alias_clean] = pid

            # Register adapter factory or default to OpenAICompatibleAdapter
            if adapter_factory:
                self._adapter_factories[pid] = adapter_factory
            elif pid not in self._adapter_factories:
                self._adapter_factories[pid] = lambda defn, sec: OpenAICompatibleAdapter(
                    defn, secrets_service=sec
                )

            # Invalidate cached adapter instance to ensure fresh initialization with new definition
            self._adapters.pop(pid, None)

    def unregister_provider(self, provider_id: str) -> bool:
        """Remove a provider from the registry. Returns True if removed."""
        with self._lock:
            pid = self.resolve_provider_id(provider_id)
            if pid in self._providers:
                # Remove aliases pointing to this provider
                aliases_to_remove = [k for k, v in self._aliases.items() if v == pid]
                for a in aliases_to_remove:
                    self._aliases.pop(a, None)

                self._providers.pop(pid, None)
                self._adapters.pop(pid, None)
                self._adapter_factories.pop(pid, None)
                return True
            return False

    def resolve_provider_id(self, identifier_or_alias: str) -> str:
        """Resolve a raw identifier or alias to the canonical provider_id."""
        clean = identifier_or_alias.strip().lower()
        # Direct match
        if clean in self._providers:
            return clean
        # Alias match
        if clean in self._aliases:
            return self._aliases[clean]
        return clean

    def get_provider(self, provider_id: str) -> Optional[ProviderDefinition]:
        """Look up provider definition by canonical ID or alias."""
        with self._lock:
            pid = self.resolve_provider_id(provider_id)
            return self._providers.get(pid)

    def get_adapter(self, provider_id: str) -> ProviderAdapter:
        """Obtain the active ProviderAdapter for a given provider."""
        with self._lock:
            pid = self.resolve_provider_id(provider_id)
            if pid not in self._providers:
                raise KeyError(f"Provider '{provider_id}' is not registered in ProviderRegistry")

            if pid not in self._adapters:
                factory = self._adapter_factories[pid]
                sec_svc = self._get_secrets_service()
                self._adapters[pid] = factory(self._providers[pid], sec_svc)

            return self._adapters[pid]

    def list_providers(
        self,
        include_disabled: bool = False,
        local_only: bool = False,
    ) -> List[ProviderDefinition]:
        """List registered provider definitions with filtering options."""
        with self._lock:
            results = []
            for p in self._providers.values():
                if not include_disabled and not p.config.is_enabled:
                    continue
                if local_only and not p.capabilities.is_local:
                    continue
                results.append(p)
            return sorted(results, key=lambda x: x.provider_id)

    def test_connection(self, provider_id: str, timeout: float = 3.0) -> ProviderHealth:
        """Execute an active connection test through the provider adapter."""
        adapter = self.get_adapter(provider_id)
        health = adapter.test_connection(timeout=timeout)
        with self._lock:
            pid = adapter.provider_id
            defn = self.get_provider(pid)
            if defn:
                defn.health = health
            self._last_probe_time[pid] = time.time()
        return health

    def check_health(
        self,
        provider_id: str,
        force_refresh: bool = False,
        timeout: float = 3.0,
    ) -> ProviderHealth:
        """Check provider health, returning cached result if within TTL."""
        pid = self.resolve_provider_id(provider_id)
        defn = self.get_provider(pid)
        if not defn:
            return ProviderHealth(
                status=ProviderHealthStatus.UNAVAILABLE,
                error_message=f"Unknown provider '{provider_id}'",
                last_checked_at=time.time(),
            )

        with self._lock:
            last_checked = self._last_probe_time.get(pid, 0.0)
            now = time.time()
            if not force_refresh and (now - last_checked < self._health_cache_ttl):
                return defn.health

        adapter = self.get_adapter(pid)
        health = adapter.check_health(timeout=timeout)
        with self._lock:
            defn.health = health
            self._last_probe_time[pid] = time.time()
        return health

    def check_all_health(
        self,
        force_refresh: bool = False,
        timeout: float = 3.0,
    ) -> Dict[str, ProviderHealth]:
        """Probe all registered enabled providers and return a status map."""
        results: Dict[str, ProviderHealth] = {}
        with self._lock:
            enabled_ids = [p.provider_id for p in self._providers.values() if p.config.is_enabled]

        for pid in enabled_ids:
            try:
                results[pid] = self.check_health(pid, force_refresh=force_refresh, timeout=timeout)
            except Exception as e:
                results[pid] = ProviderHealth(
                    config_state=ProviderConfigurationState.CONFIGURED,
                    availability=ProviderAvailability.UNAVAILABLE,
                    status=ProviderHealthStatus.UNHEALTHY,
                    error_message=str(e),
                    last_checked_at=time.time(),
                )
        return results

    @staticmethod
    def migrate_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
        """Pure function normalizing configuration dictionaries to canonical provider schemas.

        Guarantees idempotency:
        - migrate(old) == canonical
        - migrate(canonical) == canonical
        - migrate(migrate(old)) == canonical
        """
        return migrate_config_dict(config)

    def migrate_legacy_config(
        self,
        legacy_config: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Migrate legacy configuration settings and environment variables into canonical definitions.

        Supports:
        - core/router/config.yaml or custom dict
        - Environment variables (OLLAMA_BASE_URL, LLAMACPP_HOST, LOCAL_MODEL_NAME, OLLAMA_MODEL)
        - Stored credentials in SecretsService
        Returns the number of provider definitions updated.
        """
        with self._lock:
            migrated_count = 0

            # 1. Inspect environment variables for local provider endpoints
            ollama_url = os.getenv("OLLAMA_BASE_URL")
            if ollama_url and "ollama" in self._providers:
                self._providers["ollama"].config.endpoint_url = ollama_url
                migrated_count += 1

            llamacpp_url = os.getenv("LLAMACPP_HOST")
            if llamacpp_url and "llamacpp" in self._providers:
                self._providers["llamacpp"].config.endpoint_url = llamacpp_url
                migrated_count += 1

            local_model = os.getenv("LOCAL_MODEL_NAME")
            if local_model and "llamacpp" in self._providers:
                self._providers["llamacpp"].default_model = local_model
                migrated_count += 1

            ollama_model = os.getenv("OLLAMA_MODEL")
            if ollama_model and "ollama" in self._providers:
                self._providers["ollama"].default_model = ollama_model
                migrated_count += 1

            # 2. Inspect YAML config file if not explicitly supplied
            cfg_dict = legacy_config
            if cfg_dict is None:
                config_path = pathlib.Path(__file__).parent.parent / "router" / "config.yaml"
                if config_path.exists():
                    try:
                        with open(config_path, "r", encoding="utf-8") as f:
                            cfg_dict = yaml.safe_load(f) or {}
                    except Exception as e:
                        logger.warning("Failed loading router config.yaml: %s", e)

            if cfg_dict:
                # Apply pure normalization first
                normalized_cfg = migrate_config_dict(cfg_dict)
                provider_priority = normalized_cfg.get("default_priority", [])
                for idx, p_name in enumerate(provider_priority):
                    canon_id = self.resolve_provider_id(p_name)
                    if canon_id in self._providers:
                        # Ensure enabled
                        self._providers[canon_id].config.is_enabled = True

            # 3. Check credentials status and update CONFIGURED health
            for pid, defn in self._providers.items():
                if defn.capabilities.requires_credentials:
                    adapter = self.get_adapter(pid)
                    key = adapter.resolve_api_key()
                    if key:
                        defn.health.config_state = ProviderConfigurationState.CONFIGURED
                        defn.health.availability = ProviderAvailability.UNKNOWN
                        defn.health.status = ProviderHealthStatus.UNKNOWN
                        defn.health.probe_type = "config_validation"
                    else:
                        defn.health.config_state = ProviderConfigurationState.UNCONFIGURED
                        defn.health.availability = ProviderAvailability.UNKNOWN
                        defn.health.status = ProviderHealthStatus.UNKNOWN
                        defn.health.error_message = f"No API key configured for {defn.display_name}"
                        defn.health.probe_type = "config_validation"
                else:
                    # Local provider without credentials requirement starts as CONFIGURED
                    defn.health.config_state = ProviderConfigurationState.CONFIGURED
                    defn.health.availability = ProviderAvailability.UNKNOWN
                    defn.health.status = ProviderHealthStatus.UNKNOWN
                    defn.health.probe_type = "config_validation"

            return migrated_count

    def record_invocation_evidence(self, evidence: ProviderCallEvidence) -> None:
        """Append an auditable provider invocation record to the in-memory ledger."""
        with self._lock:
            # Bound in-memory log to last 1000 items
            if len(self._evidence_log) >= 1000:
                self._evidence_log.pop(0)
            self._evidence_log.append(evidence)

    def get_invocation_evidence(self, limit: int = 100) -> List[ProviderCallEvidence]:
        """Retrieve recent invocation evidence records."""
        with self._lock:
            return list(self._evidence_log[-limit:])


def get_provider_registry() -> ProviderRegistry:
    """Obtain the process-wide singleton ProviderRegistry instance."""
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = ProviderRegistry()
            _GLOBAL_REGISTRY.migrate_legacy_config()
        return _GLOBAL_REGISTRY


def reset_provider_registry() -> ProviderRegistry:
    """Reset the singleton ProviderRegistry (for test isolation)."""
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        _GLOBAL_REGISTRY = ProviderRegistry()
        return _GLOBAL_REGISTRY
