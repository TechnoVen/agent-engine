"""Feature Flag System for Agent Engine.

Enforces ADR-007 (Conflict C7) to gate enterprise multi-tenancy, multi-user,
cloud sync, and registry features so that local/personal builds remain lightweight.
"""

import os
import threading
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException, status


class TenantMode(str, Enum):
    SINGLE = "single"
    MULTI = "multi"


def _parse_bool(val: Optional[str], default: bool) -> bool:
    if val is None:
        return default
    s = val.strip().lower()
    if s in ("1", "true", "yes", "on", "t"):
        return True
    if s in ("0", "false", "no", "off", "f"):
        return False
    return default


@dataclass
class FeatureFlags:
    tenant_mode: TenantMode = TenantMode.SINGLE
    enable_multi_user: bool = False
    enable_registry: bool = True
    enable_cloud_sync: bool = False
    enable_acp: bool = False
    enable_auto_patch_apply: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tenant_mode"] = self.tenant_mode.value
        return d


_LOCK = threading.RLock()
_OVERRIDES: Dict[str, Any] = {}


def get_feature_flags() -> FeatureFlags:
    """Resolve active feature flags from environment variables + runtime overrides."""
    with _LOCK:
        # 1. Base values from environment
        raw_mode = os.getenv("TENANT_MODE", "single").strip().lower()
        mode = TenantMode.MULTI if raw_mode == "multi" else TenantMode.SINGLE

        flags = FeatureFlags(
            tenant_mode=mode,
            enable_multi_user=_parse_bool(os.getenv("ENABLE_MULTI_USER"), False),
            enable_registry=_parse_bool(os.getenv("ENABLE_REGISTRY"), True),
            enable_cloud_sync=_parse_bool(os.getenv("ENABLE_CLOUD_SYNC"), False),
            enable_acp=_parse_bool(os.getenv("ENABLE_ACP"), False),
            enable_auto_patch_apply=_parse_bool(os.getenv("ENABLE_AUTO_PATCH_APPLY"), False),
        )

        # 2. Apply runtime overrides
        for k, v in _OVERRIDES.items():
            if hasattr(flags, k):
                if k == "tenant_mode":
                    if isinstance(v, TenantMode):
                        setattr(flags, k, v)
                    else:
                        setattr(
                            flags,
                            k,
                            TenantMode.MULTI if str(v).lower() == "multi" else TenantMode.SINGLE,
                        )
                else:
                    setattr(flags, k, bool(v) if not isinstance(v, str) else _parse_bool(v, False))

        return flags


def is_flag_enabled(flag_name: str) -> bool:
    """Check if a boolean feature flag is currently active."""
    flags = get_feature_flags()
    val = getattr(flags, flag_name, None)
    if isinstance(val, bool):
        return val
    if isinstance(val, TenantMode):
        return val == TenantMode.MULTI
    return bool(val)


def set_flag_override(flag_name: str, value: Any) -> None:
    """Set a runtime override for a feature flag."""
    with _LOCK:
        _OVERRIDES[flag_name] = value


def reset_flag_overrides() -> None:
    """Clear all active runtime overrides."""
    with _LOCK:
        _OVERRIDES.clear()


def require_flag(flag_name: str) -> Callable[[], None]:
    """FastAPI route dependency that raises HTTP 404 if the feature flag is disabled."""

    def _dependency():
        if not is_flag_enabled(flag_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feature '{flag_name}' is disabled in current configuration.",
            )

    return _dependency
