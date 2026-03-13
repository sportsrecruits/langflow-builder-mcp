"""MCP tools for edge/connection manipulation."""

from typing import Any

from ..client import LangflowClient
from ..generators import build_edge_structure
from ..schema_cache import ComponentSchemaCache
from ..validator import ConnectionValidator


async def connect_nodes(
    client: LangflowClient,
    flow_id: str,
    source_node_id: str,
    source_output: str,
    target_node_id: str,
    target_input: str,
) -> dict[str, Any]:
    """Connect two nodes by creating an edge.

    Uses actual node data from the flow for type validation rather than
    the component schema cache, which handles dynamic fields and custom components.

    Args:
        flow_id: Flow UUID
        source_node_id: Source node ID (e.g., "Agent-D0Kx2")
        source_output: Output name on source (e.g., "response")
        target_node_id: Target node ID (e.g., "ChatOutput-yhCn0")
        target_input: Input field name on target (e.g., "input_value")

    Returns:
        Created edge info with full handle details

    Raises:
        ValueError: If nodes not found or types incompatible
    """

    # Get the flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Find source and target nodes
    source_node = None
    target_node = None
    for node in nodes:
        if node.get("id") == source_node_id:
            source_node = node
        if node.get("id") == target_node_id:
            target_node = node

    if not source_node:
        raise ValueError(f"Source node '{source_node_id}' not found")
    if not target_node:
        raise ValueError(f"Target node '{target_node_id}' not found")

    # Get component types
    source_data = source_node.get("data", {})
    source_node_config = source_data.get("node", {})
    source_type = source_node_config.get("key") or source_data.get("type")

    target_data = target_node.get("data", {})
    target_node_config = target_data.get("node", {})
    target_type = target_node_config.get("key") or target_data.get("type")

    # Get output types from source node's outputs (from actual node data)
    # IMPORTANT: Langflow validation logic expects:
    # - If output has 1 type: use that type
    # - If output has multiple types: use only the "selected" type
    # This matches the logic in detectBrokenEdgesEdges:
    #   outputTypes = output.types.length === 1 ? output.types : [output.selected]
    source_outputs = source_node_config.get("outputs", [])
    source_output_types: list[str] = []
    source_output_all_types: list[str] = []  # For type matching validation
    found_output = None
    for output in source_outputs:
        if output.get("name") == source_output:
            found_output = output
            # Check if output is visible:
            # - If group_outputs is True, it's always visible
            # - If group_outputs is False/undefined, it must be selected to be visible
            group_outputs = output.get("group_outputs", False)
            is_selected = output.get("selected")
            if not group_outputs and not is_selected:
                raise ValueError(
                    f"Output '{source_output}' on node '{source_node_id}' is not selected/visible. "
                    f"The output must be selected (visible) to create a connection."
                )

            all_types = output.get("types", [])
            source_output_all_types = all_types
            if len(all_types) == 1:
                source_output_types = all_types
            else:
                # Multiple types - use only the selected type
                selected = output.get("selected")
                if selected:
                    source_output_types = [selected]
                else:
                    # Fallback to first type if no selection
                    source_output_types = [all_types[0]] if all_types else []
            break

    if not found_output:
        raise ValueError(f"Output '{source_output}' not found on node '{source_node_id}'")

    # Get input types from target (from actual node data)
    target_template = target_node_config.get("template", {})
    target_input_types: list[str] = []
    target_field_type = "other"
    target_proxy: dict[str, Any] | None = None
    if target_input in target_template:
        field_data = target_template[target_input]
        target_input_types = field_data.get("input_types", [])
        target_field_type = field_data.get("type", "other")

        # Check if field is hidden - connections to hidden fields are removed on load
        if field_data.get("show") is False:
            raise ValueError(
                f"Cannot connect to '{target_input}' on node '{target_node_id}' - "
                f"the field is hidden (show=false)"
            )

        # Check for proxy field (used in groups to redirect to inner nodes)
        if "proxy" in field_data:
            target_proxy = field_data.get("proxy")

        # Check for tool_mode conflict - if node is in tool_mode and field is a
        # tool_mode field, the connection will be removed when the flow loads
        node_in_tool_mode = target_node_config.get("tool_mode", False)
        field_is_tool_mode = field_data.get("tool_mode", False)
        if node_in_tool_mode and field_is_tool_mode:
            raise ValueError(
                f"Cannot connect to '{target_input}' on node '{target_node_id}' - "
                f"the node is in tool_mode and this field is a tool_mode field "
                f"(connections to tool_mode fields are removed when tool_mode is enabled)"
            )
    else:
        raise ValueError(f"Input '{target_input}' not found on node '{target_node_id}'")

    # Validate type compatibility using ALL output types (not just selected)
    # This allows connecting even if the "selected" output type doesn't match,
    # as long as one of the possible output types is compatible
    if target_input_types:
        matched_types = [t for t in source_output_all_types if t in target_input_types]
        if not matched_types:
            raise ValueError(
                f"Type mismatch: source outputs {source_output_all_types} "
                f"not compatible with target inputs {target_input_types}"
            )
    else:
        # Empty input_types means it accepts any type
        matched_types = source_output_all_types

    # Build the edge
    edge = build_edge_structure(
        source_node_id=source_node_id,
        source_component_type=source_type,
        source_output_name=source_output,
        source_output_types=source_output_types,
        target_node_id=target_node_id,
        target_field_name=target_input,
        target_input_types=target_input_types,
        target_field_type=target_field_type,
        target_proxy=target_proxy,
    )

    # Add edge to flow
    edges.append(edge)
    flow_data["edges"] = edges

    # Update flow
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "edge_id": edge["id"],
        "source_node": source_node_id,
        "source_output": source_output,
        "target_node": target_node_id,
        "target_input": target_input,
        "matched_types": matched_types,
        "message": f"Connected {source_node_id}.{source_output} -> {target_node_id}.{target_input}",
    }


async def disconnect_nodes(
    client: LangflowClient,
    flow_id: str,
    source_node_id: str,
    target_node_id: str,
    target_input: str | None = None,
) -> dict[str, Any]:
    """Remove connection(s) between nodes.

    Args:
        flow_id: Flow UUID
        source_node_id: Source node ID
        target_node_id: Target node ID
        target_input: Specific input to disconnect (optional)
            If None, removes all edges between these nodes.

    Returns:
        Disconnection confirmation
    """
    # Get the flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    edges = flow_data.get("edges", [])

    original_count = len(edges)

    # Filter out matching edges
    new_edges = []
    for edge in edges:
        edge_data = edge.get("data", {})
        target_handle = edge_data.get("targetHandle", {})

        if edge.get("source") == source_node_id and edge.get("target") == target_node_id:
            if target_input is None:
                # Remove all edges between these nodes
                continue
            elif target_handle.get("fieldName") == target_input:
                # Remove specific edge
                continue

        new_edges.append(edge)

    removed_count = original_count - len(new_edges)

    if removed_count == 0:
        raise ValueError(
            f"No edge found between '{source_node_id}' and '{target_node_id}'"
            + (f" on input '{target_input}'" if target_input else "")
        )

    # Update flow
    flow_data["edges"] = new_edges
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "removed_count": removed_count,
        "message": f"Removed {removed_count} connection(s) between {source_node_id} and {target_node_id}",
    }


async def list_connections(
    client: LangflowClient,
    flow_id: str,
    node_id: str | None = None,
) -> list[dict[str, Any]]:
    """List all connections in a flow or for a specific node.

    Args:
        flow_id: Flow UUID
        node_id: Optional node ID to filter connections

    Returns:
        List of connections with source/target info
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    edges = flow_data.get("edges", [])

    result = []
    for edge in edges:
        # Filter by node if specified
        if node_id:
            if edge.get("source") != node_id and edge.get("target") != node_id:
                continue

        edge_data = edge.get("data", {})
        source_handle = edge_data.get("sourceHandle", {})
        target_handle = edge_data.get("targetHandle", {})

        result.append(
            {
                "edge_id": edge.get("id"),
                "source_node": edge.get("source"),
                "source_output": source_handle.get("name"),
                "source_types": source_handle.get("output_types", []),
                "target_node": edge.get("target"),
                "target_input": target_handle.get("fieldName"),
                "target_types": target_handle.get("inputTypes", []),
            }
        )

    return result


async def validate_connection(
    cache: ComponentSchemaCache,
    validator: ConnectionValidator,
    source_component_type: str,
    source_output: str,
    target_component_type: str,
    target_input: str,
) -> dict[str, Any]:
    """Check if a connection would be valid without creating it.

    Args:
        source_component_type: Component type of source node
        source_output: Output name on source
        target_component_type: Component type of target node
        target_input: Input field name on target

    Returns:
        Validation result with is_valid, error_message, matched_types
    """
    await cache.ensure_loaded()

    result = validator.validate_connection(
        source_component_type, source_output, target_component_type, target_input
    )

    return {
        "is_valid": result.is_valid,
        "error": result.error,
        "matched_types": result.matched_types,
        "source_types": result.source_types,
        "target_types": result.target_types,
    }


async def find_compatible_connections(
    client: LangflowClient,
    cache: ComponentSchemaCache,
    validator: ConnectionValidator,
    flow_id: str,
    node_id: str,
    direction: str,
) -> list[dict[str, Any]]:
    """Find all compatible connections for a node in a flow.

    Args:
        flow_id: Flow UUID
        node_id: Node to find connections for
        direction: "inputs" to find what can connect TO this node,
                   "outputs" to find what this node can connect TO

    Returns:
        List of compatible nodes with specific input/output pairs
    """
    await cache.ensure_loaded()

    # Get the flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Find the target node
    target_node = None
    for node in nodes:
        if node.get("id") == node_id:
            target_node = node
            break

    if not target_node:
        raise ValueError(f"Node '{node_id}' not found")

    target_data = target_node.get("data", {})
    target_config = target_data.get("node", {})
    target_type = target_config.get("key") or target_data.get("type")

    compatible = []

    if direction == "inputs":
        # Find outputs from other nodes that can connect to this node's inputs
        schema = cache.get_component(target_type)
        if not schema:
            return []

        for input_name, input_field in schema.inputs.items():
            if not input_field.input_types:
                continue

            # Find compatible outputs in the flow
            for node in nodes:
                if node.get("id") == node_id:
                    continue

                node_data = node.get("data", {})
                node_config = node_data.get("node", {})
                node_type = node_config.get("key") or node_data.get("type")

                for output in node_config.get("outputs", []):
                    output_types = output.get("types", [])
                    matched = [t for t in output_types if t in input_field.input_types]
                    if matched:
                        compatible.append(
                            {
                                "node_id": node.get("id"),
                                "component_type": node_type,
                                "display_name": node_config.get("display_name"),
                                "port_name": output.get("name"),
                                "port_display_name": output.get("display_name"),
                                "connects_to": input_name,
                                "matched_types": matched,
                            }
                        )

    elif direction == "outputs":
        # Find inputs on other nodes that can accept this node's outputs
        for output in target_config.get("outputs", []):
            output_types = output.get("types", [])
            if not output_types:
                continue

            for node in nodes:
                if node.get("id") == node_id:
                    continue

                node_data = node.get("data", {})
                node_config = node_data.get("node", {})
                node_type = node_config.get("key") or node_data.get("type")
                template = node_config.get("template", {})

                for field_name, field_data in template.items():
                    if not isinstance(field_data, dict) or field_name.startswith("_"):
                        continue

                    input_types = field_data.get("input_types", [])
                    if not input_types:
                        continue

                    matched = [t for t in output_types if t in input_types]
                    if matched:
                        compatible.append(
                            {
                                "node_id": node.get("id"),
                                "component_type": node_type,
                                "display_name": node_config.get("display_name"),
                                "port_name": field_name,
                                "port_display_name": field_data.get(
                                    "display_name", field_name
                                ),
                                "connects_from": output.get("name"),
                                "matched_types": matched,
                            }
                        )
    else:
        raise ValueError("direction must be 'inputs' or 'outputs'")

    return compatible
