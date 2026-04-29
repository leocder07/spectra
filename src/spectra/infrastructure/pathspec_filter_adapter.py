"""Pathspec-based workspace filter — implements ``WorkspaceFilterPort``.

Honors ``.gitignore`` (root + every nested ``.gitignore``) and ``.spectraignore``
using the ``pathspec`` library, which implements true Git wildmatch semantics
(including negation, leading-slash anchors, and trailing-slash directory rules).

Layering:
    Two compiled ``PathSpec`` instances are evaluated per file path:

    1. ``.gitignore`` chain — root-level patterns plus, for each nested
       ``.gitignore``, patterns translated by prepending the directory prefix.
       Honored unless ``honor_gitignore=False`` is passed at construction.

    2. ``.spectraignore`` — root-only, always honored. Same ``gitwildmatch``
       syntax. Documented for users who want Spectra-specific exclusions
       without polluting their ``.gitignore``.

A path is kept iff it matches *neither* compiled spec (or only the gitignore
spec when honor_gitignore is False).

The adapter is a pure function over (workspace_dir, file_paths) — it never
mutates state and never writes to disk. Per the dependency rule it only
imports the third-party ``pathspec`` library and from ``__future__``.
"""

from __future__ import annotations

from pathlib import Path

import pathspec


def _read_patterns(path: Path) -> list[str]:
    """Return non-empty, non-comment lines from ``path``; missing-file safe.

    Respects ``.gitignore`` semantics: blank lines and ``#``-prefixed
    comments are dropped so they never become accidental match patterns.
    """
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        out.append(line)
    return out


def _prefixed(patterns: list[str], dir_prefix: str) -> list[str]:
    """Translate nested ``.gitignore`` patterns into root-relative ones.

    Git scopes a nested ``.gitignore`` to its directory; pathspec's compiler
    treats every spec as root-relative. We bridge the gap by prepending the
    nested directory prefix to each pattern, preserving anchored (``/``) and
    negation (``!``) semantics.

    Args:
        patterns: Raw ignore patterns from a nested ``.gitignore``.
        dir_prefix: Directory prefix relative to the workspace root,
            e.g. ``packages/ui``.

    Returns:
        Patterns rewritten so the root spec evaluates them correctly.
    """
    if not dir_prefix:
        return patterns
    prefix = dir_prefix.rstrip("/") + "/"
    return [_prefix_one(pat, prefix) for pat in patterns]


def _prefix_one(pattern: str, prefix: str) -> str:
    """Add ``prefix`` to a single pattern, preserving negation and anchoring."""
    negated = pattern.startswith("!")
    body = pattern[1:] if negated else pattern
    body = body.removeprefix("/")
    out = f"{prefix}{body}"
    return f"!{out}" if negated else out


def _collect_gitignore_patterns(repo_root: Path) -> list[str]:
    """Walk every ``.gitignore`` in the tree; return prefix-translated patterns.

    Hidden ``.git`` directories are pruned in-place during the walk so we
    never recurse into git internals.
    """
    out: list[str] = []
    for gitignore in sorted(repo_root.rglob(".gitignore")):
        if any(part == ".git" for part in gitignore.relative_to(repo_root).parts):
            continue
        rel_dir = str(gitignore.parent.relative_to(repo_root)).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        out.extend(_prefixed(_read_patterns(gitignore), rel_dir))
    return out


class PathspecFilterAdapter:
    """Implements ``WorkspaceFilterPort`` using ``pathspec.GitIgnoreSpec``.

    Composition order matches ``man gitignore``: a later pattern can
    re-include a previously-excluded path via ``!``. Both ignore files
    use ``gitwildmatch``, so behavior is intuitive for any developer.

    Args:
        honor_gitignore: Toggle for the ``--no-gitignore`` CLI escape hatch.
            Defaults to ``True`` (the safe default — every existing
            ``.gitignore`` entry is excluded). When ``False``, ``.gitignore``
            files are skipped but ``.spectraignore`` is still applied.
    """

    def __init__(self, *, honor_gitignore: bool = True) -> None:
        self._honor_gitignore = honor_gitignore

    def filter_files(self, repo_dir: str, file_paths: list[str]) -> list[str]:
        """Return ``file_paths`` minus anything matched by an active ignore spec."""
        if not file_paths:
            return []
        spec = self._compile_spec(Path(repo_dir))
        if spec is None:
            return list(file_paths)
        return [p for p in file_paths if not spec.match_file(p)]

    def _compile_spec(self, repo_root: Path) -> pathspec.PathSpec | None:
        """Build the combined PathSpec, or ``None`` if no patterns are active."""
        patterns = self._gather_patterns(repo_root)
        if not patterns:
            return None
        return pathspec.GitIgnoreSpec.from_lines(patterns)

    def _gather_patterns(self, repo_root: Path) -> list[str]:
        """Collect every active pattern in evaluation order."""
        patterns: list[str] = []
        if self._honor_gitignore:
            patterns.extend(_collect_gitignore_patterns(repo_root))
        patterns.extend(_read_patterns(repo_root / ".spectraignore"))
        return patterns
