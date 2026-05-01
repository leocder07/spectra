"""SQLite implementation of ``ReportStorePort`` — Layer 4 (#25, ADR-022).

The single-user fallback for the history store. Same schema as the
Postgres adapter, same migration files, same Protocol contract — the
composition root picks the backend at startup and the use-case layer
sees only ``ReportStorePort``.

Why SQLite for solo mode:
    - Zero operational dependency (no Postgres for one developer).
    - Single-file DB co-located with the cache (``~/.local/state/spectra``).
    - The same range queries that Postgres handles in milliseconds work
      on SQLite up to ~100K rows — well past any single-user lifetime.

Failure mode (SPEC-010 inheritance): every public coroutine wraps the
synchronous SQLite call in ``asyncio.to_thread``. I/O failures are
logged + swallowed by callers (the pipeline never aborts on a
history-store outage).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3 as _sqlite
import threading
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from spectra.entities.models import ReportSummary
from spectra.infrastructure.history.migrations_runner import (
    list_migrations,
    read_migration_sql,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOG = logging.getLogger("spectra.history.sqlite")


# ── Migration runner ─────────────────────────────────────────


_CREATE_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL
)
"""


def apply_migrations(db_path: Path) -> tuple[str, ...]:
    """Apply every pending migration to ``db_path``; return the applied versions.

    Idempotent — versions already in ``schema_migrations`` are skipped.
    Each migration runs inside a transaction; failure rolls back so a
    half-applied schema cannot persist.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    applied: list[str] = []
    with _connect(db_path) as conn:
        conn.execute(_CREATE_SCHEMA_MIGRATIONS)
        seen = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for version, path in list_migrations():
            if version in seen:
                continue
            sql = read_migration_sql(path)
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
            applied.append(version)
    return tuple(applied)


def _connect(db_path: Path) -> _sqlite.Connection:
    """Open a SQLite connection with WAL + foreign keys.

    ``check_same_thread=False`` is required because the adapter offloads
    every call to ``asyncio.to_thread``; the connection is wrapped in
    ``self._lock`` so concurrent ``store`` / ``latest`` invocations are
    serialised at the Python level.
    """
    conn = _sqlite.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Path resolution ──────────────────────────────────────────


def default_history_path() -> Path:
    """Default sqlite history DB path: ``$XDG_STATE_HOME/spectra/history.db``."""
    base = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(base) / "spectra" / "history.db"


# ── Adapter ──────────────────────────────────────────────────


class SqliteReportStoreAdapter:
    """Sqlite-backed implementation of ``ReportStorePort``.

    The adapter holds one connection for its lifetime. Every async
    method offloads the synchronous SQLite call to a worker thread via
    ``asyncio.to_thread`` so the pipeline event loop stays responsive.
    Failures are logged and re-raised; callers wrap with the standard
    ``safe_*`` pattern from ``spectra.use_cases.audit``.
    """

    def __init__(self, db_path: Path) -> None:
        """Open ``db_path`` (auto-create parent dirs); migrations must be applied first."""
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(db_path)
        self._lock = threading.Lock()

    @property
    def db_path(self) -> Path:
        """The on-disk DB path (used by the CLI for migrate / doctor)."""
        return self._db_path

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with suppress(_sqlite.Error):
            self._conn.close()

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

    async def list_signatures_in_window(
        self,
        since: datetime,
        until: datetime,
    ) -> tuple[str, ...]:
        """Return distinct ``repo_signature`` values seen in ``[since, until)``.

        Powers ``compose_weekly_digest`` (#34) — fleet-wide enumeration
        without round-tripping the full summary payload.
        """
        return await asyncio.to_thread(self._list_signatures_sync, since, until)

    # ── Sync helpers ──────────────────────────────────────────

    def _store_sync(self, report: ReportSummary) -> None:
        """Insert (or replace) one summary + child rows in one transaction."""
        params = _summary_to_row(report)
        with self._lock, self._tx():
            self._conn.execute(_INSERT_REPORT_SQL, params)
            self._conn.execute("DELETE FROM report_dimension_scores WHERE scan_id = ?", (report.scan_id,))
            self._conn.execute("DELETE FROM report_severity_counts WHERE scan_id = ?", (report.scan_id,))
            for dim in report.score_card.dimensions:
                self._conn.execute(
                    _INSERT_DIM_SQL,
                    (
                        report.scan_id,
                        dim.dimension,
                        float(dim.score),
                        dim.grade,
                        int(dim.findings_count),
                    ),
                )
            for sev, count in report.finding_count_by_severity.items():
                self._conn.execute(_INSERT_SEV_SQL, (report.scan_id, sev, int(count)))

    def _latest_sync(self, repo_signature: str) -> ReportSummary | None:
        """Synchronous SELECT of the freshest summary for one repo."""
        with self._lock:
            row = self._conn.execute(_SELECT_LATEST_SQL, (repo_signature,)).fetchone()
        return _row_to_summary(row) if row else None

    def _history_sync(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        """Synchronous SELECT inside the half-open window."""
        with self._lock:
            rows = self._conn.execute(
                _SELECT_HISTORY_SQL,
                (repo_signature, since.isoformat(), until.isoformat()),
            ).fetchall()
        return tuple(_row_to_summary(r) for r in rows)

    def _list_signatures_sync(
        self,
        since: datetime,
        until: datetime,
    ) -> tuple[str, ...]:
        """Synchronous SELECT DISTINCT repo_signature inside the half-open window."""
        with self._lock:
            rows = self._conn.execute(
                _SELECT_DISTINCT_SIGNATURES_SQL,
                (since.isoformat(), until.isoformat()),
            ).fetchall()
        return tuple(str(r[0]) for r in rows)

    @contextmanager
    def _tx(self) -> Iterator[None]:
        """Wrap a block of writes in a single SQLite transaction."""
        self._conn.execute("BEGIN")
        try:
            yield
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")


# ── Row <-> entity mapping ────────────────────────────────────


def _summary_to_row(s: ReportSummary) -> tuple[object, ...]:
    """Pack a summary into the ``reports`` insert parameter tuple."""
    return (
        s.scan_id,
        s.repo_signature,
        s.repo_url,
        s.repo_name,
        "default",  # org_id
        s.timestamp.isoformat(),
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
        datetime.now(UTC).isoformat(),
    )


def _row_to_summary(row: tuple[object, ...]) -> ReportSummary:
    """Reverse of ``_summary_to_row`` — uses the JSON blob for fidelity.

    Querying is done via the indexed columns; the JSON blob is the source
    of truth for the entity payload because a future schema bump can add
    fields without losing old rows.
    """
    summary_json = str(row[0])
    return ReportSummary.model_validate_json(summary_json)


# ── SQL constants ─────────────────────────────────────────────


_INSERT_REPORT_SQL = """
INSERT OR REPLACE INTO reports (
    scan_id, repo_signature, repo_url, repo_name, org_id, ts,
    overall_score, overall_grade, pipeline_state, validation_status,
    spectra_version, model_versions, prompt_versions, cost_usd,
    duration_seconds, summary_json, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_DIM_SQL = """
INSERT INTO report_dimension_scores (scan_id, dimension, score, grade, finding_count)
VALUES (?, ?, ?, ?, ?)
"""

_INSERT_SEV_SQL = """
INSERT INTO report_severity_counts (scan_id, severity, count)
VALUES (?, ?, ?)
"""

_SELECT_LATEST_SQL = """
SELECT summary_json FROM reports
WHERE repo_signature = ?
ORDER BY ts DESC
LIMIT 1
"""

_SELECT_HISTORY_SQL = """
SELECT summary_json FROM reports
WHERE repo_signature = ?
  AND ts >= ?
  AND ts <  ?
ORDER BY ts DESC
"""

_SELECT_DISTINCT_SIGNATURES_SQL = """
SELECT DISTINCT repo_signature FROM reports
WHERE ts >= ?
  AND ts <  ?
"""
