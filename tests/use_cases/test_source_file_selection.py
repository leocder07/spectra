"""Tests for the source-file selection use case (Fix R3-Arch-2).

The selection heuristic — entry points first, then config, then ``src/`` source,
then any other source extension — used to live in ``infrastructure/main.py``.
That made it impossible to unit-test without spinning up the composition root,
and worse, it located domain logic ("which files carry the architecture /
security / quality signal") in the outermost layer instead of the use-case
layer where it belongs.

These tests pin the contract so the move is safe: same input file_tree → same
ranked output, identical to the legacy infrastructure helper.
"""

from __future__ import annotations

from spectra.use_cases.source_file_selection import (
    MAX_HEURISTIC_FILES,
    MAX_HEURISTIC_TOKENS,
    prioritize_source_files,
)


class TestPrioritizeSourceFiles:
    """Ranking is tier-based: entry > config > src/ source > other source."""

    def test_empty_tree_yields_empty_list(self) -> None:
        assert prioritize_source_files([]) == []

    def test_entry_point_python_file_ranks_first(self) -> None:
        tree = ["docs/index.md", "src/lib/util.py", "src/main.py"]
        result = prioritize_source_files(tree)
        # main.py is an entry stem (.py is a source ext) — must come before
        # the other src/ source file even though the tree order put it last.
        assert result[0] == "src/main.py"

    def test_config_files_rank_above_other_source(self) -> None:
        tree = ["src/lib/util.py", "pyproject.toml"]
        result = prioritize_source_files(tree)
        assert result == ["pyproject.toml", "src/lib/util.py"]

    def test_src_prefix_source_ranks_above_other_source(self) -> None:
        tree = ["random/foo.py", "src/lib/util.py"]
        result = prioritize_source_files(tree)
        assert result == ["src/lib/util.py", "random/foo.py"]

    def test_non_source_extension_is_excluded(self) -> None:
        tree = ["README.md", "docs/guide.txt", "src/main.py"]
        result = prioritize_source_files(tree)
        assert result == ["src/main.py"]

    def test_known_entry_stems_across_extensions(self) -> None:
        # All five entry stems are recognised across language extensions.
        tree = [
            "app.ts",
            "index.js",
            "server.go",
            "cli.rs",
            "__main__.py",
        ]
        result = prioritize_source_files(tree)
        # Every entry-stem file ends up in the first tier.
        assert set(result) == set(tree)
        assert len(result) == len(tree)

    def test_all_known_config_names_picked_up(self) -> None:
        tree = ["pyproject.toml", "package.json", "Cargo.toml", "go.mod"]
        result = prioritize_source_files(tree)
        assert set(result) == set(tree)

    def test_pure_function_input_not_mutated(self) -> None:
        tree = ["src/main.py", "pyproject.toml", "src/lib/util.py"]
        snapshot = list(tree)
        prioritize_source_files(tree)
        assert tree == snapshot

    def test_ranking_matches_legacy_infrastructure_helper(self) -> None:
        """Byte-identical contract with the previous infra helper.

        Ranking order: entry stems → config files → ``src/``-prefixed
        source → other source extensions.
        """
        tree = [
            "tests/test_foo.py",  # other source (no src/ prefix)
            "src/main.py",  # entry stem
            "pyproject.toml",  # config
            "src/lib/util.py",  # src/ source
            "README.md",  # excluded
        ]
        expected = [
            "src/main.py",
            "pyproject.toml",
            "src/lib/util.py",
            "tests/test_foo.py",
        ]
        assert prioritize_source_files(tree) == expected


class TestPublicConstants:
    """Selection caps are exposed as constants so callers can wire token budgets."""

    def test_max_files_cap_is_sane(self) -> None:
        assert MAX_HEURISTIC_FILES > 0
        assert MAX_HEURISTIC_FILES <= 50

    def test_max_tokens_cap_is_sane(self) -> None:
        assert MAX_HEURISTIC_TOKENS >= 50_000
