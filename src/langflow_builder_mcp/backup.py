"""Auto-backup functionality for flow modifications."""

from datetime import datetime
from typing import Any

from .client import LangflowClient
from .config import get_config


async def get_or_create_backup_folder(client: LangflowClient) -> str:
    """Get or create the MCP Backups folder.

    Returns:
        Folder ID for backups
    """
    config = get_config()
    folder_name = config.backup_folder_name

    # List existing projects to find backup folder
    projects = await client.list_projects()
    for project in projects:
        if project.get("name") == folder_name:
            return project.get("id")

    # Create if doesn't exist
    new_project = await client.create_project(
        name=folder_name,
        description="Automatic backups created by MCP Flow Builder before modifications"
    )
    return new_project.get("id")


async def create_backup(
    client: LangflowClient,
    flow_id: str,
    reason: str,
) -> dict[str, Any] | None:
    """Create a backup of a flow before modification.

    Args:
        client: Langflow API client
        flow_id: Flow ID to backup
        reason: Why the backup was created (e.g., "before move_nodes_batch")

    Returns:
        Backup flow data if created, None if backups disabled
    """
    config = get_config()
    if not config.auto_backup_before_changes:
        return None

    # Get the original flow
    flow = await client.get_flow(flow_id)
    flow_name = flow.get("name", "Unknown")

    # Get or create backup folder
    backup_folder_id = await get_or_create_backup_folder(client)

    # Generate backup name with timestamp and revision
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Count existing backups for this flow to get revision number
    all_flows = await client.list_flows()
    existing_backups = [
        f for f in all_flows
        if f.get("name", "").startswith(f"[Backup] {flow_name}")
        and f.get("folder_id") == backup_folder_id
    ]
    revision = len(existing_backups) + 1

    backup_name = f"[Backup] {flow_name} (rev {revision})"
    backup_description = f"Backup created {timestamp}\nReason: {reason}\nOriginal flow ID: {flow_id}"

    # Create the backup flow
    backup_data = {
        "name": backup_name,
        "description": backup_description,
        "data": flow.get("data"),
        "folder_id": backup_folder_id,
    }

    backup_flow = await client.create_flow(backup_data)

    return {
        "backup_id": backup_flow.get("id"),
        "backup_name": backup_name,
        "revision": revision,
        "reason": reason,
    }
