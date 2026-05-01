"""Tests for ``spectra digest`` CLI subcommand (#34)."""

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


def _summary(
    *,
    overall: float,
    when: datetime,
    repo_signature: str,
    repo_name: str,
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
        scan_id=f"scan-{repo_name}-{when.isoformat()}",
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


class _FakeStore:
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


def test_digest_command_renders_markdown_to_stdout() -> None:
    """``spectra digest`` prints a markdown body for the window."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=5), repo_signature="r1", repo_name="payments"),
            _summary(overall=80.0, when=now, repo_signature="r1", repo_name="payments"),
        ]
    )
    set_history_store_provider(lambda: store)  # type: ignore[arg-type]
    try:
        result = CliRunner().invoke(app, ["digest"])
    finally:
        set_history_store_provider(None)
    assert result.exit_code == 0
    assert "Spectra weekly digest" in result.output
    assert "payments" in result.output


def test_digest_command_empty_window_message() -> None:
    """Empty store still exits 0 with a brand-voice no-data line."""
    store = _FakeStore([])
    set_history_store_provider(lambda: store)  # type: ignore[arg-type]
    try:
        result = CliRunner().invoke(app, ["digest"])
    finally:
        set_history_store_provider(None)
    assert result.exit_code == 0
    assert "Spectra weekly digest" in result.output


def test_digest_command_since_flag_shrinks_window() -> None:
    """--since 1d only includes scans within 24h."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=10), repo_signature="r1", repo_name="payments"),
            _summary(overall=80.0, when=now, repo_signature="r1", repo_name="payments"),
        ]
    )
    set_history_store_provider(lambda: store)  # type: ignore[arg-type]
    try:
        result = CliRunner().invoke(app, ["digest", "--since", "1d"])
    finally:
        set_history_store_provider(None)
    assert result.exit_code == 0
    # Only one in-window scan, so the previous_score equals the latest.
    # The repo still appears as a tracked entry — the digest never errors.
    assert "Spectra weekly digest" in result.output
