"""Tests for ``spectra history`` subcommand (#25, ADR-022).

The CLI uses the same injection pattern as ``spectra cache``: the
composition root wires a ``ReportStorePort`` provider callable, the CLI
calls it lazily so subcommands work without an Anthropic API key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from typer.testing import CliRunner

from spectra.adapters.cli_controller import (
    app,
    set_history_migrator,
    set_history_store_provider,
)
from spectra.entities.models import (
    DimensionScore,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)

runner = CliRunner()


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


_REPO_URL = "https://github.com/octocat/spoon-knife"


def _signature_for(url: str) -> str:
    """Replicate the CLI's URL→signature shape so the stub can match."""
    from hashlib import blake2b

    digest = blake2b(digest_size=16)
    digest.update(url.encode("utf-8"))
    digest.update(b"\x00")
    return digest.hexdigest()


def _summary(scan_id: str, *, ts: datetime | None = None, score: float = 82.5) -> ReportSummary:
    return ReportSummary(
        scan_id=scan_id,
        repo_signature=_signature_for(_REPO_URL),
        repo_url="https://github.com/octocat/spoon-knife",
        repo_name="spoon-knife",
        timestamp=ts or datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
        overall_score=score,
        overall_grade=score_to_grade(score),
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


class _StubStore:
    """Synchronous-friendly in-memory ReportStorePort for CLI tests."""

    def __init__(self) -> None:
        self.summaries: list[ReportSummary] = []

    async def store(self, report: ReportSummary) -> None:
        self.summaries.append(report)

    async def latest(self, repo_signature: str) -> ReportSummary | None:
        for s in reversed(self.summaries):
            if s.repo_signature == repo_signature:
                return s
        return None

    async def history(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        rows = [s for s in self.summaries if s.repo_signature == repo_signature and since <= s.timestamp < until]
        rows.sort(key=lambda s: s.timestamp, reverse=True)
        return tuple(rows)


@pytest.fixture(autouse=True)
def reset_providers() -> Any:
    """Reset CLI provider state between tests so they stay isolated."""
    set_history_store_provider(None)
    set_history_migrator(None)
    yield
    set_history_store_provider(None)
    set_history_migrator(None)


class TestHistoryLatestCommand:
    """``spectra history latest <repo>`` prints the most recent summary."""

    def test_latest_prints_summary_when_present(self) -> None:
        store = _StubStore()
        store.summaries.append(_summary("scan-A1", score=82.5))
        set_history_store_provider(lambda: store)

        result = runner.invoke(app, ["history", "latest", "https://github.com/octocat/spoon-knife"])

        assert result.exit_code == 0
        assert "scan-A1" in result.stdout
        assert "82.5" in result.stdout

    def test_latest_friendly_message_when_empty(self) -> None:
        empty_store = _StubStore()
        set_history_store_provider(lambda: empty_store)

        result = runner.invoke(app, ["history", "latest", "https://github.com/octocat/spoon-knife"])

        assert result.exit_code == 0
        assert "no scans" in result.stdout.lower()

    def test_latest_exits_one_when_provider_missing(self) -> None:
        result = runner.invoke(app, ["history", "latest", "any-repo"])

        assert result.exit_code == 1
        assert "history backend" in result.stdout.lower() or "not initialized" in result.stdout.lower()


class TestHistoryTrendCommand:
    """``spectra history trend <repo> --since 6w`` prints a per-week table."""

    def test_trend_prints_rows_in_window(self) -> None:
        store = _StubStore()
        now = datetime.now(UTC)
        store.summaries.append(_summary("scan-old", ts=now - timedelta(weeks=4), score=70.0))
        store.summaries.append(_summary("scan-new", ts=now - timedelta(days=2), score=90.0))
        set_history_store_provider(lambda: store)

        result = runner.invoke(
            app,
            ["history", "trend", "https://github.com/octocat/spoon-knife", "--since", "6w"],
        )

        assert result.exit_code == 0
        assert "scan-new" in result.stdout
        assert "90" in result.stdout

    def test_trend_friendly_message_when_no_rows(self) -> None:
        empty_store = _StubStore()
        set_history_store_provider(lambda: empty_store)

        result = runner.invoke(
            app,
            ["history", "trend", "https://github.com/octocat/spoon-knife", "--since", "1w"],
        )

        assert result.exit_code == 0
        assert "no scans" in result.stdout.lower()

    def test_trend_rejects_invalid_duration(self) -> None:
        empty_store = _StubStore()
        set_history_store_provider(lambda: empty_store)

        result = runner.invoke(
            app,
            ["history", "trend", "any-repo", "--since", "6q"],
        )

        assert result.exit_code != 0
        assert "invalid" in result.stdout.lower() or "duration" in result.stdout.lower()


class TestHistoryMigrateCommand:
    """``spectra history migrate`` applies pending migrations to the chosen backend."""

    def test_migrate_calls_injected_runner(self) -> None:
        called: list[str] = []

        def _runner() -> tuple[str, ...]:
            called.append("ran")
            return ("001_initial_schema",)

        set_history_migrator(_runner)

        result = runner.invoke(app, ["history", "migrate"])

        assert result.exit_code == 0
        assert called == ["ran"]
        assert "001_initial_schema" in result.stdout

    def test_migrate_reports_already_up_to_date(self) -> None:
        set_history_migrator(lambda: ())

        result = runner.invoke(app, ["history", "migrate"])

        assert result.exit_code == 0
        assert "up to date" in result.stdout.lower() or "no pending" in result.stdout.lower()

    def test_migrate_exits_one_when_runner_missing(self) -> None:
        result = runner.invoke(app, ["history", "migrate"])

        assert result.exit_code == 1
