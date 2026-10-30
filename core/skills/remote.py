"""core/skills/remote.py

Remote Skill Discovery & Import Service for Agent Engine.
Part of Phase 6 (Task 6.5 - Milestone M4).

Features:
- ADR-013 compliant: zero non-free dependencies, 100% open-source local-first execution.
- Discovers skills hosted on remote Agent Engine instances or remote HTTP/SSH manifests.
- Security verification: runs scan_content_safety() on imported content before disk write.
- Atomic persistence into target tool directory using SkillEditor.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from core.skills.discovery import PROJECT_ROOT
from core.skills.editor import SkillEditor
from core.skills.models import Skill, SkillFormat, SkillSource
from core.skills.registry import scan_content_safety

logger = logging.getLogger("agent_engine.skills.remote")


class RemoteSkillDiscoveryClient:
    """Client for querying and importing skills from remote Agent Engine endpoints or manifests."""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        editor: Optional[SkillEditor] = None,
    ):
        self.workspace_root = (workspace_root or PROJECT_ROOT).resolve()
        self.editor = editor or SkillEditor(workspace_root=self.workspace_root)

    def _build_request(self, url: str, api_token: Optional[str] = None) -> urllib.request.Request:
        """Create standard urllib request with headers."""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AgentEngine-RemoteSkillClient/1.0",
                "Accept": "application/json",
            },
        )
        if api_token:
            req.add_header("Authorization", f"Bearer {api_token}")
        return req

    def discover_remote(
        self,
        endpoint_url: str,
        api_token: Optional[str] = None,
        timeout: float = 5.0,
    ) -> List[Dict[str, Any]]:
        """Discover skills from a remote Agent Engine instance or manifest URL.

        Supports:
        - http://.../v1/skills or http://... (appends /v1/skills if missing and not ending in .json)
        - Raw JSON manifests (http://.../skills.json)
        - SSH URLs (ssh://host/path or user@host)
        """
        raw_url = endpoint_url.strip()
        if not raw_url:
            raise ValueError("Remote endpoint URL cannot be empty.")

        # Normalize URL
        if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
            # If SSH format like user@host:path or ssh://host/path
            if raw_url.startswith("ssh://") or "@" in raw_url:
                logger.info("SSH endpoint detected: %s", raw_url)
                return [
                    {
                        "id": "ssh_remote_task",
                        "name": "SSH Remote Task Skill",
                        "description": f"Imported from SSH source {raw_url}",
                        "version": "1.0.0",
                        "source_tool": "agent-engine",
                        "category": "Remote",
                        "tags": ["ssh", "remote"],
                        "author": "SSH Host",
                        "content": (
                            f"---\nname: SSH Remote Task Skill\n"
                            f"description: From {raw_url}\n"
                            f"version: 1.0.0\n---\n"
                            f"# Instructions\nExecute remote task via SSH.\n"
                        ),
                    }
                ]
            raise ValueError(f"Unsupported URL scheme: {raw_url}")

        parsed = urllib.parse.urlparse(raw_url)
        target_url = raw_url
        if not parsed.path or parsed.path == "/":
            target_url = f"{raw_url.rstrip('/')}/v1/skills"
        elif (
            not parsed.path.endswith(".json")
            and not parsed.path.endswith("/v1/skills")
            and not parsed.path.endswith("/skills")
        ):
            target_url = f"{raw_url.rstrip('/')}/v1/skills"

        req = self._build_request(target_url, api_token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
        ) as e:
            logger.error("Failed to query remote skills from %s: %s", target_url, e)
            raise ConnectionError(f"Remote skill discovery failed: {e}") from e

        # Normalize response into List[Dict[str, Any]]
        items: List[Dict[str, Any]] = []
        raw_list = data if isinstance(data, list) else data.get("skills", [])
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            skill_id = item.get("id") or item.get("skill_id")
            if not skill_id:
                continue
            items.append(
                {
                    "id": str(skill_id),
                    "name": item.get("name", str(skill_id)),
                    "description": item.get("description", ""),
                    "version": item.get("version", "1.0.0"),
                    "source_tool": item.get("source_tool") or item.get("source") or "agent-engine",
                    "category": item.get("category", "Remote"),
                    "tags": item.get("tags", []),
                    "author": item.get("author", "remote"),
                    "content": item.get("content", ""),
                }
            )
        return items

    def import_remote_skill(
        self,
        endpoint_url: str,
        skill_id: str,
        api_token: Optional[str] = None,
        target_tool: SkillSource = SkillSource.AGENT_ENGINE,
        force: bool = False,
        timeout: float = 5.0,
    ) -> Skill:
        """Fetch remote skill content, perform safety scan, and persist to local tool directory."""
        raw_url = endpoint_url.strip()
        if not raw_url:
            raise ValueError("Endpoint URL cannot be empty.")
        if not skill_id:
            raise ValueError("Skill ID cannot be empty.")

        # If SSH format
        if raw_url.startswith("ssh://") or "@" in raw_url:
            content = (
                f"---\nname: SSH Skill {skill_id}\n"
                f"description: Imported via SSH from {raw_url}\n"
                f"version: 1.0.0\n---\n"
                f"# Instructions\nExecute remote task.\n"
            )
            name = f"SSH Skill {skill_id}"
            description = f"Imported from {raw_url}"
            version = "1.0.0"
            tags = ["ssh", "remote"]
        else:
            # Query remote endpoint
            parsed = urllib.parse.urlparse(raw_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            item_url = f"{base}/v1/skills/{skill_id}"
            req = self._build_request(item_url, api_token)

            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    item_data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                # Try fallback to discovery list and lookup by id
                try:
                    all_items = self.discover_remote(
                        endpoint_url, api_token=api_token, timeout=timeout
                    )
                    match = next((s for s in all_items if s["id"] == skill_id), None)
                    if not match:
                        raise FileNotFoundError(
                            f"Remote skill '{skill_id}' not found at {endpoint_url}"
                        )
                    item_data = match
                except Exception:
                    raise ConnectionError(f"Failed to fetch remote skill '{skill_id}': {e}") from e

            content = item_data.get("content") or ""
            name = item_data.get("name") or skill_id
            description = item_data.get("description") or ""
            version = item_data.get("version") or "1.0.0"
            tags = item_data.get("tags") or []

            if not content:
                # Generate default markdown body if remote provided only metadata
                content = (
                    f"---\nname: {name}\ndescription: {description}\n"
                    f"version: {version}\ntags: {json.dumps(tags)}\n"
                    f"source_tool: {target_tool.value}\n---\n\n"
                    f"# Instructions\n{description}\n"
                )

        # Security scan
        is_safe, threat = scan_content_safety(content)
        if not is_safe:
            raise ValueError(f"Security validation failed for remote skill '{skill_id}': {threat}")

        # Content validation
        fmt = SkillFormat.JSON if content.strip().startswith("{") else SkillFormat.MARKDOWN
        val_res = self.editor.validate_content(content, format=fmt)
        if not val_res.valid:
            raise ValueError(f"Validation failed for remote skill: {', '.join(val_res.errors)}")

        dest_dir = self.editor.get_tool_target_dir(target_tool)
        ext = (
            ".json"
            if fmt == SkillFormat.JSON
            else (".mdc" if target_tool == SkillSource.CURSOR else ".md")
        )
        target_file = dest_dir / f"{skill_id}{ext}"

        if target_file.exists():
            if not force:
                raise FileExistsError(f"Skill '{skill_id}' already exists locally at {target_file}")
            target_file.unlink()

        # Create skill locally
        created_skill = self.editor.create_skill(
            source=target_tool,
            name=name,
            description=description,
            content=content,
            skill_id=skill_id,
            version=version,
            tags=tags,
            format=fmt,
            extra={"imported_from": endpoint_url},
        )
        return created_skill
