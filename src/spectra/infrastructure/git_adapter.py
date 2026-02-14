"""Git adapter — implements GitPort using GitPython."""

from __future__ import annotations

import asyncio
from pathlib import Path

import git

from spectra.entities.errors import ERRORS, SpectraError

_MAX_FILE_COUNT = 10_000
_MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MB


class GitError(Exception):
    """Raised when a git operation fails with a domain error."""

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


class GitAdapter:
    """Async wrapper around GitPython implementing the GitPort protocol."""

    async def clone(self, repo_url: str, target_dir: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: git.Repo.clone_from(
                    repo_url,
                    target_dir,
                    depth=1,
                    multi_options=["--config core.hooksPath=/dev/null"],
                ),
            )
        except git.GitCommandError as exc:
            raise GitError(ERRORS["SPEC-001"]) from exc

    async def get_file_tree(self, repo_dir: str) -> list[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._walk_tree, repo_dir)

    async def read_file(self, repo_dir: str, file_path: str) -> str:
        """Read a file with path traversal and symlink protection."""
        root = Path(repo_dir).resolve()
        full = (root / file_path).resolve()
        if not full.is_relative_to(root):
            msg = f"Path traversal blocked: {file_path}"
            raise ValueError(msg)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, full.read_text, "utf-8"
        )

    async def validate_repo_size(self, repo_dir: str) -> None:
        """Reject repos exceeding file count or total size limits."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._check_size, repo_dir)

    @staticmethod
    def _check_size(repo_dir: str) -> None:
        root = Path(repo_dir)
        count = 0
        total_bytes = 0
        for p in root.rglob("*"):
            if not p.is_file() or ".git" in p.parts:
                continue
            count += 1
            if count > _MAX_FILE_COUNT:
                msg = f"Repository exceeds {_MAX_FILE_COUNT} file limit"
                raise ValueError(msg)
            total_bytes += p.stat().st_size
            if total_bytes > _MAX_TOTAL_BYTES:
                msg = f"Repository exceeds {_MAX_TOTAL_BYTES // (1024 * 1024)}MB limit"
                raise ValueError(msg)

    @staticmethod
    def _walk_tree(repo_dir: str) -> list[str]:
        root = Path(repo_dir)
        return sorted(
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts
        )
