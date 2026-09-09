import pytest
import dspy
from core.engine import (
    NodeConfig,
    DynamicSignatureBuilder,
    LowCodeAgent,
    AgentPipeline,
    _GLOBAL_TOOL_REGISTRY
)
from core.memory import AgentMemory, RAGModule
from core.router import ModelRouter

def test_dynamic_signature_generation():
    """Verify that DynamicSignatureBuilder generates valid DSPy Signature classes."""
    config = NodeConfig(
        name="SecurityAuditor",
        description="Audit source code for OWASP vulnerabilities.",
        inputs={"code_snippet": "Source code text to review"},
        outputs={
            "vulnerabilities": "List of discovered security issues",
            "risk_level": "Calculated risk severity (Low, Med, High, Critical)"
        },
        reasoning_type="cot"
    )

    sig_class = DynamicSignatureBuilder.build(config)
    assert issubclass(sig_class, dspy.Signature)
    assert "code_snippet" in sig_class.fields
    assert "vulnerabilities" in sig_class.fields
    assert "risk_level" in sig_class.fields
    assert sig_class.__doc__ == "Audit source code for OWASP vulnerabilities."

def test_lowcode_agent_initialization():
    """Verify LowCodeAgent initializes ChainOfThought and ReAct correctly."""
    # 1. Chain of Thought agent
    cot_config = NodeConfig(
        name="Explainer",
        inputs=["topic"],
        outputs=["summary"],
        reasoning_type="cot"
    )
    cot_agent = LowCodeAgent(cot_config)
    assert isinstance(cot_agent.processor, dspy.ChainOfThought)

    # 2. Predict agent
    pred_config = NodeConfig(
        name="Translator",
        inputs=["english"],
        outputs=["french"],
        reasoning_type="predict"
    )
    pred_agent = LowCodeAgent(pred_config)
    assert isinstance(pred_agent.processor, dspy.Predict)

def test_agent_memory_persistence(tmp_path):
    """Verify AgentMemory can store, query, and count vector embeddings in ChromaDB."""
    mem_dir = str(tmp_path / "chroma_test")
    memory = AgentMemory(persist_directory=mem_dir, collection_name="test_collection")

    assert memory.count() == 0

    docs = [
        "FastAPI is a modern web framework for Python.",
        "DSPy optimizes prompts for language models programmatically.",
        "ChromaDB is an open-source AI application database."
    ]
    ids = memory.add_documents(docs)
    assert len(ids) == 3
    assert memory.count() == 3

    # Semantic search retrieval
    retrieved = memory.retrieve_passages("How to optimize prompts with DSPy?", n_results=1)
    assert len(retrieved) == 1
    assert "DSPy optimizes prompts" in retrieved[0]

def test_router_status_and_instantiation():
    """Verify ModelRouter status inspects providers and creates configured LM objects."""
    router = ModelRouter()
    status = router.get_status()
    assert "primary_provider" in status
    assert "fallback_provider" in status
    assert isinstance(status["ollama_live"], bool)
    assert isinstance(status["llamacpp_live"], bool)

    # Test creating mock/offline provider
    lm, label = router.create_lm("openai", api_key="dummy_key", model="openai/gpt-4o-mini")
    assert lm is not None
    assert "OpenAI" in label
