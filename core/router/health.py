import concurrent.futures
import logging
import os
import threading
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger("agent_engine.router.health")


@dataclass
class ProbeResult:
    provider: str
    online: bool
    latency_ms: float
    error: str | None = None
    checked_at: float = 0.0


class HealthProber:
    """Active latency and availability prober for local and cloud LLM providers."""

    def __init__(
        self,
        default_timeout: float = 2.0,
        cache_ttl_seconds: float = 5.0,
    ) -> None:
        self.default_timeout = default_timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self._lock = threading.RLock()
        self._cache: dict[str, ProbeResult] = {}

    def _check_api_key(self, provider: str) -> bool:
        key_map = {
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "groq": "GROQ_API_KEY",
            "kimi": "KIMI_API_KEY",
        }
        env_var = key_map.get(provider.lower())
        if env_var:
            return bool(os.getenv(env_var))
        return True

    def probe_ollama(self, timeout: float | None = None) -> ProbeResult:
        t0 = time.perf_counter()
        to = timeout or self.default_timeout
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        hosts = [base_url, "http://127.0.0.1:11434", "http://localhost:11434"]
        # Deduplicate preserving order
        seen = set()
        unique_hosts = [h for h in hosts if not (h in seen or seen.add(h))]

        last_err = None
        for host in unique_hosts:
            try:
                resp = requests.get(f"{host}/api/tags", timeout=to)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if resp.status_code == 200:
                    return ProbeResult(
                        provider="ollama",
                        online=True,
                        latency_ms=round(elapsed_ms, 2),
                        checked_at=time.time(),
                    )
            except Exception as e:
                last_err = str(e)
                continue

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ProbeResult(
            provider="ollama",
            online=False,
            latency_ms=round(elapsed_ms, 2),
            error=last_err or "Ollama endpoint unreachable",
            checked_at=time.time(),
        )

    def probe_llamacpp(self, timeout: float | None = None) -> ProbeResult:
        t0 = time.perf_counter()
        to = timeout or self.default_timeout
        host_env = os.getenv("LLAMACPP_HOST", "http://127.0.0.1:8080/v1")
        if not host_env.endswith("/v1"):
            host_env = host_env.rstrip("/") + "/v1"
        hosts = [host_env, "http://127.0.0.1:8080/v1", "http://localhost:8080/v1"]
        seen = set()
        unique_hosts = [h for h in hosts if not (h in seen or seen.add(h))]

        last_err = None
        for host in unique_hosts:
            try:
                resp = requests.get(f"{host}/models", timeout=to)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if resp.status_code == 200:
                    return ProbeResult(
                        provider="llamacpp",
                        online=True,
                        latency_ms=round(elapsed_ms, 2),
                        checked_at=time.time(),
                    )
            except Exception as e:
                last_err = str(e)
                continue

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ProbeResult(
            provider="llamacpp",
            online=False,
            latency_ms=round(elapsed_ms, 2),
            error=last_err or "llama.cpp endpoint unreachable",
            checked_at=time.time(),
        )

    def probe_cloud(self, provider: str, timeout: float | None = None) -> ProbeResult:
        t0 = time.perf_counter()
        has_key = self._check_api_key(provider)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if not has_key:
            return ProbeResult(
                provider=provider,
                online=False,
                latency_ms=round(elapsed_ms, 2),
                error="API key missing",
                checked_at=time.time(),
            )
        return ProbeResult(
            provider=provider,
            online=True,
            latency_ms=round(elapsed_ms, 2),
            checked_at=time.time(),
        )

    def probe_provider(
        self,
        provider: str,
        timeout: float | None = None,
        force_refresh: bool = False,
    ) -> ProbeResult:
        """Probe provider with TTL caching."""
        p_name = provider.lower()
        now = time.time()
        with self._lock:
            cached = self._cache.get(p_name)
            if (
                not force_refresh
                and cached is not None
                and (now - cached.checked_at) < self.cache_ttl_seconds
            ):
                return cached

        if p_name == "ollama":
            result = self.probe_ollama(timeout)
        elif p_name in ("llamacpp", "local"):
            result = self.probe_llamacpp(timeout)
        else:
            result = self.probe_cloud(p_name, timeout)

        with self._lock:
            self._cache[p_name] = result
        return result

    def probe_all(
        self,
        providers: list[str] | None = None,
        timeout: float | None = None,
        force_refresh: bool = False,
    ) -> dict[str, ProbeResult]:
        """Probe all target providers in parallel."""
        target_providers = providers or [
            "ollama",
            "llamacpp",
            "gemini",
            "openai",
            "anthropic",
            "deepseek",
            "groq",
            "kimi",
        ]

        results: dict[str, ProbeResult] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(target_providers), 8)
        ) as executor:
            future_to_provider = {
                executor.submit(self.probe_provider, p, timeout, force_refresh): p
                for p in target_providers
            }
            for future in concurrent.futures.as_completed(future_to_provider):
                p = future_to_provider[future]
                try:
                    results[p] = future.result()
                except Exception as e:
                    results[p] = ProbeResult(
                        provider=p,
                        online=False,
                        latency_ms=0.0,
                        error=str(e),
                        checked_at=time.time(),
                    )
        return results

    def get_latency(self, provider: str) -> float | None:
        with self._lock:
            cached = self._cache.get(provider.lower())
            if cached and cached.online:
                return cached.latency_ms
            return None
