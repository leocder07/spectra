"""CLI flag tests for --otel-endpoint + --team (#30 + #33, ADR-023 Part E)."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from spectra.adapters.cli_controller import app, set_analyzer_factory
from spectra.entities.models import (
    DimensionScore,
    ScoreCard,
    score_to_grade,
)

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _fake_report() -> object:
    dims = (
        DimensionScore(dimension="architecture", score=90.0, grade="A", findings_count=2, weight=0.25),
        DimensionScore(dimension="security", score=85.0, grade="B+", findings_count=3, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="B-", findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C", findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    sc = ScoreCard(
        overall_score=83.0,
        overall_grade=score_to_grade(83.0),
        dimensions=dims,
        total_findings=18,
    )
    return SimpleNamespace(
        score_card=sc,
        repo_name="test-repo",
        findings=(),
        total_findings=18,
        analysis_duration_seconds=42.0,
        total_cost_usd=0.15,
        is_degraded=False,
        degraded_dimensions=(),
    )


class TestOtelFlagSurface:
    def test_otel_endpoint_flag_listed_in_help(self) -> None:
        result = runner.invoke(app, ["analyze", "--help"])
        assert "--otel-endpoint" in _strip_ansi(result.output)

    def test_team_flag_listed_in_help(self) -> None:
        result = runner.invoke(app, ["analyze", "--help"])
        assert "--team" in _strip_ansi(result.output)


class TestOtelFlagParsing:
    def test_otel_endpoint_flag_passed_to_factory(self) -> None:
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--otel-endpoint",
                "http://collector:4318/v1/traces",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["otel_endpoint"] == "http://collector:4318/v1/traces"

    def test_team_flag_passed_to_factory(self) -> None:
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--team", "payments-platform"],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["team"] == "payments-platform"

    def test_default_team_passed_when_flag_absent(self) -> None:
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["team"] == "default"

    def test_default_otel_endpoint_is_none(self) -> None:
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["otel_endpoint"] is None

    def test_team_env_default(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("SPECTRA_TEAM", "ml-platform")
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["team"] == "ml-platform"

    def test_explicit_team_flag_wins_over_env(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("SPECTRA_TEAM", "ml-platform")
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo", "--team", "data-eng"])
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["team"] == "data-eng"
