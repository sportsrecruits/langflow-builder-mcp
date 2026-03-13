"""ID generators for Langflow flow elements."""

import json
from typing import Any

import nanoid


def generate_node_id(component_type: str) -> str:
    """Generate a node ID in Langflow format.

    Format: {ComponentType}-{nanoid(5)}
    Example: "Agent-D0Kx2"

    Args:
        component_type: Component type name

    Returns:
        Generated node ID
    """
    random_suffix = nanoid.generate(size=5)
    return f"{component_type}-{random_suffix}"


def generate_source_handle(
    node_id: str,
    component_type: str,
    output_name: str,
    output_types: list[str],
) -> dict[str, Any]:
    """Generate source handle data for an edge.

    Args:
        node_id: Source node ID
        component_type: Component type of source node
        output_name: Name of the output
        output_types: Types this output produces

    Returns:
        Source handle dictionary
    """
    return {
        "dataType": component_type,
        "id": node_id,
        "name": output_name,
        "output_types": output_types,
    }


def generate_target_handle(
    node_id: str,
    field_name: str,
    input_types: list[str],
    field_type: str = "other",
    proxy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate target handle data for an edge.

    Args:
        node_id: Target node ID
        field_name: Name of the input field
        input_types: Types this input accepts
        field_type: Field type (usually "other" or "str")
        proxy: Optional proxy configuration for group fields

    Returns:
        Target handle dictionary
    """
    handle: dict[str, Any] = {
        "fieldName": field_name,
        "id": node_id,
        "inputTypes": input_types,
        "type": field_type,
    }
    # Add proxy if present (used in groups to redirect to inner nodes)
    # This must be included for Langflow validation to pass
    if proxy is not None:
        handle["proxy"] = proxy
    return handle


def _custom_stringify(obj: Any) -> str:
    """Recursively stringify an object with sorted keys.

    This matches Langflow's customStringify function which sorts object keys
    alphabetically to ensure consistent handle comparison.

    Args:
        obj: Value to stringify

    Returns:
        JSON string with sorted keys and no extra whitespace
    """
    if obj is None:
        return "null"

    if isinstance(obj, bool):
        return "true" if obj else "false"

    if isinstance(obj, (int, float)):
        return json.dumps(obj)

    if isinstance(obj, str):
        return json.dumps(obj)

    if isinstance(obj, list):
        items = ",".join(_custom_stringify(item) for item in obj)
        return f"[{items}]"

    if isinstance(obj, dict):
        # Sort keys alphabetically - this is critical for Langflow compatibility
        sorted_keys = sorted(obj.keys())
        pairs = ",".join(
            f'"{key}":{_custom_stringify(obj[key])}' for key in sorted_keys
        )
        return f"{{{pairs}}}"

    # Fallback for other types
    return json.dumps(obj)


def serialize_handle(handle: dict[str, Any]) -> str:
    """Serialize a handle to string format used in edge sourceHandle/targetHandle.

    Langflow uses a special character 'œ' instead of quotes in serialized handles.
    Keys must be sorted alphabetically to match Langflow's customStringify function.

    Args:
        handle: Handle dictionary

    Returns:
        Serialized handle string with sorted keys and œ instead of quotes
    """
    # Use custom stringify with sorted keys (matching Langflow's customStringify)
    json_str = _custom_stringify(handle)
    return json_str.replace('"', "œ")


def generate_edge_id(
    source_handle: dict[str, Any],
    target_handle: dict[str, Any],
) -> str:
    """Generate edge ID in reactflow format.

    Based on edge IDs in actual Langflow flow JSON files.

    Args:
        source_handle: Source handle dictionary
        target_handle: Target handle dictionary

    Returns:
        Generated edge ID
    """
    source_serialized = serialize_handle(source_handle)
    target_serialized = serialize_handle(target_handle)
    source_id = source_handle.get("id", "")
    target_id = target_handle.get("id", "")
    return f"reactflow__edge-{source_id}{source_serialized}-{target_id}{target_serialized}"


def build_node_structure(
    node_id: str,
    component_type: str,
    position_x: float,
    position_y: float,
    template: dict[str, Any],
    outputs: list[dict[str, Any]],
    base_classes: list[str],
    display_name: str,
    description: str = "",
    icon: str = "",
    category: str = "",
) -> dict[str, Any]:
    """Build complete node structure for a flow.

    Args:
        node_id: Node ID
        component_type: Component type name
        position_x: X position on canvas
        position_y: Y position on canvas
        template: Template with input field configurations
        outputs: List of output definitions
        base_classes: Component base classes
        display_name: Display name for the component
        description: Component description
        icon: Component icon
        category: Component category

    Returns:
        Complete node structure dictionary
    """
    return {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": position_x, "y": position_y},
        "data": {
            "id": node_id,
            "showNode": True,
            "type": component_type,
            "node": {
                "template": template,
                "outputs": outputs,
                "base_classes": base_classes,
                "display_name": display_name,
                "description": description,
                "icon": icon,
                "key": component_type,
                "category": category,
                "frozen": False,
                "edited": False,
                "minimized": False,
            },
        },
        "selected": False,
        "dragging": False,
    }


def build_edge_structure(
    source_node_id: str,
    source_component_type: str,
    source_output_name: str,
    source_output_types: list[str],
    target_node_id: str,
    target_field_name: str,
    target_input_types: list[str],
    target_field_type: str = "other",
    target_proxy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build complete edge structure for a flow.

    Args:
        source_node_id: Source node ID
        source_component_type: Component type of source node
        source_output_name: Name of the output
        source_output_types: Types the output produces
        target_node_id: Target node ID
        target_field_name: Name of the target input field
        target_input_types: Types the target input accepts
        target_field_type: Field type of the target
        target_proxy: Optional proxy configuration for group fields

    Returns:
        Complete edge structure dictionary
    """
    source_handle = generate_source_handle(
        source_node_id, source_component_type, source_output_name, source_output_types
    )
    target_handle = generate_target_handle(
        target_node_id, target_field_name, target_input_types, target_field_type, target_proxy
    )

    return {
        "id": generate_edge_id(source_handle, target_handle),
        "source": source_node_id,
        "target": target_node_id,
        "sourceHandle": serialize_handle(source_handle),
        "targetHandle": serialize_handle(target_handle),
        "data": {
            "sourceHandle": source_handle,
            "targetHandle": target_handle,
        },
        "selected": False,
        "animated": False,
        "className": "",
    }
