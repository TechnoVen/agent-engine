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
    Dynamic model factory with direct secret parameter injection,
    extended local timeout margins, and a fail-safe fallback routing loop.
    Does not mutate global os.environ.
    """
    provider_name = provider_name.lower()
    local_model = os.getenv("LOCAL_MODEL_NAME", "qwen2.5-coder-3b-instruct-q4_k_m")
    llamacpp_url = os.getenv("LLAMACPP_HOST", "http://localhost:8080/v1")

    if max_tokens is None:
        max_tokens = int(os.getenv("DEFAULT_MAX_TOKENS", "4096"))

    # Securely resolve credentials from SecretsService or environment
    try:
        from core.security import get_secrets_service

        secrets_svc = get_secrets_service()
    except Exception:
        secrets_svc = None

    def _resolve_key(key_name: str) -> str | None:
        if api_key:
            return api_key
        if secrets_svc:
            val = secrets_svc.get_api_key(key_name)
            if val:
                return val
        return os.getenv(key_name)

    try:
        if provider_name in ("local", "llamacpp", "gemma4"):
            logger.info(f"Initializing local llama.cpp compatible server: {local_model}")
            # Target unified client structures with safe token caps and broad timeout cushions
            return dspy.LM(
                f"openai/{local_model}",
                api_base=llamacpp_url,
                api_key="local-token-placeholder",
                max_tokens=min(max_tokens, 1024),
                cache=cache,
                timeout=120.0,  # 🪂 Extended 2-minute safety net to absorb heavy generations
            )

        if provider_name == "ollama":
            ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
            logger.info(f"Initializing local Ollama server: {ollama_model}")
            return dspy.LM(
                f"ollama_chat/{ollama_model}",
                api_base=ollama_url,
                max_tokens=min(max_tokens, 1024),
                cache=cache,
                timeout=120.0,
            )

        if provider_name in ("gemini", "google"):
            target_model = model_name or "gemini/gemini-2.5-flash"
            logger.info(f"Engaging Gemini cloud channel client: {target_model}")
            resolved_key = _resolve_key("GEMINI_API_KEY") or _resolve_key("GOOGLE_API_KEY")
            return dspy.LM(
                target_model,
                api_key=resolved_key,
                max_tokens=min(max_tokens, 2000),
                cache=cache,
            )

        if provider_name == "openai":
            logger.info("Engaging OpenAI cloud channel client.")
            return dspy.LM(
                model_name or "openai/gpt-4o-mini",
                api_key=_resolve_key("OPENAI_API_KEY"),
                max_tokens=min(max_tokens, 2000),
                cache=cache,
            )

        if provider_name == "anthropic":
            logger.info("Engaging Anthropic cloud channel client.")
            return dspy.LM(
                model=model_name or "anthropic/claude-3-5-sonnet-20241022",
                api_key=_resolve_key("ANTHROPIC_API_KEY"),
                max_tokens=min(max_tokens, 4000),
                cache=cache,
            )

        if provider_name == "deepseek":
            logger.info("Engaging DeepSeek cloud channel client.")
            return dspy.LM(
                model=model_name or "deepseek/deepseek-chat",
                api_key=_resolve_key("DEEPSEEK_API_KEY"),
                api_base="https://deepseek.com",
                max_tokens=min(max_tokens, 4000),
                cache=cache,
            )

        if provider_name == "kimi":
            logger.info("Engaging Kimi cloud channel client.")
            return dspy.LM(
                model=model_name or "moonshot-v1-8k",
                api_key=_resolve_key("KIMI_API_KEY"),
                api_base="https://moonshot.cn",
                max_tokens=min(max_tokens, 8000),
                cache=cache,
            )

        if provider_name == "groq":
            logger.info("Engaging Groq cloud channel client.")
            return dspy.LM(
                model=model_name or "groq/llama-3.3-70b-specdec",
                api_key=_resolve_key("GROQ_API_KEY"),
                max_tokens=min(max_tokens, 8000),
                cache=cache,
            )

        raise ValueError(f"Unknown framework model provider target: {provider_name}")

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
