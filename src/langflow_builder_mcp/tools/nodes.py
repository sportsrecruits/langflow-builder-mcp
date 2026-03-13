"""MCP tools for node manipulation."""

import copy
from typing import Any

from ..client import LangflowClient
from ..generators import build_node_structure, generate_node_id
from ..schema_cache import ComponentSchemaCache
from ..layout_engine import (
    detect_clusters,
    build_node_graph,
    find_main_path,
    score_layout,
    find_line_collisions,
)


async def add_node(
    client: LangflowClient,
    cache: ComponentSchemaCache,
    flow_id: str,
    component_type: str,
    position_x: float = 100,
    position_y: float = 100,
    config: dict[str, Any] | None = None,
    tool_mode: bool = False,
) -> dict[str, Any]:
    """Add a new node to a flow.

    Args:
        flow_id: Target flow UUID
        component_type: Component type (e.g., "Agent", "ChatInput", "OpenAIModel")
        position_x: X position on canvas
        position_y: Y position on canvas
        config: Optional template values to override defaults
        tool_mode: If True, enable tool_mode on the node via the Langflow API.
            This transforms the node's outputs to include "component_as_tool"
            (type: Tool) so it can be connected to an Agent's "tools" input.

    Returns:
        Created node info with generated ID and configuration

    Raises:
        ValueError: If component type not found
    """
    await cache.ensure_loaded()

    # Get component schema
    schema = cache.get_component(component_type)
    if not schema:
        raise ValueError(f"Component type '{component_type}' not found")

    # Get raw template for the component
    raw_template = cache.get_raw_template(component_type)
    if not raw_template:
        raise ValueError(f"Template for '{component_type}' not found")

    # Generate node ID
    node_id = generate_node_id(component_type)

    # Build template with config overrides
    template = copy.deepcopy(raw_template.get("template", {}))
    if config:
        for field_name, value in config.items():
            if field_name in template:
                template[field_name]["value"] = value

    # Build outputs and base_classes (may be transformed by tool_mode)
    outputs = raw_template.get("outputs", [])
    base_classes = schema.base_classes

    # If tool_mode requested, call the Langflow API to transform outputs
    if tool_mode:
        code = template.get("code", {}).get("value", "")
        if code:
            try:
                updated = await client.update_custom_component(
                    code=code,
                    template=template,
                    field="tool_mode",
                    field_value=True,
                    tool_mode=True,
                )
                if isinstance(updated, dict):
                    if "template" in updated:
                        template = updated["template"]
                    if "outputs" in updated:
                        outputs = updated["outputs"]
                    if "base_classes" in updated:
                        base_classes = updated["base_classes"]
            except Exception as e:
                # If API call fails, add the node without tool_mode
                tool_mode = False

    # Build the node structure
    node = build_node_structure(
        node_id=node_id,
        component_type=component_type,
        position_x=position_x,
        position_y=position_y,
        template=template,
        outputs=outputs,
        base_classes=base_classes,
        display_name=schema.display_name,
        description=schema.description,
        icon=schema.icon,
        category=schema.category,
    )

    # Set tool_mode flag if enabled
    if tool_mode:
        node["data"]["node"]["tool_mode"] = True

    # Get current flow and add node
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    flow_data["nodes"].append(node)

    # Update flow
    await client.update_flow(flow_id, {"data": flow_data})

    result = {
        "node_id": node_id,
        "component_type": component_type,
        "display_name": schema.display_name,
        "position": {"x": position_x, "y": position_y},
        "outputs": [{"name": o.get("name"), "types": o.get("types", [])} for o in outputs],
        "message": f"Node '{schema.display_name}' added successfully",
    }
    if tool_mode:
        result["tool_mode"] = True
        result["message"] += " (tool_mode enabled - connect 'component_as_tool' output to Agent's 'tools' input)"

    return result


async def add_inline_custom_component(
    client: LangflowClient,
    cache: ComponentSchemaCache,
    flow_id: str,
    code: str,
    position_x: float = 100,
    position_y: float = 100,
    tool_mode: bool = False,
) -> dict[str, Any]:
    """Add a custom component node using inline Python code.

    This is the preferred way to add custom components. It sends the code
    to the Langflow /custom_component API which dynamically evaluates it
    and returns the fully built node template — NO server restart required.

    The code should define a Component class (subclass of langflow.custom.Component).

    Args:
        flow_id: Target flow UUID
        code: Python code defining the component class
        position_x: X position on canvas
        position_y: Y position on canvas
        tool_mode: If True, enable tool_mode so it can be used as an Agent tool

    Returns:
        Created node info with generated ID, outputs, and component type

    Raises:
        ValueError: If code is invalid or doesn't define a valid component
    """
    # Step 1: Send code to /custom_component to get the validated template
    try:
        response = await client.create_custom_component(code=code)
    except Exception as e:
        raise ValueError(
            f"Failed to create custom component from code: {e}. "
            "Ensure the code defines a valid Component subclass."
        ) from e

    # The response has 'data' (the frontend node dict) and 'type' (component type name)
    node_data = response.get("data", {})
    component_type = response.get("type", "CustomComponent")

    template = node_data.get("template", {})
    outputs = node_data.get("outputs", [])
    base_classes = node_data.get("base_classes", [])
    display_name = node_data.get("display_name", component_type)
    description = node_data.get("description", "")
    icon = node_data.get("icon", "")

    # Step 2: If tool_mode requested, call /custom_component/update to transform outputs
    if tool_mode:
        code_value = template.get("code", {}).get("value", code)
        try:
            updated = await client.update_custom_component(
                code=code_value,
                template=template,
                field="tool_mode",
                field_value=True,
                tool_mode=True,
            )
            if isinstance(updated, dict):
                if "template" in updated:
                    template = updated["template"]
                if "outputs" in updated:
                    outputs = updated["outputs"]
                if "base_classes" in updated:
                    base_classes = updated["base_classes"]
        except Exception:
            tool_mode = False

    # Step 3: Build node structure and add to flow
    node_id = generate_node_id(component_type)

    node = build_node_structure(
        node_id=node_id,
        component_type=component_type,
        position_x=position_x,
        position_y=position_y,
        template=template,
        outputs=outputs,
        base_classes=base_classes,
        display_name=display_name,
        description=description,
        icon=icon,
    )

    if tool_mode:
        node["data"]["node"]["tool_mode"] = True

    # Get current flow and add node
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    flow_data["nodes"].append(node)

    # Update flow
    await client.update_flow(flow_id, {"data": flow_data})

    result = {
        "node_id": node_id,
        "component_type": component_type,
        "display_name": display_name,
        "position": {"x": position_x, "y": position_y},
        "outputs": [{"name": o.get("name"), "types": o.get("types", [])} for o in outputs],
        "message": f"Custom component '{display_name}' added successfully (inline code, no restart needed)",
    }
    if tool_mode:
        result["tool_mode"] = True
        result["message"] += " — tool_mode enabled, connect 'component_as_tool' output to Agent's 'tools' input"

    return result


async def set_tool_mode(
    client: LangflowClient,
    flow_id: str,
    node_id: str,
    enabled: bool = True,
) -> dict[str, Any]:
    """Enable or disable tool_mode on a node via the Langflow API.

    This calls the /custom_component/update endpoint which triggers
    server-side processing to:
    - Replace node outputs with a single "component_as_tool" output (type: Tool)
    - Add "tools_metadata" template field for tool configuration
    - Update base_classes to include "Tool"

    After enabling tool_mode, the node's "component_as_tool" output can be
    connected to an Agent's "tools" input.

    Args:
        flow_id: Flow UUID
        node_id: Node ID (e.g., "URLReader-D0Kx2")
        enabled: True to enable tool_mode, False to disable

    Returns:
        Updated node info including new outputs

    Raises:
        ValueError: If node not found or has no code (not a component)
    """
    # Get current flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Find the node
    node_index = None
    for i, node in enumerate(nodes):
        if node.get("id") == node_id:
            node_index = i
            break

    if node_index is None:
        raise ValueError(f"Node '{node_id}' not found in flow")

    node = nodes[node_index]
    node_config = node.get("data", {}).get("node", {})
    template = node_config.get("template", {})

    # Get the component code from the template
    code = template.get("code", {}).get("value", "")
    if not code:
        raise ValueError(
            f"Node '{node_id}' has no component code. "
            "tool_mode can only be set on components that have Python code."
        )

    # Call the Langflow /custom_component/update endpoint
    # This triggers server-side tool_mode transformation
    updated_node_data = await client.update_custom_component(
        code=code,
        template=template,
        field="tool_mode",
        field_value=enabled,
        tool_mode=enabled,
    )

    # Apply the server response back to the node in the flow
    # The response contains the transformed template, outputs, and base_classes
    if isinstance(updated_node_data, dict):
        # Update outputs (the key transformation - adds component_as_tool)
        if "outputs" in updated_node_data:
            node_config["outputs"] = updated_node_data["outputs"]

        # Update template (adds tools_metadata field)
        if "template" in updated_node_data:
            node_config["template"] = updated_node_data["template"]

        # Update base_classes
        if "base_classes" in updated_node_data:
            node_config["base_classes"] = updated_node_data["base_classes"]

        # Set the tool_mode flag on the node
        node_config["tool_mode"] = enabled

        # Update output_types if present
        if "output_types" in updated_node_data:
            node_config["output_types"] = updated_node_data["output_types"]

    # Save the updated flow
    await client.update_flow(flow_id, {"data": flow_data})

    # Build the response
    new_outputs = node_config.get("outputs", [])
    return {
        "node_id": node_id,
        "tool_mode": enabled,
        "outputs": [
            {"name": o.get("name"), "types": o.get("types", [])}
            for o in new_outputs
        ],
        "message": (
            f"tool_mode {'enabled' if enabled else 'disabled'} on node '{node_id}'. "
            + (
                "Node now has 'component_as_tool' output (type: Tool) that can be connected to an Agent's 'tools' input."
                if enabled
                else "Node outputs restored to default."
            )
        ),
    }


async def update_node(
    client: LangflowClient,
    flow_id: str,
    node_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Update node configuration values.

    Args:
        flow_id: Flow UUID
        node_id: Node ID (e.g., "Agent-D0Kx2")
        config: Dictionary of template field values to update
            Example: {"model_name": "gpt-4o", "temperature": 0.7}

    Returns:
        Updated node info

    Raises:
        ValueError: If node not found
    """
    # Get current flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Find the node
    node_index = None
    for i, node in enumerate(nodes):
        if node.get("id") == node_id:
            node_index = i
            break

    if node_index is None:
        raise ValueError(f"Node '{node_id}' not found in flow")

    node = nodes[node_index]
    node_config = node.get("data", {}).get("node", {})
    template = node_config.get("template", {})

    # Update template values
    updated_fields = []
    for field_name, value in config.items():
        if field_name in template:
            template[field_name]["value"] = value
            updated_fields.append(field_name)
        else:
            # Try to add the field if it doesn't exist
            template[field_name] = {"value": value}
            updated_fields.append(field_name)

    # Update the flow
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "node_id": node_id,
        "updated_fields": updated_fields,
        "message": f"Node updated successfully. Changed fields: {', '.join(updated_fields)}",
    }


async def remove_node(
    client: LangflowClient,
    flow_id: str,
    node_id: str,
) -> dict[str, Any]:
    """Remove a node and all its connections from a flow.

    Args:
        flow_id: Flow UUID
        node_id: Node ID to remove

    Returns:
        Removal confirmation

    Raises:
        ValueError: If node not found
    """
    # Get current flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Find and remove the node
    original_node_count = len(nodes)
    nodes = [n for n in nodes if n.get("id") != node_id]

    if len(nodes) == original_node_count:
        raise ValueError(f"Node '{node_id}' not found in flow")

    # Remove connected edges
    original_edge_count = len(edges)
    edges = [
        e for e in edges if e.get("source") != node_id and e.get("target") != node_id
    ]
    removed_edges = original_edge_count - len(edges)

    # Update flow data
    flow_data["nodes"] = nodes
    flow_data["edges"] = edges

    # Update the flow
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "node_id": node_id,
        "removed_edges": removed_edges,
        "message": f"Node removed successfully. Also removed {removed_edges} connected edge(s).",
    }


async def move_node(
    client: LangflowClient,
    flow_id: str,
    node_id: str,
    position_x: float,
    position_y: float,
) -> dict[str, Any]:
    """Update node position on the canvas.

    Args:
        flow_id: Flow UUID
        node_id: Node ID
        position_x: New X position
        position_y: New Y position

    Returns:
        Move confirmation

    Raises:
        ValueError: If node not found
    """
    # Get current flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Find and update the node
    found = False
    for node in nodes:
        if node.get("id") == node_id:
            node["position"] = {"x": position_x, "y": position_y}
            found = True
            break

    if not found:
        raise ValueError(f"Node '{node_id}' not found in flow")

    # Update the flow
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "node_id": node_id,
        "position": {"x": position_x, "y": position_y},
        "message": "Node moved successfully",
    }


async def get_node_details(
    client: LangflowClient,
    flow_id: str,
    node_id: str,
) -> dict[str, Any]:
    """Get detailed information about a specific node.

    Args:
        flow_id: Flow UUID
        node_id: Node ID

    Returns:
        Node details including configuration

    Raises:
        ValueError: If node not found
    """
    # Get current flow
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Find the node
    target_node = None
    for node in nodes:
        if node.get("id") == node_id:
            target_node = node
            break

    if target_node is None:
        raise ValueError(f"Node '{node_id}' not found in flow")

    node_data = target_node.get("data", {})
    node_config = node_data.get("node", {})
    template = node_config.get("template", {})

    # Extract current values
    current_values = {}
    for field_name, field_data in template.items():
        if isinstance(field_data, dict) and not field_name.startswith("_"):
            current_values[field_name] = {
                "value": field_data.get("value"),
                "type": field_data.get("type"),
                "display_name": field_data.get("display_name", field_name),
                "required": field_data.get("required", False),
            }

    # Get outputs
    outputs = node_config.get("outputs", [])

    return {
        "node_id": node_id,
        "component_type": node_config.get("key") or node_data.get("type"),
        "display_name": node_config.get("display_name"),
        "position": target_node.get("position"),
        "config": current_values,
        "outputs": [
            {"name": o.get("name"), "types": o.get("types", [])} for o in outputs
        ],
        "base_classes": node_config.get("base_classes", []),
    }


async def list_nodes(
    client: LangflowClient,
    flow_id: str,
) -> list[dict[str, Any]]:
    """List all nodes in a flow.

    Args:
        flow_id: Flow UUID

    Returns:
        List of node summaries
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    result = []
    for node in nodes:
        node_data = node.get("data", {})
        node_config = node_data.get("node", {})

        result.append(
            {
                "node_id": node.get("id"),
                "component_type": node_config.get("key") or node_data.get("type"),
                "display_name": node_config.get("display_name"),
                "position": node.get("position"),
            }
        )

    return result


async def add_note(
    client: LangflowClient,
    flow_id: str,
    content: str,
    position_x: float = 100,
    position_y: float = 100,
    width: int = 400,
    height: int = 200,
    background_color: str = "neutral",
) -> dict[str, Any]:
    """Add a sticky note/annotation to a flow.

    Args:
        flow_id: Flow UUID
        content: Note content (supports markdown)
        position_x: X position on canvas
        position_y: Y position on canvas
        width: Note width in pixels
        height: Note height in pixels
        background_color: Background color ("neutral", "transparent", "yellow", "blue", "green", "pink")

    Returns:
        Created note info
    """
    import nanoid

    # Generate note ID
    note_id = f"note-{nanoid.generate(size=5)}"

    # Build note structure
    note = {
        "id": note_id,
        "type": "noteNode",
        "position": {"x": position_x, "y": position_y},
        "data": {
            "id": note_id,
            "type": "note",
            "node": {
                "description": content,
                "display_name": "",
                "documentation": "",
                "template": {
                    "backgroundColor": background_color,
                },
            },
        },
        "measured": {
            "width": width,
            "height": height,
        },
        "selected": False,
        "dragging": False,
    }

    # Get current flow and add note
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    flow_data["nodes"].append(note)

    # Update flow
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "note_id": note_id,
        "content": content[:100] + "..." if len(content) > 100 else content,
        "position": {"x": position_x, "y": position_y},
        "message": "Note added successfully",
    }


async def update_note(
    client: LangflowClient,
    flow_id: str,
    note_id: str,
    content: str | None = None,
    background_color: str | None = None,
) -> dict[str, Any]:
    """Update a sticky note's content or appearance.

    Args:
        flow_id: Flow UUID
        note_id: Note ID (e.g., "note-28UlV")
        content: New content (markdown supported)
        background_color: New background color

    Returns:
        Update confirmation
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Find the note
    found = False
    for node in nodes:
        if node.get("id") == note_id and node.get("type") == "noteNode":
            node_config = node.get("data", {}).get("node", {})
            if content is not None:
                node_config["description"] = content
            if background_color is not None:
                node_config.setdefault("template", {})["backgroundColor"] = background_color
            found = True
            break

    if not found:
        raise ValueError(f"Note '{note_id}' not found in flow")

    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "note_id": note_id,
        "message": "Note updated successfully",
    }


def _get_node_dimensions(node: dict[str, Any]) -> tuple[float, float]:
    """Get node width and height, using stored values or defaults.

    React Flow stores actual rendered dimensions either as:
    - node.width / node.height (persisted when saved)
    - node.measured.width / node.measured.height (live from DOM)

    GenericNode default width is 384px
    Height varies significantly based on visible controls (300-700px typical)
    """
    # Try direct width/height properties first
    width = node.get("width")
    height = node.get("height")

    # Fall back to measured property
    if width is None:
        measured = node.get("measured", {})
        width = measured.get("width")
    if height is None:
        measured = node.get("measured", {})
        height = measured.get("height")

    # Default dimensions for GenericNode
    # Standard Langflow nodes are 384px wide
    # Height varies - use 550px as a safer default (many nodes are 400-700px)
    # It's better to assume nodes are taller and have extra space than to overlap
    return (width or 384, height or 550)


async def auto_arrange_flow(
    client: LangflowClient,
    flow_id: str,
    direction: str = "horizontal",
    spacing: float = 500,
    start_x: float = 100,
    start_y: float = 200,
    center_vertically: bool = True,
) -> dict[str, Any]:
    """Automatically arrange nodes in a flow for better visual layout.

    Uses a layered approach based on node dependencies:
    - Input nodes (no incoming edges) are placed on the left/top
    - Nodes are arranged in layers based on their distance from inputs
    - Output nodes end up on the right/bottom
    - Uses actual node dimensions for proper spacing

    NOTE: This provides basic topological arrangement. For complex flows with
    many connections, use analyze_flow_layout + move_nodes_batch for more
    control over positioning to avoid line crossings.

    Args:
        flow_id: Flow UUID
        direction: Layout direction ("horizontal" or "vertical")
        spacing: Gap between nodes in pixels (default 500 for generous readability)
        start_x: Starting X position
        start_y: Starting Y position
        center_vertically: If True, center nodes within each layer

    Returns:
        Arrangement summary
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Filter out note nodes for arrangement
    component_nodes = [n for n in nodes if n.get("type") != "noteNode"]

    if not component_nodes:
        return {"message": "No component nodes to arrange", "nodes_arranged": 0}

    # Build node lookup and get dimensions
    node_map = {n.get("id"): n for n in component_nodes}
    node_dims = {n.get("id"): _get_node_dimensions(n) for n in component_nodes}

    # Build adjacency info
    node_ids = set(node_map.keys())
    incoming: dict[str, list[str]] = {nid: [] for nid in node_ids}
    outgoing: dict[str, list[str]] = {nid: [] for nid in node_ids}

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in node_ids and target in node_ids:
            outgoing[source].append(target)
            incoming[target].append(source)

    # Find layers using topological sort
    layers: list[list[str]] = []
    remaining = set(node_ids)

    while remaining:
        # Find nodes with no remaining incoming edges
        layer = [
            nid for nid in remaining
            if all(src not in remaining for src in incoming[nid])
        ]

        if not layer:
            # Handle cycles - just take remaining nodes
            layer = list(remaining)

        layers.append(layer)
        remaining -= set(layer)

    # Calculate positions based on actual dimensions
    node_positions: dict[str, dict[str, float]] = {}

    if direction == "horizontal":
        # Horizontal: layers go left to right, nodes in layer stack vertically
        current_x = start_x

        for layer in layers:
            # Find max width in this layer for next layer offset
            max_width = max(node_dims[nid][0] for nid in layer)

            # Calculate total height of this layer
            layer_heights = [node_dims[nid][1] for nid in layer]
            total_height = sum(layer_heights) + spacing * (len(layer) - 1)

            # Starting Y position (centered or from start)
            if center_vertically:
                # Center the layer around a reasonable midpoint
                midpoint = start_y + 300  # Center around a reasonable y
                current_y = midpoint - total_height / 2
            else:
                current_y = start_y

            for node_id in layer:
                node_w, node_h = node_dims[node_id]
                node_positions[node_id] = {"x": current_x, "y": current_y}
                current_y += node_h + spacing

            current_x += max_width + spacing
    else:
        # Vertical: layers go top to bottom, nodes in layer spread horizontally
        current_y = start_y

        for layer in layers:
            # Find max height in this layer for next layer offset
            max_height = max(node_dims[nid][1] for nid in layer)

            # Calculate total width of this layer
            layer_widths = [node_dims[nid][0] for nid in layer]
            total_width = sum(layer_widths) + spacing * (len(layer) - 1)

            # Starting X position (centered or from start)
            if center_vertically:  # Works for both, centers main axis
                midpoint = start_x + 500
                current_x = midpoint - total_width / 2
            else:
                current_x = start_x

            for node_id in layer:
                node_w, node_h = node_dims[node_id]
                node_positions[node_id] = {"x": current_x, "y": current_y}
                current_x += node_w + spacing

            current_y += max_height + spacing

    # Apply positions to nodes
    for node in component_nodes:
        node_id = node.get("id")
        if node_id in node_positions:
            node["position"] = node_positions[node_id]

    # Update flow
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "nodes_arranged": len(component_nodes),
        "layers": len(layers),
        "direction": direction,
        "spacing": spacing,
        "message": f"Arranged {len(component_nodes)} nodes into {len(layers)} layers using actual node dimensions",
    }


async def move_nodes_batch(
    client: LangflowClient,
    flow_id: str,
    moves: list[dict[str, Any]],
) -> dict[str, Any]:
    """Move multiple nodes at once.

    Args:
        flow_id: Flow UUID
        moves: List of moves, each with {"node_id": str, "x": float, "y": float}

    Returns:
        Move summary
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Build lookup
    node_map = {n.get("id"): n for n in nodes}

    moved = []
    not_found = []

    for move in moves:
        node_id = move.get("node_id")
        x = move.get("x")
        y = move.get("y")

        if node_id in node_map:
            node_map[node_id]["position"] = {"x": x, "y": y}
            moved.append(node_id)
        else:
            not_found.append(node_id)

    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "moved": moved,
        "not_found": not_found,
        "message": f"Moved {len(moved)} nodes" + (f", {len(not_found)} not found" if not_found else ""),
    }


async def create_group(
    client: LangflowClient,
    flow_id: str,
    node_ids: list[str],
    name: str,
    description: str = "",
    exposed_fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Create a group from existing nodes.

    Groups bundle multiple nodes together and can expose selected fields
    from inner components for easy configuration.

    Args:
        flow_id: Flow UUID
        node_ids: List of node IDs to include in the group
        name: Display name for the group
        description: Description of what the group does
        exposed_fields: List of fields to expose on the group
            Each item: {"node_id": "Agent-xxx", "field": "temperature", "display_name": "Temperature"}

    Returns:
        Created group info
    """
    import nanoid

    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Find nodes to group
    node_map = {n.get("id"): n for n in nodes}
    nodes_to_group = []
    not_found = []

    for nid in node_ids:
        if nid in node_map:
            nodes_to_group.append(node_map[nid])
        else:
            not_found.append(nid)

    if not nodes_to_group:
        raise ValueError("No valid nodes found to group")

    # Find edges that are internal to the group
    node_id_set = set(node_ids)
    internal_edges = [
        e for e in edges
        if e.get("source") in node_id_set and e.get("target") in node_id_set
    ]

    # Find edges that connect to/from outside the group
    external_incoming = [
        e for e in edges
        if e.get("target") in node_id_set and e.get("source") not in node_id_set
    ]
    external_outgoing = [
        e for e in edges
        if e.get("source") in node_id_set and e.get("target") not in node_id_set
    ]

    # Calculate group position (center of grouped nodes)
    positions = [n.get("position", {"x": 0, "y": 0}) for n in nodes_to_group]
    avg_x = sum(p["x"] for p in positions) / len(positions)
    avg_y = sum(p["y"] for p in positions) / len(positions)

    # Get the component type of the first node for base classes
    first_node_data = nodes_to_group[0].get("data", {}).get("node", {})
    base_classes = first_node_data.get("base_classes", [])

    # Generate group ID
    group_id = f"Group-{nanoid.generate(size=5)}"

    # Build proxy template with exposed fields
    template = {}
    if exposed_fields:
        for field_spec in exposed_fields:
            inner_node_id = field_spec.get("node_id")
            field_name = field_spec.get("field")
            display_name = field_spec.get("display_name", f"{field_name} - {inner_node_id}")

            # Find the original field definition
            inner_node = node_map.get(inner_node_id)
            if inner_node:
                inner_template = inner_node.get("data", {}).get("node", {}).get("template", {})
                if field_name in inner_template:
                    # Create proxy field
                    original_field = copy.deepcopy(inner_template[field_name])
                    proxy_key = f"{field_name}_{inner_node_id}"
                    original_field["proxy"] = {
                        "id": inner_node_id,
                        "field": field_name
                    }
                    original_field["display_name"] = display_name
                    template[proxy_key] = original_field

    # Calculate inner flow viewport to fit grouped nodes
    inner_viewport = {
        "x": 0,
        "y": 0,
        "zoom": 1.0
    }

    # Build inner flow structure
    inner_flow = {
        "data": {
            "nodes": nodes_to_group,
            "edges": internal_edges,
            "viewport": inner_viewport
        },
        "name": name,
        "description": description,
        "id": nanoid.generate(size=5)
    }

    # Calculate group dimensions
    widths = [_get_node_dimensions(n)[0] for n in nodes_to_group]
    heights = [_get_node_dimensions(n)[1] for n in nodes_to_group]
    group_width = max(widths) + 100 if widths else 384
    group_height = sum(heights) / len(heights) + 100 if heights else 400

    # Build the group node
    group_node = {
        "id": group_id,
        "type": "genericNode",
        "position": {"x": avg_x, "y": avg_y},
        "width": group_width,
        "height": group_height,
        "data": {
            "id": group_id,
            "type": name.replace(" ", ""),  # Use name as type
            "node": {
                "display_name": name,
                "description": description or "Double-click to edit description",
                "documentation": "",
                "base_classes": base_classes,
                "template": template,
                "flow": inner_flow,
            }
        },
        "selected": False,
        "dragging": False,
    }

    # Remove grouped nodes from main flow
    remaining_nodes = [n for n in nodes if n.get("id") not in node_id_set]

    # Add group node
    remaining_nodes.append(group_node)

    # Update edges - remove internal edges, keep external edges pointing to group
    remaining_edges = []
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")

        if source in node_id_set and target in node_id_set:
            # Internal edge - skip
            continue
        elif target in node_id_set:
            # Edge coming into group - redirect to group
            new_edge = copy.deepcopy(edge)
            new_edge["target"] = group_id
            # Update target handle
            if "data" in new_edge and "targetHandle" in new_edge["data"]:
                new_edge["data"]["targetHandle"]["id"] = group_id
            remaining_edges.append(new_edge)
        elif source in node_id_set:
            # Edge going out of group - redirect from group
            new_edge = copy.deepcopy(edge)
            new_edge["source"] = group_id
            # Update source handle
            if "data" in new_edge and "sourceHandle" in new_edge["data"]:
                new_edge["data"]["sourceHandle"]["id"] = group_id
            remaining_edges.append(new_edge)
        else:
            # External edge - keep as is
            remaining_edges.append(edge)

    # Update flow
    flow_data["nodes"] = remaining_nodes
    flow_data["edges"] = remaining_edges
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "group_id": group_id,
        "name": name,
        "nodes_grouped": len(nodes_to_group),
        "exposed_fields": len(template),
        "not_found": not_found if not_found else None,
        "message": f"Created group '{name}' with {len(nodes_to_group)} nodes",
    }


async def ungroup(
    client: LangflowClient,
    flow_id: str,
    group_id: str,
) -> dict[str, Any]:
    """Ungroup a group, restoring its inner nodes to the flow.

    Args:
        flow_id: Flow UUID
        group_id: Group node ID to ungroup

    Returns:
        Ungroup result with list of restored nodes
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Find the group node
    group_node = None
    for node in nodes:
        if node.get("id") == group_id:
            group_node = node
            break

    if not group_node:
        raise ValueError(f"Group '{group_id}' not found")

    # Get inner flow data
    node_data = group_node.get("data", {}).get("node", {})
    inner_flow = node_data.get("flow", {})
    inner_data = inner_flow.get("data", {})
    inner_nodes = inner_data.get("nodes", [])
    inner_edges = inner_data.get("edges", [])

    if not inner_nodes:
        raise ValueError(f"Group '{group_id}' has no inner nodes")

    # Get group position for offset
    group_pos = group_node.get("position", {"x": 0, "y": 0})

    # Offset inner node positions relative to group position
    for inner_node in inner_nodes:
        inner_pos = inner_node.get("position", {"x": 0, "y": 0})
        inner_node["position"] = {
            "x": group_pos["x"] + inner_pos["x"],
            "y": group_pos["y"] + inner_pos["y"]
        }

    # Get IDs of restored nodes
    restored_ids = {n.get("id") for n in inner_nodes}

    # Remove group node, add inner nodes
    new_nodes = [n for n in nodes if n.get("id") != group_id]
    new_nodes.extend(inner_nodes)

    # Handle edges
    new_edges = []
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")

        if source == group_id or target == group_id:
            # Skip edges connected to group - they need to be reconnected manually
            # (We could try to restore them but it's complex)
            continue
        else:
            new_edges.append(edge)

    # Add inner edges
    new_edges.extend(inner_edges)

    # Update flow
    flow_data["nodes"] = new_nodes
    flow_data["edges"] = new_edges
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "ungrouped": group_id,
        "restored_nodes": list(restored_ids),
        "restored_edges": len(inner_edges),
        "message": f"Ungrouped '{group_id}', restored {len(inner_nodes)} nodes",
    }


async def update_group(
    client: LangflowClient,
    flow_id: str,
    group_id: str,
    name: str | None = None,
    description: str | None = None,
    exposed_fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Update group properties.

    Args:
        flow_id: Flow UUID
        group_id: Group node ID
        name: New display name
        description: New description
        exposed_fields: New list of exposed fields
            Each item: {"node_id": "Agent-xxx", "field": "temperature", "display_name": "Temperature"}

    Returns:
        Update confirmation
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])

    # Find the group node
    group_node = None
    for node in nodes:
        if node.get("id") == group_id:
            group_node = node
            break

    if not group_node:
        raise ValueError(f"Group '{group_id}' not found")

    node_config = group_node.get("data", {}).get("node", {})

    updated = []

    if name is not None:
        node_config["display_name"] = name
        updated.append("name")

    if description is not None:
        node_config["description"] = description
        updated.append("description")

    if exposed_fields is not None:
        # Get inner flow nodes for field lookup
        inner_flow = node_config.get("flow", {})
        inner_nodes = inner_flow.get("data", {}).get("nodes", [])
        inner_node_map = {n.get("id"): n for n in inner_nodes}

        # Build new template with exposed fields
        new_template = {}
        for field_spec in exposed_fields:
            inner_node_id = field_spec.get("node_id")
            field_name = field_spec.get("field")
            display_name = field_spec.get("display_name", f"{field_name} - {inner_node_id}")

            inner_node = inner_node_map.get(inner_node_id)
            if inner_node:
                inner_template = inner_node.get("data", {}).get("node", {}).get("template", {})
                if field_name in inner_template:
                    original_field = copy.deepcopy(inner_template[field_name])
                    proxy_key = f"{field_name}_{inner_node_id}"
                    original_field["proxy"] = {
                        "id": inner_node_id,
                        "field": field_name
                    }
                    original_field["display_name"] = display_name
                    new_template[proxy_key] = original_field

        node_config["template"] = new_template
        updated.append(f"exposed_fields ({len(new_template)} fields)")

    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "group_id": group_id,
        "updated": updated,
        "message": f"Updated group: {', '.join(updated)}",
    }


def _categorize_node(node: dict[str, Any]) -> str:
    """Categorize a node by its role in the flow.

    Returns one of: 'input', 'output', 'agent', 'model', 'tool', 'memory',
    'retriever', 'embedding', 'processing', 'other'
    """
    node_data = node.get("data", {})
    node_config = node_data.get("node", {})
    component_type = node_config.get("key") or node_data.get("type", "")
    display_name = (node_config.get("display_name") or "").lower()

    type_lower = component_type.lower()

    # Input/Output detection
    if "input" in type_lower or "chatinput" in type_lower:
        return "input"
    if "output" in type_lower or "chatoutput" in type_lower:
        return "output"

    # Agent detection
    if "agent" in type_lower:
        return "agent"

    # Model detection
    if any(x in type_lower for x in ["model", "openai", "anthropic", "groq", "ollama", "llm"]):
        return "model"

    # Tool detection
    if "tool" in type_lower or "calculator" in type_lower or "search" in type_lower:
        return "tool"

    # Memory detection
    if "memory" in type_lower:
        return "memory"

    # Retriever/VectorStore detection
    if any(x in type_lower for x in ["retriever", "vector", "qdrant", "pinecone", "chroma", "weaviate"]):
        return "retriever"

    # Embedding detection
    if "embed" in type_lower:
        return "embedding"

    # Processing (prompts, parsers, etc.)
    if any(x in type_lower for x in ["prompt", "parser", "splitter", "loader"]):
        return "processing"

    return "other"


async def analyze_flow_layout(
    client: LangflowClient,
    flow_id: str,
) -> dict[str, Any]:
    """Analyze a flow and provide layout recommendations.

    This tool examines the flow structure, categorizes nodes, traces data flow,
    and provides detailed information to help you position nodes optimally.

    Use this to understand the flow before using move_node or move_nodes_batch
    to position components.

    Layout Guidelines:
    - Place input nodes (ChatInput) on the LEFT side
    - Place output nodes (ChatOutput) on the RIGHT side
    - Data flows LEFT to RIGHT following connections
    - Place related nodes near each other (e.g., model near agent)
    - Group supporting nodes (tools, memory) near their parent
    - Maintain clear sight lines - avoid overlapping connection paths
    - Use vertical spacing for parallel branches
    - Nodes that share a target should be stacked vertically

    Returns:
        Detailed flow analysis with node info, connections, and recommendations
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Filter out notes
    component_nodes = [n for n in nodes if n.get("type") != "noteNode"]
    note_nodes = [n for n in nodes if n.get("type") == "noteNode"]

    if not component_nodes:
        return {"message": "No component nodes in flow", "nodes": []}

    # Build node info
    node_map = {n.get("id"): n for n in component_nodes}
    node_dims = {n.get("id"): _get_node_dimensions(n) for n in component_nodes}
    node_categories = {n.get("id"): _categorize_node(n) for n in component_nodes}

    # Build adjacency
    incoming: dict[str, list[str]] = {nid: [] for nid in node_map}
    outgoing: dict[str, list[str]] = {nid: [] for nid in node_map}

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in node_map and target in node_map:
            outgoing[source].append(target)
            incoming[target].append(source)

    # Calculate depth (distance from inputs)
    depths: dict[str, int] = {}
    queue = [(nid, 0) for nid in node_map if not incoming[nid]]
    visited = set()

    while queue:
        nid, depth = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        depths[nid] = depth
        for target in outgoing[nid]:
            queue.append((target, depth + 1))

    # Assign depth 0 to any unvisited nodes (isolated or cyclic)
    for nid in node_map:
        if nid not in depths:
            depths[nid] = 0

    # Build COMPACT node info - just essential positioning data
    node_info = []
    for node in component_nodes:
        nid = node.get("id")
        node_data = node.get("data", {})
        node_config = node_data.get("node", {})
        width, height = node_dims[nid]
        pos = node.get("position", {})
        x, y = pos.get("x", 0), pos.get("y", 0)

        # Compact format: id, name, position, size, connections
        node_info.append({
            "id": nid,
            "name": node_config.get("display_name") or node_data.get("type", "?"),
            "cat": node_categories[nid],  # Short key
            "x": round(x), "y": round(y), "w": round(width), "h": round(height),
            "depth": depths.get(nid, 0),
            "in": incoming[nid] if incoming[nid] else None,  # Omit empty
            "out": outgoing[nid] if outgoing[nid] else None,
        })

    node_info.sort(key=lambda x: (x["depth"], x["cat"]))

    # Group nodes by category
    category_groups: dict[str, list[str]] = {}
    for nid, cat in node_categories.items():
        category_groups.setdefault(cat, []).append(nid)

    # Find the main flow path (longest path from input to output)
    main_path = []
    input_nodes = [nid for nid, cat in node_categories.items() if cat == "input"]
    if input_nodes:
        # BFS to find path to output
        def find_path(start: str) -> list[str]:
            from collections import deque
            queue = deque([(start, [start])])
            longest = []
            while queue:
                current, path = queue.popleft()
                if node_categories.get(current) == "output" and len(path) > len(longest):
                    longest = path
                for next_node in outgoing[current]:
                    if next_node not in path:
                        queue.append((next_node, path + [next_node]))
            return longest if longest else [start]

        for inp in input_nodes:
            path = find_path(inp)
            if len(path) > len(main_path):
                main_path = path

    # Detect flow pattern
    categories = set(node_categories.values())
    num_tools = sum(1 for c in node_categories.values() if c == "tool")

    pattern = "chain"
    if "agent" in categories and "retriever" in categories:
        pattern = "rag"
    elif "agent" in categories and num_tools >= 3:
        pattern = "tool-heavy-agent"
    elif "agent" in categories:
        pattern = "agent"

    # Generate spacing recommendations
    max_depth = max(depths.values()) if depths else 0

    # Analyze potential line crossings
    # Calculate height stats
    max_height = max(node_dims[nid][1] for nid in node_map) if node_map else 600

    # Check for collisions - nodes blocking connection lines (COMPACT)
    collisions = []
    for edge in edges:
        src, tgt = edge.get("source"), edge.get("target")
        if src not in node_map or tgt not in node_map:
            continue

        src_node, tgt_node = node_map[src], node_map[tgt]
        src_pos, tgt_pos = src_node.get("position", {}), tgt_node.get("position", {})
        if not src_pos or not tgt_pos:
            continue

        src_x, src_y = src_pos.get("x", 0), src_pos.get("y", 0)
        tgt_x, tgt_y = tgt_pos.get("x", 0), tgt_pos.get("y", 0)
        src_w, src_h = node_dims.get(src, (384, 550))
        tgt_w, tgt_h = node_dims.get(tgt, (384, 550))

        # Line danger zone: from right edge of source to left edge of target
        dz_x1, dz_x2 = src_x + src_w + 7, tgt_x - 7
        dz_y1 = min(src_y + src_h/2, tgt_y + tgt_h/2) - 50
        dz_y2 = max(src_y + src_h/2, tgt_y + tgt_h/2) + 50

        # Check each other node for collision
        for nid, node in node_map.items():
            if nid in (src, tgt):
                continue
            np = node.get("position", {})
            nx, ny = np.get("x", 0), np.get("y", 0)
            nw, nh = node_dims.get(nid, (384, 550))

            # Rectangle intersection
            if nx < dz_x2 and nx + nw > dz_x1 and ny < dz_y2 and ny + nh > dz_y1:
                collisions.append({
                    "node": nid,
                    "blocks": f"{src}→{tgt}",
                    "node_y_range": [round(ny), round(ny + nh)],
                    "line_y_range": [round(dz_y1), round(dz_y2)],
                    "fix": f"Move ABOVE y<{round(dz_y1 - nh)} or BELOW y>{round(dz_y2)}"
                })

    # Minimal suggested X positions by depth
    suggested_positions: dict[str, dict[str, float]] = {}
    x_per_depth = 100
    for d in range(max_depth + 1):
        nodes_at_depth = [nid for nid, depth in depths.items() if depth == d]
        y_pos = 1000
        for nid in nodes_at_depth:
            suggested_positions[nid] = {"x": x_per_depth, "y": y_pos}
            y_pos += node_dims[nid][1] + 600
        x_per_depth += 1184  # 384 + 800 gap

    # COMPACT return - only essential data
    return {
        "nodes": node_info,  # Each has: id, name, cat, x, y, w, h, depth, in, out
        "main_path": main_path,
        "collisions": collisions[:15],  # Nodes blocking lines - FIX THESE FIRST
        "suggested": suggested_positions,
        "max_height": round(max_height),
        "rules": f"X spacing: 800-1000px between depths. Y spacing: {round(max_height)}+500px between nodes. Fix collisions by moving nodes ABOVE or BELOW the line_y_range.",
    }


async def get_layout_suggestions(
    client: LangflowClient,
    flow_id: str,
) -> dict[str, Any]:
    """Get detailed layout suggestions for a flow without applying changes.

    This tool analyzes the current layout and provides:
    - Detected clusters (logical groupings of nodes)
    - Main data flow path
    - Line collision problems (nodes blocking connection lines)
    - Layout quality score
    - Specific suggestions for improvement

    Use this to understand layout issues before using move_nodes_batch to fix them.

    Args:
        flow_id: Flow UUID

    Returns:
        Analysis with clusters, issues, and actionable suggestions
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {"nodes": [], "edges": []})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Filter component nodes
    component_nodes = [n for n in nodes if n.get("type") != "noteNode"]

    if not component_nodes:
        return {"message": "No component nodes in flow"}

    # Build graph and analyze
    node_graph = build_node_graph(component_nodes, edges)
    clusters = detect_clusters(node_graph)
    main_path = find_main_path(node_graph)

    # Get current positions
    current_positions = {
        n.get("id"): (n.get("position", {}).get("x", 0), n.get("position", {}).get("y", 0))
        for n in component_nodes
    }

    # Find collisions with current layout
    collisions = find_line_collisions(current_positions, node_graph, edges)

    # Score current layout
    score = score_layout(current_positions, node_graph, edges)

    # Generate suggestions
    suggestions = []

    if score["line_collisions"] > 0:
        suggestions.append({
            "priority": "high",
            "issue": f"{score['line_collisions']} nodes are blocking connection lines",
            "fix": "Move the blocking nodes above or below the connection line path",
            "details": [
                f"Node '{c['node_name']}' blocks {c['blocks_connection']}: {c['suggestion']}"
                for c in collisions[:5]
            ],
        })

    if score["node_overlaps"] > 0:
        suggestions.append({
            "priority": "high",
            "issue": f"{score['node_overlaps']} nodes are overlapping",
            "fix": "Increase spacing between nodes",
        })

    if score["horizontal_flow_violations"] > 0:
        suggestions.append({
            "priority": "medium",
            "issue": f"{score['horizontal_flow_violations']} connections go right-to-left",
            "fix": "Rearrange nodes so data flows left-to-right",
        })

    # Check spacing
    x_positions = sorted(p[0] for p in current_positions.values())
    if len(x_positions) > 1:
        min_gap = min(x_positions[i+1] - x_positions[i] for i in range(len(x_positions)-1))
        if min_gap < 500:
            suggestions.append({
                "priority": "medium",
                "issue": f"Minimum horizontal gap is only {min_gap:.0f}px (should be 600-1000px)",
                "fix": "Increase horizontal spacing between nodes",
            })

    # Build cluster info
    cluster_info = []
    for cluster in clusters:
        cluster_info.append({
            "name": cluster.name,
            "role": cluster.role,
            "nodes": [
                {"id": nid, "name": node_graph[nid].display_name}
                for nid in cluster.node_ids if nid in node_graph
            ],
        })

    return {
        "layout_score": score["overall_score"],
        "clusters": cluster_info,
        "main_path": [
            {"id": nid, "name": node_graph[nid].display_name}
            for nid in main_path if nid in node_graph
        ],
        "issues": {
            "line_collisions": score["line_collisions"],
            "node_overlaps": score["node_overlaps"],
            "flow_violations": score["horizontal_flow_violations"],
        },
        "suggestions": suggestions,
        "recommended_action": (
            "Use move_nodes_batch to fix layout issues" if suggestions
            else "Layout looks good!"
        ),
    }
