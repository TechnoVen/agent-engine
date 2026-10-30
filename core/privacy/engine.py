"""core/privacy/engine.py

Authoritative Privacy and Data-Routing Policy Engine for Agent Engine.
Part of Milestone R3 Task R3.8 (Privacy classes and data-routing policy).

Governing Principles:
1. Strict hierarchical precedence: Profile -> Project -> Task.
2. Anti-Relaxation Defense: Untrusted sources (documents, prompts, tools, model outputs,
   forged renderer headers) cannot relax privacy policy under any circumstance.
3. 3-Valued Logic: UNKNOWN location or UNKNOWN egress fails closed under LOCAL_ONLY.
4. Canonical Identity Matching: Canonical provider_id and model_id; no wildcards or substrings.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Union


from core.model_registry.models import ExecutionLocation, ModelDefinition, TriStateBool
from core.privacy.models import (
    ApprovedCloudTarget,
    DataRoutingClass,
    DataRoutingPolicy,
    EffectiveRoutingPolicy,
    PrivacyEligibilityReason,
    ProviderPrivacyEligibility,
    RoutingPolicySource,
)
from core.providers.models import ProviderDefinition, ProviderEndpointClass
from core.providers.registry import _CANONICAL_ALIAS_MAP

logger = logging.getLogger("agent_engine.privacy.engine")


class PrivacyPolicyEngine:
    """Evaluates privacy policy resolution and model/provider eligibility."""

    @staticmethod
    def resolve_effective_policy(
        profile_policy: Optional[DataRoutingPolicy] = None,
        project_policy: Optional[DataRoutingPolicy] = None,
        task_policy: Optional[Union[DataRoutingPolicy, DataRoutingClass, str]] = None,
        is_trusted_authority: bool = False,
    ) -> EffectiveRoutingPolicy:
        """Resolve effective data routing policy according to canonical precedence.

        Precedence Hierarchy:
        Profile Default -> Project Setting -> Task Override

        Rules:
        1. Tightening is always permitted at narrower scopes.
        2. Relaxing requires explicit trusted authority and permissions; untrusted entities
           or unauthenticated requests fail closed / retain the stricter policy.
        """
        # 1. Base Profile Policy
        base_profile = profile_policy or get_system_routing_policy()

        effective_class = base_profile.routing_class
        source = RoutingPolicySource.PROFILE_DEFAULT

        approved_targets: List[ApprovedCloudTarget] = list(base_profile.approved_cloud_targets)
        relaxation_attempted = False
        relaxation_denied = False
        audit_reasons: List[str] = []

        # 2. Project Policy Override
        if project_policy is not None:
            if project_policy.routing_class.is_tightening_of(effective_class):
                # Narrowing/tightening is unconditionally permitted
                effective_class = project_policy.routing_class
                source = RoutingPolicySource.PROJECT_OVERRIDE
                approved_targets = list(project_policy.approved_cloud_targets)
            elif project_policy.routing_class.is_relaxation_of(effective_class):
                relaxation_attempted = True
                if is_trusted_authority and base_profile.allow_project_relaxation:
                    effective_class = project_policy.routing_class
                    source = RoutingPolicySource.PROJECT_OVERRIDE
                    approved_targets = list(project_policy.approved_cloud_targets)
                else:
                    relaxation_denied = True
                    audit_reasons.append(
                        f"Project policy attempt to relax '{effective_class.value}' to "
                        f"'{project_policy.routing_class.value}' denied: requires trusted authority "
                        "and profile allow_project_relaxation=True"
                    )
            else:
                # Same class, update source and targets
                source = RoutingPolicySource.PROJECT_OVERRIDE
                if project_policy.approved_cloud_targets:
                    approved_targets = list(project_policy.approved_cloud_targets)

        # 3. Task Policy Override
        normalized_task_policy: Optional[DataRoutingPolicy] = None
        if task_policy is not None:
            if isinstance(task_policy, str):
                try:
                    normalized_task_policy = DataRoutingPolicy(
                        routing_class=DataRoutingClass(task_policy.strip().lower())
                    )
                except ValueError:
                    audit_reasons.append(f"Invalid task privacy class '{task_policy}' ignored")
            elif isinstance(task_policy, DataRoutingClass):
                normalized_task_policy = DataRoutingPolicy(routing_class=task_policy)
            elif isinstance(task_policy, DataRoutingPolicy):
                normalized_task_policy = task_policy

        if normalized_task_policy is not None:
            task_class = normalized_task_policy.routing_class
            if task_class.is_tightening_of(effective_class):
                # Tightening is unconditionally permitted
                effective_class = task_class
                source = RoutingPolicySource.TASK_OVERRIDE
                if normalized_task_policy.approved_cloud_targets:
                    approved_targets = list(normalized_task_policy.approved_cloud_targets)
            elif task_class.is_relaxation_of(effective_class):
                relaxation_attempted = True
                # Check if task relaxation is authorized
                allow_by_project = (
                    project_policy.allow_relaxation_by_task
                    if project_policy is not None
                    else base_profile.allow_relaxation_by_task
                )
                if is_trusted_authority and allow_by_project:
                    effective_class = task_class
                    source = RoutingPolicySource.TASK_OVERRIDE
                    if normalized_task_policy.approved_cloud_targets:
                        approved_targets = list(normalized_task_policy.approved_cloud_targets)
                else:
                    relaxation_denied = True
                    audit_reasons.append(
                        f"Task attempt to relax '{effective_class.value}' to "
                        f"'{task_class.value}' denied: requires trusted authority "
                        "and allow_relaxation_by_task=True"
                    )
            else:
                # Same class
                source = RoutingPolicySource.TASK_OVERRIDE
                if normalized_task_policy.approved_cloud_targets and is_trusted_authority:
                    approved_targets = list(normalized_task_policy.approved_cloud_targets)

        return EffectiveRoutingPolicy(
            effective_class=effective_class,
            source=source,
            profile_policy=base_profile,
            project_policy=project_policy,
            task_policy=normalized_task_policy,
            approved_targets=approved_targets,
            relaxation_attempted=relaxation_attempted,
            relaxation_denied=relaxation_denied,
            audit_reason="; ".join(audit_reasons) if audit_reasons else None,
        )

    @staticmethod
    def evaluate_model_privacy(
        model: ModelDefinition,
        effective_policy: EffectiveRoutingPolicy,
    ) -> ProviderPrivacyEligibility:
        """Evaluate a model's privacy metadata against the effective routing policy."""
        reasons: List[PrivacyEligibilityReason] = []
        provider_id = _CANONICAL_ALIAS_MAP.get(
            model.provider_id.strip().lower(), model.provider_id.strip().lower()
        )
        model_id = model.model_id.strip().lower() if model.model_id else None
        location = model.privacy.execution_location
        data_leaves_device = model.privacy.data_leaves_device

        # 1. LOCAL_ONLY Evaluation
        if effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY:
            # Check execution location
            if location == ExecutionLocation.UNKNOWN:
                reasons.append(PrivacyEligibilityReason.PRIVACY_LOCATION_UNKNOWN)
            elif location != ExecutionLocation.LOCAL:
                reasons.append(PrivacyEligibilityReason.PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER)

            # Check data leaves device
            if data_leaves_device == TriStateBool.UNKNOWN:
                reasons.append(PrivacyEligibilityReason.PRIVACY_DATA_EGRESS_UNKNOWN)
            elif data_leaves_device != TriStateBool.FALSE:
                reasons.append(PrivacyEligibilityReason.PRIVACY_DATA_LEAVES_DEVICE_FORBIDDEN)

            # Managed llamacpp on localhost qualifies as LOCAL with data_leaves_device=FALSE
            # If a model claims to be local but provider is a known remote cloud provider, reject
            known_cloud_providers = {"openai", "anthropic", "gemini", "deepseek", "groq", "kimi"}
            if provider_id in known_cloud_providers:
                if PrivacyEligibilityReason.PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER not in reasons:
                    reasons.append(PrivacyEligibilityReason.PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER)

        # 2. APPROVED_CLOUD Evaluation
        elif effective_policy.effective_class == DataRoutingClass.APPROVED_CLOUD:
            # If local model, it is automatically eligible
            is_local = (
                location == ExecutionLocation.LOCAL and data_leaves_device == TriStateBool.FALSE
            )
            if not is_local:
                # Cloud model: must be explicitly approved in targets
                if not effective_policy.is_target_approved(provider_id, model_id):
                    # Check if provider is approved but specific model was restricted
                    provider_matched = any(
                        t.provider_id == provider_id for t in effective_policy.approved_targets
                    )
                    if provider_matched:
                        reasons.append(PrivacyEligibilityReason.PRIVACY_MODEL_NOT_APPROVED)
                    else:
                        reasons.append(PrivacyEligibilityReason.PRIVACY_PROVIDER_NOT_APPROVED)

        # 3. ANY_CONFIGURED Evaluation
        elif effective_policy.effective_class == DataRoutingClass.ANY_CONFIGURED:
            # Any configured provider is privacy-eligible (still subject to health, capabilities, etc.)
            pass

        return ProviderPrivacyEligibility(
            eligible=len(reasons) == 0,
            rejection_reasons=reasons,
            provider_id=provider_id,
            model_id=model_id,
            execution_location=location,
            data_leaves_device=data_leaves_device,
        )

    @staticmethod
    def evaluate_provider_privacy(
        provider_id: str,
        effective_policy: EffectiveRoutingPolicy,
        provider_def: Optional[ProviderDefinition] = None,
    ) -> ProviderPrivacyEligibility:
        """Evaluate a provider's privacy eligibility directly."""
        canon_pid = _CANONICAL_ALIAS_MAP.get(
            provider_id.strip().lower(), provider_id.strip().lower()
        )
        reasons: List[PrivacyEligibilityReason] = []

        is_local = False
        location = ExecutionLocation.UNKNOWN
        data_leaves_device = TriStateBool.UNKNOWN

        if provider_def is not None:
            if provider_def.endpoint_class == ProviderEndpointClass.LOCAL_MANAGED:
                is_local = True
                location = ExecutionLocation.LOCAL
                data_leaves_device = TriStateBool.FALSE
            elif provider_def.endpoint_class == ProviderEndpointClass.LOCAL_EXTERNAL:
                # Deferred external local runtime (R3.7) has unknown egress for 0.5
                location = ExecutionLocation.LOCAL
                data_leaves_device = TriStateBool.UNKNOWN
            elif provider_def.endpoint_class == ProviderEndpointClass.CLOUD:
                location = ExecutionLocation.REMOTE
                data_leaves_device = TriStateBool.TRUE
        else:
            if canon_pid == "llamacpp":
                is_local = True
                location = ExecutionLocation.LOCAL
                data_leaves_device = TriStateBool.FALSE
            elif canon_pid == "ollama":
                location = ExecutionLocation.LOCAL
                data_leaves_device = TriStateBool.UNKNOWN
            elif canon_pid in {"openai", "anthropic", "gemini", "deepseek", "groq", "kimi"}:
                location = ExecutionLocation.REMOTE
                data_leaves_device = TriStateBool.TRUE

        if effective_policy.effective_class == DataRoutingClass.LOCAL_ONLY:
            if not is_local:
                if location == ExecutionLocation.UNKNOWN:
                    reasons.append(PrivacyEligibilityReason.PRIVACY_LOCATION_UNKNOWN)
                else:
                    reasons.append(PrivacyEligibilityReason.PRIVACY_LOCAL_ONLY_REMOTE_PROVIDER)
            if data_leaves_device == TriStateBool.UNKNOWN:
                reasons.append(PrivacyEligibilityReason.PRIVACY_DATA_EGRESS_UNKNOWN)
            elif data_leaves_device == TriStateBool.TRUE:
                reasons.append(PrivacyEligibilityReason.PRIVACY_DATA_LEAVES_DEVICE_FORBIDDEN)

        elif effective_policy.effective_class == DataRoutingClass.APPROVED_CLOUD:
            if not is_local:
                if not effective_policy.is_target_approved(canon_pid):
                    reasons.append(PrivacyEligibilityReason.PRIVACY_PROVIDER_NOT_APPROVED)

        return ProviderPrivacyEligibility(
            eligible=len(reasons) == 0,
            rejection_reasons=reasons,
            provider_id=canon_pid,
            model_id=None,
            execution_location=location,
            data_leaves_device=data_leaves_device,
        )


_system_routing_policy: Optional[DataRoutingPolicy] = None


def get_system_routing_policy() -> DataRoutingPolicy:
    """Get the active system/profile data routing policy."""
    global _system_routing_policy
    if _system_routing_policy is None:
        _system_routing_policy = DataRoutingPolicy(
            routing_class=DataRoutingClass.ANY_CONFIGURED,
            approved_cloud_targets=[],
            allow_relaxation_by_task=True,
            allow_project_relaxation=True,
        )
    return _system_routing_policy


def set_system_routing_policy(policy: DataRoutingPolicy) -> DataRoutingPolicy:
    """Set the active system/profile data routing policy."""
    global _system_routing_policy
    _system_routing_policy = policy
    return _system_routing_policy


def reset_system_routing_policy() -> None:
    """Reset system routing policy to default (for test isolation)."""
    global _system_routing_policy
    _system_routing_policy = None
