# core/router/model_router.py
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

import dspy
from dotenv import load_dotenv

from core.execution.models import RoutingTier
from core.privacy.engine import PrivacyPolicyEngine
from core.privacy.models import (
    DataRoutingClass,
    EffectiveRoutingPolicy,
    NoEligibleModelUnderPrivacyPolicyError,
)

from core.router.circuit_breaker import CircuitBreaker
from core.router.config import RouterConfigFile, load_router_config
from core.router.health import HealthProber, ProbeResult

# Ensure core.models and repo root are importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()

# Configure logging
logger = logging.getLogger("agent_engine.router")


@dataclass
class ResolvedModel:
    """Canonical model resolution outcome produced by the ModelRouter (Task R1.5)."""

    provider_id: str
    model_id: str
    routing_tier: RoutingTier
    reason: str = "default_routing"
    capabilities: List[str] = field(default_factory=list)
    estimated_cost_per_1k_tokens: float = 0.0
    fallback_chain: List[str] = field(default_factory=list)
    is_fallback: bool = False
    effective_privacy_class: Optional[str] = None
    policy_source: Optional[str] = None
    privacy_rejections: List[Dict[str, Any]] = field(default_factory=list)
    routing_decision: Optional[Any] = None


class ModelRouter:
    """
    Hardened smart router with circuit breaker, active latency probing,
    per-task preference chains, and resilient fallback execution.
    """

    def __init__(
        self,
        config: RouterConfigFile | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        health_prober: HealthProber | None = None,
    ) -> None:
        self.config = config or load_router_config()
        self.provider_priority = list(self.config.default_priority)
        self.circuit_breaker = circuit_breaker or CircuitBreaker(self.config.circuit_breaker)
        self.health_prober = health_prober or HealthProber(
            default_timeout=self.config.health_check.timeout_seconds,
            cache_ttl_seconds=self.config.health_check.cache_ttl_seconds,
        )
        self._configured_lm: dspy.LM | None = None
        self._configured_label: str | None = None
        self._active_provider: str | None = None

    def _check_api_key(self, provider: str) -> bool:
        """Return True if the provider requires an API key and it is present."""
        return self.health_prober._check_api_key(provider)

    def check_local_ollama_health(self) -> bool:
        """Check if Ollama is reachable."""
        res = self.health_prober.probe_ollama()
        return res.online

    def check_local_llamacpp_health(self) -> bool:
        """Check if llama.cpp server is reachable."""
        res = self.health_prober.probe_llamacpp()
        return res.online

    def get_status(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return comprehensive health, latency, circuit state, and key status for all providers."""
        try:
            from core.providers import get_provider_registry

            providers = [p.provider_id for p in get_provider_registry().list_providers()]
        except Exception:
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
        providers_to_probe = [p for p in providers if self.circuit_breaker.can_attempt(p)]
        probe_results = self.health_prober.probe_all(
            providers=providers_to_probe, force_refresh=force_refresh
        )
        for p in providers:
            if not self.circuit_breaker.can_attempt(p):
                probe_results[p] = ProbeResult(
                    provider=p,
                    online=False,
                    latency_ms=0.0,
                    error=f"Circuit OPEN: {self.circuit_breaker._last_error.get(p, 'Tripped')}",
                    checked_at=time.time(),
                )
        status: dict[str, Any] = {}

        for p in providers:
            probe = probe_results.get(p)
            online = probe.online if probe else False
            latency = probe.latency_ms if probe else 0.0
            circuit_state = self.circuit_breaker.get_state(p)

            status[f"{p}_live"] = online
            status[f"{p}_latency_ms"] = latency
            status[f"{p}_circuit_state"] = circuit_state.value
            status[f"{p}_key_present"] = self._check_api_key(p)

        # Primary and fallback providers respecting circuit breaker and priority
        available = [
            p
            for p in self.provider_priority
            if (status.get(f"{p}_live") or status.get(f"{p}_key_present"))
            and self.circuit_breaker.can_attempt(p)
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
        status["active_provider"] = self._active_provider or status["primary_provider"]
        status["circuit_breakers"] = self.circuit_breaker.get_status()
        return status

    def get_available_providers(
        self,
        task_type: str | None = None,
        effective_policy: Optional[EffectiveRoutingPolicy] = None,
        rejection_collector: Optional[List[Dict[str, Any]]] = None,
    ) -> list[str]:
        """
        Return an ordered list of providers available for invocation,
        filtering out providers whose circuit breaker is OPEN and those
        disallowed by the effective data routing privacy policy (Task R3.8).
        """
        status = self.get_status()
        candidates: list[str]
        if task_type and task_type in self.config.task_preferences:
            candidates = self.config.task_preferences[task_type]
        else:
            candidates = self.provider_priority

        available: list[str] = []
        for p in candidates:
            # 1. Privacy filtering (Task R3.8) before circuit or availability check
            if effective_policy is not None:
                elig = PrivacyPolicyEngine.evaluate_provider_privacy(p, effective_policy)
                if not elig.eligible:
                    if rejection_collector is not None:
                        rejection_collector.append(
                            {
                                "provider": p,
                                "reasons": [r.value for r in elig.rejection_reasons],
                            }
                        )
                    logger.debug(
                        "Skipping provider '%s': prohibited by privacy policy '%s' (%s)",
                        p,
                        effective_policy.effective_class.value,
                        elig.rejection_reasons,
                    )
                    continue

            # 2. Fast fail: skip providers with OPEN circuit breaker immediately
            if not self.circuit_breaker.can_attempt(p):
                logger.debug("Skipping provider '%s': circuit breaker is OPEN", p)
                continue

            if status.get(f"{p}_live", False) or status.get(f"{p}_key_present", False):
                available.append(p)

        # If task preferences yielded no available providers, fall back to general priority
        if not available and task_type:
            for p in self.provider_priority:
                if effective_policy is not None:
                    elig = PrivacyPolicyEngine.evaluate_provider_privacy(p, effective_policy)
                    if not elig.eligible:
                        continue
                if self.circuit_breaker.can_attempt(p) and (
                    status.get(f"{p}_live", False) or status.get(f"{p}_key_present", False)
                ):
                    available.append(p)

        return available

    def _get_default_model_for_provider(self, provider: str) -> str:
        defaults = {
            "ollama": "qwen2.5-coder:3b",
            "llamacpp": "qwen2.5-coder-3b-instruct-q4_k_m",
            "gemini": "gemini-2.0-flash",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-5-haiku",
            "deepseek": "deepseek-chat",
            "kimi": "moonshot-v1-8k",
            "groq": "llama-3.3-70b-specdec",
            "local": "deterministic_code",
        }
        return defaults.get(provider, "qwen2.5-coder:3b")

    def _get_default_tier_for_provider(self, provider: str) -> RoutingTier:
        if provider in ("ollama", "llamacpp"):
            return RoutingTier.LOCAL
        elif provider == "local":
            return RoutingTier.CODE
        return RoutingTier.MID

    def _estimate_cost_per_1k(self, provider: str, model: str) -> float:
        pref = model.lower()
        if "gpt-4o" in pref and "mini" not in pref:
            return 0.005
        if "sonnet" in pref or "opus" in pref or "pro" in pref:
            return 0.003
        if provider in ("ollama", "llamacpp", "local"):
            return 0.0
        return 0.00015

    def resolve_model(
        self,
        requested_model: Optional[str] = None,
        requested_tier: Optional[Union[RoutingTier, str]] = None,
        task_type: Optional[str] = None,
        effective_policy: Optional[EffectiveRoutingPolicy] = None,
        objective: Optional[Union[Any, str]] = None,
        requirements: Optional[Any] = None,
        storage: Optional[Any] = None,
        estimated_input_tokens: int = 1000,
        estimated_output_tokens: int = 500,
    ) -> ResolvedModel:
        """
        Resolve provider, model, and routing tier (Task R1.5, Task R3.8, Task R3.9).
        Respects circuit breaker status, enforces effective privacy policy constraints before scoring,
        and guarantees multi-objective optimization with zero cloud fallback under LOCAL_ONLY.
        """
        if isinstance(requested_tier, str):
            try:
                requested_tier = RoutingTier(requested_tier.lower())
            except Exception:
                pass

        effective_privacy_class = (
            effective_policy.effective_class.value if effective_policy else None
        )
        policy_source = effective_policy.source.value if effective_policy else None
        privacy_rejections: List[Dict[str, Any]] = []

        # 1. Explicit model request
        if requested_model:
            pref = requested_model.lower().strip()
            # Determine provider from model name
            provider = "ollama"
            if pref.startswith("openai/") or "gpt" in pref:
                provider = "openai"
            elif pref.startswith("gemini/") or "gemini" in pref:
                provider = "gemini"
            elif pref.startswith("anthropic/") or "claude" in pref:
                provider = "anthropic"
            elif pref.startswith("deepseek/") or "deepseek" in pref:
                provider = "deepseek"
            elif pref.startswith("groq/") or "groq" in pref:
                provider = "groq"
            elif pref.startswith("kimi/") or "kimi" in pref or "moonshot" in pref:
                provider = "kimi"
            elif pref.startswith("llamacpp/"):
                provider = "llamacpp"
            elif pref.startswith("ollama/") or "qwen" in pref or "llama" in pref:
                provider = "ollama"
            elif pref in ("deterministic_code", "code"):
                provider = "local"
            elif pref in ("semantic_cache", "cache"):
                provider = "local"
            elif "/" in pref:
                provider = pref.split("/")[0]

            # Inferred tier if not specified
            tier = requested_tier
            if not tier:
                if provider == "local":
                    tier = RoutingTier.CACHE if "cache" in pref else RoutingTier.CODE
                elif "mini" in pref or "flash" in pref or "haiku" in pref:
                    tier = RoutingTier.MID
                elif "gpt-4o" in pref or "sonnet" in pref or "opus" in pref or "pro" in pref:
                    tier = RoutingTier.FRONTIER
                elif provider in ("ollama", "llamacpp") or "qwen" in pref or "llama" in pref:
                    tier = RoutingTier.LOCAL
                else:
                    tier = RoutingTier.MID

            # Pre-scoring privacy check on requested provider (Task R3.8)
            if effective_policy is not None and provider != "local":
                elig = PrivacyPolicyEngine.evaluate_provider_privacy(provider, effective_policy)
                if not elig.eligible:
                    reasons_list = [r.value for r in elig.rejection_reasons]
                    privacy_rejections.append({"provider": provider, "reasons": reasons_list})
                    raise NoEligibleModelUnderPrivacyPolicyError(
                        f"NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: Requested model/provider '{provider}' "
                        f"is prohibited under privacy policy '{effective_policy.effective_class.value}' ({', '.join(reasons_list)})",
                        rejection_details=privacy_rejections,
                    )

            # Circuit breaker check on requested provider
            if not self.circuit_breaker.can_attempt(provider):
                logger.warning(
                    "Circuit OPEN for requested provider '%s'; resolving fallback", provider
                )
                available = self.get_available_providers(
                    task_type=task_type,
                    effective_policy=effective_policy,
                    rejection_collector=privacy_rejections,
                )
                fallbacks = [p for p in available if p != provider]
                if fallbacks:
                    fb_provider = fallbacks[0]
                    fb_model = self._get_default_model_for_provider(fb_provider)
                    fb_tier = self._get_default_tier_for_provider(fb_provider)
                    return ResolvedModel(
                        provider_id=fb_provider,
                        model_id=fb_model,
                        routing_tier=fb_tier,
                        reason=f"Circuit OPEN for '{provider}'; failed over to '{fb_provider}'",
                        capabilities=["general_chat", "completion"],
                        estimated_cost_per_1k_tokens=self._estimate_cost_per_1k(
                            fb_provider, fb_model
                        ),
                        fallback_chain=[provider, fb_provider],
                        is_fallback=True,
                        effective_privacy_class=effective_privacy_class,
                        policy_source=policy_source,
                        privacy_rejections=privacy_rejections,
                    )
                if (
                    effective_policy
                    and effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY
                ):
                    raise NoEligibleModelUnderPrivacyPolicyError(
                        f"NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: Circuit OPEN for local provider '{provider}' "
                        "and cloud fallback forbidden under LOCAL_ONLY",
                        rejection_details=privacy_rejections,
                    )
                return ResolvedModel(
                    provider_id=provider,
                    model_id=requested_model,
                    routing_tier=tier,
                    reason=f"Circuit OPEN for '{provider}' and no fallbacks available",
                    capabilities=[],
                    fallback_chain=[provider],
                    is_fallback=False,
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=privacy_rejections,
                )

            return ResolvedModel(
                provider_id=provider,
                model_id=requested_model,
                routing_tier=tier,
                reason="explicit_model_preference",
                capabilities=["general_chat", "completion"],
                estimated_cost_per_1k_tokens=self._estimate_cost_per_1k(provider, requested_model),
                fallback_chain=[provider],
                is_fallback=False,
                effective_privacy_class=effective_privacy_class,
                policy_source=policy_source,
                privacy_rejections=privacy_rejections,
            )

        # 2. Explicit tier request without explicit model
        if requested_tier:
            if requested_tier == RoutingTier.CODE:
                return ResolvedModel(
                    provider_id="local",
                    model_id="deterministic_code",
                    routing_tier=RoutingTier.CODE,
                    reason="tier_code",
                    capabilities=["deterministic"],
                    fallback_chain=["local"],
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=privacy_rejections,
                )
            elif requested_tier == RoutingTier.CACHE:
                return ResolvedModel(
                    provider_id="local",
                    model_id="semantic_cache",
                    routing_tier=RoutingTier.CACHE,
                    reason="tier_cache",
                    capabilities=["caching"],
                    fallback_chain=["local"],
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=privacy_rejections,
                )
            elif requested_tier == RoutingTier.LOCAL:
                status = self.get_status()
                candidates_local = ["llamacpp"]
                if (
                    effective_policy
                    and effective_policy.effective_class != DataRoutingClass.LOCAL_ONLY
                ):
                    candidates_local.append("ollama")
                elif not effective_policy:
                    candidates_local.append("ollama")

                available_local = [
                    p
                    for p in candidates_local
                    if self.circuit_breaker.can_attempt(p)
                    and (status.get(f"{p}_live", False) or status.get(f"{p}_key_present", False))
                ]
                if not available_local:
                    if (
                        effective_policy
                        and effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY
                    ):
                        raise NoEligibleModelUnderPrivacyPolicyError(
                            "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: Local runtime unavailable and cloud fallback forbidden under LOCAL_ONLY",
                            rejection_details=[{"provider": "llamacpp", "status": "unavailable"}],
                        )
                    prov = "llamacpp"
                    model = "qwen2.5-coder-3b-instruct-q4_k_m"
                else:
                    prov = available_local[0]
                    model = (
                        "qwen2.5-coder:3b"
                        if prov == "ollama"
                        else "qwen2.5-coder-3b-instruct-q4_k_m"
                    )

                return ResolvedModel(
                    provider_id=prov,
                    model_id=model,
                    routing_tier=RoutingTier.LOCAL,
                    reason="tier_local",
                    capabilities=["local_inference"],
                    fallback_chain=available_local or [prov],
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=privacy_rejections,
                )
            elif requested_tier == RoutingTier.FRONTIER:
                if (
                    effective_policy
                    and effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY
                ):
                    raise NoEligibleModelUnderPrivacyPolicyError(
                        "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: Frontier tier requires cloud models which are forbidden under LOCAL_ONLY",
                        rejection_details=[
                            {"tier": "frontier", "reason": "remote_tier_forbidden_under_local_only"}
                        ],
                    )
                prov = "openai" if self.circuit_breaker.can_attempt("openai") else "anthropic"
                if (
                    effective_policy
                    and effective_policy.effective_class == DataRoutingClass.APPROVED_CLOUD
                ):
                    if not effective_policy.is_target_approved(prov):
                        prov = (
                            "anthropic"
                            if effective_policy.is_target_approved("anthropic")
                            else "openai"
                        )
                        if not effective_policy.is_target_approved(prov):
                            raise NoEligibleModelUnderPrivacyPolicyError(
                                f"NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: Frontier provider '{prov}' not approved under APPROVED_CLOUD",
                                rejection_details=[{"provider": prov, "reason": "not_approved"}],
                            )
                model = "gpt-4o" if prov == "openai" else "claude-3-5-sonnet"
                return ResolvedModel(
                    provider_id=prov,
                    model_id=model,
                    routing_tier=RoutingTier.FRONTIER,
                    reason="tier_frontier",
                    capabilities=["high_reasoning", "complex_context"],
                    estimated_cost_per_1k_tokens=0.005,
                    fallback_chain=[prov],
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=privacy_rejections,
                )
            else:
                if (
                    effective_policy
                    and effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY
                ):
                    raise NoEligibleModelUnderPrivacyPolicyError(
                        "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: Mid tier requires cloud models which are forbidden under LOCAL_ONLY",
                        rejection_details=[
                            {"tier": "mid", "reason": "remote_tier_forbidden_under_local_only"}
                        ],
                    )
                prov = "gemini" if self.circuit_breaker.can_attempt("gemini") else "openai"
                if (
                    effective_policy
                    and effective_policy.effective_class == DataRoutingClass.APPROVED_CLOUD
                ):
                    if not effective_policy.is_target_approved(prov):
                        prov = (
                            "openai" if effective_policy.is_target_approved("openai") else "gemini"
                        )
                        if not effective_policy.is_target_approved(prov):
                            raise NoEligibleModelUnderPrivacyPolicyError(
                                f"NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: Mid provider '{prov}' not approved under APPROVED_CLOUD",
                                rejection_details=[{"provider": prov, "reason": "not_approved"}],
                            )
                model = "gemini-2.0-flash" if prov == "gemini" else "gpt-4o-mini"
                return ResolvedModel(
                    provider_id=prov,
                    model_id=model,
                    routing_tier=RoutingTier.MID,
                    reason="tier_mid",
                    capabilities=["general_chat", "completion"],
                    estimated_cost_per_1k_tokens=0.00015,
                    fallback_chain=[prov],
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=privacy_rejections,
                )

        # 3. Multi-objective or Default resolution (Task R3.9)
        try:
            from core.model_registry import get_model_registry
            from core.router.models import RoutingObjectiveProfile
            from core.router.objective import RoutingOptimizer

            optimizer = RoutingOptimizer(
                circuit_breaker=self.circuit_breaker,
                health_prober=self.health_prober,
            )
            catalog_candidates = get_model_registry().list_models()
            eff_objective = (
                objective
                or getattr(self.config, "default_objective", None)
                or RoutingObjectiveProfile.BALANCED
            )

            decision = optimizer.optimize(
                candidates=catalog_candidates,
                requirements=requirements,
                effective_policy=effective_policy,
                objective=eff_objective,
                task_type=task_type,
                storage=storage,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
            )

            if decision.winner is not None:
                winner_cand = decision.winner
                w_provider = winner_cand.provider_id
                w_model = winner_cand.model_id
                w_tier = winner_cand.routing_tier
                w_cost = (
                    winner_cand.metrics.cost.expected_cost_usd
                    if winner_cand.metrics.cost.expected_cost_usd is not None
                    else self._estimate_cost_per_1k(w_provider, w_model)
                )
                w_fallback_chain = list(decision.fallback_chain)
                privacy_rejs = [
                    {"provider": r.provider_id, "reasons": [r.reason]}
                    for r in decision.privacy_rejections
                ]
                return ResolvedModel(
                    provider_id=w_provider,
                    model_id=w_model,
                    routing_tier=w_tier,
                    reason=decision.selection_reason,
                    capabilities=["general_chat", "completion"],
                    estimated_cost_per_1k_tokens=w_cost,
                    fallback_chain=w_fallback_chain,
                    is_fallback=False,
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=privacy_rejs or privacy_rejections,
                    routing_decision=decision,
                )
            else:
                # No candidates survived hard constraints
                if (
                    effective_policy
                    and effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY
                ):
                    raise NoEligibleModelUnderPrivacyPolicyError(
                        "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: No local model available and cloud fallback forbidden under LOCAL_ONLY",
                        rejection_details=[
                            {"candidate": r.candidate_id, "reason": r.reason}
                            for r in decision.rejections
                        ],
                    )
                if (
                    effective_policy
                    and effective_policy.effective_class == DataRoutingClass.APPROVED_CLOUD
                ):
                    raise NoEligibleModelUnderPrivacyPolicyError(
                        "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: No approved cloud or local provider available under APPROVED_CLOUD",
                        rejection_details=[
                            {"candidate": r.candidate_id, "reason": r.reason}
                            for r in decision.rejections
                        ],
                    )
                return ResolvedModel(
                    provider_id="none",
                    model_id="none",
                    routing_tier=RoutingTier.LOCAL,
                    reason=decision.selection_reason or "no_eligible_candidates",
                    capabilities=[],
                    fallback_chain=[],
                    is_fallback=False,
                    effective_privacy_class=effective_privacy_class,
                    policy_source=policy_source,
                    privacy_rejections=[
                        {"candidate": r.candidate_id, "reason": r.reason}
                        for r in decision.privacy_rejections
                    ],
                    routing_decision=decision,
                )
        except NoEligibleModelUnderPrivacyPolicyError:
            raise
        except Exception as opt_err:
            logger.warning("RoutingOptimizer fallback to provider priority: %s", opt_err)

        # Fallback to provider priority if optimizer could not run
        available = self.get_available_providers(
            task_type=task_type,
            effective_policy=effective_policy,
            rejection_collector=privacy_rejections,
        )
        if not available:
            if effective_policy and effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY:
                raise NoEligibleModelUnderPrivacyPolicyError(
                    "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: No local model available and cloud fallback forbidden under LOCAL_ONLY",
                    rejection_details=privacy_rejections,
                )
            if (
                effective_policy
                and effective_policy.effective_class == DataRoutingClass.APPROVED_CLOUD
            ):
                raise NoEligibleModelUnderPrivacyPolicyError(
                    "NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY: No approved cloud or local provider available under APPROVED_CLOUD",
                    rejection_details=privacy_rejections,
                )
            return ResolvedModel(
                provider_id="none",
                model_id="none",
                routing_tier=RoutingTier.LOCAL,
                reason="no_available_providers",
                capabilities=[],
                fallback_chain=[],
                is_fallback=False,
                effective_privacy_class=effective_privacy_class,
                policy_source=policy_source,
                privacy_rejections=privacy_rejections,
            )

        primary = available[0]
        model = self._get_default_model_for_provider(primary)
        tier = self._get_default_tier_for_provider(primary)
        return ResolvedModel(
            provider_id=primary,
            model_id=model,
            routing_tier=tier,
            reason="router_priority",
            capabilities=["general_chat", "completion"],
            estimated_cost_per_1k_tokens=self._estimate_cost_per_1k(primary, model),
            fallback_chain=available,
            is_fallback=False,
            effective_privacy_class=effective_privacy_class,
            policy_source=policy_source,
            privacy_rejections=privacy_rejections,
        )

    def create_lm(
        self, provider: str, cache: bool = True, num_ctx: int = 4096, **kwargs: Any
    ) -> tuple[dspy.LM, str]:
        """Instantiate a dspy.LM for the given provider using core.models.get_model_provider."""
        from core.models import get_model_provider

        model_name = kwargs.get("model") or kwargs.get("model_name")
        api_key = kwargs.get("api_key")

        lm = get_model_provider(
            provider_name=provider,
            model_name=model_name,
            cache=cache,
            max_tokens=num_ctx,
            api_key=api_key,
        )
        if provider == "openai":
            label = f"OpenAI ({model_name or 'gpt-4o-mini'})"
        else:
            label = f"{provider.capitalize()} (ctx={num_ctx})"
        return lm, label

    def initialize_and_configure(
        self,
        force_provider: str | None = None,
        task_type: str | None = None,
        cache: bool = True,
        num_ctx: int = 4096,
    ) -> tuple[dspy.LM, str]:
        """
        Configure dspy.settings with the best provider according to priority/task chains
        and circuit breaker status. Traverses fallback chain automatically if a candidate fails.
        """
        if force_provider:
            # If forced provider's circuit is OPEN, warn and fall through to chain
            if not self.circuit_breaker.can_attempt(force_provider):
                logger.warning(
                    "Forced provider '%s' circuit is OPEN. Initiating fallback chain traversal.",
                    force_provider,
                )
            else:
                try:
                    logger.info("Attempting forced provider '%s'...", force_provider)
                    lm, label = self.create_lm(force_provider, cache=cache, num_ctx=num_ctx)
                    dspy.settings.configure(lm=lm, cache=cache)
                    self._configured_lm = lm
                    self._configured_label = label
                    self._active_provider = force_provider
                    self.circuit_breaker.record_success(force_provider)
                    logger.info("Configured forced LM: %s", label)
                    return lm, label
                except Exception as e:
                    logger.error(
                        "Failed to initialize forced provider '%s': %s",
                        force_provider,
                        e,
                    )
                    self.circuit_breaker.record_failure(force_provider, e)
                    # Fall through to fallback chain

        # Fallback chain selection
        available = self.get_available_providers(task_type=task_type)
        logger.info(
            "Evaluating fallback chain for task '%s': %s",
            task_type or "default",
            available,
        )

        for p in available:
            logger.info("Evaluating provider in fallback chain: '%s'...", p)
            try:
                lm, label = self.create_lm(p, cache=cache, num_ctx=num_ctx)
                dspy.settings.configure(lm=lm, cache=cache)
                self._configured_lm = lm
                self._configured_label = label
                self._active_provider = p
                self.circuit_breaker.record_success(p)
                logger.info("Configured LM: %s (selected from fallback chain)", label)
                return lm, label
            except Exception as e:
                logger.warning(
                    "Provider '%s' initialization failed: %s. Tripping breaker and advancing fallback chain...",
                    p,
                    e,
                )
                self.circuit_breaker.record_failure(p, e)
                continue

        # Ultimate fallback: try local llama.cpp directly if not already tried
        if self.circuit_breaker.can_attempt("llamacpp"):
            logger.warning(
                "No provider from fallback chain succeeded. Trying local llama.cpp safe fallback..."
            )
            try:
                lm, label = self.create_lm("llamacpp", cache=cache, num_ctx=num_ctx)
                dspy.settings.configure(lm=lm, cache=cache)
                self._configured_lm = lm
                self._configured_label = label
                self._active_provider = "llamacpp"
                self.circuit_breaker.record_success("llamacpp")
                return lm, label
            except Exception as e:
                self.circuit_breaker.record_failure("llamacpp", e)
                logger.critical("Local fallback llama.cpp failed: %s", e)

        raise RuntimeError(
            "No LLM provider available in fallback chain. All circuits OPEN or offline."
        )

    def execute_with_fallback(
        self,
        call_fn: Callable[[dspy.LM], Any],
        task_type: str | None = None,
        max_retries: int = 3,
    ) -> Any:
        """
        Execute an LM invocation with automated fallback failover across the chain.
        If the active provider throws at runtime, its circuit breaker records the failure,
        the next available provider is engaged, and the call is retried.
        """
        attempt = 0
        last_exception: Exception | None = None

        while attempt < max_retries:
            attempt += 1
            if not self._configured_lm or (
                self._active_provider
                and not self.circuit_breaker.can_attempt(self._active_provider)
            ):
                self.initialize_and_configure(task_type=task_type)

            active_p = self._active_provider or "unknown"
            try:
                result = call_fn(self._configured_lm)
                self.circuit_breaker.record_success(active_p)
                return result
            except Exception as e:
                last_exception = e
                logger.warning(
                    "Execution error on provider '%s' (attempt %d/%d): %s. Recording failure & falling back...",
                    active_p,
                    attempt,
                    max_retries,
                    e,
                )
                self.circuit_breaker.record_failure(active_p, e)
                # Invalidate configured LM to force failover to next provider
                self._configured_lm = None
                self._active_provider = None

        raise RuntimeError(
            f"Execution failed after {max_retries} fallback attempts: {last_exception}"
        ) from last_exception

    def get_current_lm(self) -> dspy.LM | None:
        return self._configured_lm

    def get_current_label(self) -> str | None:
        return self._configured_label

    def get_active_provider(self) -> str | None:
        return self._active_provider

    def record_failure(self, provider: str, model: str = "", error: Any = None) -> None:
        """Record a failure for provider in circuit breaker."""
        self.circuit_breaker.record_failure(provider, error)
        # Invalidate cached LM if failing the active provider
        if provider == self._active_provider:
            self._configured_lm = None
            self._active_provider = None
