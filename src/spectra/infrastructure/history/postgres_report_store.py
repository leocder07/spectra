"""Postgres implementation of ``ReportStorePort`` — Layer 4 (#25, ADR-022).

Portfolio-mode default. Same Protocol contract as the SQLite fallback;
same SQL migration files; same ``ReportSummary`` JSON payload as the
source of truth.

Why Postgres for portfolio mode (ADR-022 §2):
    - Concurrent writers — every CI runner inserts on scan completion.
    - Index-only range scans for ``(repo_signature, ts DESC)``.
    - Window functions for the drift detector (``LAG()``).
    - Parallel queries for the leaderboard endpoint at fleet scale.

Driver and pooling:
    - ``psycopg[pool]>=3.1,<4.0`` — installed when the user opts into
      portfolio mode. The adapter never imports ``psycopg`` at module
      load: imports happen inside ``build_pool`` so the rest of the
      Spectra wheel stays usable on installs without psycopg.
    - ``psycopg_pool.ConnectionPool`` with ``min_size=2``, ``max_size=10``
      by default; tunable via the constructor.

Failure mode (SPEC-010 inheritance): the use case wraps every history
call in the standard ``safe_*`` pattern; a Postgres outage degrades the
pipeline to "no history" but never aborts the run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from spectra.entities.models import ReportSummary
from spectra.infrastructure.history.migrations_runner import (
    list_migrations,
    read_migration_sql,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_LOG = logging.getLogger("spectra.history.postgres")


# ── Pool protocol — keeps the adapter testable without psycopg ──


class _PoolLike(Protocol):
    """Structural shape we depend on from ``psycopg_pool.ConnectionPool``.

    Stripped to the methods the adapter actually calls so the unit tests
    can substitute a fake without importing psycopg.
    """

    def connection(self) -> Any:  # noqa: ANN401 — backend-specific connection type
        ...

    def close(self) -> None: ...


# ── Public entry points ──────────────────────────────────────


def build_pool(
    url: str,
    *,
    min_size: int = 2,
    max_size: int = 10,
    pool_factory: Callable[..., _PoolLike] | None = None,
) -> _PoolLike:
    """Build a ``psycopg_pool.ConnectionPool`` against ``url``.

    Imports ``psycopg_pool`` lazily so the rest of the Spectra wheel
    keeps importing on installs without psycopg.

    Args:
        url: Postgres connection string (``postgresql://user:pass@host/db``).
        min_size: Minimum idle pool size (default 2).
        max_size: Hard cap on concurrent connections (default 10).
        pool_factory: Override for tests — receives ``(url, min_size=,
            max_size=)`` and returns a pool. Default uses
            ``psycopg_pool.ConnectionPool``.

    Returns:
        An open connection pool ready to be passed to
        ``PostgresReportStoreAdapter``.
    """
    if pool_factory is not None:
        return pool_factory(url, min_size=min_size, max_size=max_size)
    try:
        from psycopg_pool import ConnectionPool  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — env-dependent
        msg = (
            "psycopg[pool] is required for the Postgres history backend. "
            "Install via: pip install 'psycopg[pool]>=3.1,<4.0'"
        )
        raise RuntimeError(msg) from exc
    return ConnectionPool(conninfo=url, min_size=min_size, max_size=max_size, open=True)


def apply_postgres_migrations(*, pool: _PoolLike) -> tuple[str, ...]:
    """Apply every pending migration to the Postgres DB behind ``pool``.

    Idempotent — versions already in ``schema_migrations`` are skipped.
    Each migration runs inside its own transaction; failure rolls back
    so a half-applied schema cannot persist.
    """
    applied: list[str] = []
    with pool.connection() as conn:
        cur = conn.cursor()
        with cur:
            cur.execute(_CREATE_SCHEMA_MIGRATIONS_PG)
            cur.execute("SELECT version FROM schema_migrations")
            seen = {row[0] for row in cur.fetchall()}
        for version, path in list_migrations():
            if version in seen:
                continue
            sql = read_migration_sql(path)
            cur = conn.cursor()
            with cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
                    (version, datetime.now(UTC)),
                )
            applied.append(version)
    return tuple(applied)


# ── Adapter ──────────────────────────────────────────────────


class PostgresReportStoreAdapter:
    """Postgres-backed implementation of ``ReportStorePort``.

    The adapter holds a reference to a pre-built ``ConnectionPool`` so
    the composition root owns the connection lifecycle. Async port methods
    offload the (sync) psycopg calls via ``asyncio.to_thread`` so the
    event loop stays responsive while the worker waits on the network.
    """

    def __init__(self, *, pool: _PoolLike) -> None:
        """Bind a pre-built psycopg connection pool."""
        self._pool = pool

    @property
    def pool(self) -> _PoolLike:
        """Return the underlying pool (used by ``spectra history doctor``)."""
        return self._pool

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._pool.close()

    # ── ReportStorePort methods ───────────────────────────────

    async def store(self, report: ReportSummary) -> None:
        """Persist one summary; latest write wins on duplicate ``scan_id``."""
        await asyncio.to_thread(self._store_sync, report)

    async def latest(self, repo_signature: str) -> ReportSummary | None:
        """Return the most recent summary for ``repo_signature`` or ``None``."""
        return await asyncio.to_thread(self._latest_sync, repo_signature)

    async def history(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        """Return summaries within ``[since, until)`` ordered most-recent-first."""
        return await asyncio.to_thread(self._history_sync, repo_signature, since, until)

    # ── Sync helpers (run inside ``asyncio.to_thread``) ───────

    def _store_sync(self, report: ReportSummary) -> None:
        """Insert (or replace) one summary + child rows in one transaction."""
        params = _summary_to_row(report)
        with self._pool.connection() as conn:
            cur = conn.cursor()
            with cur:
                cur.execute(_INSERT_REPORT_PG_SQL, params)
                cur.execute(
                    "DELETE FROM report_dimension_scores WHERE scan_id = %s",
                    (report.scan_id,),
                )
                cur.execute(
                    "DELETE FROM report_severity_counts WHERE scan_id = %s",
                    (report.scan_id,),
                )
                for dim in report.score_card.dimensions:
                    cur.execute(
                        _INSERT_DIM_PG_SQL,
                        (
                            report.scan_id,
                            dim.dimension,
                            float(dim.score),
                            dim.grade,
                            int(dim.findings_count),
                        ),
                    )
                for sev, count in report.finding_count_by_severity.items():
                    cur.execute(_INSERT_SEV_PG_SQL, (report.scan_id, sev, int(count)))

    def _latest_sync(self, repo_signature: str) -> ReportSummary | None:
        """Synchronous SELECT of the freshest summary for one repo."""
        with self._pool.connection() as conn:
            cur = conn.cursor()
            with cur:
                cur.execute(_SELECT_LATEST_PG_SQL, (repo_signature,))
                row = cur.fetchone()
        return _row_to_summary(row) if row else None

    def _history_sync(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        """Synchronous SELECT inside the half-open window."""
        with self._pool.connection() as conn:
            cur = conn.cursor()
            with cur:
                cur.execute(_SELECT_HISTORY_PG_SQL, (repo_signature, since, until))
                rows = cur.fetchall()
        return tuple(_row_to_summary(r) for r in rows)


# ── Row <-> entity mapping (shared shape with sqlite adapter) ──


def _summary_to_row(s: ReportSummary) -> tuple[object, ...]:
    """Pack a summary into the ``reports`` insert parameter tuple."""
    return (
        s.scan_id,
        s.repo_signature,
        s.repo_url,
        s.repo_name,
        "default",  # org_id
        s.timestamp,
        float(s.overall_score),
        s.overall_grade,
        "degraded" if s.is_degraded else "complete",
        s.validation_status,
        s.spectra_version,
        s.model_versions,
        s.prompt_versions,
        float(s.cost_usd),
        float(s.duration_seconds),
        s.model_dump_json(),
        datetime.now(UTC),
    )


def _row_to_summary(row: tuple[object, ...]) -> ReportSummary:
    """Reverse of ``_summary_to_row`` — uses the JSON blob for fidelity."""
    summary_json = str(row[0])
    return ReportSummary.model_validate_json(summary_json)


# ── SQL constants — Postgres ``%s`` placeholders ──────────────


_CREATE_SCHEMA_MIGRATIONS_PG = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL
)
"""

_INSERT_REPORT_PG_SQL = """
INSERT INTO reports (
    scan_id, repo_signature, repo_url, repo_name, org_id, ts,
    overall_score, overall_grade, pipeline_state, validation_status,
    spectra_version, model_versions, prompt_versions, cost_usd,
    duration_seconds, summary_json, created_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (scan_id) DO UPDATE SET
    repo_signature = EXCLUDED.repo_signature,
    overall_score  = EXCLUDED.overall_score,
    overall_grade  = EXCLUDED.overall_grade,
    summary_json   = EXCLUDED.summary_json,
    ts             = EXCLUDED.ts
"""

_INSERT_DIM_PG_SQL = """
INSERT INTO report_dimension_scores (scan_id, dimension, score, grade, finding_count)
VALUES (%s, %s, %s, %s, %s)
"""

_INSERT_SEV_PG_SQL = """
INSERT INTO report_severity_counts (scan_id, severity, count)
VALUES (%s, %s, %s)
"""

_SELECT_LATEST_PG_SQL = """
SELECT summary_json FROM reports
WHERE repo_signature = %s
ORDER BY ts DESC
LIMIT 1
"""

_SELECT_HISTORY_PG_SQL = """
SELECT summary_json FROM reports
WHERE repo_signature = %s
  AND ts >= %s
  AND ts <  %s
ORDER BY ts DESC
"""
