# core/templates.py
# Custom OpenClaw Skill Templates Engine
# Declarative, reusable workflow templates mapped to DSPy dynamic signatures

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from core.engine import DynamicSignatureBuilder, LowCodeAgent, NodeConfig

# Default storage path for template configurations
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATES_DIR = PROJECT_ROOT / "configs" / "templates"


class SkillTemplate(BaseModel):
    """
    Declarative representation of an OpenClaw skill template.
    Abstracts Python skills into configurable JSON/YAML schemas.
    """

    id: str = Field(..., description="Unique slug identifier (e.g. 'summarize_meeting_notes')")
    name: str = Field(..., description="Human-readable template name")
    description: str = Field(..., description="Detailed instructions and objective for the agent")
    version: str = Field(default="1.0.0", description="Semantic template version")
    category: str = Field(
        default="Productivity",
        description="Workflow category (e.g. 'Productivity', 'Engineering', 'Data')",
    )
    tags: List[str] = Field(default_factory=list, description="Categorization tags")
    inputs: Union[List[str], Dict[str, str]] = Field(
        default_factory=list,
        description="Declared inputs as list of names or {field_name: field_description}",
    )
    outputs: Union[List[str], Dict[str, str]] = Field(
        default_factory=list,
        description="Declared outputs as list of names or {field_name: field_description}",
    )
    reasoning_type: str = Field(
        default="cot",
        description="Reasoning style: 'cot' (Chain of Thought), 'react' (ReAct with Tools), or 'predict' (Direct)",
    )
    tools: List[str] = Field(
        default_factory=list, description="List of registered tool names required by this template"
    )
    sample_inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Default sample values for instant playground testing and validation",
    )

    def to_node_config(self) -> NodeConfig:
        """Convert this template into a NodeConfig for the DSPy LowCodeAgent."""
        return NodeConfig(
            name=self.name,
            description=self.description,
            inputs=self.inputs,
            outputs=self.outputs,
            tools=self.tools,
            reasoning_type=self.reasoning_type,
        )

    @classmethod
    def from_node_config(
        cls,
        config: NodeConfig,
        template_id: Optional[str] = None,
        category: str = "Custom",
        tags: Optional[List[str]] = None,
        sample_inputs: Optional[Dict[str, Any]] = None,
    ) -> "SkillTemplate":
        """Construct a SkillTemplate from an existing NodeConfig."""
        slug = template_id or re.sub(r"[^a-zA-Z0-9_]+", "_", config.name.lower()).strip("_")
        return cls(
            id=slug,
            name=config.name,
            description=config.description,
            inputs=config.inputs,
            outputs=config.outputs,
            reasoning_type=config.reasoning_type,
            tools=config.tools,
            category=category,
            tags=tags or [],
            sample_inputs=sample_inputs or {},
        )

    def to_signature(self) -> type:
        """Dynamically construct a DSPy Signature class from this template."""
        return DynamicSignatureBuilder.build(self.to_node_config())

    def create_agent(self, tool_registry: Optional[Dict[str, Callable]] = None) -> LowCodeAgent:
        """Instantiate an executable LowCodeAgent using this template's specification."""
        return LowCodeAgent(self.to_node_config(), tool_registry=tool_registry)

    def execute(
        self, tool_registry: Optional[Dict[str, Callable]] = None, **kwargs
    ) -> Dict[str, Any]:
        """Execute this template against the provided inputs and return a dictionary of outputs."""
        agent = self.create_agent(tool_registry=tool_registry)
        prediction = agent(**kwargs)
        if hasattr(prediction, "toDict"):
            return prediction.toDict()
        return dict(prediction)

    def to_json(self, indent: int = 2) -> str:
        """Serialize template to a formatted JSON string."""
        return self.model_dump_json(indent=indent)

    def save_to_file(self, file_path: Union[str, Path]) -> Path:
        """Save this template to a specific file on disk."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return path

    @classmethod
    def load_from_file(cls, file_path: Union[str, Path]) -> "SkillTemplate":
        """Load and validate a SkillTemplate from a JSON file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Template file not found at: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


class TemplateManager:
    """
    Manager for discovering, loading, and persisting OpenClaw skill templates in configs/templates/.
    """

    @classmethod
    def get_templates_dir(cls, custom_dir: Optional[Union[str, Path]] = None) -> Path:
        """Return the active templates directory, creating it if needed."""
        target = Path(custom_dir) if custom_dir else DEFAULT_TEMPLATES_DIR
        target.mkdir(parents=True, exist_ok=True)
        return target

    @classmethod
    def list_templates(cls, dir_path: Optional[Union[str, Path]] = None) -> List[SkillTemplate]:
        """Discover and load all valid template JSON files in the templates directory."""
        directory = cls.get_templates_dir(dir_path)
        templates = []
        for file in sorted(directory.glob("*.json")):
            try:
                tmpl = SkillTemplate.load_from_file(file)
                templates.append(tmpl)
            except Exception as e:
                # Log or skip malformed templates gracefully
                print(f"[WARN] Failed to load skill template '{file.name}': {e}")
        return templates

    @classmethod
    def get_template(
        cls, template_id: str, dir_path: Optional[Union[str, Path]] = None
    ) -> Optional[SkillTemplate]:
        """Fetch a specific template by its unique slug ID or filename."""
        directory = cls.get_templates_dir(dir_path)
        # Direct filename lookup
        direct_path = directory / f"{template_id}.json"
        if direct_path.exists():
            return SkillTemplate.load_from_file(direct_path)

        # Search by id inside files
        for tmpl in cls.list_templates(directory):
            if tmpl.id == template_id:
                return tmpl
        return None

    @classmethod
    def save_template(
        cls, template: SkillTemplate, dir_path: Optional[Union[str, Path]] = None
    ) -> Path:
        """Persist a SkillTemplate as a JSON file in the templates directory."""
        directory = cls.get_templates_dir(dir_path)
        target_file = directory / f"{template.id}.json"
        return template.save_to_file(target_file)

    @classmethod
    def delete_template(cls, template_id: str, dir_path: Optional[Union[str, Path]] = None) -> bool:
        """Remove a template file from the templates directory."""
        directory = cls.get_templates_dir(dir_path)
        target_file = directory / f"{template_id}.json"
        if target_file.exists():
            target_file.unlink()
            return True
        return False

    @classmethod
    def import_from_json(
        cls, json_content: str, dir_path: Optional[Union[str, Path]] = None
    ) -> SkillTemplate:
        """Validate and save a raw JSON string as a new skill template."""
        data = json.loads(json_content)
        template = SkillTemplate(**data)
        cls.save_template(template, dir_path=dir_path)
        return template


def load_template_agent(
    template_id_or_path: str,
    tool_registry: Optional[Dict[str, Callable]] = None,
    dir_path: Optional[Union[str, Path]] = None,
) -> LowCodeAgent:
    """
    OpenClaw execution helper: dynamically loads a template and compiles
    a LowCodeAgent without writing or importing Python code.
    """
    path = Path(template_id_or_path)
    if path.exists() and path.is_file():
        template = SkillTemplate.load_from_file(path)
    else:
        template = TemplateManager.get_template(template_id_or_path, dir_path=dir_path)
        if not template:
            raise ValueError(
                f"Skill template '{template_id_or_path}' not found in templates directory."
            )

    return template.create_agent(tool_registry=tool_registry)
