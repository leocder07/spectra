"""Tests for the composition root — main.py."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra.entities.errors import ERRORS
from spectra.entities.models import (
    AgentOutput,
    AnalysisReport,
    AnalysisRequest,
    Codebase,
    DimensionScore,
    Finding,
    FileLocation,
    ScoreCard,
)
from spectra.infrastructure.main import ReportError, _run_analysis, cli


# ── ReportError ───────────────────────────────────────────────


class TestReportError:
    def test_has_error_attribute(self):
        err = ReportError(ERRORS["SPEC-009"])
        assert err.error.code == "SPEC-009"

    def test_message_contains_code(self):
        err = ReportError(ERRORS["SPEC-009"])
        assert "SPEC-009" in str(err)

    def test_message_contains_description(self):
        err = ReportError(ERRORS["SPEC-009"])
        assert "Report render failed" in str(err)

    def test_is_exception(self):
        err = ReportError(ERRORS["SPEC-009"])
        assert isinstance(err, Exception)

    def test_inherits_from_exception(self):
        err = ReportError(ERRORS["SPEC-009"])
        assert issubclass(ReportError, Exception)
        with pytest.raises(ReportError):
            raise err

    def test_error_attribute_matches_input(self):
        for code in ["SPEC-001", "SPEC-005", "SPEC-009"]:
            err = ReportError(ERRORS[code])
            assert err.error is ERRORS[code]


# ── _run_analysis ─────────────────────────────────────────────


class TestRunAnalysis:
    @pytest.mark.asyncio
    async def test_raises_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True), pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            await _run_analysis("https://github.com/test/repo", "/tmp/out.html")

    @pytest.mark.asyncio
    async def test_raises_with_empty_api_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                await _run_analysis("https://github.com/test/repo", "/tmp/out.html")

    @pytest.mark.asyncio
    async def test_raises_with_whitespace_api_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "   "}):
            with pytest.raises(ValueError, match="placeholder"):
                await _run_analysis("https://github.com/test/repo", "/tmp/out.html")

    @pytest.mark.asyncio
    async def test_raises_with_placeholder_api_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-your-key-here"}):
            with pytest.raises(ValueError, match="placeholder"):
                await _run_analysis("https://github.com/test/repo", "/tmp/out.html")

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mocks(self):
        """Test the full _run_analysis pipeline with all infrastructure mocked."""
        # Build a minimal valid report
        finding = Finding(
            id="arch-001",
            dimension="architecture",
            severity="info",
            title="Test finding",
            description="Test desc",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="Test rec",
            agent_role="architecture",
            confidence=0.9,
        )
        dim_score = DimensionScore(
            dimension="architecture",
            score=85.0,
            grade="B+",
            findings_count=1,
            weight=1.0,
        )
        score_card = ScoreCard(
            overall_score=85.0,
            overall_grade="B+",
            dimensions=(dim_score,),
            total_findings=1,
        )
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=score_card,
            findings=(finding,),
            analysis_duration_seconds=5.0,
            total_tokens_used=1000,
            total_cost_usd=0.5,
            agents_used=("architecture",),
        )

        # Mock git operations
        mock_git = AsyncMock()
        mock_git.clone = AsyncMock()
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["src/main.py", "README.md"])

        # Mock report renderer
        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(return_value="/tmp/out.html")

        # Mock the adapter close
        mock_adapter = MagicMock()
        mock_adapter.close = AsyncMock()

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-real-key-12345"}),
            patch("spectra.infrastructure.main.GitAdapter", return_value=mock_git),
            patch("spectra.infrastructure.main.ReportAdapter", return_value=mock_reporter),
            patch("spectra.infrastructure.main.AnthropicAdapter", return_value=mock_adapter),
            patch("spectra.infrastructure.main.RichProgressReporter"),
            patch("spectra.infrastructure.main.RetryDecorator"),
            patch("spectra.infrastructure.main.LoggingDecorator"),
            patch("spectra.infrastructure.main.AgentFactory") as mock_factory_cls,
            patch("spectra.infrastructure.main.analyze_repository", return_value=report),
            patch("tempfile.mkdtemp", return_value="/tmp/spectra-test"),
            patch("os.chmod"),
            patch("shutil.rmtree"),
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            result = await _run_analysis(
                "https://github.com/test/repo",
                "/tmp/out.html",
                output_format="html",
            )

            assert result.repo_url == "https://github.com/test/repo"
            mock_git.clone.assert_called_once()
            mock_git.validate_repo_size.assert_called_once()
            mock_reporter.render.assert_called_once()
            mock_adapter.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_json_output_format(self):
        """Test _run_analysis with JSON output format writes valid JSON."""
        finding = Finding(
            id="sec-001",
            dimension="security",
            severity="low",
            title="Info finding",
            description="Test",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="None",
            agent_role="security",
            confidence=0.8,
        )
        dim_score = DimensionScore(
            dimension="security",
            score=90.0,
            grade="A",
            findings_count=1,
            weight=1.0,
        )
        score_card = ScoreCard(
            overall_score=90.0,
            overall_grade="A",
            dimensions=(dim_score,),
            total_findings=1,
        )
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=score_card,
            findings=(finding,),
            analysis_duration_seconds=3.0,
            total_tokens_used=500,
            total_cost_usd=0.1,
            agents_used=("security",),
        )

        mock_git = AsyncMock()
        mock_git.clone = AsyncMock()
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["src/main.py"])

        mock_adapter = MagicMock()
        mock_adapter.close = AsyncMock()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            with (
                patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-real-key-12345"}),
                patch("spectra.infrastructure.main.GitAdapter", return_value=mock_git),
                patch("spectra.infrastructure.main.ReportAdapter"),
                patch("spectra.infrastructure.main.AnthropicAdapter", return_value=mock_adapter),
                patch("spectra.infrastructure.main.RichProgressReporter"),
                patch("spectra.infrastructure.main.RetryDecorator"),
                patch("spectra.infrastructure.main.LoggingDecorator"),
                patch("spectra.infrastructure.main.AgentFactory") as mock_factory_cls,
                patch("spectra.infrastructure.main.analyze_repository", return_value=report),
                patch("tempfile.mkdtemp", return_value="/tmp/spectra-test"),
                patch("os.chmod"),
                patch("shutil.rmtree"),
            ):
                mock_factory = mock_factory_cls.return_value
                mock_factory.create = MagicMock()
                mock_factory.create_specialists = MagicMock(return_value=[])

                result = await _run_analysis(
                    "https://github.com/test/repo",
                    output_path,
                    output_format="json",
                )

                assert result.repo_url == "https://github.com/test/repo"
                # Verify valid JSON was written
                content = Path(output_path).read_text()
                data = json.loads(content)
                assert data["repo_url"] == "https://github.com/test/repo"
        finally:
            os.unlink(output_path)

    @pytest.mark.asyncio
    async def test_report_render_failure_raises_report_error(self):
        """Test that a render failure raises ReportError with SPEC-009."""
        finding = Finding(
            id="q-001",
            dimension="quality",
            severity="info",
            title="T",
            description="D",
            location=FileLocation(file_path="f.py", line_start=1),
            recommendation="R",
            agent_role="quality",
            confidence=0.8,
        )
        dim_score = DimensionScore(dimension="quality", score=80.0, grade="B", findings_count=1, weight=1.0)
        score_card = ScoreCard(overall_score=80.0, overall_grade="B", dimensions=(dim_score,), total_findings=1)
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=score_card,
            findings=(finding,),
            analysis_duration_seconds=1.0,
            total_tokens_used=100,
            total_cost_usd=0.01,
            agents_used=("quality",),
        )

        mock_git = AsyncMock()
        mock_git.clone = AsyncMock()
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["f.py"])

        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(side_effect=RuntimeError("Template error"))

        mock_adapter = MagicMock()
        mock_adapter.close = AsyncMock()

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-real-key-12345"}),
            patch("spectra.infrastructure.main.GitAdapter", return_value=mock_git),
            patch("spectra.infrastructure.main.ReportAdapter", return_value=mock_reporter),
            patch("spectra.infrastructure.main.AnthropicAdapter", return_value=mock_adapter),
            patch("spectra.infrastructure.main.RichProgressReporter"),
            patch("spectra.infrastructure.main.RetryDecorator"),
            patch("spectra.infrastructure.main.LoggingDecorator"),
            patch("spectra.infrastructure.main.AgentFactory") as mock_factory_cls,
            patch("spectra.infrastructure.main.analyze_repository", return_value=report),
            patch("tempfile.mkdtemp", return_value="/tmp/spectra-test"),
            patch("os.chmod"),
            patch("shutil.rmtree"),
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            with pytest.raises(ReportError) as exc_info:
                await _run_analysis(
                    "https://github.com/test/repo",
                    "/tmp/out.html",
                )
            assert exc_info.value.error.code == "SPEC-009"
            # Verify cleanup still happened
            mock_adapter.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_runs_on_success(self):
        """Verify tmpdir is removed and adapter closed even on success."""
        finding = Finding(
            id="a-001",
            dimension="architecture",
            severity="info",
            title="T",
            description="D",
            location=FileLocation(file_path="f.py", line_start=1),
            recommendation="R",
            agent_role="architecture",
            confidence=0.8,
        )
        dim_score = DimensionScore(dimension="architecture", score=85.0, grade="B+", findings_count=1, weight=1.0)
        score_card = ScoreCard(overall_score=85.0, overall_grade="B+", dimensions=(dim_score,), total_findings=1)
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=score_card,
            findings=(finding,),
            analysis_duration_seconds=1.0,
            total_tokens_used=100,
            total_cost_usd=0.01,
            agents_used=("architecture",),
        )

        mock_git = AsyncMock()
        mock_git.clone = AsyncMock()
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["f.py"])

        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(return_value="/tmp/out.html")

        mock_adapter = MagicMock()
        mock_adapter.close = AsyncMock()

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-real-key-12345"}),
            patch("spectra.infrastructure.main.GitAdapter", return_value=mock_git),
            patch("spectra.infrastructure.main.ReportAdapter", return_value=mock_reporter),
            patch("spectra.infrastructure.main.AnthropicAdapter", return_value=mock_adapter),
            patch("spectra.infrastructure.main.RichProgressReporter"),
            patch("spectra.infrastructure.main.RetryDecorator"),
            patch("spectra.infrastructure.main.LoggingDecorator"),
            patch("spectra.infrastructure.main.AgentFactory") as mock_factory_cls,
            patch("spectra.infrastructure.main.analyze_repository", return_value=report),
            patch("tempfile.mkdtemp", return_value="/tmp/spectra-test"),
            patch("os.chmod") as mock_chmod,
            patch("shutil.rmtree") as mock_rmtree,
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            await _run_analysis("https://github.com/test/repo", "/tmp/out.html")

            # Verify security: tmpdir had restricted permissions
            mock_chmod.assert_called_once_with("/tmp/spectra-test", 0o700)
            # Verify cleanup
            mock_rmtree.assert_called_once_with("/tmp/spectra-test", ignore_errors=True)
            mock_adapter.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_critique_creates_no_critique_agent(self):
        """When skip_critique=True, critique_agent should be None."""
        finding = Finding(
            id="a-001",
            dimension="architecture",
            severity="info",
            title="T",
            description="D",
            location=FileLocation(file_path="f.py", line_start=1),
            recommendation="R",
            agent_role="architecture",
            confidence=0.8,
        )
        dim_score = DimensionScore(dimension="architecture", score=85.0, grade="B+", findings_count=1, weight=1.0)
        score_card = ScoreCard(overall_score=85.0, overall_grade="B+", dimensions=(dim_score,), total_findings=1)
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=score_card,
            findings=(finding,),
            analysis_duration_seconds=1.0,
            total_tokens_used=100,
            total_cost_usd=0.01,
            agents_used=("architecture",),
        )

        mock_git = AsyncMock()
        mock_git.clone = AsyncMock()
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["f.py"])

        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(return_value="/tmp/out.html")

        mock_adapter = MagicMock()
        mock_adapter.close = AsyncMock()

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-real-key-12345"}),
            patch("spectra.infrastructure.main.GitAdapter", return_value=mock_git),
            patch("spectra.infrastructure.main.ReportAdapter", return_value=mock_reporter),
            patch("spectra.infrastructure.main.AnthropicAdapter", return_value=mock_adapter),
            patch("spectra.infrastructure.main.RichProgressReporter"),
            patch("spectra.infrastructure.main.RetryDecorator"),
            patch("spectra.infrastructure.main.LoggingDecorator"),
            patch("spectra.infrastructure.main.AgentFactory") as mock_factory_cls,
            patch("spectra.infrastructure.main.analyze_repository", return_value=report) as mock_analyze,
            patch("tempfile.mkdtemp", return_value="/tmp/spectra-test"),
            patch("os.chmod"),
            patch("shutil.rmtree"),
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            await _run_analysis(
                "https://github.com/test/repo",
                "/tmp/out.html",
                skip_critique=True,
            )

            # critique_agent kwarg should be None when skipping
            call_kwargs = mock_analyze.call_args[1]
            assert call_kwargs["critique_agent"] is None


# ── cli function ──────────────────────────────────────────────


class TestCli:
    def test_cli_sets_analyzer_factory(self):
        with patch("spectra.infrastructure.main.set_analyzer_factory") as mock_set:
            with patch("spectra.infrastructure.main.cli_entry") as mock_cli:
                cli()
                mock_set.assert_called_once()
                mock_cli.assert_called_once()

    def test_cli_passes_run_analysis_to_factory(self):
        with patch("spectra.infrastructure.main.set_analyzer_factory") as mock_set:
            with patch("spectra.infrastructure.main.cli_entry"):
                cli()
                # The factory should receive the _run_analysis function
                assert mock_set.call_args[0][0] is _run_analysis
