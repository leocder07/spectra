"""Heuristic source-file selection for specialist agent prompts.

Layer 2 — use case. Lives here (not in ``infrastructure/``) because the
ranking is **domain logic**: it codifies which files most likely carry the
architecture / security / quality signal a specialist agent needs to do
its job. The composition root only orchestrates I/O against the ranking.

Decision tiers, highest priority first:

1. **Entry points** — files whose stem is one of ``main``, ``app``,
   ``index``, ``server``, ``cli``, ``__main__`` and whose extension is a
   known source language. These are the agent's ground-zero anchors.
2. **Configuration manifests** — ``pyproject.toml``, ``package.json``,
   ``Cargo.toml``, ``go.mod``. They expose dependencies and toolchain.
3. **First-party source** — paths under ``src/``, ``lib/``, ``app/``,
   ``pkg/``, ``cmd/`` with a known source extension.
4. **Other source** — any remaining file with a known source extension.

Files outside these tiers are excluded entirely.

Caps:
    - At most ``MAX_HEURISTIC_FILES`` files surface to the prompt.
    - At most ``MAX_HEURISTIC_TOKENS`` total tokens — the caller enforces.
"""

from __future__ import annotations

from pathlib import Path

# Public caps — callers in the composition root layer enforce them
# against the ranked output (file-count cap on slicing, token cap as
# a streaming sum during the read loop).
MAX_HEURISTIC_FILES: int = 20
MAX_HEURISTIC_TOKENS: int = 100_000


_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".ts",
        ".js",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
    }
)
_ENTRY_STEMS: frozenset[str] = frozenset(
    {
        "main",
        "app",
        "index",
        "server",
        "cli",
        "__main__",
    }
)
_CONFIG_NAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
    }
)
_SOURCE_PREFIXES: tuple[str, ...] = ("src/", "lib/", "app/", "pkg/", "cmd/")


def prioritize_source_files(file_tree: list[str]) -> list[str]:
    """Rank a file tree by signal density for specialist agent prompts.

    Pure function — given the same ``file_tree`` always returns the same
    ordering and never mutates the input list.

    Args:
        file_tree: Repository-relative paths from ``GitPort.get_file_tree``.

    Returns:
        A list of paths in priority order. Files outside every tier are
        excluded entirely. The caller decides how many to actually read
        (typically ``MAX_HEURISTIC_FILES``).
    """
    tiers: tuple[list[str], list[str], list[str], list[str]] = ([], [], [], [])
    for path in file_tree:
        p = Path(path)
        if p.stem in _ENTRY_STEMS and p.suffix in _SOURCE_EXTENSIONS:
            tiers[0].append(path)
        elif p.name in _CONFIG_NAMES:
            tiers[1].append(path)
        elif any(path.startswith(d) for d in _SOURCE_PREFIXES) and p.suffix in _SOURCE_EXTENSIONS:
            tiers[2].append(path)
        elif p.suffix in _SOURCE_EXTENSIONS:
            tiers[3].append(path)
    return [f for tier in tiers for f in tier]


__all__ = [
    "MAX_HEURISTIC_FILES",
    "MAX_HEURISTIC_TOKENS",
    "prioritize_source_files",
]
