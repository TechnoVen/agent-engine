"""core/model_registry/catalog.py

Default Built-in Model Capability Catalog for Agent Engine.
Part of Milestone R3 Task R3.2 (Model Capability Registry).

Provides calibrated reference metadata for common cloud and local models across:
- Reasoning, coding, vision, tools, structured output, embeddings, streaming.
- Exact input, output, and total context token limits.
- Up-to-date pricing metadata ($/M tokens).
- Latency classifications (fast, medium, slow, reasoning).
- Privacy and hardware constraints (RAM, VRAM, quantization).
"""

from __future__ import annotations

from typing import List

from core.model_registry.models import (
    HardwareRequirements,
    LatencyClass,
    LatencyProfile,
    ModelCapabilities,
    ModelDefinition,
    PricingProfile,
    PrivacyProfile,
    ProvenanceType,
    TriStateBool,
)


def get_builtin_catalog() -> List[ModelDefinition]:
    """Return canonical reference model definitions for Agent Engine."""
    return [
        # ==============================================================================
        # 1. OpenAI Models
        # ==============================================================================
        ModelDefinition(
            provider_id="openai",
            model_id="gpt-4o",
            display_name="GPT-4o",
            description="OpenAI flagship multimodal intelligence model",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.TRUE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.TRUE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=128000,
            max_output_tokens=16384,
            max_total_context_tokens=128000,
            pricing=PricingProfile(
                input_cost_per_million=2.50,
                output_cost_per_million=10.00,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=1200.0,
                latency_class=LatencyClass.MEDIUM,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
                zero_data_retention=False,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["flagship", "vision", "tools", "coding"],
        ),
        ModelDefinition(
            provider_id="openai",
            model_id="gpt-4o-mini",
            display_name="GPT-4o Mini",
            description="High-speed cost-efficient OpenAI multimodal model",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.TRUE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=128000,
            max_output_tokens=16384,
            max_total_context_tokens=128000,
            pricing=PricingProfile(
                input_cost_per_million=0.15,
                output_cost_per_million=0.60,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=650.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["fast", "cheap", "vision", "tools"],
        ),
        ModelDefinition(
            provider_id="openai",
            model_id="text-embedding-3-small",
            display_name="Text Embedding 3 Small",
            description="Dense text representation embeddings model",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.FALSE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.FALSE,
                structured_output=TriStateBool.FALSE,
                embeddings=TriStateBool.TRUE,
                streaming=TriStateBool.FALSE,
            ),
            max_input_tokens=8191,
            max_output_tokens=0,
            max_total_context_tokens=8191,
            pricing=PricingProfile(
                input_cost_per_million=0.02,
                output_cost_per_million=0.00,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=250.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["embeddings"],
        ),
        # ==============================================================================
        # 2. Anthropic Models
        # ==============================================================================
        ModelDefinition(
            provider_id="anthropic",
            model_id="claude-3-5-sonnet-20241022",
            display_name="Claude 3.5 Sonnet",
            description="State-of-the-art coding and complex reasoning intelligence",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.TRUE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.TRUE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=200000,
            max_output_tokens=8192,
            max_total_context_tokens=200000,
            pricing=PricingProfile(
                input_cost_per_million=3.00,
                output_cost_per_million=15.00,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=1400.0,
                latency_class=LatencyClass.MEDIUM,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["flagship", "coding", "reasoning", "vision", "tools"],
        ),
        ModelDefinition(
            provider_id="anthropic",
            model_id="claude-3-5-haiku-20241022",
            display_name="Claude 3.5 Haiku",
            description="Ultra-fast light intelligence model",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=200000,
            max_output_tokens=8192,
            max_total_context_tokens=200000,
            pricing=PricingProfile(
                input_cost_per_million=0.80,
                output_cost_per_million=4.00,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=550.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["fast", "coding", "tools"],
        ),
        # ==============================================================================
        # 3. Google Gemini Models
        # ==============================================================================
        ModelDefinition(
            provider_id="gemini",
            model_id="gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
            description="Next-generation multimodal model with 1M context window",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.TRUE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.TRUE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=1048576,
            max_output_tokens=8192,
            max_total_context_tokens=1048576,
            pricing=PricingProfile(
                input_cost_per_million=0.075,
                output_cost_per_million=0.30,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=700.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["large_context", "fast", "cheap", "vision", "tools"],
        ),
        ModelDefinition(
            provider_id="gemini",
            model_id="gemini-2.5-pro",
            display_name="Gemini 2.5 Pro",
            description="Deep reasoning multimodal frontier model with 2M context",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.TRUE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.TRUE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=2097152,
            max_output_tokens=8192,
            max_total_context_tokens=2097152,
            pricing=PricingProfile(
                input_cost_per_million=1.25,
                output_cost_per_million=5.00,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=2100.0,
                latency_class=LatencyClass.MEDIUM,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["large_context", "deep_reasoning", "vision", "tools"],
        ),
        # ==============================================================================
        # 4. DeepSeek Models
        # ==============================================================================
        ModelDefinition(
            provider_id="deepseek",
            model_id="deepseek-chat",
            display_name="DeepSeek V3",
            description="High efficiency general chat and code model",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=64000,
            max_output_tokens=8000,
            max_total_context_tokens=64000,
            pricing=PricingProfile(
                input_cost_per_million=0.14,
                output_cost_per_million=0.28,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=900.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["coding", "tools", "cheap"],
        ),
        ModelDefinition(
            provider_id="deepseek",
            model_id="deepseek-reasoner",
            display_name="DeepSeek R1",
            description="Deep mathematical and scientific reasoning model",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.TRUE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.FALSE,
                structured_output=TriStateBool.FALSE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=64000,
            max_output_tokens=8000,
            max_total_context_tokens=64000,
            pricing=PricingProfile(
                input_cost_per_million=0.55,
                output_cost_per_million=2.19,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=12000.0,
                latency_class=LatencyClass.REASONING,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["deep_reasoning", "math"],
        ),
        # ==============================================================================
        # 5. Groq Models
        # ==============================================================================
        ModelDefinition(
            provider_id="groq",
            model_id="llama-3.3-70b-specdec",
            display_name="Llama 3.3 70B (Groq LPU)",
            description="Ultra-fast LPU inference on Meta Llama 3.3 70B",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=128000,
            max_output_tokens=8192,
            max_total_context_tokens=128000,
            pricing=PricingProfile(
                input_cost_per_million=0.59,
                output_cost_per_million=0.79,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=180.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["ultra_fast", "tools", "coding"],
        ),
        # ==============================================================================
        # 6. Moonshot Kimi
        # ==============================================================================
        ModelDefinition(
            provider_id="kimi",
            model_id="moonshot-v1-8k",
            display_name="Moonshot Kimi v1 8K",
            description="Chinese-English high accuracy conversational assistant",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=8192,
            max_output_tokens=4096,
            max_total_context_tokens=8192,
            pricing=PricingProfile(
                input_cost_per_million=0.80,
                output_cost_per_million=1.50,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=1100.0,
                latency_class=LatencyClass.MEDIUM,
            ),
            privacy=PrivacyProfile(
                is_local=False,
                data_leaves_device=True,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["multilingual", "tools"],
        ),
        # ==============================================================================
        # 7. llama.cpp Local Models
        # ==============================================================================
        ModelDefinition(
            provider_id="llamacpp",
            model_id="qwen2.5-coder-3b-instruct-q4_k_m",
            display_name="Qwen 2.5 Coder 3B Instruct (Q4_K_M)",
            description="Compact local code generation model running via llama.cpp",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.FALSE,
                structured_output=TriStateBool.FALSE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=32768,
            max_output_tokens=4096,
            max_total_context_tokens=32768,
            pricing=PricingProfile(
                input_cost_per_million=0.0,
                output_cost_per_million=0.0,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=800.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=True,
                data_leaves_device=False,
                zero_data_retention=True,
            ),
            hardware=HardwareRequirements(
                min_ram_bytes=3 * 1024 * 1024 * 1024,  # 3 GB RAM
                recommended_ram_bytes=4 * 1024 * 1024 * 1024,  # 4 GB RAM
                quantization="Q4_K_M",
                parameter_size="3B",
                architecture="qwen2",
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["local", "coding", "low_resource", "private"],
        ),
        ModelDefinition(
            provider_id="llamacpp",
            model_id="llama-3.2-1b-instruct-q4_k_m",
            display_name="Llama 3.2 1B Instruct (Q4_K_M)",
            description="Ultra-lightweight local conversational model",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.FALSE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.FALSE,
                structured_output=TriStateBool.FALSE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=8192,
            max_output_tokens=2048,
            max_total_context_tokens=8192,
            pricing=PricingProfile(
                input_cost_per_million=0.0,
                output_cost_per_million=0.0,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=450.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=True,
                data_leaves_device=False,
                zero_data_retention=True,
            ),
            hardware=HardwareRequirements(
                min_ram_bytes=int(1.5 * 1024 * 1024 * 1024),  # 1.5 GB RAM
                recommended_ram_bytes=2 * 1024 * 1024 * 1024,  # 2 GB RAM
                quantization="Q4_K_M",
                parameter_size="1B",
                architecture="llama",
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["local", "lightweight", "private"],
        ),
        # ==============================================================================
        # 8. Ollama Local Models
        # ==============================================================================
        ModelDefinition(
            provider_id="ollama",
            model_id="qwen2.5-coder:3b",
            display_name="Qwen 2.5 Coder 3B (Ollama)",
            description="Local coding specialist served via Ollama daemon",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.TRUE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=32768,
            max_output_tokens=4096,
            max_total_context_tokens=32768,
            pricing=PricingProfile(
                input_cost_per_million=0.0,
                output_cost_per_million=0.0,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=850.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=True,
                data_leaves_device=False,
                zero_data_retention=True,
            ),
            hardware=HardwareRequirements(
                min_ram_bytes=int(3.5 * 1024 * 1024 * 1024),
                recommended_ram_bytes=4 * 1024 * 1024 * 1024,
                parameter_size="3B",
                architecture="qwen2",
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["local", "ollama", "coding", "tools", "private"],
        ),
        ModelDefinition(
            provider_id="ollama",
            model_id="llama3.2:1b",
            display_name="Llama 3.2 1B (Ollama)",
            description="Local edge model served via Ollama daemon",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.FALSE,
                coding=TriStateBool.FALSE,
                vision=TriStateBool.FALSE,
                tools=TriStateBool.TRUE,
                structured_output=TriStateBool.TRUE,
                embeddings=TriStateBool.FALSE,
                streaming=TriStateBool.TRUE,
            ),
            max_input_tokens=8192,
            max_output_tokens=2048,
            max_total_context_tokens=8192,
            pricing=PricingProfile(
                input_cost_per_million=0.0,
                output_cost_per_million=0.0,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=500.0,
                latency_class=LatencyClass.FAST,
            ),
            privacy=PrivacyProfile(
                is_local=True,
                data_leaves_device=False,
                zero_data_retention=True,
            ),
            hardware=HardwareRequirements(
                min_ram_bytes=2 * 1024 * 1024 * 1024,
                parameter_size="1B",
                architecture="llama",
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["local", "ollama", "lightweight", "private"],
        ),
        # ==============================================================================
        # 9. Generic Compatible (Gateway with UNKNOWN capabilities to test 3-valued logic)
        # ==============================================================================
        ModelDefinition(
            provider_id="compatible",
            model_id="default",
            display_name="Generic Inference Endpoint",
            description="Upstream OpenAI-compatible gateway with unverified capabilities",
            capabilities=ModelCapabilities(
                reasoning=TriStateBool.UNKNOWN,
                coding=TriStateBool.UNKNOWN,
                vision=TriStateBool.UNKNOWN,
                tools=TriStateBool.UNKNOWN,
                structured_output=TriStateBool.UNKNOWN,
                embeddings=TriStateBool.UNKNOWN,
                streaming=TriStateBool.UNKNOWN,
            ),
            max_input_tokens=None,
            max_output_tokens=None,
            max_total_context_tokens=4096,
            pricing=PricingProfile(
                input_cost_per_million=None,
                output_cost_per_million=None,
            ),
            latency=LatencyProfile(
                catalog_latency_ms=None,
                latency_class=LatencyClass.UNKNOWN,
            ),
            privacy=PrivacyProfile(
                is_local=None,
                data_leaves_device=TriStateBool.UNKNOWN,
                zero_data_retention=TriStateBool.UNKNOWN,
            ),
            provenance=ProvenanceType.BUILTIN,
            tags=["custom", "gateway"],
        ),
    ]
