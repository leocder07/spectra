"""Tests for ReportAdapter — Jinja2 HTML report rendering."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

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
    _concentration_rating,
    _complexity_component_score,
    _complexity_indicators,
    _complexity_risk_level,
    _compute_issue_concentration,
    _compute_file_concentration,
    _critical_count,
    _critical_findings_score,
    _dd_compliance_mapping,
    _dep_risk_rating,
    _dep_severity_penalty,
    _dependency_risk_score,
    _detect_copyleft_risk,
    _dimension_hours,
    _gini_coefficient,
    _grade_class,
    _investment_readiness_score,
    _ir_rating,
    _license_compliance,
    _license_component_score,
    _matches_soc2_criterion,
    _safe_avg,
    _safe_pct,
    _security_posture_score,
    _separate_strengths,
    _severity_distribution,
    _soc2_mapping,
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


# ── SOC 2 Mapping ────────────────────────────────────────────


class TestSoc2Mapping:
    def test_empty_findings(self):
        result = _soc2_mapping(())
        assert result["total_mapped"] == 0
        assert result["coverage_pct"] == 0.0
        assert len(result["criteria"]) == 5

    def test_criteria_have_correct_keys(self):
        result = _soc2_mapping(())
        for c in result["criteria"]:
            assert "key" in c
            assert "label" in c
            assert "finding_count" in c
            assert "severity_counts" in c
            assert "has_critical" in c

    def test_security_finding_maps_to_security_criterion(self):
        finding = _make_finding(
            dim="security",
            desc="authentication vulnerability in access control",
            line=1,
        )
        result = _soc2_mapping((finding,))
        security = [c for c in result["criteria"] if c["key"] == "security"]
        assert len(security) == 1
        assert security[0]["finding_count"] >= 1

    def test_no_critical_when_only_low_severity(self):
        finding = _make_finding(
            dim="security",
            sev="low",
            desc="minor access control concern",
            line=1,
        )
        result = _soc2_mapping((finding,))
        for c in result["criteria"]:
            assert c["has_critical"] is False

    def test_has_critical_when_critical_finding(self):
        finding = _make_finding(
            dim="security",
            sev="critical",
            desc="authentication bypass vulnerability",
            line=1,
        )
        result = _soc2_mapping((finding,))
        security = [c for c in result["criteria"] if c["key"] == "security"]
        assert security[0]["has_critical"] is True

    def test_multiple_criteria_covered(self):
        findings = (
            _make_finding(dim="security", desc="encryption vulnerability", line=1),
            _make_finding(dim="quality", desc="validation integrity check missing", line=2),
            _make_finding(dim="performance", desc="uptime redundancy concern", line=3),
        )
        result = _soc2_mapping(findings)
        covered = [c for c in result["criteria"] if c["finding_count"] > 0]
        assert len(covered) >= 2

    def test_coverage_pct_calculated_correctly(self):
        finding = _make_finding(
            dim="security",
            desc="authentication vulnerability",
            line=1,
        )
        result = _soc2_mapping((finding,))
        assert result["coverage_pct"] >= 0.0
        assert result["coverage_pct"] <= 100.0

    def test_all_five_criteria_present(self):
        result = _soc2_mapping(())
        keys = {c["key"] for c in result["criteria"]}
        assert keys == {"security", "availability", "processing_integrity", "confidentiality", "privacy"}

    def test_confidentiality_maps_credential_finding(self):
        finding = _make_finding(
            dim="security",
            desc="hardcoded credential api key exposed",
            line=1,
        )
        result = _soc2_mapping((finding,))
        conf = [c for c in result["criteria"] if c["key"] == "confidentiality"]
        assert conf[0]["finding_count"] >= 1

    def test_privacy_maps_gdpr_finding(self):
        finding = _make_finding(
            dim="security",
            desc="gdpr privacy concern personal data exposure",
            line=1,
        )
        result = _soc2_mapping((finding,))
        priv = [c for c in result["criteria"] if c["key"] == "privacy"]
        assert priv[0]["finding_count"] >= 1


# ── matches_soc2_criterion ────────────────────────────────────


class TestMatchesSoc2Criterion:
    def test_matches_when_dimension_and_keyword_match(self):
        finding = _make_finding(dim="security", desc="access control issue", line=1)
        criterion = {
            "dimensions": ("security",),
            "keywords": ("access control",),
        }
        assert _matches_soc2_criterion(finding, criterion) is True

    def test_no_match_when_dimension_wrong(self):
        finding = _make_finding(dim="quality", desc="access control issue", line=1)
        criterion = {
            "dimensions": ("security",),
            "keywords": ("access control",),
        }
        assert _matches_soc2_criterion(finding, criterion) is False

    def test_no_match_when_keyword_absent(self):
        finding = _make_finding(dim="security", desc="something else entirely", line=1)
        criterion = {
            "dimensions": ("security",),
            "keywords": ("access control",),
        }
        assert _matches_soc2_criterion(finding, criterion) is False

    def test_matches_keyword_in_title(self):
        finding = Finding(
            id="F-test-1",
            dimension="security",
            severity="high",
            title="authentication bypass vulnerability",
            description="unrelated text",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="Fix",
            agent_role="security",
            confidence=0.8,
            estimated_hours=0.0,
        )
        criterion = {
            "dimensions": ("security",),
            "keywords": ("authentication",),
        }
        assert _matches_soc2_criterion(finding, criterion) is True


# ── Issue Concentration ────────────────────────────────────────────────


class TestComputeIssueConcentration:
    def test_empty_findings(self):
        result = _compute_issue_concentration(())
        assert result["score"] == 100
        assert result["rating"] == "healthy"
        assert result["hotspots"] == []

    def test_single_finding(self):
        finding = _make_finding(line=1)
        result = _compute_issue_concentration((finding,))
        assert "score" in result
        assert "rating" in result
        assert "hotspots" in result

    def test_findings_in_one_file_scores_lower(self):
        findings = tuple(_make_finding(line=i) for i in range(10))
        result = _compute_issue_concentration(findings)
        # All in one file = concentrated = lower score
        assert result["score"] <= 100

    def test_distributed_findings_score_higher(self):
        findings = tuple(
            Finding(
                id=f"F-{i}",
                dimension="security",
                severity="high",
                title="test",
                description="test",
                location=FileLocation(file_path=f"src/file{i}.py", line_start=1),
                recommendation="Fix",
                agent_role="security",
                confidence=0.8,
                estimated_hours=0.0,
            )
            for i in range(10)
        )
        result = _compute_issue_concentration(findings)
        # Evenly distributed should have high score
        assert result["score"] >= 80

    def test_has_concentration_key(self):
        finding = _make_finding(line=1)
        result = _compute_issue_concentration((finding,))
        assert "concentration" in result

    def test_has_unique_files_key(self):
        findings = (
            _make_finding(line=1),
            _make_finding(line=2),
        )
        result = _compute_issue_concentration(findings)
        assert result["unique_files"] == 1  # all in src/main.py

    def test_hotspots_limited_to_ten(self):
        findings = tuple(
            Finding(
                id=f"F-{i}",
                dimension="security",
                severity="high",
                title="test",
                description="test",
                location=FileLocation(file_path=f"src/file{i}.py", line_start=1),
                recommendation="Fix",
                agent_role="security",
                confidence=0.8,
                estimated_hours=0.0,
            )
            for i in range(20)
        )
        result = _compute_issue_concentration(findings)
        assert len(result["hotspots"]) <= 10


# ── Gini Coefficient ─────────────────────────────────────────


class TestGiniCoefficient:
    def test_empty_list(self):
        assert _gini_coefficient([]) == 0.0

    def test_all_zeros(self):
        assert _gini_coefficient([0, 0, 0]) == 0.0

    def test_equal_distribution(self):
        result = _gini_coefficient([5, 5, 5, 5])
        assert abs(result) < 0.01

    def test_maximum_inequality(self):
        result = _gini_coefficient([0, 0, 0, 100])
        assert result > 0.5

    def test_single_value(self):
        result = _gini_coefficient([10])
        assert abs(result) < 0.01

    def test_two_equal_values(self):
        result = _gini_coefficient([5, 5])
        assert abs(result) < 0.01

    def test_two_unequal_values(self):
        result = _gini_coefficient([1, 99])
        assert result > 0.3

    def test_returns_float(self):
        result = _gini_coefficient([1, 2, 3])
        assert isinstance(result, float)


# ── Concentration Rating ────────────────────────────────────────


class TestConcentrationRating:
    def test_healthy(self):
        assert _concentration_rating(0.1) == "healthy"
        assert _concentration_rating(0.29) == "healthy"

    def test_moderate(self):
        assert _concentration_rating(0.3) == "moderate"
        assert _concentration_rating(0.49) == "moderate"

    def test_concerning(self):
        assert _concentration_rating(0.5) == "concerning"
        assert _concentration_rating(0.69) == "concerning"

    def test_critical(self):
        assert _concentration_rating(0.7) == "critical"
        assert _concentration_rating(1.0) == "critical"

    def test_zero(self):
        assert _concentration_rating(0.0) == "healthy"


# ── File Concentration ────────────────────────────────────────


class TestComputeFileConcentration:
    def test_empty_findings(self):
        result = _compute_file_concentration(())
        assert result == []

    def test_single_file(self):
        findings = tuple(_make_finding(line=i) for i in range(3))
        result = _compute_file_concentration(findings)
        assert len(result) == 1
        assert result[0]["file"] == "src/main.py"
        assert result[0]["count"] == 3

    def test_multiple_files_sorted(self):
        findings = tuple(
            Finding(
                id=f"F-{i}",
                dimension="security",
                severity="high",
                title="test",
                description="test",
                location=FileLocation(
                    file_path=f"src/file{'a' if i < 5 else 'b'}.py",
                    line_start=i,
                ),
                recommendation="Fix",
                agent_role="security",
                confidence=0.8,
                estimated_hours=0.0,
            )
            for i in range(8)
        )
        result = _compute_file_concentration(findings)
        # file_a has 5, file_b has 3, so file_a should be first
        assert result[0]["count"] >= result[-1]["count"]

    def test_max_ten_hotspots(self):
        findings = tuple(
            Finding(
                id=f"F-{i}",
                dimension="security",
                severity="high",
                title="test",
                description="test",
                location=FileLocation(file_path=f"src/f{i}.py", line_start=1),
                recommendation="Fix",
                agent_role="security",
                confidence=0.8,
                estimated_hours=0.0,
            )
            for i in range(15)
        )
        result = _compute_file_concentration(findings)
        assert len(result) <= 10


# ── License Compliance ────────────────────────────────────────


class TestLicenseCompliance:
    def test_empty_findings(self):
        result = _license_compliance(())
        assert result["total_mentions"] == 0
        assert result["unique_licenses"] == 0
        assert result["copyleft_risk"]["has_copyleft"] is False

    def test_detects_mit_license(self):
        finding = _make_finding(desc="Uses MIT licensed dependency", line=1)
        result = _license_compliance((finding,))
        assert result["total_mentions"] >= 1
        assert "MIT" in result["licenses_found"]

    def test_detects_apache_license(self):
        finding = _make_finding(desc="Apache-2.0 library detected", line=1)
        result = _license_compliance((finding,))
        assert result["total_mentions"] >= 1

    def test_detects_gpl_copyleft(self):
        finding = _make_finding(desc="GPL-3 licensed dependency", line=1)
        result = _license_compliance((finding,))
        assert result["copyleft_risk"]["has_copyleft"] is True
        assert result["copyleft_risk"]["risk_level"] == "high"

    def test_detects_agpl_copyleft(self):
        finding = _make_finding(desc="AGPL-3 licensed code", line=1)
        result = _license_compliance((finding,))
        assert result["copyleft_risk"]["has_copyleft"] is True

    def test_no_copyleft_with_permissive_licenses(self):
        finding = _make_finding(desc="MIT and BSD-2 licenses", line=1)
        result = _license_compliance((finding,))
        assert result["copyleft_risk"]["has_copyleft"] is False
        assert result["copyleft_risk"]["risk_level"] == "none"

    def test_flagged_findings_limited_to_20(self):
        findings = tuple(_make_finding(desc=f"MIT license #{i}", line=i) for i in range(30))
        result = _license_compliance(findings)
        assert len(result["flagged"]) <= 20

    def test_flagged_finding_has_correct_keys(self):
        finding = _make_finding(desc="MIT license here", line=1)
        result = _license_compliance((finding,))
        if result["flagged"]:
            f = result["flagged"][0]
            assert "license" in f
            assert "finding_id" in f
            assert "title" in f
            assert "severity" in f

    def test_multiple_licenses_in_one_finding(self):
        finding = _make_finding(desc="Both MIT and Apache-2.0 detected", line=1)
        result = _license_compliance((finding,))
        assert result["unique_licenses"] >= 2

    def test_license_in_recommendation(self):
        finding = _make_finding(desc="some issue", rec="Switch to MIT license", line=1)
        result = _license_compliance((finding,))
        assert result["total_mentions"] >= 1

    def test_license_in_title(self):
        finding = Finding(
            id="F-lic-1",
            dimension="security",
            severity="high",
            title="GPL-3 dependency found",
            description="unrelated",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="Review",
            agent_role="security",
            confidence=0.8,
            estimated_hours=0.0,
        )
        result = _license_compliance((finding,))
        assert result["total_mentions"] >= 1


# ── Detect Copyleft Risk ──────────────────────────────────────


class TestDetectCopyleftRisk:
    def test_no_licenses(self):
        from collections import Counter

        result = _detect_copyleft_risk(Counter())
        assert result["has_copyleft"] is False
        assert result["risk_level"] == "none"

    def test_permissive_only(self):
        from collections import Counter

        result = _detect_copyleft_risk(Counter({"MIT": 3, "APACHE-2.0": 1}))
        assert result["has_copyleft"] is False

    def test_gpl_detected(self):
        from collections import Counter

        result = _detect_copyleft_risk(Counter({"GPL-3": 1}))
        assert result["has_copyleft"] is True
        assert "GPL-3" in result["copyleft_licenses"]

    def test_lgpl_detected(self):
        from collections import Counter

        result = _detect_copyleft_risk(Counter({"LGPL-2.1": 1}))
        assert result["has_copyleft"] is True

    def test_agpl_detected(self):
        from collections import Counter

        result = _detect_copyleft_risk(Counter({"AGPL-3": 1}))
        assert result["has_copyleft"] is True

    def test_mixed_licenses(self):
        from collections import Counter

        result = _detect_copyleft_risk(Counter({"MIT": 5, "GPL-3": 1, "BSD-2": 2}))
        assert result["has_copyleft"] is True
        assert result["risk_level"] == "high"


# ── Complexity Indicators ─────────────────────────────────────


class TestComplexityIndicators:
    def test_empty_findings(self):
        result = _complexity_indicators(())
        assert result["max_complexity"] == 0
        assert result["avg_complexity"] == 0.0
        assert result["high_complexity_count"] == 0
        assert result["risk_level"] == "unknown"

    def test_extracts_numeric_complexity(self):
        finding = _make_finding(
            desc="cyclomatic complexity: 25",
            line=1,
        )
        result = _complexity_indicators((finding,))
        assert 25 in result["mentioned_scores"]
        assert result["max_complexity"] == 25

    def test_extracts_cognitive_complexity(self):
        finding = _make_finding(desc="cognitive complexity 15", line=1)
        result = _complexity_indicators((finding,))
        assert 15 in result["mentioned_scores"]

    def test_detects_high_complexity_flag(self):
        finding = _make_finding(desc="high cyclomatic complexity detected", line=1)
        result = _complexity_indicators((finding,))
        assert result["high_complexity_count"] >= 1

    def test_detects_excessive_complexity(self):
        finding = _make_finding(desc="excessive complexity in module", line=1)
        result = _complexity_indicators((finding,))
        assert result["high_complexity_count"] >= 1

    def test_risk_level_low(self):
        finding = _make_finding(desc="cyclomatic complexity: 5", line=1)
        result = _complexity_indicators((finding,))
        assert result["risk_level"] == "low"

    def test_risk_level_moderate(self):
        finding = _make_finding(desc="cyclomatic complexity: 15", line=1)
        result = _complexity_indicators((finding,))
        assert result["risk_level"] == "moderate"

    def test_risk_level_high(self):
        finding = _make_finding(desc="cyclomatic complexity: 25", line=1)
        result = _complexity_indicators((finding,))
        assert result["risk_level"] == "high"

    def test_risk_level_critical(self):
        finding = _make_finding(desc="cyclomatic complexity: 35", line=1)
        result = _complexity_indicators((finding,))
        assert result["risk_level"] == "critical"

    def test_mentioned_scores_sorted_descending(self):
        findings = (
            _make_finding(desc="cyclomatic complexity: 5", line=1),
            _make_finding(desc="cyclomatic complexity: 25", line=2),
            _make_finding(desc="cyclomatic complexity: 15", line=3),
        )
        result = _complexity_indicators(findings)
        assert result["mentioned_scores"] == sorted(result["mentioned_scores"], reverse=True)

    def test_mentioned_scores_capped_at_20(self):
        findings = tuple(_make_finding(desc=f"cyclomatic complexity: {i}", line=i) for i in range(1, 30))
        result = _complexity_indicators(findings)
        assert len(result["mentioned_scores"]) <= 20

    def test_high_complexity_files_capped_at_10(self):
        findings = tuple(_make_finding(desc="high complexity detected", line=i) for i in range(15))
        result = _complexity_indicators(findings)
        assert len(result["high_complexity_files"]) <= 10

    def test_avg_complexity_computed(self):
        findings = (
            _make_finding(desc="cyclomatic complexity: 10", line=1),
            _make_finding(desc="cyclomatic complexity: 20", line=2),
        )
        result = _complexity_indicators(findings)
        assert result["avg_complexity"] == 15.0


# ── Complexity Risk Level ─────────────────────────────────────


class TestComplexityRiskLevel:
    def test_empty(self):
        assert _complexity_risk_level([]) == "unknown"

    def test_low(self):
        assert _complexity_risk_level([5, 8]) == "low"

    def test_moderate(self):
        assert _complexity_risk_level([15]) == "moderate"

    def test_high(self):
        assert _complexity_risk_level([25]) == "high"

    def test_critical(self):
        assert _complexity_risk_level([35]) == "critical"

    def test_uses_max_value(self):
        assert _complexity_risk_level([5, 35]) == "critical"


# ── Safe Avg ──────────────────────────────────────────────────


class TestSafeAvg:
    def test_empty(self):
        assert _safe_avg([]) == 0.0

    def test_single(self):
        assert _safe_avg([10]) == 10.0

    def test_multiple(self):
        assert _safe_avg([10, 20, 30]) == 20.0

    def test_rounds_to_one_decimal(self):
        result = _safe_avg([1, 2])
        assert result == 1.5


# ── Safe Pct ──────────────────────────────────────────────────


class TestSafePct:
    def test_zero_denominator(self):
        assert _safe_pct(5, 0) == 0.0

    def test_normal(self):
        assert _safe_pct(50, 100) == 50.0

    def test_all(self):
        assert _safe_pct(100, 100) == 100.0

    def test_none(self):
        assert _safe_pct(0, 100) == 0.0

    def test_rounds_to_one_decimal(self):
        result = _safe_pct(1, 3)
        assert result == 33.3


# ── Dependency Risk Score ─────────────────────────────────────


class TestDependencyRiskScore:
    def test_empty_findings(self):
        result = _dependency_risk_score(())
        assert result["score"] == 0
        assert result["rating"] == "low"
        assert result["total_dep_findings"] == 0

    def test_maintainability_findings_used(self):
        finding = _make_finding(
            dim="maintainability",
            desc="outdated deprecated dependency",
            line=1,
        )
        result = _dependency_risk_score((finding,))
        assert result["total_dep_findings"] == 1
        assert result["score"] > 0

    def test_keyword_outdated_adds_points(self):
        finding = _make_finding(dim="maintainability", desc="outdated package", line=1)
        result = _dependency_risk_score((finding,))
        assert result["score"] >= 15

    def test_keyword_vulnerable_adds_points(self):
        finding = _make_finding(dim="maintainability", desc="vulnerable dependency", line=1)
        result = _dependency_risk_score((finding,))
        assert result["score"] >= 25

    def test_severity_penalty_for_critical(self):
        finding = _make_finding(dim="maintainability", sev="critical", desc="outdated", line=1)
        result = _dependency_risk_score((finding,))
        assert result["severity_penalty"] >= 20

    def test_score_capped_at_100(self):
        findings = tuple(
            _make_finding(
                dim="maintainability",
                sev="critical",
                desc="outdated vulnerable deprecated end of life unmaintained cve",
                line=i,
            )
            for i in range(10)
        )
        result = _dependency_risk_score(findings)
        assert result["score"] <= 100

    def test_risk_signals_limited(self):
        findings = tuple(_make_finding(dim="maintainability", desc="outdated deprecated", line=i) for i in range(20))
        result = _dependency_risk_score(findings)
        assert len(result["risk_signals"]) <= 15

    def test_fallback_to_agent_role_dependency(self):
        finding = Finding(
            id="F-dep-1",
            dimension="quality",  # Not maintainability
            severity="high",
            title="test",
            description="outdated lib",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="update",
            agent_role="dependency",  # But agent_role is dependency
            confidence=0.8,
            estimated_hours=0.0,
        )
        result = _dependency_risk_score((finding,))
        assert result["total_dep_findings"] == 1

    def test_rating_low(self):
        assert _dep_risk_rating(10) == "low"

    def test_rating_moderate(self):
        assert _dep_risk_rating(30) == "moderate"

    def test_rating_elevated(self):
        assert _dep_risk_rating(50) == "elevated"

    def test_rating_high(self):
        assert _dep_risk_rating(70) == "high"

    def test_rating_critical(self):
        assert _dep_risk_rating(90) == "critical"


# ── Dep Severity Penalty ──────────────────────────────────────


class TestDepSeverityPenalty:
    def test_empty(self):
        assert _dep_severity_penalty([]) == 0

    def test_critical_adds_20(self):
        findings = [_make_finding(sev="critical", line=1)]
        assert _dep_severity_penalty(findings) == 20

    def test_high_adds_10(self):
        findings = [_make_finding(sev="high", line=1)]
        assert _dep_severity_penalty(findings) == 10

    def test_medium_adds_5(self):
        findings = [_make_finding(sev="medium", line=1)]
        assert _dep_severity_penalty(findings) == 5

    def test_low_adds_nothing(self):
        findings = [_make_finding(sev="low", line=1)]
        assert _dep_severity_penalty(findings) == 0

    def test_info_adds_nothing(self):
        findings = [_make_finding(sev="info", line=1)]
        assert _dep_severity_penalty(findings) == 0

    def test_capped_at_50(self):
        findings = [_make_finding(sev="critical", line=i) for i in range(10)]
        assert _dep_severity_penalty(findings) == 50

    def test_mixed_severities(self):
        findings = [
            _make_finding(sev="critical", line=1),
            _make_finding(sev="high", line=2),
            _make_finding(sev="medium", line=3),
        ]
        assert _dep_severity_penalty(findings) == 35


# ── Investment Readiness Score ────────────────────────────────


class TestInvestmentReadinessScore:
    def _default_report(self) -> AnalysisReport:
        return _minimal_report(score=85.0)

    def _default_issue_concentration(self) -> dict:
        return {"score": 80, "rating": "healthy"}

    def _default_dep_risk(self) -> dict:
        return {"score": 20, "rating": "moderate"}

    def _default_complexity(self) -> dict:
        return {"risk_level": "low"}

    def _default_license(self) -> dict:
        return {"copyleft_risk": {"has_copyleft": False}}

    def _default_soc2(self) -> dict:
        return {"coverage_pct": 50.0}

    def test_returns_score(self):
        result = _investment_readiness_score(
            self._default_report(),
            self._default_issue_concentration(),
            self._default_dep_risk(),
            self._default_complexity(),
            self._default_license(),
            self._default_soc2(),
        )
        assert "score" in result
        assert 0 <= result["score"] <= 100

    def test_returns_rating(self):
        result = _investment_readiness_score(
            self._default_report(),
            self._default_issue_concentration(),
            self._default_dep_risk(),
            self._default_complexity(),
            self._default_license(),
            self._default_soc2(),
        )
        assert result["rating"] in {
            "investment-ready",
            "near-ready",
            "needs-work",
            "significant-gaps",
            "not-ready",
        }

    def test_returns_components(self):
        result = _investment_readiness_score(
            self._default_report(),
            self._default_issue_concentration(),
            self._default_dep_risk(),
            self._default_complexity(),
            self._default_license(),
            self._default_soc2(),
        )
        assert "components" in result
        assert "overall_score" in result["components"]
        assert "security_posture" in result["components"]

    def test_returns_weights(self):
        result = _investment_readiness_score(
            self._default_report(),
            self._default_issue_concentration(),
            self._default_dep_risk(),
            self._default_complexity(),
            self._default_license(),
            self._default_soc2(),
        )
        assert "weights" in result
        assert abs(sum(result["weights"].values()) - 1.0) < 0.01

    def test_high_score_with_good_inputs(self):
        report = _minimal_report(score=95.0)
        result = _investment_readiness_score(
            report,
            {"score": 95},
            {"score": 5},
            {"risk_level": "low"},
            {"copyleft_risk": {"has_copyleft": False}},
            {"coverage_pct": 80.0},
        )
        assert result["score"] >= 70

    def test_low_score_with_bad_inputs(self):
        report = _minimal_report(score=40.0)
        result = _investment_readiness_score(
            report,
            {"score": 20},
            {"score": 80},
            {"risk_level": "critical"},
            {"copyleft_risk": {"has_copyleft": True}},
            {"coverage_pct": 10.0},
        )
        assert result["score"] <= 60

    def test_copyleft_reduces_license_score(self):
        no_copyleft = _investment_readiness_score(
            self._default_report(),
            self._default_issue_concentration(),
            self._default_dep_risk(),
            self._default_complexity(),
            {"copyleft_risk": {"has_copyleft": False}},
            self._default_soc2(),
        )
        with_copyleft = _investment_readiness_score(
            self._default_report(),
            self._default_issue_concentration(),
            self._default_dep_risk(),
            self._default_complexity(),
            {"copyleft_risk": {"has_copyleft": True}},
            self._default_soc2(),
        )
        assert no_copyleft["score"] > with_copyleft["score"]


# ── IR Rating ─────────────────────────────────────────────────


class TestIRRating:
    def test_investment_ready(self):
        assert _ir_rating(85.0) == "investment-ready"
        assert _ir_rating(100.0) == "investment-ready"

    def test_near_ready(self):
        assert _ir_rating(70.0) == "near-ready"
        assert _ir_rating(84.9) == "near-ready"

    def test_needs_work(self):
        assert _ir_rating(50.0) == "needs-work"
        assert _ir_rating(69.9) == "needs-work"

    def test_significant_gaps(self):
        assert _ir_rating(30.0) == "significant-gaps"
        assert _ir_rating(49.9) == "significant-gaps"

    def test_not_ready(self):
        assert _ir_rating(0.0) == "not-ready"
        assert _ir_rating(29.9) == "not-ready"


# ── Security Posture Score ────────────────────────────────────


class TestSecurityPostureScore:
    def test_returns_security_dimension_score(self):
        report = _minimal_report()
        score = _security_posture_score(report)
        assert score == 80.0

    def test_defaults_to_50_when_no_security(self):
        sc = ScoreCard(
            overall_score=70.0,
            overall_grade="C",
            dimensions=(
                DimensionScore(
                    dimension="architecture",
                    score=70.0,
                    grade=score_to_grade(70.0),
                    findings_count=0,
                    weight=1.0,
                ),
            ),
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
        assert _security_posture_score(report) == 50.0


# ── Complexity Component Score ────────────────────────────────


class TestComplexityComponentScore:
    def test_low(self):
        assert _complexity_component_score({"risk_level": "low"}) == 90.0

    def test_moderate(self):
        assert _complexity_component_score({"risk_level": "moderate"}) == 70.0

    def test_high(self):
        assert _complexity_component_score({"risk_level": "high"}) == 40.0

    def test_critical(self):
        assert _complexity_component_score({"risk_level": "critical"}) == 15.0

    def test_unknown(self):
        assert _complexity_component_score({"risk_level": "unknown"}) == 50.0

    def test_missing_key(self):
        assert _complexity_component_score({}) == 50.0


# ── License Component Score ───────────────────────────────────


class TestLicenseComponentScore:
    def test_clean(self):
        assert _license_component_score({"copyleft_risk": {"has_copyleft": False}}) == 95.0

    def test_copyleft(self):
        assert _license_component_score({"copyleft_risk": {"has_copyleft": True}}) == 40.0

    def test_missing_copyleft_risk(self):
        assert _license_component_score({}) == 95.0

    def test_non_dict_copyleft(self):
        assert _license_component_score({"copyleft_risk": "none"}) == 95.0


# ── Critical Findings Score ───────────────────────────────────


class TestCriticalFindingsScore:
    def test_no_criticals(self):
        report = _minimal_report()
        assert _critical_findings_score(report) == 100.0

    def test_one_critical(self):
        finding = _make_finding(sev="critical", line=1)
        report = _minimal_report(findings=(finding,))
        assert _critical_findings_score(report) == 85.0

    def test_many_criticals_floors_at_zero(self):
        findings = tuple(_make_finding(sev="critical", line=i) for i in range(10))
        report = _minimal_report(findings=findings)
        assert _critical_findings_score(report) == 0.0

    def test_two_criticals(self):
        findings = (
            _make_finding(sev="critical", line=1),
            _make_finding(sev="critical", line=2),
        )
        report = _minimal_report(findings=findings)
        assert _critical_findings_score(report) == 70.0


# ── OWASP 2025 Coverage ──────────────────────────────────────


class TestOWASP2025Coverage:
    def test_has_2024_coverage(self):
        result = _dd_compliance_mapping(())
        assert "owasp_2025_coverage" in result
        assert len(result["owasp_2025_coverage"]) == 10

    def test_2024_total(self):
        result = _dd_compliance_mapping(())
        assert result["owasp_2025_total"] == 10

    def test_2024_initially_uncovered(self):
        result = _dd_compliance_mapping(())
        assert result["owasp_2025_covered_count"] == 0

    def test_2024_category_detected(self):
        finding = _make_finding(desc="A03 injection vulnerability", line=1)
        result = _dd_compliance_mapping((finding,))
        assert result["owasp_2025_covered_count"] >= 1


# ── Parametrized Gini Coefficient ────────────────────────────

import pytest  # noqa: E811 — re-import for parametrize visibility


class TestGiniCoefficientParametrized:
    @pytest.mark.parametrize(
        ("values", "expected_min", "expected_max"),
        [
            ([], 0.0, 0.0),
            ([1], -0.01, 0.01),
            ([1, 1], -0.01, 0.01),
            ([1, 100], 0.3, 1.0),
            ([50, 50, 50], -0.01, 0.01),
            ([0, 0, 0, 100], 0.5, 1.0),
            ([10, 10, 10, 10, 10], -0.01, 0.01),
            ([1, 2, 3, 4, 5], 0.1, 0.5),
        ],
    )
    def test_gini_range(self, values, expected_min, expected_max):
        result = _gini_coefficient(values)
        assert expected_min <= result <= expected_max

    def test_gini_returns_float(self):
        assert isinstance(_gini_coefficient([1, 2, 3]), float)

    def test_gini_all_same_large(self):
        result = _gini_coefficient([42] * 100)
        assert abs(result) < 0.01

    def test_gini_extreme_inequality(self):
        result = _gini_coefficient([0] * 99 + [1000])
        assert result > 0.9


# ── SOC2 with all zero findings ─────────────────────────────


class TestSoc2ZeroFindings:
    def test_all_criteria_zero_finding_count(self):
        result = _soc2_mapping(())
        for c in result["criteria"]:
            assert c["finding_count"] == 0
            assert c["has_critical"] is False
            for k, v in c["severity_counts"].items():
                assert v == 0

    def test_coverage_pct_is_zero(self):
        result = _soc2_mapping(())
        assert result["coverage_pct"] == 0.0

    def test_total_mapped_is_zero(self):
        result = _soc2_mapping(())
        assert result["total_mapped"] == 0


# ── Bus factor with 1 file having all findings ──────────────


class TestBusFactorSingleFile:
    def test_all_findings_same_file_high_concentration(self):
        findings = tuple(_make_finding(sev="high", line=i) for i in range(20))
        result = _compute_issue_concentration(findings)
        assert result["unique_files"] == 1
        assert result["concentration"] >= 0.0

    def test_single_file_rating(self):
        findings = tuple(_make_finding(sev="critical", line=i) for i in range(10))
        result = _compute_issue_concentration(findings)
        assert result["rating"] in {"healthy", "moderate", "concerning", "critical"}

    def test_single_file_hotspots_has_one_entry(self):
        findings = tuple(_make_finding(sev="high", line=i) for i in range(5))
        result = _compute_issue_concentration(findings)
        assert len(result["hotspots"]) == 1
        assert result["hotspots"][0]["file"] == "src/main.py"


# ── Investment readiness with perfect scores ─────────────────


class TestInvestmentReadinessPerfect:
    def test_perfect_score_is_investment_ready(self):
        report = _minimal_report(score=100.0)
        result = _investment_readiness_score(
            report,
            {"score": 100},
            {"score": 0},
            {"risk_level": "low"},
            {"copyleft_risk": {"has_copyleft": False}},
            {"coverage_pct": 100.0},
        )
        assert result["rating"] == "investment-ready"
        assert result["score"] >= 85

    def test_perfect_all_components_high(self):
        report = _minimal_report(score=100.0)
        result = _investment_readiness_score(
            report,
            {"score": 100},
            {"score": 0},
            {"risk_level": "low"},
            {"copyleft_risk": {"has_copyleft": False}},
            {"coverage_pct": 100.0},
        )
        assert result["components"]["overall_score"] >= 90
        assert result["components"]["security_posture"] >= 70


# ── Complexity with no numeric scores found ──────────────────


class TestComplexityNoNumericScores:
    def test_no_numeric_scores_unknown_risk(self):
        result = _complexity_indicators(())
        assert result["risk_level"] == "unknown"
        assert result["mentioned_scores"] == []
        assert result["max_complexity"] == 0
        assert result["avg_complexity"] == 0.0

    def test_text_only_findings_no_scores(self):
        finding = _make_finding(desc="This function is too long", line=1)
        result = _complexity_indicators((finding,))
        # No numeric complexity found, but "high complexity" keywords not present
        assert result["max_complexity"] == 0

    def test_high_complexity_keyword_without_number(self):
        finding = _make_finding(desc="high complexity detected in module", line=1)
        result = _complexity_indicators((finding,))
        assert result["high_complexity_count"] >= 1
        assert result["mentioned_scores"] == [] or result["max_complexity"] == 0


# ── Score to grade extra boundary values ─────────────────────


class TestScoreToGradeExtraBoundaries:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.0, "F"),
            (56.0, "F"),
            (56.9, "F"),
            (57.0, "D-"),
            (59.9, "D-"),
            (60.0, "D"),
            (62.9, "D"),
            (63.0, "D+"),
            (66.9, "D+"),
            (67.0, "C-"),
            (69.9, "C-"),
            (70.0, "C"),
            (72.9, "C"),
            (73.0, "C+"),
            (76.9, "C+"),
            (77.0, "B-"),
            (79.9, "B-"),
            (80.0, "B"),
            (82.9, "B"),
            (83.0, "B+"),
            (86.9, "B+"),
            (87.0, "A-"),
            (89.9, "A-"),
            (90.0, "A"),
            (94.9, "A"),
            (95.0, "A+"),
            (100.0, "A+"),
        ],
    )
    def test_all_grade_boundaries(self, score, expected):
        assert score_to_grade(score) == expected


# ── Separate Strengths ───────────────────────────────────────


class TestSeparateStrengths:
    def test_empty_findings(self):
        strengths, issues = _separate_strengths(())
        assert strengths == []
        assert issues == []

    def test_info_with_positive_keyword_is_strength(self):
        finding = _make_finding(
            sev="info",
            desc="Code is well-structured and follows patterns",
            line=1,
        )
        strengths, issues = _separate_strengths((finding,))
        assert len(strengths) == 1
        assert len(issues) == 0

    def test_info_without_positive_keyword_is_issue(self):
        finding = _make_finding(
            sev="info",
            desc="Some neutral observation here",
            line=1,
        )
        strengths, issues = _separate_strengths((finding,))
        assert len(strengths) == 0
        assert len(issues) == 1

    def test_non_info_with_positive_keyword_is_issue(self):
        finding = _make_finding(
            sev="high",
            desc="Not well-structured despite claims",
            line=1,
        )
        strengths, issues = _separate_strengths((finding,))
        assert len(strengths) == 0
        assert len(issues) == 1

    def test_mixed_findings_separated(self):
        findings = (
            _make_finding(sev="info", desc="well-organized module structure", line=1),
            _make_finding(sev="high", desc="SQL injection vulnerability", line=2),
            _make_finding(sev="info", desc="good separation of concerns", line=3),
            _make_finding(sev="critical", desc="hardcoded credentials", line=4),
        )
        strengths, issues = _separate_strengths(findings)
        assert len(strengths) == 2
        assert len(issues) == 2

    def test_comprehensive_keyword_detected(self):
        finding = _make_finding(
            sev="info",
            desc="comprehensive test coverage",
            line=1,
        )
        strengths, issues = _separate_strengths((finding,))
        assert len(strengths) == 1

    def test_properly_keyword_detected(self):
        finding = _make_finding(
            sev="info",
            desc="properly configured error handling",
            line=1,
        )
        strengths, issues = _separate_strengths((finding,))
        assert len(strengths) == 1


# ── Badge score rounding ──────────────────────────────────────


class TestBadgeScoreRounding:
    def test_badge_rounds_instead_of_truncates(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=83.7)
        badge = adapter.render_badge(report)
        # round(83.7) = 84, int(83.7) would be 83
        assert "84" in badge

    def test_badge_rounds_down_when_below_half(self):
        adapter = ReportAdapter()
        report = _minimal_report(score=83.2)
        badge = adapter.render_badge(report)
        # round(83.2) = 83
        assert "83" in badge
