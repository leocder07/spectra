"""Real-Postgres integration test for the history store (#25, ADR-022).

Skipped automatically unless ``SPECTRA_POSTGRES_URL`` is set.

To run locally::

    docker run --rm -d --name spectra-pg-test \\
        -e POSTGRES_USER=spectra -e POSTGRES_PASSWORD=spectra \\
        -e POSTGRES_DB=spectra_history -p 55432:5432 postgres:16
    SPECTRA_POSTGRES_URL=postgresql://spectra:spectra@localhost:55432/spectra_history \\
        pytest tests/integration/test_postgres_history_integration.py -m integration

In CI we add ``-m "not integration"`` by default so this is opt-in.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

from spectra.entities.models import (
    DimensionScore,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)

POSTGRES_URL = os.environ.get("SPECTRA_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="SPECTRA_POSTGRES_URL not set — Postgres integration test skipped",
    ),
]


def _scorecard() -> ScoreCard:
    dims = (
        DimensionScore(dimension="architecture", score=85.0, grade="B", findings_count=3, weight=0.25),
        DimensionScore(dimension="security", score=90.0, grade="A-", findings_count=2, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="C+", findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C-", findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    overall = sum(d.score * d.weight for d in dims)
    return ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dims,
        total_findings=18,
    )


def _summary(repo_signature: str, *, scan_id: str | None = None, ts: datetime | None = None) -> ReportSummary:
    return ReportSummary(
        scan_id=scan_id or str(uuid.uuid4()),
        repo_signature=repo_signature,
        repo_url="https://github.com/octocat/spoon-knife",
        repo_name="spoon-knife",
        timestamp=ts or datetime.now(UTC),
        overall_score=82.5,
        overall_grade="B",
        score_card=_scorecard(),
        total_findings=18,
        finding_count_by_severity={"critical": 1, "high": 4, "medium": 8, "low": 3, "info": 2},
        finding_count_by_dimension={
            "architecture": 3,
            "security": 2,
            "quality": 5,
            "documentation": 4,
            "maintainability": 3,
            "performance": 1,
        },
        model_versions="claude-opus-4-7",
        prompt_versions="abcd1234",
        spectra_version="0.7.0",
        is_degraded=False,
        validation_status="validated",
        duration_seconds=142.7,
        cost_usd=0.42,
    )


@pytest.fixture
def pg_store() -> object:
    """Build a PostgresReportStoreAdapter against the live test DB."""
    from spectra.infrastructure.history.postgres_report_store import (
        PostgresReportStoreAdapter,
        apply_postgres_migrations,
        build_pool,
    )

    pool = build_pool(POSTGRES_URL)
    apply_postgres_migrations(pool=pool)
    return PostgresReportStoreAdapter(pool=pool)


@pytest.mark.asyncio
async def test_postgres_round_trip_store_and_latest(pg_store: object) -> None:
    """The Postgres adapter satisfies the same contract as the SQLite adapter."""
    sig = uuid.uuid4().hex * 2  # 64-char unique signature per test run
    s = _summary(sig)

    await pg_store.store(s)  # type: ignore[attr-defined]
    latest = await pg_store.latest(sig)  # type: ignore[attr-defined]

    assert latest is not None
    assert latest.scan_id == s.scan_id


@pytest.mark.asyncio
async def test_postgres_history_window_query(pg_store: object) -> None:
    """Time-window queries return the right ordering and exclude out-of-range rows."""
    sig = uuid.uuid4().hex * 2
    older = _summary(sig, ts=datetime(2025, 1, 1, tzinfo=UTC))
    newer = _summary(sig, ts=datetime(2026, 4, 30, tzinfo=UTC))

    await pg_store.store(older)  # type: ignore[attr-defined]
    await pg_store.store(newer)  # type: ignore[attr-defined]

    result = await pg_store.history(  # type: ignore[attr-defined]
        sig,
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2027, 1, 1, tzinfo=UTC),
    )

    assert len(result) == 1
    assert result[0].scan_id == newer.scan_id
