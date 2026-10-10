"""core/packs package for Agent Engine 0.5.

Modular Capability Packs architecture supporting Milestone R5.
"""

from core.packs.models import (
    PackCapability,
    PackEvaluation,
    PackManifest,
    PackPermission,
    PackPermissionScope,
    PackSkill,
    PackWorkflow,
)
from core.packs.service import (
    CANONICAL_BINDING_ALLOWLIST,
    CapabilityPackService,
    PackValidationError,
    get_capability_pack_service,
)

__all__ = [
    "PackCapability",
    "PackEvaluation",
    "PackManifest",
    "PackPermission",
    "PackPermissionScope",
    "PackSkill",
    "PackWorkflow",
    "CANONICAL_BINDING_ALLOWLIST",
    "CapabilityPackService",
    "PackValidationError",
    "get_capability_pack_service",
]
