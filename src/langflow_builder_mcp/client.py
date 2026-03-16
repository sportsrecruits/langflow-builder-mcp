"""HTTP client for Langflow API."""

import json
from typing import Any

import httpx

from .config import Config


class LangflowClient:
    """Async HTTP client for interacting with Langflow API."""

    def __init__(self, config: Config | None = None):
        """Initialize the client with configuration.

        Args:
            config: Configuration object. If None, uses default config.
        """
        if config is None:
            from .config import get_config

            config = get_config()

        self.base_url = config.langflow_url.rstrip("/")
        self.timeout = config.request_timeout
        self.headers: dict[str, str] = {
            "Content-Type": "application/json",
            "x-api-key": config.api_key,
            **config.custom_headers,
        }

    def _build_url(self, path: str) -> str:
        """Build full URL for API endpoint."""
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}/api/v1{path}"

    async def get(self, path: str, **params: Any) -> Any:
        """Make GET request to Langflow API.

        Args:
            path: API path (e.g., "/flows" or "/all")
            **params: Query parameters

        Returns:
            JSON response data
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self._build_url(path),
                headers=self.headers,
                params=params if params else None,
            )
            response.raise_for_status()
            return response.json()

    async def post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """Make POST request to Langflow API.

        Args:
            path: API path
            data: Request body as dictionary

        Returns:
            JSON response data
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._build_url(path),
                headers=self.headers,
                json=data or {},
            )
            response.raise_for_status()
            return response.json()

    async def patch(self, path: str, data: dict[str, Any]) -> Any:
        """Make PATCH request to Langflow API.

        Args:
            path: API path
            data: Request body as dictionary

        Returns:
            JSON response data
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                self._build_url(path),
                headers=self.headers,
                json=data,
            )
            response.raise_for_status()
            return response.json()

    async def delete(self, path: str) -> Any:
        """Make DELETE request to Langflow API.

        Args:
            path: API path

        Returns:
            JSON response data
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.delete(
                self._build_url(path),
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    # Convenience methods for common operations

    async def get_version(self) -> dict[str, Any]:
        """Get Langflow version information.

        Returns:
            Version info dict with 'version', 'main_version', 'package' keys
        """
        return await self.get("/version")

    async def get_all_components(self) -> dict[str, Any]:
        """Get all available component types and their metadata.

        Returns:
            Dictionary of component categories and their components
        """
        return await self.get("/all")

    async def list_flows(self, **params: Any) -> list[dict[str, Any]]:
        """List all flows.

        Args:
            **params: Query parameters (e.g., folder_id, components_only)

        Returns:
            List of flow summaries
        """
        return await self.get("/flows/", **params)

    async def get_flow(self, flow_id: str) -> dict[str, Any]:
        """Get a single flow by ID.

        Args:
            flow_id: Flow UUID

        Returns:
            Complete flow data including nodes and edges
        """
        return await self.get(f"/flows/{flow_id}")

    async def create_flow(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new flow.

        Args:
            data: Flow creation data (name, description, data, etc.)

        Returns:
            Created flow data
        """
        return await self.post("/flows/", data)

    async def update_flow(self, flow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing flow.

        Args:
            flow_id: Flow UUID
            data: Partial update data

        Returns:
            Updated flow data
        """
        return await self.patch(f"/flows/{flow_id}", data)

    async def delete_flow(self, flow_id: str) -> dict[str, Any]:
        """Delete a flow.

        Args:
            flow_id: Flow UUID

        Returns:
            Deletion confirmation
        """
        return await self.delete(f"/flows/{flow_id}")

    async def list_projects(self) -> list[dict[str, Any]]:
        """List all projects (folders).

        Returns:
            List of project summaries
        """
        return await self.get("/projects/")

    async def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        """Create a new project (folder).

        Args:
            name: Project name
            description: Project description

        Returns:
            Created project data
        """
        return await self.post("/projects/", {"name": name, "description": description})

    @staticmethod
    def _parse_ndjson(text: str) -> list[dict[str, Any]]:
        """Parse newline-delimited JSON (NDJSON) response.

        The Langflow build API returns NDJSON (application/x-ndjson),
        where each line is a separate JSON object. Standard json.loads()
        fails on this because it expects a single root object.

        Args:
            text: Raw response text containing one or more JSON objects

        Returns:
            List of parsed JSON objects
        """
        events = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    async def build_flow(
        self,
        flow_id: str,
        input_value: str | None = None,
        input_type: str = "chat",
    ) -> dict[str, Any]:
        """Build/run a flow.

        This executes all components in the flow, processing inputs and
        producing outputs. The build API returns NDJSON (newline-delimited
        JSON), which this method handles correctly.

        Args:
            flow_id: Flow UUID
            input_value: Optional input value (for chat/text inputs)
            input_type: Type of input ("chat", "text", or "any")

        Returns:
            Build result — either a single dict (job_id for polling)
            or a dict with collected events if the response is NDJSON
        """
        data: dict[str, Any] = {}
        if input_value is not None:
            data["inputs"] = {
                "input_value": input_value,
                "type": input_type,
            }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._build_url(f"/build/{flow_id}/flow"),
                headers=self.headers,
                json=data,
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            # Handle NDJSON responses from the build API
            if "ndjson" in content_type:
                events = self._parse_ndjson(response.text)
                if len(events) == 1:
                    return events[0]
                return {"events": events, "status": "completed"}

            # Try standard JSON first, fall back to NDJSON parsing
            try:
                return response.json()
            except json.JSONDecodeError:
                events = self._parse_ndjson(response.text)
                if len(events) == 1:
                    return events[0]
                return {"events": events, "status": "completed"}

    async def get_build_events(self, job_id: str) -> dict[str, Any]:
        """Get events for a build job.

        The events endpoint returns NDJSON (newline-delimited JSON),
        not standard JSON.

        Args:
            job_id: Build job ID from build_flow response

        Returns:
            Dict with list of parsed events
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self._build_url(f"/build/{job_id}/events"),
                headers=self.headers,
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "ndjson" in content_type:
                events = self._parse_ndjson(response.text)
                return {"events": events, "status": "completed"}

            try:
                return response.json()
            except json.JSONDecodeError:
                events = self._parse_ndjson(response.text)
                return {"events": events, "status": "completed"}

    async def build_vertex(
        self,
        flow_id: str,
        vertex_id: str,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a single vertex (node) in a flow.

        This executes just one component, useful for testing or
        partial updates.

        Args:
            flow_id: Flow UUID
            vertex_id: Vertex/Node ID to build
            inputs: Optional input values for the vertex

        Returns:
            Build result for the vertex
        """
        data: dict[str, Any] = {}
        if inputs:
            data["inputs"] = inputs
        return await self.post(f"/build/{flow_id}/vertices/{vertex_id}", data)

    async def get_vertices_order(self, flow_id: str) -> dict[str, Any]:
        """Get the build order for vertices in a flow.

        This returns the topologically sorted order in which
        vertices should be built.

        Args:
            flow_id: Flow UUID

        Returns:
            Vertices order information
        """
        return await self.post(f"/build/{flow_id}/vertices", {})

    async def create_custom_component(
        self,
        code: str,
        frontend_node: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create/validate a custom component from Python code.

        Calls POST /custom_component to evaluate the code and build the
        full node template (inputs, outputs, base_classes, etc.) dynamically.
        No server restart required.

        Args:
            code: Python code defining the component class
            frontend_node: Optional existing node state to merge with

        Returns:
            Dict with 'data' (the built frontend node) and 'type' (component type name)
        """
        data: dict[str, Any] = {"code": code}
        if frontend_node is not None:
            data["frontend_node"] = frontend_node
        return await self.post("/custom_component", data)

    async def update_custom_component(
        self,
        code: str,
        template: dict[str, Any],
        field: str,
        field_value: Any = None,
        tool_mode: bool = False,
    ) -> dict[str, Any]:
        """Update a custom component via the /custom_component/update endpoint.

        This triggers server-side processing including tool_mode output
        transformation, build config updates, and output validation.

        Args:
            code: Component Python code (from template.code.value)
            template: Full template dict from the node
            field: Field name being updated (e.g., "tool_mode")
            field_value: New value for the field
            tool_mode: Whether tool_mode should be enabled

        Returns:
            Updated component node data with transformed outputs and template
        """
        data = {
            "code": code,
            "template": template,
            "field": field,
            "field_value": field_value,
            "tool_mode": tool_mode,
        }
        return await self.post("/custom_component/update", data)


# Global client instance
_client: LangflowClient | None = None


def get_client() -> LangflowClient:
    """Get the global client instance."""
    global _client
    if _client is None:
        _client = LangflowClient()
    return _client


def reset_client() -> None:
    """Reset the global client instance (useful for testing)."""
    global _client
    _client = None
