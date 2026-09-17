"""core/skills/collections.py

Skill Collections and Full-Text Search Service for Agent Engine.
Part of Phase 6 (Task 6.3 - Milestone M4).

Features:
- SQLite-backed Skill Collections management (CRUD, member skill tagging, curated bundles).
- Full-text and metadata search engine across multi-tool skills with relevance scoring.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import List, Optional, Tuple

from core.skills.discovery import MultiToolSkillDiscovery, PROJECT_ROOT
from core.skills.models import Skill, SkillCollection, SkillSource

logger = logging.getLogger("agent_engine.skills.collections")

DEFAULT_SQLITE_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")


class SkillCollectionManager:
    """Manages skill collections in SQLite and provides fast multi-attribute search across skills."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        discovery: Optional[MultiToolSkillDiscovery] = None,
    ):
        self.db_path = db_path or DEFAULT_SQLITE_PATH
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self.discovery = discovery or MultiToolSkillDiscovery()

        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Ensure collections tables and indexes exist."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS skill_collections (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS collection_skills (
                    collection_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (collection_id, skill_id),
                    FOREIGN KEY (collection_id) REFERENCES skill_collections(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_collection_skills_skill ON collection_skills(skill_id);
            """)
            conn.commit()

    def create_collection(
        self,
        name: str,
        description: str = "",
        tags: Optional[List[str]] = None,
        skill_ids: Optional[List[str]] = None,
        collection_id: Optional[str] = None,
    ) -> SkillCollection:
        """Create a new skill collection and optionally associate initial skills."""
        clean_id = (
            collection_id
            or re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower()).strip("_")
            or f"coll_{int(time.time())}"
        )
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tag_list = tags or []
        skills_to_add = skill_ids or []

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM skill_collections WHERE id = ?", (clean_id,))
            if cursor.fetchone():
                raise FileExistsError(f"Collection '{clean_id}' already exists.")

            cursor.execute(
                """
                INSERT INTO skill_collections (id, name, description, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (clean_id, name, description, json.dumps(tag_list), now, now),
            )

            for s_id in skills_to_add:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO collection_skills (collection_id, skill_id, added_at)
                    VALUES (?, ?, ?)
                    """,
                    (clean_id, s_id, now),
                )

            conn.commit()

        return SkillCollection(
            id=clean_id,
            name=name,
            description=description,
            tags=tag_list,
            skill_ids=skills_to_add,
            created_at=now,
            updated_at=now,
        )

    def get_collection(self, collection_id: str) -> Optional[SkillCollection]:
        """Fetch a collection by ID along with its associated skill IDs."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, name, description, tags, created_at, updated_at
                FROM skill_collections
                WHERE id = ?
                """,
                (collection_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            cursor.execute(
                """
                SELECT skill_id FROM collection_skills
                WHERE collection_id = ?
                ORDER BY added_at ASC
                """,
                (collection_id,),
            )
            skill_rows = cursor.fetchall()
            skill_ids = [r["skill_id"] for r in skill_rows]

            try:
                tags = json.loads(row["tags"])
            except Exception:
                tags = []

            return SkillCollection(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                tags=tags,
                skill_ids=skill_ids,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_collections(self, tag: Optional[str] = None) -> List[SkillCollection]:
        """List all skill collections, optionally filtered by tag."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, name, description, tags, created_at, updated_at
                FROM skill_collections
                ORDER BY name ASC
                """
            )
            rows = cursor.fetchall()

            collections: List[SkillCollection] = []
            for row in rows:
                c_id = row["id"]
                try:
                    tags = json.loads(row["tags"])
                except Exception:
                    tags = []

                if tag and tag.lower() not in [t.lower() for t in tags]:
                    continue

                cursor.execute(
                    """
                    SELECT skill_id FROM collection_skills
                    WHERE collection_id = ?
                    ORDER BY added_at ASC
                    """,
                    (c_id,),
                )
                skill_ids = [r["skill_id"] for r in cursor.fetchall()]

                collections.append(
                    SkillCollection(
                        id=c_id,
                        name=row["name"],
                        description=row["description"],
                        tags=tags,
                        skill_ids=skill_ids,
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )

            return collections

    def update_collection(
        self,
        collection_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> SkillCollection:
        """Update collection metadata."""
        coll = self.get_collection(collection_id)
        if not coll:
            raise FileNotFoundError(f"Collection '{collection_id}' not found.")

        new_name = name if name is not None else coll.name
        new_desc = description if description is not None else coll.description
        new_tags = tags if tags is not None else coll.tags
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE skill_collections
                SET name = ?, description = ?, tags = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_name, new_desc, json.dumps(new_tags), now, collection_id),
            )
            conn.commit()

        return self.get_collection(collection_id)  # type: ignore

    def delete_collection(self, collection_id: str) -> bool:
        """Delete a collection and all its skill associations."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM skill_collections WHERE id = ?", (collection_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def add_skill_to_collection(self, collection_id: str, skill_id: str) -> bool:
        """Associate a skill with a collection."""
        coll = self.get_collection(collection_id)
        if not coll:
            raise FileNotFoundError(f"Collection '{collection_id}' not found.")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO collection_skills (collection_id, skill_id, added_at)
                VALUES (?, ?, ?)
                """,
                (collection_id, skill_id, now),
            )
            cursor.execute(
                "UPDATE skill_collections SET updated_at = ? WHERE id = ?",
                (now, collection_id),
            )
            conn.commit()
            return True

    def remove_skill_from_collection(self, collection_id: str, skill_id: str) -> bool:
        """Remove a skill from a collection."""
        coll = self.get_collection(collection_id)
        if not coll:
            raise FileNotFoundError(f"Collection '{collection_id}' not found.")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM collection_skills
                WHERE collection_id = ? AND skill_id = ?
                """,
                (collection_id, skill_id),
            )
            removed = cursor.rowcount > 0
            if removed:
                cursor.execute(
                    "UPDATE skill_collections SET updated_at = ? WHERE id = ?",
                    (now, collection_id),
                )
            conn.commit()
            return removed

    def get_collection_skills(
        self,
        collection_id: str,
        workspace_dir: Optional[Path] = None,
    ) -> List[Skill]:
        """Resolve and load full Skill entities for all members of a collection."""
        coll = self.get_collection(collection_id)
        if not coll:
            raise FileNotFoundError(f"Collection '{collection_id}' not found.")

        skills: List[Skill] = []
        for s_id in coll.skill_ids:
            skill = self.discovery.get_skill(s_id, workspace_dir=workspace_dir)
            if skill:
                skills.append(skill)
        return skills

    def search_skills(
        self,
        query: str,
        source: Optional[SkillSource] = None,
        tag: Optional[str] = None,
        category: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
    ) -> List[Tuple[Skill, float]]:
        """
        Full-text search and multi-criteria ranking across discovered skills.
        Returns list of (Skill, relevance_score) sorted descending by score.
        """
        all_skills = self.discovery.discover_all(workspace_dir=workspace_dir)
        tokens = [t.lower() for t in re.split(r"\s+", query.strip()) if t.strip()]

        scored_results: List[Tuple[Skill, float]] = []

        for skill in all_skills:
            # Source filter
            if source and skill.metadata.source_tool != source:
                continue

            # Category filter
            if category and skill.metadata.category.lower() != category.lower():
                continue

            # Tag filter
            if tag and tag.lower() not in [t.lower() for t in skill.metadata.tags]:
                continue

            # Scoring
            score = 0.0
            s_id = skill.id.lower()
            s_name = skill.metadata.name.lower()
            s_desc = (skill.metadata.description or "").lower()
            s_tags = [t.lower() for t in skill.metadata.tags]
            s_tools = [t.lower() for t in skill.metadata.tools]
            s_content = (skill.content or "").lower()

            # If empty query, give base score
            if not tokens:
                scored_results.append((skill, 1.0))
                continue

            # Exact ID / Name matches
            q_full = query.strip().lower()
            if q_full == s_id:
                score += 100.0
            elif q_full == s_name:
                score += 80.0
            elif q_full in s_name:
                score += 40.0

            for tok in tokens:
                if tok == s_id:
                    score += 50.0
                elif tok in s_name:
                    score += 25.0
                if any(tok == t for t in s_tags):
                    score += 30.0
                elif any(tok in t for t in s_tags):
                    score += 15.0
                if any(tok == t for t in s_tools):
                    score += 20.0
                if tok in s_desc:
                    score += 15.0
                if tok in s_content:
                    score += 5.0

            if score > 0:
                scored_results.append((skill, score))

        scored_results.sort(key=lambda x: x[1], reverse=True)
        return scored_results
