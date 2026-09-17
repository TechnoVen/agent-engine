"""core/skills/editor.py

Skill Editor Service for Agent Engine.
Part of Phase 6 (Task 6.2 - Milestone M4).

Features:
- CRUD operations for skills across tool-specific directories (Claude Code, Cursor, Codex, Goose, Agent Engine).
- Atomic safe file writing with rename to prevent corruption.
- Frontmatter YAML and JSON schema validation with syntax and semantic diagnostics.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field

from core.skills.discovery import MultiToolSkillDiscovery, PROJECT_ROOT
from core.skills.models import Skill, SkillFormat, SkillMetadata, SkillSource

logger = logging.getLogger("agent_engine.skills.editor")


class SkillValidationResult(BaseModel):
    """Validation report for a skill definition or raw file content."""

    valid: bool
    errors: List[str] = Field(default_factory=list, description="Fatal validation errors")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings or lints")
    parsed_metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Extracted metadata if parsing succeeded"
    )


class SkillEditor:
    """Manages authoring, modifying, validating, and deleting skill files across developer tool paths."""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        home_dir: Optional[Path] = None,
        discovery: Optional[MultiToolSkillDiscovery] = None,
    ):
        self.workspace_root = (workspace_root or PROJECT_ROOT).resolve()
        self.home_dir = (home_dir or Path(os.path.expanduser("~"))).resolve()
        self.discovery = discovery or MultiToolSkillDiscovery()

    def get_tool_target_dir(self, source: SkillSource) -> Path:
        """Return the canonical directory for storing skills for the specified tool source."""
        if source == SkillSource.AGENT_ENGINE:
            return self.workspace_root / "data" / "skills"
        elif source == SkillSource.CLAUDE_CODE:
            return self.home_dir / ".claude" / "commands"
        elif source == SkillSource.CURSOR:
            return self.workspace_root / ".cursor" / "rules"
        elif source == SkillSource.CODEX:
            return self.workspace_root / ".codex" / "skills"
        elif source == SkillSource.GOOSE:
            return self.home_dir / ".config" / "goose" / "skills"
        elif source == SkillSource.REGISTRY:
            return self.workspace_root / "data" / "skills" / "registry"
        elif source == SkillSource.REMOTE:
            return self.workspace_root / "data" / "skills" / "remote"
        return self.workspace_root / "data" / "skills"

    def validate_content(
        self,
        content: str,
        format: SkillFormat = SkillFormat.MARKDOWN,
    ) -> SkillValidationResult:
        """Validate raw content string against syntax and structural schema requirements."""
        errors: List[str] = []
        warnings: List[str] = []
        parsed_metadata: Optional[Dict[str, Any]] = None

        if not content.strip():
            return SkillValidationResult(
                valid=False,
                errors=["Skill content cannot be empty."],
                warnings=warnings,
                parsed_metadata=None,
            )

        if format == SkillFormat.JSON:
            try:
                data = json.loads(content)
                if not isinstance(data, dict):
                    return SkillValidationResult(
                        valid=False,
                        errors=["Root JSON element must be an object/dict."],
                    )
                parsed_metadata = data

                if not data.get("name") and not data.get("id"):
                    errors.append("Missing required field: 'name' or 'id'.")
                if not data.get("description"):
                    warnings.append("Missing recommended field: 'description'.")
                if "inputs" in data and not isinstance(data["inputs"], (list, dict)):
                    errors.append("'inputs' field must be a list of keys or dictionary.")
                if "outputs" in data and not isinstance(data["outputs"], (list, dict)):
                    errors.append("'outputs' field must be a list of keys or dictionary.")

            except Exception as e:
                return SkillValidationResult(
                    valid=False,
                    errors=[f"Invalid JSON syntax: {e}"],
                )
        else:
            # Markdown / frontmatter validation
            pattern = r"^---\s*\n(.*?)\n---\s*\n?(.*)$"
            match = re.match(pattern, content, re.DOTALL)
            if match:
                fm_raw, body = match.group(1), match.group(2)
                try:
                    meta = yaml.safe_load(fm_raw)
                    if not isinstance(meta, dict):
                        errors.append("Frontmatter YAML must parse to a dictionary/mapping.")
                    else:
                        parsed_metadata = meta
                        if not meta.get("name"):
                            errors.append("Frontmatter missing required field: 'name'.")
                        if not meta.get("description"):
                            warnings.append("Frontmatter missing recommended field: 'description'.")

                        version = str(meta.get("version", ""))
                        if version and not re.match(r"^\d+\.\d+(\.\d+)?", version):
                            warnings.append(f"Version '{version}' is not semantic (e.g., 1.0.0).")

                        if "inputs" in meta and not isinstance(meta["inputs"], (list, dict)):
                            errors.append("Frontmatter 'inputs' must be a list or dict.")
                        if "outputs" in meta and not isinstance(meta["outputs"], (list, dict)):
                            errors.append("Frontmatter 'outputs' must be a list or dict.")

                except Exception as e:
                    errors.append(f"Invalid YAML frontmatter syntax: {e}")

                if not body.strip():
                    warnings.append("Skill Markdown body contains no instructions.")
            else:
                warnings.append(
                    "No YAML frontmatter found; relying on markdown structure and headers."
                )
                heading_match = re.match(r"^#\s+(.+)$", content.strip(), re.MULTILINE)
                if heading_match:
                    parsed_metadata = {"name": heading_match.group(1).strip()}
                else:
                    warnings.append("No primary H1 heading (# Name) found in markdown.")

        return SkillValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            parsed_metadata=parsed_metadata,
        )

    def _atomic_write(self, target_path: Path, content: str) -> None:
        """Write content to target path atomically using a temporary file and replace."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_file_path = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix=".tmp_skill_",
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_file_path, target_path)
        except Exception:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            raise

    def create_skill(
        self,
        source: SkillSource,
        name: str,
        description: str,
        content: str,
        skill_id: Optional[str] = None,
        author: str = "local",
        version: str = "1.0.0",
        tags: Optional[List[str]] = None,
        inputs: Optional[List[str]] = None,
        outputs: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        target_dir: Optional[Path] = None,
        format: SkillFormat = SkillFormat.MARKDOWN,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Skill:
        """Create a new skill and write it to the canonical tool directory."""
        clean_id = (
            skill_id or re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower()).strip("_") or "new_skill"
        )
        dest_dir = target_dir or self.get_tool_target_dir(source)

        ext = (
            ".json"
            if format == SkillFormat.JSON
            else (".mdc" if source == SkillSource.CURSOR else ".md")
        )
        target_file = dest_dir / f"{clean_id}{ext}"

        if target_file.exists():
            raise FileExistsError(f"Skill '{clean_id}' already exists at {target_file}")

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        metadata = SkillMetadata(
            id=clean_id,
            name=name,
            description=description,
            version=version,
            author=author,
            tags=tags or [],
            category=(extra or {}).get("category", "General"),
            inputs=inputs or [],
            outputs=outputs or [],
            tools=tools or [],
            source_tool=source,
            created_at=timestamp,
            updated_at=timestamp,
            extra=extra or {},
        )

        if format == SkillFormat.JSON:
            payload = {
                "id": clean_id,
                "name": name,
                "description": description,
                "version": version,
                "author": author,
                "tags": tags or [],
                "inputs": inputs or [],
                "outputs": outputs or [],
                "tools": tools or [],
                "source_tool": source.value,
                "body": content,
                **(extra or {}),
            }
            raw_text = json.dumps(payload, indent=2)
        else:
            fm_data: Dict[str, Any] = {
                "name": name,
                "description": description,
                "version": version,
                "author": author,
                "source_tool": source.value,
            }
            if tags:
                fm_data["tags"] = tags
            if inputs:
                fm_data["inputs"] = inputs
            if outputs:
                fm_data["outputs"] = outputs
            if tools:
                fm_data["tools"] = tools
            if extra:
                for k, v in extra.items():
                    if k not in fm_data:
                        fm_data[k] = v

            fm_yaml = yaml.safe_dump(fm_data, sort_keys=False).strip()
            raw_text = f"---\n{fm_yaml}\n---\n\n{content.strip()}\n"

        self._atomic_write(target_file, raw_text)

        return Skill(
            id=clean_id,
            metadata=metadata,
            content=content,
            path=str(target_file.resolve()),
            is_readonly=False,
            format=format,
        )

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Find a skill by ID using multi-tool discovery."""
        return self.discovery.get_skill(skill_id, workspace_dir=self.workspace_root)

    def update_skill(
        self,
        skill_id: str,
        content: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> Skill:
        """Update an existing skill in place, updating frontmatter and body atomically."""
        skill = self.get_skill(skill_id)
        if not skill or not skill.path:
            raise FileNotFoundError(f"Skill '{skill_id}' not found.")

        if skill.is_readonly:
            raise PermissionError(f"Skill '{skill_id}' is read-only.")

        file_path = Path(skill.path)
        if not file_path.exists():
            raise FileNotFoundError(f"Skill file missing at {file_path}")

        updates = metadata_updates or {}
        new_content = content if content is not None else skill.content

        if skill.format == SkillFormat.JSON:
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            data.update(updates)
            if content is not None:
                data["body"] = content
            data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            raw_text = json.dumps(data, indent=2)
        else:
            old_raw = file_path.read_text(encoding="utf-8")
            old_fm, old_body = MultiToolSkillDiscovery.parse_frontmatter(old_raw)
            old_fm.update(updates)
            old_fm["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fm_yaml = yaml.safe_dump(old_fm, sort_keys=False).strip()
            body_to_write = new_content.strip()
            raw_text = f"---\n{fm_yaml}\n---\n\n{body_to_write}\n"

        self._atomic_write(file_path, raw_text)

        # Return refreshed skill
        refreshed = self.discovery._parse_file_as_skill(file_path, skill.metadata.source_tool)
        if not refreshed:
            raise RuntimeError(f"Failed to reload updated skill from {file_path}")
        return refreshed

    def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill file from disk."""
        skill = self.get_skill(skill_id)
        if not skill or not skill.path:
            return False

        if skill.is_readonly:
            raise PermissionError(f"Skill '{skill_id}' is read-only.")

        file_path = Path(skill.path)
        if file_path.exists():
            file_path.unlink()
            return True
        return False
