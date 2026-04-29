"""Tests for the ``spectra render pr-comment`` CLI subcommand."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from spectra import __version__
from spectra.adapters.cli_controller import app
from spectra.adapters.pr_comment_renderer import PR_COMMENT_SENTINEL
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _empty_report() -> AnalysisReport:
    dims = (
        DimensionScore(dimension="architecture", score=85.0, grade="B+", findings_count=0, weight=0.25),
        DimensionScore(dimension="security", score=90.0, grade="A", findings_count=0, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="B-", findings_count=0, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C", findings_count=0, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=0, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=0, weight=0.10),
    )
    return AnalysisReport(
        repo_url="https://github.com/example/repo",
        repo_name="repo",
        score_card=ScoreCard(
            overall_score=83.0,
            overall_grade=score_to_grade(83.0),
            dimensions=dims,
            total_findings=0,
        ),
        findings=(),
        analysis_duration_seconds=12.3,
        total_tokens_used=1000,
        total_cost_usd=0.01,
        agents_used=("architecture",),
    )


def _malicious_report() -> AnalysisReport:
    finding = Finding(
        id="F-001",
        dimension="security",
        severity="critical",
        title="<script>alert(1)</script>",
        description="payload here",
        location=FileLocation(file_path="src/app.py", line_start=10),
        recommendation="exfil this",
        agent_role="security",
        confidence=0.95,
    )
    dims = (
        DimensionScore(dimension="architecture", score=85.0, grade="B+", findings_count=0, weight=0.25),
        DimensionScore(dimension="security", score=10.0, grade="F", findings_count=1, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="B-", findings_count=0, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C", findings_count=0, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=0, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=0, weight=0.10),
    )
    return AnalysisReport(
        repo_url="https://github.com/example/repo",
        repo_name="repo",
        score_card=ScoreCard(
            overall_score=70.0,
            overall_grade="C",
            dimensions=dims,
            total_findings=1,
        ),
        findings=(finding,),
        analysis_duration_seconds=12.3,
        total_tokens_used=1000,
        total_cost_usd=0.01,
        agents_used=("security",),
    )


class TestRenderPrCommentCli:
    def test_empty_report_emits_sentinel_and_no_findings_message(self, tmp_path: Path):
        report_path = tmp_path / "report.json"
        report_path.write_text(_empty_report().model_dump_json())
        result = runner.invoke(app, ["render", "pr-comment", str(report_path)])
        assert result.exit_code == 0, result.output
        assert PR_COMMENT_SENTINEL in result.output
        assert f"No findings — Spectra v{__version__}" in result.output

    def test_malicious_finding_sanitized(self, tmp_path: Path):
        report_path = tmp_path / "report.json"
        report_path.write_text(_malicious_report().model_dump_json())
        result = runner.invoke(app, ["render", "pr-comment", str(report_path)])
        assert result.exit_code == 0, result.output
        # Raw <script> never appears
        assert "<script>" not in result.output
        # Allowlist enforcement — recommendation excluded
        assert "exfil this" not in result.output
        # Sentinel still on the first line
        assert result.output.startswith(PR_COMMENT_SENTINEL)

    def test_missing_report_path_exits_with_typer_error(self, tmp_path: Path):
        result = runner.invoke(app, ["render", "pr-comment", str(tmp_path / "missing.json")])
        # Typer's exists=True validator yields exit code 2
        assert result.exit_code == 2

    def test_invalid_json_exits_one(self, tmp_path: Path):
        report_path = tmp_path / "bad.json"
        report_path.write_text("{ not valid json")
        result = runner.invoke(app, ["render", "pr-comment", str(report_path)])
        assert result.exit_code == 1
        assert "Failed to load report" in result.output

    def test_valid_json_wrong_schema_exits_one(self, tmp_path: Path):
        report_path = tmp_path / "wrong.json"
        report_path.write_text(json.dumps({"hello": "world"}))
        result = runner.invoke(app, ["render", "pr-comment", str(report_path)])
        assert result.exit_code == 1
