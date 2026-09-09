# core/models.py
import logging
import os
from typing import Optional  # still needed for some older code? Actually we can drop Optional entirely.

# We'll use Python 3.10+ style: `str | None` instead of `Optional[str]`
# No need to import Optional at all.

import dspy
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("agent_engine.models")


def get_model_provider(
    provider_name: str,
    model_name: str | None = None,          # ✅ Python 3.10+ union syntax
    cache: bool = True,
    max_tokens: int | None = None,          # ✅ union syntax
) -> dspy.LM:
    """
    Dynamic model factory with explicit OS environment variable injection,
    configurable timeouts, and a fail‑safe fallback routing loop.
    """
    provider_name = provider_name.lower()
    local_model = os.getenv("LOCAL_MODEL_NAME", "qwen2.5-coder-3b-instruct-q4_k_m")
    llamacpp_url = os.getenv("LLAMACPP_HOST", "http://localhost:8080/v1")

    if max_tokens is None:
        max_tokens = int(os.getenv("DEFAULT_MAX_TOKENS", "4096"))

    # Inject API keys into environment for LiteLLM
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "KIMI_API_KEY", "GROQ_API_KEY"):
        value = os.getenv(key)
        if value:
            os.environ[key] = value

    try:
        if provider_name in ("local", "llamacpp", "gemma4"):
            logger.info(f"Initializing local llama.cpp server with model: {local_model}")
            return dspy.LM(
                f"openai/{local_model}",
                api_base=llamacpp_url,
                api_key="local-token-placeholder",
                max_tokens=min(max_tokens, 1024),
                cache=cache,
            )

        if provider_name in ("gemini", "google"):
            target_model = model_name or "gemini/gemini-2.5-flash"
            logger.info(f"Engaging Gemini client: {target_model}")
            return dspy.LM(
                target_model,
                api_key=os.getenv("GEMINI_API_KEY"),
                max_tokens=min(max_tokens, 2000),
                cache=cache,
            )

        if provider_name == "openai":
            return dspy.LM(
                model_name or "openai/gpt-4o-mini",
                api_key=os.getenv("OPENAI_API_KEY"),
                max_tokens=min(max_tokens, 2000),
                cache=cache,
            )

        if provider_name == "deepseek":
            return dspy.LM(
                model=model_name or "deepseek/deepseek-chat",
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                api_base="https://api.deepseek.com/v1",
                max_tokens=min(max_tokens, 4000),
                cache=cache,
            )

        if provider_name == "kimi":
            return dspy.LM(
                model=model_name or "moonshot-v1-8k",
                api_key=os.getenv("KIMI_API_KEY"),
                api_base="https://api.moonshot.cn/v1",
                max_tokens=min(max_tokens, 8000),
                cache=cache,
            )

        if provider_name == "groq":
            return dspy.LM(
                model=model_name or "groq/llama-3.3-70b-specdec",
                api_key=os.getenv("GROQ_API_KEY"),
                max_tokens=min(max_tokens, 8000),
                cache=cache,
            )

        raise ValueError(f"Unknown framework model provider target: {provider_name}")

    except Exception as runtime_init_error:  # noqa: BLE001
        logger.error(f"Primary initialization failed: {runtime_init_error}")
        logger.info("Falling back to local llama.cpp server.")
        return dspy.LM(
            f"openai/{local_model}",
            api_base=llamacpp_url,
            api_key="local-token-placeholder",
            max_tokens=1024,
            cache=cache,
        )
