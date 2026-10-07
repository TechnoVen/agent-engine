"""core/model_registry/registry.py

Canonical Model Capability Registry Implementation for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).

Design Invariants:
1. Scoped Canonical Identity: Indexes models as 'provider_id:model_id'.
2. 3-Valued Logic: Capabilities evaluated via TriStateBool (TRUE, FALSE, UNKNOWN).
   UNKNOWN cannot satisfy hard requirements.
3. Provenance Precedence: USER_OVERRIDE > LOCAL_INSPECTED > REMOTE_DISCOVERY > BUILTIN.
4. Deterministic Querying: Evaluates ModelRequirements and outputs ModelCandidate
   instances with complete, explainable rejection reasons when disqualified.
5. Inviolable Provider Decoupling: Relies on ProviderRegistry for transport/auth
   without embedding network execution inside model metadata.
6. Thread-Safe: Operations guarded by RLock.
"""

from __future__ import annotations

import logging
from threading import RLock
import time
from typing import Any, Dict, List, Optional, Tuple

from core.model_registry.catalog import get_builtin_catalog
from core.model_registry.models import (
    LatencyClass,
    ModelCandidate,
    ModelDefinition,
    ModelRequirements,
    TriStateBool,
)

logger = logging.getLogger("agent_engine.model_registry")

_GLOBAL_MODEL_REGISTRY: Optional[ModelRegistry] = None
_MODEL_REGISTRY_LOCK = RLock()


class ModelRegistry:
    """Thread-safe authoritative registry managing model capabilities and constraints."""

    def __init__(self, provider_registry: Optional[Any] = None) -> None:
        self._lock = RLock()
        self._models: Dict[str, ModelDefinition] = {}
        self._provider_registry = provider_registry

        # Load standard reference catalog
        self._load_builtin_catalog()

    def _get_provider_registry(self) -> Optional[Any]:
        if self._provider_registry is not None:
            return self._provider_registry
        try:
            from core.providers import get_provider_registry

            self._provider_registry = get_provider_registry()
            return self._provider_registry
        except Exception:
            return None

    def _load_builtin_catalog(self) -> None:
        for model_def in get_builtin_catalog():
            self._models[model_def.canonical_id] = model_def

    @staticmethod
    def parse_canonical_id(scoped_id: str) -> Tuple[str, str]:
        """Split a scoped canonical ID into (provider_id, model_id)."""
        clean = scoped_id.strip()
        if ":" not in clean:
            raise ValueError(
                f"Invalid scoped model identifier '{scoped_id}': expected 'provider_id:model_id'"
            )
        parts = clean.split(":", 1)
        pid = parts[0].strip().lower()
        mid = parts[1].strip()
        if not pid or not mid:
            raise ValueError(
                f"Invalid scoped model identifier '{scoped_id}': neither provider_id nor model_id may be empty"
            )
        return pid, mid

    def resolve_canonical_id(self, scoped_id: str) -> str:
        """Resolve any provider alias in the scoped ID to its canonical form."""
        pid, mid = self.parse_canonical_id(scoped_id)
        prov_reg = self._get_provider_registry()
        if prov_reg:
            canon_pid = prov_reg.resolve_provider_id(pid)
        else:
            canon_pid = pid
        return f"{canon_pid}:{mid}"

    def register_model(
        self,
        definition: ModelDefinition,
        force: bool = False,
    ) -> bool:
        """Register or update a model definition obeying provenance precedence.

        Precedence: USER_OVERRIDE (4) > LOCAL_INSPECTED (3) > REMOTE_DISCOVERY (2) > BUILTIN (1).
        Returns True if registered, False if rejected due to lower precedence.
        """
        with self._lock:
            # Normalize provider_id using canonical provider registry if available
            prov_reg = self._get_provider_registry()
            if prov_reg:
                definition.provider_id = prov_reg.resolve_provider_id(definition.provider_id)

            cid = definition.canonical_id

            if cid in self._models and not force:
                existing = self._models[cid]
                if definition.provenance.precedence < existing.provenance.precedence:
                    logger.debug(
                        "Registration of '%s' rejected: provenance '%s' has lower precedence than existing '%s'",
                        cid,
                        definition.provenance.value,
                        existing.provenance.value,
                    )
                    return False

            definition.updated_at = time.time()
            self._models[cid] = definition
            return True

    def unregister_model(self, scoped_id: str) -> bool:
        """Remove a model from the registry by its scoped ID."""
        with self._lock:
            cid = self.resolve_canonical_id(scoped_id)
            if cid in self._models:
                del self._models[cid]
                return True
            return False

    def get_model(self, scoped_id: str) -> Optional[ModelDefinition]:
        """Look up a model definition by its scoped identifier (e.g. 'openai:gpt-4o')."""
        with self._lock:
            try:
                cid = self.resolve_canonical_id(scoped_id)
                return self._models.get(cid)
            except ValueError:
                return None

    def list_models(
        self,
        provider_id: Optional[str] = None,
        local_only: bool = False,
        tag: Optional[str] = None,
    ) -> List[ModelDefinition]:
        """List registered model definitions with optional filtering."""
        with self._lock:
            results = []
            target_pid = None
            if provider_id:
                prov_reg = self._get_provider_registry()
                target_pid = (
                    prov_reg.resolve_provider_id(provider_id)
                    if prov_reg
                    else provider_id.lower().strip()
                )

            for m in self._models.values():
                if target_pid and m.provider_id != target_pid:
                    continue
                if local_only and not m.privacy.is_local:
                    continue
                if tag and tag not in m.tags:
                    continue
                results.append(m)

            return sorted(results, key=lambda x: x.canonical_id)

    def update_telemetry(self, scoped_id: str, latency_ms: float) -> bool:
        """Update runtime observed latency telemetry for a model."""
        with self._lock:
            cid = self.resolve_canonical_id(scoped_id)
            model = self._models.get(cid)
            if not model:
                return False
            model.latency.telemetry_latency_ms = latency_ms
            model.latency.telemetry_updated_at = time.time()
            # Dynamically update latency class if observed latency differs significantly
            if latency_ms < 1000.0:
                model.latency.latency_class = LatencyClass.FAST
            elif latency_ms < 3000.0:
                model.latency.latency_class = LatencyClass.MEDIUM
            elif latency_ms < 8000.0:
                model.latency.latency_class = LatencyClass.SLOW
            else:
                model.latency.latency_class = LatencyClass.REASONING
            return True

    def query_eligible_models(
        self,
        requirements: ModelRequirements,
        eligible_only: bool = True,
    ) -> List[ModelCandidate]:
        """Evaluate registered models against ModelRequirements deterministically.

        Invariants:
        1. 3-Valued Logic: UNKNOWN capabilities CANNOT satisfy hard requirements.
        2. Comprehensive explanation: ModelCandidate records all rejection reasons.
        3. Deterministic scoring: Eligible candidates scored by capability, context, cost, and latency.
        """
        with self._lock:
            candidates: List[ModelCandidate] = []
            models_to_evaluate = list(self._models.values())

        for model in models_to_evaluate:
            reasons: List[str] = []

            # 1. Provider constraints
            if requirements.allowed_providers:
                allowed_pids = [p.lower().strip() for p in requirements.allowed_providers]
                if model.provider_id not in allowed_pids:
                    reasons.append(
                        f"Provider '{model.provider_id}' is not in allowed_providers list"
                    )

            if requirements.excluded_providers:
                excluded_pids = [p.lower().strip() for p in requirements.excluded_providers]
                if model.provider_id in excluded_pids:
                    reasons.append(f"Provider '{model.provider_id}' is explicitly excluded")

            # 2. Hard capability constraints (3-valued logic check)
            cap_checks = [
                ("reasoning", requirements.require_reasoning),
                ("coding", requirements.require_coding),
                ("vision", requirements.require_vision),
                ("tools", requirements.require_tools),
                ("structured_output", requirements.require_structured_output),
                ("embeddings", requirements.require_embeddings),
                ("streaming", requirements.require_streaming),
            ]
            for cap_name, req_val in cap_checks:
                if req_val is True:
                    sat, err = model.capabilities.satisfies_requirement(cap_name, True)
                    if not sat and err:
                        reasons.append(err)

            # 3. Context window constraints
            if requirements.min_input_tokens is not None:
                max_in = model.max_input_tokens or model.max_total_context_tokens
                if max_in < requirements.min_input_tokens:
                    reasons.append(
                        f"Input context {max_in} < required {requirements.min_input_tokens}"
                    )

            if requirements.min_output_tokens is not None:
                max_out = model.max_output_tokens or model.max_total_context_tokens
                if max_out < requirements.min_output_tokens:
                    reasons.append(
                        f"Output context {max_out} < required {requirements.min_output_tokens}"
                    )

            if requirements.min_total_tokens is not None:
                if model.max_total_context_tokens < requirements.min_total_tokens:
                    reasons.append(
                        f"Total context {model.max_total_context_tokens} < required {requirements.min_total_tokens}"
                    )

            # 4. Pricing constraints
            if requirements.max_input_cost_per_million is not None:
                cost_in = model.pricing.input_cost_per_million
                if cost_in is not None and cost_in > requirements.max_input_cost_per_million:
                    reasons.append(
                        f"Input cost ${cost_in:.3f}/M > allowed ${requirements.max_input_cost_per_million:.3f}/M"
                    )

            if requirements.max_output_cost_per_million is not None:
                cost_out = model.pricing.output_cost_per_million
                if cost_out is not None and cost_out > requirements.max_output_cost_per_million:
                    reasons.append(
                        f"Output cost ${cost_out:.3f}/M > allowed ${requirements.max_output_cost_per_million:.3f}/M"
                    )

            # 5. Latency constraints
            if requirements.max_latency_ms is not None:
                eff_lat = model.latency.effective_latency_ms
                if eff_lat is not None and eff_lat > requirements.max_latency_ms:
                    reasons.append(
                        f"Latency {eff_lat:.1f}ms > allowed {requirements.max_latency_ms:.1f}ms"
                    )

            if requirements.allowed_latency_classes:
                if model.latency.latency_class not in requirements.allowed_latency_classes:
                    reasons.append(
                        f"Latency class '{model.latency.latency_class.value}' not in allowed classes"
                    )

            # 6. Privacy constraints
            if requirements.require_local_only and not model.privacy.is_local:
                reasons.append("Model is not local (violates require_local_only)")

            if not requirements.allow_data_leaves_device and model.privacy.data_leaves_device:
                reasons.append("Data leaves device (violates allow_data_leaves_device=False)")

            if requirements.require_zero_retention and not model.privacy.zero_data_retention:
                reasons.append("Zero data retention is not guaranteed")

            # 7. Hardware constraints (for local models)
            if requirements.max_available_ram_bytes is not None and model.hardware:
                if (
                    model.hardware.min_ram_bytes
                    and model.hardware.min_ram_bytes > requirements.max_available_ram_bytes
                ):
                    reasons.append(
                        f"Requires {model.hardware.min_ram_bytes} RAM bytes > available {requirements.max_available_ram_bytes}"
                    )

            if requirements.max_available_vram_bytes is not None and model.hardware:
                if (
                    model.hardware.min_vram_bytes
                    and model.hardware.min_vram_bytes > requirements.max_available_vram_bytes
                ):
                    reasons.append(
                        f"Requires {model.hardware.min_vram_bytes} VRAM bytes > available {requirements.max_available_vram_bytes}"
                    )

            # 8. Tag filters
            for tag in requirements.required_tags:
                if tag not in model.tags:
                    reasons.append(f"Missing required tag '{tag}'")

            is_eligible = len(reasons) == 0

            # Deterministic candidate scoring heuristic
            score = 0.0
            if is_eligible:
                score = 100.0
                # Quality & capability bonus
                if model.capabilities.reasoning == TriStateBool.TRUE:
                    score += 20.0
                if model.capabilities.coding == TriStateBool.TRUE:
                    score += 15.0
                if model.capabilities.vision == TriStateBool.TRUE:
                    score += 10.0
                # Context headroom bonus (logarithmic scaling)
                score += min(model.max_total_context_tokens / 10000.0, 25.0)
                # Cost penalty
                if model.pricing.input_cost_per_million:
                    score -= min(model.pricing.input_cost_per_million * 2.0, 30.0)
                # Latency bonus/penalty
                if model.latency.latency_class == LatencyClass.FAST:
                    score += 15.0
                elif model.latency.latency_class == LatencyClass.REASONING:
                    score += 5.0

            candidate = ModelCandidate(
                canonical_id=model.canonical_id,
                provider_id=model.provider_id,
                model_id=model.model_id,
                model_definition=model,
                eligible=is_eligible,
                rejection_reasons=reasons,
                score=round(score, 2),
            )

            if not eligible_only or is_eligible:
                candidates.append(candidate)

        # Sort: eligible candidates first with highest score descending; ineligible sorted by canonical_id
        candidates.sort(key=lambda c: (-int(c.eligible), -c.score, c.canonical_id))
        return candidates


def get_model_registry() -> ModelRegistry:
    """Obtain the process-wide singleton ModelRegistry instance."""
    global _GLOBAL_MODEL_REGISTRY
    with _MODEL_REGISTRY_LOCK:
        if _GLOBAL_MODEL_REGISTRY is None:
            _GLOBAL_MODEL_REGISTRY = ModelRegistry()
        return _GLOBAL_MODEL_REGISTRY


def reset_model_registry() -> ModelRegistry:
    """Reset the singleton ModelRegistry (for test isolation)."""
    global _GLOBAL_MODEL_REGISTRY
    with _MODEL_REGISTRY_LOCK:
        _GLOBAL_MODEL_REGISTRY = ModelRegistry()
        return _GLOBAL_MODEL_REGISTRY
