"""core/skills/discovery.py

Multi-Tool Skill Discovery Service for Agent Engine.
Part of Phase 6 (Task 6.1 - Milestone M4).

Features:
- Automatic multi-tool skill discovery across Claude Code, Cursor, Codex, Goose, and Agent Engine.
- YAML frontmatter parser for markdown prompt & rule files.
- JSON template loader mapping declarative templates into unified Skill models.
- Configurable search paths for local development, tests, and user workspaces.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from core.skills.models import Skill, SkillFormat, SkillMetadata, SkillSource

logger = logging.getLogger("agent_engine.skills.discovery")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class MultiToolSkillDiscovery:
    """
    Discovers, parses, and normalizes skills authored for different developer tools
    (Claude Code, Cursor, Codex, Goose, and Agent Engine).
    """

    def __init__(
        self,
        agent_engine_dirs: Optional[List[Path]] = None,
        claude_dirs: Optional[List[Path]] = None,
        cursor_dirs: Optional[List[Path]] = None,
        codex_dirs: Optional[List[Path]] = None,
        goose_dirs: Optional[List[Path]] = None,
    ):
        self._custom_ae_dirs = agent_engine_dirs
        self._custom_claude_dirs = claude_dirs
        self._custom_cursor_dirs = cursor_dirs
        self._custom_codex_dirs = codex_dirs
        self._custom_goose_dirs = goose_dirs

    @staticmethod
    def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
        """
        Extract YAML frontmatter and body content from a markdown file.
        Returns (metadata_dict, body_content).
        """
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        if match:
            fm_text, body = match.group(1), match.group(2)
            try:
                meta = yaml.safe_load(fm_text) or {}
                if isinstance(meta, dict):
                    return meta, body.strip()
            except Exception as e:
                logger.debug(f"Failed to parse frontmatter as YAML: {e}")

        # Fallback: check for top-level heading if no frontmatter
        heading_match = re.match(r"^#\s+(.+)$", content.strip(), re.MULTILINE)
        name = heading_match.group(1).strip() if heading_match else ""
        meta = {"name": name} if name else {}
        return meta, content.strip()

    def _resolve_paths(
        self,
        tool: SkillSource,
        workspace_dir: Optional[Path] = None,
    ) -> List[Path]:
        """Resolve list of existing directories/files for a given tool source."""
        home = Path(os.path.expanduser("~"))
        ws = workspace_dir or PROJECT_ROOT
        paths: List[Path] = []

        if tool == SkillSource.AGENT_ENGINE:
            if self._custom_ae_dirs is not None:
                return self._custom_ae_dirs
            paths.extend(
                [
                    ws / "configs" / "templates",
                    ws / "data" / "skills",
                    ws / ".agent-engine" / "skills",
                    home / ".agent-engine" / "skills",
                ]
            )
        elif tool == SkillSource.CLAUDE_CODE:
            if self._custom_claude_dirs is not None:
                return self._custom_claude_dirs
            paths.extend(
                [
                    ws / ".claude" / "commands",
                    ws / ".claude" / "skills",
                    home / ".claude" / "commands",
                    home / ".claude" / "skills",
                ]
            )
        elif tool == SkillSource.CURSOR:
            if self._custom_cursor_dirs is not None:
                return self._custom_cursor_dirs
            paths.extend(
                [
                    ws / ".cursor" / "rules",
                    ws / ".cursorrules",
                    home / ".cursor" / "rules",
                ]
            )
        elif tool == SkillSource.CODEX:
            if self._custom_codex_dirs is not None:
                return self._custom_codex_dirs
            paths.extend(
                [
                    ws / "configs" / "codex" / "skills",
                    ws / ".codex" / "skills",
                    home / ".codex" / "skills",
                ]
            )
        elif tool == SkillSource.GOOSE:
            if self._custom_goose_dirs is not None:
                return self._custom_goose_dirs
            paths.extend(
                [
                    ws / ".goose" / "skills",
                    ws / ".goosehints",
                    home / ".config" / "goose" / "skills",
                ]
            )

        return [p for p in paths if p.exists()]

    def _parse_file_as_skill(self, file_path: Path, source_tool: SkillSource) -> Optional[Skill]:
        """Read and parse a file into a Skill object."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.debug(f"Could not read skill file {file_path}: {e}")
            return None

        slug_id = file_path.stem.lower().replace(" ", "_")

        # 1. JSON Skill Format
        if file_path.suffix.lower() == ".json":
            try:
                data = json.loads(content)
                if not isinstance(data, dict):
                    return None

                skill_id = data.get("id") or slug_id
                name = data.get("name") or skill_id.replace("_", " ").title()
                desc = data.get("description", "")
                cat = data.get("category", "General")
                tags = data.get("tags", [])
                inputs = (
                    list(data.get("inputs", {}).keys())
                    if isinstance(data.get("inputs"), dict)
                    else data.get("inputs", [])
                )
                outputs = (
                    list(data.get("outputs", {}).keys())
                    if isinstance(data.get("outputs"), dict)
                    else data.get("outputs", [])
                )
                tools = data.get("tools", [])

                metadata = SkillMetadata(
                    id=skill_id,
                    name=name,
                    description=desc,
                    category=cat,
                    tags=tags,
                    inputs=inputs,
                    outputs=outputs,
                    tools=tools,
                    source_tool=source_tool,
                )
                return Skill(
                    id=skill_id,
                    metadata=metadata,
                    content=content,
                    path=str(file_path.resolve()),
                    format=SkillFormat.JSON,
                )
            except Exception as e:
                logger.debug(f"Error parsing JSON skill {file_path}: {e}")
                return None

        # 2. Markdown / Rules / Hints Format
        fm, body = self.parse_frontmatter(content)
        name = fm.get("name") or fm.get("title") or slug_id.replace("_", " ").title()
        description = fm.get("description") or fm.get("summary") or (body[:160] if body else "")
        category = fm.get("category") or "General"
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        tools = fm.get("tools") or []
        if isinstance(tools, str):
            tools = [tools]

        metadata = SkillMetadata(
            id=slug_id,
            name=name,
            description=description,
            category=category,
            tags=tags,
            tools=tools,
            source_tool=source_tool,
            version=str(fm.get("version", "1.0.0")),
            author=str(fm.get("author", "local")),
            extra=fm,
        )

        return Skill(
            id=slug_id,
            metadata=metadata,
            content=body or content,
            path=str(file_path.resolve()),
            format=SkillFormat.MARKDOWN,
        )

    def discover_by_tool(
        self,
        source_tool: SkillSource,
        workspace_dir: Optional[Path] = None,
    ) -> List[Skill]:
        """Discover all skills belonging to a specific tool source."""
        skills: List[Skill] = []
        resolved = self._resolve_paths(source_tool, workspace_dir=workspace_dir)

        for target in resolved:
            if target.is_file():
                skill = self._parse_file_as_skill(target, source_tool)
                if skill:
                    skills.append(skill)
            elif target.is_dir():
                for ext in ("*.json", "*.md", "*.markdown", "*.yaml", "*.yml"):
                    for file_path in target.glob(ext):
                        skill = self._parse_file_as_skill(file_path, source_tool)
                        if skill:
                            skills.append(skill)

        return skills

    def discover_all(self, workspace_dir: Optional[Path] = None) -> List[Skill]:
        """Discover skills across all registered tools with deduplication."""
        all_skills: Dict[str, Skill] = {}

        # Prioritize tools in order
        tools_order = [
            SkillSource.AGENT_ENGINE,
            SkillSource.CLAUDE_CODE,
            SkillSource.CURSOR,
            SkillSource.CODEX,
            SkillSource.GOOSE,
        ]

        for tool in tools_order:
            for skill in self.discover_by_tool(tool, workspace_dir=workspace_dir):
                if skill.id not in all_skills:
                    all_skills[skill.id] = skill

        return list(all_skills.values())

    def get_skill(
        self,
        skill_id: str,
        workspace_dir: Optional[Path] = None,
    ) -> Optional[Skill]:
        """Find a specific skill by unique ID across all tool sources."""
        for skill in self.discover_all(workspace_dir=workspace_dir):
            if skill.id == skill_id:
                return skill
        return None
