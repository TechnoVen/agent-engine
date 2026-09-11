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
from core.memory import (
    AgentMemory,
    Observation,
    ObservationalMemory,
    PreferenceExtractor,
    RAGModule,
    ScoredObservation,
    SessionSummarizer,
)

# from core.router import ModelRouter, get_language_model
from core.router import (
    ExecutionRouter,
    ExecutionTier,
    ModelRouter,
    RatioAudit,
    StepExecutionResult,
    StepProfile,
    audit_pipeline,
    profiled_step,
)

from core.session import (
    AgentParticipant,
    ToolCall,
    UnifiedMessage,
    UnifiedSession,
    UnifiedSessionStore,
    get_session_store,
)
from core.cache import SemanticCache, cached_step, get_semantic_cache
from core.context import BuiltContext, ContextBuilder, ContextSpec, build_context
from core.eval import (
    EvalSample,
    ModelEvalReport,
    ModelEvalSuite,
    ModelRanking,
    get_golden_dataset,
)
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
    "ObservationalMemory",
    "Observation",
    "ScoredObservation",
    "PreferenceExtractor",
    "SessionSummarizer",
    "AgentHarness",
    "train_and_optimize",
    "SkillTemplate",
    "TemplateManager",
    "load_template_agent",
    "UnifiedSession",
    "UnifiedMessage",
    "AgentParticipant",
    "ToolCall",
    "UnifiedSessionStore",
    "get_session_store",
    "SemanticCache",
    "cached_step",
    "get_semantic_cache",
    "ContextSpec",
    "BuiltContext",
    "ContextBuilder",
    "build_context",
    "ModelEvalSuite",
    "EvalSample",
    "ModelEvalReport",
    "ModelRanking",
    "get_golden_dataset",
    "ExecutionRouter",
    "ExecutionTier",
    "StepProfile",
    "StepExecutionResult",
    "RatioAudit",
    "audit_pipeline",
    "profiled_step",
]
