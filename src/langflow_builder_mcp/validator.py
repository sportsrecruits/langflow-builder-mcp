"""Connection validation for Langflow flows."""

from .schema_cache import ComponentSchemaCache
from .types import ValidationResult


class ConnectionValidator:
    """Validates connections between nodes based on type compatibility."""

    def __init__(self, schema_cache: ComponentSchemaCache):
        """Initialize the validator.

        Args:
            schema_cache: Component schema cache for type lookups
        """
        self.schema_cache = schema_cache

    def validate_connection(
        self,
        source_component_type: str,
        source_output_name: str,
        target_component_type: str,
        target_input_name: str,
    ) -> ValidationResult:
        """Validate if a connection between two nodes is compatible.

        Logic mirrors Langflow's Edge._validate_handles():
        - Get output_types from source output
        - Get input_types from target input
        - Check if any output_type is in input_types

        Args:
            source_component_type: Component type of source node
            source_output_name: Name of output on source node
            target_component_type: Component type of target node
            target_input_name: Name of input field on target node

        Returns:
            ValidationResult with is_valid flag and details
        """
        # Get source output types
        source_types = self.schema_cache.get_output_types(
            source_component_type, source_output_name
        )

        if not source_types:
            # Check if the component or output exists
            source_schema = self.schema_cache.get_component(source_component_type)
            if not source_schema:
                return ValidationResult(
                    is_valid=False,
                    error=f"Component type '{source_component_type}' not found",
                )
            return ValidationResult(
                is_valid=False,
                error=f"Output '{source_output_name}' not found on {source_component_type}",
                source_types=[],
            )

        # Get target input types
        target_types = self.schema_cache.get_input_types(
            target_component_type, target_input_name
        )

        if not target_types:
            # Check if the component exists
            target_schema = self.schema_cache.get_component(target_component_type)
            if not target_schema:
                return ValidationResult(
                    is_valid=False,
                    error=f"Component type '{target_component_type}' not found",
                )

            # Check if input exists
            if target_input_name not in target_schema.inputs:
                return ValidationResult(
                    is_valid=False,
                    error=f"Input '{target_input_name}' not found on {target_component_type}",
                )

            # Empty input_types means it accepts any type
            return ValidationResult(
                is_valid=True,
                matched_types=source_types,
                source_types=source_types,
                target_types=[],
            )

        # Check for type compatibility
        matched = [t for t in source_types if t in target_types]

        if matched:
            return ValidationResult(
                is_valid=True,
                matched_types=matched,
                source_types=source_types,
                target_types=target_types,
            )
        else:
            return ValidationResult(
                is_valid=False,
                error=f"Type mismatch: source outputs {source_types} not compatible with target inputs {target_types}",
                source_types=source_types,
                target_types=target_types,
            )

    def find_compatible_outputs(
        self,
        target_component_type: str,
        target_input_name: str,
    ) -> list[tuple[str, str, list[str]]]:
        """Find all component outputs that could connect to a target input.

        Args:
            target_component_type: Component type of target node
            target_input_name: Name of input field on target node

        Returns:
            List of (component_type, output_name, matched_types) tuples
        """
        target_types = self.schema_cache.get_input_types(
            target_component_type, target_input_name
        )

        compatible: list[tuple[str, str, list[str]]] = []

        for comp_name, schema in self.schema_cache._cache.items():
            for output in schema.outputs:
                if not target_types:
                    # Accept any type
                    compatible.append((comp_name, output.name, output.types))
                else:
                    matched = [t for t in output.types if t in target_types]
                    if matched:
                        compatible.append((comp_name, output.name, matched))

        return compatible

    def find_compatible_inputs(
        self,
        source_component_type: str,
        source_output_name: str,
    ) -> list[tuple[str, str, list[str]]]:
        """Find all component inputs that could accept a source output.

        Args:
            source_component_type: Component type of source node
            source_output_name: Name of output on source node

        Returns:
            List of (component_type, input_name, matched_types) tuples
        """
        source_types = self.schema_cache.get_output_types(
            source_component_type, source_output_name
        )

        if not source_types:
            return []

        compatible: list[tuple[str, str, list[str]]] = []

        for comp_name, schema in self.schema_cache._cache.items():
            for input_name, input_field in schema.inputs.items():
                if not input_field.input_types:
                    # Accepts any type
                    compatible.append((comp_name, input_name, source_types))
                else:
                    matched = [t for t in source_types if t in input_field.input_types]
                    if matched:
                        compatible.append((comp_name, input_name, matched))

        return compatible


# Global validator instance
_validator: ConnectionValidator | None = None


def get_validator(schema_cache: ComponentSchemaCache | None = None) -> ConnectionValidator:
    """Get the global validator instance.

    Args:
        schema_cache: Optional schema cache to use

    Returns:
        ConnectionValidator instance
    """
    global _validator
    if _validator is None:
        if schema_cache is None:
            from .schema_cache import get_schema_cache

            schema_cache = get_schema_cache()
        _validator = ConnectionValidator(schema_cache)
    return _validator


def reset_validator() -> None:
    """Reset the global validator instance."""
    global _validator
    _validator = None
