"""core/model_registry/registry.py

Canonical Model Capability Registry Implementation for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).

Design Invariants:
1. Structured Model Identity: ModelIdentity(provider_id, model_id) avoids delimiter parsing ambiguities.
2. 3-Valued Logic: Capabilities and privacy evaluated via TriStateBool (TRUE, FALSE, UNKNOWN).
   UNKNOWN cannot satisfy hard requirements.
3. Provenance Precedence & Field-Level Merge:
   USER_OVERRIDE (4) > LOCAL_INSPECTED (3) > REMOTE_DISCOVERY (2) > BUILTIN (1).
   Sparse higher-precedence records do NOT erase known lower-precedence fields.
   User override cannot convert authoritative cloud data_leaves_device to FALSE.
4. Restricted Precedence Override: force=True is strictly restricted to trusted internal/admin callers.
5. Latency Separation: Catalog baseline classification preserved separately from observed telemetry.
6. Pricing Discipline: Missing price is UNKNOWN, never zero.
7. Non-Routing Candidate Evaluation: Eligibility + explainable rejection reasons without premature ranking.
8. Thread-Safe: Operations guarded by RLock; no I/O held across locks.
"""

from __future__ import annotations

import logging
from threading import RLock
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from core.model_registry.catalog import get_builtin_catalog
from core.model_registry.models import (
    ExecutionLocation,
    LatencyClass,
    ModelCandidate,
    ModelDefinition,
    ModelIdentity,
    ModelRequirements,
    ObservedLatencyMetrics,
    ProvenanceType,
    TriStateBool,
    parse_model_identifier,
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
    def parse_canonical_id(scoped_id: Union[str, ModelIdentity]) -> Tuple[str, str]:
        """Parse identifier into (provider_id, model_id) tuple via structured ModelIdentity."""
        ident = parse_model_identifier(scoped_id)
        return ident.provider_id, ident.model_id

    def resolve_canonical_id(self, scoped_id: Union[str, ModelIdentity]) -> str:
        """Resolve any provider alias in the scoped ID to its canonical display form."""
        ident = parse_model_identifier(scoped_id)
        prov_reg = self._get_provider_registry()
        if prov_reg:
            canon_pid = prov_reg.resolve_provider_id(ident.provider_id)
        else:
            canon_pid = ident.provider_id
        return f"{canon_pid}:{ident.model_id}"

    def register_model(
        self,
        definition: ModelDefinition,
        force: bool = False,
        caller_role: Optional[str] = None,
    ) -> bool:
        """Register or update a model definition obeying provenance precedence and field-level merging.

        Precedence: USER_OVERRIDE (4) > LOCAL_INSPECTED (3) > REMOTE_DISCOVERY (2) > BUILTIN (1).
        Invariants:
        1. force=True is strictly restricted to trusted internal/admin callers.
        2. Sparse higher-precedence records do NOT erase known lower-precedence fields.
        3. USER_OVERRIDE cannot downgrade authoritative cloud data_leaves_device=TRUE to FALSE.
        """
        with self._lock:
            # Audit force authorization
            if force and caller_role not in ("admin", "trusted_internal"):
                raise PermissionError(
                    f"Untrusted caller role '{caller_role}' cannot invoke precedence-force registration"
                )

            # Normalize provider_id using canonical provider registry if available
            prov_reg = self._get_provider_registry()
            if prov_reg:
                definition.provider_id = prov_reg.resolve_provider_id(definition.provider_id)

            cid = definition.canonical_id

            if cid in self._models:
                existing = self._models[cid]

                # If existing definition has strictly higher precedence and force is not set,
                # reject full replacement if incoming is lower.
                if definition.provenance.precedence < existing.provenance.precedence and not force:
                    logger.debug(
                        "Registration of '%s' rejected: provenance '%s' has lower precedence than existing '%s'",
                        cid,
                        definition.provenance.value,
                        existing.provenance.value,
                    )
                    return False

                # Security invariant: User override must not convert authoritative data_leaves_device=TRUE to FALSE
                if definition.provenance == ProvenanceType.USER_OVERRIDE:
                    if (
                        existing.privacy.data_leaves_device == TriStateBool.TRUE
                        and definition.privacy.data_leaves_device == TriStateBool.FALSE
                    ):
                        raise ValueError(
                            f"User override cannot convert authoritative data_leaves_device=TRUE to FALSE for {cid}"
                        )

                # Field-level merge: sparse metadata must not erase known facts!
                merged = existing.model_copy(deep=True)

                if definition.display_name:
                    merged.display_name = definition.display_name
                if definition.description:
                    merged.description = definition.description

                # Capabilities field-by-field merge
                for cap in [
                    "reasoning",
                    "coding",
                    "vision",
                    "tools",
                    "structured_output",
                    "embeddings",
                    "streaming",
                ]:
                    inc_val = getattr(definition.capabilities, cap)
                    if inc_val != TriStateBool.UNKNOWN:
                        existing_fact = existing.capabilities.get_fact(cap)
                        if (
                            definition.provenance.precedence >= existing_fact.source.precedence
                            or force
                        ):
                            merged.capabilities.set_fact(cap, inc_val, definition.provenance)
                    # If inc_val == UNKNOWN: preserve existing fact unchanged

                # Context limits merge
                if definition.max_input_tokens is not None:
                    merged.max_input_tokens = definition.max_input_tokens
                if definition.max_output_tokens is not None:
                    merged.max_output_tokens = definition.max_output_tokens
                if (
                    definition.max_total_context_tokens is not None
                    and definition.max_total_context_tokens != 4096
                ):
                    merged.max_total_context_tokens = definition.max_total_context_tokens

                # Pricing merge
                if definition.pricing.input_price is not None:
                    merged.pricing.input_price = definition.pricing.input_price
                if definition.pricing.output_price is not None:
                    merged.pricing.output_price = definition.pricing.output_price
                if definition.pricing.is_free:
                    merged.pricing.is_free = True

                # Privacy merge
                if definition.privacy.execution_location != ExecutionLocation.UNKNOWN:
                    merged.privacy.execution_location = definition.privacy.execution_location
                if definition.privacy.data_leaves_device != TriStateBool.UNKNOWN:
                    merged.privacy.data_leaves_device = definition.privacy.data_leaves_device
                if definition.privacy.zero_data_retention != TriStateBool.UNKNOWN:
                    merged.privacy.zero_data_retention = definition.privacy.zero_data_retention
                if definition.privacy.compliance_tags:
                    merged.privacy.compliance_tags = list(
                        set(merged.privacy.compliance_tags + definition.privacy.compliance_tags)
                    )

                # Hardware merge
                if definition.hardware is not None:
                    merged.hardware = definition.hardware

                # Latency merge (preserve catalog baseline class)
                if definition.latency.catalog_latency_class != LatencyClass.UNKNOWN:
                    merged.latency.catalog_latency_class = definition.latency.catalog_latency_class
                if definition.latency.catalog_latency_ms is not None:
                    merged.latency.catalog_latency_ms = definition.latency.catalog_latency_ms
                if definition.latency.observed_metrics is not None:
                    merged.latency.observed_metrics = definition.latency.observed_metrics

                merged.provenance = max(
                    definition.provenance, existing.provenance, key=lambda p: p.precedence
                )
                merged.updated_at = time.time()
                self._models[cid] = merged
                return True

            definition.updated_at = time.time()
            self._models[cid] = definition
            return True

    def unregister_model(self, scoped_id: Union[str, ModelIdentity]) -> bool:
        """Remove a model from the registry by its scoped ID."""
        with self._lock:
            cid = self.resolve_canonical_id(scoped_id)
            if cid in self._models:
                del self._models[cid]
                return True
            return False

    def get_model(self, scoped_id: Union[str, ModelIdentity]) -> Optional[ModelDefinition]:
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
                if local_only and m.privacy.is_local != TriStateBool.TRUE:
                    continue
                if tag and tag not in m.tags:
                    continue
                results.append(m)

            return sorted(results, key=lambda x: x.canonical_id)

    def update_telemetry(self, scoped_id: Union[str, ModelIdentity], latency_ms: float) -> bool:
        """Update runtime observed latency telemetry without mutating catalog classification."""
        with self._lock:
            cid = self.resolve_canonical_id(scoped_id)
            model = self._models.get(cid)
            if not model:
                return False

            if model.latency.observed_metrics is None:
                model.latency.observed_metrics = ObservedLatencyMetrics()

            obs = model.latency.observed_metrics
            obs.sample_count += 1
            obs.last_observed_ms = latency_ms
            obs.observed_at = time.time()

            if obs.p50_ms is None:
                obs.p50_ms = latency_ms
                obs.p90_ms = latency_ms
                obs.p99_ms = latency_ms
            else:
                obs.p50_ms = round(0.7 * obs.p50_ms + 0.3 * latency_ms, 1)
                obs.p90_ms = max(obs.p90_ms, latency_ms)
                obs.p99_ms = max(obs.p99_ms, latency_ms)

            # Static catalog_latency_class is preserved untouched!
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
        3. No Premature Routing: Candidates are NOT scored or sorted into winners.
           Score represents deterministic metadata completeness [0.0, 1.0].
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

            # 4. Pricing constraints (unit-explicit, missing is UNKNOWN, never zero)
            if requirements.max_input_cost_per_million is not None:
                cost_in = model.pricing.input_cost_per_million
                if cost_in is None:
                    reasons.append(
                        "Input pricing is UNKNOWN (cannot verify max_input_cost_per_million)"
                    )
                elif cost_in > requirements.max_input_cost_per_million:
                    reasons.append(
                        f"Input cost ${cost_in:.3f}/M > allowed ${requirements.max_input_cost_per_million:.3f}/M"
                    )

            if requirements.max_output_cost_per_million is not None:
                cost_out = model.pricing.output_cost_per_million
                if cost_out is None:
                    reasons.append(
                        "Output pricing is UNKNOWN (cannot verify max_output_cost_per_million)"
                    )
                elif cost_out > requirements.max_output_cost_per_million:
                    reasons.append(
                        f"Output cost ${cost_out:.3f}/M > allowed ${requirements.max_output_cost_per_million:.3f}/M"
                    )

            # 5. Latency constraints (static catalog class separate from telemetry)
            if requirements.max_latency_ms is not None:
                eff_lat = model.latency.effective_latency_ms
                if eff_lat is None:
                    reasons.append("Latency is UNKNOWN (cannot verify max_latency_ms)")
                elif eff_lat > requirements.max_latency_ms:
                    reasons.append(
                        f"Latency {eff_lat:.1f}ms > allowed {requirements.max_latency_ms:.1f}ms"
                    )

            if requirements.allowed_latency_classes:
                if model.latency.catalog_latency_class not in requirements.allowed_latency_classes:
                    reasons.append(
                        f"Catalog latency class '{model.latency.catalog_latency_class.value}' not in allowed classes"
                    )

            # 6. Privacy constraints (3-valued logic, UNKNOWN rejected on hard privacy requirements)
            if requirements.require_local_only:
                if model.privacy.execution_location != ExecutionLocation.LOCAL:
                    reasons.append(
                        f"Model execution location is '{model.privacy.execution_location.value}' (violates require_local_only)"
                    )
                if model.privacy.data_leaves_device != TriStateBool.FALSE:
                    reasons.append(
                        f"Data leaves device is {model.privacy.data_leaves_device.value} (violates require_local_only)"
                    )

            if not requirements.allow_data_leaves_device:
                if model.privacy.data_leaves_device != TriStateBool.FALSE:
                    reasons.append(
                        f"Data leaves device is {model.privacy.data_leaves_device.value} (violates allow_data_leaves_device=False)"
                    )

            if requirements.require_zero_retention:
                if model.privacy.zero_data_retention != TriStateBool.TRUE:
                    reasons.append(
                        f"Zero data retention is {model.privacy.zero_data_retention.value} (violates require_zero_retention=True)"
                    )

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

            # Deterministic metadata completeness score (NOT routing preference)
            all_caps = [
                model.capabilities.reasoning,
                model.capabilities.coding,
                model.capabilities.vision,
                model.capabilities.tools,
                model.capabilities.structured_output,
                model.capabilities.embeddings,
                model.capabilities.streaming,
            ]
            known_count = sum(1 for c in all_caps if c != TriStateBool.UNKNOWN)
            completeness_score = round(known_count / len(all_caps), 2)

            candidate = ModelCandidate(
                canonical_id=model.canonical_id,
                provider_id=model.provider_id,
                model_id=model.model_id,
                model_definition=model,
                eligible=is_eligible,
                rejection_reasons=reasons,
                score=completeness_score if is_eligible else 0.0,
            )

            if not eligible_only or is_eligible:
                candidates.append(candidate)

        # Deterministic sort: eligible first, then alphabetical by canonical_id (no winner ranking)
        candidates.sort(key=lambda c: (not c.eligible, c.canonical_id))
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
