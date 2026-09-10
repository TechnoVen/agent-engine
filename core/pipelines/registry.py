from dataclasses import asdict, dataclass, field
import logging
import threading
from typing import Any, Callable, Type

import dspy

logger = logging.getLogger("agent_engine.pipelines.registry")


@dataclass
class PipelineMetadata:
    name: str
    description: str
    inputs: list[str]
    outputs: list[str]
    tools: list[str] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    category: str = "general"
    version: str = "1.0.0"
    author: str = "Agent Engine"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PipelineRegistry:
    """Thread-safe registry for modular DSPy agent pipelines."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registry: dict[str, tuple[Type[dspy.Module], PipelineMetadata]] = {}

    def register(
        self,
        cls: Type[dspy.Module],
        metadata: PipelineMetadata | dict[str, Any],
    ) -> Type[dspy.Module]:
        """Register a pipeline class with metadata."""
        meta = metadata if isinstance(metadata, PipelineMetadata) else PipelineMetadata(**metadata)
        with self._lock:
            self._registry[meta.name] = (cls, meta)
            logger.info("Registered pipeline '%s' (category: %s)", meta.name, meta.category)
        return cls

    def get(self, name: str) -> Type[dspy.Module] | None:
        """Retrieve a pipeline class by name."""
        with self._lock:
            entry = self._registry.get(name)
            return entry[0] if entry else None

    def get_metadata(self, name: str) -> PipelineMetadata | None:
        """Retrieve metadata for a registered pipeline."""
        with self._lock:
            entry = self._registry.get(name)
            return entry[1] if entry else None

    def list_pipelines(self) -> list[PipelineMetadata]:
        """List metadata for all registered pipelines."""
        with self._lock:
            return [entry[1] for entry in self._registry.values()]

    def instantiate(self, name: str, **kwargs: Any) -> dspy.Module:
        """Instantiate a registered pipeline by name."""
        cls = self.get(name)
        if cls is None:
            raise KeyError(f"Pipeline '{name}' not found in registry")
        return cls(**kwargs)

    def run(self, name: str, **inputs: Any) -> dict[str, Any]:
        """Instantiate and execute a registered pipeline with given inputs."""
        meta = self.get_metadata(name)
        if meta is None:
            raise KeyError(f"Pipeline '{name}' not found in registry")

        instance = self.instantiate(name)
        pred = instance(**inputs)
        if hasattr(pred, "toDict"):
            result = pred.toDict()
        elif isinstance(pred, dict):
            result = pred
        else:
            result = dict(pred)
        return result

    def unregister(self, name: str) -> bool:
        """Remove a pipeline from the registry."""
        with self._lock:
            if name in self._registry:
                del self._registry[name]
                return True
            return False

    def clear(self) -> None:
        """Clear all registered pipelines (used for testing)."""
        with self._lock:
            self._registry.clear()


_GLOBAL_PIPELINE_REGISTRY = PipelineRegistry()


def get_pipeline_registry() -> PipelineRegistry:
    """Return the global PipelineRegistry instance."""
    return _GLOBAL_PIPELINE_REGISTRY


def register_pipeline(
    name: str,
    description: str = "",
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    tools: list[str] | None = None,
    guardrails: list[str] | None = None,
    category: str = "general",
    version: str = "1.0.0",
    author: str = "Agent Engine",
    registry: PipelineRegistry | None = None,
) -> Callable[[Type[dspy.Module]], Type[dspy.Module]]:
    """Decorator to register a DSPy Module class into the PipelineRegistry."""

    def decorator(cls: Type[dspy.Module]) -> Type[dspy.Module]:
        target_registry = registry or get_pipeline_registry()
        meta = PipelineMetadata(
            name=name,
            description=description,
            inputs=inputs or [],
            outputs=outputs or [],
            tools=tools or [],
            guardrails=guardrails or [],
            category=category,
            version=version,
            author=author,
        )
        target_registry.register(cls, meta)
        return cls

    return decorator
