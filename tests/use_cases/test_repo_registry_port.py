"""Contract tests for ``RepoRegistryPort`` — the portfolio registry seam (#26).

The Protocol lives in ``spectra.use_cases.interfaces`` so the use-case
layer never imports ``sqlite3``. These tests exercise the contract via
a tiny in-memory implementation; the SQLite adapter has its own
infrastructure-level test suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectra.entities.models import RepoRegistryEntry
from spectra.use_cases.interfaces import RepoRegistryPort

_NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


class _InMemoryRegistry:
    """Synchronous in-memory ``RepoRegistryPort`` for contract tests."""

    def __init__(self) -> None:
        self._rows: dict[str, RepoRegistryEntry] = {}

    def add(self, repo_url: str, *, tags: tuple[str, ...] = (), now: datetime | None = None) -> RepoRegistryEntry:
        if repo_url in self._rows:
            existing = self._rows[repo_url]
            merged_tags = tuple(dict.fromkeys((*existing.tags, *tags)))
            entry = existing.model_copy(update={"tags": merged_tags})
        else:
            entry = RepoRegistryEntry(
                repo_url=repo_url,
                added_at=now or datetime.now(UTC),
                tags=tags,
            )
        self._rows[repo_url] = entry
        return entry

    def remove(self, repo_url: str) -> bool:
        return self._rows.pop(repo_url, None) is not None

    def list(self, *, tag: str | None = None) -> tuple[RepoRegistryEntry, ...]:
        rows = sorted(self._rows.values(), key=lambda e: e.added_at)
        if tag is None:
            return tuple(rows)
        return tuple(r for r in rows if r.has_tag(tag))

    def mark_scanned(self, repo_url: str, *, scanned_at: datetime) -> RepoRegistryEntry | None:
        existing = self._rows.get(repo_url)
        if existing is None:
            return None
        updated = existing.model_copy(update={"last_scan_at": scanned_at})
        self._rows[repo_url] = updated
        return updated


def _registry() -> RepoRegistryPort:
    """Return a fresh in-memory registry typed at the Protocol."""
    return _InMemoryRegistry()


class TestRepoRegistryPortAdd:
    """``add`` is idempotent and merges tags."""

    def test_add_new_repo_returns_entry_with_tags(self) -> None:
        reg = _registry()

        entry = reg.add("https://github.com/a/b", tags=("team:payments",), now=_NOW)

        assert entry.repo_url == "https://github.com/a/b"
        assert entry.tags == ("team:payments",)
        assert entry.last_scan_at is None

    def test_add_same_repo_merges_tags_without_duplicates(self) -> None:
        reg = _registry()

        reg.add("https://github.com/a/b", tags=("team:payments",), now=_NOW)
        merged = reg.add("https://github.com/a/b", tags=("tier:1", "team:payments"), now=_NOW)

        assert merged.tags == ("team:payments", "tier:1")


class TestRepoRegistryPortRemove:
    """``remove`` returns whether anything was deleted."""

    def test_remove_existing_returns_true(self) -> None:
        reg = _registry()
        reg.add("https://github.com/a/b", now=_NOW)

        assert reg.remove("https://github.com/a/b") is True
        assert reg.list() == ()

    def test_remove_missing_returns_false(self) -> None:
        reg = _registry()

        assert reg.remove("https://github.com/a/b") is False


class TestRepoRegistryPortList:
    """``list`` returns deterministic order and supports tag filtering."""

    def test_list_returns_entries_in_added_at_order(self) -> None:
        reg = _registry()
        reg.add("https://github.com/a/first", now=_NOW)
        reg.add("https://github.com/a/second", now=_NOW + timedelta(seconds=1))

        rows = reg.list()

        assert [r.repo_url for r in rows] == [
            "https://github.com/a/first",
            "https://github.com/a/second",
        ]

    def test_list_filters_by_tag(self) -> None:
        reg = _registry()
        reg.add("https://github.com/a/payments", tags=("team:payments",), now=_NOW)
        reg.add("https://github.com/a/web", tags=("team:web",), now=_NOW)

        payments = reg.list(tag="team:payments")

        assert len(payments) == 1
        assert payments[0].repo_url == "https://github.com/a/payments"

    def test_list_empty_when_no_match(self) -> None:
        reg = _registry()
        reg.add("https://github.com/a/payments", tags=("team:payments",), now=_NOW)

        assert reg.list(tag="team:nope") == ()


class TestRepoRegistryPortMarkScanned:
    """``mark_scanned`` updates ``last_scan_at`` and returns the new entry."""

    def test_mark_scanned_updates_timestamp(self) -> None:
        reg = _registry()
        reg.add("https://github.com/a/b", now=_NOW)

        scanned_at = _NOW + timedelta(hours=1)
        updated = reg.mark_scanned("https://github.com/a/b", scanned_at=scanned_at)

        assert updated is not None
        assert updated.last_scan_at == scanned_at

    def test_mark_scanned_returns_none_when_missing(self) -> None:
        reg = _registry()

        assert reg.mark_scanned("https://github.com/a/missing", scanned_at=_NOW) is None
