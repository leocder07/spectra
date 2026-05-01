"""Tests for ``SqliteReportStoreAdapter`` — the default ``ReportStorePort`` impl (#25).

ADR-022: SQLite is the single-user fallback for the history store. Same
``ReportStorePort`` shape as the Postgres adapter; same migrations
applied; runs in-process with zero infra.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spectra.entities.models import (
    DimensionScore,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)
from spectra.infrastructure.history.sqlite_report_store import (
    SqliteReportStoreAdapter,
    apply_migrations,
)


def _scorecard(overall: float = 82.5) -> ScoreCard:
    dims = (
        DimensionScore(dimension="architecture", score=85.0, grade="B", findings_count=3, weight=0.25),
        DimensionScore(
            dimension="security", score=overall, grade=score_to_grade(overall), findings_count=2, weight=0.25
        ),
        DimensionScore(dimension="quality", score=78.0, grade="C+", findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C-", findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    weighted = sum(d.score * d.weight for d in dims)
    return ScoreCard(
        overall_score=weighted,
        overall_grade=score_to_grade(weighted),
        dimensions=dims,
        total_findings=18,
    )


def _summary(
    *,
    scan_id: str = "0190a8b8-7b1a-7b1c-9c2d-7b1a7b1c9c2d",
    repo_signature: str = "deadbeef" * 4,
    repo_url: str = "https://github.com/octocat/spoon-knife",
    timestamp: datetime | None = None,
    overall_score: float = 82.5,
) -> ReportSummary:
    return ReportSummary(
        scan_id=scan_id,
        repo_signature=repo_signature,
        repo_url=repo_url,
        repo_name="spoon-knife",
        timestamp=timestamp or datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
        overall_score=overall_score,
        overall_grade=score_to_grade(overall_score),
        score_card=_scorecard(overall_score),
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
def store(tmp_path: Path) -> SqliteReportStoreAdapter:
    """Build a fresh sqlite report store for each test."""
    db_path = tmp_path / "history.db"
    apply_migrations(db_path)
    return SqliteReportStoreAdapter(db_path=db_path)


class TestSqliteReportStoreApplyMigrations:
    """Migrations create the expected tables on a fresh DB."""

    def test_apply_creates_reports_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        apply_migrations(db_path)
        # Reopen with stdlib sqlite3 to inspect the schema.
        import sqlite3

        with sqlite3.connect(str(db_path)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "reports" in tables
        assert "schema_migrations" in tables

    def test_apply_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        apply_migrations(db_path)
        # Second call must not error.
        apply_migrations(db_path)


@pytest.mark.asyncio
class TestSqliteReportStoreStoreAndLatest:
    """The store + latest round-trip is the smallest end-to-end path."""

    async def test_store_then_latest_returns_same_summary(self, store: SqliteReportStoreAdapter) -> None:
        original = _summary()
        await store.store(original)

        latest = await store.latest(original.repo_signature)

        assert latest is not None
        assert latest.scan_id == original.scan_id
        assert latest.overall_score == original.overall_score

    async def test_latest_returns_none_when_no_scan(self, store: SqliteReportStoreAdapter) -> None:
        result = await store.latest("never-seen")
        assert result is None

    async def test_latest_returns_most_recent_for_repo(self, store: SqliteReportStoreAdapter) -> None:
        older = _summary(
            scan_id="01-aaaa",
            timestamp=datetime(2026, 4, 1, tzinfo=UTC),
            overall_score=70.0,
        )
        newer = _summary(
            scan_id="01-bbbb",
            timestamp=datetime(2026, 4, 30, tzinfo=UTC),
            overall_score=90.0,
        )
        await store.store(older)
        await store.store(newer)

        latest = await store.latest(older.repo_signature)

        assert latest is not None
        assert latest.scan_id == "01-bbbb"
        assert latest.overall_score == 90.0

    async def test_store_is_idempotent_on_same_scan_id(self, store: SqliteReportStoreAdapter) -> None:
        s = _summary()
        await store.store(s)
        await store.store(s)  # Latest write wins; no error on duplicate scan_id.

        latest = await store.latest(s.repo_signature)
        assert latest is not None
        assert latest.scan_id == s.scan_id


@pytest.mark.asyncio
class TestSqliteReportStoreHistory:
    """Range queries return ordered, half-open windows."""

    async def test_history_returns_summaries_in_window(self, store: SqliteReportStoreAdapter) -> None:
        a = _summary(scan_id="01-a", timestamp=datetime(2026, 4, 1, tzinfo=UTC), overall_score=70.0)
        b = _summary(scan_id="01-b", timestamp=datetime(2026, 4, 15, tzinfo=UTC), overall_score=80.0)
        c = _summary(scan_id="01-c", timestamp=datetime(2026, 4, 28, tzinfo=UTC), overall_score=90.0)
        for s in (a, b, c):
            await store.store(s)

        result = await store.history(
            a.repo_signature,
            since=datetime(2026, 4, 10, tzinfo=UTC),
            until=datetime(2026, 4, 30, tzinfo=UTC),
        )

        assert [r.scan_id for r in result] == ["01-c", "01-b"]  # most recent first

    async def test_history_excludes_other_repos(self, store: SqliteReportStoreAdapter) -> None:
        repo_a = _summary(scan_id="A1", repo_signature="aaaa" * 8)
        repo_b = _summary(scan_id="B1", repo_signature="bbbb" * 8)
        await store.store(repo_a)
        await store.store(repo_b)

        result = await store.history(
            repo_a.repo_signature,
            since=datetime(2025, 1, 1, tzinfo=UTC),
            until=datetime(2027, 1, 1, tzinfo=UTC),
        )

        assert len(result) == 1
        assert result[0].scan_id == "A1"

    async def test_history_empty_window_returns_empty_tuple(self, store: SqliteReportStoreAdapter) -> None:
        s = _summary(timestamp=datetime(2026, 1, 1, tzinfo=UTC))
        await store.store(s)

        result = await store.history(
            s.repo_signature,
            since=datetime(2026, 5, 1, tzinfo=UTC),
            until=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert result == ()

    async def test_history_until_is_exclusive(self, store: SqliteReportStoreAdapter) -> None:
        ts = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
        s = _summary(timestamp=ts)
        await store.store(s)

        # until exactly equals the timestamp — must exclude.
        result = await store.history(
            s.repo_signature,
            since=ts - timedelta(days=1),
            until=ts,
        )

        assert result == ()


@pytest.mark.asyncio
class TestSqliteReportStorePreservesSummaryFields:
    """Round-trip through SQL preserves the entire ReportSummary contract."""

    async def test_round_trip_preserves_severity_and_dimension_counts(self, store: SqliteReportStoreAdapter) -> None:
        original = _summary()
        await store.store(original)

        latest = await store.latest(original.repo_signature)

        assert latest is not None
        assert latest.finding_count_by_severity == original.finding_count_by_severity
        assert latest.finding_count_by_dimension == original.finding_count_by_dimension
        assert latest.score_card == original.score_card
