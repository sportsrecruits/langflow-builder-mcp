# Langflow Builder MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that enables AI assistants to programmatically build and modify [Langflow](https://github.com/langflow-ai/langflow) flows. Works with Claude Code, Claude Desktop, Cursor, Windsurf, and any MCP-compatible client.

Give your AI assistant the ability to create flows, add components, wire up agents with tools, write custom components inline, and manage your entire Langflow workspace — all through natural language.

## Features

- **Component Discovery** — List, search, and inspect schemas for all available Langflow components
- **Flow Management** — Create, read, update, delete, and duplicate flows
- **Node Manipulation** — Add, configure, move, and remove nodes with full template control
- **Custom Components** — Write Python components inline with no server restart required
- **Tool Mode** — Enable tool_mode on any component so Agents can call it as a tool
- **Connection Management** — Connect/disconnect nodes with automatic type validation
- **Build & Execute** — Run flows and get results, with proper NDJSON streaming support
- **Layout Engine** — Analyze, auto-arrange, and manually position nodes for clean layouts
- **Source Explorer** — Search and read Langflow's source code to understand internals

---

## Quick Start

### 1. Install

```bash
# Using pip
pip install langflow-builder-mcp

# Using uv (recommended)
uv pip install langflow-builder-mcp

# From source
git clone https://github.com/sportsrecruits/langflow-builder-mcp.git
cd langflow-builder-mcp
pip install -e .
```

### 2. Create a Langflow API Key

The MCP server authenticates with Langflow using an API key. To create one:

1. Open your Langflow instance in a browser
2. Click your **profile icon** (bottom-left corner of the sidebar)
3. Select **Settings**
4. Go to the **Langflow API** section
5. Click **Add New** to generate a new API key
6. Copy the key — you'll need it in the next step

> If you're running Langflow locally with default settings and have not enabled authentication, you may need to start Langflow with `--auto-login` disabled or configure a superuser to access the API settings.

### 3. Configure

The server connects to a running Langflow instance. Set your Langflow URL and API key:

```bash
export LANGFLOW_MCP_LANGFLOW_URL="http://localhost:7860"
export LANGFLOW_MCP_API_KEY="sk-..."
```

### 4. Add to your AI tool

See [Installation per Tool](#installation-per-tool) below for Claude Code, Cursor, Windsurf, etc.

---

## Installation per Tool

### Claude Code

Add to your project-level MCP config (`.mcp.json` in your project root):

```json
{
  "mcpServers": {
    "langflow-builder": {
      "command": "python",
      "args": ["-m", "langflow_builder_mcp.server"],
      "env": {
        "LANGFLOW_MCP_LANGFLOW_URL": "http://localhost:7860",
        "LANGFLOW_MCP_API_KEY": "sk-..."
      }
    }
  }
}
```

Or add it globally at `~/.claude/mcp.json` to make it available in all projects.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "langflow-builder": {
      "command": "python",
      "args": ["-m", "langflow_builder_mcp.server"],
      "env": {
        "LANGFLOW_MCP_LANGFLOW_URL": "http://localhost:7860",
        "LANGFLOW_MCP_API_KEY": "sk-..."
      }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "langflow-builder": {
      "command": "python",
      "args": ["-m", "langflow_builder_mcp.server"],
      "env": {
        "LANGFLOW_MCP_LANGFLOW_URL": "http://localhost:7860",
        "LANGFLOW_MCP_API_KEY": "sk-..."
      }
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "langflow-builder": {
      "command": "python",
      "args": ["-m", "langflow_builder_mcp.server"],
      "env": {
        "LANGFLOW_MCP_LANGFLOW_URL": "http://localhost:7860",
        "LANGFLOW_MCP_API_KEY": "sk-..."
      }
    }
  }
}
```

### Using uvx (no install needed)

If you have `uv` installed, you can run without installing:

```json
{
  "mcpServers": {
    "langflow-builder": {
      "command": "uvx",
      "args": ["langflow-builder-mcp"],
      "env": {
        "LANGFLOW_MCP_LANGFLOW_URL": "http://localhost:7860",
        "LANGFLOW_MCP_API_KEY": "sk-..."
      }
    }
  }
}
```

---

## Configuration

All configuration is via environment variables with the `LANGFLOW_MCP_` prefix:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LANGFLOW_MCP_LANGFLOW_URL` | | `http://localhost:7860` | Langflow instance URL |
| `LANGFLOW_MCP_API_KEY` | **Yes** | | API key for authentication ([how to create](#2-create-a-langflow-api-key)) |
| `LANGFLOW_MCP_CACHE_TTL` | | `300` | Component schema cache TTL (seconds) |
| `LANGFLOW_MCP_REQUEST_TIMEOUT` | | `30.0` | HTTP request timeout (seconds) |
| `LANGFLOW_MCP_AUTO_BACKUP_BEFORE_CHANGES` | | `false` | Auto-backup flows before modifications |
| `LANGFLOW_MCP_BACKUP_FOLDER_NAME` | | `MCP Backups` | Folder name for auto-backups |
| `LANGFLOW_MCP_LANGFLOW_VERSION_OVERRIDE` | | (auto-detected) | Override Langflow version for source exploration |
| `LANGFLOW_MCP_LANGFLOW_SOURCE_CACHE_DIR` | | `~/.cache/langflow-mcp` | Directory to cache Langflow source code |

You can also place these in a `.env` file in your working directory.

---

## Available Tools

### Component Discovery

| Tool | Description |
|------|-------------|
| `list_component_categories` | List all available categories (agents, models, vectorstores, etc.) |
| `list_components` | List components in a specific category |
| `get_component_schema` | Get full schema for a component (inputs, outputs, types) |
| `search_components` | Search components by name or description |

### Flow Management

| Tool | Description |
|------|-------------|
| `list_flows` | List all flows accessible to the current user |
| `get_flow` | Get complete flow structure with all nodes and edges |
| `create_flow` | Create a new empty flow |
| `delete_flow` | Delete a flow permanently |
| `duplicate_flow` | Duplicate an existing flow |

### Build & Execution

| Tool | Description |
|------|-------------|
| `build_flow` | Build and execute a flow (run all components) |
| `build_node` | Build a single node without running the full flow |
| `get_build_status` | Poll for build completion (async builds) |

### Node Manipulation

| Tool | Description |
|------|-------------|
| `add_node` | Add a built-in component node to a flow |
| `add_custom_component` | Add a custom component using inline Python code (no restart!) |
| `update_node` | Update node configuration values |
| `set_tool_mode` | Enable/disable tool_mode on a node for Agent integration |
| `remove_node` | Remove a node and all its connections |
| `get_node_details` | Get detailed node information |
| `list_nodes` | List all nodes in a flow |

### Layout & Positioning

| Tool | Description |
|------|-------------|
| `move_node` | Move a node to a new position |
| `move_nodes_batch` | Move multiple nodes at once |
| `auto_arrange_flow` | Automatically arrange nodes in layers |
| `analyze_flow_layout` | Analyze flow structure for layout planning |
| `get_layout_suggestions` | Get specific layout improvement suggestions |
| `add_note` | Add a sticky note/annotation to a flow |
| `update_note` | Update a note's content or appearance |

### Connection Management

| Tool | Description |
|------|-------------|
| `connect_nodes` | Create an edge between two nodes |
| `disconnect_nodes` | Remove edge(s) between nodes |
| `list_connections` | List all connections in a flow |
| `validate_connection` | Check if a connection would be valid |
| `find_compatible_connections` | Find all valid connections for a node |

### Langflow Source Exploration

| Tool | Description |
|------|-------------|
| `setup_langflow_source` | Clone/update the Langflow source repo locally |
| `explore_langflow` | Search Langflow source code (grep-style) |
| `read_langflow_file` | Read a specific file from the Langflow source |
| `list_langflow_directory` | List files in a Langflow source directory |
| `langflow_concepts` | Quick reference for Langflow concepts and patterns |

---

## Examples

### Build a Flow Step by Step

> "Create a flow where a Chat Input feeds into a Prompt template, which then goes to an OpenAI model, and finally to Chat Output"

```
create_flow(name="Prompt Chain")

add_node(flow_id="...", component_type="ChatInput", position_x=100, position_y=300)
add_node(flow_id="...", component_type="Prompt", position_x=600, position_y=300)
add_node(flow_id="...", component_type="OpenAIModel", position_x=1100, position_y=300)
add_node(flow_id="...", component_type="ChatOutput", position_x=1600, position_y=300)

connect_nodes(source_node_id="ChatInput-abc", source_output="message",
              target_node_id="Prompt-def", target_input="input_value")
connect_nodes(source_node_id="Prompt-def", source_output="prompt",
              target_node_id="OpenAIModel-ghi", target_input="input_value")
connect_nodes(source_node_id="OpenAIModel-ghi", source_output="text",
              target_node_id="ChatOutput-jkl", target_input="input_value")

build_flow(flow_id="...")
```

### Add a Custom Component (No Restart!)

> "Add a custom component that reverses the input text and connects it to the agent as a tool"

```
add_custom_component(
  flow_id="...",
  tool_mode=True,
  code="""
from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema.message import Message

class TextReverser(Component):
    display_name = "Text Reverser"
    description = "Reverses the input text"
    icon = "ArrowLeftRight"

    inputs = [
        MessageTextInput(
            name="input_text",
            display_name="Input Text",
            tool_mode=True,
        ),
    ]

    outputs = [
        Output(display_name="Reversed", name="reversed", method="reverse_text"),
    ]

    def reverse_text(self) -> Message:
        text = self.input_text if isinstance(self.input_text, str) else self.input_text.text
        return Message(text=text[::-1])
"""
)

connect_nodes(source_node_id="TextReverser-xyz", source_output="component_as_tool",
              target_node_id="Agent-abc", target_input="tools")
```

The component is validated and added instantly — no Langflow restart needed. With `tool_mode=True`, it automatically gets a `component_as_tool` output that the Agent can call.

### Enable Tool Mode on an Existing Component

> "Make the URL Reader component usable as a tool by the agent"

```
set_tool_mode(flow_id="...", node_id="URLReader-abc", enabled=True)

connect_nodes(source_node_id="URLReader-abc", source_output="component_as_tool",
              target_node_id="Agent-def", target_input="tools")
```

### Create a Custom Data Processor as a Tool

> "Create a component that parses CSV text into structured data"

```
add_custom_component(
  flow_id="...",
  tool_mode=True,
  code="""
import csv
import io
from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema import Data

class CSVParser(Component):
    display_name = "CSV Parser"
    description = "Parses CSV text into structured records"
    icon = "Table"

    inputs = [
        MessageTextInput(
            name="csv_text",
            display_name="CSV Text",
            info="Raw CSV content to parse",
            tool_mode=True,
        ),
    ]

    outputs = [
        Output(display_name="Records", name="records", method="parse_csv"),
    ]

    def parse_csv(self) -> Data:
        text = self.csv_text if isinstance(self.csv_text, str) else self.csv_text.text
        reader = csv.DictReader(io.StringIO(text))
        records = [row for row in reader]
        self.status = f"Parsed {len(records)} records"
        return Data(data={"records": records, "count": len(records)})
"""
)
```

### Modify an Existing Flow

> "Change the model in my agent to Claude and update the system prompt"

```
list_flows()
get_flow(flow_id="...")

update_node(flow_id="...", node_id="Agent-abc",
            config={"model_name": "claude-3-5-sonnet", "system_prompt": "You are a coding assistant."})

build_flow(flow_id="...")
```

### Explore What Components Are Available

> "What vector store components does Langflow have?"

```
search_components(query="vector")
```

Returns matching components like Qdrant, Pinecone, Chroma, AstraDB, etc. with descriptions.

> "Show me the full schema for the Qdrant component"

```
get_component_schema(component_type="Qdrant")
```

Returns all inputs (with types, defaults, options), outputs, and base classes.

### Layout and Arrangement

> "Clean up the layout of my flow"

```
analyze_flow_layout(flow_id="...")
get_layout_suggestions(flow_id="...")
auto_arrange_flow(flow_id="...", direction="horizontal", spacing=400)
```

Or for precise control:

```
move_nodes_batch(flow_id="...", moves=[
  {"node_id": "ChatInput-abc", "x": 100, "y": 300},
  {"node_id": "Agent-def", "x": 800, "y": 300},
  {"node_id": "ChatOutput-ghi", "x": 1500, "y": 300},
  {"node_id": "OpenAIModel-jkl", "x": 600, "y": 0},
])
```

---

## Key Concepts

### Custom Components: Inline Code vs File-Based

This MCP server uses **inline code** for custom components. When you call `add_custom_component`, the Python code is sent to Langflow's API which evaluates it dynamically and builds the node template on the fly. The code is stored directly on the node — no `.py` file creation, no server restart.

This is the same mechanism the Langflow UI uses when you edit a Custom Component node.

### Tool Mode

Any Langflow component can be made into a tool that an Agent can call. When you enable `tool_mode`:

1. The component's outputs are replaced with a single `component_as_tool` output (type: `Tool`)
2. A `tools_metadata` field is added for configuring tool names and descriptions
3. The `component_as_tool` output can be connected to an Agent's `tools` input

Use `set_tool_mode` or pass `tool_mode=True` to `add_node`/`add_custom_component`.

**Important:** Inputs marked `tool_mode=True` in the component code become parameters the Agent provides at call time. Inputs without `tool_mode` (or `tool_mode=False`) remain as static configuration.

### Build vs Save

API changes (adding nodes, connecting, updating config) only modify the flow's saved structure. Components don't execute until you call `build_flow`. Always build after making changes to verify everything works.

---

## Architecture

```
src/langflow_builder_mcp/
├── server.py           # MCP server entry point and tool registrations
├── instructions.py     # MCP server instructions for LLM guidance
├── concepts.py         # Langflow concept reference documentation
├── config.py           # Environment configuration (pydantic-settings)
├── client.py           # Langflow HTTP API client (with NDJSON support)
├── types.py            # Pydantic data models
├── schema_cache.py     # Component metadata cache
├── validator.py        # Connection type validation
├── generators.py       # Node/edge ID and structure generators
├── layout_engine.py    # Flow layout analysis and optimization
├── source_repo.py      # Langflow source code exploration
├── backup.py           # Flow backup functionality
└── tools/
    ├── build.py        # Build and execution tools
    ├── components.py   # Component discovery tools
    ├── flows.py        # Flow CRUD tools
    ├── nodes.py        # Node manipulation tools
    ├── edges.py        # Connection management tools
    └── source.py       # Langflow source code exploration tools
```

---

## Development

```bash
# Clone and install in development mode
git clone https://github.com/sportsrecruits/langflow-builder-mcp.git
cd langflow-builder-mcp
pip install -e ".[dev]"

# Run tests
pytest

# Format code
ruff format .

# Lint
ruff check .
```

### Running the server directly

```bash
# Via the entry point
langflow-builder-mcp

# Via Python module
python -m langflow_builder_mcp.server
```

The server communicates over stdio using the MCP protocol. It's designed to be launched by an MCP client (Claude Code, Cursor, etc.), not run standalone.

---

## Troubleshooting

### "Component type not found"

The component name is case-sensitive and must match exactly. Use `search_components` to find the correct name:

```
search_components(query="openai")
```

### "Error executing tool build_flow"

Make sure your Langflow instance is running and accessible at the configured URL. The build API uses NDJSON streaming — this server handles it correctly, but network timeouts on large flows may need the timeout increased:

```bash
export LANGFLOW_MCP_REQUEST_TIMEOUT=60.0
```

### Custom component code errors

If `add_custom_component` fails, the error message will include the validation error from Langflow. Common issues:
- Missing imports (always import from `langflow.custom`, `langflow.io`, `langflow.schema`)
- Method referenced in `Output` doesn't exist on the class
- Return type annotation missing on output methods

### Connection type mismatches

Use `validate_connection` before connecting, or `find_compatible_connections` to discover what can connect to what:

```
find_compatible_connections(flow_id="...", node_id="Agent-abc", direction="inputs")
```

---

## License

MIT
