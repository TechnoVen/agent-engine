"""
Core DSPy Agent Engine package.
"""
import numpy  # Pre-load numpy before dspy lazy imports
import dspy

# Unlock thread restrictions across Streamlit & worker threads
try:
    type(dspy.settings)._ensure_configure_allowed = lambda self: None
except Exception:
    pass

from core.engine import LowCodeAgent, NodeConfig, DynamicSignatureBuilder, AgentPipeline
from core.router import ModelRouter, get_language_model
from core.memory import AgentMemory, RAGModule
from core.harness import AgentHarness, train_and_optimize

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
]
