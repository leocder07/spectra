"""Tests for GitAdapter — URL validation, symlink protection, size limits."""

from __future__ import annotations

import pytest

from spectra.entities.errors import GitError
from spectra.infrastructure.git_adapter import (
    _MAX_FILE_COUNT,
    _MAX_FILE_SIZE,
    _MAX_TOTAL_BYTES,
    _is_private_ip,
    GitAdapter,
)


@pytest.fixture
def adapter() -> GitAdapter:
    return GitAdapter()


# ── URL validation ───────────────────────────────────────────


class TestCloneValidation:
    @pytest.mark.asyncio
    async def test_https_url_accepted(self, adapter: GitAdapter, tmp_path):
        """HTTPS URLs pass URL validation -- mock clone_from to avoid network."""
        from unittest.mock import MagicMock, patch

        with patch("spectra.infrastructure.git_adapter.git.Repo.clone_from") as mock_clone:
            mock_clone.return_value = MagicMock()
            await adapter.clone("https://github.com/test/repo.git", str(tmp_path / "out"))
            mock_clone.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_url_rejected(self, adapter: GitAdapter, tmp_path):
        """Plain HTTP is rejected — HTTPS only."""
        with pytest.raises(GitError):
            await adapter.clone("http://github.com/test/repo.git", str(tmp_path / "out"))

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

    @pytest.mark.asyncio
    async def test_ftp_url_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("ftp://example.com/repo", str(tmp_path / "out"))

    @pytest.mark.asyncio
    async def test_relative_path_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("../local/repo", str(tmp_path / "out"))

    @pytest.mark.asyncio
    async def test_absolute_path_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("/tmp/local/repo", str(tmp_path / "out"))  # noqa: S108

    @pytest.mark.asyncio
    async def test_data_url_rejected(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(GitError):
            await adapter.clone("data:text/plain;base64,abc", str(tmp_path / "out"))

    @pytest.mark.asyncio
    async def test_git_clone_error_raises_git_error(self, adapter: GitAdapter, tmp_path):
        """GitCommandError from clone_from is wrapped as GitError."""
        from unittest.mock import patch

        import git

        with patch("spectra.infrastructure.git_adapter.git.Repo.clone_from") as mock_clone:
            mock_clone.side_effect = git.GitCommandError("clone", "fatal")
            with pytest.raises(GitError):
                await adapter.clone("https://github.com/test/repo.git", str(tmp_path / "out"))

    @pytest.mark.asyncio
    async def test_clone_passes_depth_1(self, adapter: GitAdapter, tmp_path):
        """Clone uses depth=1 for shallow clone."""
        from unittest.mock import MagicMock, patch

        with patch("spectra.infrastructure.git_adapter.git.Repo.clone_from") as mock_clone:
            mock_clone.return_value = MagicMock()
            await adapter.clone("https://github.com/test/repo.git", str(tmp_path / "out"))
            call_kwargs = mock_clone.call_args
            assert call_kwargs[1]["depth"] == 1


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

    @pytest.mark.asyncio
    async def test_nested_directories_multiple_files(self, adapter: GitAdapter, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("main")
        (tmp_path / "src" / "utils.py").write_text("utils")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("test")
        tree = await adapter.get_file_tree(str(tmp_path))
        assert len(tree) == 3
        assert "src/main.py" in tree
        assert "src/utils.py" in tree
        assert "tests/test_main.py" in tree

    @pytest.mark.asyncio
    async def test_hidden_files_included(self, adapter: GitAdapter, tmp_path):
        """Hidden files (except .git) should be included."""
        (tmp_path / ".env").write_text("SECRET=x")
        (tmp_path / "main.py").write_text("code")
        tree = await adapter.get_file_tree(str(tmp_path))
        assert ".env" in tree
        assert "main.py" in tree

    @pytest.mark.asyncio
    async def test_tree_is_sorted(self, adapter: GitAdapter, tmp_path):
        for name in ("z.py", "a.py", "m.py"):
            (tmp_path / name).write_text("code")
        tree = await adapter.get_file_tree(str(tmp_path))
        assert tree == sorted(tree)

    @pytest.mark.asyncio
    async def test_skips_symlink_directories(self, adapter: GitAdapter, tmp_path):
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.py").write_text("code")
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(real_dir)
        tree = await adapter.get_file_tree(str(tmp_path))
        # Files inside the symlinked directory should not appear
        assert not [f for f in tree if f.startswith("link_dir")]
        # The real dir files should appear
        assert "real_dir/file.py" in tree


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
    async def test_blocks_absolute_path_traversal(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(ValueError, match="Invalid file path"):
            await adapter.read_file(str(tmp_path), "/etc/passwd")

    @pytest.mark.asyncio
    async def test_blocks_null_byte_in_path(self, adapter: GitAdapter, tmp_path):
        with pytest.raises(ValueError, match="Invalid file path"):
            await adapter.read_file(str(tmp_path), "file\x00.py")

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

    @pytest.mark.asyncio
    async def test_file_at_size_limit(self, adapter: GitAdapter, tmp_path):
        """File exactly at the size limit should be readable."""
        f = tmp_path / "exact.bin"
        f.write_bytes(b"x" * _MAX_FILE_SIZE)
        content = await adapter.read_file(str(tmp_path), "exact.bin")
        assert len(content) == _MAX_FILE_SIZE

    @pytest.mark.asyncio
    async def test_nonexistent_file_raises(self, adapter: GitAdapter, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            await adapter.read_file(str(tmp_path), "nonexistent.py")

    @pytest.mark.asyncio
    async def test_empty_file_reads_empty(self, adapter: GitAdapter, tmp_path):
        (tmp_path / "empty.py").write_text("")
        content = await adapter.read_file(str(tmp_path), "empty.py")
        assert content == ""

    @pytest.mark.asyncio
    async def test_utf8_content(self, adapter: GitAdapter, tmp_path):
        (tmp_path / "unicode.py").write_text("# \u00e9\u00e8\u00ea unicode content \u2603")
        content = await adapter.read_file(str(tmp_path), "unicode.py")
        assert "\u2603" in content


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

    @pytest.mark.asyncio
    async def test_empty_repo_passes(self, adapter: GitAdapter, tmp_path):
        await adapter.validate_repo_size(str(tmp_path))  # should not raise

    @pytest.mark.asyncio
    async def test_single_file_repo_passes(self, adapter: GitAdapter, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        await adapter.validate_repo_size(str(tmp_path))  # should not raise

    @pytest.mark.asyncio
    async def test_nested_structure_passes(self, adapter: GitAdapter, tmp_path):
        for depth in range(5):
            d = tmp_path
            for j in range(depth + 1):
                d = d / f"dir_{j}"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"file_{depth}.py").write_text("code" * 10)
        await adapter.validate_repo_size(str(tmp_path))  # should not raise


# ── Constants ────────────────────────────────────────────────


class TestGitAdapterConstants:
    def test_max_file_size_is_1mb(self):
        assert _MAX_FILE_SIZE == 1_048_576

    def test_max_total_bytes_is_100mb(self):
        assert _MAX_TOTAL_BYTES == 100 * 1024 * 1024

    def test_max_file_count(self):
        assert _MAX_FILE_COUNT == 10_000


# ── SSRF prevention: _is_private_ip ──────────────────────────


class TestIsPrivateIp:
    """Tests for _is_private_ip SSRF protection."""

    def test_loopback_127_0_0_1(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_private_10_0_0_1(self):
        assert _is_private_ip("10.0.0.1") is True

    def test_private_192_168_1_1(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_private_172_16_0_1(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_link_local_169_254(self):
        assert _is_private_ip("169.254.1.1") is True

    def test_loopback_ipv6(self):
        assert _is_private_ip("::1") is True

    def test_public_ip_8_8_8_8(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_public_ip_1_1_1_1(self):
        assert _is_private_ip("1.1.1.1") is False

    def test_public_ip_93_184_216_34(self):
        assert _is_private_ip("93.184.216.34") is False

    def test_unresolvable_hostname_fails_closed(self):
        """Non-existent hostname must fail-closed: treat as private (block).

        Hardened policy: fail-closed on resolution failure. Returning False
        here would let a clone proceed against a host that Python could not
        resolve but git later might (e.g. a transient DNS failure in an
        attacker-controlled rebinding window).
        """
        assert _is_private_ip("this-host-does-not-exist-xyz123.invalid") is True

    def test_unspecified_0_0_0_0_blocked(self):
        """0.0.0.0 (unspecified) must be blocked."""
        assert _is_private_ip("0.0.0.0") is True

    def test_multicast_blocked(self):
        """Multicast addresses must be blocked."""
        assert _is_private_ip("224.0.0.1") is True

    def test_reserved_blocked(self):
        """Reserved IPv4 ranges must be blocked."""
        assert _is_private_ip("240.0.0.1") is True


# ── SSRF: clone rejects bad addrs via DNS ───────────────────


class TestCloneSSRFGuards:
    """Defence-in-depth: DNS that resolves to bad addrs must reject the clone."""

    @pytest.mark.asyncio
    async def test_clone_rejects_host_resolving_to_unspecified(
        self, adapter: GitAdapter, tmp_path, monkeypatch
    ):
        """If hostname resolves to 0.0.0.0, clone must be rejected."""
        import socket

        def fake_getaddrinfo(host, *_args, **_kwargs):
            return [(socket.AF_INET, 0, 0, "", ("0.0.0.0", 0))]

        monkeypatch.setattr(
            "spectra.infrastructure.git_adapter.socket.getaddrinfo",
            fake_getaddrinfo,
        )
        with pytest.raises(GitError):
            await adapter.clone(
                "https://evil.example.com/repo.git", str(tmp_path / "out")
            )

    @pytest.mark.asyncio
    async def test_clone_fails_closed_on_dns_resolution_error(
        self, adapter: GitAdapter, tmp_path, monkeypatch
    ):
        """DNS resolution failure must fail-closed (reject) before clone_from.

        Verifies the SSRF guard rejects unresolvable hosts *before* invoking
        git, not by relying on git itself to fail.
        """
        import socket
        from unittest.mock import patch

        def raising_getaddrinfo(*_args, **_kwargs):
            raise socket.gaierror("Name does not resolve")

        monkeypatch.setattr(
            "spectra.infrastructure.git_adapter.socket.getaddrinfo",
            raising_getaddrinfo,
        )
        with patch(
            "spectra.infrastructure.git_adapter.git.Repo.clone_from"
        ) as mock_clone:
            with pytest.raises(GitError):
                await adapter.clone(
                    "https://nonexistent-host-xyz.invalid/repo.git",
                    str(tmp_path / "out"),
                )
            mock_clone.assert_not_called()


# ── TOCTOU + intermediate-symlink bypass ─────────────────────


class TestIntermediateSymlinkBypass:
    """Catch attacks where an intermediate dir (not the leaf) is a symlink."""

    @pytest.mark.asyncio
    async def test_read_file_rejects_intermediate_symlink_dir(
        self, adapter: GitAdapter, tmp_path
    ):
        """repo/foo/link/file.txt where foo/link -> /etc must be blocked."""
        import os

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "foo").mkdir()
        # Plant intermediate symlink: foo/link -> some other tmp dir with file.txt
        external = tmp_path / "external"
        external.mkdir()
        (external / "file.txt").write_text("escaped content")
        os.symlink(str(external), str(repo / "foo" / "link"))

        # The leaf file.txt is NOT a symlink, but the intermediate "link" is.
        # Today this slips past leaf-only is_symlink() and resolve() follows it.
        with pytest.raises(ValueError, match="[Ss]ymlink"):
            await adapter.read_file(str(repo), "foo/link/file.txt")

    @pytest.mark.asyncio
    async def test_read_file_rejects_symlink_to_temp_clone_internal(
        self, adapter: GitAdapter, tmp_path
    ):
        """Even if symlink target is *inside* repo_dir, it must still be blocked."""
        import os

        repo = tmp_path / "repo"
        repo.mkdir()
        secret_dir = repo / ".git"
        secret_dir.mkdir()
        (secret_dir / "config").write_text("[user]\n  email = leak@example.com")
        (repo / "src").mkdir()
        # src/escape -> .git/config (inside repo, so passes is_relative_to)
        os.symlink(str(secret_dir / "config"), str(repo / "src" / "escape"))

        # The leaf IS a symlink — should be blocked by existing leaf check.
        with pytest.raises(ValueError, match="[Ss]ymlink"):
            await adapter.read_file(str(repo), "src/escape")

    @pytest.mark.asyncio
    async def test_walk_tree_does_not_traverse_symlinked_dirs(
        self, adapter: GitAdapter, tmp_path
    ):
        """rglob follows symlinked directories — must use os.walk(followlinks=False)."""
        import os

        repo = tmp_path / "repo"
        repo.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        (external / "leaked.txt").write_text("should not appear")
        # Create symlinked directory inside repo
        os.symlink(str(external), str(repo / "linkdir"))

        tree = await adapter.get_file_tree(str(repo))
        # leaked.txt must NOT appear under linkdir/ — the directory traversal
        # should not follow the symlink at all.
        assert not any("linkdir" in p for p in tree), (
            f"Symlinked dir was traversed: {tree}"
        )

    @pytest.mark.asyncio
    async def test_validate_repo_size_does_not_traverse_symlinked_dirs(
        self, adapter: GitAdapter, tmp_path
    ):
        """_check_size must not double-count via symlinked dirs (followlinks=False)."""
        import os

        repo = tmp_path / "repo"
        repo.mkdir()
        # External dir of huge size — would blow the limit if traversed
        external = tmp_path / "external"
        external.mkdir()
        # Write a single small file; the test asserts we do NOT descend at all
        (external / "leaked.bin").write_bytes(b"x" * 1024)
        os.symlink(str(external), str(repo / "linkdir"))

        # Should not raise — the linkdir must be skipped, not descended.
        await adapter.validate_repo_size(str(repo))
