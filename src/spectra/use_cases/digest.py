"""Weekly digest composer — capability #34.

Reads the history store for a window (default 7 days), aggregates per-
repo deltas, and returns a :class:`Digest` value object. The CLI
``spectra digest`` renders it as markdown to stdout; with
``--notify <webhook>`` it fans the same payload to ``NotifierPort``.

The use case enumerates repos via a small extension of
``ReportStorePort`` (``list_signatures_in_window``) — defined here as a
structural protocol so the layer-2 contract stays focused on
single-repo lookups. Both real adapters (sqlite + postgres) implement
it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import BaseModel

from spectra.entities.enums import Grade

if TYPE_CHECKING:
    from spectra.entities.models import ReportSummary


# ── Window protocol ─────────────────────────────────────────


class HistoryWindowPort(Protocol):
    """Sub-protocol of ``ReportStorePort`` plus repo enumeration.

    The base port supports per-repo lookups; the digest needs a fleet-
    wide sweep over distinct repo signatures inside a window. Both
    real adapters (sqlite + postgres) implement this method; tests pass
    in-memory stubs that satisfy the same shape.
    """

    async def history(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]: ...

    async def list_signatures_in_window(
        self,
        since: datetime,
        until: datetime,
    ) -> tuple[str, ...]: ...


# ── Value objects ───────────────────────────────────────────


class RepoDelta(BaseModel, frozen=True):
    """One repo's score change over the digest window.

    Attributes:
        repo_name: Friendly short name from the latest summary.
        latest_score: Most recent overall score.
        previous_score: Score at window start (or earliest in-window scan
            when no previous scan exists).
        latest_grade: Letter grade derived from ``latest_score``.
        previous_grade: Letter grade for ``previous_score``.
        latest_findings: Total findings on the most recent scan.
    """

    repo_name: str
    latest_score: float
    previous_score: float
    latest_grade: Grade
    previous_grade: Grade
    latest_findings: int

    @property
    def delta(self) -> float:
        """Signed score change (latest - previous). Negative = drop."""
        return self.latest_score - self.previous_score


class Digest(BaseModel, frozen=True):
    """Aggregated digest across the fleet.

    Attributes:
        repos: Every repo seen in the window, sorted by absolute delta.
        worst: Repos whose score dropped, worst-first (top 5 in CLI).
        best: Repos whose score improved, best-first (top 5 in CLI).
        window_days: Lookback window in days.
    """

    repos: tuple[RepoDelta, ...]
    worst: tuple[RepoDelta, ...]
    best: tuple[RepoDelta, ...]
    window_days: int


# ── Composer ────────────────────────────────────────────────


# How many repos to surface in the worst/best leaderboards. The full
# list is also available via ``Digest.repos`` for callers that want to
# render their own.
_LEADERBOARD_TOP_N: Final[int] = 5


async def compose_weekly_digest(
    *,
    history: HistoryWindowPort,
    window_days: int = 7,
) -> Digest:
    """Build a :class:`Digest` over the last ``window_days`` of history.

    Returns an empty ``Digest`` when no scans were recorded — never raises
    on empty data so the CLI / cron path can branch on the shape.
    """
    until = datetime.now(UTC)
    since = until - timedelta(days=window_days)
    signatures = await history.list_signatures_in_window(since=since, until=until)
    if not signatures:
        return Digest(repos=(), worst=(), best=(), window_days=window_days)
    deltas: list[RepoDelta] = []
    for sig in signatures:
        delta = await _compute_delta_for_repo(history, repo_signature=sig, since=since, until=until)
        if delta is not None:
            deltas.append(delta)
    repos = tuple(sorted(deltas, key=lambda d: -abs(d.delta)))
    worst = tuple(sorted([d for d in deltas if d.delta < 0], key=lambda d: d.delta))[:_LEADERBOARD_TOP_N]
    best = tuple(sorted([d for d in deltas if d.delta > 0], key=lambda d: -d.delta))[:_LEADERBOARD_TOP_N]
    return Digest(repos=repos, worst=worst, best=best, window_days=window_days)


async def _compute_delta_for_repo(
    history: HistoryWindowPort,
    *,
    repo_signature: str,
    since: datetime,
    until: datetime,
) -> RepoDelta | None:
    """Return the latest-vs-earliest delta for one repo in the window."""
    rows = await history.history(repo_signature, since=since, until=until)
    if not rows:
        return None
    # rows are most-recent-first per ADR-022 §6
    latest = rows[0]
    previous = rows[-1]  # earliest in-window scan
    return RepoDelta(
        repo_name=latest.repo_name,
        latest_score=latest.overall_score,
        previous_score=previous.overall_score,
        latest_grade=latest.overall_grade,
        previous_grade=previous.overall_grade,
        latest_findings=latest.total_findings,
    )


# ── Renderers ───────────────────────────────────────────────


def render_digest_markdown(digest: Digest) -> str:
    """Render the digest as a brand-voice markdown body.

    The same body is used for stdout (``spectra digest``) and for the
    notifier payload (``spectra digest --notify <webhook>``).
    """
    lines: list[str] = [
        f"# Spectra weekly digest — last {digest.window_days} days",
        "",
    ]
    if not digest.repos:
        lines.append("No scans in the window.")
        return "\n".join(lines)
    lines.append(f"_Tracked {len(digest.repos)} repo(s)._")
    lines.append("")
    if digest.worst:
        lines.append(f"## Top {len(digest.worst)} worst trends")
        lines.append("")
        lines.extend(_render_delta_line(d, drop=True) for d in digest.worst)
        lines.append("")
    if digest.best:
        lines.append(f"## Top {len(digest.best)} best improvements")
        lines.append("")
        lines.extend(_render_delta_line(d, drop=False) for d in digest.best)
        lines.append("")
    return "\n".join(lines)


def _render_delta_line(delta: RepoDelta, *, drop: bool) -> str:
    """One-line bullet for a RepoDelta — direction emoji + grade arrow."""
    arrow = "↓" if drop else "↑"
    return (
        f"- *{delta.repo_name}* {arrow} **{delta.previous_grade}** → **{delta.latest_grade}** "
        f"({delta.previous_score:.1f} → {delta.latest_score:.1f}, "
        f"Δ {delta.delta:+.1f}, {delta.latest_findings} findings)"
    )


__all__ = [
    "Digest",
    "HistoryWindowPort",
    "RepoDelta",
    "compose_weekly_digest",
    "render_digest_markdown",
]
