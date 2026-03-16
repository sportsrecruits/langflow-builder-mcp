"""MCP tools for flow CRUD operations."""

import re
from typing import Any

from ..client import LangflowClient
from ..config import get_config

# Matches the backup naming convention: [Backup] <name> (rev <N>)
_BACKUP_NAME_RE = re.compile(r"^\[Backup\] .+ \(rev \d+\)$")


def _is_backup_flow(flow: dict[str, Any], backup_folder_id: str | None) -> bool:
    """Check if a flow is a backup based on naming convention or folder."""
    name = flow.get("name", "")
    if _BACKUP_NAME_RE.match(name):
        return True
    if backup_folder_id and flow.get("folder_id") == backup_folder_id:
        return True
    return False


async def list_flows(client: LangflowClient) -> list[dict[str, Any]]:
    """List all flows accessible to the current user.

    Excludes backup flows to keep results concise. A flow is considered a backup
    if it matches the naming convention '[Backup] ... (rev N)' or lives in the
    configured backup folder.

    Returns:
        List of flow summaries with id, name, description, is_component
    """
    config = get_config()
    flows = await client.list_flows()

    # Find the backup folder ID so we can also exclude by folder
    backup_folder_id = None
    projects = await client.list_projects()
    for project in projects:
        if project.get("name") == config.backup_folder_name:
            backup_folder_id = project.get("id")
            break

    return [
        {
            "id": flow.get("id"),
            "name": flow.get("name"),
            "description": flow.get("description"),
            "is_component": flow.get("is_component", False),
            "endpoint_name": flow.get("endpoint_name"),
            "folder_id": flow.get("folder_id"),
        }
        for flow in flows
        if not _is_backup_flow(flow, backup_folder_id)
    ]


async def list_all_flows(client: LangflowClient) -> list[dict[str, Any]]:
    """List all flows including MCP backup flows.

    Returns:
        List of flow summaries with id, name, description, is_component
    """
    flows = await client.list_flows()

    return [
        {
            "id": flow.get("id"),
            "name": flow.get("name"),
            "description": flow.get("description"),
            "is_component": flow.get("is_component", False),
            "endpoint_name": flow.get("endpoint_name"),
            "folder_id": flow.get("folder_id"),
        }
        for flow in flows
    ]


async def get_flow(client: LangflowClient, flow_id: str) -> dict[str, Any]:
    """Get complete flow structure including all nodes and edges.

    Args:
        flow_id: UUID of the flow

    Returns:
        Full flow structure with nodes, edges, and metadata
    """
    flow = await client.get_flow(flow_id)

    # Extract and simplify the flow structure for easier understanding
    flow_data = flow.get("data", {})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Simplify node information
    simplified_nodes = []
    for node in nodes:
        node_data = node.get("data", {})
        node_config = node_data.get("node", {})

        simplified_nodes.append(
            {
                "id": node.get("id"),
                "type": node.get("type"),
                "component_type": node_config.get("key") or node_data.get("type"),
                "display_name": node_config.get("display_name"),
                "position": node.get("position"),
                "template_values": _extract_template_values(node_config.get("template", {})),
            }
        )

    # Simplify edge information
    simplified_edges = []
    for edge in edges:
        edge_data = edge.get("data", {})
        source_handle = edge_data.get("sourceHandle", {})
        target_handle = edge_data.get("targetHandle", {})

        simplified_edges.append(
            {
                "id": edge.get("id"),
                "source_node": edge.get("source"),
                "source_output": source_handle.get("name"),
                "source_types": source_handle.get("output_types", []),
                "target_node": edge.get("target"),
                "target_input": target_handle.get("fieldName"),
                "target_types": target_handle.get("inputTypes", []),
            }
        )

    return {
        "id": flow.get("id"),
        "name": flow.get("name"),
        "description": flow.get("description"),
        "is_component": flow.get("is_component", False),
        "nodes": simplified_nodes,
        "edges": simplified_edges,
        "node_count": len(simplified_nodes),
        "edge_count": len(simplified_edges),
    }


def _extract_template_values(template: dict[str, Any]) -> dict[str, Any]:
    """Extract current values from a node template.

    Args:
        template: Node template dictionary

    Returns:
        Dictionary of field names to their current values
    """
    values = {}
    for field_name, field_data in template.items():
        if isinstance(field_data, dict) and not field_name.startswith("_"):
            value = field_data.get("value")
            if value is not None and value != "" and value != "__UNDEFINED__":
                values[field_name] = value
    return values


async def get_flow_raw(client: LangflowClient, flow_id: str) -> dict[str, Any]:
    """Get complete raw flow structure as returned by API.

    This is useful when you need the full flow data for modifications.

    Args:
        flow_id: UUID of the flow

    Returns:
        Complete raw flow data
    """
    return await client.get_flow(flow_id)


async def create_flow(
    client: LangflowClient,
    name: str,
    description: str | None = None,
    folder_id: str | None = None,
) -> dict[str, Any]:
    """Create a new empty flow.

    Args:
        name: Flow name
        description: Optional description
        folder_id: Optional folder UUID

    Returns:
        Created flow data including id
    """
    flow_data: dict[str, Any] = {
        "name": name,
        "data": {
            "nodes": [],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }

    if description:
        flow_data["description"] = description
    if folder_id:
        flow_data["folder_id"] = folder_id

    result = await client.create_flow(flow_data)

    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "description": result.get("description"),
        "message": f"Flow '{name}' created successfully",
    }


async def update_flow_metadata(
    client: LangflowClient,
    flow_id: str,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update flow metadata (name, description).

    Args:
        flow_id: Flow UUID
        name: New name (optional)
        description: New description (optional)

    Returns:
        Updated flow data
    """
    update_data: dict[str, Any] = {}
    if name:
        update_data["name"] = name
    if description is not None:
        update_data["description"] = description

    if not update_data:
        raise ValueError("At least one of name or description must be provided")

    result = await client.update_flow(flow_id, update_data)

    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "description": result.get("description"),
        "message": "Flow updated successfully",
    }


async def update_flow_data(
    client: LangflowClient,
    flow_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Update complete flow data (nodes and edges).

    Args:
        flow_id: Flow UUID
        data: Complete flow data with nodes and edges

    Returns:
        Updated flow data
    """
    # Validate data structure
    if "nodes" not in data:
        raise ValueError("Flow data must have 'nodes' key")
    if "edges" not in data:
        raise ValueError("Flow data must have 'edges' key")

    result = await client.update_flow(flow_id, {"data": data})

    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "node_count": len(data.get("nodes", [])),
        "edge_count": len(data.get("edges", [])),
        "message": "Flow data updated successfully",
    }


async def delete_flow(client: LangflowClient, flow_id: str) -> dict[str, Any]:
    """Delete a flow permanently.

    Args:
        flow_id: Flow UUID

    Returns:
        Deletion confirmation
    """
    result = await client.delete_flow(flow_id)

    return {
        "success": True,
        "message": result.get("message", "Flow deleted successfully"),
    }


async def duplicate_flow(
    client: LangflowClient,
    flow_id: str,
    new_name: str | None = None,
) -> dict[str, Any]:
    """Duplicate an existing flow.

    Args:
        flow_id: Flow UUID to duplicate
        new_name: Name for the new flow (defaults to "Copy of {original_name}")

    Returns:
        Created flow data
    """
    # Get the original flow
    original = await client.get_flow(flow_id)
    original_name = original.get("name", "Unnamed")

    # Create the duplicate
    duplicate_data: dict[str, Any] = {
        "name": new_name or f"Copy of {original_name}",
        "description": original.get("description"),
        "data": original.get("data", {"nodes": [], "edges": []}),
    }

    result = await client.create_flow(duplicate_data)

    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "original_id": flow_id,
        "message": f"Flow duplicated successfully",
    }
