"""core/model_recommendation/catalog.py

Curated and versioned local model catalog for Agent Engine.
Part of Milestone R3 Task R3.5 (Local Model Catalog and Recommendation).

Invariants:
1. Curated, Not Global Index: Contains only vetted, llama.cpp-compatible local models.
2. Versioned & Timestamped: Fixed catalog schema version and update timestamp.
3. Factual Hardware Requirements: Includes minimum and recommended RAM/VRAM, parameter count,
   quantization, context limits, and capability mappings.
4. No Model Downloading: Downloading, resume, and hash verification belong strictly to Task R3.6.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from core.model_recommendation.models import (
    CatalogModelEntry,
    RequirementsProvenance,
)
from core.model_registry.models import ModelIdentity, TriStateBool

DEFAULT_CATALOG_VERSION = "2026.10.1"
DEFAULT_CATALOG_UPDATED_AT = "2026-10-08T00:00:00Z"


def get_curated_local_models() -> List[CatalogModelEntry]:
    """Return the authoritative curated list of supported local models for Agent Engine."""
    return [
        # 1. Llama 3.2 1B Instruct (Ultra-lightweight general assistant)
        CatalogModelEntry(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="llama-3.2-1b-instruct-q4_k_m"
            ),
            family="llama3.2",
            architecture="llama",
            parameter_size="1B",
            parameter_count_billions=1.2,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            artifact_size_bytes=850 * 1024 * 1024,  # ~850 MB
            min_ram_bytes=int(1.5 * 1024 * 1024 * 1024),  # 1.5 GB
            recommended_ram_bytes=2 * 1024 * 1024 * 1024,  # 2.0 GB
            context_window_limit=8192,
            capabilities={
                "coding": TriStateBool.FALSE,
                "reasoning": TriStateBool.FALSE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.FALSE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_score=0.50,
            provenance=RequirementsProvenance.TRUSTED_CATALOG,
            catalog_version=DEFAULT_CATALOG_VERSION,
            updated_at=DEFAULT_CATALOG_UPDATED_AT,
        ),
        # 2. Qwen 2.5 Coder 1.5B Instruct (Ultra-fast local code generator)
        CatalogModelEntry(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="qwen2.5-coder-1.5b-instruct-q4_k_m"
            ),
            family="qwen2.5-coder",
            architecture="qwen2",
            parameter_size="1.5B",
            parameter_count_billions=1.5,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            artifact_size_bytes=int(1.1 * 1024 * 1024 * 1024),  # ~1.1 GB
            min_ram_bytes=2 * 1024 * 1024 * 1024,  # 2.0 GB
            recommended_ram_bytes=int(2.5 * 1024 * 1024 * 1024),  # 2.5 GB
            context_window_limit=32768,
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.FALSE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_score=0.65,
            provenance=RequirementsProvenance.TRUSTED_CATALOG,
            catalog_version=DEFAULT_CATALOG_VERSION,
            updated_at=DEFAULT_CATALOG_UPDATED_AT,
        ),
        # 3. Llama 3.2 3B Instruct (Compact conversational model)
        CatalogModelEntry(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="llama-3.2-3b-instruct-q4_k_m"
            ),
            family="llama3.2",
            architecture="llama",
            parameter_size="3B",
            parameter_count_billions=3.2,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            artifact_size_bytes=int(2.0 * 1024 * 1024 * 1024),  # ~2.0 GB
            min_ram_bytes=3 * 1024 * 1024 * 1024,  # 3.0 GB
            recommended_ram_bytes=4 * 1024 * 1024 * 1024,  # 4.0 GB
            context_window_limit=16384,
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.FALSE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_score=0.72,
            provenance=RequirementsProvenance.TRUSTED_CATALOG,
            catalog_version=DEFAULT_CATALOG_VERSION,
            updated_at=DEFAULT_CATALOG_UPDATED_AT,
        ),
        # 4. Qwen 2.5 Coder 3B Instruct (Default balanced local code and reasoning engine)
        CatalogModelEntry(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m"
            ),
            family="qwen2.5-coder",
            architecture="qwen2",
            parameter_size="3B",
            parameter_count_billions=3.1,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            artifact_size_bytes=int(2.0 * 1024 * 1024 * 1024),  # ~2.0 GB
            min_ram_bytes=3 * 1024 * 1024 * 1024,  # 3.0 GB
            recommended_ram_bytes=4 * 1024 * 1024 * 1024,  # 4.0 GB
            context_window_limit=32768,
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_score=0.80,
            provenance=RequirementsProvenance.TRUSTED_CATALOG,
            catalog_version=DEFAULT_CATALOG_VERSION,
            updated_at=DEFAULT_CATALOG_UPDATED_AT,
        ),
        # 5. Qwen 2.5 Coder 7B Instruct (Strong code/reasoning model for medium-to-high workstations)
        CatalogModelEntry(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="qwen2.5-coder-7b-instruct-q4_k_m"
            ),
            family="qwen2.5-coder",
            architecture="qwen2",
            parameter_size="7B",
            parameter_count_billions=7.6,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            artifact_size_bytes=int(4.7 * 1024 * 1024 * 1024),  # ~4.7 GB
            min_ram_bytes=6 * 1024 * 1024 * 1024,  # 6.0 GB
            recommended_ram_bytes=8 * 1024 * 1024 * 1024,  # 8.0 GB
            context_window_limit=32768,
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_score=0.88,
            provenance=RequirementsProvenance.TRUSTED_CATALOG,
            catalog_version=DEFAULT_CATALOG_VERSION,
            updated_at=DEFAULT_CATALOG_UPDATED_AT,
        ),
        # 6. Qwen 2.5 14B Instruct (High-tier local intelligence model)
        CatalogModelEntry(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="qwen2.5-14b-instruct-q4_k_m"
            ),
            family="qwen2.5",
            architecture="qwen2",
            parameter_size="14B",
            parameter_count_billions=14.7,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            artifact_size_bytes=int(9.0 * 1024 * 1024 * 1024),  # ~9.0 GB
            min_ram_bytes=12 * 1024 * 1024 * 1024,  # 12.0 GB
            recommended_ram_bytes=16 * 1024 * 1024 * 1024,  # 16.0 GB
            context_window_limit=32768,
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_score=0.93,
            provenance=RequirementsProvenance.TRUSTED_CATALOG,
            catalog_version=DEFAULT_CATALOG_VERSION,
            updated_at=DEFAULT_CATALOG_UPDATED_AT,
        ),
        # 7. Qwen 2.5 32B Instruct (Extreme-tier local model for 32GB+ systems)
        CatalogModelEntry(
            model_identity=ModelIdentity(
                provider_id="llamacpp", model_id="qwen2.5-32b-instruct-q4_k_m"
            ),
            family="qwen2.5",
            architecture="qwen2",
            parameter_size="32B",
            parameter_count_billions=32.5,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            artifact_size_bytes=int(20.0 * 1024 * 1024 * 1024),  # ~20.0 GB
            min_ram_bytes=24 * 1024 * 1024 * 1024,  # 24.0 GB
            recommended_ram_bytes=32 * 1024 * 1024 * 1024,  # 32.0 GB
            context_window_limit=32768,
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_score=0.97,
            provenance=RequirementsProvenance.TRUSTED_CATALOG,
            catalog_version=DEFAULT_CATALOG_VERSION,
            updated_at=DEFAULT_CATALOG_UPDATED_AT,
        ),
    ]


class LocalModelCatalog:
    """Thread-safe in-memory registry of curated local models."""

    def __init__(
        self,
        models: Optional[List[CatalogModelEntry]] = None,
        version: str = DEFAULT_CATALOG_VERSION,
        updated_at: str = DEFAULT_CATALOG_UPDATED_AT,
    ) -> None:
        self.version = version
        self.updated_at = updated_at
        self._models: Dict[str, CatalogModelEntry] = {}
        for m in models or get_curated_local_models():
            self.register_model(m)

    def register_model(self, entry: CatalogModelEntry) -> None:
        key = entry.model_identity.canonical_id
        self._models[key] = entry

    def get_model(self, model_identity: ModelIdentity) -> Optional[CatalogModelEntry]:
        return self._models.get(model_identity.canonical_id)

    def get_all_models(self) -> List[CatalogModelEntry]:
        return list(self._models.values())
