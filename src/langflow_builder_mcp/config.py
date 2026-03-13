"""Configuration management for Langflow Flow Builder MCP Server."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_default_cache_dir() -> str:
    """Get the default cache directory for storing Langflow source."""
    # Use XDG_CACHE_HOME if set, otherwise ~/.cache
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache)
    else:
        base = Path.home() / ".cache"
    return str(base / "langflow-mcp")


class Config(BaseSettings):
    """MCP Server configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="LANGFLOW_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Langflow API connection
    langflow_url: str = "http://localhost:7860"
    api_key: str

    # Cache settings
    cache_ttl: int = 300  # Component cache TTL in seconds

    # Timeouts
    request_timeout: float = 30.0

    # Auto-backup settings
    auto_backup_before_changes: bool = False
    backup_folder_name: str = "MCP Backups"

    # Langflow version override (if not auto-detected from API)
    # Usually auto-detected, but can be set manually if needed
    langflow_version_override: str | None = None

    # Directory to cache Langflow source code for exploration
    # Defaults to ~/.cache/langflow-mcp or $XDG_CACHE_HOME/langflow-mcp
    langflow_source_cache_dir: str = _get_default_cache_dir()


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
