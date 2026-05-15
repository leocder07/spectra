"""Tests for ``LocalFileMemoryAdapter`` (Layer 4, Q4 #50, ADR-025).

Covers:
- ``MemoryPort`` Protocol compliance via ``isinstance``-style structural check
- Append + immediate read round-trip
- Filter by ``kind`` and by ``since``
- ``limit`` honoured on both query + search
- FTS5 search finds events by payload text
- Idempotent append on duplicate ``event.id``
- Newest-first ordering
- File permissions are owner-only (ADR-012 carry-over)
- Adapter raises ``AgentError(SPEC-010)`` on read against a corrupt DB
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spectra.entities.errors import AgentError
from spectra.entities.memory import MemoryEvent
from spectra.infrastructure.local_file_memory_adapter import LocalFileMemoryAdapter
from spectra.use_cases.interfaces import MemoryPort

# ── Helpers ────────────────────────────────────────────────────


def _now(offset_seconds: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


def _event(
    *,
    kind: str = "scan_completed",
    payload: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
    actor: str = "leocder07@spectra-ai",
    repo_url: str = "https://github.com/leocder07/spectra",
) -> MemoryEvent:
    kwargs = {
        "kind": kind,
        "repo_url": repo_url,
        "payload": payload or {},
        "actor": actor,
        "occurred_at": occurred_at or _now(),
    }
    if event_id is not None:
        kwargs["id"] = event_id
    return MemoryEvent(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "memory.sqlite"


# ── Protocol compliance ────────────────────────────────────────


def test_satisfies_memory_port_protocol(db_path: Path) -> None:
    """Structural Protocol compliance — verify each method exists.

    The project convention (every other Port in interfaces.py) is to
    skip ``@runtime_checkable``; we mirror that here and check the
    method surface explicitly. The integration tests below exercise
    each method end-to-end, which is the real correctness signal.
    """
    adapter = LocalFileMemoryAdapter(db_path)
    for name in ("append_event", "query_events", "search"):
        assert callable(getattr(adapter, name)), f"missing MemoryPort method: {name}"
    # Hint to the reader: the variable is intentionally referenced so
    # the Protocol import is exercised.
    _ = MemoryPort


# ── Round-trip ─────────────────────────────────────────────────


class TestAppendAndQuery:
    @pytest.mark.asyncio
    async def test_append_then_query_returns_event(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        event = _event(payload={"score": 92})
        await adapter.append_event(event)
        result = await adapter.query_events()
        assert event in result
        assert result[0].payload == {"score": 92}

    @pytest.mark.asyncio
    async def test_query_with_no_events_returns_empty_tuple(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        assert await adapter.query_events() == ()

    @pytest.mark.asyncio
    async def test_idempotent_append_on_duplicate_id(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        event = _event(event_id="evt-fixed-1")
        await adapter.append_event(event)
        await adapter.append_event(event)
        result = await adapter.query_events()
        assert len(result) == 1, "Duplicate event id should not introduce a second row"

    @pytest.mark.asyncio
    async def test_results_ordered_newest_first(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        old = _event(event_id="evt-old", occurred_at=_now(-3600))
        new = _event(event_id="evt-new", occurred_at=_now())
        await adapter.append_event(old)
        await adapter.append_event(new)
        result = await adapter.query_events()
        assert result[0].id == "evt-new"
        assert result[1].id == "evt-old"


# ── Filters ────────────────────────────────────────────────────


class TestFilters:
    @pytest.mark.asyncio
    async def test_filter_by_kind(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        await adapter.append_event(_event(event_id="s", kind="scan_completed"))
        await adapter.append_event(_event(event_id="w", kind="waiver_added"))
        await adapter.append_event(_event(event_id="d", kind="drift_detected"))
        result = await adapter.query_events(kind="waiver_added")
        assert {e.id for e in result} == {"w"}

    @pytest.mark.asyncio
    async def test_filter_by_since_strictly_after(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        cutoff = _now()
        await adapter.append_event(_event(event_id="before", occurred_at=cutoff - timedelta(seconds=10)))
        await adapter.append_event(_event(event_id="at", occurred_at=cutoff))
        await adapter.append_event(_event(event_id="after", occurred_at=cutoff + timedelta(seconds=10)))
        result = await adapter.query_events(since=cutoff)
        # ADR-025 says strictly greater than `since`.
        assert {e.id for e in result} == {"after"}

    @pytest.mark.asyncio
    async def test_limit_caps_result_count(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        for i in range(5):
            await adapter.append_event(_event(event_id=f"evt-{i}", occurred_at=_now(i)))
        result = await adapter.query_events(limit=2)
        assert len(result) == 2


# ── FTS5 search ────────────────────────────────────────────────


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_finds_event_by_payload_text(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        await adapter.append_event(
            _event(event_id="auth-finding", payload={"summary": "missing authorization on PII endpoint"}),
        )
        await adapter.append_event(
            _event(event_id="other-finding", payload={"summary": "performance regression in cache adapter"}),
        )
        result = await adapter.search("authorization")
        assert {e.id for e in result} == {"auth-finding"}

    @pytest.mark.asyncio
    async def test_search_limit_caps_result_count(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        for i in range(15):
            await adapter.append_event(
                _event(event_id=f"e-{i}", payload={"summary": "shared keyword token"}),
            )
        result = await adapter.search("keyword", limit=5)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        await adapter.append_event(_event(payload={"summary": "alpha"}))
        result = await adapter.search("never_appears")
        assert result == ()


# ── File permissions (ADR-012 carry-over) ──────────────────────


class TestFilePermissions:
    @pytest.mark.asyncio
    async def test_db_file_owner_only(self, db_path: Path) -> None:
        if os.name != "posix":
            pytest.skip("POSIX permission semantics only")
        adapter = LocalFileMemoryAdapter(db_path)
        await adapter.append_event(_event())
        mode = db_path.stat().st_mode & 0o777
        assert mode == 0o600, f"DB file must be owner-only (got {oct(mode)})"


# ── Failure mode (ADR-025: reads raise; corrupt DB → SPEC-010) ─


class TestReadFailureMode:
    @pytest.mark.asyncio
    async def test_corrupt_db_raises_spec_010_on_query(self, db_path: Path) -> None:
        # Drop bytes that aren't a valid SQLite database.
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"\x00" * 256)
        adapter = LocalFileMemoryAdapter(db_path)
        with pytest.raises(AgentError) as exc_info:
            await adapter.query_events()
        assert exc_info.value.error.code == "SPEC-010"


# ── Concurrency smoke ──────────────────────────────────────────


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_parallel_appends_preserve_all_events(self, db_path: Path) -> None:
        adapter = LocalFileMemoryAdapter(db_path)
        events = [_event(event_id=f"par-{i}", occurred_at=_now(i)) for i in range(20)]
        await asyncio.gather(*(adapter.append_event(e) for e in events))
        result = await adapter.query_events(limit=100)
        assert len(result) == 20
        assert {e.id for e in result} == {e.id for e in events}


@pytest.fixture
def _close_sqlite_handles(db_path: Path) -> None:
    # Smoke fixture so PyFlakes doesn't trip the import.
    _ = sqlite3
