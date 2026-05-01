"""Spectra history-store adapters (#25, ADR-022).

Two backends, one Protocol contract:

- ``SqliteReportStoreAdapter`` — single-user fallback, zero infra.
- ``PostgresReportStoreAdapter`` — portfolio mode, real concurrency.

Both apply the same SQL migrations from ``migrations/`` so the schema
is identical across backends. The composition root picks one based on
``--history-backend`` (default: sqlite) or ``SPECTRA_HISTORY_BACKEND``.
"""

from __future__ import annotations

from spectra.infrastructure.history.migrations_runner import (
    MIGRATIONS_DIR,
    list_migrations,
    read_migration_sql,
)
from spectra.infrastructure.history.postgres_report_store import (
    PostgresReportStoreAdapter,
    apply_postgres_migrations,
    build_pool,
)
from spectra.infrastructure.history.sqlite_report_store import (
    SqliteReportStoreAdapter,
    default_history_path,
)
from spectra.infrastructure.history.sqlite_report_store import (
    apply_migrations as apply_sqlite_migrations,
)

__all__ = [
    "MIGRATIONS_DIR",
    "PostgresReportStoreAdapter",
    "SqliteReportStoreAdapter",
    "apply_postgres_migrations",
    "apply_sqlite_migrations",
    "build_pool",
    "default_history_path",
    "list_migrations",
    "read_migration_sql",
]
