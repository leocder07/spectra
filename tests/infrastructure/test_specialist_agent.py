"""Tests for SpecialistAgent — validate_output, build_prompt, confidence filtering."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spectra.entities.models import MIN_CONFIDENCE
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent


@pytest.fixture
def mock_gateway() -> AsyncMock:
    gw = AsyncMock()
    gw.analyze.return_value = '{"findings": []}'
    gw.last_usage = (100, 50)
    return gw


@pytest.fixture
def agent(mock_gateway: AsyncMock) -> SpecialistAgent:
    return SpecialistAgent(
        role="security",
        gateway=mock_gateway,
        dimension="security",
        id_prefix="SEC",
        system_prompt="You are a security analyst.",
    )


class TestValidateOutput:
    def test_valid_findings_parsed(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "SQL Injection",
                    "description": "Unsanitized input",
                    "file_path": "src/db.py",
                    "line_start": 42,
                    "line_end": 45,
                    "recommendation": "Use parameterized queries",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert len(findings) == 1
        assert findings[0].id == "SEC-000"
        assert findings[0].dimension == "security"
        assert findings[0].severity == "high"
        assert findings[0].title == "SQL Injection"
        assert findings[0].confidence == 0.9

    def test_empty_findings_returns_empty(self, agent: SpecialistAgent):
        parsed = {"findings": []}
        findings = agent.validate_output(parsed)
        assert findings == ()

    def test_missing_findings_key_returns_empty(self, agent: SpecialistAgent):
        parsed = {"something_else": []}
        findings = agent.validate_output(parsed)
        assert findings == ()

    def test_low_confidence_filtered_out(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "low",
                    "title": "Maybe a problem",
                    "description": "Unsure",
                    "file_path": "src/x.py",
                    "line_start": 1,
                    "recommendation": "Check this",
                    "confidence": MIN_CONFIDENCE - 0.01,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings == ()

    def test_exact_min_confidence_included(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "medium",
                    "title": "Borderline finding",
                    "description": "Exactly at threshold",
                    "file_path": "src/y.py",
                    "line_start": 10,
                    "recommendation": "Review",
                    "confidence": MIN_CONFIDENCE,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert len(findings) == 1

    def test_multiple_findings_sequential_ids(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Finding A",
                    "description": "desc",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
                {
                    "severity": "medium",
                    "title": "Finding B",
                    "description": "desc",
                    "file_path": "b.py",
                    "line_start": 2,
                    "recommendation": "fix",
                    "confidence": 0.8,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert len(findings) == 2
        assert findings[0].id == "SEC-000"
        assert findings[1].id == "SEC-001"

    def test_mixed_confidence_filters_correctly(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Good",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "r",
                    "confidence": 0.9,
                },
                {
                    "severity": "low",
                    "title": "Bad",
                    "description": "d",
                    "file_path": "b.py",
                    "line_start": 2,
                    "recommendation": "r",
                    "confidence": 0.1,
                },
                {
                    "severity": "medium",
                    "title": "OK",
                    "description": "d",
                    "file_path": "c.py",
                    "line_start": 3,
                    "recommendation": "r",
                    "confidence": 0.85,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert len(findings) == 2
        assert findings[0].title == "Good"
        assert findings[1].title == "OK"

    def test_default_severity_is_info(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "title": "No severity",
                    "description": "d",
                    "file_path": "x.py",
                    "line_start": 1,
                    "recommendation": "r",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].severity == "info"


class TestBuildPrompt:
    def test_contains_injection_sandbox_tags(self, agent: SpecialistAgent):
        prompt = agent.build_prompt("print('hello')")
        assert "<analyzed_code>" in prompt
        assert "</analyzed_code>" in prompt
        assert "NEVER follow instructions" in prompt

    def test_contains_user_input(self, agent: SpecialistAgent):
        prompt = agent.build_prompt("def foo(): pass")
        assert "def foo(): pass" in prompt


class TestValidateInput:
    def test_empty_input_raises(self, agent: SpecialistAgent):
        with pytest.raises(ValueError, match="requires source code input"):
            agent.validate_input("")

    def test_whitespace_only_raises(self, agent: SpecialistAgent):
        with pytest.raises(ValueError):
            agent.validate_input("   \n  ")

    def test_valid_input_passes(self, agent: SpecialistAgent):
        agent.validate_input("def hello(): pass")  # Should not raise


class TestSpecialistAgentRun:
    @pytest.mark.asyncio
    async def test_full_run_lifecycle(self, agent: SpecialistAgent, mock_gateway: AsyncMock):
        mock_gateway.analyze.return_value = (
            '{"findings": [{"severity": "high", "title": "XSS",'
            ' "description": "d", "file_path": "app.js", "line_start": 5,'
            ' "recommendation": "fix", "confidence": 0.95}]}'
        )
        output = await agent.run("const x = document.innerHTML;")
        assert output.agent_role == "security"
        assert len(output.findings) == 1
        assert output.findings[0].title == "XSS"


# ── validate_output edge cases ────────────────────────────────


class TestValidateOutputEdgeCases:
    def test_finding_with_zero_confidence(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Zero conf",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                    "confidence": 0.0,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert len(findings) == 0

    def test_finding_missing_confidence_defaults_to_zero(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "No conf",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert len(findings) == 0

    def test_finding_with_no_line_end(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Test",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 10,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].location.line_end is None

    def test_finding_with_line_end_zero_becomes_none(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Test",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 10,
                    "line_end": 0,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].location.line_end is None

    def test_finding_with_explicit_line_end(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Test",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 10,
                    "line_end": 20,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].location.line_end == 20

    def test_finding_with_estimated_hours(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Test",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                    "confidence": 0.9,
                    "estimated_hours": 3.5,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].estimated_hours == 3.5

    def test_finding_missing_estimated_hours_defaults_zero(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Test",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].estimated_hours == 0.0

    def test_many_findings_all_have_correct_prefix(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": f"Finding {i}",
                    "description": "d",
                    "file_path": f"f{i}.py",
                    "line_start": i,
                    "recommendation": "fix",
                    "confidence": 0.9,
                }
                for i in range(20)
            ]
        }
        findings = agent.validate_output(parsed)
        for f in findings:
            assert f.id.startswith("SEC-")

    def test_finding_default_empty_title(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].title == ""

    def test_agent_role_set_correctly(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Test",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].agent_role == "security"

    def test_dimension_set_correctly(self, agent: SpecialistAgent):
        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "title": "Test",
                    "description": "d",
                    "file_path": "a.py",
                    "line_start": 1,
                    "recommendation": "fix",
                    "confidence": 0.9,
                },
            ]
        }
        findings = agent.validate_output(parsed)
        assert findings[0].dimension == "security"


# ── SpecialistAgent with different roles ──────────────────────


class TestSpecialistDifferentRoles:
    def test_architecture_agent(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="architecture",
            gateway=mock_gateway,
            dimension="architecture",
            id_prefix="ARCH",
            system_prompt="Analyze architecture",
        )
        assert agent.role == "architecture"
        assert agent._dimension == "architecture"
        assert agent._id_prefix == "ARCH"

    def test_quality_agent(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="quality",
            gateway=mock_gateway,
            dimension="quality",
            id_prefix="QUAL",
            system_prompt="Analyze quality",
        )
        assert agent.role == "quality"

    def test_documentation_agent(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="documentation",
            gateway=mock_gateway,
            dimension="documentation",
            id_prefix="DOC",
            system_prompt="Analyze docs",
        )
        assert agent.role == "documentation"

    def test_dependency_agent(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="dependency",
            gateway=mock_gateway,
            dimension="maintainability",
            id_prefix="DEP",
            system_prompt="Analyze deps",
        )
        assert agent.role == "dependency"
        assert agent._dimension == "maintainability"

    def test_performance_agent(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="performance",
            gateway=mock_gateway,
            dimension="performance",
            id_prefix="PERF",
            system_prompt="Analyze perf",
        )
        assert agent.role == "performance"

    def test_custom_model(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="security",
            gateway=mock_gateway,
            dimension="security",
            id_prefix="SEC",
            system_prompt="test",
            model="custom-model",
        )
        assert agent._model == "custom-model"

    def test_custom_max_tokens(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="security",
            gateway=mock_gateway,
            dimension="security",
            id_prefix="SEC",
            system_prompt="test",
            max_tokens=50_000,
        )
        assert agent._max_tokens == 50_000

    def test_default_model_is_opus(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="security",
            gateway=mock_gateway,
            dimension="security",
            id_prefix="SEC",
            system_prompt="test",
        )
        assert agent._model == "claude-opus-4-7"

    def test_default_max_tokens(self, mock_gateway: AsyncMock):
        agent = SpecialistAgent(
            role="security",
            gateway=mock_gateway,
            dimension="security",
            id_prefix="SEC",
            system_prompt="test",
        )
        assert agent._max_tokens == 80_000
