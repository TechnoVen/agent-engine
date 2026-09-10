"""
core/pipelines package.
Provides modular DSPy pipeline registration, metadata discovery, and pre-built standard pipelines.
"""

from core.pipelines.registry import (
    PipelineMetadata,
    PipelineRegistry,
    get_pipeline_registry,
    register_pipeline,
)
from core.pipelines.standard import (
    ChapterWritePipeline,
    CodeFixPipeline,
    CodeLintPipeline,
    EmailDraftPipeline,
    FinanceExtractPipeline,
    SecurityAuditPipeline,
)

__all__ = [
    "PipelineRegistry",
    "PipelineMetadata",
    "register_pipeline",
    "get_pipeline_registry",
    "SecurityAuditPipeline",
    "CodeLintPipeline",
    "CodeFixPipeline",
    "EmailDraftPipeline",
    "FinanceExtractPipeline",
    "ChapterWritePipeline",
]
