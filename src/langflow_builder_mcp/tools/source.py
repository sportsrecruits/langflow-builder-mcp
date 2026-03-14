"""Langflow source code exploration tool implementations."""

import json
from typing import Any

from ..client import LangflowClient
from ..config import get_config
from ..source_repo import get_source_repo

# Cache for Langflow version
_langflow_version_cache: str | None = None


async def _get_langflow_version(client: LangflowClient) -> str:
    """Get the Langflow version from API or config override."""
    global _langflow_version_cache

    config = get_config()
    if config.langflow_version_override:
        return config.langflow_version_override

    if _langflow_version_cache:
        return _langflow_version_cache

    try:
        version_info = await client.get_version()
        _langflow_version_cache = version_info.get("version", "main")
        return _langflow_version_cache
    except Exception:
        return "main"


def _require_source_repo() -> str | None:
    """Check if the source repo is cloned and ready.

    Returns None if ready, or a JSON error string if not.
    """
    repo = get_source_repo()
    if not repo.is_cloned:
        return json.dumps(
            {
                "error": "Langflow source repository is not set up yet.",
                "action_required": "Call the setup_langflow_source tool first. "
                "It will clone the Langflow repository locally (this takes 1-2 minutes "
                "on first run). After that, explore_langflow, read_langflow_file, and "
                "list_langflow_directory will work.",
                "tool_to_call": "setup_langflow_source",
            },
            indent=2,
        )
    return None


async def setup_langflow_source(client: LangflowClient) -> dict[str, Any]:
    """Clone/update the Langflow source code repository."""
    version = await _get_langflow_version(client)
    repo = get_source_repo()
    return await repo.ensure_version(version)


async def explore_langflow(
    client: LangflowClient,
    query: str,
    path_filter: str,
    max_results: int,
) -> dict[str, Any] | str:
    """Search Langflow's source code."""
    error = _require_source_repo()
    if error:
        return error

    version = await _get_langflow_version(client)
    repo = get_source_repo()
    matches = await repo.search_files(query, path_filter, max_results)

    return {
        "langflow_version": version,
        "query": query,
        "path_filter": path_filter,
        "result_count": len(matches),
        "results": matches,
        "tip": "Use read_langflow_file to get the full content of any file",
    }


async def read_langflow_file(
    client: LangflowClient,
    file_path: str,
    start_line: int,
    end_line: int,
) -> dict[str, Any] | str:
    """Read a file from Langflow's source code."""
    error = _require_source_repo()
    if error:
        return error

    version = await _get_langflow_version(client)
    repo = get_source_repo()
    result = repo.read_file(file_path, start_line, end_line)
    result["langflow_version"] = version
    return result


async def list_langflow_directory(
    client: LangflowClient,
    directory: str,
) -> dict[str, Any] | str:
    """List files in a directory of the Langflow repository."""
    error = _require_source_repo()
    if error:
        return error

    version = await _get_langflow_version(client)
    repo = get_source_repo()
    result = repo.list_directory(directory)
    result["langflow_version"] = version
    return result
