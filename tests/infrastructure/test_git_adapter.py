"""Tests for GitAdapter — URL validation, symlink protection, size limits."""

from __future__ import annotations

import asyncio
import os

import pytest

from spectra.entities.errors import GitError
from spectra.infrastructure.git_adapter import (
    _MAX_FILE_SIZE,
    _MAX_TOTAL_BYTES,
    GitAdapter,
)


@pytest.fixture
def adapter() -> GitAdapter:
    return GitAdapter()


# ── URL validation ───────────────────────────────────────────


class TestCloneValidation:
    @pytest.mark.asyncio
    async def test_https_url_accepted(self, adapter: GitAdapter, tmp_path):
        """HTTPS URLs pass URL validation — mock clone_from to avoid network."""
        from unittest.mock import patch, MagicMock

        with patch("spectra.infrastructure.git_adapter.git.Repo.clone_from") as mock_clone:
            mock_clone.return_value = MagicMock()
            await adapter.clone("https://github.com/test/repo.git", str(tmp_path / "out"))
            mock_clone.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_url_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("file:///tmp/evil", str(tmp_path / "out"))

    @pytest.mark.asyncio
    async def test_ssh_url_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("ssh://git@github.com/user/repo.git", str(tmp_path / "out"))

    @pytest.mark.asyncio
    async def test_git_protocol_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("git://github.com/user/repo.git", str(tmp_path / "out"))

    @pytest.mark.asyncio
    async def test_empty_url_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("", str(tmp_path / "out"))


# ── File tree walking ────────────────────────────────────────


class TestWalkTree:
    @pytest.mark.asyncio
    async def test_walks_regular_files(self, adapter: GitAdapter, tmp_path):
        (tmp_path / "a.py").write_text("code")
        (tmp_path / "b.txt").write_text("text")
        tree = await adapter.get_file_tree(str(tmp_path))
        assert sorted(tree) == ["a.py", "b.txt"]

    @pytest.mark.asyncio
    async def test_skips_symlinks(self, adapter: GitAdapter, tmp_path):
        real = tmp_path / "real.py"
        real.write_text("code")
        link = tmp_path / "link.py"
        link.symlink_to(real)
        tree = await adapter.get_file_tree(str(tmp_path))
        assert "link.py" not in tree
        assert "real.py" in tree

    @pytest.mark.asyncio
    async def test_skips_git_directory(self, adapter: GitAdapter, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")
        (tmp_path / "src.py").write_text("code")
        tree = await adapter.get_file_tree(str(tmp_path))
        assert tree == ["src.py"]

    @pytest.mark.asyncio
    async def test_recursive_walk(self, adapter: GitAdapter, tmp_path):
        sub = tmp_path / "src" / "pkg"
        sub.mkdir(parents=True)
        (sub / "main.py").write_text("code")
        tree = await adapter.get_file_tree(str(tmp_path))
        assert "src/pkg/main.py" in tree

    @pytest.mark.asyncio
    async def test_empty_directory(self, adapter: GitAdapter, tmp_path):
        tree = await adapter.get_file_tree(str(tmp_path))
        assert tree == []


# ── Read file protection ─────────────────────────────────────


class TestReadFile:
    @pytest.mark.asyncio
    async def test_reads_normal_file(self, adapter: GitAdapter, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello world")
        content = await adapter.read_file(str(tmp_path), "test.py")
        assert content == "hello world"

    @pytest.mark.asyncio
    async def test_blocks_symlink(self, adapter: GitAdapter, tmp_path):
        real = tmp_path / "real.txt"
        real.write_text("secret")
        link = tmp_path / "link.txt"
        link.symlink_to(real)
        with pytest.raises(ValueError, match="Symlink blocked"):
            await adapter.read_file(str(tmp_path), "link.txt")

    @pytest.mark.asyncio
    async def test_blocks_path_traversal(self, adapter: GitAdapter, tmp_path):
        # Create a file outside the repo directory
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        repo = tmp_path / "repo"
        repo.mkdir()

        with pytest.raises((ValueError, FileNotFoundError)):
            await adapter.read_file(str(repo), "../outside/secret.txt")

    @pytest.mark.asyncio
    async def test_blocks_oversized_file(self, adapter: GitAdapter, tmp_path):
        big = tmp_path / "big.bin"
        big.write_bytes(b"\x00" * (_MAX_FILE_SIZE + 1))
        with pytest.raises(ValueError, match="byte limit"):
            await adapter.read_file(str(tmp_path), "big.bin")

    @pytest.mark.asyncio
    async def test_nested_file_read(self, adapter: GitAdapter, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").write_text("nested content")
        content = await adapter.read_file(str(tmp_path), "src/main.py")
        assert content == "nested content"


# ── Repo size validation ─────────────────────────────────────


class TestValidateRepoSize:
    @pytest.mark.asyncio
    async def test_small_repo_passes(self, adapter: GitAdapter, tmp_path):
        for i in range(5):
            (tmp_path / f"file_{i}.py").write_text("code")
        await adapter.validate_repo_size(str(tmp_path))  # should not raise

    @pytest.mark.asyncio
    async def test_oversized_repo_rejected(self, adapter: GitAdapter, tmp_path):
        # Create files exceeding total byte limit
        chunk = b"\x00" * (10 * 1024 * 1024)  # 10 MB each
        for i in range(11):
            (tmp_path / f"big_{i}.bin").write_bytes(chunk)
        with pytest.raises(ValueError, match="MB limit"):
            await adapter.validate_repo_size(str(tmp_path))

    @pytest.mark.asyncio
    async def test_symlinks_skipped_in_size_check(self, adapter: GitAdapter, tmp_path):
        real = tmp_path / "real.py"
        real.write_text("code")
        (tmp_path / "link.py").symlink_to(real)
        # Should not double-count the symlinked file
        await adapter.validate_repo_size(str(tmp_path))

    @pytest.mark.asyncio
    async def test_git_dir_skipped_in_size_check(self, adapter: GitAdapter, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "objects").write_bytes(b"\x00" * 1000)
        (tmp_path / "src.py").write_text("code")
        await adapter.validate_repo_size(str(tmp_path))
