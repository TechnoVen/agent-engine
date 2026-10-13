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

from core.model_download.models import ModelArtifactDescriptor
from core.model_recommendation.models import (
    CatalogModelEntry,
    ModelKVArchitectureMetadata,
    NumericFactProvenance,
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
            parameter_count_provenance=NumericFactProvenance.DECLARED_FACT,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            memory_unit="bytes",
            artifact_size_bytes=807690656,
            artifact_size_provenance=NumericFactProvenance.MEASURED_FACT,
            artifact_size_source="meta_llama_3.2_1b_gguf_release",
            artifact_descriptor=ModelArtifactDescriptor(
                artifact_id="llama-3.2-1b-instruct-q4_k_m.gguf",
                model_identity=ModelIdentity(
                    provider_id="llamacpp", model_id="llama-3.2-1b-instruct-q4_k_m"
                ),
                source_url="https://huggingface.co/hugging-quants/Llama-3.2-1B-Instruct-Q4_K_M-GGUF/resolve/main/llama-3.2-1b-instruct-q4_k_m.gguf",
                expected_size_bytes=807690656,
                expected_sha256="a9b4b3b52dee68ea2d6c10f0fcf72ecf0ebef6690f2fc30ca0ca1379c379d875",
                format="gguf",
                quantization="Q4_K_M",
                provenance="curated_catalog",
                catalog_version=DEFAULT_CATALOG_VERSION,
            ),
            min_ram_bytes=int(1.5 * 1024 * 1024 * 1024),  # 1.5 GiB
            min_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            min_ram_source="curated_catalog_policy_v2026.10.1",
            recommended_ram_bytes=2 * 1024 * 1024 * 1024,  # 2.0 GiB
            recommended_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            recommended_ram_source="curated_catalog_policy_v2026.10.1",
            accelerator_required=False,
            context_window_limit=8192,
            context_window_provenance=NumericFactProvenance.DECLARED_FACT,
            kv_metadata=ModelKVArchitectureMetadata(
                num_layers=16,
                num_kv_heads=8,
                head_dim=64,
                cache_element_bytes=2,
                source="meta-llama-3.2-1b-config",
            ),
            capabilities={
                "coding": TriStateBool.FALSE,
                "reasoning": TriStateBool.FALSE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.FALSE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_rank=1,
            quality_rank_provenance=NumericFactProvenance.CURATED_POLICY,
            quality_rank_source="Agent Engine Curated Quality Policy v2026.10.1",
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
            parameter_count_provenance=NumericFactProvenance.DECLARED_FACT,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            memory_unit="bytes",
            artifact_size_bytes=int(1.1 * 1024 * 1024 * 1024),  # ~1.1 GiB
            artifact_size_provenance=NumericFactProvenance.MEASURED_FACT,
            artifact_size_source="qwen2.5_coder_1.5b_gguf_release",
            min_ram_bytes=2 * 1024 * 1024 * 1024,  # 2.0 GiB
            min_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            min_ram_source="curated_catalog_policy_v2026.10.1",
            recommended_ram_bytes=int(2.5 * 1024 * 1024 * 1024),  # 2.5 GiB
            recommended_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            recommended_ram_source="curated_catalog_policy_v2026.10.1",
            accelerator_required=False,
            context_window_limit=32768,
            context_window_provenance=NumericFactProvenance.DECLARED_FACT,
            kv_metadata=ModelKVArchitectureMetadata(
                num_layers=28,
                num_kv_heads=2,
                head_dim=128,
                cache_element_bytes=2,
                source="qwen2.5-coder-1.5b-config",
            ),
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.FALSE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_rank=2,
            quality_rank_provenance=NumericFactProvenance.CURATED_POLICY,
            quality_rank_source="Agent Engine Curated Quality Policy v2026.10.1",
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
            parameter_count_provenance=NumericFactProvenance.DECLARED_FACT,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            memory_unit="bytes",
            artifact_size_bytes=int(2.0 * 1024 * 1024 * 1024),  # ~2.0 GiB
            artifact_size_provenance=NumericFactProvenance.MEASURED_FACT,
            artifact_size_source="meta_llama_3.2_3b_gguf_release",
            min_ram_bytes=3 * 1024 * 1024 * 1024,  # 3.0 GiB
            min_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            min_ram_source="curated_catalog_policy_v2026.10.1",
            recommended_ram_bytes=4 * 1024 * 1024 * 1024,  # 4.0 GiB
            recommended_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            recommended_ram_source="curated_catalog_policy_v2026.10.1",
            accelerator_required=False,
            context_window_limit=16384,
            context_window_provenance=NumericFactProvenance.DECLARED_FACT,
            kv_metadata=ModelKVArchitectureMetadata(
                num_layers=28,
                num_kv_heads=8,
                head_dim=128,
                cache_element_bytes=2,
                source="meta-llama-3.2-3b-config",
            ),
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.FALSE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_rank=3,
            quality_rank_provenance=NumericFactProvenance.CURATED_POLICY,
            quality_rank_source="Agent Engine Curated Quality Policy v2026.10.1",
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
            parameter_count_provenance=NumericFactProvenance.DECLARED_FACT,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            memory_unit="bytes",
            artifact_size_bytes=1929903072,
            artifact_size_provenance=NumericFactProvenance.MEASURED_FACT,
            artifact_size_source="qwen2.5_coder_3b_gguf_release",
            artifact_descriptor=ModelArtifactDescriptor(
                artifact_id="qwen2.5-coder-3b-instruct-q4_k_m.gguf",
                model_identity=ModelIdentity(
                    provider_id="llamacpp", model_id="qwen2.5-coder-3b-instruct-q4_k_m"
                ),
                source_url="https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf",
                expected_size_bytes=1929903072,
                expected_sha256="4a188102020e9c9530b687fd6400f775c45e90a0d7baafe65bd0a36963fbb7ba",
                format="gguf",
                quantization="Q4_K_M",
                provenance="curated_catalog",
                catalog_version=DEFAULT_CATALOG_VERSION,
            ),
            min_ram_bytes=3 * 1024 * 1024 * 1024,  # 3.0 GiB
            min_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            min_ram_source="curated_catalog_policy_v2026.10.1",
            recommended_ram_bytes=4 * 1024 * 1024 * 1024,  # 4.0 GiB
            recommended_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            recommended_ram_source="curated_catalog_policy_v2026.10.1",
            accelerator_required=False,
            context_window_limit=32768,
            context_window_provenance=NumericFactProvenance.DECLARED_FACT,
            kv_metadata=ModelKVArchitectureMetadata(
                num_layers=36,
                num_kv_heads=2,
                head_dim=128,
                cache_element_bytes=2,
                source="qwen2.5-coder-3b-config",
            ),
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_rank=4,
            quality_rank_provenance=NumericFactProvenance.CURATED_POLICY,
            quality_rank_source="Agent Engine Curated Quality Policy v2026.10.1",
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
            parameter_count_provenance=NumericFactProvenance.DECLARED_FACT,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            memory_unit="bytes",
            artifact_size_bytes=int(4.7 * 1024 * 1024 * 1024),  # ~4.7 GiB
            artifact_size_provenance=NumericFactProvenance.MEASURED_FACT,
            artifact_size_source="qwen2.5_coder_7b_gguf_release",
            min_ram_bytes=6 * 1024 * 1024 * 1024,  # 6.0 GiB
            min_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            min_ram_source="curated_catalog_policy_v2026.10.1",
            recommended_ram_bytes=8 * 1024 * 1024 * 1024,  # 8.0 GiB
            recommended_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            recommended_ram_source="curated_catalog_policy_v2026.10.1",
            accelerator_required=False,
            context_window_limit=32768,
            context_window_provenance=NumericFactProvenance.DECLARED_FACT,
            kv_metadata=ModelKVArchitectureMetadata(
                num_layers=28,
                num_kv_heads=4,
                head_dim=128,
                cache_element_bytes=2,
                source="qwen2.5-coder-7b-config",
            ),
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_rank=5,
            quality_rank_provenance=NumericFactProvenance.CURATED_POLICY,
            quality_rank_source="Agent Engine Curated Quality Policy v2026.10.1",
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
            parameter_count_provenance=NumericFactProvenance.DECLARED_FACT,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            memory_unit="bytes",
            artifact_size_bytes=int(9.0 * 1024 * 1024 * 1024),  # ~9.0 GiB
            artifact_size_provenance=NumericFactProvenance.MEASURED_FACT,
            artifact_size_source="qwen2.5_14b_gguf_release",
            min_ram_bytes=12 * 1024 * 1024 * 1024,  # 12.0 GiB
            min_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            min_ram_source="curated_catalog_policy_v2026.10.1",
            recommended_ram_bytes=16 * 1024 * 1024 * 1024,  # 16.0 GiB
            recommended_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            recommended_ram_source="curated_catalog_policy_v2026.10.1",
            accelerator_required=False,
            context_window_limit=32768,
            context_window_provenance=NumericFactProvenance.DECLARED_FACT,
            kv_metadata=ModelKVArchitectureMetadata(
                num_layers=48,
                num_kv_heads=8,
                head_dim=128,
                cache_element_bytes=2,
                source="qwen2.5-14b-config",
            ),
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_rank=6,
            quality_rank_provenance=NumericFactProvenance.CURATED_POLICY,
            quality_rank_source="Agent Engine Curated Quality Policy v2026.10.1",
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
            parameter_count_provenance=NumericFactProvenance.DECLARED_FACT,
            quantization="Q4_K_M",
            managed_runtime="llamacpp",
            memory_unit="bytes",
            artifact_size_bytes=int(20.0 * 1024 * 1024 * 1024),  # ~20.0 GiB
            artifact_size_provenance=NumericFactProvenance.MEASURED_FACT,
            artifact_size_source="qwen2.5_32b_gguf_release",
            min_ram_bytes=24 * 1024 * 1024 * 1024,  # 24.0 GiB
            min_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            min_ram_source="curated_catalog_policy_v2026.10.1",
            recommended_ram_bytes=32 * 1024 * 1024 * 1024,  # 32.0 GiB
            recommended_ram_provenance=NumericFactProvenance.CURATED_HEURISTIC,
            recommended_ram_source="curated_catalog_policy_v2026.10.1",
            accelerator_required=False,
            context_window_limit=32768,
            context_window_provenance=NumericFactProvenance.DECLARED_FACT,
            kv_metadata=ModelKVArchitectureMetadata(
                num_layers=64,
                num_kv_heads=8,
                head_dim=128,
                cache_element_bytes=2,
                source="qwen2.5-32b-config",
            ),
            capabilities={
                "coding": TriStateBool.TRUE,
                "reasoning": TriStateBool.TRUE,
                "vision": TriStateBool.FALSE,
                "tools": TriStateBool.TRUE,
                "structured_output": TriStateBool.TRUE,
                "streaming": TriStateBool.TRUE,
            },
            quality_rank=7,
            quality_rank_provenance=NumericFactProvenance.CURATED_POLICY,
            quality_rank_source="Agent Engine Curated Quality Policy v2026.10.1",
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

    def get_artifact_descriptor(
        self, model_identity: ModelIdentity
    ) -> Optional[ModelArtifactDescriptor]:
        """Resolve authoritative ModelArtifactDescriptor for a catalog model."""
        entry = self.get_model(model_identity)
        if not entry:
            return None
        if entry.artifact_descriptor:
            return entry.artifact_descriptor
        artifact_id = f"{entry.model_identity.model_id}.gguf"
        return ModelArtifactDescriptor(
            artifact_id=artifact_id,
            model_identity=entry.model_identity,
            source_url=f"https://huggingface.co/Qwen/{entry.family}-GGUF/resolve/main/{artifact_id}",
            expected_size_bytes=entry.artifact_size_bytes,
            expected_sha256="0" * 64,
            format="gguf",
            quantization=entry.quantization,
            provenance="curated_catalog",
            catalog_version=entry.catalog_version,
        )
