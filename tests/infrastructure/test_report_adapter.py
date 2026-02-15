"""Tests for ReportAdapter — Jinja2 HTML report rendering."""

from __future__ import annotations

import tempfile
from pathlib import Path

from spectra.adapters.brand import build_verdict
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)
from spectra.infrastructure.report_adapter import (
    ReportAdapter,
    _bar_class,
    _build_executive_summary,
    _build_spectrum_segments,
    _critical_count,
    _dd_compliance_mapping,
    _dimension_hours,
    _grade_class,
    _severity_distribution,
    _sort_by_severity,
    _tech_debt_summary,
    _top_findings,
    _total_hours,
)


def _make_finding(
    *,
    sev: str = "high",
    dim: str = "security",
    line: int = 10,
    desc: str = "Test description",
    rec: str = "Fix this",
    hours: float = 0.0,
) -> Finding:
    role_map = {
        "architecture": "architecture",
        "security": "security",
        "quality": "quality",
        "documentation": "documentation",
        "maintainability": "dependency",
        "performance": "performance",
    }
    return Finding(
        id=f"F-{sev}-{line}",
        dimension=dim,
        severity=sev,
        title=f"{sev} {dim} finding",
        description=desc,
        location=FileLocation(file_path="src/main.py", line_start=line),
        recommendation=rec,
        agent_role=role_map.get(dim, "security"),
        confidence=0.8,
        estimated_hours=hours,
    )


def _minimal_report(
    *,
    findings: tuple[Finding, ...] | None = None,
    score: float = 83.5,
) -> AnalysisReport:
    """Create a minimal AnalysisReport for rendering tests."""
    default_finding = _make_finding()
    if findings is None:
        findings = (default_finding,)
    dimensions = (
        DimensionScore(dimension="architecture", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.25),
        DimensionScore(dimension="security", score=80.0, grade=score_to_grade(80.0), findings_count=1, weight=0.25),
        DimensionScore(dimension="quality", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.20),
        DimensionScore(
            dimension="documentation", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.10
        ),
        DimensionScore(
            dimension="maintainability", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.10
        ),
        DimensionScore(dimension="performance", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.10),
    )
    score_card = ScoreCard(
        overall_score=score,
        overall_grade=score_to_grade(score),
        dimensions=dimensions,
        total_findings=len(findings),
    )
    return AnalysisReport(
        repo_url="https://github.com/test/repo",
        repo_name="repo",
        score_card=score_card,
        findings=findings,
        analysis_duration_seconds=5.0,
        total_tokens_used=1000,
        total_cost_usd=0.01,
        agents_used=("architecture", "security", "quality", "documentation", "dependency", "performance"),
    )


# ── ReportAdapter rendering ──────────────────────────────────


class TestReportAdapter:
    def test_render_creates_file(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        result = adapter.render(report, path)
        assert result == path
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 0
        Path(path).unlink()

    def test_render_contains_repo_name(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "repo" in content
        Path(path).unlink()

    def test_render_produces_valid_html(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        # Valid HTML should contain basic structure
        assert "<html" in content.lower() or "<!doctype" in content.lower() or "<head" in content.lower()
        assert "</html>" in content.lower() or "</body>" in content.lower()
        Path(path).unlink()

    def test_template_globals_registered(self):
        adapter = ReportAdapter()
        env = adapter._env
        assert "_grade_class" in env.globals
        assert "_bar_class" in env.globals
        assert "_dim_label" in env.globals
        assert "_critical_count" in env.globals
        assert "_sort_by_severity" in env.globals
        assert "dimensions_order" in env.globals

    def test_render_contains_executive_summary(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "scores" in content.lower() or "verdict" in content.lower() or "summary" in content.lower()
        Path(path).unlink()

    def test_render_with_multiple_findings(self):
        adapter = ReportAdapter()
        findings = (
            _make_finding(sev="critical", line=1),
            _make_finding(sev="high", line=2),
            _make_finding(sev="medium", line=3),
            _make_finding(sev="low", line=4),
            _make_finding(sev="info", line=5),
        )
        report = _minimal_report(findings=findings)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 0
        Path(path).unlink()

    def test_render_with_no_findings(self):
        adapter = ReportAdapter()
        report = _minimal_report(findings=())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 0
        Path(path).unlink()


# ── Badge SVG generation ─────────────────────────────────────


class TestBadgeSVG:
    def test_badge_contains_svg_element(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        badge = adapter.render_badge(report)
        assert "<svg" in badge
        assert "</svg>" in badge

    def test_badge_contains_spectra_text(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        badge = adapter.render_badge(report)
        assert "Spectra" in badge

    def test_badge_contains_grade(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=95.0)
        badge = adapter.render_badge(report)
        assert "A+" in badge

    def test_badge_contains_score(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=83.5)
        badge = adapter.render_badge(report)
        assert "83" in badge or "84" in badge

    def test_badge_color_for_a_grade(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=95.0)
        badge = adapter.render_badge(report)
        # A grade maps to green (#22C55E)
        assert "22C55E" in badge

    def test_badge_color_for_b_grade(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=83.5)
        badge = adapter.render_badge(report)
        # B grade maps to cyan (#06B6D4)
        assert "06B6D4" in badge

    def test_badge_color_for_c_grade(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=72.0)
        badge = adapter.render_badge(report)
        # C grade maps to amber (#F59E0B)
        assert "F59E0B" in badge

    def test_badge_color_for_f_grade(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=40.0)
        badge = adapter.render_badge(report)
        # F grade maps to red (#EF4444)
        assert "EF4444" in badge

    def test_badge_dimensions_160x20(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        badge = adapter.render_badge(report)
        assert 'width="160"' in badge
        assert 'height="20"' in badge


# ── Grade class and bar class ────────────────────────────────


class TestGradeClass:
    def test_a_grades_return_grade_a(self):
        for grade in ("A+", "A", "A-"):
            assert _grade_class(grade) == "grade-a"

    def test_b_grades_return_grade_b(self):
        for grade in ("B+", "B", "B-"):
            assert _grade_class(grade) == "grade-b"

    def test_c_grades_return_grade_c(self):
        for grade in ("C+", "C", "C-"):
            assert _grade_class(grade) == "grade-c"

    def test_d_grades_return_grade_d(self):
        for grade in ("D+", "D", "D-"):
            assert _grade_class(grade) == "grade-d"

    def test_f_grade_returns_grade_f(self):
        assert _grade_class("F") == "grade-f"

    def test_unknown_grade_returns_grade_f(self):
        assert _grade_class("Z") == "grade-f"


class TestBarClass:
    def test_a_grades_return_bar_a(self):
        for grade in ("A+", "A", "A-"):
            assert _bar_class(grade) == "bar-a"

    def test_b_grades_return_bar_b(self):
        for grade in ("B+", "B", "B-"):
            assert _bar_class(grade) == "bar-b"

    def test_f_grade_returns_bar_f(self):
        assert _bar_class("F") == "bar-f"

    def test_unknown_grade_returns_bar_f(self):
        assert _bar_class("Z") == "bar-f"


# ── Sort by severity ─────────────────────────────────────────


class TestSortBySeverity:
    def test_sorts_critical_first(self):
        findings = [
            _make_finding(sev="low", line=1),
            _make_finding(sev="critical", line=2),
            _make_finding(sev="high", line=3),
        ]
        sorted_f = _sort_by_severity(findings)
        assert sorted_f[0].severity == "critical"
        assert sorted_f[1].severity == "high"
        assert sorted_f[2].severity == "low"

    def test_full_severity_order(self):
        findings = [
            _make_finding(sev="info", line=1),
            _make_finding(sev="medium", line=2),
            _make_finding(sev="critical", line=3),
            _make_finding(sev="low", line=4),
            _make_finding(sev="high", line=5),
        ]
        sorted_f = _sort_by_severity(findings)
        severities = [f.severity for f in sorted_f]
        assert severities == ["critical", "high", "medium", "low", "info"]

    def test_empty_list(self):
        assert _sort_by_severity([]) == []


# ── Critical count ───────────────────────────────────────────


class TestCriticalCount:
    def test_counts_criticals(self):
        findings = (
            _make_finding(sev="critical", line=1),
            _make_finding(sev="high", line=2),
            _make_finding(sev="critical", line=3),
        )
        assert _critical_count(findings) == 2

    def test_no_criticals(self):
        findings = (_make_finding(sev="high", line=1), _make_finding(sev="low", line=2))
        assert _critical_count(findings) == 0

    def test_empty(self):
        assert _critical_count(()) == 0

    def test_all_criticals(self):
        findings = tuple(_make_finding(sev="critical", line=i) for i in range(5))
        assert _critical_count(findings) == 5


# ── Severity distribution ────────────────────────────────────


class TestSeverityDistribution:
    def test_empty_findings(self):
        dist = _severity_distribution(())
        assert dist == {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

    def test_all_severities_counted(self):
        findings = (
            _make_finding(sev="critical", line=1),
            _make_finding(sev="critical", line=2),
            _make_finding(sev="high", line=3),
            _make_finding(sev="medium", line=4),
            _make_finding(sev="low", line=5),
            _make_finding(sev="info", line=6),
        )
        dist = _severity_distribution(findings)
        assert dist["critical"] == 2
        assert dist["high"] == 1
        assert dist["medium"] == 1
        assert dist["low"] == 1
        assert dist["info"] == 1

    def test_single_severity(self):
        findings = tuple(_make_finding(sev="high", line=i) for i in range(3))
        dist = _severity_distribution(findings)
        assert dist["high"] == 3
        assert dist["critical"] == 0
        assert dist["medium"] == 0


# ── Spectrum segments ────────────────────────────────────────


class TestBuildSpectrumSegments:
    def test_returns_six_segments(self):
        report = _minimal_report()
        segments = _build_spectrum_segments(report)
        assert len(segments) == 6

    def test_segments_have_required_keys(self):
        report = _minimal_report()
        segments = _build_spectrum_segments(report)
        for seg in segments:
            assert "label" in seg
            assert "score" in seg
            assert "grade" in seg
            assert "weight_pct" in seg
            assert "color" in seg

    def test_segments_ordered_by_dimensions(self):
        report = _minimal_report()
        segments = _build_spectrum_segments(report)
        labels = [s["label"] for s in segments]
        expected = ["Architecture", "Security", "Quality", "Documentation", "Maintainability", "Performance"]
        assert labels == expected

    def test_segment_scores_are_integers(self):
        report = _minimal_report()
        segments = _build_spectrum_segments(report)
        for seg in segments:
            assert isinstance(seg["score"], int)

    def test_segment_colors_are_hex(self):
        report = _minimal_report()
        segments = _build_spectrum_segments(report)
        for seg in segments:
            assert isinstance(seg["color"], str)
            assert seg["color"].startswith("#")

    def test_segment_weight_pct_sum(self):
        report = _minimal_report()
        segments = _build_spectrum_segments(report)
        total = sum(s["weight_pct"] for s in segments)
        assert abs(total - 100.0) < 0.1


# ── Tech debt summary ────────────────────────────────────────


class TestTechDebtSummary:
    def test_empty_findings(self):
        summary = _tech_debt_summary(())
        assert summary["total_hours"] == 0.0
        assert summary["cost_usd"] == 0
        assert summary["by_dimension"] == {}
        assert summary["by_severity"] == {}

    def test_computes_total_hours(self):
        findings = (
            _make_finding(hours=2.0, line=1),
            _make_finding(hours=3.5, line=2),
        )
        summary = _tech_debt_summary(findings)
        assert summary["total_hours"] == 5.5

    def test_computes_cost_usd(self):
        findings = (_make_finding(hours=10.0, line=1),)
        summary = _tech_debt_summary(findings)
        # Cost = 10 * 150 = 1500
        assert summary["cost_usd"] == 1500

    def test_groups_by_dimension(self):
        findings = (
            _make_finding(dim="security", hours=2.0, line=1),
            _make_finding(dim="security", hours=1.0, line=2),
            _make_finding(dim="quality", hours=3.0, line=3),
        )
        summary = _tech_debt_summary(findings)
        assert summary["by_dimension"]["security"] == 3.0
        assert summary["by_dimension"]["quality"] == 3.0

    def test_groups_by_severity(self):
        findings = (
            _make_finding(sev="critical", hours=5.0, line=1),
            _make_finding(sev="high", hours=2.0, line=2),
            _make_finding(sev="critical", hours=3.0, line=3),
        )
        summary = _tech_debt_summary(findings)
        assert summary["by_severity"]["critical"] == 8.0
        assert summary["by_severity"]["high"] == 2.0


# ── DD compliance mapping (OWASP + CWE) ─────────────────────


class TestDDComplianceMapping:
    def test_empty_findings(self):
        result = _dd_compliance_mapping(())
        assert result["owasp_covered_count"] == 0
        assert result["owasp_total"] == 10
        assert result["cwes"] == []
        assert len(result["owasp_coverage"]) == 10

    def test_owasp_coverage_all_uncovered_by_default(self):
        result = _dd_compliance_mapping(())
        for entry in result["owasp_coverage"]:
            assert entry["covered"] is False

    def test_owasp_category_detected(self):
        finding = _make_finding(
            desc="This violates A01 Broken Access Control",
            line=1,
        )
        result = _dd_compliance_mapping((finding,))
        assert result["owasp_covered_count"] >= 1
        # Find A01 entry
        a01 = [e for e in result["owasp_coverage"] if e["code"] == "A01"]
        assert len(a01) == 1
        assert a01[0]["covered"] is True

    def test_multiple_owasp_categories_detected(self):
        finding = _make_finding(
            desc="Violates A01 and A03 injection patterns",
            line=1,
        )
        result = _dd_compliance_mapping((finding,))
        assert result["owasp_covered_count"] >= 2

    def test_owasp_in_recommendation(self):
        finding = _make_finding(
            desc="Some issue",
            rec="Fix according to A05 Security Misconfiguration",
            line=1,
        )
        result = _dd_compliance_mapping((finding,))
        a05 = [e for e in result["owasp_coverage"] if e["code"] == "A05"]
        assert a05[0]["covered"] is True

    def test_cwe_extraction(self):
        finding = _make_finding(
            desc="This is CWE-79 Cross-Site Scripting",
            line=1,
        )
        result = _dd_compliance_mapping((finding,))
        assert "79" in result["cwes"]

    def test_multiple_cwes_extracted(self):
        finding = _make_finding(
            desc="Issues: CWE-79 XSS and CWE-89 SQL Injection",
            line=1,
        )
        result = _dd_compliance_mapping((finding,))
        assert "79" in result["cwes"]
        assert "89" in result["cwes"]

    def test_cwes_sorted_numerically(self):
        finding = _make_finding(
            desc="CWE-200, CWE-79, CWE-89, CWE-22",
            line=1,
        )
        result = _dd_compliance_mapping((finding,))
        cwes_int = [int(c) for c in result["cwes"]]
        assert cwes_int == sorted(cwes_int)

    def test_cwe_in_recommendation(self):
        finding = _make_finding(
            desc="Some issue",
            rec="Fix CWE-352 CSRF vulnerability",
            line=1,
        )
        result = _dd_compliance_mapping((finding,))
        assert "352" in result["cwes"]

    def test_owasp_coverage_has_correct_structure(self):
        result = _dd_compliance_mapping(())
        for entry in result["owasp_coverage"]:
            assert "code" in entry
            assert "label" in entry
            assert "covered" in entry
            assert entry["code"].startswith("A")

    def test_owasp_total_is_10(self):
        result = _dd_compliance_mapping(())
        assert result["owasp_total"] == 10


# ── Top findings ─────────────────────────────────────────────


class TestTopFindings:
    def test_returns_max_five(self):
        findings = tuple(_make_finding(line=i) for i in range(10))
        result = _top_findings(findings)
        assert len(result) <= 5

    def test_sorted_by_severity(self):
        findings = (
            _make_finding(sev="low", line=1),
            _make_finding(sev="critical", line=2),
            _make_finding(sev="info", line=3),
            _make_finding(sev="high", line=4),
            _make_finding(sev="medium", line=5),
        )
        result = _top_findings(findings)
        assert result[0].severity == "critical"
        assert result[1].severity == "high"

    def test_empty_findings(self):
        assert _top_findings(()) == []


# ── Total hours and dimension hours ──────────────────────────


class TestTotalHours:
    def test_empty(self):
        assert _total_hours(()) == 0.0

    def test_sums_hours(self):
        findings = (
            _make_finding(hours=1.5, line=1),
            _make_finding(hours=2.5, line=2),
        )
        assert _total_hours(findings) == 4.0

    def test_rounds_to_one_decimal(self):
        findings = (
            _make_finding(hours=1.333, line=1),
            _make_finding(hours=2.666, line=2),
        )
        result = _total_hours(findings)
        assert result == 4.0  # 1.333 + 2.666 = 3.999, rounds to 4.0


class TestDimensionHours:
    def test_empty(self):
        assert _dimension_hours(()) == {}

    def test_groups_by_dimension(self):
        findings = (
            _make_finding(dim="security", hours=2.0, line=1),
            _make_finding(dim="quality", hours=3.0, line=2),
            _make_finding(dim="security", hours=1.0, line=3),
        )
        result = _dimension_hours(findings)
        assert result["security"] == 3.0
        assert result["quality"] == 3.0

    def test_rounds_to_one_decimal(self):
        findings = (
            _make_finding(dim="security", hours=1.333, line=1),
            _make_finding(dim="security", hours=2.666, line=2),
        )
        result = _dimension_hours(findings)
        assert result["security"] == 4.0


# ── Build executive summary ──────────────────────────────────


class TestBuildExecutiveSummary:
    def test_summary_has_required_keys(self):
        report = _minimal_report()
        summary = _build_executive_summary(report)
        assert "verdict" in summary
        assert "strengths" in summary
        assert "concerns" in summary
        assert "critical_count" in summary
        assert "total_findings" in summary
        assert "agents_count" in summary
        assert "duration" in summary

    def test_summary_has_extended_keys(self):
        report = _minimal_report()
        summary = _build_executive_summary(report)
        assert "severity_dist" in summary
        assert "total_tech_debt_hours" in summary
        assert "dimension_hours" in summary

    def test_summary_values_match_report(self):
        report = _minimal_report()
        summary = _build_executive_summary(report)
        assert summary["total_findings"] == len(report.findings)
        assert summary["agents_count"] == len(report.agents_used)
        assert summary["duration"] == report.analysis_duration_seconds

    def test_strengths_are_top_dimensions(self):
        report = _minimal_report()
        summary = _build_executive_summary(report)
        strengths = summary["strengths"]
        assert len(strengths) == 3
        # Strengths are sorted by score descending
        scores = [d.score for d in strengths]
        assert scores == sorted(scores, reverse=True)

    def test_concerns_are_bottom_dimensions(self):
        report = _minimal_report()
        summary = _build_executive_summary(report)
        concerns = summary["concerns"]
        assert len(concerns) <= 3
        # Concerns should include the lowest-scoring dimension
        scores = [d.score for d in concerns]
        assert scores == sorted(scores)

    def test_critical_count_in_summary(self):
        critical_finding = _make_finding(sev="critical", line=1)
        report = _minimal_report(findings=(critical_finding,))
        summary = _build_executive_summary(report)
        assert summary["critical_count"] == 1

    def test_no_critical_in_summary(self):
        report = _minimal_report()
        summary = _build_executive_summary(report)
        assert summary["critical_count"] == 0

    def test_severity_dist_in_summary(self):
        findings = (
            _make_finding(sev="critical", line=1),
            _make_finding(sev="high", line=2),
            _make_finding(sev="high", line=3),
        )
        report = _minimal_report(findings=findings)
        summary = _build_executive_summary(report)
        assert summary["severity_dist"]["critical"] == 1
        assert summary["severity_dist"]["high"] == 2


# ── Build verdict (integration with ReportAdapter) ───────────


class TestBuildVerdictReport:
    def test_includes_grade_and_score(self):
        report = _minimal_report()
        verdict = build_verdict(report)
        assert "B+" in verdict
        assert "84" in verdict or "83" in verdict

    def test_identifies_strengths_and_gaps(self):
        report = _minimal_report()
        verdict = build_verdict(report)
        assert "strong" in verdict or "gaps" in verdict or "scores" in verdict

    def test_empty_dimensions(self):
        sc = ScoreCard(
            overall_score=0.0,
            overall_grade="F",
            dimensions=(),
            total_findings=0,
        )
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sc,
            findings=(),
            analysis_duration_seconds=1.0,
            total_tokens_used=0,
            total_cost_usd=0.0,
            agents_used=(),
        )
        verdict = build_verdict(report)
        assert "F" in verdict
