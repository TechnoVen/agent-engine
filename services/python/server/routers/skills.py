"""services/python/server/routers/skills.py

Skills API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

# Core domain imports
from core.config import require_flag
from core.execution import (
    ExecutionCoordinator,
    ExecutionRequest,
    ExecutionStatus,
)
from core.skills import (
    MultiToolSkillDiscovery,
    RemoteSkillDiscoveryClient,
    SkillCollectionManager,
    SkillEditor,
    SkillFormat,
    SkillRegistryClient,
    SkillSource,
)
from core.templates import TemplateManager

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_execution_coordinator,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.skills")
router = APIRouter(tags=["skills"])


@router.get("/agents", response_model=List[AgentInfo])
async def list_agents():
    """List all registered and active agents."""
    return [
        AgentInfo(
            id="agent_code_sentry",
            name="Code Sentry Watcher",
            status="idle",
            project="default",
            current_task="Filesystem monitoring",
        ),
        AgentInfo(
            id="agent_fastmcp",
            name="FastMCP Tool Host",
            status="idle",
            project="default",
            current_task="Listening on stdio",
        ),
    ]


@router.get("/skills", response_model=List[SkillInfo])
async def list_skills(
    source: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    tag: Optional[str] = None,
):
    """List available skills and templates discovered across developer tools."""
    discovery = MultiToolSkillDiscovery()
    skills_map: Dict[str, SkillInfo] = {}

    try:
        discovered = discovery.discover_all()
        for s in discovered:
            skills_map[s.id] = SkillInfo(
                id=s.id,
                name=s.metadata.name,
                category=s.metadata.category,
                description=s.metadata.description,
                inputs=s.metadata.inputs,
                outputs=s.metadata.outputs,
                source=s.metadata.source_tool.value,
                author=s.metadata.author,
                version=s.metadata.version,
                tags=s.metadata.tags,
                tools=s.metadata.tools,
                format=s.format.value,
                file_path=s.path,
                content=s.content,
                is_readonly=s.is_readonly,
            )
    except Exception as e:
        logger.warning(f"Error during multi-tool skill discovery: {e}")

    try:
        templates = TemplateManager.list_templates()
        for t in templates:
            if t.id not in skills_map:
                in_fields = list(t.inputs.keys()) if isinstance(t.inputs, dict) else t.inputs
                out_fields = list(t.outputs.keys()) if isinstance(t.outputs, dict) else t.outputs
                skills_map[t.id] = SkillInfo(
                    id=t.id,
                    name=t.name,
                    category=t.category,
                    description=t.description,
                    inputs=in_fields,
                    outputs=out_fields,
                    source=SkillSource.AGENT_ENGINE.value,
                    author="agent-engine",
                    version="1.0.0",
                    tags=t.tags or [],
                    format="json",
                    content=t.to_json(),
                    is_readonly=True,
                )
    except Exception as e:
        logger.warning(f"Error loading template skills: {e}")

    results = list(skills_map.values())

    if source:
        results = [s for s in results if (s.source or "").lower() == source.lower()]
    if category:
        results = [s for s in results if (s.category or "").lower() == category.lower()]
    if tag:
        results = [s for s in results if tag.lower() in [t.lower() for t in s.tags]]
    if search:
        q = search.lower()
        results = [
            s
            for s in results
            if q in s.name.lower()
            or q in (s.description or "").lower()
            or any(q in t.lower() for t in s.tags)
            or q in (s.content or "").lower()
        ]

    return results


@router.post("/skills/validate", response_model=ValidateSkillResponse)
async def validate_skill_content(req: ValidateSkillRequest):
    """Validate raw skill markdown/frontmatter or JSON structure."""
    editor = SkillEditor()
    fmt = SkillFormat.JSON if req.format.lower() == "json" else SkillFormat.MARKDOWN
    res = editor.validate_content(req.content, format=fmt)
    return ValidateSkillResponse(
        valid=res.valid,
        errors=res.errors,
        warnings=res.warnings,
        parsed_metadata=res.parsed_metadata,
    )


@router.post("/skills/create", response_model=SkillInfo)
async def create_skill(req: CreateSkillRequest):
    """Create a new skill and write it to the canonical tool directory."""
    editor = SkillEditor()
    try:
        src = SkillSource(req.source)
    except Exception:
        src = SkillSource.AGENT_ENGINE

    fmt = SkillFormat.JSON if req.format.lower() == "json" else SkillFormat.MARKDOWN
    try:
        skill = editor.create_skill(
            source=src,
            name=req.name,
            description=req.description,
            content=req.content,
            skill_id=req.skill_id,
            author=req.author,
            version=req.version,
            tags=req.tags,
            inputs=req.inputs,
            outputs=req.outputs,
            tools=req.tools,
            format=fmt,
            extra={"category": req.category},
        )
        return SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source=skill.metadata.source_tool.value,
            author=skill.metadata.author,
            version=skill.metadata.version,
            tags=skill.metadata.tags,
            tools=skill.metadata.tools,
            format=skill.format.value,
            file_path=skill.path,
            content=skill.content,
            is_readonly=skill.is_readonly,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/skills/search", response_model=List[SkillSearchResult])
async def search_skills_endpoint(
    q: str = Query(default="", description="Search query string"),
    source: Optional[str] = Query(default=None, description="Filter by tool source"),
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
):
    """Full-text search across discovered skills with relevance scoring."""
    manager = SkillCollectionManager()
    src = None
    if source:
        try:
            src = SkillSource(source)
        except Exception:
            src = None

    results = manager.search_skills(query=q, source=src, tag=tag, category=category)
    response_items = []
    for skill, score in results:
        info = SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source=skill.metadata.source_tool.value,
            author=skill.metadata.author,
            version=skill.metadata.version,
            tags=skill.metadata.tags,
            tools=skill.metadata.tools,
            format=skill.format.value,
            file_path=skill.path,
            content=skill.content,
            is_readonly=skill.is_readonly,
        )
        response_items.append(SkillSearchResult(skill=info, score=score))
    return response_items


@router.get("/skills/collections", response_model=List[SkillCollectionInfo])
async def list_skill_collections(tag: Optional[str] = None):
    """List all user and curated skill collections."""
    manager = SkillCollectionManager()
    colls = manager.list_collections(tag=tag)
    return [
        SkillCollectionInfo(
            id=c.id,
            name=c.name,
            description=c.description,
            tags=c.tags,
            skill_ids=c.skill_ids,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in colls
    ]


@router.post("/skills/collections", response_model=SkillCollectionInfo)
async def create_skill_collection(req: CreateSkillCollectionRequest):
    """Create a new skill collection."""
    manager = SkillCollectionManager()
    try:
        c = manager.create_collection(
            name=req.name,
            description=req.description,
            tags=req.tags,
            skill_ids=req.skill_ids,
            collection_id=req.collection_id,
        )
        return SkillCollectionInfo(
            id=c.id,
            name=c.name,
            description=c.description,
            tags=c.tags,
            skill_ids=c.skill_ids,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/skills/collections/{collection_id}", response_model=SkillCollectionInfo)
async def get_skill_collection(collection_id: str):
    """Get a specific skill collection."""
    manager = SkillCollectionManager()
    c = manager.get_collection(collection_id)
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found.",
        )
    return SkillCollectionInfo(
        id=c.id,
        name=c.name,
        description=c.description,
        tags=c.tags,
        skill_ids=c.skill_ids,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.put("/skills/collections/{collection_id}", response_model=SkillCollectionInfo)
async def update_skill_collection(collection_id: str, req: UpdateSkillCollectionRequest):
    """Update metadata of a skill collection."""
    manager = SkillCollectionManager()
    try:
        c = manager.update_collection(
            collection_id=collection_id,
            name=req.name,
            description=req.description,
            tags=req.tags,
        )
        return SkillCollectionInfo(
            id=c.id,
            name=c.name,
            description=c.description,
            tags=c.tags,
            skill_ids=c.skill_ids,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/skills/collections/{collection_id}")
async def delete_skill_collection(collection_id: str):
    """Delete a skill collection."""
    manager = SkillCollectionManager()
    deleted = manager.delete_collection(collection_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found.",
        )
    return {"success": True, "collection_id": collection_id}


@router.get("/skills/collections/{collection_id}/skills", response_model=List[SkillInfo])
async def get_collection_member_skills(collection_id: str):
    """Retrieve full SkillInfo entities for all members of a collection."""
    manager = SkillCollectionManager()
    try:
        skills = manager.get_collection_skills(collection_id)
        return [
            SkillInfo(
                id=s.id,
                name=s.metadata.name,
                category=s.metadata.category,
                description=s.metadata.description,
                inputs=s.metadata.inputs,
                outputs=s.metadata.outputs,
                source=s.metadata.source_tool.value,
                author=s.metadata.author,
                version=s.metadata.version,
                tags=s.metadata.tags,
                tools=s.metadata.tools,
                format=s.format.value,
                file_path=s.path,
                content=s.content,
                is_readonly=s.is_readonly,
            )
            for s in skills
        ]
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/skills/collections/{collection_id}/skills")
async def add_skill_to_collection_endpoint(collection_id: str, req: AddSkillToCollectionRequest):
    """Add a skill to a collection."""
    manager = SkillCollectionManager()
    try:
        manager.add_skill_to_collection(collection_id, req.skill_id)
        return {"success": True, "collection_id": collection_id, "skill_id": req.skill_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/skills/collections/{collection_id}/skills/{skill_id}")
async def remove_skill_from_collection_endpoint(collection_id: str, skill_id: str):
    """Remove a skill from a collection."""
    manager = SkillCollectionManager()
    try:
        removed = manager.remove_skill_from_collection(collection_id, skill_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' not found in collection '{collection_id}'.",
            )
        return {"success": True, "collection_id": collection_id, "skill_id": skill_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/skills/registry",
    response_model=List[SkillRegistryPackageInfo],
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def list_registry_packages(
    query: Optional[str] = Query(default=None, description="Filter by text"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
):
    """List available community and verified packages in the skill registry."""
    client = SkillRegistryClient()
    pkgs = client.list_packages(query=query, category=category, tag=tag)
    return [
        SkillRegistryPackageInfo(
            id=p.id,
            name=p.name,
            version=p.version,
            description=p.description,
            author=p.author,
            tags=p.tags,
            category=p.category,
            sha256=p.sha256,
            verified=p.verified,
            installs=p.installs,
            is_installed=p.is_installed,
            installed_path=p.installed_path,
        )
        for p in pkgs
    ]


@router.post(
    "/skills/registry/install",
    response_model=SkillRegistryPackageInfo,
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def install_registry_package(req: InstallSkillPackageRequest):
    """Install a skill package from registry with hash verification and security scan."""
    client = SkillRegistryClient()
    try:
        pkg = client.install_package(req.package_id, force=req.force)
        return SkillRegistryPackageInfo(
            id=pkg.id,
            name=pkg.name,
            version=pkg.version,
            description=pkg.description,
            author=pkg.author,
            tags=pkg.tags,
            category=pkg.category,
            sha256=pkg.sha256,
            verified=pkg.verified,
            installs=pkg.installs,
            is_installed=pkg.is_installed,
            installed_path=pkg.installed_path,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/skills/registry/uninstall",
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def uninstall_registry_package(req: UninstallSkillPackageRequest):
    """Uninstall a package previously installed from the registry."""
    client = SkillRegistryClient()
    try:
        success = client.uninstall_package(req.package_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Package '{req.package_id}' is not currently installed.",
            )
        return {"success": True, "package_id": req.package_id}
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/skills/remote/discover",
    response_model=List[SkillInfo],
)
async def discover_remote_skills(req: RemoteSkillDiscoverRequest):
    """Discover available skills on a remote Agent Engine instance or manifest."""
    client = RemoteSkillDiscoveryClient()
    try:
        remote_items = client.discover_remote(req.endpoint_url, api_token=req.api_token)
        return [
            SkillInfo(
                id=item["id"],
                name=item["name"],
                category=item.get("category", "Remote"),
                description=item.get("description", ""),
                inputs=item.get("inputs", []),
                outputs=item.get("outputs", []),
                source_tool=item.get("source_tool", "agent-engine"),
                version=item.get("version", "1.0.0"),
                author=item.get("author", "remote"),
                tags=item.get("tags", []),
                content=item.get("content", ""),
            )
            for item in remote_items
        ]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/skills/remote/import",
    response_model=SkillInfo,
)
async def import_remote_skill(req: RemoteSkillImportRequest):
    """Fetch remote skill, validate safety scan and schema, and persist locally."""
    client = RemoteSkillDiscoveryClient()
    try:
        try:
            source = SkillSource(req.target_tool) if req.target_tool else SkillSource.AGENT_ENGINE
        except ValueError:
            source = SkillSource.AGENT_ENGINE

        skill = client.import_remote_skill(
            endpoint_url=req.endpoint_url,
            skill_id=req.skill_id,
            api_token=req.api_token,
            target_tool=source,
            force=req.force,
        )
        return SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source_tool=skill.metadata.source_tool.value,
            version=skill.metadata.version,
            author=skill.metadata.author,
            tags=skill.metadata.tags,
            content=skill.content,
            path=str(skill.path.resolve()) if skill.path else None,
            is_readonly=skill.is_readonly,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/skills/{skill_id}", response_model=SkillInfo)
async def get_skill(skill_id: str):
    """Get full details and raw content of a specific skill."""
    editor = SkillEditor()
    skill = editor.get_skill(skill_id)
    if skill:
        return SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source=skill.metadata.source_tool.value,
            author=skill.metadata.author,
            version=skill.metadata.version,
            tags=skill.metadata.tags,
            tools=skill.metadata.tools,
            format=skill.format.value,
            file_path=skill.path,
            content=skill.content,
            is_readonly=skill.is_readonly,
        )

    template = TemplateManager.get_template(skill_id)
    if template:
        in_fields = (
            list(template.inputs.keys()) if isinstance(template.inputs, dict) else template.inputs
        )
        out_fields = (
            list(template.outputs.keys())
            if isinstance(template.outputs, dict)
            else template.outputs
        )
        return SkillInfo(
            id=template.id,
            name=template.name,
            category=template.category,
            description=template.description,
            inputs=in_fields,
            outputs=out_fields,
            source=SkillSource.AGENT_ENGINE.value,
            author="agent-engine",
            version="1.0.0",
            tags=template.tags or [],
            format="json",
            content=template.to_json(),
            is_readonly=True,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Skill '{skill_id}' not found.",
    )


@router.put("/skills/{skill_id}", response_model=SkillInfo)
async def update_skill(skill_id: str, req: UpdateSkillRequest):
    """Update an existing skill in place."""
    editor = SkillEditor()
    meta_updates = {}
    if req.name is not None:
        meta_updates["name"] = req.name
    if req.description is not None:
        meta_updates["description"] = req.description
    if req.version is not None:
        meta_updates["version"] = req.version
    if req.tags is not None:
        meta_updates["tags"] = req.tags
    if req.inputs is not None:
        meta_updates["inputs"] = req.inputs
    if req.outputs is not None:
        meta_updates["outputs"] = req.outputs
    if req.tools is not None:
        meta_updates["tools"] = req.tools
    if req.category is not None:
        meta_updates["category"] = req.category

    try:
        updated = editor.update_skill(
            skill_id=skill_id,
            content=req.content,
            metadata_updates=meta_updates or None,
        )
        return SkillInfo(
            id=updated.id,
            name=updated.metadata.name,
            category=updated.metadata.category,
            description=updated.metadata.description,
            inputs=updated.metadata.inputs,
            outputs=updated.metadata.outputs,
            source=updated.metadata.source_tool.value,
            author=updated.metadata.author,
            version=updated.metadata.version,
            tags=updated.metadata.tags,
            tools=updated.metadata.tools,
            format=updated.format.value,
            file_path=updated.path,
            content=updated.content,
            is_readonly=updated.is_readonly,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete an editable skill file."""
    editor = SkillEditor()
    try:
        deleted = editor.delete_skill(skill_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' not found.",
            )
        return {"success": True, "skill_id": skill_id}
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/skills", response_model=ExecuteSkillResponse)
async def execute_skill(
    req: ExecuteSkillRequest,
    x_project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Execute a pre-built OpenClaw skill template by its ID via the canonical ExecutionCoordinator."""
    resolved_item, _ = coordinator._resolve_skill(req.skill_id)
    template = TemplateManager.get_template(req.skill_id)
    if not resolved_item and not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill template '{req.skill_id}' not found.",
        )

    payload = req.payload or (template.sample_inputs if template else {}) or {}
    effective_project_id = (
        (payload.get("project_id") if isinstance(payload, dict) else None)
        or x_project_id
        or "default"
    )

    clean_payload = dict(payload) if isinstance(payload, dict) else {}
    exec_req = ExecutionRequest(
        task_type="skill",
        prompt=str(clean_payload.get("prompt") or f"Execute skill {req.skill_id}"),
        inputs={
            "skill_id": req.skill_id,
            "payload": clean_payload,
            **clean_payload,
        },
        project_id=effective_project_id,
        session_id=clean_payload.get("session_id"),
    )

    try:
        result = await coordinator.execute(exec_req)
        if result.status == ExecutionStatus.BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Execution of skill '{req.skill_id}' blocked: {result.error}",
            )
        if result.status == ExecutionStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Execution of skill '{req.skill_id}' cancelled: {result.error}",
            )
        if result.status == ExecutionStatus.FAILED:
            if "not found" in str(result.error).lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill template '{req.skill_id}' not found.",
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Execution of skill '{req.skill_id}' failed: {result.error}",
            )
        pred_dict = result.outputs.get("results")
        if pred_dict is None:
            pred_dict = result.outputs
        return ExecuteSkillResponse(skill_id=req.skill_id, results=pred_dict)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution of skill '{req.skill_id}' failed: {e}",
        )
