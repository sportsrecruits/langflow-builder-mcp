"""Pydantic models for Langflow flow structures."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Component Schema Models
# ============================================================================


class InputField(BaseModel):
    """Represents an input field on a component."""

    name: str
    display_name: str = ""
    type: str = "str"
    input_types: list[str] = Field(default_factory=list)
    required: bool = False
    advanced: bool = False
    value: Any = None
    info: str = ""
    options: list[str] | None = None

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, v: Any) -> list[str] | None:
        """Normalize options to list of strings.

        Langflow can return options as either:
        - list of strings: ["option1", "option2"]
        - list of dicts: [{"name": "option1", "icon": "..."}, ...]
        """
        if v is None:
            return None
        if not isinstance(v, list):
            return None

        normalized = []
        for item in v:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict) and "name" in item:
                normalized.append(item["name"])
            else:
                # Skip items we can't normalize
                continue
        return normalized if normalized else None


class OutputField(BaseModel):
    """Represents an output on a component."""

    name: str
    display_name: str = ""
    types: list[str] = Field(default_factory=list)
    method: str = ""
    selected: str | None = None


class ComponentSchema(BaseModel):
    """Schema for a Langflow component type."""

    name: str
    display_name: str = ""
    description: str = ""
    category: str = ""
    icon: str = ""
    inputs: dict[str, InputField] = Field(default_factory=dict)
    outputs: list[OutputField] = Field(default_factory=list)
    base_classes: list[str] = Field(default_factory=list)
    output_types: list[str] = Field(default_factory=list)


class ComponentSummary(BaseModel):
    """Summary of a component for listing."""

    name: str
    display_name: str
    description: str = ""
    category: str = ""
    icon: str = ""


# ============================================================================
# Flow Structure Models
# ============================================================================


class Position(BaseModel):
    """Node position on the canvas."""

    x: float = 0
    y: float = 0


class SourceHandle(BaseModel):
    """Source handle for an edge (output side)."""

    dataType: str
    id: str
    name: str
    output_types: list[str] = Field(default_factory=list)


class TargetHandle(BaseModel):
    """Target handle for an edge (input side)."""

    fieldName: str
    id: str
    inputTypes: list[str] | None = None
    type: str = "other"


class EdgeData(BaseModel):
    """Data embedded in an edge."""

    sourceHandle: SourceHandle
    targetHandle: TargetHandle


class Edge(BaseModel):
    """Edge connecting two nodes."""

    id: str
    source: str
    target: str
    sourceHandle: str = ""  # Serialized handle string
    targetHandle: str = ""  # Serialized handle string
    data: EdgeData
    selected: bool = False
    animated: bool = False
    className: str = ""


class NodeTemplate(BaseModel):
    """Template containing input field configurations."""

    # This is dynamically populated from component schema
    # Keys are field names, values are field configurations

    class Config:
        extra = "allow"


class NodeConfig(BaseModel):
    """Node configuration within data.node."""

    template: dict[str, Any] = Field(default_factory=dict)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    base_classes: list[str] = Field(default_factory=list)
    display_name: str = ""
    description: str = ""
    icon: str = ""
    key: str = ""  # Component type name
    category: str = ""
    frozen: bool = False
    edited: bool = False
    minimized: bool = False


class NodeData(BaseModel):
    """Data section of a node."""

    id: str
    node: NodeConfig
    type: str = ""  # "note" for note nodes, empty for generic
    showNode: bool = True
    selected_output: str = ""


class Node(BaseModel):
    """A node in a flow."""

    id: str
    type: str = "genericNode"  # "genericNode" or "noteNode"
    position: Position
    data: NodeData
    selected: bool = False
    dragging: bool = False
    measured: dict[str, int] | None = None


class Viewport(BaseModel):
    """Canvas viewport settings."""

    x: float = 0
    y: float = 0
    zoom: float = 1


class FlowData(BaseModel):
    """The data section of a flow containing nodes and edges."""

    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    viewport: Viewport = Field(default_factory=Viewport)


class Flow(BaseModel):
    """Complete flow structure."""

    id: str = ""
    name: str
    description: str | None = None
    data: FlowData = Field(default_factory=FlowData)
    is_component: bool = False
    endpoint_name: str | None = None
    folder_id: str | None = None
    user_id: str | None = None


class FlowSummary(BaseModel):
    """Summary of a flow for listing."""

    id: str
    name: str
    description: str | None = None
    is_component: bool = False
    endpoint_name: str | None = None
    folder_id: str | None = None


# ============================================================================
# Tool Result Models
# ============================================================================


class ValidationResult(BaseModel):
    """Result of connection validation."""

    is_valid: bool
    error: str | None = None
    matched_types: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)


class NodeResult(BaseModel):
    """Result of node operation."""

    node_id: str
    component_type: str
    position: Position
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeResult(BaseModel):
    """Result of edge operation."""

    edge_id: str
    source_node: str
    source_output: str
    target_node: str
    target_input: str
    matched_types: list[str] = Field(default_factory=list)


class ConnectionInfo(BaseModel):
    """Information about a connection in a flow."""

    edge_id: str
    source_node_id: str
    source_component_type: str
    source_output: str
    target_node_id: str
    target_component_type: str
    target_input: str


class CompatibleConnection(BaseModel):
    """A compatible connection possibility."""

    node_id: str
    component_type: str
    display_name: str
    port_name: str
    port_display_name: str
    types: list[str]
