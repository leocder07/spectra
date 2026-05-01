"""Tests for the ``manage_portfolio`` use case (#26).

Pure scheduling logic — given a list of registered repos, a tag filter,
and a staleness threshold, return the subset to scan and the subset to
skip. The use case has no I/O; the registry, scanner, and clock are all
injected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectra.entities.models import RepoRegistryEntry
from spectra.use_cases.manage_portfolio import (
    PortfolioScanPlan,
    PortfolioScanRunMode,
    plan_portfolio_scan,
    select_run_mode,
)

_NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


def _entry(
    url: str,
    *,
    last_scan_at: datetime | None = None,
    tags: tuple[str, ...] = (),
    added_offset_seconds: int = 0,
) -> RepoRegistryEntry:
    return RepoRegistryEntry(
        repo_url=url,
        added_at=_NOW + timedelta(seconds=added_offset_seconds),
        last_scan_at=last_scan_at,
        tags=tags,
    )


class TestPlanPortfolioScan:
    """``plan_portfolio_scan`` returns ``(to_scan, skipped)`` partitions."""

    def test_empty_registry_returns_empty_plan(self) -> None:
        plan = plan_portfolio_scan(
            entries=(),
            tag=None,
            since=timedelta(days=7),
            now=_NOW,
        )

        assert plan.to_scan == ()
        assert plan.skipped == ()

    def test_never_scanned_repos_are_always_in_to_scan(self) -> None:
        entry = _entry("https://github.com/a/b")

        plan = plan_portfolio_scan(
            entries=(entry,),
            tag=None,
            since=timedelta(days=7),
            now=_NOW,
        )

        assert plan.to_scan == (entry,)
        assert plan.skipped == ()

    def test_recently_scanned_repo_is_skipped(self) -> None:
        fresh = _entry(
            "https://github.com/a/fresh",
            last_scan_at=_NOW - timedelta(days=2),
        )

        plan = plan_portfolio_scan(
            entries=(fresh,),
            tag=None,
            since=timedelta(days=7),
            now=_NOW,
        )

        assert plan.to_scan == ()
        assert plan.skipped == (fresh,)

    def test_long_ago_scanned_repo_is_in_to_scan(self) -> None:
        stale = _entry(
            "https://github.com/a/stale",
            last_scan_at=_NOW - timedelta(days=30),
        )

        plan = plan_portfolio_scan(
            entries=(stale,),
            tag=None,
            since=timedelta(days=7),
            now=_NOW,
        )

        assert plan.to_scan == (stale,)
        assert plan.skipped == ()

    def test_tag_filter_excludes_other_tags(self) -> None:
        payments = _entry("https://github.com/a/payments", tags=("team:payments",))
        web = _entry("https://github.com/a/web", tags=("team:web",))

        plan = plan_portfolio_scan(
            entries=(payments, web),
            tag="team:payments",
            since=timedelta(days=7),
            now=_NOW,
        )

        assert plan.to_scan == (payments,)
        assert plan.skipped == ()

    def test_tag_filter_combined_with_staleness(self) -> None:
        # Matches tag, fresh — skipped (kept in plan output for visibility)
        payments_fresh = _entry(
            "https://github.com/a/payments-fresh",
            tags=("team:payments",),
            last_scan_at=_NOW - timedelta(days=2),
        )
        # Matches tag, stale — scan
        payments_stale = _entry(
            "https://github.com/a/payments-stale",
            tags=("team:payments",),
            last_scan_at=_NOW - timedelta(days=30),
        )
        # Other tag, stale — excluded entirely
        other = _entry(
            "https://github.com/a/other",
            tags=("team:web",),
            last_scan_at=_NOW - timedelta(days=30),
        )

        plan = plan_portfolio_scan(
            entries=(payments_fresh, payments_stale, other),
            tag="team:payments",
            since=timedelta(days=7),
            now=_NOW,
        )

        assert plan.to_scan == (payments_stale,)
        assert plan.skipped == (payments_fresh,)


class TestSelectRunMode:
    """``select_run_mode`` picks sync vs Batch API based on volume."""

    def test_small_count_returns_sync(self) -> None:
        assert select_run_mode(repo_count=1) is PortfolioScanRunMode.SYNC
        assert select_run_mode(repo_count=5) is PortfolioScanRunMode.SYNC

    def test_large_count_returns_batch(self) -> None:
        assert select_run_mode(repo_count=6) is PortfolioScanRunMode.BATCH
        assert select_run_mode(repo_count=312) is PortfolioScanRunMode.BATCH

    def test_zero_count_returns_sync_for_no_op(self) -> None:
        # An empty plan never reaches the dispatcher; sync is the safer
        # zero-cost default so the caller doesn't allocate Batch resources.
        assert select_run_mode(repo_count=0) is PortfolioScanRunMode.SYNC

    def test_threshold_can_be_overridden_for_tests(self) -> None:
        assert select_run_mode(repo_count=3, batch_threshold=10) is PortfolioScanRunMode.SYNC
        assert select_run_mode(repo_count=11, batch_threshold=10) is PortfolioScanRunMode.BATCH


class TestPortfolioScanPlanShape:
    """``PortfolioScanPlan`` is a frozen entity (Layer-1 contract)."""

    def test_plan_total_repos(self) -> None:
        a = _entry("https://github.com/a/b")
        b = _entry("https://github.com/c/d", last_scan_at=_NOW - timedelta(days=2))

        plan = plan_portfolio_scan(
            entries=(a, b),
            tag=None,
            since=timedelta(days=7),
            now=_NOW,
        )

        assert plan.total_known() == 2
        assert plan.has_work() is True

    def test_empty_plan_has_no_work(self) -> None:
        plan = PortfolioScanPlan(to_scan=(), skipped=())
        assert plan.has_work() is False
