"""Tests for ``SqliteRepoRegistry`` — Layer 4 implementation of ``RepoRegistryPort`` (#26).

The adapter persists rows in the same on-disk file as the cache (one
``cache.db`` per ``$XDG_CACHE_HOME``), separate table
``portfolio_repos``. The adapter applies its own migration on startup
(idempotent CREATE TABLE IF NOT EXISTS) so reusing the existing cache
file is safe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spectra.entities.errors import AgentError
from spectra.infrastructure.history.sqlite_repo_registry import SqliteRepoRegistry

_NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def registry(tmp_path: Path) -> SqliteRepoRegistry:
    """Open a fresh SQLite registry on a temp file."""
    return SqliteRepoRegistry(db_path=tmp_path / "portfolio.db")


class TestSqliteRepoRegistryAddAndList:
    """``add`` is idempotent and round-trips through SQLite."""

    def test_add_then_list_returns_entry(self, registry: SqliteRepoRegistry) -> None:
        entry = registry.add(
            "https://github.com/a/b",
            tags=("team:payments",),
            now=_NOW,
        )

        rows = registry.list()

        assert len(rows) == 1
        assert rows[0].repo_url == entry.repo_url
        assert rows[0].tags == ("team:payments",)
        assert rows[0].last_scan_at is None

    def test_add_same_url_merges_tags(self, registry: SqliteRepoRegistry) -> None:
        registry.add("https://github.com/a/b", tags=("team:payments",), now=_NOW)
        registry.add("https://github.com/a/b", tags=("tier:1", "team:payments"), now=_NOW)

        rows = registry.list()

        assert len(rows) == 1
        assert rows[0].tags == ("team:payments", "tier:1")

    def test_list_returns_added_at_order(self, registry: SqliteRepoRegistry) -> None:
        registry.add("https://github.com/a/first", now=_NOW)
        registry.add("https://github.com/a/second", now=_NOW + timedelta(seconds=1))

        rows = registry.list()

        assert [r.repo_url for r in rows] == [
            "https://github.com/a/first",
            "https://github.com/a/second",
        ]

    def test_list_filters_by_tag(self, registry: SqliteRepoRegistry) -> None:
        registry.add("https://github.com/a/payments", tags=("team:payments",), now=_NOW)
        registry.add("https://github.com/a/web", tags=("team:web",), now=_NOW)

        rows = registry.list(tag="team:payments")

        assert len(rows) == 1
        assert rows[0].repo_url == "https://github.com/a/payments"


class TestSqliteRepoRegistryRemove:
    """``remove`` deletes the row + reports whether it existed."""

    def test_remove_existing_returns_true(self, registry: SqliteRepoRegistry) -> None:
        registry.add("https://github.com/a/b", now=_NOW)

        assert registry.remove("https://github.com/a/b") is True
        assert registry.list() == ()

    def test_remove_missing_returns_false(self, registry: SqliteRepoRegistry) -> None:
        assert registry.remove("https://github.com/a/missing") is False


class TestSqliteRepoRegistryMarkScanned:
    """``mark_scanned`` updates the persisted ``last_scan_at`` column."""

    def test_mark_scanned_persists_timestamp(self, registry: SqliteRepoRegistry) -> None:
        registry.add("https://github.com/a/b", now=_NOW)

        scanned_at = _NOW + timedelta(hours=1)
        updated = registry.mark_scanned("https://github.com/a/b", scanned_at=scanned_at)

        assert updated is not None
        assert updated.last_scan_at == scanned_at

        rows = registry.list()
        assert rows[0].last_scan_at == scanned_at

    def test_mark_scanned_returns_none_when_missing(self, registry: SqliteRepoRegistry) -> None:
        assert registry.mark_scanned("https://github.com/a/missing", scanned_at=_NOW) is None


class TestSqliteRepoRegistryPersistence:
    """The registry survives process restarts (different adapter instances)."""

    def test_two_instances_share_state(self, tmp_path: Path) -> None:
        db_path = tmp_path / "portfolio.db"
        first = SqliteRepoRegistry(db_path=db_path)
        first.add("https://github.com/a/b", tags=("team:payments",), now=_NOW)
        first.close()

        second = SqliteRepoRegistry(db_path=db_path)
        rows = second.list()

        assert len(rows) == 1
        assert rows[0].repo_url == "https://github.com/a/b"
        assert rows[0].tags == ("team:payments",)


class TestSqliteRepoRegistryFailure:
    """SPEC-010: cache I/O failure raises ``AgentError`` so the CLI degrades cleanly."""

    def test_open_on_unwritable_directory_raises(self, tmp_path: Path) -> None:
        # /proc on Linux is read-only; on macOS use a non-existent volume root.
        bad = Path("/this/path/should/never/be/writable/spectra-test/portfolio.db")
        with pytest.raises((AgentError, OSError)):
            SqliteRepoRegistry(db_path=bad)


class TestSqliteRepoRegistryStaleness:
    """The ``is_stale`` entity helper round-trips through SQLite correctly."""

    def test_never_scanned_entry_is_stale_after_load(self, registry: SqliteRepoRegistry) -> None:
        registry.add("https://github.com/a/b", now=_NOW)

        rows = registry.list()

        assert rows[0].is_stale(now=_NOW + timedelta(days=1), max_age=timedelta(days=7)) is True

    def test_recently_scanned_entry_is_not_stale_after_load(self, registry: SqliteRepoRegistry) -> None:
        registry.add("https://github.com/a/b", now=_NOW)
        registry.mark_scanned("https://github.com/a/b", scanned_at=_NOW + timedelta(days=1))

        rows = registry.list()

        assert rows[0].is_stale(now=_NOW + timedelta(days=2), max_age=timedelta(days=7)) is False
