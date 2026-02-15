"""Tests for brand utilities — dimension labels, verdict builder, brand constants."""

from __future__ import annotations

from types import SimpleNamespace

from spectra.adapters.brand import (
    AMBER,
    CYAN,
    DIMENSION_LABELS,
    GRAY,
    GREEN,
    RED,
    VIOLET,
    build_verdict,
    dim_label,
)
from spectra.entities.models import DimensionScore, ScoreCard, score_to_grade

# ── Brand color constants ────────────────────────────────────


class TestBrandColors:
    def test_violet_hex(self):
        assert VIOLET == "#7C3AED"

    def test_amber_hex(self):
        assert AMBER == "#F59E0B"

    def test_red_hex(self):
        assert RED == "#EF4444"

    def test_green_hex(self):
        assert GREEN == "#22C55E"

    def test_cyan_hex(self):
        assert CYAN == "#06B6D4"

    def test_gray_hex(self):
        assert GRAY == "#6B7280"

    def test_all_colors_are_hex(self):
        for color in (VIOLET, AMBER, RED, GREEN, CYAN, GRAY):
            assert color.startswith("#")
            assert len(color) == 7


# ── Dimension labels ─────────────────────────────────────────


class TestDimensionLabels:
    def test_architecture_label(self):
        assert DIMENSION_LABELS["architecture"] == "Architecture"

    def test_security_label(self):
        assert DIMENSION_LABELS["security"] == "Security"

    def test_quality_label(self):
        assert DIMENSION_LABELS["quality"] == "Quality"

    def test_documentation_label(self):
        assert DIMENSION_LABELS["documentation"] == "Documentation"

    def test_maintainability_label(self):
        assert DIMENSION_LABELS["maintainability"] == "Maintainability"

    def test_performance_label(self):
        assert DIMENSION_LABELS["performance"] == "Performance"

    def test_covers_all_six_dimensions(self):
        expected = {
            "architecture",
            "security",
            "quality",
            "documentation",
            "maintainability",
            "performance",
        }
        assert set(DIMENSION_LABELS.keys()) == expected

    def test_labels_are_title_case(self):
        for label in DIMENSION_LABELS.values():
            assert label[0].isupper()


# ── dim_label function ───────────────────────────────────────


class TestDimLabel:
    def test_known_dimension_architecture(self):
        assert dim_label("architecture") == "Architecture"

    def test_known_dimension_security(self):
        assert dim_label("security") == "Security"

    def test_known_dimension_quality(self):
        assert dim_label("quality") == "Quality"

    def test_known_dimension_documentation(self):
        assert dim_label("documentation") == "Documentation"

    def test_known_dimension_maintainability(self):
        assert dim_label("maintainability") == "Maintainability"

    def test_known_dimension_performance(self):
        assert dim_label("performance") == "Performance"

    def test_all_known_dimensions(self):
        for dim, expected in DIMENSION_LABELS.items():
            assert dim_label(dim) == expected

    def test_unknown_dimension_capitalized(self):
        """Unknown dimensions fall back to capitalize()."""
        result = dim_label("unknown_dim")
        assert result == "Unknown_dim"

    def test_unknown_dimension_single_word(self):
        result = dim_label("reliability")
        assert result == "Reliability"


# ── build_verdict function ───────────────────────────────────


def _make_scorecard(
    *,
    overall: float = 83.0,
    dims: tuple[DimensionScore, ...] | None = None,
) -> ScoreCard:
    if dims is None:
        dims = (
            DimensionScore(dimension="architecture", score=90.0, grade="A", findings_count=2, weight=0.25),
            DimensionScore(dimension="security", score=85.0, grade="B+", findings_count=3, weight=0.25),
            DimensionScore(dimension="quality", score=78.0, grade="B-", findings_count=5, weight=0.20),
            DimensionScore(dimension="documentation", score=70.0, grade="C", findings_count=4, weight=0.10),
            DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
            DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
        )
    return ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dims,
        total_findings=18,
    )


class TestBuildVerdict:
    def test_returns_string(self):
        report = SimpleNamespace(score_card=_make_scorecard())
        assert isinstance(build_verdict(report), str)

    def test_includes_grade(self):
        report = SimpleNamespace(score_card=_make_scorecard())
        verdict = build_verdict(report)
        assert "B+" in verdict

    def test_includes_score(self):
        report = SimpleNamespace(score_card=_make_scorecard())
        verdict = build_verdict(report)
        assert "83" in verdict

    def test_identifies_top_dimension(self):
        report = SimpleNamespace(score_card=_make_scorecard())
        verdict = build_verdict(report)
        # Architecture is the top at 90.0
        assert "architecture" in verdict.lower()

    def test_identifies_bottom_dimension(self):
        report = SimpleNamespace(score_card=_make_scorecard())
        verdict = build_verdict(report)
        # Documentation is the bottom at 70.0
        assert "documentation" in verdict.lower()

    def test_no_scorecard_returns_empty(self):
        report = SimpleNamespace(score_card=None)
        assert build_verdict(report) == ""

    def test_empty_dimensions_no_crash(self):
        sc = _make_scorecard(overall=80.0, dims=())
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "B" in verdict
        assert "80" in verdict

    def test_single_dimension_no_strong_weak(self):
        """A single dimension means top == bottom, so no strong/gaps."""
        dim = DimensionScore(
            dimension="security",
            score=90.0,
            grade="A",
            findings_count=1,
            weight=1.0,
        )
        sc = _make_scorecard(overall=90.0, dims=(dim,))
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "A" in verdict
        assert "90" in verdict
        # Should not contain "strong ... with ... gaps" pattern
        assert "gaps" not in verdict

    def test_two_dimensions_shows_strong_and_gaps(self):
        dims = (
            DimensionScore(dimension="architecture", score=95.0, grade="A+", findings_count=0, weight=0.5),
            DimensionScore(dimension="security", score=60.0, grade="D", findings_count=10, weight=0.5),
        )
        sc = _make_scorecard(overall=77.5, dims=dims)
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "architecture" in verdict.lower()
        assert "security" in verdict.lower()

    def test_f_grade_verdict(self):
        sc = _make_scorecard(overall=40.0, dims=())
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "F" in verdict
        assert "40" in verdict

    def test_a_plus_grade_verdict(self):
        sc = _make_scorecard(overall=98.0, dims=())
        report = SimpleNamespace(score_card=sc)
        verdict = build_verdict(report)
        assert "A+" in verdict
        assert "98" in verdict

    def test_verdict_contains_scores_keyword(self):
        report = SimpleNamespace(score_card=_make_scorecard())
        verdict = build_verdict(report)
        assert "scores" in verdict.lower()

    def test_verdict_em_dash_separator(self):
        """Multi-dimension verdicts use an em dash separator."""
        report = SimpleNamespace(score_card=_make_scorecard())
        verdict = build_verdict(report)
        assert "\u2014" in verdict
