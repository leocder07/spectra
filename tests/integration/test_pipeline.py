"""Integration tests — wire real adapters with mocked LLM gateway."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)
from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent
from spectra.infrastructure.report_adapter import ReportAdapter


def _mock_gateway_with_response(response: str) -> AsyncMock:
    gw = AsyncMock()
    gw.analyze.return_value = response
    gw.analyze_with_thinking.return_value = response
    gw.last_usage = (500, 200)
    return gw


def _valid_specialist_response(n_findings: int = 2) -> str:
    findings = []
    for i in range(n_findings):
        findings.append(
            {
                "severity": "high",
                "title": f"Finding {i}",
                "description": f"Description {i}",
                "file_path": "src/main.py",
                "line_start": i + 1,
                "line_end": i + 5,
                "recommendation": f"Fix {i}",
                "confidence": 0.9,
                "estimated_hours": 1.0,
            }
        )
    return json.dumps({"findings": findings, "dimension_score": 75})


def _valid_critique_response() -> str:
    return json.dumps(
        {
            "validated_findings": [],
            "rejected_findings": [],
            "severity_adjustments": [],
            "cross_cutting_insights": ["Finding A and B are related"],
        }
    )


def _minimal_report(findings: tuple[Finding, ...] = ()) -> AnalysisReport:
    dims = (
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
    sc = ScoreCard(overall_score=83.5, overall_grade="B+", dimensions=dims, total_findings=len(findings))
    return AnalysisReport(
        repo_url="https://github.com/test/repo",
        repo_name="repo",
        score_card=sc,
        findings=findings,
        analysis_duration_seconds=5.0,
        total_tokens_used=1000,
        total_cost_usd=0.01,
        agents_used=("architecture", "security"),
    )


# ── AgentFactory Integration ─────────────────────────────────


class TestAgentFactoryIntegration:
    def test_creates_meta_prompter(self):
        gw = _mock_gateway_with_response("{}")
        factory = AgentFactory(gateway=gw)
        agent = factory.create("meta_prompter")
        assert agent.role == "meta_prompter"

    def test_creates_critique_agent(self):
        gw = _mock_gateway_with_response("{}")
        factory = AgentFactory(gateway=gw)
        agent = factory.create("critique")
        assert agent.role == "critique"

    def test_creates_six_specialists(self):
        gw = _mock_gateway_with_response("{}")
        factory = AgentFactory(gateway=gw)
        specialists = factory.create_specialists()
        assert len(specialists) == 6

    def test_specialist_roles_correct(self):
        gw = _mock_gateway_with_response("{}")
        factory = AgentFactory(gateway=gw)
        specialists = factory.create_specialists()
        roles = {s.role for s in specialists}
        assert roles == {"architecture", "security", "quality", "documentation", "dependency", "performance"}


# ── SpecialistAgent Integration ──────────────────────────────


class TestSpecialistAgentIntegration:
    @pytest.mark.asyncio
    async def test_specialist_run_returns_output(self):
        gw = _mock_gateway_with_response(_valid_specialist_response(2))
        agent = SpecialistAgent(
            role="security",
            gateway=gw,
            dimension="security",
            id_prefix="sec",
            system_prompt="Analyze security",
        )
        result = await agent.run("def foo(): pass")
        assert result.agent_role == "security"
        assert len(result.findings) == 2

    @pytest.mark.asyncio
    async def test_specialist_filters_low_confidence(self):
        response = json.dumps(
            {
                "findings": [
                    {
                        "severity": "high",
                        "title": "Low conf",
                        "description": "desc",
                        "file_path": "a.py",
                        "line_start": 1,
                        "recommendation": "fix",
                        "confidence": 0.3,
                    },
                    {
                        "severity": "high",
                        "title": "High conf",
                        "description": "desc",
                        "file_path": "b.py",
                        "line_start": 2,
                        "recommendation": "fix",
                        "confidence": 0.9,
                    },
                ],
                "dimension_score": 80,
            }
        )
        gw = _mock_gateway_with_response(response)
        agent = SpecialistAgent(
            role="quality",
            gateway=gw,
            dimension="quality",
            id_prefix="qual",
            system_prompt="Analyze quality",
        )
        result = await agent.run("def foo(): pass")
        assert len(result.findings) == 1
        assert result.findings[0].title == "High conf"

    @pytest.mark.asyncio
    async def test_specialist_with_no_findings(self):
        response = json.dumps({"findings": [], "dimension_score": 95})
        gw = _mock_gateway_with_response(response)
        agent = SpecialistAgent(
            role="architecture",
            gateway=gw,
            dimension="architecture",
            id_prefix="arch",
            system_prompt="Analyze arch",
        )
        result = await agent.run("def foo(): pass")
        assert len(result.findings) == 0

    @pytest.mark.asyncio
    async def test_specialist_empty_input_raises(self):
        gw = _mock_gateway_with_response("{}")
        agent = SpecialistAgent(
            role="security",
            gateway=gw,
            dimension="security",
            id_prefix="sec",
            system_prompt="Analyze",
        )
        with pytest.raises(ValueError, match="requires source code input"):
            await agent.run("")

    @pytest.mark.asyncio
    async def test_specialist_dimension_score_captured(self):
        response = json.dumps({"findings": [], "dimension_score": 88})
        gw = _mock_gateway_with_response(response)
        agent = SpecialistAgent(
            role="performance",
            gateway=gw,
            dimension="performance",
            id_prefix="perf",
            system_prompt="Analyze perf",
        )
        result = await agent.run("def foo(): pass")
        assert result.dimension_score == 88.0


# ── ReportAdapter Integration ─────────────────────────────────


class TestReportAdapterIntegration:
    def test_render_creates_valid_html(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "<html" in content.lower() or "<!doctype" in content.lower()
        Path(path).unlink()

    def test_render_with_findings(self):
        finding = Finding(
            id="sec-001",
            dimension="security",
            severity="critical",
            title="Hardcoded secret",
            description="API key exposed in config.py",
            location=FileLocation(file_path="src/config.py", line_start=12),
            recommendation="Use environment variables",
            agent_role="security",
            confidence=0.95,
            estimated_hours=2.0,
        )
        report = _minimal_report(findings=(finding,))
        adapter = ReportAdapter()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 100
        Path(path).unlink()

    def test_badge_generation_integrated(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        badge = adapter.render_badge(report)
        assert "Spectra" in badge
        assert "<svg" in badge

    def test_dd_frameworks_rendered(self):
        adapter = ReportAdapter()
        finding = Finding(
            id="sec-001",
            dimension="security",
            severity="high",
            title="A01 access control",
            description="Broken access control vulnerability CWE-79",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="Fix A03 injection",
            agent_role="security",
            confidence=0.9,
            estimated_hours=3.0,
        )
        report = _minimal_report(findings=(finding,))
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 500
        Path(path).unlink()


# ── End-to-end DD Framework Integration ───────────────────────


class TestDDFrameworkIntegration:
    def test_build_dd_frameworks_all_keys(self):
        adapter = ReportAdapter()
        report = _minimal_report()
        result = adapter._build_dd_frameworks(report)
        assert "dd_compliance" in result
        assert "soc2" in result
        assert "bus_factor" in result
        assert "license_compliance" in result
        assert "complexity" in result
        assert "dependency_risk" in result
        assert "investment_readiness" in result

    def test_build_dd_frameworks_with_empty_findings(self):
        adapter = ReportAdapter()
        report = _minimal_report(findings=())
        result = adapter._build_dd_frameworks(report)
        assert result["bus_factor"]["score"] == 100
        assert result["dependency_risk"]["score"] == 0

    def test_build_dd_frameworks_with_complex_findings(self):
        findings = (
            Finding(
                id="sec-001",
                dimension="security",
                severity="critical",
                title="authentication bypass",
                description="A01 broken access control CWE-79",
                location=FileLocation(file_path="src/auth.py", line_start=1),
                recommendation="Fix A03 injection",
                agent_role="security",
                confidence=0.9,
                estimated_hours=5.0,
            ),
            Finding(
                id="dep-001",
                dimension="maintainability",
                severity="high",
                title="outdated deprecated dependency",
                description="GPL-3 licensed vulnerable package",
                location=FileLocation(file_path="src/deps.py", line_start=1),
                recommendation="update unmaintained lib",
                agent_role="dependency",
                confidence=0.9,
                estimated_hours=3.0,
            ),
            Finding(
                id="qual-001",
                dimension="quality",
                severity="medium",
                title="high cyclomatic complexity",
                description="cyclomatic complexity: 25",
                location=FileLocation(file_path="src/logic.py", line_start=1),
                recommendation="Refactor function",
                agent_role="quality",
                confidence=0.85,
                estimated_hours=2.0,
            ),
        )
        adapter = ReportAdapter()
        report = _minimal_report(findings=findings)
        result = adapter._build_dd_frameworks(report)

        # OWASP should detect categories
        assert result["dd_compliance"]["owasp_covered_count"] >= 1
        # SOC2 should have coverage
        assert result["soc2"]["total_mapped"] >= 1
        # License should detect GPL
        assert result["license_compliance"]["copyleft_risk"]["has_copyleft"] is True
        # Complexity should detect numeric
        assert result["complexity"]["max_complexity"] == 25
        # Dependency should detect risk keywords
        assert result["dependency_risk"]["score"] > 0


# ── Report rendering edge cases ──────────────────────────────


class TestReportRenderingEdgeCases:
    def test_render_with_mermaid_finding(self):
        finding = Finding(
            id="arch-001",
            dimension="architecture",
            severity="medium",
            title="Architecture diagram",
            description="Here is the diagram:\n```mermaid\ngraph LR\nA-->B\n```",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="Review diagram",
            agent_role="architecture",
            confidence=0.9,
            estimated_hours=1.0,
        )
        adapter = ReportAdapter()
        report = _minimal_report(findings=(finding,))
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 0
        Path(path).unlink()

    def test_render_with_very_long_description(self):
        finding = Finding(
            id="qual-001",
            dimension="quality",
            severity="low",
            title="Long description",
            description="A" * 10000,
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="B" * 5000,
            agent_role="quality",
            confidence=0.9,
            estimated_hours=0.5,
        )
        adapter = ReportAdapter()
        report = _minimal_report(findings=(finding,))
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 100
        Path(path).unlink()

    def test_render_with_all_severity_types(self):
        findings = tuple(
            Finding(
                id=f"F-{sev}-1",
                dimension="security",
                severity=sev,
                title=f"{sev} finding",
                description=f"A {sev} issue",
                location=FileLocation(file_path="src/main.py", line_start=i),
                recommendation="Fix",
                agent_role="security",
                confidence=0.9,
                estimated_hours=float(i),
            )
            for i, sev in enumerate(["critical", "high", "medium", "low", "info"], 1)
        )
        adapter = ReportAdapter()
        report = _minimal_report(findings=findings)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 500
        Path(path).unlink()

    def test_render_with_high_score(self):
        adapter = ReportAdapter()
        report = _minimal_report(
            findings=(),
        )
        # Create an A+ report
        dims = (
            DimensionScore(
                dimension="architecture", score=98.0, grade=score_to_grade(98.0), findings_count=0, weight=0.25
            ),
            DimensionScore(dimension="security", score=97.0, grade=score_to_grade(97.0), findings_count=0, weight=0.25),
            DimensionScore(dimension="quality", score=96.0, grade=score_to_grade(96.0), findings_count=0, weight=0.20),
            DimensionScore(
                dimension="documentation", score=95.0, grade=score_to_grade(95.0), findings_count=0, weight=0.10
            ),
            DimensionScore(
                dimension="maintainability", score=99.0, grade=score_to_grade(99.0), findings_count=0, weight=0.10
            ),
            DimensionScore(
                dimension="performance", score=98.0, grade=score_to_grade(98.0), findings_count=0, weight=0.10
            ),
        )
        sc = ScoreCard(overall_score=97.4, overall_grade="A+", dimensions=dims, total_findings=0)
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sc,
            findings=(),
            analysis_duration_seconds=5.0,
            total_tokens_used=1000,
            total_cost_usd=0.01,
            agents_used=("architecture", "security"),
        )
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "A+" in content
        Path(path).unlink()

    def test_render_with_f_grade(self):
        adapter = ReportAdapter()
        dims = (
            DimensionScore(dimension="architecture", score=30.0, grade="F", findings_count=10, weight=0.25),
            DimensionScore(dimension="security", score=20.0, grade="F", findings_count=15, weight=0.25),
            DimensionScore(dimension="quality", score=25.0, grade="F", findings_count=12, weight=0.20),
            DimensionScore(dimension="documentation", score=35.0, grade="F", findings_count=8, weight=0.10),
            DimensionScore(dimension="maintainability", score=40.0, grade="F", findings_count=6, weight=0.10),
            DimensionScore(dimension="performance", score=15.0, grade="F", findings_count=5, weight=0.10),
        )
        sc = ScoreCard(overall_score=26.5, overall_grade="F", dimensions=dims, total_findings=56)
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sc,
            findings=(),
            analysis_duration_seconds=5.0,
            total_tokens_used=1000,
            total_cost_usd=0.01,
            agents_used=("architecture", "security"),
        )
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        Path(path).unlink()

    def test_render_degraded_report(self):
        adapter = ReportAdapter()
        dims = (
            DimensionScore(dimension="quality", score=85.0, grade=score_to_grade(85.0), findings_count=2, weight=0.50),
            DimensionScore(
                dimension="documentation", score=80.0, grade=score_to_grade(80.0), findings_count=1, weight=0.50
            ),
        )
        sc = ScoreCard(overall_score=82.5, overall_grade="B", dimensions=dims, total_findings=3)
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sc,
            findings=(),
            analysis_duration_seconds=30.0,
            total_tokens_used=5000,
            total_cost_usd=0.50,
            agents_used=("quality", "documentation"),
            is_degraded=True,
            degraded_dimensions=("architecture", "security", "maintainability", "performance"),
        )
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        adapter.render(report, path)
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 100
        Path(path).unlink()
