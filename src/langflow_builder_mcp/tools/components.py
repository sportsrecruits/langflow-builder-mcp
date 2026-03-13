"""MCP tools for component discovery."""

from typing import Any

from ..schema_cache import ComponentSchemaCache
from ..types import ComponentSchema, ComponentSummary


async def list_component_categories(cache: ComponentSchemaCache) -> list[str]:
    """List all available component categories.

    Returns categories like: agents, models, vectorstores, embeddings,
    data, helpers, input_output, tools, processing, etc.

    Returns:
        List of category names
    """
    await cache.ensure_loaded()
    return cache.get_categories()


async def list_components_in_category(
    cache: ComponentSchemaCache,
    category: str,
) -> list[dict[str, Any]]:
    """List all components in a category with basic info.

    Args:
        category: Category name (e.g., "agents", "models")

    Returns:
        List of component summaries with name, display_name, description
    """
    await cache.ensure_loaded()
    component_names = cache.get_components_in_category(category)

    results = []
    for comp_name in component_names:
        schema = cache.get_component(comp_name)
        if schema:
            results.append(
                {
                    "name": comp_name,
                    "display_name": schema.display_name,
                    "description": schema.description[:200] if schema.description else "",
                    "icon": schema.icon,
                }
            )

    return results


async def get_component_schema(
    cache: ComponentSchemaCache,
    component_type: str,
) -> dict[str, Any]:
    """Get full schema for a component including all inputs and outputs.

    Args:
        component_type: Component type name (e.g., "Agent", "ChatInput")

    Returns:
        Full schema with:
        - inputs: dict of input fields with types, required, defaults
        - outputs: list of outputs with output_types
        - base_classes: list of compatible base classes
        - description: component description

    Raises:
        ValueError: If component type not found
    """
    await cache.ensure_loaded()
    schema = cache.get_component(component_type)

    if not schema:
        raise ValueError(f"Component type '{component_type}' not found")

    return {
        "name": schema.name,
        "display_name": schema.display_name,
        "description": schema.description,
        "category": schema.category,
        "icon": schema.icon,
        "inputs": {
            name: {
                "display_name": field.display_name,
                "type": field.type,
                "input_types": field.input_types,
                "required": field.required,
                "advanced": field.advanced,
                "default_value": field.value,
                "info": field.info,
                "options": field.options,
            }
            for name, field in schema.inputs.items()
        },
        "outputs": [
            {
                "name": out.name,
                "display_name": out.display_name,
                "types": out.types,
                "method": out.method,
            }
            for out in schema.outputs
        ],
        "base_classes": schema.base_classes,
        "output_types": schema.output_types,
    }


async def search_components(
    cache: ComponentSchemaCache,
    query: str,
) -> list[dict[str, Any]]:
    """Search components by name or description.

    Args:
        query: Search query (e.g., "openai", "vector", "qdrant")

    Returns:
        List of matching component summaries
    """
    await cache.ensure_loaded()
    results = cache.search_components(query)

    return [
        {
            "name": r.name,
            "display_name": r.display_name,
            "description": r.description[:200] if r.description else "",
            "category": r.category,
            "icon": r.icon,
        }
        for r in results
    ]


async def list_all_components(cache: ComponentSchemaCache) -> list[dict[str, Any]]:
    """List all available components.

    Returns:
        List of all component summaries grouped info
    """
    await cache.ensure_loaded()
    results = cache.list_all_components()

    return [
        {
            "name": r.name,
            "display_name": r.display_name,
            "description": r.description[:100] if r.description else "",
            "category": r.category,
        }
        for r in results
    ]
