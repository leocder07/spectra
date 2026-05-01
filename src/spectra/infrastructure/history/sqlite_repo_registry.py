"""SQLite implementation of ``RepoRegistryPort`` — Layer 4 (#26).

The portfolio scheduler iterates over rows persisted here. The adapter
co-exists with the analysis cache in the same on-disk file (one
``cache.db`` per ``$XDG_CACHE_HOME``); CREATE TABLE IF NOT EXISTS makes
the migration idempotent so opening the cache file from a second
process — e.g. ``spectra portfolio list`` while ``spectra analyze`` is
running — never trips on a half-applied schema.

Failure mode: serious I/O failures bubble up as ``AgentError`` carrying
``SPEC-010`` so the CLI surface degrades cleanly. The CLI catches the
error and prints a brand-voice ✗ instead of leaking a stack trace.
"""

from __future__ import annotations

import json
import sqlite3 as _sqlite
import threading
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.models import RepoRegistryEntry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ── DDL ──────────────────────────────────────────────────────


CREATE_PORTFOLIO_REPOS_SQL = """
CREATE TABLE IF NOT EXISTS portfolio_repos (
    repo_url       TEXT     PRIMARY KEY,
    added_at       TIMESTAMP NOT NULL,
    last_scan_at   TIMESTAMP,
    tags_json      TEXT     NOT NULL DEFAULT '[]'
)
"""
"""DDL applied by both the standalone adapter and ``cache_adapter.py``.

Exposed as a module-level constant so the cache adapter can import the
exact same statement — single source of truth, no schema drift across
the two entry points.
"""


_INSERT_OR_REPLACE_SQL = """
INSERT OR REPLACE INTO portfolio_repos (repo_url, added_at, last_scan_at, tags_json)
VALUES (?, ?, ?, ?)
"""

_SELECT_ALL_SQL = """
SELECT repo_url, added_at, last_scan_at, tags_json
FROM portfolio_repos
ORDER BY added_at ASC, repo_url ASC
"""

_SELECT_ONE_SQL = """
SELECT repo_url, added_at, last_scan_at, tags_json
FROM portfolio_repos
WHERE repo_url = ?
"""

_DELETE_SQL = "DELETE FROM portfolio_repos WHERE repo_url = ?"

_UPDATE_SCANNED_SQL = "UPDATE portfolio_repos SET last_scan_at = ? WHERE repo_url = ?"


# ── SPEC-010 envelope helper ─────────────────────────────────


def _spec_010(cause: BaseException) -> AgentError:
    """Wrap any sqlite/OS failure in the cache SPEC code so the CLI degrades cleanly."""
    err = AgentError(ERRORS["SPEC-010"])
    err.__cause__ = cause
    return err


@contextmanager
def _guard_io() -> Iterator[None]:
    """Convert ``sqlite3.Error`` and ``OSError`` into ``AgentError`` SPEC-010."""
    try:
        yield
    except (_sqlite.Error, OSError) as exc:
        raise _spec_010(exc) from exc


# ── Adapter ──────────────────────────────────────────────────


class SqliteRepoRegistry:
    """Sqlite-backed implementation of ``RepoRegistryPort``.

    The adapter holds one connection for its lifetime. Writes serialise
    on a Python ``threading.Lock`` — SQLite already serialises writers
    at the file level, but the lock keeps the in-process ``check_same_thread``
    contract tidy and removes a class of test flakes.
    """

    def __init__(self, db_path: Path) -> None:
        """Open ``db_path`` (auto-create parent dirs) and apply the migration.

        Failure mode: any SQLite or OSError on open is wrapped in
        SPEC-010 so the CLI prints a friendly error rather than leaking
        a stack trace.
        """
        self._db_path = db_path
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _spec_010(exc) from exc
        with _guard_io():
            self._conn = _sqlite.connect(
                str(db_path),
                isolation_level=None,
                check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(CREATE_PORTFOLIO_REPOS_SQL)
        self._lock = threading.Lock()

    @property
    def db_path(self) -> Path:
        """The on-disk DB path (used by the CLI for diagnostics)."""
        return self._db_path

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with suppress(_sqlite.Error):
            self._conn.close()

    # ── RepoRegistryPort methods ─────────────────────────────

    def add(
        self,
        repo_url: str,
        *,
        tags: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> RepoRegistryEntry:
        """Insert ``repo_url`` (or merge tags onto an existing row)."""
        timestamp = now or datetime.now(UTC)
        with self._lock, _guard_io():
            existing = self._fetch_one(repo_url)
            if existing is None:
                merged = RepoRegistryEntry(
                    repo_url=repo_url,
                    added_at=timestamp,
                    tags=_dedupe_tags((), tags),
                )
            else:
                merged = existing.model_copy(
                    update={"tags": _dedupe_tags(existing.tags, tags)},
                )
            self._conn.execute(
                _INSERT_OR_REPLACE_SQL,
                (
                    merged.repo_url,
                    merged.added_at.isoformat(),
                    merged.last_scan_at.isoformat() if merged.last_scan_at else None,
                    json.dumps(list(merged.tags)),
                ),
            )
            return merged

    def remove(self, repo_url: str) -> bool:
        """Delete the row keyed by ``repo_url``; return True when something was removed."""
        with self._lock, _guard_io():
            cursor = self._conn.execute(_DELETE_SQL, (repo_url,))
            return cursor.rowcount > 0

    def list(self, *, tag: str | None = None) -> tuple[RepoRegistryEntry, ...]:
        """Return every registered entry; optionally filter by ``tag``."""
        with self._lock, _guard_io():
            rows = self._conn.execute(_SELECT_ALL_SQL).fetchall()
        entries = tuple(_row_to_entry(r) for r in rows)
        if tag is None:
            return entries
        return tuple(e for e in entries if e.has_tag(tag))

    def mark_scanned(
        self,
        repo_url: str,
        *,
        scanned_at: datetime,
    ) -> RepoRegistryEntry | None:
        """Stamp ``last_scan_at = scanned_at`` on ``repo_url``."""
        with self._lock, _guard_io():
            self._conn.execute(_UPDATE_SCANNED_SQL, (scanned_at.isoformat(), repo_url))
            return self._fetch_one(repo_url)

    # ── helpers ──────────────────────────────────────────────

    def _fetch_one(self, repo_url: str) -> RepoRegistryEntry | None:
        """Synchronous SELECT of a single row by URL."""
        row = self._conn.execute(_SELECT_ONE_SQL, (repo_url,)).fetchone()
        return _row_to_entry(row) if row else None


# ── Row <-> entity mapping ────────────────────────────────────


def _row_to_entry(row: tuple[object, ...]) -> RepoRegistryEntry:
    """Inverse of the INSERT parameter shape — no MAC/HMAC, no JSON blob inside JSON."""
    repo_url = str(row[0])
    added_at = _parse_ts(str(row[1]))
    last_scan_at = _parse_ts(str(row[2])) if row[2] is not None else None
    tags = tuple(json.loads(str(row[3]))) if row[3] is not None else ()
    return RepoRegistryEntry(
        repo_url=repo_url,
        added_at=added_at,
        last_scan_at=last_scan_at,
        tags=tags,
    )


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, defaulting to UTC when no offset is present."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _dedupe_tags(existing: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    """Merge two tag tuples preserving order; first-occurrence wins."""
    return tuple(dict.fromkeys((*existing, *extra)))
