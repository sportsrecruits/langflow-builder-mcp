"""High-level semantic tools for common flow operations."""

from typing import Any

from ..client import LangflowClient
from ..generators import build_edge_structure, build_node_structure, generate_node_id
from ..schema_cache import ComponentSchemaCache
from ..validator import ConnectionValidator


# Common model mappings
MODEL_PROVIDERS = {
    "openai": {
        "component_type": "OpenAIModel",
        "model_field": "model_name",
        "api_key_field": "api_key",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"],
    },
    "anthropic": {
        "component_type": "ChatAnthropic",
        "model_field": "model",
        "api_key_field": "anthropic_api_key",
        "models": ["claude-3-5-sonnet", "claude-3-opus", "claude-3-haiku"],
    },
    "google": {
        "component_type": "GoogleGenerativeAIModel",
        "model_field": "model",
        "api_key_field": "google_api_key",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash"],
    },
}


async def create_agent_flow(
    client: LangflowClient,
    cache: ComponentSchemaCache,
    name: str,
    tools: list[str] | None = None,
    model_provider: str = "openai",
    model_name: str = "gpt-4o",
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Create a complete agent flow with chat input/output.

    This creates a flow with:
    - ChatInput node
    - Agent node (configured with specified model)
    - ChatOutput node
    - Tool nodes (if specified)
    - All necessary connections

    Args:
        name: Flow name
        tools: List of tool component types to add (e.g., ["Calculator", "WebSearch"])
        model_provider: LLM provider ("openai", "anthropic", "google")
        model_name: Model name (e.g., "gpt-4o", "claude-3-5-sonnet")
        system_prompt: Agent system prompt

    Returns:
        Created flow details
    """
    await cache.ensure_loaded()

    # Create the flow first
    flow_create_data = {
        "name": name,
        "description": f"Agent flow with {model_provider} {model_name}",
        "data": {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}},
    }
    created_flow = await client.create_flow(flow_create_data)
    flow_id = created_flow.get("id")

    nodes = []
    edges = []

    # Layout positions
    input_x, input_y = 100, 200
    agent_x, agent_y = 500, 200
    output_x, output_y = 900, 200
    tool_x, tool_y = 500, 450

    # 1. Create ChatInput node
    chat_input_id = generate_node_id("ChatInput")
    chat_input_schema = cache.get_component("ChatInput")
    chat_input_template = cache.get_raw_template("ChatInput")

    if chat_input_schema and chat_input_template:
        nodes.append(
            build_node_structure(
                node_id=chat_input_id,
                component_type="ChatInput",
                position_x=input_x,
                position_y=input_y,
                template=chat_input_template.get("template", {}),
                outputs=chat_input_template.get("outputs", []),
                base_classes=chat_input_schema.base_classes,
                display_name=chat_input_schema.display_name,
                description=chat_input_schema.description,
                icon=chat_input_schema.icon,
                category=chat_input_schema.category,
            )
        )

    # 2. Create Agent node
    agent_id = generate_node_id("Agent")
    agent_schema = cache.get_component("Agent")
    agent_template = cache.get_raw_template("Agent")

    if agent_schema and agent_template:
        template = agent_template.get("template", {}).copy()

        # Configure model
        if "model_name" in template:
            template["model_name"]["value"] = model_name
        if "agent_llm" in template:
            template["agent_llm"]["value"] = model_name

        # Configure system prompt
        if system_prompt and "system_prompt" in template:
            template["system_prompt"]["value"] = system_prompt

        nodes.append(
            build_node_structure(
                node_id=agent_id,
                component_type="Agent",
                position_x=agent_x,
                position_y=agent_y,
                template=template,
                outputs=agent_template.get("outputs", []),
                base_classes=agent_schema.base_classes,
                display_name=agent_schema.display_name,
                description=agent_schema.description,
                icon=agent_schema.icon,
                category=agent_schema.category,
            )
        )

    # 3. Create ChatOutput node
    chat_output_id = generate_node_id("ChatOutput")
    chat_output_schema = cache.get_component("ChatOutput")
    chat_output_template = cache.get_raw_template("ChatOutput")

    if chat_output_schema and chat_output_template:
        nodes.append(
            build_node_structure(
                node_id=chat_output_id,
                component_type="ChatOutput",
                position_x=output_x,
                position_y=output_y,
                template=chat_output_template.get("template", {}),
                outputs=chat_output_template.get("outputs", []),
                base_classes=chat_output_schema.base_classes,
                display_name=chat_output_schema.display_name,
                description=chat_output_schema.description,
                icon=chat_output_schema.icon,
                category=chat_output_schema.category,
            )
        )

    # 4. Create tool nodes if specified
    tool_node_ids = []
    if tools:
        for i, tool_type in enumerate(tools):
            tool_schema = cache.get_component(tool_type)
            tool_template = cache.get_raw_template(tool_type)

            if tool_schema and tool_template:
                tool_id = generate_node_id(tool_type)
                tool_node_ids.append(tool_id)

                template = tool_template.get("template", {}).copy()
                outputs = tool_template.get("outputs", [])
                base_classes = tool_schema.base_classes

                # Enable tool_mode via the Langflow API to get proper
                # component_as_tool output transformation
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
                    except Exception:
                        # Fall back to default template if API call fails
                        pass

                node_structure = build_node_structure(
                    node_id=tool_id,
                    component_type=tool_type,
                    position_x=tool_x + (i * 350),
                    position_y=tool_y,
                    template=template,
                    outputs=outputs,
                    base_classes=base_classes,
                    display_name=tool_schema.display_name,
                    description=tool_schema.description,
                    icon=tool_schema.icon,
                    category=tool_schema.category,
                )
                # Set tool_mode flag on the node data
                node_structure["data"]["node"]["tool_mode"] = True

                nodes.append(node_structure)

    # 5. Create edges

    # ChatInput -> Agent (input_value)
    edges.append(
        build_edge_structure(
            source_node_id=chat_input_id,
            source_component_type="ChatInput",
            source_output_name="message",
            source_output_types=["Message"],
            target_node_id=agent_id,
            target_field_name="input_value",
            target_input_types=["Message"],
            target_field_type="str",
        )
    )

    # Agent -> ChatOutput
    edges.append(
        build_edge_structure(
            source_node_id=agent_id,
            source_component_type="Agent",
            source_output_name="response",
            source_output_types=["Message"],
            target_node_id=chat_output_id,
            target_field_name="input_value",
            target_input_types=["Data", "DataFrame", "Message"],
            target_field_type="other",
        )
    )

    # Tools -> Agent
    for tool_id in tool_node_ids:
        # Get tool type from node id
        tool_type = tool_id.rsplit("-", 1)[0]
        edges.append(
            build_edge_structure(
                source_node_id=tool_id,
                source_component_type=tool_type,
                source_output_name="component_as_tool",
                source_output_types=["Tool"],
                target_node_id=agent_id,
                target_field_name="tools",
                target_input_types=["Tool"],
                target_field_type="other",
            )
        )

    # Update flow with nodes and edges
    flow_data = {
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
    }
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "id": flow_id,
        "name": name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": {
            "chat_input": chat_input_id,
            "agent": agent_id,
            "chat_output": chat_output_id,
            "tools": tool_node_ids,
        },
        "message": f"Created agent flow '{name}' with {len(tool_node_ids)} tools",
    }


async def create_rag_flow(
    client: LangflowClient,
    cache: ComponentSchemaCache,
    name: str,
    vector_store: str = "Qdrant",
    embedding_model: str = "OpenAIEmbeddings",
    llm_provider: str = "openai",
    llm_model: str = "gpt-4o",
) -> dict[str, Any]:
    """Create a RAG (Retrieval Augmented Generation) flow.

    This creates a flow with:
    - ChatInput node
    - Vector store node (for retrieval)
    - Embedding model node
    - LLM/Agent node
    - ChatOutput node
    - Prompt node for RAG template

    Args:
        name: Flow name
        vector_store: Vector store type (e.g., "Qdrant", "Pinecone", "Chroma")
        embedding_model: Embedding model type
        llm_provider: LLM provider
        llm_model: LLM model name

    Returns:
        Created flow details
    """
    await cache.ensure_loaded()

    # Create the flow
    flow_create_data = {
        "name": name,
        "description": f"RAG flow with {vector_store} and {llm_provider} {llm_model}",
        "data": {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}},
    }
    created_flow = await client.create_flow(flow_create_data)
    flow_id = created_flow.get("id")

    nodes = []
    edges = []

    # Layout positions (horizontal flow)
    chat_input_pos = (100, 200)
    vectorstore_pos = (500, 400)
    embedding_pos = (100, 400)
    agent_pos = (900, 200)
    chat_output_pos = (1300, 200)

    created_nodes = {}

    # Helper to create a node
    async def create_node(
        component_type: str, position: tuple, config: dict | None = None
    ) -> str | None:
        schema = cache.get_component(component_type)
        template_raw = cache.get_raw_template(component_type)

        if not schema or not template_raw:
            return None

        node_id = generate_node_id(component_type)
        template = template_raw.get("template", {}).copy()

        if config:
            for key, value in config.items():
                if key in template:
                    template[key]["value"] = value

        nodes.append(
            build_node_structure(
                node_id=node_id,
                component_type=component_type,
                position_x=position[0],
                position_y=position[1],
                template=template,
                outputs=template_raw.get("outputs", []),
                base_classes=schema.base_classes,
                display_name=schema.display_name,
                description=schema.description,
                icon=schema.icon,
                category=schema.category,
            )
        )

        return node_id

    # Create nodes
    chat_input_id = await create_node("ChatInput", chat_input_pos)
    embedding_id = await create_node(embedding_model, embedding_pos)
    vectorstore_id = await create_node(vector_store, vectorstore_pos)
    agent_id = await create_node("Agent", agent_pos, {"model_name": llm_model})
    chat_output_id = await create_node("ChatOutput", chat_output_pos)

    created_nodes = {
        "chat_input": chat_input_id,
        "embedding": embedding_id,
        "vectorstore": vectorstore_id,
        "agent": agent_id,
        "chat_output": chat_output_id,
    }

    # Create edges
    if chat_input_id and agent_id:
        edges.append(
            build_edge_structure(
                source_node_id=chat_input_id,
                source_component_type="ChatInput",
                source_output_name="message",
                source_output_types=["Message"],
                target_node_id=agent_id,
                target_field_name="input_value",
                target_input_types=["Message"],
            )
        )

    if agent_id and chat_output_id:
        edges.append(
            build_edge_structure(
                source_node_id=agent_id,
                source_component_type="Agent",
                source_output_name="response",
                source_output_types=["Message"],
                target_node_id=chat_output_id,
                target_field_name="input_value",
                target_input_types=["Data", "DataFrame", "Message"],
            )
        )

    if vectorstore_id and agent_id:
        # Connect vectorstore as a tool to the agent
        edges.append(
            build_edge_structure(
                source_node_id=vectorstore_id,
                source_component_type=vector_store,
                source_output_name="retriever",
                source_output_types=["Retriever"],
                target_node_id=agent_id,
                target_field_name="tools",
                target_input_types=["Tool", "Retriever"],
            )
        )

    if embedding_id and vectorstore_id:
        # Connect embeddings to vectorstore
        edges.append(
            build_edge_structure(
                source_node_id=embedding_id,
                source_component_type=embedding_model,
                source_output_name="embeddings",
                source_output_types=["Embeddings"],
                target_node_id=vectorstore_id,
                target_field_name="embedding",
                target_input_types=["Embeddings"],
            )
        )

    # Update flow
    flow_data = {
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 0, "y": 0, "zoom": 0.7},
    }
    await client.update_flow(flow_id, {"data": flow_data})

    return {
        "id": flow_id,
        "name": name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": created_nodes,
        "message": f"Created RAG flow '{name}' with {vector_store}",
    }


async def explain_flow(client: LangflowClient, flow_id: str) -> str:
    """Generate a natural language explanation of a flow.

    Args:
        flow_id: Flow UUID

    Returns:
        Human-readable description of the flow
    """
    flow = await client.get_flow(flow_id)
    flow_data = flow.get("data", {})
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Build node descriptions
    node_descriptions = []
    node_map = {}

    for node in nodes:
        node_id = node.get("id")
        node_data = node.get("data", {})
        node_config = node_data.get("node", {})
        component_type = node_config.get("key") or node_data.get("type")
        display_name = node_config.get("display_name", component_type)

        node_map[node_id] = display_name
        node_descriptions.append(f"- {display_name} ({node_id})")

    # Build edge descriptions
    edge_descriptions = []
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        edge_data = edge.get("data", {})
        source_handle = edge_data.get("sourceHandle", {})
        target_handle = edge_data.get("targetHandle", {})

        source_name = node_map.get(source, source)
        target_name = node_map.get(target, target)
        output_name = source_handle.get("name", "output")
        input_name = target_handle.get("fieldName", "input")

        edge_descriptions.append(
            f"- {source_name}.{output_name} -> {target_name}.{input_name}"
        )

    # Build explanation
    explanation = f"""## Flow: {flow.get('name', 'Unnamed')}

**Description:** {flow.get('description') or 'No description'}

### Components ({len(nodes)} nodes):
{chr(10).join(node_descriptions)}

### Connections ({len(edges)} edges):
{chr(10).join(edge_descriptions) if edge_descriptions else '- No connections'}
"""

    return explanation
