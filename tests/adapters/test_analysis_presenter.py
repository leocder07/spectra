"""Tests for analysis_presenter — ScoreCard rendering and verdict generation."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from spectra.adapters.analysis_presenter import (
    _build_dimensions_table,
    _score_bar,
    present_scorecard,
)
from spectra.adapters.brand import DIMENSION_LABELS, build_verdict
from spectra.entities.models import DimensionScore, ScoreCard, score_to_grade


def _console_and_buf() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, force_terminal=True, width=120), buf


def _make_report(
    *,
    overall: float = 83.0,
    is_degraded: bool = False,
    degraded_dimensions: tuple[str, ...] = (),
) -> SimpleNamespace:
    """Build a fake AnalysisReport-shaped object."""
    dims = (
        DimensionScore(dimension="architecture", score=90.0, grade="A", findings_count=2, weight=0.25),
        DimensionScore(dimension="security", score=85.0, grade="B+", findings_count=3, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="B-", findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C", findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    sc = ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dims,
        total_findings=18,
    )
    return SimpleNamespace(
        score_card=sc,
        repo_name="test/repo",
        findings=(),
        total_findings=18,
        analysis_duration_seconds=42.0,
        total_cost_usd=0.15,
        is_degraded=is_degraded,
        degraded_dimensions=degraded_dimensions,
    )


class TestScoreBar:
    def test_full_score(self):
        bar = _score_bar(100.0)
        assert "█" in bar
        assert len(bar) == 10

    def test_zero_score(self):
        bar = _score_bar(0.0)
        assert "░" in bar
        assert len(bar) == 10

    def test_mid_score(self):
        bar = _score_bar(50.0)
        assert "█" in bar
        assert "░" in bar
        assert len(bar) == 10


class TestBuildVerdict:
    def test_verdict_with_all_dimensions(self):
        report = _make_report()
        verdict = build_verdict(report)
        assert "B+" in verdict
        assert "83" in verdict
        assert "architecture" in verdict.lower()

    def test_verdict_no_scorecard(self):
        report = SimpleNamespace(score_card=None)
        assert build_verdict(report) == ""

    def test_verdict_no_dimensions(self):
        sc = ScoreCard(
            overall_score=80.0,
            overall_grade="B",
            dimensions=(),
            total_findings=0,
        )
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "B" in verdict
        assert "80" in verdict

    def test_verdict_single_dimension(self):
        dim = DimensionScore(
            dimension="security", score=90.0, grade="A",
            findings_count=1, weight=1.0,
        )
        sc = ScoreCard(
            overall_score=90.0,
            overall_grade="A",
            dimensions=(dim,),
            total_findings=1,
        )
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "A" in verdict


class TestBuildDimensionsTable:
    def test_includes_all_six_dimensions(self):
        report = _make_report()
        table = _build_dimensions_table(report.score_card.dimensions)
        # Table should have 6 rows (one per dimension)
        assert table.row_count == 6


class TestPresentScorecard:
    def test_renders_without_error(self):
        console, buf = _console_and_buf()
        report = _make_report()
        present_scorecard(report, console)
        output = buf.getvalue()
        assert "SPECTRA SCORECARD" in output
        assert "test/repo" in output

    def test_no_scorecard_shows_error(self):
        console, buf = _console_and_buf()
        report = SimpleNamespace(score_card=None)
        present_scorecard(report, console)
        output = buf.getvalue()
        assert "✗" in output
        assert "No scorecard" in output

    def test_degraded_mode_shows_warning(self):
        console, buf = _console_and_buf()
        report = _make_report(is_degraded=True, degraded_dimensions=("security", "quality"))
        present_scorecard(report, console)
        output = buf.getvalue()
        assert "Degraded" in output
        assert "security" in output
        assert "quality" in output

    def test_non_degraded_no_warning(self):
        console, buf = _console_and_buf()
        report = _make_report(is_degraded=False)
        present_scorecard(report, console)
        output = buf.getvalue()
        assert "Degraded" not in output

    def test_dimension_labels_cover_all(self):
        expected = {
            "architecture", "security", "quality",
            "documentation", "maintainability", "performance",
        }
        assert set(DIMENSION_LABELS.keys()) == expected

    def test_grade_a_scorecard(self):
        console, buf = _console_and_buf()
        report = _make_report(overall=95.0)
        present_scorecard(report, console)
        output = buf.getvalue()
        assert "A+" in output

    def test_grade_f_scorecard(self):
        console, buf = _console_and_buf()
        report = _make_report(overall=40.0)
        present_scorecard(report, console)
        output = buf.getvalue()
        assert "F" in output
