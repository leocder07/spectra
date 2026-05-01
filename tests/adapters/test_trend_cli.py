"""Tests for ``spectra trend`` CLI subcommand (#27)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from spectra.adapters.cli_controller import (
    app,
    set_history_store_provider,
)
from spectra.entities.models import (
    DimensionScore,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)


class _FakeHistoryStore:
    def __init__(self, summaries: list[ReportSummary]) -> None:
        self._summaries = sorted(summaries, key=lambda s: s.timestamp, reverse=True)

    async def store(self, report: ReportSummary) -> None:
        self._summaries.append(report)

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


def _summary(*, overall: float, when: datetime) -> ReportSummary:
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
        scan_id=f"scan-{when.isoformat()}",
        repo_signature="abc" + "0" * 29,  # 32 hex
        repo_url="https://example.com/payments",
        repo_name="payments",
        timestamp=when,
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        score_card=ScoreCard(
            overall_score=overall,
            overall_grade=score_to_grade(overall),
            dimensions=dims,
            total_findings=0,
        ),
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


def test_trend_command_renders_table_for_two_scans() -> None:
    """``spectra trend <repo>`` prints one row per scan."""
    now = datetime.now(UTC)
    store = _FakeHistoryStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),
            _summary(overall=80.0, when=now),
        ]
    )
    set_history_store_provider(lambda: store)  # type: ignore[arg-type]
    try:
        result = CliRunner().invoke(app, ["trend", "abc" + "0" * 29])
    finally:
        set_history_store_provider(None)
    assert result.exit_code == 0
    # Both grades show up in the rendered table.
    assert "92" in result.output
    assert "80" in result.output


def test_trend_command_no_data_prints_friendly_message() -> None:
    """No scans → brand-voice ▸ message, exit 0."""
    store = _FakeHistoryStore([])
    set_history_store_provider(lambda: store)  # type: ignore[arg-type]
    try:
        result = CliRunner().invoke(app, ["trend", "abc" + "0" * 29])
    finally:
        set_history_store_provider(None)
    assert result.exit_code == 0
    assert "No scans" in result.output


def test_trend_command_explain_flag_prints_drift_when_present() -> None:
    """With --explain, the command surfaces drift detection results."""
    now = datetime.now(UTC)
    store = _FakeHistoryStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),
            _summary(overall=78.0, when=now),  # 14pt drop
        ]
    )
    set_history_store_provider(lambda: store)  # type: ignore[arg-type]
    try:
        result = CliRunner().invoke(app, ["trend", "abc" + "0" * 29, "--explain"])
    finally:
        set_history_store_provider(None)
    assert result.exit_code == 0
    # Explain block surfaces the drift event by name.
    assert "drift" in result.output.lower() or "overall" in result.output.lower()
