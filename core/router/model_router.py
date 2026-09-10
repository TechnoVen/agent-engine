# core/router/model_router.py
import logging
import os
import sys
from typing import Any

import dspy
import requests
from dotenv import load_dotenv

# Ensure core.models is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("agent_engine.router")

# Read configuration from .env
PROVIDER_PRIORITY = os.getenv(
    "PROVIDER_PRIORITY", "ollama,llamacpp,gemini,openai,deepseek,groq,kimi"
).split(",")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "5"))


class ModelRouter:
    """Smart router that selects the best available LLM provider based on health and priority."""

    def __init__(self):
        self.provider_priority = [p.strip() for p in PROVIDER_PRIORITY if p.strip()]
        self._configured_lm = None
        self._configured_label = None

    def _check_api_key(self, provider: str) -> bool:
        """Return True if the provider requires an API key and it is present."""
        key_map = {
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "groq": "GROQ_API_KEY",
            "kimi": "KIMI_API_KEY",
        }
        env_var = key_map.get(provider)
        if env_var:
            return bool(os.getenv(env_var))
        # Local providers (ollama, llamacpp) don't need an API key
        return True

    def check_local_ollama_health(self) -> bool:
        """Check if Ollama is reachable."""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        for host in [base_url, "http://127.0.0.1:11434", "http://localhost:11434"]:
            try:
                resp = requests.get(f"{host}/api/tags", timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    return True
            except Exception:
                continue
        return False

    def check_local_llamacpp_health(self) -> bool:
        """Check if llama.cpp server is reachable."""
        host_env = os.getenv("LLAMACPP_HOST", "http://127.0.0.1:8080/v1")
        if not host_env.endswith("/v1"):
            host_env = host_env.rstrip("/") + "/v1"
        for host in [host_env, "http://127.0.0.1:8080/v1", "http://localhost:8080/v1"]:
            try:
                resp = requests.get(f"{host}/models", timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    return True
            except Exception:
                continue
        return False

    def get_status(self) -> dict[str, Any]:
        """Return health and key status for all providers."""
        providers = [
            "ollama",
            "llamacpp",
            "gemini",
            "openai",
            "anthropic",
            "deepseek",
            "groq",
            "kimi",
        ]
        status = {}
        for p in providers:
            if p == "ollama":
                online = self.check_local_ollama_health()
            elif p == "llamacpp":
                online = self.check_local_llamacpp_health()
            else:
                # For cloud providers, we can't easily ping; we treat as "online" if key is present
                online = self._check_api_key(p)
            status[f"{p}_live"] = online
            status[f"{p}_key_present"] = self._check_api_key(p)

        # Primary and fallback providers
        available = [
            p
            for p in self.provider_priority
            if status.get(f"{p}_live") or status.get(f"{p}_key_present")
        ]
        status["primary_provider"] = (
            available[0]
            if available
            else (self.provider_priority[0] if self.provider_priority else "llamacpp")
        )
        status["fallback_provider"] = available[1] if len(available) > 1 else "llamacpp"
        status["active_model"] = self._configured_label or os.getenv(
            "LOCAL_MODEL_NAME", "qwen2.5-coder-3b-instruct-q4_k_m"
        )
        return status

    def get_available_providers(self) -> list[str]:
        """Return a list of provider names that are currently available (health + key)."""
        status = self.get_status()
        available = []
        for p in [
            "ollama",
            "llamacpp",
            "gemini",
            "openai",
            "anthropic",
            "deepseek",
            "groq",
            "kimi",
        ]:
            if status.get(f"{p}_live", False):
                available.append(p)
        # Also include providers that have a key but we can't health‑check (they'll be tried on demand)
        for p in ["gemini", "openai", "anthropic", "deepseek", "groq", "kimi"]:
            if p not in available and status.get(f"{p}_key_present", False):
                available.append(p)
        return available

    def create_lm(
        self, provider: str, cache: bool = True, num_ctx: int = 4096, **kwargs: Any
    ) -> tuple[dspy.LM, str]:
        """Instantiate a dspy.LM for the given provider using core.models.get_model_provider."""
        from core.models import get_model_provider

        model_name = kwargs.get("model") or kwargs.get("model_name")
        api_key = kwargs.get("api_key")
        if api_key:
            key_name = f"{provider.upper()}_API_KEY"
            os.environ[key_name] = api_key

        lm = get_model_provider(
            provider_name=provider,
            model_name=model_name,
            cache=cache,
            max_tokens=num_ctx,
        )
        if provider == "openai":
            label = f"OpenAI ({model_name or 'gpt-4o-mini'})"
        else:
            label = f"{provider.capitalize()} (ctx={num_ctx})"
        return lm, label

    def initialize_and_configure(
        self, force_provider: str | None = None, cache: bool = True, num_ctx: int = 4096
    ) -> tuple[dspy.LM, str]:
        """
        Select the best provider (or the forced one) and configure dspy.settings.
        Returns the LM and a human‑readable label.
        """
        if force_provider:
            # Check if the forced provider is available
            status = self.get_status()
            if not status.get(f"{force_provider}_live", False) and force_provider not in [
                "ollama",
                "llamacpp",
            ]:
                # For cloud providers, live means key present
                if not status.get(f"{force_provider}_key_present", False):
                    logger.warning(
                        f"Forced provider '{force_provider}' is not available (missing key or offline)."
                    )
                    # Fall through to priority selection
                else:
                    # Even if we can't ping, try it
                    pass
            # Attempt to create it
            try:
                lm, label = self.create_lm(force_provider, cache=cache, num_ctx=num_ctx)
                dspy.settings.configure(lm=lm, cache=cache)
                self._configured_lm = lm
                self._configured_label = label
                logger.info(f"Configured LM: {label}")
                return lm, label
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to initialize forced provider '{force_provider}': {e}")
                # Fall through to priority selection

        # Priority‑based selection
        available = self.get_available_providers()
        logger.info(f"Available providers: {available}")
        for p in self.provider_priority:
            if p in available:
                try:
                    lm, label = self.create_lm(p, cache=cache, num_ctx=num_ctx)
                    dspy.settings.configure(lm=lm, cache=cache)
                    self._configured_lm = lm
                    self._configured_label = label
                    logger.info(f"Configured LM: {label} (selected by priority)")
                    return lm, label
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Failed to initialize {p}: {e}")
                    continue

        # Ultimate fallback: try local llama.cpp directly
        logger.warning("No provider from priority list succeeded; falling back to local llama.cpp.")
        try:
            lm, label = self.create_lm("llamacpp", cache=cache, num_ctx=num_ctx)
            dspy.settings.configure(lm=lm, cache=cache)
            self._configured_lm = lm
            self._configured_label = label
            return lm, label
        except Exception as e:
            logger.critical(f"Even fallback failed: {e}")
            raise RuntimeError(
                "No LLM provider available. Check your configuration and network."
            ) from e

    def get_current_lm(self) -> dspy.LM | None:
        return self._configured_lm

    def get_current_label(self) -> str | None:
        return self._configured_label
