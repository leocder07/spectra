"""Drift detection use case — capability #27.

Compares the most recent two ``ReportSummary`` rows for a repo and
emits a :class:`DriftEvent` per dimension whose score dropped beyond a
configurable threshold (or whose overall grade dropped a full letter).
The downstream consumer (CLI ``spectra trend`` and the post-scan hook)
fans the events out to ``NotifierPort`` for Slack/Teams alerts.

Thresholds:
    Default ``threshold_pts`` is 10 — a conservative "full-grade drop"
    cut-off that screens out per-run stochastic noise (post-R3 self-scan
    caveat noted in the Q3 plan). Operators tune via CLI flag.

The use case is read-only: it touches ``ReportStorePort.history`` and
nothing else, so it cannot accidentally mutate scan history. Failures
in the store propagate (not swallowed here) so the caller can decide
whether drift is mandatory or best-effort for that path.

ADR references in this module: ADR-022 (history store + window query
patterns). See ``docs/glossary.md`` for the at-a-glance ADR index.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel

from spectra.entities.enums import Dimension, Grade

if TYPE_CHECKING:
    from spectra.entities.models import DimensionScore, ReportSummary
    from spectra.use_cases.interfaces import ReportStorePort


# Lookback window for the latest-vs-previous comparison. We grab one
# month so a slow-cadence repo (e.g. weekly scan) still has a previous
# point to diff against. The query is index-only on (repo_signature, ts).
_DEFAULT_LOOKBACK_DAYS: Final[int] = 60

# Minimum absolute delta (points) below which we never fire — the
# post-R3 self-scan noise floor (Q3 plan §27 risk note).
_NOISE_FLOOR_PTS: Final[float] = 2.0

# Default per-dimension drop threshold in points.
_DEFAULT_THRESHOLD_PTS: Final[int] = 10


# Drift can fire on any individual dimension OR on the overall score.
# The overall is rendered as the literal ``"overall"`` so consumers can
# distinguish "the whole repo dropped a grade" from "one dim slipped".
DriftDimension = Literal[
    "overall",
    "architecture",
    "security",
    "quality",
    "documentation",
    "maintainability",
    "performance",
]


class DriftEvent(BaseModel, frozen=True):
    """Single drift detection — emitted per dimension when the delta crosses.

    Attributes:
        dimension: ``"overall"`` for the top-level scorecard, or one of
            the six analysis dimensions.
        previous_score: Score from the prior scan.
        current_score: Score from the most recent scan.
        previous_grade: Letter grade derived from ``previous_score``.
        current_grade: Letter grade derived from ``current_score``.
    """

    dimension: DriftDimension
    previous_score: float
    current_score: float
    previous_grade: Grade
    current_grade: Grade

    @property
    def delta(self) -> float:
        """Signed change in points (current - previous). Negative = drop."""
        return self.current_score - self.previous_score


async def detect_drift(
    history: ReportStorePort,
    repo_signature: str,
    threshold_pts: int = _DEFAULT_THRESHOLD_PTS,
) -> tuple[DriftEvent, ...]:
    """Compare the latest two scans and return any DriftEvent that fired.

    Args:
        history: Wired ``ReportStorePort`` (sqlite or postgres).
        repo_signature: 32-hex blake2b of the file tree.
        threshold_pts: Absolute drop threshold per dimension. Defaults
            to 10 — the conservative "full grade drop" cut-off.

    Returns:
        Tuple of :class:`DriftEvent` (empty when no drift detected).
        The order follows: ``overall`` first, then the six dimensions
        in canonical order.
    """
    until = datetime.now(UTC)
    since = until - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    rows = await history.history(repo_signature, since=since, until=until)
    if len(rows) < 2:
        return ()
    # rows are most-recent-first per ADR-022 §6
    latest, previous = rows[0], rows[1]
    return _diff_summaries(previous=previous, latest=latest, threshold_pts=threshold_pts)


def _diff_summaries(
    *,
    previous: ReportSummary,
    latest: ReportSummary,
    threshold_pts: int,
) -> tuple[DriftEvent, ...]:
    """Build the per-dimension drift events that crossed the threshold."""
    events: list[DriftEvent] = []
    overall_event = _diff_overall(previous=previous, latest=latest, threshold_pts=threshold_pts)
    if overall_event is not None:
        events.append(overall_event)
    events.extend(_diff_dimensions(previous=previous, latest=latest, threshold_pts=threshold_pts))
    return tuple(events)


def _diff_overall(
    *,
    previous: ReportSummary,
    latest: ReportSummary,
    threshold_pts: int,
) -> DriftEvent | None:
    """Return an overall DriftEvent when the top-level score dropped beyond threshold."""
    delta = latest.overall_score - previous.overall_score
    if not _crossed_threshold(delta, threshold_pts):
        return None
    return DriftEvent(
        dimension="overall",
        previous_score=previous.overall_score,
        current_score=latest.overall_score,
        previous_grade=previous.overall_grade,
        current_grade=latest.overall_grade,
    )


def _diff_dimensions(
    *,
    previous: ReportSummary,
    latest: ReportSummary,
    threshold_pts: int,
) -> list[DriftEvent]:
    """Return one DriftEvent per dimension whose drop crossed threshold."""
    prev_by_dim = _dim_lookup(previous)
    out: list[DriftEvent] = []
    for dim_score in latest.score_card.dimensions:
        prev = prev_by_dim.get(dim_score.dimension)
        if prev is None:
            continue
        delta = dim_score.score - prev.score
        if not _crossed_threshold(delta, threshold_pts):
            continue
        out.append(
            DriftEvent(
                dimension=dim_score.dimension,
                previous_score=prev.score,
                current_score=dim_score.score,
                previous_grade=prev.grade,
                current_grade=dim_score.grade,
            )
        )
    return out


def _dim_lookup(summary: ReportSummary) -> dict[Dimension, DimensionScore]:
    """Map dimension name to its DimensionScore for O(1) lookup."""
    return {d.dimension: d for d in summary.score_card.dimensions}


def _crossed_threshold(delta: float, threshold_pts: int) -> bool:
    """Return True when ``delta`` is a drop that crossed ``threshold_pts``.

    Improvements (positive delta) never fire. Drops smaller than the
    noise floor (2 points) never fire either, even when the threshold
    is configured below it — guards against false alarms on stochastic
    self-scan noise.
    """
    if delta >= 0:
        return False
    drop = -delta
    if drop < _NOISE_FLOOR_PTS:
        return False
    return drop >= float(threshold_pts)


def render_drift_message(
    *,
    repo_name: str,
    events: tuple[DriftEvent, ...],
    report_url: str | None = None,
) -> str:
    """Compose the brand-voice markdown body of a drift notification.

    Returns an empty string when ``events`` is empty so callers can
    branch cleanly on the result.
    """
    if not events:
        return ""
    lines: list[str] = [f"`{repo_name}` drifted on the latest scan:", ""]
    lines.extend(
        f"- *{ev.dimension}*: **{ev.previous_grade}** → **{ev.current_grade}** "
        f"({ev.previous_score:.1f} → {ev.current_score:.1f}, "
        f"Δ {ev.delta:+.1f})"
        for ev in events
    )
    if report_url:
        lines.extend(["", f"<{report_url}|Open report>"])
    return "\n".join(lines)


__all__ = [
    "DriftDimension",
    "DriftEvent",
    "detect_drift",
    "render_drift_message",
]
