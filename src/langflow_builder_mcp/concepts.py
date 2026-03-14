"""Langflow concept reference documentation for the langflow_concepts tool."""

CONCEPTS: dict[str, str] = {
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
