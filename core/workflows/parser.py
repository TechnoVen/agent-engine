"""core/workflows/parser.py

Lossless YAML/JSON parser and DAG graph validator for Agent Engine workflows.
Part of Phase 7 (Task 7.1 - Milestone M5).

Features:
- Lossless round-trip conversion between YAML, JSON, and WorkflowDefinition.
- Kahn's algorithm topological sorting and cycle detection.
- Structural schema and edge connectivity validation.
"""

from __future__ import annotations

from collections import deque
import json
import logging
from typing import Any, Dict, List, Set, Tuple
import yaml

from core.workflows.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowNodeType,
)

logger = logging.getLogger("agent_engine.workflows.parser")


class WorkflowParser:
    """Parser and validator for workflow definitions in YAML and JSON."""

    @staticmethod
    def to_dict(workflow: WorkflowDefinition) -> Dict[str, Any]:
        """Convert a WorkflowDefinition instance to a clean dictionary."""
        return workflow.model_dump(mode="json", exclude_none=True)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> WorkflowDefinition:
        """Parse a dictionary into a validated WorkflowDefinition instance."""
        if not isinstance(data, dict):
            raise ValueError("Workflow data must be a dictionary/mapping.")
        return WorkflowDefinition.model_validate(data)

    @classmethod
    def to_yaml(cls, workflow: WorkflowDefinition) -> str:
        """Convert a WorkflowDefinition to a clean, human-readable YAML string."""
        raw_dict = cls.to_dict(workflow)
        return yaml.dump(
            raw_dict,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            indent=2,
        )

    @classmethod
    def from_yaml(cls, yaml_content: str) -> WorkflowDefinition:
        """Parse a YAML string into a WorkflowDefinition."""
        if not yaml_content or not yaml_content.strip():
            raise ValueError("Workflow YAML content cannot be empty.")
        try:
            data = yaml.safe_load(yaml_content)
        except Exception as e:
            raise ValueError(f"Failed to parse YAML syntax: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("Workflow YAML root must be a mapping/dictionary.")

        return cls.from_dict(data)

    @classmethod
    def to_json(cls, workflow: WorkflowDefinition, indent: int = 2) -> str:
        """Serialize a WorkflowDefinition to a formatted JSON string."""
        return json.dumps(cls.to_dict(workflow), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_content: str) -> WorkflowDefinition:
        """Parse a JSON string into a WorkflowDefinition."""
        if not json_content or not json_content.strip():
            raise ValueError("Workflow JSON content cannot be empty.")
        try:
            data = json.loads(json_content)
        except Exception as e:
            raise ValueError(f"Failed to parse JSON syntax: {e}") from e
        return cls.from_dict(data)

    @staticmethod
    def validate(workflow: WorkflowDefinition) -> Tuple[bool, List[str]]:
        """Perform comprehensive graph and schema validation.

        Returns (is_valid, error_messages).
        """
        errors: List[str] = []

        if not workflow.id or not workflow.id.strip():
            errors.append("Workflow must have a non-empty 'id'.")
        if not workflow.name or not workflow.name.strip():
            errors.append("Workflow must have a non-empty 'name'.")

        if not workflow.nodes:
            errors.append("Workflow must contain at least one node.")
            return False, errors

        # 1. Node uniqueness and validation
        node_ids: Set[str] = set()
        for node in workflow.nodes:
            if not node.id or not node.id.strip():
                errors.append("All nodes must have a non-empty 'id'.")
                continue
            if node.id in node_ids:
                errors.append(f"Duplicate node ID detected: '{node.id}'.")
            node_ids.add(node.id)

        # 2. Edge validation
        edge_ids: Set[str] = set()
        in_degrees: Dict[str, int] = {nid: 0 for nid in node_ids}
        adj_list: Dict[str, List[str]] = {nid: [] for nid in node_ids}

        for edge in workflow.edges:
            if not edge.id:
                errors.append("All edges must have a non-empty 'id'.")
            elif edge.id in edge_ids:
                errors.append(f"Duplicate edge ID detected: '{edge.id}'.")
            edge_ids.add(edge.id)

            if edge.source not in node_ids:
                errors.append(
                    f"Edge '{edge.id}' references non-existent source node '{edge.source}'."
                )
            if edge.target not in node_ids:
                errors.append(
                    f"Edge '{edge.id}' references non-existent target node '{edge.target}'."
                )

            if edge.source in node_ids and edge.target in node_ids:
                adj_list[edge.source].append(edge.target)
                in_degrees[edge.target] += 1

        # 3. Entry point check: at least one node with in-degree 0
        root_nodes = [nid for nid, deg in in_degrees.items() if deg == 0]
        if workflow.nodes and not root_nodes:
            errors.append(
                "Workflow has no starting entry node (all nodes have incoming edges, cycle detected)."
            )

        # 4. Cycle Detection using Kahn's algorithm
        queue = deque(root_nodes)
        visited_count = 0
        temp_in_degrees = dict(in_degrees)

        while queue:
            curr = queue.popleft()
            visited_count += 1
            for neighbor in adj_list.get(curr, []):
                temp_in_degrees[neighbor] -= 1
                if temp_in_degrees[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count < len(node_ids):
            unvisited = [nid for nid, deg in temp_in_degrees.items() if deg > 0]
            errors.append(
                f"Cycle detected in workflow graph involving nodes: {', '.join(unvisited)}."
            )

        # 5. Semantic node checks
        for node in workflow.nodes:
            if node.type == WorkflowNodeType.CONDITION:
                outgoing = [e for e in workflow.edges if e.source == node.id]
                if not outgoing:
                    errors.append(f"Condition node '{node.id}' has no outgoing conditional edges.")

        return len(errors) == 0, errors

    @staticmethod
    def get_topological_sort(workflow: WorkflowDefinition) -> List[WorkflowNode]:
        """Compute a valid topological execution order for the workflow nodes."""
        node_map = {node.id: node for node in workflow.nodes}
        in_degrees = {node.id: 0 for node in workflow.nodes}
        adj_list: Dict[str, List[str]] = {node.id: [] for node in workflow.nodes}

        for edge in workflow.edges:
            if edge.source in node_map and edge.target in node_map:
                adj_list[edge.source].append(edge.target)
                in_degrees[edge.target] += 1

        queue = deque([nid for nid, deg in in_degrees.items() if deg == 0])
        sorted_nodes: List[WorkflowNode] = []

        while queue:
            curr = queue.popleft()
            sorted_nodes.append(node_map[curr])
            for neighbor in adj_list.get(curr, []):
                in_degrees[neighbor] -= 1
                if in_degrees[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_nodes) < len(workflow.nodes):
            raise ValueError("Cannot compute topological order: workflow contains a cycle.")

        return sorted_nodes
