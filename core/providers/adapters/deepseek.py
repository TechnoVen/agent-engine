"""core/providers/adapters/deepseek.py

DeepSeek Provider Adapter for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import dspy

from core.providers.adapters.compatible import OpenAICompatibleAdapter

logger = logging.getLogger("agent_engine.providers.deepseek")


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Canonical adapter for DeepSeek intelligence services."""

    def create_dspy_lm(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        cache: bool = True,
        timeout: Optional[float] = None,
        api_key: Optional[str] = None,
    ) -> dspy.LM:
        key = api_key or self.resolve_api_key()
        m = model or self._definition.default_model
        model_name = m if m.startswith("deepseek/") else f"deepseek/{m}"
        base_url = self._get_base_url()
        to = timeout or self._definition.config.timeout_seconds

        kwargs: Dict[str, Any] = {
            "api_key": key,
            "api_base": base_url,
            "max_tokens": max_tokens or 4000,
            "cache": cache,
            "timeout": to,
        }
        return dspy.LM(model_name, **kwargs)
