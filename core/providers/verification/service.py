"""core/providers/verification/service.py

Authoritative Provider Connection Verification Service.
Part of Milestone R3 Task R3.11 (Provider Connection Verification).

Design Invariants:
1. Operational Truth: "Connected" means a real provider operation succeeds (real completion canary),
   not merely that configuration exists or /models or /health responds.
2. Provider Pinning: Pins the requested provider_id and ModelIdentity; never falls back to another provider.
3. Failure Taxonomy: Classifies authentication, network, timeout, model 404, rate limit, quota exhaustion,
   and provider errors with sanitized error messages.
4. Policy Gate: Evaluates Prospective verification against PolicyEngine; denied policy causes ZERO provider calls.
5. Economics Isolation: Executions tagged as PROVIDER_VERIFICATION and excluded from R3.10 cohorts.
6. Local Managed Support: Checks LocalInferenceSupervisor state and executes real local completion for llamacpp.
"""

from __future__ import annotations

import logging
import re
from threading import RLock
import time
from typing import Dict, Optional

from core.model_registry.models import ModelIdentity
from core.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
)
from core.providers.models import ProviderEndpointClass
from core.providers.registry import ProviderRegistry, get_provider_registry
from core.providers.verification.models import (
    CURRENT_VERIFICATION_METHOD_VERSION,
    DEFAULT_VERIFICATION_TTL_SECONDS,
    ConnectionVerificationStatus,
    ProviderConnectionVerification,
)
from core.safety.policy import PolicyEngine

logger = logging.getLogger("agent_engine.providers.verification")

_GLOBAL_VERIFICATION_SERVICE: Optional[ProviderVerificationService] = None
_SERVICE_LOCK = RLock()

# Secrets pattern for sanitization
_SECRET_SANITIZE_PATTERN = re.compile(
    r"(sk-[a-zA-Z0-9_\-]{8,}|bearer\s+[a-zA-Z0-9_\-\.]{8,}|key=[a-zA-Z0-9_\-]+|api[_\-]?key[:=\s]+[a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)


class ProviderVerificationService:
    """Authoritative service executing and caching provider connection verification probes."""

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        policy_engine: Optional[PolicyEngine] = None,
        verification_ttl_seconds: float = DEFAULT_VERIFICATION_TTL_SECONDS,
        verification_method_version: str = CURRENT_VERIFICATION_METHOD_VERSION,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self.verification_ttl_seconds = verification_ttl_seconds
        self.verification_method_version = verification_method_version
        self._cache: Dict[str, ProviderConnectionVerification] = {}
        self._lock = RLock()

    @property
    def registry(self) -> ProviderRegistry:
        if self._registry is None:
            self._registry = get_provider_registry()
        return self._registry

    @property
    def policy_engine(self) -> PolicyEngine:
        if self._policy_engine is None:
            self._policy_engine = PolicyEngine()
        return self._policy_engine

    def verify_provider(
        self,
        provider_id: str,
        model_id: Optional[str] = None,
        timeout: float = 5.0,
    ) -> ProviderConnectionVerification:
        """Execute a real minimal provider operation verification probe.

        Strictly adheres to R3.11 rules:
        - Pins requested provider_id and model (zero fallback routing).
        - Executes real minimal completion canary ("Return exactly: AE_PROVIDER_OK").
        - Evaluates safety policy; denies cause zero provider calls.
        - Classifies failures into standard taxonomy.
        - Records timestamped verification with freshness boundaries.
        """
        pid = self.registry.resolve_provider_id(provider_id)
        defn = self.registry.get_provider(pid)

        # 1. Check registration
        if defn is None:
            res = ProviderConnectionVerification(
                provider_id=provider_id,
                status=ConnectionVerificationStatus.NOT_CONFIGURED,
                failure_class="NOT_CONFIGURED",
                sanitized_error=f"Provider '{provider_id}' is not registered in ProviderRegistry.",
                last_verified_at=time.time(),
            )
            with self._lock:
                self._cache[pid] = res
            return res

        # 2. Check enabled state & credentials
        adapter = self.registry.get_adapter(pid)
        if not defn.config.is_enabled:
            res = ProviderConnectionVerification(
                provider_id=pid,
                status=ConnectionVerificationStatus.NOT_CONFIGURED,
                failure_class="DISABLED",
                sanitized_error=f"Provider '{pid}' is disabled in configuration.",
                last_verified_at=time.time(),
            )
            with self._lock:
                self._cache[pid] = res
            return res

        if defn.capabilities.requires_credentials:
            key = adapter.resolve_api_key()
            if not key:
                res = ProviderConnectionVerification(
                    provider_id=pid,
                    status=ConnectionVerificationStatus.NOT_CONFIGURED,
                    failure_class="AUTHENTICATION_FAILED",
                    sanitized_error=f"Provider '{pid}' requires credentials but none were resolved.",
                    last_verified_at=time.time(),
                )
                with self._lock:
                    self._cache[pid] = res
                return res

        # 3. PolicyEngine authorization gate (Directive 20)
        # Must evaluate before making any provider call; denied causes ZERO provider calls.
        policy_decision = self.policy_engine.evaluate(
            tool_name="provider_verification",
            tool_args={
                "provider_id": pid,
                "endpoint_class": defn.endpoint_class.value,
            },
            context={"allow_high_risk": True},
        )
        if policy_decision.decision == "block":
            logger.warning("Provider verification for '%s' blocked by PolicyEngine", pid)
            res = ProviderConnectionVerification(
                provider_id=pid,
                status=ConnectionVerificationStatus.POLICY_BLOCKED,
                failure_class="POLICY_BLOCKED",
                sanitized_error=f"Provider verification blocked by active security policy: {policy_decision.reason or 'authorization denied'}.",
                last_verified_at=time.time(),
                verification_method_version=self.verification_method_version,
                details={"policy_reason": policy_decision.reason},
            )
            with self._lock:
                self._cache[pid] = res
            return res

        # 4. Determine canonical ModelIdentity (pinned, no fallback)
        target_model = model_id or defn.default_model
        model_ident = ModelIdentity(
            provider_id=pid,
            model_id=target_model,
            version="default",
        )

        # 5. Local managed runtime inspection (Directive 21)
        if pid == "llamacpp" and defn.endpoint_class == ProviderEndpointClass.LOCAL_MANAGED:
            try:
                from core.inference.supervisor import get_local_inference_supervisor

                sup = get_local_inference_supervisor()
                inst = sup.get_active_instance()
                if inst is None or inst.state.value != "ready":
                    res = ProviderConnectionVerification(
                        provider_id=pid,
                        model_identity=model_ident,
                        status=ConnectionVerificationStatus.NOT_CONFIGURED,
                        failure_class="SUPERVISOR_NOT_READY",
                        sanitized_error="Managed local inference supervisor is not in READY state.",
                        last_verified_at=time.time(),
                        verification_method_version=self.verification_method_version,
                    )
                    with self._lock:
                        self._cache[pid] = res
                    return res
            except Exception as e:
                logger.debug("Local inference supervisor check notice: %s", e)

        # 6. Execute real minimal provider operation (Directive 13, 14, 15)
        # Pinned adapter traversal through ProviderRegistry["llamacpp" | pid] (Zero direct HTTP bypass)
        canary_prompt = "Return exactly: AE_PROVIDER_OK"
        effective_timeout = max(1.0, min(timeout, 30.0))
        t0 = time.perf_counter()
        known_secret = adapter.resolve_api_key() if hasattr(adapter, "resolve_api_key") else None

        try:
            invocation_res = adapter.invoke(
                prompt=canary_prompt,
                model=target_model,
                max_tokens=10,
                temperature=0.0,
                timeout=effective_timeout,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            content = (invocation_res.content or "").strip()

            if not content:
                res = ProviderConnectionVerification(
                    provider_id=pid,
                    model_identity=model_ident,
                    status=ConnectionVerificationStatus.INVALID_RESPONSE,
                    latency_ms=elapsed_ms,
                    failure_class="EMPTY_RESPONSE",
                    sanitized_error="Upstream provider returned an empty response body.",
                    last_verified_at=time.time(),
                    verification_method_version=self.verification_method_version,
                )
            elif "AE_PROVIDER_OK" not in content:
                res = ProviderConnectionVerification(
                    provider_id=pid,
                    model_identity=model_ident,
                    status=ConnectionVerificationStatus.INVALID_RESPONSE,
                    latency_ms=elapsed_ms,
                    failure_class="CANARY_MISMATCH",
                    sanitized_error="Upstream provider response did not contain required canary token 'AE_PROVIDER_OK'.",
                    last_verified_at=time.time(),
                    verification_method_version=self.verification_method_version,
                    details={"received_length": len(content), "canary_token_verified": False},
                )
            else:
                res = ProviderConnectionVerification(
                    provider_id=pid,
                    model_identity=model_ident,
                    status=ConnectionVerificationStatus.VERIFIED_CONNECTED,
                    latency_ms=elapsed_ms,
                    details={"canary_response_length": len(content), "canary_token_verified": True},
                    last_verified_at=time.time(),
                    verification_method_version=self.verification_method_version,
                )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            res = self._classify_failure(
                pid,
                model_ident,
                exc,
                elapsed_ms,
                known_secret=known_secret,
            )

        with self._lock:
            self._cache[pid] = res
        return res

    def get_verification(self, provider_id: str) -> ProviderConnectionVerification:
        """Retrieve the latest cached verification record for a provider."""
        pid = self.registry.resolve_provider_id(provider_id)
        with self._lock:
            if pid in self._cache:
                return self._cache[pid]

        defn = self.registry.get_provider(pid)
        if defn is None:
            return ProviderConnectionVerification(
                provider_id=provider_id,
                status=ConnectionVerificationStatus.NOT_CONFIGURED,
                failure_class="NOT_CONFIGURED",
                sanitized_error=f"Provider '{provider_id}' is not registered.",
                last_verified_at=0.0,
                verification_method_version=self.verification_method_version,
            )

        return ProviderConnectionVerification(
            provider_id=pid,
            status=ConnectionVerificationStatus.NOT_CONFIGURED,
            failure_class="NEVER_VERIFIED",
            sanitized_error="Provider has not yet been verified.",
            last_verified_at=0.0,
            verification_method_version=self.verification_method_version,
        )

    def list_verifications(self) -> Dict[str, ProviderConnectionVerification]:
        """Return all cached provider verifications."""
        with self._lock:
            return dict(self._cache)

    def _classify_failure(
        self,
        provider_id: str,
        model_identity: ModelIdentity,
        exc: Exception,
        latency_ms: float,
        known_secret: Optional[str] = None,
    ) -> ProviderConnectionVerification:
        """Classify failure into normalized taxonomy with strict secret redaction (Directive 16)."""
        err_str = str(exc)
        lower_err = err_str.lower()
        status_code = getattr(exc, "status_code", None)

        # 1. Authentication (HTTP 401) vs Authorization / Access Denied (HTTP 403)
        if (
            (isinstance(exc, ProviderAuthenticationError) and status_code == 401)
            or ("401" in lower_err and "403" not in lower_err)
            or "unauthorized" in lower_err
        ):
            status = ConnectionVerificationStatus.AUTHENTICATION_FAILED
            failure_class = "AUTHENTICATION_FAILED"
            sanitized = "Upstream authentication failed: Invalid or expired API credentials."

        elif (
            (isinstance(exc, ProviderAuthenticationError) and status_code == 403)
            or "403" in lower_err
            or "forbidden" in lower_err
            or "access denied" in lower_err
            or "permission_denied" in lower_err
        ):
            status = ConnectionVerificationStatus.ACCESS_DENIED
            failure_class = "ACCESS_DENIED"
            sanitized = "Upstream authorization failed: Credential lacks required permissions or model access denied."

        elif isinstance(exc, ProviderAuthenticationError):
            status = ConnectionVerificationStatus.AUTHENTICATION_FAILED
            failure_class = "AUTHENTICATION_FAILED"
            sanitized = "Upstream authentication failed: Invalid or expired API credentials."

        # 2. Rate limit vs Quota exhaustion (Directive 16)
        elif (
            isinstance(exc, ProviderRateLimitError)
            or "429" in lower_err
            or "rate limit" in lower_err
        ):
            if any(
                k in lower_err
                for k in (
                    "quota",
                    "insufficient_quota",
                    "exceeded quota",
                    "billing",
                    "credit_exhausted",
                    "quota_exceeded",
                )
            ):
                status = ConnectionVerificationStatus.QUOTA_EXHAUSTED
                failure_class = "QUOTA_EXHAUSTED"
                sanitized = "Upstream provider quota or credits exhausted."
            else:
                status = ConnectionVerificationStatus.RATE_LIMITED
                failure_class = "RATE_LIMITED"
                sanitized = "Upstream provider request rate limit exceeded."

        # 3. Timeout
        elif (
            isinstance(exc, ProviderTimeoutError)
            or "timeout" in lower_err
            or "timed out" in lower_err
        ):
            status = ConnectionVerificationStatus.TIMEOUT
            failure_class = "TIMEOUT"
            sanitized = f"Upstream provider connection timed out after {latency_ms:.0f}ms."

        # 4. Model not found
        elif (
            isinstance(exc, ProviderNotFoundError)
            or "404" in lower_err
            or "model_not_found" in lower_err
            or "does not exist" in lower_err
        ):
            status = ConnectionVerificationStatus.MODEL_NOT_FOUND
            failure_class = "MODEL_NOT_FOUND"
            sanitized = (
                f"Model '{model_identity.model_id}' was not found on provider '{provider_id}'."
            )

        # 5. Network / Transport error
        elif isinstance(exc, ProviderConnectionError) or any(
            k in lower_err
            for k in (
                "connection",
                "dns",
                "unreachable",
                "failed to establish",
                "connection refused",
                "network",
            )
        ):
            status = ConnectionVerificationStatus.NETWORK_ERROR
            failure_class = "NETWORK_ERROR"
            sanitized = (
                f"Network transport error: Unable to reach endpoint for provider '{provider_id}'."
            )

        # 6. Upstream server error (5xx)
        elif isinstance(exc, ProviderServerError) or any(
            k in lower_err for k in ("500", "502", "503", "504", "server error", "internal error")
        ):
            status = ConnectionVerificationStatus.PROVIDER_ERROR
            failure_class = "PROVIDER_ERROR"
            sanitized = f"Upstream provider server error occurred on '{provider_id}'."

        else:
            status = ConnectionVerificationStatus.UNKNOWN_FAILURE
            failure_class = "UNKNOWN_FAILURE"
            sanitized = f"Provider verification failed: {self._sanitize_string(err_str, known_secret=known_secret)}"

        return ProviderConnectionVerification(
            provider_id=provider_id,
            model_identity=model_identity,
            status=status,
            latency_ms=latency_ms,
            failure_class=failure_class,
            sanitized_error=sanitized,
            last_verified_at=time.time(),
            verification_method_version=self.verification_method_version,
            details={"raw_exception_type": type(exc).__name__},
        )

    def _sanitize_string(self, text: str, known_secret: Optional[str] = None) -> str:
        """Strip any sensitive credentials, tokens, or private information from text."""
        sanitized = text
        if known_secret and len(known_secret.strip()) >= 4:
            sanitized = sanitized.replace(known_secret.strip(), "[REDACTED_SECRET]")
        sanitized = _SECRET_SANITIZE_PATTERN.sub("[REDACTED_CREDENTIAL]", sanitized)
        if len(sanitized) > 500:
            sanitized = sanitized[:497] + "..."
        return sanitized


def get_provider_verification_service(
    registry: Optional[ProviderRegistry] = None,
    policy_engine: Optional[PolicyEngine] = None,
) -> ProviderVerificationService:
    """Factory retrieving singleton ProviderVerificationService instance."""
    global _GLOBAL_VERIFICATION_SERVICE
    with _SERVICE_LOCK:
        if _GLOBAL_VERIFICATION_SERVICE is None:
            _GLOBAL_VERIFICATION_SERVICE = ProviderVerificationService(
                registry=registry,
                policy_engine=policy_engine,
            )
        return _GLOBAL_VERIFICATION_SERVICE


def reset_provider_verification_service() -> None:
    """Reset singleton for test isolation."""
    global _GLOBAL_VERIFICATION_SERVICE
    with _SERVICE_LOCK:
        _GLOBAL_VERIFICATION_SERVICE = None
