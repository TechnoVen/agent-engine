import os
import numpy  # Pre-import numpy to prevent dspy lazy import conflicts
import chromadb
from chromadb.config import Settings
import dspy
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

_CHROMA_CLIENTS: Dict[str, Any] = {}

class AgentMemory:
    """
    Persistent Vector Store interface using ChromaDB for Agent Context and RAG.
    """
    def __init__(self, persist_directory: Optional[str] = None, collection_name: str = "agent_knowledge"):
        self.persist_directory = persist_directory or os.getenv("CHROMA_PERSIST_DIR", "/home/nadir/agent_engine/data/chroma")
        os.makedirs(self.persist_directory, exist_ok=True)
        
        # Reuse existing persistent client instance to prevent destructor conflicts
        if self.persist_directory not in _CHROMA_CLIENTS:
            _CHROMA_CLIENTS[self.persist_directory] = chromadb.PersistentClient(path=self.persist_directory)
        
        self.client = _CHROMA_CLIENTS[self.persist_directory]
        self.collection_name = collection_name
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Agent Engine Long-Term & RAG Memory"}
        )

    def add_documents(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """
        Store documents into vector memory with embeddings.
        """
        if not documents:
            return []

        if ids is None:
            import uuid
            ids = [str(uuid.uuid4()) for _ in documents]

        if metadatas is None:
            import datetime
            now_iso = datetime.datetime.now().isoformat()
            metadatas = [{"timestamp": now_iso, "source": "agent_ingestion"} for _ in documents]

        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        return ids

    def query(self, query_text: str, n_results: int = 3) -> Dict[str, Any]:
        """
        Query vector memory for top semantic matches.
        """
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        return results

    def retrieve_passages(self, query_text: str, n_results: int = 3) -> List[str]:
        """
        Convenience method returning list of matching document text passages.
        """
        results = self.query(query_text, n_results=n_results)
        docs = results.get("documents", [[]])
        return docs[0] if docs else []

    def count(self) -> int:
        """Count total stored vectors in this collection."""
        return self.collection.count()

    def clear(self):
        """Reset the active collection."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(name=self.collection_name)


class RAGModule(dspy.Module):
    """
    DSPy RAG Module that queries AgentMemory for relevant context before answering.
    """
    def __init__(self, memory: Optional[AgentMemory] = None, k: int = 3):
        super().__init__()
        self.memory = memory or AgentMemory()
        self.k = k

        # Dynamic signature for contextual question answering
        class ContextQASig(dspy.Signature):
            """Answer the question using the retrieved background context accurately."""
            context: str = dspy.InputField(desc="Relevant retrieved passages and background memory")
            question: str = dspy.InputField(desc="The user query or task")
            answer: str = dspy.OutputField(desc="Detailed, accurate answer grounded in the context")

        self.qa_agent = dspy.ChainOfThought(ContextQASig)

    def forward(self, question: str) -> dspy.Prediction:
        passages = self.memory.retrieve_passages(question, n_results=self.k)
        context_str = "\n---\n".join(passages) if passages else "No prior memory found."
        
        prediction = self.qa_agent(context=context_str, question=question)
        prediction.retrieved_passages = passages
        return prediction
