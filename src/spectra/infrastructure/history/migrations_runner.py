"""Shared migration loader for both history-store backends (#25, ADR-022 §4).

Migrations are raw SQL files in ``migrations/`` named ``NNN_<slug>.sql``.
They are applied in lexicographic order; each one runs in a transaction;
applied versions are tracked in ``schema_migrations`` so reruns skip them.

We deliberately reject Alembic — see ADR-022 §4 for the reasoning.
"""

from __future__ import annotations

from pathlib import Path

MIGRATIONS_DIR: Path = Path(__file__).parent / "migrations"
"""Absolute path to the SQL migration files. Shared by both backends."""

_MIGRATIONS_GLOB = "*.sql"


def list_migrations() -> tuple[tuple[str, Path], ...]:
    """Return ``((version, path), ...)`` sorted by version.

    The version string is the filename without the ``.sql`` extension —
    e.g. ``001_initial_schema``. Lexicographic sort matches semantic
    order because every file starts with a zero-padded numeric prefix.
    """
    files = sorted(MIGRATIONS_DIR.glob(_MIGRATIONS_GLOB))
    return tuple((path.stem, path) for path in files)


def read_migration_sql(path: Path) -> str:
    """Read a migration file and return its SQL contents."""
    return path.read_text(encoding="utf-8")
