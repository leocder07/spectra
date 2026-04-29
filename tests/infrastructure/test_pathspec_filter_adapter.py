"""Tests for PathspecFilterAdapter — .gitignore + .spectraignore honor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from spectra.infrastructure.pathspec_filter_adapter import PathspecFilterAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def adapter() -> PathspecFilterAdapter:
    return PathspecFilterAdapter()


# ── .gitignore honor ─────────────────────────────────────────


class TestGitignoreHonor:
    def test_excludes_env_file(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        (tmp_path / ".gitignore").write_text(".env\n")
        files = [".env", "src/main.py", "README.md"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert ".env" not in kept
        assert "src/main.py" in kept
        assert "README.md" in kept

    def test_excludes_directory_pattern(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        files = ["node_modules/foo/index.js", "src/app.ts"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert "node_modules/foo/index.js" not in kept
        assert "src/app.ts" in kept

    def test_excludes_glob_pattern(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n")
        files = ["debug.log", "src/main.py"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert "debug.log" not in kept
        assert "src/main.py" in kept

    def test_no_gitignore_keeps_everything(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        files = [".env", "src/main.py", "node_modules/foo.js"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert kept == files

    def test_nested_gitignore_honored(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        (tmp_path / ".gitignore").write_text("dist/\n")
        sub = tmp_path / "packages" / "ui"
        sub.mkdir(parents=True)
        (sub / ".gitignore").write_text("local-build/\n")
        files = [
            "packages/ui/local-build/bundle.js",
            "packages/ui/src/index.ts",
            "dist/main.js",
            "src/app.py",
        ]
        kept = adapter.filter_files(str(tmp_path), files)
        assert "packages/ui/local-build/bundle.js" not in kept
        assert "dist/main.js" not in kept
        assert "packages/ui/src/index.ts" in kept
        assert "src/app.py" in kept

    def test_negation_pattern(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n!important.log\n")
        files = ["debug.log", "important.log"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert "debug.log" not in kept
        assert "important.log" in kept


# ── .spectraignore layered on top ────────────────────────────


class TestSpectraignore:
    def test_excludes_vendor_when_not_in_gitignore(
        self,
        tmp_path: Path,
        adapter: PathspecFilterAdapter,
    ) -> None:
        # No .gitignore entry for vendor/
        (tmp_path / ".gitignore").write_text(".env\n")
        (tmp_path / ".spectraignore").write_text("vendor/\n")
        files = ["vendor/lib.go", "src/main.go", ".env"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert "vendor/lib.go" not in kept
        assert ".env" not in kept
        assert "src/main.go" in kept

    def test_layered_with_gitignore(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / ".spectraignore").write_text("docs/\n")
        files = ["debug.log", "docs/intro.md", "src/main.py"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert "debug.log" not in kept
        assert "docs/intro.md" not in kept
        assert "src/main.py" in kept

    def test_spectraignore_only_no_gitignore(
        self,
        tmp_path: Path,
        adapter: PathspecFilterAdapter,
    ) -> None:
        (tmp_path / ".spectraignore").write_text("secrets/\n")
        files = ["secrets/key.pem", "src/app.py"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert "secrets/key.pem" not in kept
        assert "src/app.py" in kept


# ── Bypass ────────────────────────────────────────────────────


class TestBypass:
    def test_honor_gitignore_false_keeps_everything(
        self,
        tmp_path: Path,
    ) -> None:
        adapter = PathspecFilterAdapter(honor_gitignore=False)
        (tmp_path / ".gitignore").write_text(".env\nnode_modules/\n")
        files = [".env", "node_modules/foo.js", "src/main.py"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert kept == files

    def test_honor_gitignore_false_still_honors_spectraignore(
        self,
        tmp_path: Path,
    ) -> None:
        adapter = PathspecFilterAdapter(honor_gitignore=False)
        (tmp_path / ".gitignore").write_text(".env\n")
        (tmp_path / ".spectraignore").write_text("vendor/\n")
        files = [".env", "vendor/lib.go", "src/main.py"]
        kept = adapter.filter_files(str(tmp_path), files)
        # .env is allowed (gitignore bypassed) but vendor/ blocked (.spectraignore still active)
        assert ".env" in kept
        assert "vendor/lib.go" not in kept
        assert "src/main.py" in kept


# ── Edge cases ────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_file_list(self, tmp_path: Path, adapter: PathspecFilterAdapter) -> None:
        (tmp_path / ".gitignore").write_text(".env\n")
        assert adapter.filter_files(str(tmp_path), []) == []

    def test_comments_and_blank_lines_skipped(
        self,
        tmp_path: Path,
        adapter: PathspecFilterAdapter,
    ) -> None:
        (tmp_path / ".gitignore").write_text("# comment\n\n.env\n")
        kept = adapter.filter_files(str(tmp_path), [".env", "src/main.py"])
        assert ".env" not in kept
        assert "src/main.py" in kept

    def test_returns_input_order_preserved(
        self,
        tmp_path: Path,
        adapter: PathspecFilterAdapter,
    ) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n")
        files = ["zeta.py", "alpha.py", "beta.py"]
        kept = adapter.filter_files(str(tmp_path), files)
        assert kept == files
