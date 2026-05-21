"""Memory-directory + per-URL DB path resolution (v0.9.1, ADR-025 wiring).

Composition root uses these helpers to bind ``LocalFileMemoryAdapter`` to a
stable on-disk location. The path resolution lives in Layer 4 (infrastructure
concern); the use-case layer never needs to compute paths.

Precedence (highest first):
  1. ``--memory-dir`` CLI override
  2. ``SPECTRA_MEMORY_DIR`` environment variable
  3. Default: ``$XDG_DATA_HOME/spectra/memory`` (or ``~/.local/share/spectra/memory``)

Per-URL keying via sha256 of the canonical repo URL — two equivalent URLs
(scheme/host case, trailing ``.git``, trailing ``/``) land in the same DB so
the audit-trail-shaped historical record is consistent across runs.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse

__all__ = [
    "canonicalize_repo_url",
    "default_memory_dir",
    "memory_db_for",
    "resolve_memory_dir",
]

_MEMORY_SUBPATH = ("spectra", "memory")
_ENV_VAR = "SPECTRA_MEMORY_DIR"
_XDG_VAR = "XDG_DATA_HOME"
_XDG_FALLBACK = (".local", "share")


def default_memory_dir() -> Path:
    """Return the default memory directory per the XDG Base Directory spec.

    ``$XDG_DATA_HOME/spectra/memory`` when ``XDG_DATA_HOME`` is set and
    non-empty; otherwise ``~/.local/share/spectra/memory``.
    """
    xdg = os.environ.get(_XDG_VAR)
    if xdg:
        return Path(xdg).joinpath(*_MEMORY_SUBPATH)
    return Path.home().joinpath(*_XDG_FALLBACK, *_MEMORY_SUBPATH)


def resolve_memory_dir(*, cli_override: str | None) -> Path:
    """Resolve the memory directory using the documented precedence.

    Args:
        cli_override: Value passed via ``--memory-dir`` on the CLI.
            When ``None``, falls through to ``SPECTRA_MEMORY_DIR``, then
            to ``default_memory_dir()``.

    Returns:
        The resolved directory as a ``Path``. The directory is NOT created
        here — adapter creation is responsible for lazy ``mkdir(parents=True)``
        with the ADR-012 permission discipline (``0o700``).
    """
    if cli_override:
        return Path(cli_override)
    env = os.environ.get(_ENV_VAR)
    if env:
        return Path(env)
    return default_memory_dir()


def canonicalize_repo_url(repo_url: str) -> str:
    """Return a deterministic canonical form of ``repo_url``.

    Rules:
      - Scheme and host lower-cased
      - Trailing ``.git`` stripped
      - Trailing ``/`` stripped
      - ``file://`` URLs and bare local paths resolved to absolute paths

    Path components are NOT case-folded — GitHub case-folds owner names but
    other VCS hosts (ToolForge, internal Gitea) do not, so we preserve case.
    """
    parsed = urlparse(repo_url)

    if parsed.scheme in ("", "file") or not parsed.netloc:
        local_path = parsed.path if parsed.scheme == "file" else repo_url
        return str(Path(local_path).resolve())

    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return f"{scheme}://{host}{path}"


def memory_db_for(repo_url: str, *, memory_dir: Path | None = None) -> Path:
    """Return the SQLite DB path for ``repo_url`` under ``memory_dir``.

    Args:
        repo_url: The repository URL or local path (canonicalized internally).
        memory_dir: When provided, overrides the resolved memory directory.
            Useful for tests and for the composition-root code path that has
            already resolved the directory once.

    Returns:
        ``<memory_dir>/<sha256-of-canonical-url>.db``.
    """
    target_dir = memory_dir if memory_dir is not None else resolve_memory_dir(cli_override=None)
    canonical = canonicalize_repo_url(repo_url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return target_dir / f"{digest}.db"
