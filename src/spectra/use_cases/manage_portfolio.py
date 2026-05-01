"""Portfolio scheduling logic — Layer 2 (#26).

Pure functions over ``RepoRegistryEntry`` tuples. The scheduler partitions
the registry into ``to_scan`` and ``skipped`` based on a tag filter and a
staleness threshold; the dispatcher (in ``infrastructure``) iterates over
``to_scan`` and reuses the existing analyzer pipeline.

The use case has zero I/O — every dependency (registry, clock, scanner)
is injected at the call site so the pipeline is trivially testable.

ADR references: ADR-022 (history schema — the scan results land there
on every successful run via the analyze_repository write-back hook).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from spectra.entities.models import RepoRegistryEntry


# ── Run mode selector ────────────────────────────────────────


_DEFAULT_BATCH_THRESHOLD = 6
"""Repo counts at or above this threshold dispatch through Batch API.

Picked so a small portfolio (~5 repos, the demo size in the q3-plan)
runs sync — the wall-clock win matters more than the 50% Batch discount
on a $0.50 run. Above the threshold, the cost dominates and the
overnight Batch latency is acceptable.
"""


class PortfolioScanRunMode(Enum):
    """Dispatch mode for one ``portfolio scan`` invocation.

    SYNC: one ``await analyzer(repo)`` per repo, sequential. Best for
        small portfolios where wall clock matters more than cost.
    BATCH: route every per-repo analyzer call through ``BatchSubmitterPort``
        for the 50% Anthropic Batch discount. Best for overnight runs
        on 50+ repos.
    """

    SYNC = "sync"
    BATCH = "batch"


def select_run_mode(
    *,
    repo_count: int,
    batch_threshold: int = _DEFAULT_BATCH_THRESHOLD,
) -> PortfolioScanRunMode:
    """Pick sync vs Batch dispatch based on the number of repos to scan.

    Pure function — the inputs are integers and the output is a frozen
    enum. Callers (the CLI / dispatcher) pass the threshold explicitly
    in tests so the logic stays deterministic across CI runs.
    """
    if repo_count >= batch_threshold:
        return PortfolioScanRunMode.BATCH
    return PortfolioScanRunMode.SYNC


# ── Plan + planner ────────────────────────────────────────────


@dataclass(frozen=True)
class PortfolioScanPlan:
    """Result of partitioning the registry by ``--tag`` and ``--since``.

    Attributes:
        to_scan: Tuple of entries the dispatcher should analyze, ordered
            most-stale first so the long pole runs early when scheduled
            sequentially.
        skipped: Tuple of entries excluded by the staleness filter
            (kept for the user-facing summary). Tag-excluded entries are
            absent from both tuples — they are out of scope for this run.
    """

    to_scan: tuple[RepoRegistryEntry, ...]
    skipped: tuple[RepoRegistryEntry, ...]

    def total_known(self) -> int:
        """Return the total number of entries the planner considered."""
        return len(self.to_scan) + len(self.skipped)

    def has_work(self) -> bool:
        """Return True when at least one entry was selected for scanning."""
        return len(self.to_scan) > 0


def plan_portfolio_scan(
    *,
    entries: tuple[RepoRegistryEntry, ...],
    tag: str | None,
    since: timedelta,
    now: datetime,
) -> PortfolioScanPlan:
    """Partition ``entries`` into ``(to_scan, skipped)`` for the dispatcher.

    Tag-excluded entries vanish — they are out of scope for this run and
    the user already knows about them from ``portfolio list``. Entries
    that match the tag are split by staleness: never-scanned and stale
    entries land in ``to_scan``, fresh entries in ``skipped``. The
    half-open interval — exactly ``since`` ago is still fresh — matches
    ``RepoRegistryEntry.is_stale``.

    Args:
        entries: Every registered entry (filter applied here, not by the
            registry adapter, so the use case stays pure).
        tag: Optional tag filter; ``None`` means "every entry".
        since: Maximum age before a previously-scanned entry counts as
            stale. ``timedelta(0)`` would mean "rescan everything".
        now: Caller-supplied current UTC timestamp. Tests inject a fixed
            value; production passes ``datetime.now(UTC)``.

    Returns:
        A frozen :class:`PortfolioScanPlan`.
    """
    in_scope = tuple(e for e in entries if tag is None or e.has_tag(tag))
    to_scan: list[RepoRegistryEntry] = []
    skipped: list[RepoRegistryEntry] = []
    for entry in in_scope:
        if entry.is_stale(now=now, max_age=since):
            to_scan.append(entry)
        else:
            skipped.append(entry)
    # Most-stale first: never-scanned entries (None) sort before any
    # datetime when we use the "minimum scan time" key — but Python
    # cannot compare None with datetime, so we coerce None to a sentinel
    # earlier than any real timestamp.
    to_scan.sort(key=_sort_key_oldest_first)
    return PortfolioScanPlan(to_scan=tuple(to_scan), skipped=tuple(skipped))


def _sort_key_oldest_first(entry: RepoRegistryEntry) -> tuple[int, object]:
    """Sort key: never-scanned (None) first, then by ``last_scan_at`` ascending."""
    if entry.last_scan_at is None:
        return (0, "")  # never scanned wins
    return (1, entry.last_scan_at.isoformat())
