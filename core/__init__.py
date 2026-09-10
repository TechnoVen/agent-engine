"""
Core DSPy Agent Engine package.
"""

# ruff: noqa: I001, F401
import numpy  # Pre-load numpy before dspy lazy imports
import dspy

# Unlock thread restrictions across Streamlit & worker threads
try:
    type(dspy.settings)._ensure_configure_allowed = lambda self: None
except Exception:
    pass

from core.engine import AgentPipeline, DynamicSignatureBuilder, LowCodeAgent, NodeConfig
from core.harness import AgentHarness, train_and_optimize
from core.memory import AgentMemory, RAGModule

# from core.router import ModelRouter, get_language_model
from core.router import ModelRouter
from core.templates import SkillTemplate, TemplateManager, load_template_agent

__all__ = [
    "LowCodeAgent",
    "NodeConfig",
    "DynamicSignatureBuilder",
    "AgentPipeline",
    "ModelRouter",
    "get_language_model",
    "AgentMemory",
    "RAGModule",
    "AgentHarness",
    "train_and_optimize",
    "SkillTemplate",
    "TemplateManager",
    "load_template_agent",
]
