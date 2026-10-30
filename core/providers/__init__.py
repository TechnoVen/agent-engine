"""core/providers/__init__.py

Canonical Provider Capability Subsystem for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).
"""

from core.providers.adapters import (
    AnthropicAdapter,
    DeepSeekAdapter,
    GeminiAdapter,
    GroqAdapter,
    KimiAdapter,
    LlamaCppAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    OpenAICompatibleAdapter,
)
from core.providers.base import (
    NormalizedProviderError,
    ProviderAdapter,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderInvalidRequestError,
    ProviderInvocationResult,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
)
from core.providers.models import (
    ProviderAuthType,
    ProviderAvailability,
    ProviderCallEvidence,
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderConfigurationState,
    ProviderDefinition,
    ProviderEndpointClass,
    ProviderEndpointStyle,
    ProviderHealth,
    ProviderHealthStatus,
)
from core.providers.registry import (
    ProviderRegistry,
    get_provider_registry,
    migrate_config_dict,
    reset_provider_registry,
)

__all__ = [
    # Models & Enums
    "ProviderAuthType",
    "ProviderAvailability",
    "ProviderConfigurationState",
    "ProviderEndpointClass",
    "ProviderEndpointStyle",
    "ProviderHealthStatus",
    "ProviderCapabilities",
    "ProviderHealth",
    "ProviderConfiguration",
    "ProviderDefinition",
    "ProviderCallEvidence",
    # Base Adapter & Results
    "ProviderAdapter",
    "ProviderInvocationResult",
    # Normalized Errors
    "NormalizedProviderError",
    "ProviderAuthenticationError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderConnectionError",
    "ProviderNotFoundError",
    "ProviderServerError",
    "ProviderInvalidRequestError",
    # Concrete Adapters
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "OllamaAdapter",
    "LlamaCppAdapter",
    "DeepSeekAdapter",
    "GroqAdapter",
    "KimiAdapter",
    "OpenAICompatibleAdapter",
    # Registry & Singleton
    "ProviderRegistry",
    "get_provider_registry",
    "migrate_config_dict",
    "reset_provider_registry",
]
