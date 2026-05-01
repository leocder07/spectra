"""Tests for the weekly digest use case (#34).

Reads the history store for a window, aggregates per-repo deltas, and
returns a Digest value object that the CLI / NotifierPort renders into
either stdout (markdown) or a notifier message.
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
from spectra.use_cases.digest import (
    Digest,
    RepoDelta,
    compose_weekly_digest,
    render_digest_markdown,
)

# ── Fixture helpers ─────────────────────────────────────────


def _summary(
    *,
    overall: float,
    when: datetime,
    repo_signature: str,
    repo_name: str = "payments",
    findings: int = 0,
) -> ReportSummary:
    dims = tuple(
        DimensionScore(
            dimension=dim,  # type: ignore[arg-type]
            score=overall,
            grade=score_to_grade(overall),
            findings_count=0,
            weight=1 / 6,
        )
        for dim in (
            "architecture",
            "security",
            "quality",
            "documentation",
            "maintainability",
            "performance",
        )
    )
    return ReportSummary(
        scan_id=f"s-{repo_name}-{when.isoformat()}",
        repo_signature=repo_signature,
        repo_url=f"https://example.com/{repo_name}",
        repo_name=repo_name,
        timestamp=when,
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        score_card=ScoreCard(
            overall_score=overall,
            overall_grade=score_to_grade(overall),
            dimensions=dims,
            total_findings=findings,
        ),
        total_findings=findings,
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


class _FakeStore:
    """In-memory ReportStorePort. Holds many repos."""

    def __init__(self, summaries: list[ReportSummary]) -> None:
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

    async def list_signatures_in_window(
        self,
        since: datetime,
        until: datetime,
    ) -> tuple[str, ...]:
        seen: set[str] = set()
        for s in self._summaries:
            if since <= s.timestamp < until:
                seen.add(s.repo_signature)
        return tuple(seen)


# ── Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compose_weekly_digest_aggregates_per_repo() -> None:
    """Digest contains one RepoDelta per repo seen in the window."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7), repo_signature="r1", repo_name="payments"),
            _summary(overall=80.0, when=now, repo_signature="r1", repo_name="payments"),
            _summary(overall=70.0, when=now - timedelta(days=7), repo_signature="r2", repo_name="auth"),
            _summary(overall=85.0, when=now, repo_signature="r2", repo_name="auth"),
        ]
    )
    digest = await compose_weekly_digest(history=store, window_days=14)
    assert isinstance(digest, Digest)
    repo_names = {d.repo_name for d in digest.repos}
    assert repo_names == {"payments", "auth"}


@pytest.mark.asyncio
async def test_compose_weekly_digest_sorts_worst_first() -> None:
    """Worst-trending repos sort earliest in the digest."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7), repo_signature="r1", repo_name="payments"),
            _summary(overall=70.0, when=now, repo_signature="r1", repo_name="payments"),  # -22
            _summary(overall=85.0, when=now - timedelta(days=7), repo_signature="r2", repo_name="auth"),
            _summary(overall=82.0, when=now, repo_signature="r2", repo_name="auth"),  # -3
        ]
    )
    digest = await compose_weekly_digest(history=store, window_days=14)
    # Worst-first ordering — payments (-22) before auth (-3).
    worst_names = [d.repo_name for d in digest.worst]
    assert worst_names.index("payments") < worst_names.index("auth")


@pytest.mark.asyncio
async def test_compose_weekly_digest_separates_best_and_worst() -> None:
    """Improvements show up in ``best``; drops in ``worst``."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=70.0, when=now - timedelta(days=7), repo_signature="r1", repo_name="payments"),
            _summary(overall=92.0, when=now, repo_signature="r1", repo_name="payments"),  # +22
            _summary(overall=92.0, when=now - timedelta(days=7), repo_signature="r2", repo_name="auth"),
            _summary(overall=70.0, when=now, repo_signature="r2", repo_name="auth"),  # -22
        ]
    )
    digest = await compose_weekly_digest(history=store, window_days=14)
    best_names = {d.repo_name for d in digest.best}
    worst_names = {d.repo_name for d in digest.worst}
    assert "payments" in best_names
    assert "auth" in worst_names


@pytest.mark.asyncio
async def test_compose_weekly_digest_empty_when_no_history() -> None:
    """Empty store → empty digest, no error."""
    store = _FakeStore([])
    digest = await compose_weekly_digest(history=store, window_days=14)
    assert digest.repos == ()
    assert digest.best == ()
    assert digest.worst == ()


# ── Markdown rendering ──────────────────────────────────────


def test_render_digest_markdown_includes_brand_voice_header() -> None:
    """Rendered digest contains the Spectra header and per-section labels."""
    digest = Digest(
        repos=(
            RepoDelta(
                repo_name="payments",
                latest_score=80.0,
                previous_score=92.0,
                latest_grade="B",
                previous_grade="A",
                latest_findings=8,
            ),
        ),
        worst=(
            RepoDelta(
                repo_name="payments",
                latest_score=80.0,
                previous_score=92.0,
                latest_grade="B",
                previous_grade="A",
                latest_findings=8,
            ),
        ),
        best=(),
        window_days=7,
    )
    md = render_digest_markdown(digest)
    assert "Spectra weekly digest" in md
    assert "payments" in md
    assert "A" in md
    assert "B" in md


def test_render_digest_markdown_handles_empty_digest() -> None:
    md = render_digest_markdown(Digest(repos=(), worst=(), best=(), window_days=7))
    assert "Spectra weekly digest" in md
    assert "No scans" in md
