"""Tests for ReportAdapter — Jinja2 HTML report rendering."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)
from spectra.adapters.brand import build_verdict
from spectra.infrastructure.report_adapter import (
    ReportAdapter,
    _build_executive_summary,
    _critical_count,
    _sort_by_severity,
)


def _minimal_report(
    *,
    findings: tuple[Finding, ...] | None = None,
    score: float = 83.5,
) -> AnalysisReport:
    """Create a minimal AnalysisReport for rendering tests."""
    default_finding = Finding(
        id="TEST-001",
        dimension="security",
        severity="high",
        title="Test finding",
        description="Test description",
        location=FileLocation(file_path="src/main.py", line_start=10),
        recommendation="Fix this",
        agent_role="security",
        confidence=0.9,
    )
    if findings is None:
        findings = (default_finding,)
    dimensions = (
        DimensionScore(dimension="architecture", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.25),
        DimensionScore(dimension="security", score=80.0, grade=score_to_grade(80.0), findings_count=1, weight=0.25),
        DimensionScore(dimension="quality", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.20),
        DimensionScore(dimension="documentation", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.10),
        DimensionScore(dimension="maintainability", score=85.0, grade=score_to_grade(85.0), findings_count=0, weight=0.10),
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


# ── Helper functions ─────────────────────────────────────────


class TestSortBySeverity:
    def _finding(self, sev: str, line: int) -> Finding:
        return Finding(
            id=f"F-{sev}-{line}",
            dimension="security",
            severity=sev,
            title=f"{sev} finding",
            description="Test",
            location=FileLocation(file_path="src/main.py", line_start=line),
            recommendation="Fix",
            agent_role="security",
            confidence=0.8,
        )

    def test_sorts_critical_first(self):
        findings = [
            self._finding("low", 1),
            self._finding("critical", 2),
            self._finding("high", 3),
        ]
        sorted_f = _sort_by_severity(findings)
        assert sorted_f[0].severity == "critical"
        assert sorted_f[1].severity == "high"
        assert sorted_f[2].severity == "low"

    def test_full_severity_order(self):
        findings = [
            self._finding("info", 1),
            self._finding("medium", 2),
            self._finding("critical", 3),
            self._finding("low", 4),
            self._finding("high", 5),
        ]
        sorted_f = _sort_by_severity(findings)
        severities = [f.severity for f in sorted_f]
        assert severities == ["critical", "high", "medium", "low", "info"]

    def test_empty_list(self):
        assert _sort_by_severity([]) == []


class TestCriticalCount:
    def _finding(self, sev: str, line: int) -> Finding:
        return Finding(
            id=f"F-{sev}-{line}",
            dimension="security",
            severity=sev,
            title=f"{sev} finding",
            description="Test",
            location=FileLocation(file_path="src/main.py", line_start=line),
            recommendation="Fix",
            agent_role="security",
            confidence=0.8,
        )

    def test_counts_criticals(self):
        findings = (
            self._finding("critical", 1),
            self._finding("high", 2),
            self._finding("critical", 3),
        )
        assert _critical_count(findings) == 2

    def test_no_criticals(self):
        findings = (self._finding("high", 1), self._finding("low", 2))
        assert _critical_count(findings) == 0

    def test_empty(self):
        assert _critical_count(()) == 0


class TestBuildVerdict:
    def test_includes_grade_and_score(self):
        report = _minimal_report()
        verdict = build_verdict(report)
        assert "B+" in verdict
        assert "84" in verdict or "83" in verdict

    def test_identifies_strengths_and_gaps(self):
        report = _minimal_report()
        verdict = build_verdict(report)
        # With default dims: architecture/quality/documentation/maintainability/performance = 85, security = 80
        # Top is one of the 85-score dims, bottom is security at 80
        assert "strong" in verdict or "gaps" in verdict or "scores" in verdict

    def test_empty_dimensions(self):
        sc = ScoreCard(
            overall_score=0.0, overall_grade="F",
            dimensions=(), total_findings=0,
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
        critical_finding = Finding(
            id="CRIT-1",
            dimension="security",
            severity="critical",
            title="Critical vulnerability",
            description="Bad",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="Fix now",
            agent_role="security",
            confidence=0.95,
        )
        report = _minimal_report(findings=(critical_finding,))
        summary = _build_executive_summary(report)
        assert summary["critical_count"] == 1
