# core/models.py
import logging
import os

import dspy
from dotenv import load_dotenv

load_dotenv()

# Configure logging parameters
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("agent_engine.models")


def get_model_provider(
    provider_name: str,
    model_name: str | None = None,
    cache: bool = True,
    max_tokens: int | None = None,
    api_key: str | None = None,
) -> dspy.LM:
    """
    Dynamic model factory delegating to the canonical ProviderRegistry (Milestone R3 Task R3.1).
    Passes credentials directly without mutating global os.environ.
    Preserves fail-safe fallback routing loop.
    """
    from core.providers import get_provider_registry

    registry = get_provider_registry()
    p_clean = provider_name.lower().strip()
    canon_id = registry.resolve_provider_id(p_clean)

    local_model = os.getenv("LOCAL_MODEL_NAME", "qwen2.5-coder-3b-instruct-q4_k_m")
    llamacpp_url = os.getenv("LLAMACPP_HOST", "http://localhost:8080/v1")

    try:
        adapter = registry.get_adapter(canon_id)
        return adapter.create_dspy_lm(
            model=model_name,
            max_tokens=max_tokens,
            cache=cache,
            api_key=api_key,
        )
    except Exception as runtime_init_error:
        logger.error(f"Primary initialization failed: {runtime_init_error}")
        logger.info("Falling back to local isolated llama.cpp infrastructure nodes safely.")
        return dspy.LM(
            f"openai/{local_model}",
            api_base=llamacpp_url,
            api_key="local-token-placeholder",
            max_tokens=1024,
            cache=cache,
            timeout=120.0,
        )
