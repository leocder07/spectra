"""Tests for ``ReportSummary`` — Layer-1 frozen entity for trend queries (#25).

ADR-022: the history store persists per-scan summaries (no findings,
no code, no PII) so trend / portfolio / drift queries do not have to
re-load full reports. Equality, immutability, and round-trip JSON are
all part of the entity contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from spectra.entities.models import (
    DimensionScore,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)


def _scorecard() -> ScoreCard:
    """Build a minimal six-dimension scorecard for tests."""
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


def _build_summary(**overrides: object) -> ReportSummary:
    """Compose a default ReportSummary; tests pass overrides only for what they vary."""
    base: dict[str, object] = {
        "scan_id": "0190a8b8-7b1a-7b1c-9c2d-7b1a7b1c9c2d",
        "repo_signature": "deadbeef" * 4,
        "repo_url": "https://github.com/octocat/spoon-knife",
        "repo_name": "spoon-knife",
        "timestamp": datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
        "overall_score": 82.5,
        "overall_grade": "B",
        "score_card": _scorecard(),
        "total_findings": 18,
        "finding_count_by_severity": {"critical": 1, "high": 4, "medium": 8, "low": 3, "info": 2},
        "finding_count_by_dimension": {
            "architecture": 3,
            "security": 2,
            "quality": 5,
            "documentation": 4,
            "maintainability": 3,
            "performance": 1,
        },
        "model_versions": "claude-opus-4-7",
        "prompt_versions": "abcd1234",
        "spectra_version": "0.7.0",
        "is_degraded": False,
        "validation_status": "validated",
        "duration_seconds": 142.7,
        "cost_usd": 0.42,
    }
    base.update(overrides)
    return ReportSummary(**base)  # type: ignore[arg-type]


class TestReportSummaryConstruction:
    """The entity validates inputs and freezes them."""

    def test_constructs_with_minimum_valid_payload(self) -> None:
        summary = _build_summary()

        assert summary.scan_id == "0190a8b8-7b1a-7b1c-9c2d-7b1a7b1c9c2d"
        assert summary.overall_score == 82.5
        assert summary.overall_grade == "B"
        assert summary.repo_signature == "deadbeef" * 4

    def test_is_frozen(self) -> None:
        summary = _build_summary()

        with pytest.raises(ValidationError):
            summary.overall_score = 99.9  # type: ignore[misc]

    def test_score_outside_zero_to_hundred_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _build_summary(overall_score=120.0)

    def test_negative_finding_counts_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _build_summary(total_findings=-1)


class TestReportSummaryRoundTrip:
    """JSON round-trip preserves every field — required for SQL persistence."""

    def test_round_trip_preserves_all_fields(self) -> None:
        original = _build_summary()
        rebuilt = ReportSummary.model_validate_json(original.model_dump_json())

        assert rebuilt == original

    def test_round_trip_preserves_severity_counts(self) -> None:
        original = _build_summary(
            finding_count_by_severity={
                "critical": 7,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
            }
        )
        rebuilt = ReportSummary.model_validate_json(original.model_dump_json())

        assert rebuilt.finding_count_by_severity["critical"] == 7


class TestReportSummaryFromAnalysisReport:
    """The factory builds a summary from the larger report — the privacy boundary
    in ADR-022 §1: no findings, no code excerpts, no PII leak into history."""

    def test_from_report_drops_findings(self, sample_scorecard: ScoreCard) -> None:
        from spectra.entities.models import AnalysisReport, FileLocation, Finding

        report = AnalysisReport(
            repo_url="https://github.com/octocat/spoon-knife",
            repo_name="spoon-knife",
            score_card=sample_scorecard,
            findings=(
                Finding(
                    id="SEC-001",
                    dimension="security",
                    severity="high",
                    title="t",
                    description="d",
                    location=FileLocation(file_path="src/main.py", line_start=10),
                    recommendation="fix",
                    agent_role="security",
                    confidence=0.9,
                ),
            ),
            analysis_duration_seconds=10.0,
            total_tokens_used=100,
            total_cost_usd=0.01,
            agents_used=("security",),
        )

        summary = ReportSummary.from_report(
            report=report,
            scan_id="0190a8b8-7b1a-7b1c-9c2d-7b1a7b1c9c2d",
            repo_signature="deadbeef" * 4,
            timestamp=datetime(2026, 4, 30, tzinfo=UTC),
            model_versions="claude-opus-4-7",
            prompt_versions="abcd",
            spectra_version="0.7.0",
        )

        assert summary.overall_score == sample_scorecard.overall_score
        assert summary.total_findings == 1
        assert summary.finding_count_by_severity["high"] == 1
        assert summary.finding_count_by_dimension["security"] == 1
        # Privacy boundary — no field on the summary carries the original
        # finding text or location. The test confirms by checking the
        # serialised form contains no finding title or path substring.
        payload = summary.model_dump_json()
        assert "src/main.py" not in payload
        assert "SEC-001" not in payload
