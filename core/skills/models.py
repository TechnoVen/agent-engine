"""core/skills/models.py

Unified Data Models for Agent Engine Multi-Tool Skill Management.
Part of Phase 6 (Task 6.1 - Milestone M4).
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SkillSource(str, Enum):
    """Origin tool or registry of a skill."""

    AGENT_ENGINE = "agent-engine"
    CLAUDE_CODE = "claude-code"
    CURSOR = "cursor"
    CODEX = "codex"
    GOOSE = "goose"
    REGISTRY = "registry"
    REMOTE = "remote"


class SkillFormat(str, Enum):
    """File/payload format of a skill."""

    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"


class SkillPermission(str, Enum):
    """Canonical capability permissions for skills and tool executions."""

    READ = "read"
    WRITE_LOCAL = "write_local"
    EXECUTE = "execute"
    NETWORK = "network"
    COMMUNICATE = "communicate"
    ADMIN = "admin"
    FINANCIAL = "financial"
    DESTRUCTIVE = "destructive"


class SkillMetadata(BaseModel):
    """Standardized metadata across all discovered and authored skills."""

    id: str = Field(..., description="Unique slug ID of the skill")
    name: str = Field(..., description="Human-readable skill name")
    description: str = Field(default="", description="Summary of instructions or purpose")
    version: str = Field(default="1.0.0", description="Semantic version string")
    author: str = Field(default="local", description="Author or publisher of the skill")
    tags: List[str] = Field(default_factory=list, description="Categorization tags")
    category: str = Field(default="General", description="Grouping category")
    inputs: List[str] = Field(default_factory=list, description="Declared input variable names")
    outputs: List[str] = Field(default_factory=list, description="Declared output variable names")
    tools: List[str] = Field(default_factory=list, description="Required MCP or native tool names")
    permissions: List[SkillPermission] = Field(
        default_factory=list, description="Canonical declared permissions"
    )
    implementation_hash: Optional[str] = Field(
        default=None, description="SHA-256 hash of the implementation"
    )
    source_tool: SkillSource = Field(
        default=SkillSource.AGENT_ENGINE, description="Originating tool environment"
    )
    license: Optional[str] = Field(default="MIT", description="Software license")
    created_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    updated_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="Tool-specific extended metadata"
    )


class Skill(BaseModel):
    """Unified skill entity representing an executable or prompted instruction set."""

    id: str
    metadata: SkillMetadata
    content: str = Field(
        default="", description="Raw body text (Markdown instructions, prompt, or JSON)"
    )
    path: Optional[str] = Field(default=None, description="Absolute or relative file path on disk")
    is_readonly: bool = Field(default=False, description="Whether skill is built-in or read-only")
    format: SkillFormat = Field(
        default=SkillFormat.MARKDOWN, description="Underlying serialization format"
    )

    def model_post_init(self, __context: Any) -> None:
        """Ensure implementation_hash is populated from content if missing."""
        if not self.metadata.implementation_hash and self.content:
            import hashlib

            self.metadata.implementation_hash = hashlib.sha256(
                self.content.strip().encode("utf-8")
            ).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert Skill to dictionary representation."""
        return self.model_dump()


class SkillCollection(BaseModel):
    """Curated or user-defined collection of skills."""

    id: str = Field(..., description="Unique slug ID of the collection")
    name: str = Field(..., description="Display name of the collection")
    description: str = Field(default="", description="Detailed purpose of the collection")
    skill_ids: List[str] = Field(default_factory=list, description="List of member skill IDs")
    tags: List[str] = Field(default_factory=list, description="Category/domain tags")
    created_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    updated_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
