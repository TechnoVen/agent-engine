"""tests/test_skills.py

Unit and integration tests for Skill Management Subsystem (Phase 6 - Milestone M4).
Covers:
- Task 6.1: Multi-Tool Skill Discovery (Claude Code, Cursor, Codex, Goose, Agent Engine)
"""

from pathlib import Path

from core.skills.discovery import MultiToolSkillDiscovery
from core.skills.models import SkillFormat, SkillSource


def test_frontmatter_parser():
    """Verify YAML frontmatter extraction and fallback header detection."""
    # 1. Valid YAML frontmatter
    content = """---
name: Semantic Git Committer
description: Analyzes git diff and authors conventional commits
version: 1.2.0
tags: [git, automation, vcs]
category: Engineering
tools: [git_diff, git_commit]
---
# Instructions
Inspect the staged changes and produce a concise Conventional Commit message.
"""
    meta, body = MultiToolSkillDiscovery.parse_frontmatter(content)
    assert meta["name"] == "Semantic Git Committer"
    assert meta["version"] == "1.2.0"
    assert meta["category"] == "Engineering"
    assert "git" in meta["tags"]
    assert "git_diff" in meta["tools"]
    assert body.startswith("# Instructions")

    # 2. Markdown without frontmatter (fallback to title)
    plain_md = """# Rust Code Optimizer

Analyze memory safety and borrow checker lifetime constraints.
"""
    meta_plain, body_plain = MultiToolSkillDiscovery.parse_frontmatter(plain_md)
    assert meta_plain["name"] == "Rust Code Optimizer"
    assert "Analyze memory safety" in body_plain


def test_multi_tool_skill_discovery_mock(tmp_path: Path):
    """Verify discovery across mock Claude Code, Cursor, Codex, Goose, and Agent Engine directories."""
    # Setup mock directory structure
    ae_dir = tmp_path / "configs" / "templates"
    ae_dir.mkdir(parents=True)
    claude_dir = tmp_path / ".claude" / "commands"
    claude_dir.mkdir(parents=True)
    cursor_dir = tmp_path / ".cursor" / "rules"
    cursor_dir.mkdir(parents=True)
    codex_dir = tmp_path / ".codex" / "skills"
    codex_dir.mkdir(parents=True)
    goose_dir = tmp_path / ".goose" / "skills"
    goose_dir.mkdir(parents=True)

    # 1. Agent Engine Native JSON template
    (ae_dir / "summarize_notes.json").write_text(
        """{
            "id": "summarize_notes",
            "name": "Meeting Notes Summarizer",
            "description": "Synthesize meeting notes into action items",
            "category": "Productivity",
            "tags": ["meeting", "notes"],
            "inputs": ["raw_notes"],
            "outputs": ["summary", "action_items"]
        }""",
        encoding="utf-8",
    )

    # 2. Claude Code Command (.md with frontmatter)
    (claude_dir / "review_pr.md").write_text(
        """---
name: Review Pull Request
description: Perform strict security audit on PR diff
tags: [review, security]
---
Review git diff for CWE security flaws.
""",
        encoding="utf-8",
    )

    # 3. Cursor Rule (.md with frontmatter)
    (cursor_dir / "fastapi_conventions.md").write_text(
        """---
name: FastAPI Coding Standards
description: Enforce async endpoint patterns and Pydantic v2 schemas
tags: [python, fastapi]
---
Always declare type annotations and use async def for IO endpoints.
""",
        encoding="utf-8",
    )

    # 4. Codex Skill (.md)
    (codex_dir / "sql_optimizer.md").write_text(
        """---
name: SQL Query Tuner
description: Optimize query execution plan and suggest indices
tags: [sql, postgres, performance]
---
Examine EXPLAIN ANALYZE and suggest missing indices.
""",
        encoding="utf-8",
    )

    # 5. Goose Skill (.md)
    (goose_dir / "docker_builder.md").write_text(
        """---
name: Docker Multi-Stage Builder
description: Generate minimal distroless Dockerfiles
tags: [docker, devops]
---
Use multi-stage builds to minimize image surface.
""",
        encoding="utf-8",
    )

    discovery = MultiToolSkillDiscovery(
        agent_engine_dirs=[ae_dir],
        claude_dirs=[claude_dir],
        cursor_dirs=[cursor_dir],
        codex_dirs=[codex_dir],
        goose_dirs=[goose_dir],
    )

    # Discover by tool
    ae_skills = discovery.discover_by_tool(SkillSource.AGENT_ENGINE)
    assert len(ae_skills) == 1
    assert ae_skills[0].id == "summarize_notes"
    assert ae_skills[0].metadata.source_tool == SkillSource.AGENT_ENGINE
    assert ae_skills[0].format == SkillFormat.JSON

    claude_skills = discovery.discover_by_tool(SkillSource.CLAUDE_CODE)
    assert len(claude_skills) == 1
    assert claude_skills[0].id == "review_pr"
    assert claude_skills[0].metadata.source_tool == SkillSource.CLAUDE_CODE
    assert claude_skills[0].format == SkillFormat.MARKDOWN

    cursor_skills = discovery.discover_by_tool(SkillSource.CURSOR)
    assert len(cursor_skills) == 1
    assert cursor_skills[0].id == "fastapi_conventions"
    assert cursor_skills[0].metadata.source_tool == SkillSource.CURSOR

    codex_skills = discovery.discover_by_tool(SkillSource.CODEX)
    assert len(codex_skills) == 1
    assert codex_skills[0].id == "sql_optimizer"
    assert codex_skills[0].metadata.source_tool == SkillSource.CODEX

    goose_skills = discovery.discover_by_tool(SkillSource.GOOSE)
    assert len(goose_skills) == 1
    assert goose_skills[0].id == "docker_builder"
    assert goose_skills[0].metadata.source_tool == SkillSource.GOOSE

    # Discover all (deduplicated)
    all_skills = discovery.discover_all()
    assert len(all_skills) == 5
    ids = {s.id for s in all_skills}
    assert ids == {
        "summarize_notes",
        "review_pr",
        "fastapi_conventions",
        "sql_optimizer",
        "docker_builder",
    }

    # Get single skill by ID
    single = discovery.get_skill("review_pr")
    assert single is not None
    assert single.metadata.name == "Review Pull Request"
    assert "Review git diff" in single.content


def test_discover_native_configs_templates():
    """Verify discovering real templates from the agent_engine repository configs/templates/."""
    discovery = MultiToolSkillDiscovery()
    native_skills = discovery.discover_by_tool(SkillSource.AGENT_ENGINE)
    # The repository contains 12 templates in configs/templates/
    assert len(native_skills) >= 10
    names = {s.metadata.name for s in native_skills}
    assert any("Code Review" in n for n in names)
    assert any("Meeting" in n for n in names)


def test_discovery_with_malformed_files(tmp_path: Path):
    """Ensure malformed or unreadable files do not break discovery."""
    ae_dir = tmp_path / "templates"
    ae_dir.mkdir()

    # Broken JSON
    (ae_dir / "broken.json").write_text("{ not valid json :", encoding="utf-8")
    # Valid JSON
    (ae_dir / "good.json").write_text('{"id": "good_one", "name": "Good Skill"}', encoding="utf-8")

    discovery = MultiToolSkillDiscovery(agent_engine_dirs=[ae_dir])
    skills = discovery.discover_all()
    assert len(skills) == 1
    assert skills[0].id == "good_one"


def test_skill_model_serialization():
    """Verify Skill and SkillMetadata serialization to dict and JSON."""
    parsed_meta = MultiToolSkillDiscovery.parse_frontmatter(
        "---\nname: Test Skill\nversion: 2.0.0\n---\nHello"
    )[0]
    assert parsed_meta["name"] == "Test Skill"
    from core.skills.models import Skill, SkillMetadata, SkillSource

    m = SkillMetadata(
        id="s1",
        name="Test",
        source_tool=SkillSource.CLAUDE_CODE,
        tags=["a", "b"],
    )
    s = Skill(id="s1", metadata=m, content="content")
    d = s.to_dict()
    assert d["id"] == "s1"
    assert d["metadata"]["source_tool"] == "claude-code"
    assert d["metadata"]["tags"] == ["a", "b"]
