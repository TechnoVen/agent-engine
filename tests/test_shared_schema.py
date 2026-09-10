import json
import os

import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_monorepo_directory_structure():
    """Verify that all core monorepo packages and directories exist."""
    expected_paths = [
        "apps/desktop",
        "services/python",
        "packages/shared-schema",
        "packages/sdk-js",
        "packages/sdk-python",
        "docs",
        "infra",
        "Makefile",
        "pyproject.toml",
        "pnpm-workspace.yaml",
        "README.md",
    ]
    for rel_path in expected_paths:
        full_path = os.path.join(PROJECT_ROOT, rel_path)
        assert os.path.exists(full_path), f"Expected path does not exist: {rel_path}"


def test_openapi_schema_validity():
    """Verify that openapi.yaml parses cleanly and includes required v1 endpoints."""
    openapi_path = os.path.join(PROJECT_ROOT, "packages", "shared-schema", "openapi.yaml")
    assert os.path.isfile(openapi_path), "openapi.yaml not found"

    with open(openapi_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    assert spec["openapi"].startswith("3."), f"Expected OpenAPI 3.x, got {spec.get('openapi')}"
    assert "paths" in spec

    required_endpoints = [
        "/chat/completions",
        "/events",
        "/agents",
        "/skills",
        "/workflows",
        "/memory",
        "/patches",
        "/telemetry",
        "/auth/session",
        "/registry/search",
    ]
    for endpoint in required_endpoints:
        assert endpoint in spec["paths"], f"Missing required endpoint: {endpoint}"


def test_events_schema_validity():
    """Verify that events.schema.json is valid JSON Schema with all required event types."""
    events_path = os.path.join(PROJECT_ROOT, "packages", "shared-schema", "events.schema.json")
    assert os.path.isfile(events_path), "events.schema.json not found"

    with open(events_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    assert "$defs" in schema
    expected_events = [
        "TokenEvent",
        "ToolCallEvent",
        "ApprovalRequestEvent",
        "PatchStagedEvent",
        "CostUpdateEvent",
        "AgentStatusEvent",
    ]
    for event_name in expected_events:
        assert event_name in schema["$defs"], f"Missing expected event def: {event_name}"


def test_roadmap_tracker_exists():
    """Verify that docs/ROADMAP.md exists and tracks Milestone 0."""
    roadmap_path = os.path.join(PROJECT_ROOT, "docs", "ROADMAP.md")
    assert os.path.isfile(roadmap_path), "ROADMAP.md not found"

    with open(roadmap_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "M0 — Foundations" in content
    assert "Task 0.1 — Repository Restructure" in content
