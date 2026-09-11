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
) -> dspy.LM:
    """
    Dynamic model factory with explicit OS environment variable injection,
    extended local timeout margins, and a fail-safe fallback routing loop.
    """
    provider_name = provider_name.lower()
    local_model = os.getenv("LOCAL_MODEL_NAME", "qwen2.5-coder-3b-instruct-q4_k_m")
    llamacpp_url = os.getenv("LLAMACPP_HOST", "http://localhost:8080/v1")

    if max_tokens is None:
        max_tokens = int(os.getenv("DEFAULT_MAX_TOKENS", "4096"))

    # Securely resolve credentials from CredentialManager or environment
    try:
        from core.security import get_credential_manager

        cred_mgr = get_credential_manager()
    except Exception:
        cred_mgr = None

    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "KIMI_API_KEY",
        "GROQ_API_KEY",
    ):
        value = cred_mgr.get_api_key(key) if cred_mgr else os.getenv(key)
        if value:
            os.environ[key] = value

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
            return dspy.LM(
                target_model,
                api_key=os.getenv("GEMINI_API_KEY"),
                max_tokens=min(max_tokens, 2000),
                cache=cache,
            )

        if provider_name == "openai":
            logger.info("Engaging OpenAI cloud channel client.")
            return dspy.LM(
                model_name or "openai/gpt-4o-mini",
                api_key=os.getenv("OPENAI_API_KEY"),
                max_tokens=min(max_tokens, 2000),
                cache=cache,
            )

        if provider_name == "deepseek":
            logger.info("Engaging DeepSeek cloud channel client.")
            return dspy.LM(
                model=model_name or "deepseek/deepseek-chat",
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                api_base="https://deepseek.com",
                max_tokens=min(max_tokens, 4000),
                cache=cache,
            )

        if provider_name == "kimi":
            logger.info("Engaging Kimi cloud channel client.")
            return dspy.LM(
                model=model_name or "moonshot-v1-8k",
                api_key=os.getenv("KIMI_API_KEY"),
                api_base="https://moonshot.cn",
                max_tokens=min(max_tokens, 8000),
                cache=cache,
            )

        if provider_name == "groq":
            logger.info("Engaging Groq cloud channel client.")
            return dspy.LM(
                model=model_name or "groq/llama-3.3-70b-specdec",
                api_key=os.getenv("GROQ_API_KEY"),
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
