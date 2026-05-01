"""Tests for ``detect_drift`` — the #27 use case.

Compares the most recent two scans for a repo and emits a ``DriftEvent``
per dimension when the delta exceeds the configured threshold (or the
overall grade dropped a full letter). Returns ``()`` when no drift.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectra.entities.models import (
    DimensionScore,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)
from spectra.use_cases.drift_detection import DriftEvent, detect_drift

# ── In-memory ReportStore stub ───────────────────────────────


class _StoreStub:
    def __init__(self, summaries: list[ReportSummary]) -> None:
        # most-recent-first to mirror the real store contract
        self._summaries = sorted(summaries, key=lambda s: s.timestamp, reverse=True)

    async def store(self, report: ReportSummary) -> None:
        self._summaries.append(report)
        self._summaries.sort(key=lambda s: s.timestamp, reverse=True)

    async def latest(self, repo_signature: str) -> ReportSummary | None:
        for s in self._summaries:
            if s.repo_signature == repo_signature:
                return s
        return None

    async def history(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        return tuple(s for s in self._summaries if s.repo_signature == repo_signature and since <= s.timestamp < until)


# ── Helpers to build summaries ──────────────────────────────


def _summary(
    *,
    overall: float,
    dim_overrides: dict[str, float] | None = None,
    when: datetime,
    repo_signature: str = "abc123",
    scan_id: str | None = None,
) -> ReportSummary:
    """Build a ``ReportSummary`` whose dimensions all sit at ``overall``.

    ``dim_overrides`` lets a test perturb individual dimensions without
    rebuilding the whole scorecard from scratch.
    """
    dims: list[DimensionScore] = []
    for dim in (
        "architecture",
        "security",
        "quality",
        "documentation",
        "maintainability",
        "performance",
    ):
        score = (dim_overrides or {}).get(dim, overall)
        dims.append(
            DimensionScore(
                dimension=dim,  # type: ignore[arg-type]
                score=score,
                grade=score_to_grade(score),
                findings_count=0,
                weight=1.0 / 6,
            )
        )
    score_card = ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=tuple(dims),
        total_findings=0,
    )
    return ReportSummary(
        scan_id=scan_id or f"scan-{when.isoformat()}",
        repo_signature=repo_signature,
        repo_url="https://example.com/payments",
        repo_name="payments",
        timestamp=when,
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        score_card=score_card,
        total_findings=0,
        finding_count_by_severity={},
        finding_count_by_dimension={},
        model_versions="opus-4.7",
        prompt_versions="p1",
        spectra_version="0.7.0",
        is_degraded=False,
        validation_status="validated",
        duration_seconds=10.0,
        cost_usd=0.5,
    )


# ── Empty / single-scan cases ───────────────────────────────


@pytest.mark.asyncio
async def test_no_drift_when_history_empty() -> None:
    store = _StoreStub([])
    events = await detect_drift(store, repo_signature="abc123")
    assert events == ()


@pytest.mark.asyncio
async def test_no_drift_when_only_one_scan() -> None:
    """Single scan = first scan ever; nothing to compare against."""
    now = datetime.now(UTC)
    store = _StoreStub([_summary(overall=92.0, when=now)])
    events = await detect_drift(store, repo_signature="abc123")
    assert events == ()


# ── Threshold semantics ─────────────────────────────────────


@pytest.mark.asyncio
async def test_no_drift_when_delta_below_threshold() -> None:
    """A 4-point overall drop below the default 10pt threshold = no event."""
    now = datetime.now(UTC)
    store = _StoreStub(
        [
            _summary(overall=88.0, when=now - timedelta(days=7)),
            _summary(overall=92.0, when=now),  # latest is BETTER
        ]
    )
    events = await detect_drift(store, repo_signature="abc123")
    assert events == ()


@pytest.mark.asyncio
async def test_drift_fires_on_overall_drop_above_threshold() -> None:
    """A 12-pt overall drop above the default 10pt threshold = DriftEvent."""
    now = datetime.now(UTC)
    store = _StoreStub(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),  # previous
            _summary(overall=80.0, when=now),  # latest — dropped 12 points
        ]
    )
    events = await detect_drift(store, repo_signature="abc123")
    assert len(events) >= 1
    overall = next(e for e in events if e.dimension == "overall")
    assert overall.previous_score == pytest.approx(92.0)
    assert overall.current_score == pytest.approx(80.0)
    assert overall.delta == pytest.approx(-12.0)
    assert overall.previous_grade == "A"
    assert overall.current_grade == "B"


@pytest.mark.asyncio
async def test_threshold_is_configurable() -> None:
    """A 6-pt drop fires when --threshold-pts=5; not when default 10."""
    now = datetime.now(UTC)
    store = _StoreStub(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),
            _summary(overall=86.0, when=now),
        ]
    )
    none = await detect_drift(store, repo_signature="abc123")
    assert all(e.dimension != "overall" for e in none)
    fired = await detect_drift(store, repo_signature="abc123", threshold_pts=5)
    assert any(e.dimension == "overall" for e in fired)


# ── Per-dimension drift ─────────────────────────────────────


@pytest.mark.asyncio
async def test_drift_fires_per_dimension_when_dim_drops() -> None:
    """A single-dimension 15pt drop fires that dim's event regardless of overall."""
    now = datetime.now(UTC)
    store = _StoreStub(
        [
            _summary(
                overall=92.0,
                dim_overrides={"security": 95.0},
                when=now - timedelta(days=7),
            ),
            _summary(
                overall=92.0,
                dim_overrides={"security": 78.0},
                when=now,
            ),
        ]
    )
    events = await detect_drift(store, repo_signature="abc123")
    sec = next(e for e in events if e.dimension == "security")
    assert sec.previous_score == pytest.approx(95.0)
    assert sec.current_score == pytest.approx(78.0)


# ── Improvements never fire ─────────────────────────────────


@pytest.mark.asyncio
async def test_improvements_do_not_fire_drift() -> None:
    """Score going UP is never drift, even by a huge margin."""
    now = datetime.now(UTC)
    store = _StoreStub(
        [
            _summary(overall=70.0, when=now - timedelta(days=7)),
            _summary(overall=95.0, when=now),  # +25 — pure win
        ]
    )
    events = await detect_drift(store, repo_signature="abc123")
    assert events == ()


# ── DriftEvent shape ────────────────────────────────────────


def test_drift_event_is_frozen() -> None:
    event = DriftEvent(
        dimension="overall",
        previous_score=92.0,
        current_score=80.0,
        previous_grade="A",
        current_grade="B",
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        event.previous_score = 0.0  # type: ignore[misc]


def test_drift_event_delta_is_negative_signed() -> None:
    event = DriftEvent(
        dimension="overall",
        previous_score=92.0,
        current_score=80.0,
        previous_grade="A",
        current_grade="B",
    )
    assert event.delta == pytest.approx(-12.0)
