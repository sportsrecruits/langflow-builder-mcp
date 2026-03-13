"""Component schema cache for Langflow components."""

import time
from typing import Any

from .client import LangflowClient
from .types import ComponentSchema, ComponentSummary, InputField, OutputField


class ComponentSchemaCache:
    """Cache for component metadata loaded from Langflow API."""

    def __init__(self, client: LangflowClient, ttl: int = 300):
        """Initialize the cache.

        Args:
            client: Langflow API client
            ttl: Cache time-to-live in seconds
        """
        self.client = client
        self.ttl = ttl
        self._cache: dict[str, ComponentSchema] = {}
        self._categories: dict[str, list[str]] = {}
        self._raw_templates: dict[str, dict[str, Any]] = {}
        self._loaded_at: float = 0
        self._loaded = False

    def _is_expired(self) -> bool:
        """Check if cache has expired."""
        if not self._loaded:
            return True
        return time.time() - self._loaded_at > self.ttl

    async def load(self, force: bool = False) -> None:
        """Load all component metadata from Langflow API.

        Args:
            force: Force reload even if cache is valid
        """
        if not force and not self._is_expired():
            return

        response = await self.client.get_all_components()

        self._cache.clear()
        self._categories.clear()
        self._raw_templates.clear()

        for category, components in response.items():
            if not isinstance(components, dict):
                continue

            self._categories[category] = []

            for comp_name, template in components.items():
                if not isinstance(template, dict):
                    continue

                self._categories[category].append(comp_name)
                self._raw_templates[comp_name] = template
                self._cache[comp_name] = self._parse_template(comp_name, category, template)

        self._loaded = True
        self._loaded_at = time.time()

    def _parse_template(
        self, comp_name: str, category: str, template: dict[str, Any]
    ) -> ComponentSchema:
        """Parse a component template into a ComponentSchema.

        Args:
            comp_name: Component type name
            category: Component category
            template: Raw template from API

        Returns:
            Parsed ComponentSchema
        """
        # Parse inputs from template
        inputs: dict[str, InputField] = {}
        raw_template = template.get("template", {})

        for field_name, field_data in raw_template.items():
            if not isinstance(field_data, dict):
                continue
            if field_name.startswith("_"):
                continue

            inputs[field_name] = InputField(
                name=field_name,
                display_name=field_data.get("display_name", field_name),
                type=field_data.get("type", "str"),
                input_types=field_data.get("input_types", []),
                required=field_data.get("required", False),
                advanced=field_data.get("advanced", False),
                value=field_data.get("value"),
                info=field_data.get("info", ""),
                options=field_data.get("options"),
            )

        # Parse outputs
        outputs: list[OutputField] = []
        for output_data in template.get("outputs", []):
            if not isinstance(output_data, dict):
                continue
            outputs.append(
                OutputField(
                    name=output_data.get("name", ""),
                    display_name=output_data.get("display_name", ""),
                    types=output_data.get("types", []),
                    method=output_data.get("method", ""),
                    selected=output_data.get("selected"),
                )
            )

        return ComponentSchema(
            name=comp_name,
            display_name=template.get("display_name", comp_name),
            description=template.get("description", ""),
            category=category,
            icon=template.get("icon", ""),
            inputs=inputs,
            outputs=outputs,
            base_classes=template.get("base_classes", []),
            output_types=template.get("output_types", []),
        )

    async def ensure_loaded(self) -> None:
        """Ensure cache is loaded, loading if necessary."""
        if self._is_expired():
            await self.load()

    def get_categories(self) -> list[str]:
        """Get list of component categories.

        Returns:
            List of category names
        """
        return list(self._categories.keys())

    def get_components_in_category(self, category: str) -> list[str]:
        """Get component names in a category.

        Args:
            category: Category name

        Returns:
            List of component type names
        """
        return self._categories.get(category, [])

    def get_component(self, component_type: str) -> ComponentSchema | None:
        """Get component schema by type name.

        Args:
            component_type: Component type name (e.g., "Agent", "ChatInput")

        Returns:
            ComponentSchema or None if not found
        """
        return self._cache.get(component_type)

    def get_raw_template(self, component_type: str) -> dict[str, Any] | None:
        """Get raw template for a component type.

        Args:
            component_type: Component type name

        Returns:
            Raw template dict or None if not found
        """
        return self._raw_templates.get(component_type)

    def get_output_types(self, component_type: str, output_name: str) -> list[str]:
        """Get output types for a specific output on a component.

        Args:
            component_type: Component type name
            output_name: Output name

        Returns:
            List of output types
        """
        schema = self._cache.get(component_type)
        if not schema:
            return []
        for output in schema.outputs:
            if output.name == output_name:
                return output.types
        return []

    def get_input_types(self, component_type: str, input_name: str) -> list[str]:
        """Get acceptable input types for a specific input on a component.

        Args:
            component_type: Component type name
            input_name: Input field name

        Returns:
            List of acceptable input types
        """
        schema = self._cache.get(component_type)
        if not schema:
            return []
        input_field = schema.inputs.get(input_name)
        if not input_field:
            return []
        return input_field.input_types

    def search_components(self, query: str) -> list[ComponentSummary]:
        """Search components by name or description.

        Args:
            query: Search query (case-insensitive)

        Returns:
            List of matching component summaries
        """
        query_lower = query.lower()
        results: list[ComponentSummary] = []

        for comp_name, schema in self._cache.items():
            if (
                query_lower in comp_name.lower()
                or query_lower in schema.display_name.lower()
                or query_lower in schema.description.lower()
            ):
                results.append(
                    ComponentSummary(
                        name=comp_name,
                        display_name=schema.display_name,
                        description=schema.description,
                        category=schema.category,
                        icon=schema.icon,
                    )
                )

        return results

    def list_all_components(self) -> list[ComponentSummary]:
        """List all components as summaries.

        Returns:
            List of all component summaries
        """
        return [
            ComponentSummary(
                name=comp_name,
                display_name=schema.display_name,
                description=schema.description,
                category=schema.category,
                icon=schema.icon,
            )
            for comp_name, schema in self._cache.items()
        ]


# Global cache instance
_cache: ComponentSchemaCache | None = None


def get_schema_cache(client: LangflowClient | None = None) -> ComponentSchemaCache:
    """Get the global schema cache instance.

    Args:
        client: Optional client to use. If None, uses global client.

    Returns:
        ComponentSchemaCache instance
    """
    global _cache
    if _cache is None:
        if client is None:
            from .client import get_client

            client = get_client()
        _cache = ComponentSchemaCache(client)
    return _cache


def reset_cache() -> None:
    """Reset the global cache instance."""
    global _cache
    _cache = None
