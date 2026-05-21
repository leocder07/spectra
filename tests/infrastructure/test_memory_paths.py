"""Tests for memory path resolution (v0.9.1, ADR-025 wiring).

Per the design doc §3 + §6 storage decision:

  Default:  $XDG_DATA_HOME/spectra/memory/<sha256-of-canonical-repo-url>.db
  Override: --memory-dir on the CLI (highest precedence)
  Env:      SPECTRA_MEMORY_DIR

These tests pin the resolution rules so a future remote KV adapter cannot
silently weaken the per-URL keying (the layer the audit-trail relies on).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from spectra.infrastructure.memory_paths import (
    canonicalize_repo_url,
    default_memory_dir,
    memory_db_for,
    resolve_memory_dir,
)


class TestDefaultMemoryDir:
    """Spec: $XDG_DATA_HOME/spectra/memory when XDG set; ~/.local/share/spectra/memory when unset."""

    def test_uses_xdg_data_home_when_set(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        xdg = tmp_path / "xdg-data"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
        assert default_memory_dir() == xdg / "spectra" / "memory"

    def test_falls_back_to_home_local_share_when_xdg_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert default_memory_dir() == tmp_path / ".local" / "share" / "spectra" / "memory"

    def test_falls_back_to_home_when_xdg_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", "")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert default_memory_dir() == tmp_path / ".local" / "share" / "spectra" / "memory"


class TestResolveMemoryDir:
    """Spec: CLI override > env var > default."""

    def test_cli_override_wins_over_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        cli = tmp_path / "from-cli"
        env = tmp_path / "from-env"
        monkeypatch.setenv("SPECTRA_MEMORY_DIR", str(env))
        assert resolve_memory_dir(cli_override=str(cli)) == cli

    def test_env_used_when_no_cli_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        env = tmp_path / "from-env"
        monkeypatch.setenv("SPECTRA_MEMORY_DIR", str(env))
        assert resolve_memory_dir(cli_override=None) == env

    def test_default_used_when_neither_cli_nor_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        xdg = tmp_path / "xdg-data"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
        monkeypatch.delenv("SPECTRA_MEMORY_DIR", raising=False)
        assert resolve_memory_dir(cli_override=None) == xdg / "spectra" / "memory"

    def test_empty_env_treated_as_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        xdg = tmp_path / "xdg-data"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
        monkeypatch.setenv("SPECTRA_MEMORY_DIR", "")
        assert resolve_memory_dir(cli_override=None) == xdg / "spectra" / "memory"


class TestCanonicalizeRepoUrl:
    """Spec: scheme+host lowercase, strip trailing .git and /, file:// and bare paths resolve absolute."""

    def test_lowercases_scheme_and_host(self) -> None:
        assert canonicalize_repo_url("HTTPS://GitHub.COM/Foo/Bar") == "https://github.com/Foo/Bar"

    def test_strips_trailing_git(self) -> None:
        assert canonicalize_repo_url("https://github.com/foo/bar.git") == "https://github.com/foo/bar"

    def test_strips_trailing_slash(self) -> None:
        assert canonicalize_repo_url("https://github.com/foo/bar/") == "https://github.com/foo/bar"

    def test_strips_both_trailing_slash_and_git(self) -> None:
        assert canonicalize_repo_url("https://github.com/foo/bar.git/") == "https://github.com/foo/bar"

    def test_preserves_case_of_path_component(self) -> None:
        # Path components are case-sensitive on most VCS hosts (GitHub case-folds owner
        # but ToolForge etc. do not). We do not normalize the path.
        assert canonicalize_repo_url("https://github.com/LeoCder07/Spectra") == "https://github.com/LeoCder07/Spectra"

    def test_resolves_relative_local_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "myrepo").mkdir()
        result = canonicalize_repo_url("./myrepo")
        assert result == str((tmp_path / "myrepo").resolve())

    def test_resolves_file_url(self, tmp_path: Path) -> None:
        target = tmp_path / "myrepo"
        target.mkdir()
        result = canonicalize_repo_url(f"file://{target}")
        assert result == str(target.resolve())

    def test_resolves_absolute_local_path(self, tmp_path: Path) -> None:
        (tmp_path / "x").mkdir()
        assert canonicalize_repo_url(str(tmp_path / "x")) == str((tmp_path / "x").resolve())

    def test_scp_ssh_normalizes_to_https_equivalent(self) -> None:
        # Greptile #90: SCP-style URLs should not fragment memory by cwd
        assert canonicalize_repo_url("git@github.com:foo/bar.git") == "https://github.com/foo/bar"
        assert canonicalize_repo_url("user@gitlab.example.com:org/repo") == "https://gitlab.example.com/org/repo"

    def test_scp_ssh_and_https_yield_same_canonical(self) -> None:
        ssh = canonicalize_repo_url("git@github.com:foo/bar.git")
        https = canonicalize_repo_url("https://github.com/foo/bar.git")
        assert ssh == https

    def test_ssh_scheme_collapses_to_https(self) -> None:
        # Greptile #90 round 2: ssh:// URLs collapse to https for memory sharing
        assert canonicalize_repo_url("ssh://git@github.com/foo/bar.git") == "https://github.com/foo/bar"

    def test_git_plus_ssh_scheme_collapses_to_https(self) -> None:
        assert canonicalize_repo_url("git+ssh://git@github.com/foo/bar.git") == "https://github.com/foo/bar"

    def test_git_scheme_collapses_to_https(self) -> None:
        assert canonicalize_repo_url("git://github.com/foo/bar.git") == "https://github.com/foo/bar"

    def test_default_https_port_stripped(self) -> None:
        a = canonicalize_repo_url("https://github.com/foo/bar")
        b = canonicalize_repo_url("https://github.com:443/foo/bar")
        assert a == b == "https://github.com/foo/bar"

    def test_default_http_port_stripped(self) -> None:
        a = canonicalize_repo_url("http://internal-gitea/foo/bar")
        b = canonicalize_repo_url("http://internal-gitea:80/foo/bar")
        assert a == b == "http://internal-gitea/foo/bar"

    def test_non_default_port_preserved(self) -> None:
        # Self-hosted Gitea on :3000 must keep the port (different server)
        assert (
            canonicalize_repo_url("https://gitea.example.com:3000/foo/bar") == "https://gitea.example.com:3000/foo/bar"
        )

    def test_dot_dot_segments_normalized(self) -> None:
        # Security review MEDIUM: posixpath.normpath collapses ../ traversal
        assert canonicalize_repo_url("https://github.com/foo/bar/../baz") == "https://github.com/foo/baz"

    def test_double_slash_collapsed(self) -> None:
        assert canonicalize_repo_url("https://github.com/foo//bar") == "https://github.com/foo/bar"


class TestMemoryDbFor:
    """Spec: deterministic per-canonical-URL sha256, under the resolved memory dir."""

    def test_two_equivalent_urls_hash_to_same_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = memory_db_for("https://github.com/foo/bar.git")
        b = memory_db_for("HTTPS://GitHub.com/foo/bar/")
        assert a == b
        assert a.parent == tmp_path / "spectra" / "memory"

    def test_filename_is_sha256_of_canonical_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        url = "https://github.com/foo/bar"
        expected_stem = hashlib.sha256(url.encode("utf-8")).hexdigest()
        result = memory_db_for(url)
        assert result.stem == expected_stem
        assert result.suffix == ".db"

    def test_different_urls_hash_to_different_files(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = memory_db_for("https://github.com/foo/bar")
        b = memory_db_for("https://github.com/foo/baz")
        assert a != b

    def test_uses_explicit_memory_dir_when_given(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom-mem"
        result = memory_db_for("https://github.com/foo/bar", memory_dir=custom)
        assert result.parent == custom

    def test_local_path_input_uses_resolved_absolute_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        repo = tmp_path / "my-local-repo"
        repo.mkdir()
        # Pass relative path via chdir
        monkeypatch.chdir(tmp_path)
        result_rel = memory_db_for("./my-local-repo")
        result_abs = memory_db_for(str(repo))
        # Both should resolve to the same canonical absolute and thus the same DB
        assert result_rel == result_abs
