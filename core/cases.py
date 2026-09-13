# core/cases.py
# Curated Case Templates Engine for Agent Engine Capabilities
# Loads, validates, and serves realistic featured cases across all 8 capability modes

import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_DIR = PROJECT_ROOT / "configs" / "cases"

SUPPORTED_MODES = [
    "code",
    "deep-research",
    "docs",
    "sheets",
    "slides",
    "websites",
    "design",
    "diagrams",
]


class FeaturedCase(BaseModel):
    """Declarative representation of a curated featured case item."""

    id: str = Field(..., description="Unique case identifier")
    title: str = Field(..., description="Human-readable title")
    category: str = Field(..., description="Category group within mode")
    description: str = Field(..., description="Short summary of task and value proposition")
    mode: str = Field(..., description="Associated capability mode")
    icon_name: str = Field(default="sparkles", description="Lucide icon identifier")
    est_cost: str = Field(default="$0.0010", description="Cost estimate preview")
    tags: List[str] = Field(default_factory=list, description="Categorization keywords")
    prompt: str = Field(..., description="Realistic one-click runnable prompt")
    expected_tools: List[str] = Field(
        default_factory=list, description="Ordered tool chain utilized during execution"
    )
    sample_output: str = Field(..., description="Expected output preview, formatted text, or diff")


class ModeCasesConfig(BaseModel):
    """Configuration and curated cases for a specific capability mode."""

    mode: str = Field(..., description="Canonical mode identifier")
    title: str = Field(..., description="Mode display title")
    tagline: str = Field(..., description="Descriptive tagline")
    badge: str = Field(..., description="Badge or engine label")
    pipeline: str = Field(..., description="Backing execution pipeline")
    categories: List[str] = Field(default_factory=list, description="Category filter tabs")
    cases: List[FeaturedCase] = Field(default_factory=list, description="Curated case items")


class CaseManager:
    """Manager for discovering, loading, and searching curated case templates."""

    def __init__(self, cases_dir: Optional[Path] = None):
        self.cases_dir = cases_dir or DEFAULT_CASES_DIR
        self._cache: Dict[str, ModeCasesConfig] = {}
        self._reload_cache()

    def _normalize_mode(self, mode: str) -> str:
        return mode.lower().replace("-", "_")

    def _canonical_mode(self, mode: str) -> str:
        return mode.lower().replace("_", "-")

    def _reload_cache(self) -> None:
        self._cache.clear()
        if not self.cases_dir.exists():
            return

        for json_file in self.cases_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                config = ModeCasesConfig(**raw)
                # Store by both hyphenated and underscore keys
                canonical = self._canonical_mode(config.mode)
                self._cache[canonical] = config
                self._cache[self._normalize_mode(config.mode)] = config
            except Exception as e:
                print(f"Warning: Failed to load case file {json_file}: {e}")

    def get_mode_config(self, mode: str) -> Optional[ModeCasesConfig]:
        """Retrieve curated config and cases for a mode."""
        key = self._canonical_mode(mode)
        if key in self._cache:
            return self._cache[key]
        normalized = self._normalize_mode(mode)
        return self._cache.get(normalized)

    def list_all_modes(self) -> List[ModeCasesConfig]:
        """List distinct configurations for all supported capability modes."""
        seen = set()
        configs = []
        for key, conf in self._cache.items():
            if conf.mode not in seen:
                seen.add(conf.mode)
                configs.append(conf)
        return configs

    def get_case(self, case_id: str) -> Optional[FeaturedCase]:
        """Lookup a specific case item by its ID across all modes."""
        for conf in self.list_all_modes():
            for c in conf.cases:
                if c.id == case_id:
                    return c
        return None

    def search(self, query: str, mode: Optional[str] = None) -> List[FeaturedCase]:
        """Search cases by query substring across title, description, prompt, and tags."""
        query_lower = query.lower().strip()
        results: List[FeaturedCase] = []
        target_configs = (
            [self.get_mode_config(mode)]
            if mode and self.get_mode_config(mode)
            else self.list_all_modes()
        )

        for conf in target_configs:
            if not conf:
                continue
            for c in conf.cases:
                matches_text = (
                    query_lower in c.title.lower()
                    or query_lower in c.description.lower()
                    or query_lower in c.prompt.lower()
                    or any(query_lower in t.lower() for t in c.tags)
                    or query_lower in c.category.lower()
                )
                if matches_text:
                    results.append(c)

        return results


# Global singleton instance
_case_manager: Optional[CaseManager] = None


def get_case_manager() -> CaseManager:
    """Retrieve or initialize the global CaseManager singleton."""
    global _case_manager
    if _case_manager is None:
        _case_manager = CaseManager()
    return _case_manager


def load_mode_cases(mode_name: str) -> Optional[ModeCasesConfig]:
    """Helper to fetch ModeCasesConfig for a mode."""
    return get_case_manager().get_mode_config(mode_name)


def list_all_mode_cases() -> List[ModeCasesConfig]:
    """Helper to fetch all ModeCasesConfig instances."""
    return get_case_manager().list_all_modes()
