"""MCP Server for Langflow Flow Building.

This server exposes tools for building and modifying Langflow flows
through natural language commands.
"""

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .backup import create_backup
from .client import LangflowClient, get_client
from .config import get_config
from .schema_cache import ComponentSchemaCache, get_schema_cache
from .validator import ConnectionValidator, get_validator
from .tools import components as comp_tools
from .tools import edges as edge_tools
from .tools import flows as flow_tools
from .tools import nodes as node_tools
from .tools import smart as smart_tools


async def _backup_if_enabled(flow_id: str, reason: str) -> dict[str, Any] | None:
    """Create a backup if auto-backup is enabled.

    Returns backup info dict if created, None otherwise.
    """
    return await create_backup(_get_client(), flow_id, reason)


def _summarize_build_events(result: dict[str, Any]) -> dict[str, Any]:
    """Summarize build events into a concise result.

    The build API returns NDJSON with many events (vertices_sorted, end_vertex,
    token, end, etc.). This extracts the useful information into a summary.

    Args:
        result: Dict with "events" list and optional "status"

    Returns:
        Summarized build result
    """
    events = result.get("events", [])
    status = result.get("status", "unknown")

    errors = []
    built_vertices = []
    outputs = {}

    for evt in events:
        evt_type = evt.get("event", evt.get("type", ""))
        evt_data = evt.get("data", {})

        if evt_type == "error":
            status = "error"
            errors.append(evt_data.get("error", str(evt_data)))

        elif evt_type == "end_vertex":
            build_data = evt_data.get("build_data", {})
            vertex_id = build_data.get("id", "")
            if vertex_id:
                built_vertices.append(vertex_id)
            # Capture outputs/results if present
            vertex_results = build_data.get("results", {})
            if vertex_results:
                outputs[vertex_id] = vertex_results

        elif evt_type == "end":
            if status != "error":
                status = "completed"

    summary: dict[str, Any] = {
        "status": status,
        "built_vertices": built_vertices,
        "vertex_count": len(built_vertices),
    }

    if errors:
        summary["errors"] = errors
    if outputs:
        summary["outputs"] = outputs

    return summary


# Initialize the MCP server
mcp = FastMCP(
    name="langflow-builder",
    instructions="""
You are a Langflow flow builder assistant. You can:
- Discover and describe available Langflow components
- Create, read, update, and delete flows
- Add, configure, and remove nodes from flows
- Connect and disconnect nodes with type validation
- Position and arrange nodes for clean visual layouts
- Group related nodes together with exposed fields
- Use high-level tools for common patterns (agent flows, RAG pipelines)
- Explore Langflow's source code to understand how it works internally

IMPORTANT GUIDELINES:
1. Always list or search for components before creating nodes to ensure they exist
2. Validate connections before making them to avoid type mismatches
3. Use the high-level tools (create_agent_flow, create_rag_flow) for common patterns
4. When modifying existing flows, always get the flow first to understand its structure
5. Use langflow_concepts() to quickly understand Langflow patterns before implementing
6. Use explore_langflow() to search the source code ONLY when you need deeper understanding

=================================================================================
CRITICAL LANGFLOW BEHAVIORS - READ THIS BEFORE DOING ANYTHING
=================================================================================

1. CUSTOM COMPONENTS - USE INLINE CODE (NO RESTART!)
   ────────────────────────────────────────────────────
   Use add_custom_component(flow_id, code, tool_mode=True/False) to create custom components.
   This sends the Python code to the Langflow API which dynamically evaluates it and
   builds the full node template. The component works IMMEDIATELY — no restart needed.

   NEVER create .py files for custom components! Always use inline code via add_custom_component.
   This is how the Langflow UI itself works — it stores code directly on the node.

   Only file-based components (loaded from LANGFLOW_COMPONENTS_PATH) require restart,
   but you should NOT use that approach. Inline code is always preferred because:
   - No restart needed
   - Code is stored on the node itself (portable with the flow)
   - The API validates and builds the template immediately
   - tool_mode can be enabled in the same call

2. BUILDING AND EXECUTION - USE build_flow() TO EXECUTE
   ───────────────────────────────────────────────────────
   - Adding nodes via API does NOT execute/build them
   - Connecting nodes via API does NOT execute/build them
   - Updating node values via API does NOT execute/build them
   - USE build_flow(flow_id) TO EXECUTE THE FLOW after making changes!
   - You can also use build_node(flow_id, node_id) to build a single component
   - Template components (prompts, etc.) need to be built to process their templates
   - After building, outputs will be available and you can verify changes took effect

3. TOOL MODE - DYNAMIC OUTPUT GENERATION (NO RESTART NEEDED)
   ────────────────────────────────────────────────────────────
   Enabling tool_mode on an EXISTING component is dynamic - it does NOT require restart!

   When you set tool_mode=True on a node:
   - The component DYNAMICALLY generates a "component_as_tool" output with type ["Tool"]
   - This happens at BUILD TIME, not at Langflow startup
   - Just call build_flow() or build_node() after enabling tool_mode
   - The new Tool output will appear and can be connected to Agent's tools input

   IMPORTANT DISTINCTION:
   - Enabling tool_mode on existing component → NO restart, just build
   - Creating custom components with inline code → NO restart (use add_custom_component)

   TOOL MODE FIELD BEHAVIOR:
   - When tool_mode=True is set on a node, connections to tool_mode fields are REMOVED
   - This is BY DESIGN - the Agent provides those values when calling the tool
   - Don't try to connect to tool_mode fields on a tool_mode-enabled node
   - Fields marked tool_mode=True in the component become the tool's parameters
   - Fields marked tool_mode=False (or not set) stay as configuration

   USING EXISTING COMPONENTS AS TOOLS:
   - Most built-in components already have tool_mode fields defined
   - Use the set_tool_mode(flow_id, node_id, enabled=True) tool to enable tool_mode
   - Do NOT use update_node to set tool_mode - it won't trigger the output transformation
   - After set_tool_mode, the node will have a "component_as_tool" output (type: Tool)
   - Connect the "component_as_tool" output to your Agent's tools input
   - No custom code or restart needed!

4. COMPONENT OUTPUTS AND THE "selected" PROPERTY
   ──────────────────────────────────────────────
   - When a component has multiple output types, one is "selected" (active)
   - Only the selected output type flows through connections
   - When connecting nodes, use the output's current selected type
   - If connection fails, check if the output type matches the input's accepted types

5. HIDDEN FIELDS AND CONNECTIONS
   ──────────────────────────────
   - Fields with show=False cannot receive connections (they're hidden)
   - Connections to hidden fields are automatically removed when flow loads
   - Check field visibility before attempting to connect

6. NODE CONFIGURATION VS CONNECTIONS
   ──────────────────────────────────
   - Inputs can receive values TWO ways: direct configuration OR incoming connection
   - When a connection exists, it overrides any configured value
   - Some inputs are "connection only" (HandleInput) - they can't be configured directly

WORKFLOW FOR CREATING FLOWS:
1. Create an empty flow with create_flow
2. Add built-in nodes with add_node, OR custom components with add_custom_component (inline code)
3. If a component needs to be used as an Agent tool, use tool_mode=True in add_node/add_custom_component
   OR call set_tool_mode(flow_id, node_id) after adding
4. Connect nodes with connect_nodes (specifying source output and target input)
5. Update node configurations with update_node if needed
6. Arrange nodes for clarity using move_node or move_nodes_batch
7. Run build_flow to execute and verify everything works

WORKFLOW FOR ADDING CUSTOM COMPONENTS (NO RESTART!):
1. Write the Python code defining a Component subclass
2. Call add_custom_component(flow_id, code, tool_mode=True/False)
3. The Langflow API validates the code and builds the template dynamically
4. The node appears in the flow immediately — no restart needed
5. Connect it to other nodes and build the flow
NEVER create .py files for custom components. Always use inline code.

WORKFLOW FOR WIRING A COMPONENT AS AN AGENT TOOL:
1. Add the component node with add_node(tool_mode=True) or add_custom_component(code, tool_mode=True)
2. Connect the node's "component_as_tool" output to the Agent's "tools" input
3. Run build_flow to execute

WORKFLOW FOR MODIFYING FLOWS:
1. Use list_flows to find the flow
2. Use get_flow to see current structure
3. Use update_node, add_node, remove_node, connect_nodes, disconnect_nodes as needed
4. To toggle tool_mode on a node, use set_tool_mode (NOT update_node)
5. Run build_flow to execute changes and verify they work

LAYOUT GUIDELINES (for positioning nodes):

THE GOAL: Create a clean, spacious layout where someone can instantly trace any data
path with their eyes. Think subway map - clear lines, no clutter, obvious flow direction.

=== CRITICAL: HOW CONNECTION LINES ARE RENDERED ===
Langflow uses BEZIER CURVES for connections. Here's exactly how they work:

1. LINE EXIT POINT: Right edge of source node + 7px offset
   - X = source_node.x + source_node.width + 7
   - Y = the Y position of the specific output handle (varies per field)

2. LINE ENTRY POINT: Left edge of target node - 7px offset
   - X = target_node.x - 7
   - Y = the Y position of the specific input handle (varies per field)

3. BEZIER CURVE PATH: The line follows this shape:
   - Starts at exit point, initially goes HORIZONTAL to the right
   - Control point 1: at X midpoint, same Y as source (horizontal from source)
   - Control point 2: at X midpoint, same Y as target (horizontal to target)
   - Ends at entry point

   This means the line BULGES OUTWARD horizontally before curving to target!

4. THE DANGER ZONE for a connection from (x1,y1) to (x2,y2):
   - Horizontal range: x1 to x2 (entire space between nodes)
   - Vertical range: min(y1,y2) to max(y1,y2) (between the handle Y positions)
   - The WIDEST part of the curve is at the horizontal midpoint!
   - Add 50px padding to vertical range for the curve bulge

5. HANDLE Y POSITIONS within a node:
   - Each input/output field has its own handle at 50% of that field's row
   - Fields are stacked vertically within the node
   - First handle might be at node.y + 80px, subsequent handles ~40-60px apart
   - A node with many fields will have handles spread across its full height

=== RULE 1: EXTREME HORIZONTAL SPACING ===
Use MUCH more horizontal space than you think necessary:
- MINIMUM X gap between connected nodes: 600px (node is 384px wide, so next node starts at x+984)
- RECOMMENDED X gap: 800-1000px for complex flows
- For a flow with 5 horizontal stages, canvas should be 5000-6000px wide
- Example: If node A is at x=100, the node it connects to should be at x=1000 or more

=== RULE 2: VERTICAL POSITIONING TO AVOID LINE COVERAGE ===
Connection lines run horizontally. To avoid a node covering a line:
- If node A (at y=100) connects to node C (at y=500), a line runs from y≈100 to y≈500
- Do NOT place node B anywhere in the vertical range y=100 to y=500 if B is horizontally between A and C
- SAFE ZONE: Place nodes ABOVE the highest connection or BELOW the lowest connection passing through that X region
- When multiple connections pass through an X region, leave that entire Y band EMPTY

=== RULE 3: FAN OUT VERTICALLY, NOT HORIZONTALLY ===
When multiple nodes connect to the same target:
- Stack them vertically with LARGE gaps (600-800px between each)
- All source nodes should be at similar X positions (vertically aligned)
- The target should be far to the right (800-1000px away)
- This creates parallel horizontal lines that don't cross

=== RULE 4: SWIM LANES FOR BRANCHES ===
When the flow branches into parallel paths:
- Each branch gets its own horizontal "lane" at a distinct Y level
- Lanes should be 800-1200px apart vertically
- Nodes within a lane progress left-to-right
- Where branches converge, bring them together gradually

=== RULE 5: SUPPORTING NODES GO FAR OUTSIDE ===
Models, tools, memory, and config nodes that feed into a main node:
- Position them far ABOVE (y = main_node_y - 800) or far BELOW (y = main_node_y + main_node_height + 600)
- This keeps connection lines short and away from the main horizontal flow
- These nodes should be at similar or slightly less X than their consumer

=== CONCRETE SPACING VALUES ===
- Node width: 384px (fixed)
- Node height: 400-700px (check actual height from analyze_flow_layout!)
- Horizontal gap between connected nodes: 600-1000px
- Vertical gap when stacking: 600-800px
- Branch lane separation: 800-1200px
- Supporting node offset: 600-800px above/below main flow
- Total canvas: 4000-8000px wide, 3000-6000px tall is FINE

=== LAYOUT PROCESS ===
1. Call analyze_flow_layout to get node dimensions and connections
2. Identify the MAIN PATH (longest input→output chain) - this is your horizontal spine
3. Position main path nodes in a horizontal line at y=1500 (middle of canvas), x increasing by 800-1000px each
4. For each main path node, position its supporting nodes (models, tools) 600-800px above or below
5. Position parallel branches in separate lanes 800-1200px above/below the main path
6. CHECK: For each connection, verify no node sits in the Y band between source and target at intermediate X values
7. If any node covers a line, move it UP or DOWN until it's outside the line's Y range

=== EXAMPLE ===
Main path: ChatInput → Agent → ChatOutput
- ChatInput at (100, 1500)
- Agent at (1000, 1500)  [900px gap]
- ChatOutput at (2000, 1500)  [1000px gap]

Agent's model feeds into Agent:
- OpenAIModel at (800, 700)  [800px above Agent, slightly left]
- Connection runs from (800,700) to (1000,1500) - this diagonal is CLEAR because no nodes between them

Agent's tools:
- Tool1 at (600, 2300)  [800px below Agent]
- Tool2 at (600, 3000)  [700px below Tool1]
- Both connect to Agent at (1000, 1500) - diagonal lines, well separated

Use analyze_flow_layout to understand the flow structure before repositioning.
Use get_layout_suggestions to get specific improvement recommendations.
Use move_nodes_batch to move multiple nodes efficiently.
""",
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
    import asyncio

    client = _get_client()

    # Start the build — may return immediately with all events (NDJSON)
    # or return a job_id for polling
    build_result = await client.build_flow(
        flow_id,
        input_value=input_value if input_value else None,
        input_type=input_type,
    )

    # If the response already contains events (NDJSON mode), it completed inline
    if "events" in build_result:
        return json.dumps(_summarize_build_events(build_result), indent=2)

    if not wait_for_completion:
        return json.dumps({
            "status": "started",
            "job_id": build_result.get("job_id"),
            "message": "Build started. Use get_build_status to poll for completion."
        }, indent=2)

    # Poll for completion using job_id
    job_id = build_result.get("job_id")
    if not job_id:
        return json.dumps(build_result, indent=2)

    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout_seconds:
            return json.dumps({
                "status": "timeout",
                "job_id": job_id,
                "elapsed_seconds": elapsed,
                "message": f"Build did not complete within {timeout_seconds} seconds"
            }, indent=2)

        try:
            result = await client.get_build_events(job_id)

            # get_build_events returns {"events": [...], "status": "completed"}
            if result.get("status") == "completed":
                return json.dumps(_summarize_build_events(result), indent=2)
            if result.get("status") == "error":
                return json.dumps(_summarize_build_events(result), indent=2)

            # Check individual events for end/error
            events = result.get("events", [])
            for evt in events:
                evt_type = evt.get("event", evt.get("type", ""))
                if evt_type in ("end", "error"):
                    return json.dumps(_summarize_build_events(result), indent=2)

        except Exception as e:
            # 404 means job completed and was cleaned up
            if "404" in str(e):
                return json.dumps({"status": "completed", "job_id": job_id}, indent=2)
            raise

        await asyncio.sleep(0.5)


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
    result = await _get_client().build_vertex(flow_id, node_id)
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
    result = await _get_client().get_build_events(job_id)
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

    Layout Guidelines:
    - Input nodes (ChatInput) go on the LEFT
    - Output nodes (ChatOutput) go on the RIGHT
    - Data flows LEFT to RIGHT
    - Related nodes stay close (model near agent, tools near agent)
    - Nodes at the same depth should have similar X positions
    - Use vertical spacing for parallel branches
    - Keep connection lines clean and non-overlapping

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

    NOTE: This may not avoid line crossings in complex flows. For complex
    flows, use analyze_flow_layout to understand the structure, then
    manually position with move_nodes_batch for optimal clarity.

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

    Use this when you want to understand layout problems before fixing them,
    or when you want to manually adjust specific nodes with move_nodes_batch.

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
# High-Level Semantic Tools
# ============================================================================


@mcp.tool()
async def create_agent_flow(
    name: str,
    tools: list | None = None,
    model_provider: str = "openai",
    model_name: str = "gpt-4o",
    system_prompt: str = "",
) -> str:
    """Create a complete agent flow with chat input/output and optional tools.

    This is the recommended way to quickly create a working agent flow.

    Args:
        name: Flow name
        tools: List of tool component types (e.g., ["Calculator", "WebSearch"])
        model_provider: LLM provider ("openai", "anthropic", "google")
        model_name: Model name (e.g., "gpt-4o", "claude-3-5-sonnet")
        system_prompt: Agent system prompt
    """
    tool_list = tools or []
    result = await smart_tools.create_agent_flow(
        _get_client(),
        _get_cache(),
        name,
        tool_list,
        model_provider,
        model_name,
        system_prompt or None,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_rag_flow(
    name: str,
    vector_store: str = "Qdrant",
    embedding_model: str = "OpenAIEmbeddings",
    llm_provider: str = "openai",
    llm_model: str = "gpt-4o",
) -> str:
    """Create a RAG (Retrieval Augmented Generation) flow.

    Creates a flow with vector store retrieval connected to an agent.

    Args:
        name: Flow name
        vector_store: Vector store type (e.g., "Qdrant", "Pinecone", "Chroma")
        embedding_model: Embedding model type (e.g., "OpenAIEmbeddings")
        llm_provider: LLM provider
        llm_model: LLM model name
    """
    result = await smart_tools.create_rag_flow(
        _get_client(),
        _get_cache(),
        name,
        vector_store,
        embedding_model,
        llm_provider,
        llm_model,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def explain_flow(flow_id: str) -> str:
    """Generate a natural language explanation of a flow.

    Use this to understand what a flow does.

    Args:
        flow_id: Flow UUID
    """
    result = await smart_tools.explain_flow(_get_client(), flow_id)
    return result


# ============================================================================
# Langflow Source Code Exploration Tools (Local Repository)
# ============================================================================

from .source_repo import get_source_repo

# Cache for Langflow version
_langflow_version_cache: str | None = None


async def _get_langflow_version() -> str:
    """Get the Langflow version from API or config override."""
    global _langflow_version_cache

    config = get_config()
    if config.langflow_version_override:
        return config.langflow_version_override

    if _langflow_version_cache:
        return _langflow_version_cache

    try:
        version_info = await _get_client().get_version()
        _langflow_version_cache = version_info.get("version", "main")
        return _langflow_version_cache
    except Exception:
        return "main"


async def _ensure_source_repo() -> dict:
    """Ensure the Langflow source repo is cloned and at the correct version.

    Used only by setup_langflow_source. Other tools should use _require_source_repo.
    """
    version = await _get_langflow_version()
    repo = get_source_repo()
    return await repo.ensure_version(version)


def _require_source_repo() -> str | None:
    """Check if the source repo is cloned and ready.

    Returns None if ready, or a JSON error string if not.
    Other source exploration tools should call this first and return
    the error immediately instead of silently triggering a clone.
    """
    repo = get_source_repo()
    if not repo.is_cloned:
        return json.dumps({
            "error": "Langflow source repository is not set up yet.",
            "action_required": "Call the setup_langflow_source tool first. "
                "It will clone the Langflow repository locally (this takes 1-2 minutes "
                "on first run). After that, explore_langflow, read_langflow_file, and "
                "list_langflow_directory will work.",
            "tool_to_call": "setup_langflow_source",
        }, indent=2)
    return None


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
    result = await _ensure_source_repo()
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
    # Check repo is set up — don't auto-clone, it times out
    error = _require_source_repo()
    if error:
        return error

    version = await _get_langflow_version()
    repo = get_source_repo()

    # Search using git grep
    matches = await repo.search_files(query, path_filter, max_results)

    return json.dumps({
        "langflow_version": version,
        "query": query,
        "path_filter": path_filter,
        "result_count": len(matches),
        "results": matches,
        "tip": "Use read_langflow_file to get the full content of any file"
    }, indent=2)


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
    # Check repo is set up — don't auto-clone, it times out
    error = _require_source_repo()
    if error:
        return error

    version = await _get_langflow_version()
    repo = get_source_repo()

    result = repo.read_file(file_path, start_line, end_line)
    result["langflow_version"] = version

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
    # Check repo is set up — don't auto-clone, it times out
    error = _require_source_repo()
    if error:
        return error

    version = await _get_langflow_version()
    repo = get_source_repo()

    result = repo.list_directory(directory)
    result["langflow_version"] = version

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
    concepts = {
        "common_mistakes": """
# Common Mistakes When Working with Langflow

## Mistake 1: Creating .py files for custom components instead of using inline code
WRONG: Write .py file → Tell user to restart Langflow → Wait → Component available
RIGHT: Use add_custom_component(flow_id, code) → Component available immediately!

ALWAYS use add_custom_component with inline Python code. The Langflow API
dynamically evaluates the code and builds the node template on the fly.
No restart needed. No file creation needed. This is exactly how the
Langflow UI itself works.

## Mistake 2: Expecting changes to take effect without running the flow
WRONG: Update node config → Read node → Wonder why output hasn't changed
RIGHT: Update node config → Tell user to run the flow → Output updates

API changes (add_node, connect_nodes, update_node) only modify the flow structure.
Components don't execute until the flow is RUN.

## Mistake 3: Using update_node to enable tool_mode
WRONG: update_node(flow_id, node_id, {"tool_mode": True}) → Node flag set but outputs unchanged → No "component_as_tool" output → Cannot connect to Agent
RIGHT: set_tool_mode(flow_id, node_id, enabled=True) → Server transforms outputs → "component_as_tool" output appears → Connect to Agent's "tools" input

Enabling tool_mode requires server-side processing via the /custom_component/update API.
set_tool_mode handles this correctly. update_node only patches template values and does
NOT trigger the output transformation.

## Mistake 4: Making tool_mode too complicated
WRONG: Mark all inputs as tool_mode=True, add complex logic for tool registration
RIGHT: Create simple component, use set_tool_mode to enable it, let Langflow handle the rest

Only mark inputs as tool_mode=True if they should be provided by the Agent
dynamically at each call. Most inputs should be pre-configured.

## Mistake 5: Trying to connect to tool_mode fields on a tool
WRONG: Enable tool_mode on component → Try to connect to its inputs → Connections removed
RIGHT: Configure tool_mode inputs directly (they come from the Agent at runtime)

When tool_mode is enabled, fields marked tool_mode=True cannot receive connections.
The Agent provides those values when it calls the tool.

## Mistake 6: Not checking component availability before adding nodes
WRONG: Assume component exists → add_node fails
RIGHT: search_components first → verify exists → then add_node

## Mistake 7: Connecting incompatible types
WRONG: Connect any output to any input → Connection removed on flow load
RIGHT: Check output_types match input_types → Connection persists

Use validate_connection() to check before connecting, or catch the error from connect_nodes.

## Mistake 8: Connecting to "component_as_tool" before enabling tool_mode
WRONG: add_node → connect_nodes with source_output="component_as_tool" → Fails (output doesn't exist)
RIGHT: add_node → set_tool_mode(flow_id, node_id) → connect_nodes with source_output="component_as_tool"

Or use add_node with tool_mode=True to do it in one step.
""",

        "custom_components": """
# Custom Components in Langflow

## USE INLINE CODE — No Restart Needed!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use add_custom_component(flow_id, code) to create custom components.
The Langflow API dynamically evaluates the code and builds the node template.
The component works immediately — NO restart, NO file creation.

NEVER create .py files for custom components. Always use inline code.

## How It Works
1. You write the Python code defining a Component subclass
2. add_custom_component sends it to POST /custom_component
3. Langflow evaluates the code, extracts the class, and builds the template
4. The built node (with inputs, outputs, types) is added to the flow
5. The code is stored in the node's template["code"].value field
6. When the flow runs, the code is evaluated again to execute the component

## Basic Custom Component Structure
```python
from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema.message import Message

class MyComponent(Component):
    display_name = "My Component"
    description = "What this component does"
    icon = "Sparkles"  # Any Lucide icon name

    inputs = [
        MessageTextInput(
            name="input_text",
            display_name="Input Text",
        ),
    ]

    outputs = [
        Output(display_name="Output", name="output", method="process"),
    ]

    def process(self) -> Message:
        return Message(text=self.input_text.upper())
```

## Key Points
- Class name = component type (MyComponent)
- display_name = what users see in UI
- inputs = left side handles + configuration
- outputs = right side handles
- Each output's "method" = the method that produces that output
- Methods should have return type annotations

## For Tool Usage
If the component will be used as a tool by an Agent:
- Use add_custom_component(flow_id, code, tool_mode=True) to create with tool_mode enabled
- Or use set_tool_mode(flow_id, node_id) after adding to enable tool_mode later
- Do NOT use update_node to set tool_mode - it won't transform the outputs
- Only mark inputs as tool_mode=True if they should be filled by the Agent at runtime
- Most inputs should be pre-configured, not dynamic
""",

        "tool_mode": """
# Tool Mode in Langflow

## What is Tool Mode?
Tool mode makes a component callable by an Agent as a "tool".

## IMPORTANT: No Restart Required!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Enabling tool_mode on an existing component is DYNAMIC:
1. Use set_tool_mode(flow_id, node_id, enabled=True) to enable it
2. The node's outputs are replaced with "component_as_tool" (type: Tool)
3. Connect "component_as_tool" output to Agent's "tools" input
4. Build the flow with build_flow() to execute

This does NOT require a Langflow restart!

## How It Works (Under the Hood)
When set_tool_mode is called:
1. The Langflow server's /custom_component/update endpoint is called
2. The server replaces ALL node outputs with a single "component_as_tool" output (type: Tool)
3. A "tools_metadata" field is added to the template for configuring tool names/descriptions
4. base_classes are updated to include "Tool"
5. The updated node data is saved back to the flow

## CRITICAL: Use set_tool_mode, NOT update_node
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WRONG: update_node(flow_id, node_id, {"tool_mode": True})
  → Only sets a template value, does NOT transform outputs
  → Node still has original outputs, no "component_as_tool"
  → Cannot connect to Agent

RIGHT: set_tool_mode(flow_id, node_id, enabled=True)
  → Calls server API for full transformation
  → Outputs replaced with "component_as_tool" (type: Tool)
  → Can now connect to Agent's "tools" input

You can also use add_node(flow_id, component_type, tool_mode=True) to add
a node with tool_mode already enabled in one step.

## When to Use tool_mode=True on Inputs
Only use tool_mode=True on an input when:
- The input value should come from the Agent dynamically
- Different Agent calls should provide different values for this input

Example: A search component
```python
inputs = [
    MessageTextInput(
        name="query",
        display_name="Search Query",
        tool_mode=True,  # Agent provides this each time it calls the tool
    ),
    StrInput(
        name="api_key",
        display_name="API Key",
        tool_mode=False,  # Configured once, same for all calls
    ),
]
```

## CRITICAL: Connections to tool_mode Fields Are Removed
When you enable tool_mode on a node:
- All connections to fields marked tool_mode=True are AUTOMATICALLY REMOVED
- This is intentional - those fields are filled by the Agent, not by connections
- Fields without tool_mode=True keep their connections

## Don't Over-Engineer It
Common mistake: Making every input tool_mode=True
- This makes the tool harder for the Agent to use
- Most inputs should be pre-configured, not dynamic
- Only dynamic query/input parameters need tool_mode=True

## Enabling Tool Mode via MCP Tools

For built-in components:
  add_node(flow_id, "MyComponent", tool_mode=True)
  connect_nodes(flow_id, node_id, "component_as_tool", agent_id, "tools")

For custom components (inline code):
  add_custom_component(flow_id, code, tool_mode=True)
  connect_nodes(flow_id, node_id, "component_as_tool", agent_id, "tools")

For existing nodes (toggle tool_mode after the fact):
  set_tool_mode(flow_id, node_id, enabled=True)
  connect_nodes(flow_id, node_id, "component_as_tool", agent_id, "tools")
""",

        "building": """
# Building and Execution in Langflow

## CRITICAL: API Changes Don't Execute Components
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When you use the MCP tools to:
- Add a node → Node exists but hasn't run
- Connect nodes → Connection exists but no data flows
- Update a value → Value is saved but not processed

Components only execute when the FLOW IS RUN.

## What "Building" Means
Building = executing a component's code to produce outputs.

The build process:
1. Resolves all input values (from config or upstream connections)
2. Calls the component's output methods
3. Caches the results
4. Makes outputs available to downstream components

## When Building Happens
Building happens when:
1. User clicks the "Play" button in UI
2. User runs a specific component (component play button)
3. API call to /run endpoint
4. Webhook triggers the flow

Building does NOT happen when:
- Adding/removing nodes via API
- Creating/removing connections via API
- Updating field values via API

## After Making API Changes
Always tell the user: "Run the flow to see changes take effect"

Don't try to read outputs expecting them to be updated - they won't be
until the flow runs.

## Template Components (Prompts, etc.)
Template components (like Prompt) process their template text when built.
- Updating the template text via API saves the new text
- The processed output only updates when the flow runs
- Variables in templates are resolved at build time
""",

        "component_structure": """
# Component Structure in Langflow

## Base Classes
- Component: Main base class (use this)
- CustomComponent: Legacy alias for Component

## Class Attributes
```python
from langflow.custom import Component
from langflow.io import MessageTextInput, StrInput, Output
from langflow.schema.message import Message

class MyComponent(Component):
    # Required
    display_name = "My Component"      # Shown in UI

    # Optional but recommended
    description = "What it does"       # Tooltip
    icon = "Sparkles"                  # Lucide icon name
    name = "MyComponent"               # Internal name (defaults to class name)

    # Inputs and Outputs
    inputs = [...]                     # List of Input objects
    outputs = [...]                    # List of Output objects
```

## Output Methods
Each Output references a method that produces its value:
```python
outputs = [
    Output(display_name="Message", name="message", method="create_message"),
    Output(display_name="Data", name="data", method="create_data"),
]

def create_message(self) -> Message:
    return Message(text="Hello")

def create_data(self) -> Data:
    return Data(data={"key": "value"})
```

## Accessing Inputs in Methods
Input values become instance attributes:
```python
inputs = [
    StrInput(name="my_input", display_name="My Input"),
]

def process(self) -> Message:
    value = self.my_input  # Access input value
    return Message(text=value)
```

## Setting Status
Show status in UI:
```python
def process(self) -> Message:
    self.status = "Processing..."
    result = do_work()
    self.status = f"Processed {len(result)} items"
    return Message(text=result)
```
""",

        "outputs": """
# Component Outputs in Langflow

## Defining Outputs
```python
from langflow.io import Output

outputs = [
    Output(
        display_name="Result",        # Shown in UI
        name="result",                # Internal name for connections
        method="build_result",        # Method that produces this output
    ),
]

def build_result(self) -> Message:
    return Message(text="Hello")
```

## Output Types
Type is inferred from method return type annotation:
- Message: Text/conversation messages
- Data: Structured data (dict-like)
- str: Plain text
- list: Multiple items
- LanguageModel: LLM instances
- Tool: Tool instances
- etc.

## Multiple Outputs
```python
outputs = [
    Output(display_name="Text", name="text", method="get_text"),
    Output(display_name="Data", name="data", method="get_data"),
]

def get_text(self) -> Message:
    return Message(text="text output")

def get_data(self) -> Data:
    return Data(data={"key": "value"})
```

## Selected Output
When multiple outputs exist with similar types:
- One output is "selected" (active)
- The selected output's type is used for connections
- Users can change selection via dropdown on the output handle
- Connection handles show the currently selected type
""",

        "inputs": """
# Component Inputs in Langflow

## Input Types
```python
from langflow.io import (
    MessageTextInput,  # Text, can receive Message connections
    StrInput,          # String configuration
    IntInput,          # Integer
    FloatInput,        # Float
    BoolInput,         # Boolean toggle
    DropdownInput,     # Selection from options
    MultilineInput,    # Multi-line text
    SecretStrInput,    # Password/API key (hidden)
    FileInput,         # File upload
    HandleInput,       # Connection-only (no manual entry)
    DataInput,         # Accepts Data connections
)
```

## Input Parameters
```python
MessageTextInput(
    name="my_input",           # REQUIRED: Internal name, becomes self.my_input
    display_name="My Input",   # REQUIRED: UI label
    info="Help text",          # Tooltip
    value="default",           # Default value
    required=True,             # Must have value to build
    advanced=False,            # Show in advanced section
    show=True,                 # Show in UI (False = hidden)
    input_types=["Message"],   # Types accepted from connections
    tool_mode=False,           # Becomes tool parameter when tool_mode enabled
)
```

## Connection-Only Inputs
Use HandleInput for inputs that can ONLY receive connections:
```python
HandleInput(
    name="model",
    display_name="Language Model",
    input_types=["LanguageModel"],
)
```

## Dropdown Inputs
```python
DropdownInput(
    name="choice",
    display_name="Select Option",
    options=["option1", "option2", "option3"],
    value="option1",  # Default selection
)
```
""",

        "connections": """
# How Connections Work in Langflow

## Connection Basics
- Connections flow LEFT to RIGHT
- Source: output handle (right side of node)
- Target: input handle (left side of node)

## Type Compatibility
A connection is valid when:
- Source output_types contains a type that...
- Target input_types accepts

Example:
- Source outputs ["Message", "str"]
- Target accepts ["Message", "Text"]
- Valid because both have "Message"

## Connection Validation
Before connecting via API, the MCP validates:
1. Source node and output exist
2. Target node and input exist
3. Types are compatible
4. Target field is visible (show != false)
5. Target field is not tool_mode when node is in tool_mode

## Connections That Get Removed
When a flow loads, Langflow removes connections that are:
- To fields with show=false (hidden fields)
- To tool_mode fields when node has tool_mode enabled
- Between incompatible types (type changed since connection was made)
- To/from outputs that were deselected

## The "selected" Output
When an output has multiple types:
- Only one type is "selected" at a time
- Connections use the selected type
- Changing selection may invalidate existing connections

## Duplicate Connections
Most inputs only accept ONE connection:
- Connecting a second source replaces the first
- Exception: inputs with is_list=True accept multiple connections
""",
    }

    if not topic:
        return json.dumps({
            "available_topics": list(concepts.keys()),
            "usage": "Call langflow_concepts with a topic name to get detailed information",
            "example": 'langflow_concepts("custom_components")'
        }, indent=2)

    if topic not in concepts:
        return json.dumps({
            "error": f"Unknown topic: {topic}",
            "available_topics": list(concepts.keys())
        }, indent=2)

    return json.dumps({
        "topic": topic,
        "content": concepts[topic]
    }, indent=2)


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
