"""Langflow source code repository management.

Clones and manages a local copy of the Langflow repository for code exploration.
Uses shallow clones (--depth 1) for fast setup (~5 seconds instead of minutes).
"""

import asyncio
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import get_config

LANGFLOW_REPO_URL = "https://github.com/langflow-ai/langflow.git"


class LangflowSourceRepo:
    """Manages a local clone of the Langflow repository."""

    def __init__(self, cache_dir: str | None = None):
        """Initialize the source repo manager.

        Args:
            cache_dir: Directory to store the cloned repo. Defaults to config value.
        """
        if cache_dir is None:
            cache_dir = get_config().langflow_source_cache_dir
        self.cache_dir = Path(cache_dir)
        self.repo_dir = self.cache_dir / "langflow"
        self._current_version: str | None = None
        self._lock = asyncio.Lock()

    @property
    def is_cloned(self) -> bool:
        """Check if the repository is already cloned."""
        return (self.repo_dir / ".git").is_dir()

    def _run_git(self, *args: str, cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + list(args)
        return subprocess.run(
            cmd,
            cwd=cwd or self.repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    async def _run_git_async(
        self, *args: str, cwd: Path | None = None, timeout: int = 60
    ) -> subprocess.CompletedProcess:
        """Run a git command asynchronously."""
        return await asyncio.to_thread(self._run_git, *args, cwd=cwd, timeout=timeout)

    async def _find_best_tag(self, version: str) -> str | None:
        """Find the best matching tag for a version using ls-remote (no clone needed).

        Args:
            version: Version string like "1.6.5"

        Returns:
            Tag name (e.g., "v1.6.5") or None if no match
        """
        # Use ls-remote to list tags without cloning — fast network call
        result = await self._run_git_async(
            "ls-remote", "--tags", "--refs", LANGFLOW_REPO_URL,
            cwd=self.cache_dir if self.cache_dir.exists() else Path.home(),
            timeout=30,
        )
        if result.returncode != 0:
            return None

        # Parse tags from ls-remote output: "<sha>\trefs/tags/<tag>"
        tags = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                tag = parts[1].replace("refs/tags/", "")
                tags.append(tag)

        if not tags:
            return None

        # Try exact match first
        exact_tag = f"v{version}"
        if exact_tag in tags:
            return exact_tag

        # Parse version
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
        if not match:
            return None

        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))

        # Find release tags (not dev/pre-release)
        release_pattern = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
        releases = []
        for tag in tags:
            m = release_pattern.match(tag)
            if m:
                t_major, t_minor, t_patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
                releases.append((t_major, t_minor, t_patch, tag))

        if not releases:
            return None

        # Sort descending and find closest version <= requested
        releases.sort(reverse=True)
        for t_major, t_minor, t_patch, tag in releases:
            if (t_major, t_minor, t_patch) <= (major, minor, patch):
                return tag

        # If requested version is older than all releases, use oldest
        return releases[-1][3]

    async def clone_version(self, version: str) -> dict[str, Any]:
        """Clone the repo at a specific version using a shallow clone.

        This is fast (~5 seconds) because it only downloads one commit.

        Args:
            version: Version string like "1.6.5"

        Returns:
            Status dict
        """
        async with self._lock:
            # If already cloned at this version, skip
            if self.is_cloned and self._current_version == version:
                return {"status": "ok", "version": version, "path": str(self.repo_dir)}

            # Find the best tag for this version
            tag = await self._find_best_tag(version)
            ref = tag or "main"

            # If already cloned but wrong version, remove and re-clone
            # (shallow clones can't easily switch tags)
            if self.is_cloned:
                shutil.rmtree(self.repo_dir)

            # Create cache directory
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            # Shallow clone — only 1 commit, single branch, no tags overhead
            result = await self._run_git_async(
                "clone",
                "--depth", "1",
                "--single-branch",
                "--branch", ref,
                "--no-tags",
                LANGFLOW_REPO_URL,
                str(self.repo_dir),
                cwd=self.cache_dir,
                timeout=120,
            )

            if result.returncode != 0:
                return {
                    "status": "error",
                    "error": result.stderr,
                    "attempted_ref": ref,
                }

            self._current_version = version
            return {
                "status": "ok",
                "ref": ref,
                "version": version,
                "path": str(self.repo_dir),
            }

    async def ensure_version(self, version: str) -> dict[str, Any]:
        """Ensure the repo is cloned and at the correct version.

        Args:
            version: Version string like "1.6.5"

        Returns:
            Status dict with path to source code
        """
        if self._current_version == version and self.is_cloned:
            return {"status": "ok", "version": version, "path": str(self.repo_dir)}

        return await self.clone_version(version)

    def get_source_path(self) -> Path | None:
        """Get the path to the source code, or None if not available."""
        if self.is_cloned:
            return self.repo_dir
        return None

    async def search_files(
        self,
        query: str,
        path_filter: str = "src/backend",
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for files containing a query string.

        Args:
            query: Search term
            path_filter: Path prefix to search in
            max_results: Maximum results

        Returns:
            List of matches with file, line, and content
        """
        if not self.is_cloned:
            return []

        search_path = self.repo_dir / path_filter

        if not search_path.exists():
            search_path = self.repo_dir

        # Use git grep for speed
        result = await self._run_git_async(
            "grep", "-n", "-I",  # Line numbers, skip binary
            "--max-count", "5",  # Max matches per file
            "-e", query,
            "--", str(search_path.relative_to(self.repo_dir)),
        )

        matches = []
        for line in result.stdout.strip().split("\n")[:max_results]:
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({
                    "file": parts[0],
                    "line": int(parts[1]) if parts[1].isdigit() else 0,
                    "content": parts[2][:200],
                })

        return matches

    def read_file(
        self,
        file_path: str,
        start_line: int = 1,
        end_line: int = 0,
    ) -> dict[str, Any]:
        """Read a file from the repository.

        Args:
            file_path: Path relative to repo root
            start_line: Starting line (1-indexed)
            end_line: Ending line (0 = to end, max 500 lines)

        Returns:
            Dict with file content and metadata
        """
        if not self.is_cloned:
            return {"error": "Repository not cloned"}

        full_path = self.repo_dir / file_path
        if not full_path.is_file():
            return {"error": f"File not found: {file_path}"}

        # Security check
        try:
            full_path.resolve().relative_to(self.repo_dir.resolve())
        except ValueError:
            return {"error": "Path traversal not allowed"}

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            start_idx = max(0, start_line - 1)
            if end_line > 0:
                end_idx = min(end_line, len(lines))
            else:
                end_idx = min(start_idx + 500, len(lines))

            selected = lines[start_idx:end_idx]
            content = "".join(
                f"{i:4d} | {line}"
                for i, line in enumerate(selected, start=start_idx + 1)
            )

            return {
                "file": file_path,
                "start_line": start_idx + 1,
                "end_line": start_idx + len(selected),
                "total_lines": len(lines),
                "content": content,
                "truncated": end_idx < len(lines),
            }
        except Exception as e:
            return {"error": str(e)}

    def list_directory(self, directory: str = "src/backend/base/langflow") -> dict[str, Any]:
        """List files in a directory.

        Args:
            directory: Path relative to repo root

        Returns:
            Dict with files and subdirectories
        """
        if not self.is_cloned:
            return {"error": "Repository not cloned"}

        dir_path = self.repo_dir / directory
        if not dir_path.is_dir():
            return {"error": f"Directory not found: {directory}"}

        # Security check
        try:
            dir_path.resolve().relative_to(self.repo_dir.resolve())
        except ValueError:
            return {"error": "Path traversal not allowed"}

        files = []
        directories = []

        for item in sorted(dir_path.iterdir()):
            rel_path = str(item.relative_to(self.repo_dir))
            if item.is_file():
                files.append({"name": item.name, "path": rel_path})
            elif item.is_dir() and not item.name.startswith("."):
                directories.append({"name": item.name, "path": rel_path})

        return {
            "directory": directory,
            "subdirectories": directories,
            "files": files,
        }


# Global instance
_source_repo: LangflowSourceRepo | None = None


def get_source_repo() -> LangflowSourceRepo:
    """Get the global source repo instance."""
    global _source_repo
    if _source_repo is None:
        _source_repo = LangflowSourceRepo()
    return _source_repo
