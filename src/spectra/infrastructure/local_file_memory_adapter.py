"""``LocalFileMemoryAdapter`` — local SQLite + FTS5 ``MemoryPort`` (Q4 #50, ADR-025).

Implements the per-repo memory log with append-only semantics, FTS5
search over event payloads, and the ADR-012 file-permission discipline
(parent dir 0o700, db file 0o600).

The use-case layer never imports ``sqlite3``; this adapter is the
single seam between Python's stdlib SQLite and the ``MemoryPort``
Protocol declared in Layer 2.

Failure mode (per ADR-025 §"Failure mode contract"):
- ``append_event`` failures degrade to a one-shot WARN and return
  cleanly — the analysis pipeline must not abort because the memory
  log is unwritable.
- ``query_events`` and ``search`` raise ``AgentError(SPEC-010)`` so
  the caller (e.g. ``spectra ask`` degraded mode, ``spectra brief``)
  can decide to surface or degrade. Loud-on-read prevents the silent
  empty-result failure that would mask a corrupt DB.

Idempotency: ``append_event`` is idempotent on ``event.id`` via
``INSERT OR IGNORE``. The post-Stage-6 hook can retry the write on
transient I/O without introducing duplicate rows.

FTS5 backing: events have a virtual table ``events_fts`` over
``payload_text`` (the JSON-serialised payload). We use FTS5's BM25
ranking by default; queries that look like FTS5 syntax pass through;
queries that don't are quoted as a single match.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING

from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.memory import MemoryEvent

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_LOG = logging.getLogger("spectra.memory")

_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        repo_url TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        actor TEXT NOT NULL,
        occurred_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_events_kind_occurred
        ON events(kind, occurred_at DESC);

    -- Standalone FTS5 table (not external-content): smaller code path,
    -- straightforward inserts. We pay ~2x storage for the duplicated
    -- payload text vs an external-content config; for an event log
    -- that grows ~100 events per repo per quarter this is negligible.
    CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
        id UNINDEXED,
        payload_text
    );
"""

_INSERT_EVENT_SQL = """
    INSERT OR IGNORE INTO events (id, kind, repo_url, payload_json, actor, occurred_at)
    VALUES (?, ?, ?, ?, ?, ?)
"""

_INSERT_FTS_SQL = """
    INSERT INTO events_fts (id, payload_text) VALUES (?, ?)
"""

_SELECT_FTS_SQL = """
    SELECT events.id, events.kind, events.repo_url, events.payload_json,
           events.actor, events.occurred_at
    FROM events_fts
    JOIN events ON events.id = events_fts.id
    WHERE events_fts MATCH ?
    ORDER BY events.occurred_at DESC
    LIMIT ?
"""


def _spec_010(cause: BaseException) -> AgentError:
    err = AgentError(ERRORS["SPEC-010"])
    err.__cause__ = cause
    return err


@contextmanager
def _guard_read() -> Iterator[None]:
    """Convert sqlite3 / OS read failures into ``AgentError(SPEC-010)``."""
    try:
        yield
    except (sqlite3.Error, OSError) as exc:
        raise _spec_010(exc) from exc


class LocalFileMemoryAdapter:
    """SQLite + FTS5 implementation of ``MemoryPort``.

    Constructor side effects (lazy until first use):
    - Parent directory created with ``0o700`` perms.
    - DB file created with ``0o600`` perms (POSIX best-effort).
    - Schema initialized via ``CREATE TABLE IF NOT EXISTS`` (idempotent).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._initialized = False

    # ── Public Port surface ─────────────────────────────────────

    async def append_event(self, event: MemoryEvent) -> None:
        """Append ``event``; idempotent on ``event.id``.

        Failures degrade to a one-shot WARN — the call returns cleanly
        so the analysis pipeline never aborts because the log is
        unwritable.
        """
        try:
            async with self._lock:
                await asyncio.to_thread(self._append_event_sync, event)
        except (sqlite3.Error, OSError) as exc:
            _LOG.warning(
                "SPEC-010: memory append failed (%s: %s); event %s dropped",
                type(exc).__name__,
                exc,
                event.id,
            )

    async def query_events(
        self,
        *,
        kind: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[MemoryEvent, ...]:
        async with self._lock:
            return await asyncio.to_thread(self._query_events_sync, kind, since, limit)

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> tuple[MemoryEvent, ...]:
        async with self._lock:
            return await asyncio.to_thread(self._search_sync, query, limit)

    # ── Sync helpers (run via asyncio.to_thread) ───────────────

    def _append_event_sync(self, event: MemoryEvent) -> None:
        self._ensure_initialized()
        payload_json = json.dumps(event.payload, default=str, sort_keys=True)
        with sqlite3.connect(str(self._db_path), isolation_level=None) as conn:
            cursor = conn.execute(
                _INSERT_EVENT_SQL,
                (
                    event.id,
                    event.kind,
                    event.repo_url,
                    payload_json,
                    event.actor,
                    event.occurred_at.isoformat(),
                ),
            )
            # Mirror into FTS5 only on first-write (rowcount == 1);
            # duplicates already-skipped by INSERT OR IGNORE upstream.
            if cursor.rowcount == 1:
                conn.execute(_INSERT_FTS_SQL, (event.id, payload_json))

    def _query_events_sync(
        self,
        kind: str | None,
        since: datetime | None,
        limit: int,
    ) -> tuple[MemoryEvent, ...]:
        with _guard_read():
            self._ensure_initialized()
            clauses: list[str] = []
            params: list[object] = []
            if kind is not None:
                clauses.append("kind = ?")
                params.append(kind)
            if since is not None:
                clauses.append("occurred_at > ?")
                params.append(since.isoformat())
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = (
                f"SELECT id, kind, repo_url, payload_json, actor, occurred_at "  # noqa: S608 — clauses are fixed strings
                f"FROM events {where} ORDER BY occurred_at DESC LIMIT ?"
            )
            params.append(limit)
            with sqlite3.connect(str(self._db_path)) as conn:
                rows = conn.execute(sql, params).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    def _search_sync(self, query: str, limit: int) -> tuple[MemoryEvent, ...]:
        with _guard_read():
            self._ensure_initialized()
            fts_query = self._sanitize_fts_query(query)
            with sqlite3.connect(str(self._db_path)) as conn:
                rows = conn.execute(_SELECT_FTS_SQL, (fts_query, limit)).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    # ── Initialization + housekeeping ──────────────────────────

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tighten_dir_perms()
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript(_SCHEMA_DDL)
        self._tighten_db_perms()
        self._initialized = True

    def _tighten_dir_perms(self) -> None:
        if os.name != "posix":
            return
        try:
            os.chmod(self._db_path.parent, 0o700)
        except OSError as exc:
            _LOG.debug("Could not chmod 0700 on memory dir: %s", exc)

    def _tighten_db_perms(self) -> None:
        if os.name != "posix":
            return
        for sibling in (
            self._db_path,
            self._db_path.with_suffix(self._db_path.suffix + "-wal"),
            self._db_path.with_suffix(self._db_path.suffix + "-shm"),
        ):
            try:
                if sibling.exists():
                    os.chmod(sibling, 0o600)
            except OSError as exc:
                _LOG.debug("Could not chmod 0600 on %s: %s", sibling, exc)

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Quote a free-text query as a single FTS5 phrase.

        FTS5 syntax characters (``"`` ``-`` ``*`` ``:`` ``(`` ``)``)
        in raw operator input would either error or change semantics.
        Wrapping the user's query in double quotes makes it a phrase
        match, which is the right default for "search payloads for
        this token."
        """
        cleaned = query.replace('"', '""')
        return f'"{cleaned}"'

    @staticmethod
    def _row_to_event(row: tuple[object, ...]) -> MemoryEvent:
        event_id, kind, repo_url, payload_json, actor, occurred_at = row
        return MemoryEvent(
            id=str(event_id),
            kind=str(kind),  # type: ignore[arg-type]
            repo_url=str(repo_url),
            payload=json.loads(str(payload_json)),
            actor=str(actor),
            occurred_at=datetime.fromisoformat(str(occurred_at)),
        )


__all__ = ["LocalFileMemoryAdapter"]
