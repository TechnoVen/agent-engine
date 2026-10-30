"""core/skills/registry.py

Skill Registry Integration Service for Agent Engine.
Part of Phase 6 (Task 6.4 - Milestone M4).

Features:
- ADR-007 gating via `enable_registry` flag check.
- ADR-013 compliant: zero non-free dependencies, 100% open-source local-first execution.
- Curated & community skill catalog with SHA-256 integrity verification.
- Static security verification scanning for malicious shell execution and destructive patterns.
- Fast package installation (<10s) and clean uninstallation.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from core.config import is_flag_enabled
from core.skills.discovery import PROJECT_ROOT
from core.skills.models import SkillSource

logger = logging.getLogger("agent_engine.skills.registry")

DEFAULT_REGISTRY_DIR = PROJECT_ROOT / "data" / "skills" / "registry"

# Security scanning patterns against hostile instructions
DANGEROUS_PATTERNS = [
    (r"\brm\s+-(?:r|f|rf|fr)\s+/(?:\s|$)", "Destructive root filesystem deletion"),
    (r"\bmkfs\b", "Filesystem format instruction"),
    (r"\bdd\s+if=/dev/(?:zero|urandom)\s+of=/dev/", "Raw device disk overwriting"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "Forkbomb denial of service"),
    (r"\b(?:nc|netcat)\s+-[e|c]\s+/bin/(?:sh|bash)", "Reverse shell netcat execution"),
    (r"/dev/tcp/\d+\.\d+\.\d+\.\d+/\d+", "Direct /dev/tcp socket redirection"),
    (r"\bcurl\b.*\|\s*(?:bash|sh)\b", "Piped remote script download and direct execution"),
    (r"\bwget\b.*\|\s*(?:bash|sh)\b", "Piped remote script download and direct execution"),
]


def scan_content_safety(content: str) -> Tuple[bool, Optional[str]]:
    """Scan raw skill markdown or code for known hostile or destructive patterns."""
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return False, description
    return True, None


class SkillRegistryPackage(BaseModel):
    """Metadata and payload for a package available in the skill registry."""

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "Agent Engine Core"
    tags: List[str] = Field(default_factory=list)
    category: str = "General"
    sha256: str = ""
    verified: bool = True
    installs: int = 0
    content: str = ""
    source: SkillSource = SkillSource.REGISTRY
    is_installed: bool = False
    installed_path: Optional[str] = None


def _build_default_catalog() -> List[SkillRegistryPackage]:
    """Generate default curated, verified skills."""
    catalog = [
        {
            "id": "git_commit_generator",
            "name": "Git Conventional Committer",
            "version": "1.2.0",
            "description": "Analyzes staged git diff and writes conventional commit messages.",
            "category": "Engineering",
            "tags": ["git", "vcs", "automation"],
            "author": "Agent Engine Core",
            "content": """---
name: Git Conventional Committer
description: Analyzes staged git diff and writes conventional commit messages.
version: 1.2.0
author: Agent Engine Core
tags: [git, vcs, automation]
source_tool: registry
---

# Instructions
1. Inspect the staged diff using git diff --staged.
2. Group changes into logical concerns (feat, fix, docs, refactor, test, chore).
3. Author a concise conventional commit summary under 72 characters.
""",
        },
        {
            "id": "fastapi_endpoint_scaffold",
            "name": "FastAPI Endpoint Scaffolder",
            "version": "1.0.1",
            "description": "Generates production-ready FastAPI route handlers and Pydantic schemas.",
            "category": "Engineering",
            "tags": ["python", "fastapi", "rest"],
            "author": "Agent Engine Core",
            "content": """---
name: FastAPI Endpoint Scaffolder
description: Generates production-ready FastAPI route handlers and Pydantic schemas.
version: 1.0.1
author: Agent Engine Core
tags: [python, fastapi, rest]
source_tool: registry
---

# Instructions
1. Define request and response Pydantic models.
2. Structure APIRouter route with dependency injection and error handling.
3. Include typing, docstrings, and status codes.
""",
        },
        {
            "id": "python_security_audit",
            "name": "Python Security Auditor",
            "version": "1.1.0",
            "description": "Scans code for common OWASP vulnerabilities and insecure deserialization.",
            "category": "Security",
            "tags": ["security", "python", "audit"],
            "author": "Security Team",
            "content": """---
name: Python Security Auditor
description: Scans code for common OWASP vulnerabilities and insecure deserialization.
version: 1.1.0
author: Security Team
tags: [security, python, audit]
source_tool: registry
---

# Instructions
1. Check for unsafe subprocess/eval/pickle calls.
2. Check for SQL injection in raw query strings.
3. Suggest secure alternatives using parameterized queries.
""",
        },
        {
            "id": "sql_query_optimizer",
            "name": "SQL Query Optimizer",
            "version": "1.0.0",
            "description": "Analyzes SQL query execution plans and suggests missing indexes.",
            "category": "Data",
            "tags": ["sql", "database", "performance"],
            "author": "Data Engineering",
            "content": """---
name: SQL Query Optimizer
description: Analyzes SQL query execution plans and suggests missing indexes.
version: 1.0.0
author: Data Engineering
tags: [sql, database, performance]
source_tool: registry
---

# Instructions
1. Parse query predicates and join clauses.
2. Recommend compound or single-column indexes.
3. Identify redundant subqueries and window function optimizations.
""",
        },
    ]

    packages: List[SkillRegistryPackage] = []
    for item in catalog:
        c = item["content"].strip()
        h = hashlib.sha256(c.encode("utf-8")).hexdigest()
        packages.append(
            SkillRegistryPackage(
                id=item["id"],
                name=item["name"],
                version=item["version"],
                description=item["description"],
                category=item["category"],
                tags=item["tags"],
                author=item["author"],
                sha256=h,
                verified=True,
                installs=42,
                content=c,
            )
        )
    return packages


class SkillRegistryClient:
    """Client for querying, verifying, installing, and uninstalling skills from the registry."""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        registry_dir: Optional[Path] = None,
        custom_packages: Optional[List[SkillRegistryPackage]] = None,
    ):
        self.workspace_root = (workspace_root or PROJECT_ROOT).resolve()
        self.registry_dir = (
            registry_dir or (self.workspace_root / "data" / "skills" / "registry")
        ).resolve()
        self._catalog: Dict[str, SkillRegistryPackage] = {}

        packages = custom_packages if custom_packages is not None else _build_default_catalog()
        for p in packages:
            self._catalog[p.id] = p.model_copy()

    def _ensure_registry_enabled(self) -> None:
        """Enforce ADR-007: Registry feature flag must be enabled."""
        if not is_flag_enabled("enable_registry"):
            raise PermissionError("Registry is disabled by policy (ADR-007)")

    def _is_package_installed(self, package_id: str) -> Tuple[bool, Optional[str]]:
        """Check whether the package exists in the registry directory."""
        if not self.registry_dir.exists():
            return False, None
        for ext in (".md", ".json", ".mdc"):
            cand = self.registry_dir / f"{package_id}{ext}"
            if cand.exists():
                return True, str(cand.resolve())
        return False, None

    def list_packages(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[SkillRegistryPackage]:
        """List all packages in the registry, decorated with their installation status."""
        self._ensure_registry_enabled()

        results: List[SkillRegistryPackage] = []
        for pkg in self._catalog.values():
            installed, path = self._is_package_installed(pkg.id)
            item = pkg.model_copy(update={"is_installed": installed, "installed_path": path})

            if category and item.category.lower() != category.lower():
                continue
            if tag and tag.lower() not in [t.lower() for t in item.tags]:
                continue
            if query:
                q = query.lower()
                if (
                    q not in item.name.lower()
                    and q not in item.description.lower()
                    and not any(q in t.lower() for t in item.tags)
                ):
                    continue

            results.append(item)

        results.sort(key=lambda p: p.name)
        return results

    def get_package(self, package_id: str) -> Optional[SkillRegistryPackage]:
        """Get details for a specific package including local installation status."""
        self._ensure_registry_enabled()
        pkg = self._catalog.get(package_id)
        if not pkg:
            return None
        installed, path = self._is_package_installed(pkg.id)
        return pkg.model_copy(update={"is_installed": installed, "installed_path": path})

    def install_package(self, package_id: str, force: bool = False) -> SkillRegistryPackage:
        """Verify checksum, run security scan, and install package to registry directory (<10s)."""
        self._ensure_registry_enabled()

        pkg = self._catalog.get(package_id)
        if not pkg:
            raise FileNotFoundError(f"Package '{package_id}' not found in registry.")

        installed, path = self._is_package_installed(package_id)
        if installed and not force:
            return pkg.model_copy(update={"is_installed": True, "installed_path": path})

        # 1. Checksum validation
        content_bytes = pkg.content.strip().encode("utf-8")
        computed_hash = hashlib.sha256(content_bytes).hexdigest()
        if pkg.sha256 and computed_hash != pkg.sha256:
            raise ValueError(
                f"Checksum mismatch for '{package_id}': expected {pkg.sha256}, got {computed_hash}"
            )

        # 2. Security scan
        is_safe, threat = scan_content_safety(pkg.content)
        if not is_safe:
            raise ValueError(f"Security validation failed for '{package_id}': {threat}")

        # 3. Fast atomic write
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.registry_dir / f"{package_id}.md"

        temp_fd, temp_file_path = tempfile.mkstemp(
            dir=str(self.registry_dir),
            prefix=".tmp_pkg_",
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(pkg.content.strip() + "\n")
            os.replace(temp_file_path, target_path)
        except Exception:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            raise

        pkg.installs += 1
        return pkg.model_copy(
            update={"is_installed": True, "installed_path": str(target_path.resolve())}
        )

    def uninstall_package(self, package_id: str) -> bool:
        """Remove an installed registry skill from disk."""
        self._ensure_registry_enabled()

        installed, path = self._is_package_installed(package_id)
        if not installed or not path:
            return False

        p = Path(path)
        if p.exists():
            p.unlink()
            return True
        return False
