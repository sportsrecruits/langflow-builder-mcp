"""MCP Server for Langflow Flow Building.

This server exposes tools for building and modifying Langflow flows
through natural language commands.
"""

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .backup import create_backup
from .client import LangflowClient, get_client
from .concepts import CONCEPTS
from .instructions import INSTRUCTIONS
from .schema_cache import ComponentSchemaCache, get_schema_cache
from .tools import build as build_tools
from .tools import components as comp_tools
from .tools import edges as edge_tools
from .tools import flows as flow_tools
from .tools import nodes as node_tools
from .tools import source as source_tools
from .validator import ConnectionValidator, get_validator


async def _backup_if_enabled(flow_id: str, reason: str) -> dict[str, Any] | None:
    """Create a backup if auto-backup is enabled."""
    return await create_backup(_get_client(), flow_id, reason)


# Initialize the MCP server
mcp = FastMCP(
    name="langflow-builder",
    instructions=INSTRUCTIONS,
)


# Global instances (initialized lazily)
_client: LangflowClient | None = None
_cache: ComponentSchemaCache | None = None
_validator: ConnectionValidator | None = None


def _get_client() -> LangflowClient:
    """Get or create the Langflow API client."""
    global _client
    if _client is None:
        _client = get_client()
    return _client


def _get_cache() -> ComponentSchemaCache:
    """Get or create the component schema cache."""
    global _cache
    if _cache is None:
        _cache = get_schema_cache(_get_client())
    return _cache


def _get_validator() -> ConnectionValidator:
    """Get or create the connection validator."""
    global _validator
    if _validator is None:
        _validator = get_validator(_get_cache())
    return _validator


# ============================================================================
# Component Discovery Tools
# ============================================================================


@mcp.tool()
async def list_component_categories() -> str:
    """List all available component categories.

    Returns categories like: agents, models, vectorstores, embeddings,
    data, helpers, input_output, tools, processing, etc.
    """
    categories = await comp_tools.list_component_categories(_get_cache())
    return json.dumps({"categories": categories}, indent=2)


@mcp.tool()
async def list_components(category: str) -> str:
    """List all components in a category with basic info.

    Args:
        category: Category name (e.g., "agents", "models", "vectorstores")
    """
    components = await comp_tools.list_components_in_category(_get_cache(), category)
    return json.dumps({"components": components, "count": len(components)}, indent=2)


@mcp.tool()
async def get_component_schema(component_type: str) -> str:
    """Get full schema for a component including all inputs and outputs.

    Use this to understand what configuration options a component has
    before adding it to a flow.

    Args:
        component_type: Component type name (e.g., "Agent", "ChatInput", "OpenAIModel")
    """
    schema = await comp_tools.get_component_schema(_get_cache(), component_type)
    return json.dumps(schema, indent=2)


@mcp.tool()
async def search_components(query: str) -> str:
    """Search components by name or description.

    Args:
        query: Search query (e.g., "openai", "vector", "qdrant", "chat")
    """
    results = await comp_tools.search_components(_get_cache(), query)
    return json.dumps({"results": results, "count": len(results)}, indent=2)


# ============================================================================
# Flow Management Tools
# ============================================================================


@mcp.tool()
async def list_flows() -> str:
    """List all flows accessible to the current user.

    Returns flow summaries with id, name, description.
    """
    flows = await flow_tools.list_flows(_get_client())
    return json.dumps({"flows": flows, "count": len(flows)}, indent=2)


@mcp.tool()
async def get_flow(flow_id: str) -> str:
    """Get complete flow structure including all nodes and edges.

    Use this to understand the current state of a flow before making changes.

    Args:
        flow_id: UUID of the flow
    """
    flow = await flow_tools.get_flow(_get_client(), flow_id)
    return json.dumps(flow, indent=2)


@mcp.tool()
async def create_flow(name: str, description: str = "") -> str:
    """Create a new empty flow.

    After creating, use add_node and connect_nodes to build the flow.

    Args:
        name: Flow name
        description: Optional description
    """
    result = await flow_tools.create_flow(_get_client(), name, description or None)
    return json.dumps(result, indent=2)


@mcp.tool()
async def delete_flow(flow_id: str) -> str:
    """Delete a flow permanently.

    WARNING: This cannot be undone.

    Args:
        flow_id: Flow UUID
    """
    result = await flow_tools.delete_flow(_get_client(), flow_id)
    return json.dumps(result, indent=2)


@mcp.tool()
async def duplicate_flow(flow_id: str, new_name: str = "") -> str:
    """Duplicate an existing flow.

    Args:
        flow_id: Flow UUID to duplicate
        new_name: Name for the new flow (defaults to "Copy of {original_name}")
    """
    result = await flow_tools.duplicate_flow(
        _get_client(), flow_id, new_name or None
    )
    return json.dumps(result, indent=2)


# ============================================================================
# Build/Execution Tools
# ============================================================================


@mcp.tool()
async def build_flow(
    flow_id: str,
    input_value: str = "",
    input_type: str = "chat",
    wait_for_completion: bool = True,
    timeout_seconds: int = 120,
) -> str:
    """Build and execute a flow, running all components.

    This is the key tool that makes changes take effect! After using add_node,
    connect_nodes, update_node, etc., call this to actually execute the flow
    and produce outputs.

    The build process:
    1. Resolves all component dependencies
    2. Executes components in topological order
    3. Passes data through connections
    4. Produces final outputs

    Args:
        flow_id: Flow UUID to build
        input_value: Optional input value for ChatInput/TextInput components
        input_type: Type of input - "chat", "text", or "any" (default: "chat")
        wait_for_completion: If True, wait for build to complete and return results.
            If False, return immediately with job_id for polling.
        timeout_seconds: Max seconds to wait for completion (default: 120)

    Returns:
        Build results including outputs from all components, or job_id if not waiting
    """
    result = await build_tools.build_flow(
        _get_client(),
        flow_id,
        input_value=input_value if input_value else None,
        input_type=input_type,
        wait_for_completion=wait_for_completion,
        timeout_seconds=timeout_seconds,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def build_node(
    flow_id: str,
    node_id: str,
) -> str:
    """Build a single node (vertex) in a flow.

    Use this to execute just one component without running the entire flow.
    Useful for testing a specific component or when you only need one
    component's output.

    Note: The node's upstream dependencies must already be built for this
    to produce meaningful results.

    Args:
        flow_id: Flow UUID
        node_id: Node ID to build (e.g., "Agent-D0Kx2")

    Returns:
        Build result for the node including its outputs
    """
    result = await build_tools.build_node(_get_client(), flow_id, node_id)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_build_status(job_id: str) -> str:
    """Get the status and events for a build job.

    Use this to poll for completion when build_flow was called with
    wait_for_completion=False.

    Args:
        job_id: Build job ID from build_flow response

    Returns:
        Build events and current status
    """
    result = await build_tools.get_build_status(_get_client(), job_id)
    return json.dumps(result, indent=2)


# ============================================================================
# Node Manipulation Tools
# ============================================================================


@mcp.tool()
async def add_node(
    flow_id: str,
    component_type: str,
    position_x: float = 100,
    position_y: float = 100,
    config: dict | None = None,
    tool_mode: bool = False,
) -> str:
    """Add a new node to a flow.

    NOTE: The node is added to the flow but NOT executed. The flow must be RUN
    for the component to produce outputs.

    Args:
        flow_id: Target flow UUID
        component_type: Component type (e.g., "Agent", "ChatInput", "OpenAIModel")
            Use search_components() first to verify the component exists.
        position_x: X position on canvas (default 100)
        position_y: Y position on canvas (default 100)
        config: Template values to override defaults
            Example: {"model_name": "gpt-4o", "temperature": 0.7}
        tool_mode: If True, enable tool_mode on the node so it can be used as an
            Agent tool. This transforms the node's outputs to include
            "component_as_tool" (type: Tool). After adding, connect the
            "component_as_tool" output to the Agent's "tools" input.
    """
    await _backup_if_enabled(flow_id, f"add_node: {component_type}")
    config_dict = config or {}
    result = await node_tools.add_node(
        _get_client(),
        _get_cache(),
        flow_id,
        component_type,
        position_x,
        position_y,
        config_dict,
        tool_mode,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def add_custom_component(
    flow_id: str,
    code: str,
    position_x: float = 100,
    position_y: float = 100,
    tool_mode: bool = False,
) -> str:
    """Add a custom component to a flow using inline Python code.

    THIS IS THE PREFERRED WAY TO CREATE CUSTOM COMPONENTS. No server restart needed!

    The code is sent to the Langflow API which dynamically evaluates it,
    builds the full node template (inputs, outputs, types), and returns it.
    The resulting node works immediately — no restart, no file creation.

    The code should define a Component subclass. Example:
    ```python
    from langflow.custom import Component
    from langflow.io import MessageTextInput, Output
    from langflow.schema.message import Message

    class MyComponent(Component):
        display_name = "My Component"
        description = "What this does"

        inputs = [
            MessageTextInput(name="input_text", display_name="Input"),
        ]

        outputs = [
            Output(display_name="Result", name="result", method="process"),
        ]

        def process(self) -> Message:
            return Message(text=self.input_text.upper())
    ```

    Args:
        flow_id: Target flow UUID
        code: Python code defining the Component subclass
        position_x: X position on canvas (default 100)
        position_y: Y position on canvas (default 100)
        tool_mode: If True, enable tool_mode so the component can be used as
            an Agent tool. Adds "component_as_tool" output (type: Tool).
    """
    await _backup_if_enabled(flow_id, "add_custom_component")
    result = await node_tools.add_inline_custom_component(
        _get_client(),
        _get_cache(),
        flow_id,
        code,
        position_x,
        position_y,
        tool_mode,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_node(flow_id: str, node_id: str, config: dict) -> str:
    """Update node configuration values.

    NOTE: This updates the saved configuration but does NOT re-execute the component.
    The flow must be RUN for changes to take effect and produce new outputs.
    For template components (like Prompt), the template is saved but not processed
    until the flow runs.

    IMPORTANT: Do NOT use this tool to enable/disable tool_mode. Use set_tool_mode instead.
    Setting tool_mode requires server-side processing to transform outputs and template.

    Args:
        flow_id: Flow UUID
        node_id: Node ID (e.g., "Agent-D0Kx2")
        config: Template field values to update
            Example: {"model_name": "gpt-4o", "temperature": 0.7}
    """
    await _backup_if_enabled(flow_id, f"update_node: {node_id}")
    result = await node_tools.update_node(_get_client(), flow_id, node_id, config)
    return json.dumps(result, indent=2)


@mcp.tool()
async def set_tool_mode(flow_id: str, node_id: str, enabled: bool = True) -> str:
    """Enable or disable tool_mode on a component node.

    This is the CORRECT way to make a component usable as an Agent tool.
    It calls the Langflow server to perform the full tool_mode transformation:

    When enabled (tool_mode=True):
    - Replaces all node outputs with a single "component_as_tool" output (type: Tool)
    - Adds a "tools_metadata" field to the template for configuring tool names/descriptions
    - Updates base_classes to ["Tool"]
    - The "component_as_tool" output can then be connected to an Agent's "tools" input

    When disabled (tool_mode=False):
    - Restores the node's original outputs
    - Removes the "tools_metadata" template field
    - Restores original base_classes

    IMPORTANT: Do NOT try to enable tool_mode by using update_node with
    config={"tool_mode": True}. That only sets a value without performing
    the server-side output transformation, which will leave the node without
    the "component_as_tool" output it needs to connect to agents.

    Args:
        flow_id: Flow UUID
        node_id: Node ID (e.g., "URLReader-D0Kx2", "CustomComponent-aBcDe")
        enabled: True to enable tool_mode (default), False to disable
    """
    await _backup_if_enabled(flow_id, f"set_tool_mode: {node_id} -> {enabled}")
    result = await node_tools.set_tool_mode(_get_client(), flow_id, node_id, enabled)
    return json.dumps(result, indent=2)


@mcp.tool()
async def remove_node(flow_id: str, node_id: str) -> str:
    """Remove a node and all its connections from a flow.

    Args:
        flow_id: Flow UUID
        node_id: Node ID to remove
    """
    await _backup_if_enabled(flow_id, f"remove_node: {node_id}")
    result = await node_tools.remove_node(_get_client(), flow_id, node_id)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_node_details(flow_id: str, node_id: str) -> str:
    """Get detailed information about a specific node.

    Args:
        flow_id: Flow UUID
        node_id: Node ID
    """
    result = await node_tools.get_node_details(_get_client(), flow_id, node_id)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_nodes(flow_id: str) -> str:
    """List all nodes in a flow.

    Args:
        flow_id: Flow UUID
    """
    result = await node_tools.list_nodes(_get_client(), flow_id)
    return json.dumps({"nodes": result, "count": len(result)}, indent=2)


@mcp.tool()
async def move_node(flow_id: str, node_id: str, x: float, y: float) -> str:
    """Move a node to a new position on the canvas.

    Args:
        flow_id: Flow UUID
        node_id: Node ID to move
        x: New X position
        y: New Y position
    """
    result = await node_tools.move_node(_get_client(), flow_id, node_id, x, y)
    return json.dumps(result, indent=2)


@mcp.tool()
async def add_note(
    flow_id: str,
    content: str,
    x: float = 100,
    y: float = 100,
    width: int = 400,
    height: int = 200,
    background_color: str = "neutral",
) -> str:
    """Add a sticky note/annotation to a flow.

    Use notes to document sections of your flow, add instructions,
    or explain what different parts do.

    Args:
        flow_id: Flow UUID
        content: Note content (supports markdown with headers, lists, etc.)
        x: X position on canvas
        y: Y position on canvas
        width: Note width in pixels (default 400)
        height: Note height in pixels (default 200)
        background_color: Color - "neutral", "transparent", "yellow", "blue", "green", "pink"
    """
    result = await node_tools.add_note(
        _get_client(), flow_id, content, x, y, width, height, background_color
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_note(
    flow_id: str,
    note_id: str,
    content: str | None = None,
    background_color: str | None = None,
) -> str:
    """Update a sticky note's content or appearance.

    Args:
        flow_id: Flow UUID
        note_id: Note ID (e.g., "note-28UlV")
        content: New content (markdown supported)
        background_color: New background color
    """
    result = await node_tools.update_note(
        _get_client(), flow_id, note_id, content, background_color
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def analyze_flow_layout(flow_id: str) -> str:
    """Analyze a flow's structure to help with positioning nodes.

    This tool examines the flow and provides:
    - Node categories (input, output, agent, tool, model, etc.)
    - Node dimensions (width, height)
    - Current positions
    - Connection graph (what connects to what)
    - Depth levels (distance from inputs)
    - Main flow path
    - Layout recommendations

    Use this before calling move_node or move_nodes_batch to understand
    how to position nodes for a clean, readable layout.

    Args:
        flow_id: Flow UUID
    """
    result = await node_tools.analyze_flow_layout(_get_client(), flow_id)
    return json.dumps(result, indent=2)


@mcp.tool()
async def auto_arrange_flow(
    flow_id: str,
    direction: str = "horizontal",
    spacing: float = 300,
    start_x: float = 100,
    start_y: float = 100,
) -> str:
    """Basic automatic arrangement of nodes in layers.

    This provides a simple topological sort arrangement. For more control,
    use analyze_flow_layout to understand the flow structure, then use
    move_nodes_batch to position nodes exactly where you want them.

    Uses actual node dimensions (width/height) to prevent overlap.

    Args:
        flow_id: Flow UUID
        direction: "horizontal" (left-to-right) or "vertical" (top-to-bottom)
        spacing: Gap between nodes in pixels (default 300 for readability)
        start_x: Starting X position (default 100)
        start_y: Starting Y position (default 100)
    """
    await _backup_if_enabled(flow_id, "auto_arrange_flow")
    result = await node_tools.auto_arrange_flow(
        _get_client(), flow_id, direction, spacing, start_x, start_y
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def move_nodes_batch(flow_id: str, moves: list) -> str:
    """Move multiple nodes at once.

    More efficient than moving nodes one at a time.

    Args:
        flow_id: Flow UUID
        moves: List of moves, each with {"node_id": "...", "x": 100, "y": 200}
    """
    result = await node_tools.move_nodes_batch(_get_client(), flow_id, moves)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_layout_suggestions(flow_id: str) -> str:
    """Analyze current layout and get specific improvement suggestions.

    This tool does NOT modify the flow. It analyzes the current layout and returns:
    - Detected clusters (logical groupings of related nodes)
    - Main data flow path
    - Layout quality score (0-100)
    - Specific issues (line collisions, overlaps, spacing problems)
    - Actionable suggestions to fix issues

    Args:
        flow_id: Flow UUID
    """
    result = await node_tools.get_layout_suggestions(_get_client(), flow_id)
    return json.dumps(result, indent=2)


# ============================================================================
# Edge/Connection Tools
# ============================================================================


@mcp.tool()
async def connect_nodes(
    flow_id: str,
    source_node_id: str,
    source_output: str,
    target_node_id: str,
    target_input: str,
) -> str:
    """Connect two nodes by creating an edge.

    The connection will be validated for type compatibility before creation.

    NOTE: Creating a connection does NOT execute the components. The flow must be
    RUN for data to actually flow through the connection.

    IMPORTANT: Connections may be automatically removed when the flow loads if:
    - Target field is hidden (show=false)
    - Target node has tool_mode enabled AND target field has tool_mode=true
    - Types become incompatible (e.g., output type changed)

    Args:
        flow_id: Flow UUID
        source_node_id: Source node ID (e.g., "ChatInput-iPUSx")
        source_output: Output name on source (e.g., "message")
        target_node_id: Target node ID (e.g., "Agent-D0Kx2")
        target_input: Input field name on target (e.g., "input_value")
    """
    await _backup_if_enabled(flow_id, f"connect_nodes: {source_node_id} → {target_node_id}")
    result = await edge_tools.connect_nodes(
        _get_client(),
        flow_id,
        source_node_id,
        source_output,
        target_node_id,
        target_input,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def disconnect_nodes(
    flow_id: str,
    source_node_id: str,
    target_node_id: str,
    target_input: str = "",
) -> str:
    """Remove connection(s) between nodes.

    Args:
        flow_id: Flow UUID
        source_node_id: Source node ID
        target_node_id: Target node ID
        target_input: Specific input to disconnect (optional)
            If empty, removes all edges between these nodes.
    """
    await _backup_if_enabled(flow_id, f"disconnect_nodes: {source_node_id} → {target_node_id}")
    result = await edge_tools.disconnect_nodes(
        _get_client(),
        flow_id,
        source_node_id,
        target_node_id,
        target_input or None,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_connections(flow_id: str, node_id: str = "") -> str:
    """List all connections in a flow or for a specific node.

    Args:
        flow_id: Flow UUID
        node_id: Optional node ID to filter connections
    """
    result = await edge_tools.list_connections(
        _get_client(), flow_id, node_id or None
    )
    return json.dumps({"connections": result, "count": len(result)}, indent=2)


@mcp.tool()
async def validate_connection(
    source_component_type: str,
    source_output: str,
    target_component_type: str,
    target_input: str,
) -> str:
    """Check if a connection would be valid without creating it.

    Use this to verify type compatibility before connecting nodes.

    Args:
        source_component_type: Component type of source node
        source_output: Output name on source
        target_component_type: Component type of target node
        target_input: Input field name on target
    """
    result = await edge_tools.validate_connection(
        _get_cache(),
        _get_validator(),
        source_component_type,
        source_output,
        target_component_type,
        target_input,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def find_compatible_connections(
    flow_id: str, node_id: str, direction: str
) -> str:
    """Find all compatible connections for a node in a flow.

    Use this to discover what nodes can be connected to/from a specific node.

    Args:
        flow_id: Flow UUID
        node_id: Node to find connections for
        direction: "inputs" to find what can connect TO this node,
                   "outputs" to find what this node can connect TO
    """
    result = await edge_tools.find_compatible_connections(
        _get_client(),
        _get_cache(),
        _get_validator(),
        flow_id,
        node_id,
        direction,
    )
    return json.dumps({"compatible": result, "count": len(result)}, indent=2)


# ============================================================================
# Langflow Source Code Exploration Tools
# ============================================================================


@mcp.tool()
async def setup_langflow_source() -> str:
    """Clone/update the Langflow source code repository for exploration.

    This tool clones the Langflow repository locally and checks out the version
    matching your running Langflow instance. This enables fast, offline code
    exploration with the explore_langflow, read_langflow_file, and
    list_langflow_directory tools.

    The repository is cached at ~/.cache/langflow-mcp/langflow (or
    $XDG_CACHE_HOME/langflow-mcp/langflow).

    Run this once when you first need to explore Langflow source code.
    It will automatically update to match your Langflow version.

    Returns:
        Status of the clone/checkout operation
    """
    result = await source_tools.setup_langflow_source(_get_client())
    return json.dumps(result, indent=2)


@mcp.tool()
async def explore_langflow(
    query: str,
    path_filter: str = "src/backend",
    max_results: int = 20,
) -> str:
    """Search Langflow's source code to understand how it works.

    This tool searches a local clone of the Langflow repository, using the
    version matching your running Langflow instance.

    PREREQUISITE: You must call setup_langflow_source first to clone the repo.
    If the repo is not set up, this tool will return an error with instructions.

    Use this tool when you need to understand:
    - How custom components work (search: "CustomComponent" or "class Component")
    - How tool_mode works (search: "tool_mode")
    - How builds work (search: "def build")
    - Component base classes (search: "class.*Component")
    - API endpoints (search: "@router")
    - Input/output types (search: "class.*Input")

    RECOMMENDED SEARCH PATHS:
    - "src/backend/base/langflow/base" - Component base classes
    - "src/backend/base/langflow/io" - Input/Output definitions
    - "src/backend/base/langflow/graph" - Graph building and execution
    - "src/backend/base/langflow/custom" - Custom component support
    - "src/backend/base/langflow/components" - Built-in components (examples!)
    - "src/backend/base/langflow/api" - API endpoints

    Args:
        query: Search term (class name, function name, or keyword)
        path_filter: Path prefix to search in (default: "src/backend")
        max_results: Maximum results to return (default: 20)

    Returns:
        List of matching files with line numbers and content snippets
    """
    result = await source_tools.explore_langflow(
        _get_client(), query, path_filter, max_results
    )
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2)


@mcp.tool()
async def read_langflow_file(
    file_path: str,
    start_line: int = 1,
    end_line: int = 0,
) -> str:
    """Read a file from Langflow's source code.

    PREREQUISITE: You must call setup_langflow_source first to clone the repo.

    Use this after explore_langflow finds relevant files, or to read known files.

    Common useful files:
    - src/backend/base/langflow/custom/custom_component/component.py (Component base class)
    - src/backend/base/langflow/io/inputs.py (Input types)
    - src/backend/base/langflow/io/outputs.py (Output types)
    - src/backend/base/langflow/graph/vertex/base.py (Build system)
    - src/backend/base/langflow/base/tools/component_tool.py (Tool mode)

    Args:
        file_path: Path to file in Langflow repo (e.g., "src/backend/base/langflow/io/inputs.py")
        start_line: Starting line number (1-indexed, default 1)
        end_line: Ending line number (0 means read to end, max 500 lines)

    Returns:
        File contents with line numbers
    """
    result = await source_tools.read_langflow_file(
        _get_client(), file_path, start_line, end_line
    )
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_langflow_directory(directory: str = "src/backend/base/langflow") -> str:
    """List files in a directory of the Langflow repository.

    PREREQUISITE: You must call setup_langflow_source first to clone the repo.

    Use this to explore the codebase structure and find relevant files.

    Key directories:
    - src/backend/base/langflow/base - Base component classes
    - src/backend/base/langflow/components - Built-in components (great examples!)
    - src/backend/base/langflow/custom - Custom component support
    - src/backend/base/langflow/graph - Graph building and execution
    - src/backend/base/langflow/io - Input/Output type definitions
    - src/backend/base/langflow/api - REST API endpoints

    Args:
        directory: Directory path to list (e.g., "src/backend/base/langflow/components")

    Returns:
        List of files and subdirectories
    """
    result = await source_tools.list_langflow_directory(_get_client(), directory)
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2)


@mcp.tool()
async def langflow_concepts(topic: str = "") -> str:
    """Get quick reference information about Langflow concepts.

    READ THIS FIRST before creating custom components or making complex flow changes.
    This provides essential information about how Langflow works.

    Args:
        topic: Topic to get info about. Options:
            - "custom_components" - Creating custom components with inline code (IMPORTANT!)
            - "tool_mode" - How tool_mode works for making components callable by Agents
            - "building" - How flow building/execution works (IMPORTANT!)
            - "component_structure" - Basic component class structure
            - "outputs" - How component outputs work
            - "inputs" - How component inputs and fields work
            - "connections" - How connections work and validation rules
            - "common_mistakes" - Common mistakes to avoid (READ THIS!)
            - "" (empty) - List all available topics

    Returns:
        Explanation of the requested concept
    """
    if not topic:
        return json.dumps(
            {
                "available_topics": list(CONCEPTS.keys()),
                "usage": "Call langflow_concepts with a topic name to get detailed information",
                "example": 'langflow_concepts("custom_components")',
            },
            indent=2,
        )

    if topic not in CONCEPTS:
        return json.dumps(
            {
                "error": f"Unknown topic: {topic}",
                "available_topics": list(CONCEPTS.keys()),
            },
            indent=2,
        )

    return json.dumps({"topic": topic, "content": CONCEPTS[topic]}, indent=2)


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
