"""Tests for ``RepoRegistryEntry`` — Layer-1 frozen entity (#26).

The entity carries one row of ``portfolio_repos``: the repo URL, the
moment it was added, the most recent scan timestamp (None for never
scanned), and a frozen tuple of free-form tags (``team:payments``,
``tier:1``). Equality, immutability, and tag normalisation are all
part of the entity contract — the registry adapter relies on them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from spectra.entities.models import RepoRegistryEntry

_NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


class TestRepoRegistryEntryConstruction:
    """Construction + validation contract."""

    def test_minimal_entry_uses_empty_tag_tuple(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/octocat/spoon-knife",
            added_at=_NOW,
        )
        assert entry.tags == ()
        assert entry.last_scan_at is None

    def test_tags_are_frozen_tuple(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/octocat/spoon-knife",
            added_at=_NOW,
            tags=("team:payments", "tier:1"),
        )
        assert entry.tags == ("team:payments", "tier:1")
        # Immutability: cannot reassign the tag tuple.
        with pytest.raises(ValidationError):
            entry.tags = ("other",)  # type: ignore[misc]

    def test_last_scan_at_accepts_aware_datetime(self) -> None:
        scan_ts = _NOW + timedelta(hours=2)
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW,
            last_scan_at=scan_ts,
        )
        assert entry.last_scan_at == scan_ts

    def test_empty_repo_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RepoRegistryEntry(repo_url="", added_at=_NOW)


class TestRepoRegistryEntryTagSemantics:
    """Tag-list helpers used by the CLI ``--tag`` filter."""

    def test_has_tag_returns_true_for_exact_match(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW,
            tags=("team:payments", "tier:1"),
        )
        assert entry.has_tag("team:payments") is True
        assert entry.has_tag("tier:1") is True

    def test_has_tag_returns_false_for_missing_tag(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW,
            tags=("team:payments",),
        )
        assert entry.has_tag("team:web") is False

    def test_has_tag_is_case_sensitive(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW,
            tags=("team:payments",),
        )
        assert entry.has_tag("TEAM:PAYMENTS") is False


class TestRepoRegistryEntryStaleness:
    """``is_stale`` powers the scheduler's ``--since`` filter."""

    def test_never_scanned_repo_is_always_stale(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW,
        )
        assert entry.is_stale(now=_NOW, max_age=timedelta(days=7)) is True

    def test_recently_scanned_repo_is_not_stale(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW - timedelta(days=30),
            last_scan_at=_NOW - timedelta(days=2),
        )
        assert entry.is_stale(now=_NOW, max_age=timedelta(days=7)) is False

    def test_long_ago_scanned_repo_is_stale(self) -> None:
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW - timedelta(days=30),
            last_scan_at=_NOW - timedelta(days=14),
        )
        assert entry.is_stale(now=_NOW, max_age=timedelta(days=7)) is True

    def test_scanned_exactly_at_threshold_is_not_stale(self) -> None:
        # Half-open interval — exactly at ``max_age`` ago is still fresh.
        entry = RepoRegistryEntry(
            repo_url="https://github.com/o/r",
            added_at=_NOW - timedelta(days=30),
            last_scan_at=_NOW - timedelta(days=7),
        )
        assert entry.is_stale(now=_NOW, max_age=timedelta(days=7)) is False
