"""Git adapter — implements GitPort using GitPython."""

from __future__ import annotations

import asyncio
from pathlib import Path

import git

from spectra.entities.errors import ERRORS, GitError

_MAX_FILE_COUNT = 10_000
_MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_FILE_SIZE = 1_048_576  # 1 MB per file
_CLONE_TIMEOUT = 120  # seconds


class GitAdapter:
    """Async wrapper around GitPython implementing the GitPort protocol."""

    async def clone(self, repo_url: str, target_dir: str) -> None:
        if not repo_url.startswith(("https://", "http://")):
            raise GitError(ERRORS["SPEC-001"])
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: git.Repo.clone_from(
                        repo_url,
                        target_dir,
                        depth=1,
                        multi_options=[
                            "--config core.hooksPath=/dev/null",
                            "--no-recurse-submodules",
                        ],
                    ),
                ),
                timeout=_CLONE_TIMEOUT,
            )
        except TimeoutError:
            raise GitError(ERRORS["SPEC-001"]) from None
        except git.GitCommandError as exc:
            raise GitError(ERRORS["SPEC-001"]) from exc

    async def get_file_tree(self, repo_dir: str) -> list[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._walk_tree, repo_dir)

    async def read_file(self, repo_dir: str, file_path: str) -> str:
        """Read a file with path traversal, symlink, and size protection."""
        root = Path(repo_dir).resolve()
        raw = root / file_path
        if raw.is_symlink():
            msg = f"Symlink blocked: {file_path}"
            raise ValueError(msg)
        full = raw.resolve()
        if not full.is_relative_to(root):
            msg = f"Path traversal blocked: {file_path}"
            raise ValueError(msg)
        if full.stat().st_size > _MAX_FILE_SIZE:
            msg = f"File exceeds {_MAX_FILE_SIZE} byte limit: {file_path}"
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
            if p.is_symlink() or not p.is_file() or ".git" in p.parts:
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
            if p.is_file() and not p.is_symlink() and ".git" not in p.parts
        )
