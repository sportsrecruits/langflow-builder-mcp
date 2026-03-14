"""Build and execution tool implementations."""

import asyncio
from typing import Any

from ..client import LangflowClient


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


async def build_flow(
    client: LangflowClient,
    flow_id: str,
    input_value: str | None,
    input_type: str,
    wait_for_completion: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Build and execute a flow."""
    build_result = await client.build_flow(
        flow_id,
        input_value=input_value,
        input_type=input_type,
    )

    # If the response already contains events (NDJSON mode), it completed inline
    if "events" in build_result:
        return _summarize_build_events(build_result)

    if not wait_for_completion:
        return {
            "status": "started",
            "job_id": build_result.get("job_id"),
            "message": "Build started. Use get_build_status to poll for completion.",
        }

    # Poll for completion using job_id
    job_id = build_result.get("job_id")
    if not job_id:
        return build_result

    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout_seconds:
            return {
                "status": "timeout",
                "job_id": job_id,
                "elapsed_seconds": elapsed,
                "message": f"Build did not complete within {timeout_seconds} seconds",
            }

        try:
            result = await client.get_build_events(job_id)

            # get_build_events returns {"events": [...], "status": "completed"}
            if result.get("status") in ("completed", "error"):
                return _summarize_build_events(result)

            # Check individual events for end/error
            events = result.get("events", [])
            for evt in events:
                evt_type = evt.get("event", evt.get("type", ""))
                if evt_type in ("end", "error"):
                    return _summarize_build_events(result)

        except Exception as e:
            # 404 means job completed and was cleaned up
            if "404" in str(e):
                return {"status": "completed", "job_id": job_id}
            raise

        await asyncio.sleep(0.5)


async def build_node(
    client: LangflowClient,
    flow_id: str,
    node_id: str,
) -> dict[str, Any]:
    """Build a single node (vertex) in a flow."""
    return await client.build_vertex(flow_id, node_id)


async def get_build_status(
    client: LangflowClient,
    job_id: str,
) -> dict[str, Any]:
    """Get the status and events for a build job."""
    return await client.get_build_events(job_id)
