"""Tests for JSON output format in the composition root."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

# Import enums first so Pydantic can resolve forward refs in models.
from spectra.entities.enums import (  # noqa: F401
    AgentRole,
    Dimension,
    Grade,
    Severity,
)
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)

# Resolve deferred Pydantic annotations (TYPE_CHECKING guard in models.py).
Finding.model_rebuild()
DimensionScore.model_rebuild()
ScoreCard.model_rebuild()
AnalysisReport.model_rebuild()

_ALL_AGENTS = (
    "architecture",
    "security",
    "quality",
    "documentation",
    "dependency",
    "performance",
)


def _dim(
    name: str,
    score: float = 85.0,
    count: int = 0,
    weight: float = 0.10,
) -> DimensionScore:
    return DimensionScore(
        dimension=name,
        score=score,
        grade=score_to_grade(score),
        findings_count=count,
        weight=weight,
    )


def _minimal_report() -> AnalysisReport:
    """Create a minimal AnalysisReport for JSON output tests."""
    finding = Finding(
        id="TEST-001",
        dimension="security",
        severity="high",
        title="Test finding",
        description="Test description",
        location=FileLocation(
            file_path="src/main.py",
            line_start=10,
        ),
        recommendation="Fix this",
        agent_role="security",
        confidence=0.9,
    )
    dimensions = (
        _dim("architecture", 85.0, 0, 0.25),
        _dim("security", 80.0, 1, 0.25),
        _dim("quality", 85.0, 0, 0.20),
        _dim("documentation", 85.0, 0, 0.10),
        _dim("maintainability", 85.0, 0, 0.10),
        _dim("performance", 85.0, 0, 0.10),
    )
    overall = sum(d.score * d.weight for d in dimensions)
    score_card = ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dimensions,
        total_findings=1,
    )
    return AnalysisReport(
        repo_url="https://github.com/test/repo",
        repo_name="repo",
        score_card=score_card,
        findings=(finding,),
        analysis_duration_seconds=5.0,
        total_tokens_used=1000,
        total_cost_usd=0.01,
        agents_used=_ALL_AGENTS,
        is_degraded=False,
        degraded_dimensions=(),
    )


class TestJsonOutput:
    """Verify JSON output produces valid JSON with all fields."""

    def test_model_dump_json_is_valid_json(self):
        report = _minimal_report()
        data = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        )
        parsed = json.loads(data)
        assert isinstance(parsed, dict)

    def test_json_contains_all_report_fields(self):
        report = _minimal_report()
        parsed = report.model_dump(mode="json")

        expected_keys = {
            "repo_url",
            "repo_name",
            "score_card",
            "findings",
            "analysis_duration_seconds",
            "total_tokens_used",
            "total_cost_usd",
            "agents_used",
            "is_degraded",
            "degraded_dimensions",
            "cross_cutting_insights",
        }
        assert expected_keys.issubset(parsed.keys())

    def test_json_output_is_not_html(self):
        report = _minimal_report()
        data = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        )
        assert "<html" not in data
        assert "<!DOCTYPE" not in data

    def test_json_written_to_file(self):
        report = _minimal_report()
        data = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        )

        with tempfile.NamedTemporaryFile(
            suffix=".json",
            delete=False,
        ) as f:
            path = f.name

        Path(path).write_text(data, encoding="utf-8")
        content = Path(path).read_text(encoding="utf-8")
        parsed = json.loads(content)

        assert parsed["repo_name"] == "repo"
        assert parsed["repo_url"] == "https://github.com/test/repo"
        assert parsed["total_tokens_used"] == 1000
        assert parsed["is_degraded"] is False
        assert len(parsed["findings"]) == 1
        assert parsed["findings"][0]["severity"] == "high"

        Path(path).unlink()

    def test_json_scorecard_structure(self):
        report = _minimal_report()
        parsed = report.model_dump(mode="json")
        sc = parsed["score_card"]

        assert "overall_score" in sc
        assert "overall_grade" in sc
        assert "dimensions" in sc
        assert len(sc["dimensions"]) == 6
        for dim in sc["dimensions"]:
            assert "dimension" in dim
            assert "score" in dim
            assert "grade" in dim
            assert "weight" in dim
