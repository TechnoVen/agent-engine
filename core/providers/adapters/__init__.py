"""core/providers/adapters/__init__.py

Canonical Provider Adapters for Agent Engine.
Part of Milestone R3 Task R3.1 (Canonical Provider Registry Contract).
"""

from core.providers.adapters.anthropic import AnthropicAdapter
from core.providers.adapters.compatible import OpenAICompatibleAdapter
from core.providers.adapters.deepseek import DeepSeekAdapter
from core.providers.adapters.gemini import GeminiAdapter
from core.providers.adapters.groq import GroqAdapter
from core.providers.adapters.kimi import KimiAdapter
from core.providers.adapters.llamacpp import LlamaCppAdapter
from core.providers.adapters.ollama import OllamaAdapter
from core.providers.adapters.openai import OpenAIAdapter

__all__ = [
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "OllamaAdapter",
    "LlamaCppAdapter",
    "DeepSeekAdapter",
    "GroqAdapter",
    "KimiAdapter",
    "OpenAICompatibleAdapter",
]
