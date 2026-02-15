"""Tests for analysis_presenter — ScoreCard rendering and verdict generation."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from spectra.adapters.analysis_presenter import (
    GRADE_COLORS,
    _build_dimensions_table,
    _build_header_grid,
    _build_summary_text,
    _grade_text,
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


# ── Score bar ────────────────────────────────────────────────


class TestScoreBar:
    def test_full_score(self):
        bar = _score_bar(100.0)
        assert "\u2588" in bar
        assert len(bar) == 10

    def test_zero_score(self):
        bar = _score_bar(0.0)
        assert "\u2591" in bar
        assert len(bar) == 10

    def test_mid_score(self):
        bar = _score_bar(50.0)
        assert "\u2588" in bar
        assert "\u2591" in bar
        assert len(bar) == 10

    def test_quarter_score(self):
        bar = _score_bar(25.0)
        filled = bar.count("\u2588")
        empty = bar.count("\u2591")
        assert filled + empty == 10
        # 25/10 rounds to 2 or 3
        assert 2 <= filled <= 3

    def test_seventy_five_score(self):
        bar = _score_bar(75.0)
        filled = bar.count("\u2588")
        empty = bar.count("\u2591")
        assert filled + empty == 10
        # 75/10 rounds to 8
        assert filled == 8

    def test_bar_length_always_10(self):
        for score in range(0, 101, 5):
            bar = _score_bar(float(score))
            assert len(bar) == 10


# ── Grade colors ─────────────────────────────────────────────


class TestGradeColors:
    def test_all_grades_have_colors(self):
        all_grades = [
            "A+",
            "A",
            "A-",
            "B+",
            "B",
            "B-",
            "C+",
            "C",
            "C-",
            "D+",
            "D",
            "D-",
            "F",
        ]
        for grade in all_grades:
            assert grade in GRADE_COLORS

    def test_a_grades_are_green(self):
        from spectra.adapters.brand import GREEN

        for grade in ("A+", "A", "A-"):
            assert GRADE_COLORS[grade] == GREEN

    def test_b_grades_are_cyan(self):
        from spectra.adapters.brand import CYAN

        for grade in ("B+", "B", "B-"):
            assert GRADE_COLORS[grade] == CYAN

    def test_c_grades_are_amber(self):
        from spectra.adapters.brand import AMBER

        for grade in ("C+", "C", "C-"):
            assert GRADE_COLORS[grade] == AMBER

    def test_d_grades_are_red(self):
        from spectra.adapters.brand import RED

        for grade in ("D+", "D", "D-"):
            assert GRADE_COLORS[grade] == RED

    def test_f_is_red(self):
        from spectra.adapters.brand import RED

        assert GRADE_COLORS["F"] == RED


# ── Grade text ───────────────────────────────────────────────


class TestGradeText:
    def test_returns_rich_text(self):
        from rich.text import Text

        result = _grade_text("A+")
        assert isinstance(result, Text)

    def test_text_content_is_grade(self):
        result = _grade_text("B")
        assert str(result) == "B"

    def test_unknown_grade_uses_gray_fallback(self):

        result = _grade_text("Z")
        # Should not crash, uses GRAY fallback
        assert str(result) == "Z"


# ── Build header grid ────────────────────────────────────────


class TestBuildHeaderGrid:
    def test_header_grid_contains_scorecard_title(self):
        console, buf = _console_and_buf()
        grid = _build_header_grid("my-repo", "A", 92.0)
        console.print(grid)
        output = buf.getvalue()
        assert "SPECTRA SCORECARD" in output

    def test_header_grid_contains_repo_name(self):
        console, buf = _console_and_buf()
        grid = _build_header_grid("my-cool-repo", "B+", 85.0)
        console.print(grid)
        output = buf.getvalue()
        assert "my-cool-repo" in output

    def test_header_grid_contains_grade_and_score(self):
        console, buf = _console_and_buf()
        grid = _build_header_grid("repo", "C+", 74.0)
        console.print(grid)
        output = buf.getvalue()
        assert "C+" in output
        assert "74" in output


# ── Build dimensions table ───────────────────────────────────


class TestBuildDimensionsTable:
    def test_includes_all_six_dimensions(self):
        report = _make_report()
        table = _build_dimensions_table(report.score_card.dimensions)
        # Table should have 6 rows (one per dimension)
        assert table.row_count == 6

    def test_single_dimension(self):
        dim = DimensionScore(
            dimension="security",
            score=90.0,
            grade="A",
            findings_count=1,
            weight=1.0,
        )
        table = _build_dimensions_table((dim,))
        assert table.row_count == 1

    def test_empty_dimensions(self):
        table = _build_dimensions_table(())
        assert table.row_count == 0


# ── Build summary text ───────────────────────────────────────


class TestBuildSummaryText:
    def test_summary_includes_findings_count(self):
        report = _make_report()
        text = _build_summary_text(report)
        assert "18 findings" in str(text)

    def test_summary_includes_duration(self):
        report = _make_report()
        text = _build_summary_text(report)
        assert "42s" in str(text)

    def test_summary_includes_cost(self):
        report = _make_report()
        text = _build_summary_text(report)
        assert "$0.15" in str(text)

    def test_summary_includes_critical_count(self):
        report = _make_report()
        text = _build_summary_text(report)
        # No critical findings in this report
        assert "0 critical" in str(text)

    def test_summary_with_no_findings_attr(self):
        """When report lacks total_findings, falls back to len(findings)."""
        report = SimpleNamespace(
            findings=(),
            analysis_duration_seconds=10.0,
            total_cost_usd=0.05,
        )
        text = _build_summary_text(report)
        assert "0 findings" in str(text)


# ── Build verdict ────────────────────────────────────────────


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
            dimension="security",
            score=90.0,
            grade="A",
            findings_count=1,
            weight=1.0,
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

    def test_verdict_with_low_score(self):
        sc = ScoreCard(
            overall_score=40.0,
            overall_grade="F",
            dimensions=(),
            total_findings=50,
        )
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "F" in verdict
        assert "40" in verdict


# ── Present ScoreCard ────────────────────────────────────────


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
        assert "\u2717" in output
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
            "architecture",
            "security",
            "quality",
            "documentation",
            "maintainability",
            "performance",
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

    def test_scorecard_shows_all_dimension_names(self):
        console, buf = _console_and_buf()
        report = _make_report()
        present_scorecard(report, console)
        output = buf.getvalue()
        for label in DIMENSION_LABELS.values():
            assert label in output

    def test_scorecard_shows_verdict_arrow(self):
        console, buf = _console_and_buf()
        report = _make_report()
        present_scorecard(report, console)
        output = buf.getvalue()
        # The verdict line has a triangle bullet
        assert "\u25b8" in output

    def test_degraded_single_dimension(self):
        console, buf = _console_and_buf()
        report = _make_report(
            is_degraded=True,
            degraded_dimensions=("performance",),
        )
        present_scorecard(report, console)
        output = buf.getvalue()
        assert "Degraded" in output
        assert "performance" in output

    def test_scorecard_panel_rendered(self):
        """Present scorecard wraps content in a Rich Panel."""
        console, buf = _console_and_buf()
        report = _make_report()
        present_scorecard(report, console)
        output = buf.getvalue()
        # Panel has border characters
        assert "\u2500" in output or "\u2502" in output or "\u256d" in output
