import numpy  # noqa: F401
from dataclasses import asdict, dataclass, field
import logging
import threading
from typing import Any, Callable, Optional, Type

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
    artifact_mappings: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PipelineRegistry:
    """Thread-safe registry for modular DSPy agent pipelines."""

    def __init__(self, coordinator: Optional[Any] = None) -> None:
        self._lock = threading.RLock()
        self._registry: dict[str, tuple[Type[dspy.Module], PipelineMetadata]] = {}
        self._coordinator = coordinator

    def set_coordinator(self, coordinator: Any) -> None:
        """Set or update the ExecutionCoordinator backing this registry."""
        with self._lock:
            self._coordinator = coordinator

    def _get_coordinator(self) -> Any:
        """Resolve ExecutionCoordinator instance."""
        with self._lock:
            if self._coordinator is not None:
                return self._coordinator
        try:
            from services.python.server.api import get_execution_coordinator

            return get_execution_coordinator()
        except Exception:
            from core.execution.coordinator import ExecutionCoordinator

            return ExecutionCoordinator()

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

    def extract_artifact_candidates(self, name: str, outputs: dict[str, Any]) -> list[Any]:
        """Extract canonical ArtifactCandidate objects from pipeline outputs according to metadata."""
        import json
        from core.artifacts.models import ArtifactCandidate, ArtifactStatus, ArtifactType

        candidates: list[ArtifactCandidate] = []
        meta = self.get_metadata(name)
        mappings = meta.artifact_mappings if meta else {}

        default_mappings: dict[str, dict[str, Any]] = {
            "diff_patch": {
                "name": "diff.patch",
                "type": ArtifactType.PATCH,
                "mime_type": "text/x-diff",
            },
            "vulnerabilities": {
                "name": "vulnerabilities.json",
                "type": ArtifactType.DATA,
                "mime_type": "application/json",
            },
            "fixed_code": {
                "name": "fixed_code.py",
                "type": ArtifactType.CODE,
                "mime_type": "text/x-python",
            },
            "clean_code": {
                "name": "clean_code.py",
                "type": ArtifactType.CODE,
                "mime_type": "text/x-python",
            },
        }

        active_mappings = {**default_mappings, **mappings}

        for field_name, map_cfg in active_mappings.items():
            if field_name in outputs and outputs[field_name] is not None:
                val = outputs[field_name]
                if isinstance(val, (dict, list)):
                    content_str = json.dumps(val, indent=2)
                else:
                    content_str = str(val)

                name_val = map_cfg.get("name", f"{field_name}.txt")
                if field_name == "vulnerabilities" and not isinstance(val, (dict, list)):
                    name_val = "vulnerabilities.txt"

                candidates.append(
                    ArtifactCandidate(
                        name=name_val,
                        content=content_str,
                        type=map_cfg.get("type", ArtifactType.DATA),
                        mime_type=map_cfg.get("mime_type"),
                        status=ArtifactStatus.READY,
                        lineage={"pipeline_name": name, "field": field_name},
                    )
                )

        return candidates

    async def run_async(self, name: str, **inputs: Any) -> dict[str, Any]:
        """Instantiate and execute a registered pipeline asynchronously via ExecutionCoordinator."""
        meta = self.get_metadata(name)
        if meta is None:
            raise KeyError(f"Pipeline '{name}' not found in registry")

        coordinator = self._get_coordinator()
        if getattr(coordinator, "pipeline_registry", None) is not self:
            coordinator.pipeline_registry = self

        project_id = inputs.get("project_id", "default")
        session_id = inputs.get("session_id")

        from core.execution.models import ExecutionRequest, ExecutionStatus

        clean_inputs = {k: v for k, v in inputs.items() if k != "pipeline_registry"}
        exec_req = ExecutionRequest(
            task_type="pipeline",
            prompt=str(
                inputs.get("prompt")
                or inputs.get("code")
                or inputs.get("brief")
                or inputs.get("document_text")
                or inputs.get("outline")
                or f"Execute pipeline {name}"
            ),
            inputs={
                "pipeline_name": name,
                "pipeline_inputs": clean_inputs,
                **clean_inputs,
            },
            project_id=project_id,
            session_id=session_id,
        )

        result = await coordinator.execute(exec_req)

        if result.status == ExecutionStatus.BLOCKED:
            raise PermissionError(
                f"Pipeline '{name}' execution blocked by guardrails: {result.error}"
            )
        if result.status == ExecutionStatus.CANCELLED:
            from core.execution.cancellation import ExecutionCancelledError

            raise ExecutionCancelledError(f"Pipeline '{name}' cancelled: {result.error}")
        if result.status == ExecutionStatus.FAILED:
            raise RuntimeError(f"Pipeline '{name}' execution failed: {result.error}")

        return result.outputs

    def run(self, name: str, **inputs: Any) -> dict[str, Any]:
        """Instantiate and execute a registered pipeline with given inputs.
        Synchronous compatibility wrapper delegating to run_async via ExecutionCoordinator."""

        def _run_coroutine_sync(coro: Any) -> Any:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()
            else:
                return asyncio.run(coro)

        return _run_coroutine_sync(self.run_async(name, **inputs))

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
    artifact_mappings: dict[str, dict[str, Any]] | None = None,
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
            artifact_mappings=artifact_mappings or {},
        )
        target_registry.register(cls, meta)
        return cls

    return decorator
