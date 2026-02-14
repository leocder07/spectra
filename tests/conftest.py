"""Shared test fixtures for the Spectra test suite."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spectra.entities.enums import AgentRole, Dimension
from spectra.entities.models import (
    AgentOutput,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)


@pytest.fixture
def mock_llm_gateway() -> AsyncMock:
    """Mock LLMGateway that returns predefined agent outputs."""
    gateway = AsyncMock()
    gateway.analyze.return_value = '{"findings": [], "dimension_score": 75}'
    return gateway


@pytest.fixture
def mock_git_port() -> AsyncMock:
    """Mock GitPort that returns a test file tree."""
    port = AsyncMock()
    port.clone.return_value = None
    port.get_file_tree.return_value = ["src/main.py", "README.md"]
    port.read_file.return_value = "# test content"
    return port


@pytest.fixture
def mock_token_port() -> AsyncMock:
    """Mock TokenPort for token counting."""
    port = AsyncMock()
    port.count.return_value = 100
    port.fits_budget.return_value = True
    return port


@pytest.fixture
def sample_file_location() -> FileLocation:
    """A sample FileLocation value object."""
    return FileLocation(file_path="src/main.py", line_start=10, line_end=20)


@pytest.fixture
def sample_finding() -> Finding:
    """A sample Finding for testing."""
    return Finding(
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


@pytest.fixture
def sample_finding_factory():
    """Factory to create Finding instances with overrides."""

    def _create(
        *,
        id: str = "TEST-001",
        dimension: Dimension = "security",
        severity: str = "high",
        title: str = "Test finding",
        description: str = "Test description",
        file_path: str = "src/main.py",
        line_start: int = 10,
        recommendation: str = "Fix this",
        agent_role: AgentRole = "security",
        confidence: float = 0.9,
    ) -> Finding:
        return Finding(
            id=id,
            dimension=dimension,
            severity=severity,
            title=title,
            description=description,
            location=FileLocation(file_path=file_path, line_start=line_start),
            recommendation=recommendation,
            agent_role=agent_role,
            confidence=confidence,
        )

    return _create


@pytest.fixture
def make_agent():
    """Factory to create mock AnalysisAgent instances for pipeline tests."""

    def _create(
        role: AgentRole,
        findings: tuple[Finding, ...] = (),
        error: Exception | None = None,
    ) -> AsyncMock:
        agent = AsyncMock()
        agent.role = role
        if error:
            agent.run.side_effect = error
        else:
            agent.run.return_value = AgentOutput(
                agent_role=role,
                findings=findings,
                tokens_used=500,
                duration_seconds=1.0,
                raw_response="{}",
            )
        return agent

    return _create


@pytest.fixture
def make_finding():
    """Factory for Finding instances in pipeline/integration tests."""

    def _create(
        dim: str = "security",
        sev: str = "high",
        line: int = 10,
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
            id=f"F-{dim}-{line}",
            dimension=dim,
            severity=sev,
            title=f"{sev} {dim} finding",
            description="Test",
            location=FileLocation(file_path="src/main.py", line_start=line),
            recommendation="Fix",
            agent_role=role_map.get(dim, "architecture"),
            confidence=0.8,
        )

    return _create


@pytest.fixture
def sample_scorecard() -> ScoreCard:
    """A sample ScoreCard with all 6 dimensions."""
    dimensions = (
        DimensionScore(dimension="architecture", score=85.0, grade=score_to_grade(85.0), findings_count=3, weight=0.25),
        DimensionScore(dimension="security", score=90.0, grade=score_to_grade(90.0), findings_count=2, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade=score_to_grade(78.0), findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade=score_to_grade(70.0), findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade=score_to_grade(82.0), findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade=score_to_grade(88.0), findings_count=1, weight=0.10),
    )
    overall = sum(d.score * d.weight for d in dimensions)
    return ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dimensions,
        total_findings=18,
    )


@pytest.fixture
def sample_scorecard_factory():
    """Factory to create ScoreCard instances with custom dimension scores."""

    def _create(
        *,
        arch: float = 85.0,
        sec: float = 90.0,
        qual: float = 78.0,
        doc: float = 70.0,
        maint: float = 82.0,
        perf: float = 88.0,
    ) -> ScoreCard:
        dims = (
            DimensionScore(dimension="architecture", score=arch, grade=score_to_grade(arch), findings_count=3, weight=0.25),
            DimensionScore(dimension="security", score=sec, grade=score_to_grade(sec), findings_count=2, weight=0.25),
            DimensionScore(dimension="quality", score=qual, grade=score_to_grade(qual), findings_count=5, weight=0.20),
            DimensionScore(dimension="documentation", score=doc, grade=score_to_grade(doc), findings_count=4, weight=0.10),
            DimensionScore(dimension="maintainability", score=maint, grade=score_to_grade(maint), findings_count=3, weight=0.10),
            DimensionScore(dimension="performance", score=perf, grade=score_to_grade(perf), findings_count=1, weight=0.10),
        )
        overall = sum(d.score * d.weight for d in dims)
        return ScoreCard(
            overall_score=overall,
            overall_grade=score_to_grade(overall),
            dimensions=dims,
            total_findings=18,
        )

    return _create
