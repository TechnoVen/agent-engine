"""tests/test_skills.py

Unit and integration tests for Skill Management Subsystem (Phase 6 - Milestone M4).
Covers:
- Task 6.1: Multi-Tool Skill Discovery (Claude Code, Cursor, Codex, Goose, Agent Engine)
"""

from pathlib import Path
import time

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


def test_skill_editor_validation_markdown():
    """Verify SkillEditor Markdown/YAML frontmatter validator."""
    from core.skills.editor import SkillEditor
    from core.skills.models import SkillFormat

    editor = SkillEditor()

    # Valid markdown with frontmatter
    valid_md = """---
name: Valid Skill
description: A well-formed skill for testing
version: 1.2.0
author: tester
tags: [unit, test]
inputs: [query]
outputs: [response]
---

You are a helpful test assistant.
"""
    res = editor.validate_content(valid_md, format=SkillFormat.MARKDOWN)
    assert res.valid is True
    assert len(res.errors) == 0
    assert res.parsed_metadata is not None
    assert res.parsed_metadata["name"] == "Valid Skill"

    # Empty content
    res_empty = editor.validate_content("   ", format=SkillFormat.MARKDOWN)
    assert res_empty.valid is False
    assert any("empty" in e.lower() for e in res_empty.errors)

    # Missing name in frontmatter
    invalid_md = """---
description: No name here
inputs: [query]
---

Body instructions.
"""
    res_noname = editor.validate_content(invalid_md, format=SkillFormat.MARKDOWN)
    assert res_noname.valid is False
    assert any("name" in e.lower() for e in res_noname.errors)

    # Malformed YAML
    bad_yaml = """---
name: Broken
description: [unclosed list
---
"""
    res_bad = editor.validate_content(bad_yaml, format=SkillFormat.MARKDOWN)
    assert res_bad.valid is False
    assert any("yaml" in e.lower() for e in res_bad.errors)


def test_skill_editor_validation_json():
    """Verify SkillEditor JSON validator."""
    from core.skills.editor import SkillEditor
    from core.skills.models import SkillFormat

    editor = SkillEditor()

    # Valid JSON
    valid_json = (
        '{"name": "JSON Skill", "description": "Desc", "inputs": ["text"], "outputs": ["result"]}'
    )
    res = editor.validate_content(valid_json, format=SkillFormat.JSON)
    assert res.valid is True
    assert len(res.errors) == 0

    # Malformed JSON syntax
    res_bad = editor.validate_content('{"name": unquoted}', format=SkillFormat.JSON)
    assert res_bad.valid is False
    assert any("syntax" in e.lower() for e in res_bad.errors)


def test_skill_editor_crud_lifecycle(tmp_path):
    """Verify complete CRUD lifecycle via SkillEditor with atomic writing."""
    from core.skills.discovery import MultiToolSkillDiscovery
    from core.skills.editor import SkillEditor
    from core.skills.models import SkillSource

    ws = tmp_path / "workspace"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    discovery = MultiToolSkillDiscovery(
        agent_engine_dirs=[ws / "data" / "skills"],
        cursor_dirs=[ws / ".cursor" / "rules"],
    )
    editor = SkillEditor(workspace_root=ws, home_dir=home, discovery=discovery)

    # 1. Create skill (agent-engine markdown)
    skill = editor.create_skill(
        source=SkillSource.AGENT_ENGINE,
        name="Unit Testing Skill",
        description="A skill created by automated tests",
        content="Execute tests and report coverage.",
        author="pytest",
        version="1.0.0",
        tags=["ci", "testing"],
        inputs=["code"],
        outputs=["report"],
    )
    assert skill.id == "unit_testing_skill"
    assert skill.path is not None
    assert Path(skill.path).exists()
    assert "Execute tests and report coverage." in skill.content

    # Duplicate creation raises FileExistsError
    import pytest

    with pytest.raises(FileExistsError):
        editor.create_skill(
            source=SkillSource.AGENT_ENGINE,
            name="Unit Testing Skill",
            description="Duplicate",
            content="Duplicate",
        )

    # 2. Read / Get skill
    fetched = editor.get_skill("unit_testing_skill")
    assert fetched is not None
    assert fetched.id == "unit_testing_skill"
    assert fetched.metadata.name == "Unit Testing Skill"
    assert fetched.metadata.tags == ["ci", "testing"]

    # 3. Update skill
    updated = editor.update_skill(
        skill_id="unit_testing_skill",
        content="New instructions: run with verbose output.",
        metadata_updates={"version": "1.1.0", "description": "Updated description"},
    )
    assert updated.metadata.version == "1.1.0"
    assert updated.metadata.description == "Updated description"
    assert "verbose output" in updated.content

    # 4. Delete skill
    deleted = editor.delete_skill("unit_testing_skill")
    assert deleted is True
    assert not Path(skill.path).exists()
    assert editor.get_skill("unit_testing_skill") is None


def test_skill_editor_tool_targets(tmp_path):
    """Verify tool-specific target directory routing."""
    from core.skills.editor import SkillEditor
    from core.skills.models import SkillSource

    ws = tmp_path / "ws"
    home = tmp_path / "home"
    editor = SkillEditor(workspace_root=ws, home_dir=home)

    assert editor.get_tool_target_dir(SkillSource.AGENT_ENGINE) == ws / "data" / "skills"
    assert editor.get_tool_target_dir(SkillSource.CLAUDE_CODE) == home / ".claude" / "commands"
    assert editor.get_tool_target_dir(SkillSource.CURSOR) == ws / ".cursor" / "rules"
    assert editor.get_tool_target_dir(SkillSource.CODEX) == ws / ".codex" / "skills"
    assert editor.get_tool_target_dir(SkillSource.GOOSE) == home / ".config" / "goose" / "skills"


def test_skill_editor_api_endpoints():
    """Verify Skill Editor FastAPI endpoints: validate, create, get, update, delete."""
    from fastapi.testclient import TestClient
    from services.python.server.api import app

    client = TestClient(app)

    # 1. POST /v1/skills/validate
    val_resp = client.post(
        "/v1/skills/validate",
        json={
            "content": "---\nname: Test Valid\ndescription: OK\n---\nHello",
            "format": "markdown",
        },
    )
    assert val_resp.status_code == 200
    assert val_resp.json()["valid"] is True

    val_bad = client.post(
        "/v1/skills/validate",
        json={"content": "   ", "format": "markdown"},
    )
    assert val_bad.status_code == 200
    assert val_bad.json()["valid"] is False

    # 2. GET /v1/skills
    list_resp = client.get("/v1/skills")
    assert list_resp.status_code == 200
    skills = list_resp.json()
    assert isinstance(skills, list)
    assert len(skills) >= 1

    # 3. GET /v1/skills/{skill_id} for prebuilt template
    prebuilt_resp = client.get("/v1/skills/summarize_meeting_notes")
    assert prebuilt_resp.status_code == 200
    pb_data = prebuilt_resp.json()
    assert pb_data["id"] == "summarize_meeting_notes"
    assert pb_data["is_readonly"] is True

    # 4. POST /v1/skills/create
    unique_id = f"api_test_skill_{int(time.time() * 1000)}"
    create_resp = client.post(
        "/v1/skills/create",
        json={
            "skill_id": unique_id,
            "name": "API Created Skill",
            "description": "Created via REST API test",
            "content": "Follow instructions carefully.",
            "source": "agent-engine",
            "tags": ["api", "test"],
        },
    )
    assert create_resp.status_code == 200
    c_data = create_resp.json()
    assert c_data["id"] == unique_id
    assert c_data["name"] == "API Created Skill"

    # 5. GET /v1/skills/{skill_id}
    fetch_resp = client.get(f"/v1/skills/{unique_id}")
    assert fetch_resp.status_code == 200
    assert fetch_resp.json()["id"] == unique_id

    # 6. PUT /v1/skills/{skill_id}
    put_resp = client.put(
        f"/v1/skills/{unique_id}",
        json={"content": "Updated content from API.", "description": "New description"},
    )
    assert put_resp.status_code == 200
    assert "Updated content from API." in put_resp.json()["content"]
    assert put_resp.json()["description"] == "New description"

    # 7. DELETE /v1/skills/{skill_id}
    del_resp = client.delete(f"/v1/skills/{unique_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Confirm 404 after deletion
    assert client.get(f"/v1/skills/{unique_id}").status_code == 404


def test_skill_collection_manager_crud(tmp_path):
    """Verify SkillCollectionManager CRUD and tag filtering."""
    from core.skills.collections import SkillCollectionManager

    db_file = str(tmp_path / "test_skills.db")
    mgr = SkillCollectionManager(db_path=db_file)

    # 1. Create collection
    coll = mgr.create_collection(
        name="Data Science Toolkit",
        description="Core skills for data analysis and ML",
        tags=["python", "data", "ml"],
        skill_ids=["sql_gen", "chart_builder"],
        collection_id="ds_toolkit",
    )
    assert coll.id == "ds_toolkit"
    assert coll.name == "Data Science Toolkit"
    assert coll.tags == ["python", "data", "ml"]
    assert "sql_gen" in coll.skill_ids

    # 2. Get collection
    fetched = mgr.get_collection("ds_toolkit")
    assert fetched is not None
    assert fetched.name == "Data Science Toolkit"
    assert len(fetched.skill_ids) == 2

    # 3. List collections with tag filter
    all_colls = mgr.list_collections()
    assert len(all_colls) == 1

    ml_colls = mgr.list_collections(tag="ml")
    assert len(ml_colls) == 1

    web_colls = mgr.list_collections(tag="frontend")
    assert len(web_colls) == 0

    # 4. Update collection
    updated = mgr.update_collection(
        "ds_toolkit",
        name="Advanced Data Science Toolkit",
        description="Updated description",
        tags=["python", "ai"],
    )
    assert updated.name == "Advanced Data Science Toolkit"
    assert updated.tags == ["python", "ai"]

    # 5. Delete collection
    assert mgr.delete_collection("ds_toolkit") is True
    assert mgr.get_collection("ds_toolkit") is None


def test_skill_collection_member_skills(tmp_path):
    """Verify adding, removing, and resolving member skills in collections."""
    from core.skills.collections import SkillCollectionManager
    from core.skills.discovery import MultiToolSkillDiscovery
    from core.skills.models import Skill, SkillMetadata, SkillSource

    db_file = str(tmp_path / "members.db")

    # Mock discovery
    discovery = MultiToolSkillDiscovery(agent_engine_dirs=[])
    m1 = SkillMetadata(id="skill_a", name="Skill Alpha", source_tool=SkillSource.AGENT_ENGINE)
    m2 = SkillMetadata(id="skill_b", name="Skill Beta", source_tool=SkillSource.CURSOR)
    discovery.discover_all = lambda workspace_dir=None: [  # type: ignore
        Skill(id="skill_a", metadata=m1, content="alpha"),
        Skill(id="skill_b", metadata=m2, content="beta"),
    ]
    discovery.get_skill = lambda s_id, workspace_dir=None: next(  # type: ignore
        (s for s in discovery.discover_all() if s.id == s_id), None
    )

    mgr = SkillCollectionManager(db_path=db_file, discovery=discovery)
    mgr.create_collection(name="Bundle 1", collection_id="b1")

    # Add skills
    assert mgr.add_skill_to_collection("b1", "skill_a") is True
    assert mgr.add_skill_to_collection("b1", "skill_b") is True

    coll = mgr.get_collection("b1")
    assert len(coll.skill_ids) == 2

    # Resolve member skills
    skills = mgr.get_collection_skills("b1")
    assert len(skills) == 2
    assert {s.id for s in skills} == {"skill_a", "skill_b"}

    # Remove a skill
    assert mgr.remove_skill_from_collection("b1", "skill_a") is True
    remaining = mgr.get_collection_skills("b1")
    assert len(remaining) == 1
    assert remaining[0].id == "skill_b"


def test_skill_search_scoring():
    """Verify search scoring and ranking algorithm."""
    from core.skills.collections import SkillCollectionManager
    from core.skills.discovery import MultiToolSkillDiscovery
    from core.skills.models import Skill, SkillMetadata

    # Create distinct skills for testing
    m_exact = SkillMetadata(
        id="deploy_docker", name="Deploy Docker Container", tags=["docker", "devops"]
    )
    m_fuzzy = SkillMetadata(
        id="kubernetes_orchestrator",
        name="K8s Orchestrator",
        tags=["devops"],
        description="Deploys to cluster",
    )
    m_other = SkillMetadata(id="generate_sql", name="Generate SQL", tags=["data"])

    discovery = MultiToolSkillDiscovery(agent_engine_dirs=[])
    discovery.discover_all = lambda workspace_dir=None: [  # type: ignore
        Skill(id="deploy_docker", metadata=m_exact, content="run docker build and push"),
        Skill(
            id="kubernetes_orchestrator", metadata=m_fuzzy, content="manage pods and deployments"
        ),
        Skill(id="generate_sql", metadata=m_other, content="select * from table"),
    ]

    mgr = SkillCollectionManager(db_path=":memory:", discovery=discovery)

    # Exact ID search
    res1 = mgr.search_skills("deploy_docker")
    assert len(res1) >= 1
    assert res1[0][0].id == "deploy_docker"
    assert res1[0][1] >= 100.0

    # Token match in name/tags/content
    res2 = mgr.search_skills("docker")
    assert len(res2) >= 1
    assert res2[0][0].id == "deploy_docker"

    # Tag filter search
    res3 = mgr.search_skills("", tag="devops")
    assert len(res3) == 2
    ids = {s.id for s, _ in res3}
    assert "deploy_docker" in ids
    assert "kubernetes_orchestrator" in ids


def test_skill_collection_api_endpoints():
    """Verify Collection REST endpoints."""
    from fastapi.testclient import TestClient
    from services.python.server.api import app

    client = TestClient(app)

    unique_coll_id = f"coll_api_{int(time.time() * 1000)}"

    # 1. POST /v1/skills/collections
    create_resp = client.post(
        "/v1/skills/collections",
        json={
            "collection_id": unique_coll_id,
            "name": "Integration Collection",
            "description": "Created during API test",
            "tags": ["test", "api"],
            "skill_ids": ["summarize_meeting_notes"],
        },
    )
    assert create_resp.status_code == 200
    c_data = create_resp.json()
    assert c_data["id"] == unique_coll_id
    assert "summarize_meeting_notes" in c_data["skill_ids"]

    # 2. GET /v1/skills/collections
    list_resp = client.get("/v1/skills/collections")
    assert list_resp.status_code == 200
    all_colls = list_resp.json()
    assert any(c["id"] == unique_coll_id for c in all_colls)

    # 3. GET /v1/skills/collections/{id}
    get_resp = client.get(f"/v1/skills/collections/{unique_coll_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Integration Collection"

    # 4. PUT /v1/skills/collections/{id}
    put_resp = client.put(
        f"/v1/skills/collections/{unique_coll_id}",
        json={"name": "Renamed Collection", "description": "Updated"},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["name"] == "Renamed Collection"

    # 5. GET /v1/skills/collections/{id}/skills
    skills_resp = client.get(f"/v1/skills/collections/{unique_coll_id}/skills")
    assert skills_resp.status_code == 200
    member_skills = skills_resp.json()
    assert len(member_skills) >= 1
    assert any(s["id"] == "summarize_meeting_notes" for s in member_skills)

    # 6. DELETE /v1/skills/collections/{id}/skills/{skill_id}
    rem_resp = client.delete(
        f"/v1/skills/collections/{unique_coll_id}/skills/summarize_meeting_notes"
    )
    assert rem_resp.status_code == 200
    assert rem_resp.json()["success"] is True

    # 7. DELETE /v1/skills/collections/{id}
    del_resp = client.delete(f"/v1/skills/collections/{unique_coll_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Confirm 404
    assert client.get(f"/v1/skills/collections/{unique_coll_id}").status_code == 404


def test_skill_search_api_endpoint():
    """Verify GET /v1/skills/search endpoint."""
    from fastapi.testclient import TestClient
    from services.python.server.api import app

    client = TestClient(app)

    # Search for "meeting" which matches summarize_meeting_notes
    resp = client.get("/v1/skills/search?q=meeting")
    assert resp.status_code == 200
    results = resp.json()
    assert isinstance(results, list)
    assert len(results) >= 1
    top = results[0]
    assert "skill" in top
    assert "score" in top
    assert top["score"] > 0
    assert "meeting" in top["skill"]["name"].lower() or "meeting" in top["skill"]["id"].lower()
