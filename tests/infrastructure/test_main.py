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
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
)
from spectra.infrastructure.main import (
    _SARIF_SEVERITY,
    ReportError,
    _build_sarif,
    _run_analysis,
    cli,
)

# Test-only path constants computed at import time from the platform tempdir.
# Avoids ruff S108 (hardcoded /tmp literal); these strings are mock return
# values / arguments and never touch the filesystem.
_TMP_OUT_HTML = str(Path(tempfile.gettempdir()) / "out.html")
_TMP_SPECTRA_TEST = str(Path(tempfile.gettempdir()) / "spectra-test")

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
            await _run_analysis("https://github.com/test/repo", _TMP_OUT_HTML)

    @pytest.mark.asyncio
    async def test_raises_with_empty_api_key(self):
        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}),
            pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"),
        ):
            await _run_analysis("https://github.com/test/repo", _TMP_OUT_HTML)

    @pytest.mark.asyncio
    async def test_raises_with_whitespace_api_key(self):
        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "   "}),
            pytest.raises(ValueError, match="placeholder"),
        ):
            await _run_analysis("https://github.com/test/repo", _TMP_OUT_HTML)

    @pytest.mark.asyncio
    async def test_raises_with_placeholder_api_key(self):
        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-your-key-here"}),
            pytest.raises(ValueError, match="placeholder"),
        ):
            await _run_analysis("https://github.com/test/repo", _TMP_OUT_HTML)

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
        mock_git.prepare_workspace = AsyncMock(return_value=_TMP_SPECTRA_TEST)
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["src/main.py", "README.md"])

        # Mock report renderer
        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(return_value=_TMP_OUT_HTML)

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
            patch("tempfile.mkdtemp", return_value=_TMP_SPECTRA_TEST),
            patch("os.chmod"),
            patch("shutil.rmtree"),
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            result = await _run_analysis(
                "https://github.com/test/repo",
                _TMP_OUT_HTML,
                output_format="html",
            )

            assert result.repo_url == "https://github.com/test/repo"
            mock_git.prepare_workspace.assert_called_once()
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
        mock_git.prepare_workspace = AsyncMock(return_value=_TMP_SPECTRA_TEST)
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
                patch("tempfile.mkdtemp", return_value=_TMP_SPECTRA_TEST),
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
        mock_git.prepare_workspace = AsyncMock(return_value=_TMP_SPECTRA_TEST)
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
            patch("tempfile.mkdtemp", return_value=_TMP_SPECTRA_TEST),
            patch("os.chmod"),
            patch("shutil.rmtree"),
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            with pytest.raises(ReportError) as exc_info:
                await _run_analysis(
                    "https://github.com/test/repo",
                    _TMP_OUT_HTML,
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
        mock_git.prepare_workspace = AsyncMock(return_value=_TMP_SPECTRA_TEST)
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["f.py"])

        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(return_value=_TMP_OUT_HTML)

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
            patch("tempfile.mkdtemp", return_value=_TMP_SPECTRA_TEST),
            patch("os.chmod") as mock_chmod,
            patch("shutil.rmtree") as mock_rmtree,
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            await _run_analysis("https://github.com/test/repo", _TMP_OUT_HTML)

            # Verify security: tmpdir had restricted permissions
            mock_chmod.assert_called_once_with(_TMP_SPECTRA_TEST, 0o700)
            # Verify cleanup of the cloned tmpdir (URL source ⇒ owns_workspace)
            mock_rmtree.assert_called_once_with(_TMP_SPECTRA_TEST, ignore_errors=True)
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
        mock_git.prepare_workspace = AsyncMock(return_value=_TMP_SPECTRA_TEST)
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["f.py"])

        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(return_value=_TMP_OUT_HTML)

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
            patch("tempfile.mkdtemp", return_value=_TMP_SPECTRA_TEST),
            patch("os.chmod"),
            patch("shutil.rmtree"),
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            await _run_analysis(
                "https://github.com/test/repo",
                _TMP_OUT_HTML,
                skip_critique=True,
            )

            # critique_agent on the PipelineContext should be None when skipping
            ctx_arg = mock_analyze.call_args.args[0]
            assert ctx_arg.critique_agent is None

    @pytest.mark.asyncio
    async def test_local_path_skips_tempdir_and_cleanup(self, tmp_path):
        """Local-path source must not allocate a tmpdir nor remove the user's repo."""
        # Build a local repo on disk
        local_repo = tmp_path / "myrepo"
        (local_repo / ".git").mkdir(parents=True)
        (local_repo / "src").mkdir()
        (local_repo / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")

        finding = Finding(
            id="a-001",
            dimension="architecture",
            severity="info",
            title="T",
            description="D",
            location=FileLocation(file_path="src/main.py", line_start=1),
            recommendation="R",
            agent_role="architecture",
            confidence=0.8,
        )
        dim_score = DimensionScore(dimension="architecture", score=85.0, grade="B+", findings_count=1, weight=1.0)
        score_card = ScoreCard(overall_score=85.0, overall_grade="B+", dimensions=(dim_score,), total_findings=1)
        report = AnalysisReport(
            repo_url=str(local_repo),
            repo_name="myrepo",
            score_card=score_card,
            findings=(finding,),
            analysis_duration_seconds=1.0,
            total_tokens_used=100,
            total_cost_usd=0.01,
            agents_used=("architecture",),
        )

        mock_git = AsyncMock()
        mock_git.clone = AsyncMock()
        mock_git.prepare_workspace = AsyncMock(return_value=str(local_repo))
        mock_git.validate_repo_size = AsyncMock()
        mock_git.get_file_tree = AsyncMock(return_value=["src/main.py"])

        mock_reporter = MagicMock()
        mock_reporter.render = MagicMock(return_value="/tmp/out.html")  # noqa: S108

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
            patch("spectra.infrastructure.main.tempfile.mkdtemp") as mock_mkdtemp,
            patch("spectra.infrastructure.main.shutil.rmtree") as mock_rmtree,
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create = MagicMock()
            mock_factory.create_specialists = MagicMock(return_value=[])

            await _run_analysis(str(local_repo), "/tmp/out.html")  # noqa: S108

            mock_mkdtemp.assert_not_called()
            mock_rmtree.assert_not_called()
            mock_git.prepare_workspace.assert_called_once()


# ── cli function ──────────────────────────────────────────────


class TestCli:
    def test_cli_sets_analyzer_factory(self):
        with (
            patch("spectra.infrastructure.main.set_analyzer_factory") as mock_set,
            patch("spectra.infrastructure.main.cli_entry") as mock_cli,
        ):
            cli()
            mock_set.assert_called_once()
            mock_cli.assert_called_once()

    def test_cli_passes_run_analysis_to_factory(self):
        with (
            patch("spectra.infrastructure.main.set_analyzer_factory") as mock_set,
            patch("spectra.infrastructure.main.cli_entry"),
        ):
            cli()
            # The factory should receive the _run_analysis function
            assert mock_set.call_args[0][0] is _run_analysis


# ── _build_sarif ─────────────────────────────────────────────


class TestBuildSarif:
    """Tests for SARIF v2.1.0 output generation."""

    @staticmethod
    def _make_report(findings: tuple[Finding, ...] = ()) -> AnalysisReport:
        dim_score = DimensionScore(
            dimension="security", score=85.0, grade="B+", findings_count=len(findings), weight=1.0
        )
        score_card = ScoreCard(
            overall_score=85.0, overall_grade="B+", dimensions=(dim_score,), total_findings=len(findings)
        )
        return AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=score_card,
            findings=findings,
            analysis_duration_seconds=5.0,
            total_tokens_used=1000,
            total_cost_usd=0.5,
            agents_used=("security",),
        )

    def test_sarif_top_level_structure(self):
        """SARIF output has $schema, version, and runs keys."""
        report = self._make_report()
        sarif = _build_sarif(report)
        assert sarif["$schema"].endswith("sarif-schema-2.1.0.json")
        assert sarif["version"] == "2.1.0"
        assert isinstance(sarif["runs"], list)
        assert len(sarif["runs"]) == 1

    def test_sarif_tool_driver(self):
        """SARIF run contains Spectra tool driver metadata."""
        sarif = _build_sarif(self._make_report())
        driver = sarif["runs"][0]["tool"]["driver"]
        assert driver["name"] == "Spectra"
        assert driver["version"] == "0.1.0"
        assert "informationUri" in driver

    def test_sarif_zero_findings_empty_results(self):
        """Report with no findings produces an empty results array."""
        sarif = _build_sarif(self._make_report(findings=()))
        assert sarif["runs"][0]["results"] == []

    def test_sarif_finding_to_result_mapping(self):
        """Each finding maps to a SARIF result with ruleId, level, locations."""
        finding = Finding(
            id="sec-001",
            dimension="security",
            severity="critical",
            title="SQL Injection",
            description="Unsanitized user input",
            location=FileLocation(file_path="src/db.py", line_start=42),
            recommendation="Use parameterized queries",
            agent_role="security",
            confidence=0.95,
            estimated_hours=2.0,
        )
        sarif = _build_sarif(self._make_report(findings=(finding,)))
        results = sarif["runs"][0]["results"]
        assert len(results) == 1

        r = results[0]
        assert r["ruleId"] == "spectra/security/sec-001"
        assert r["level"] == "error"
        assert "SQL Injection" in r["message"]["text"]
        assert "Unsanitized user input" in r["message"]["text"]

        loc = r["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/db.py"
        assert loc["region"]["startLine"] == 42

        assert r["properties"]["severity"] == "critical"
        assert r["properties"]["dimension"] == "security"
        assert r["properties"]["recommendation"] == "Use parameterized queries"
        assert r["properties"]["estimatedHours"] == 2.0

    def test_sarif_severity_mapping_critical_to_error(self):
        assert _SARIF_SEVERITY["critical"] == "error"

    def test_sarif_severity_mapping_high_to_error(self):
        assert _SARIF_SEVERITY["high"] == "error"

    def test_sarif_severity_mapping_medium_to_warning(self):
        assert _SARIF_SEVERITY["medium"] == "warning"

    def test_sarif_severity_mapping_low_to_note(self):
        assert _SARIF_SEVERITY["low"] == "note"

    def test_sarif_severity_mapping_info_to_note(self):
        assert _SARIF_SEVERITY["info"] == "note"

    def test_sarif_unknown_severity_defaults_to_note(self):
        """Unknown severity falls back to 'note' via dict.get default."""
        finding = Finding(
            id="x-001",
            dimension="quality",
            severity="low",
            title="Title",
            description="Desc",
            location=FileLocation(file_path="f.py", line_start=1),
            recommendation="Rec",
            agent_role="quality",
            confidence=0.8,
        )
        sarif = _build_sarif(self._make_report(findings=(finding,)))
        assert sarif["runs"][0]["results"][0]["level"] == "note"

    def test_sarif_multiple_findings(self):
        """Multiple findings produce multiple SARIF results."""
        f1 = Finding(
            id="sec-001",
            dimension="security",
            severity="critical",
            title="SQL Injection",
            description="Input not sanitized",
            location=FileLocation(file_path="src/db.py", line_start=10),
            recommendation="Fix",
            agent_role="security",
            confidence=0.9,
        )
        f2 = Finding(
            id="perf-001",
            dimension="performance",
            severity="medium",
            title="N+1 query",
            description="Loop queries",
            location=FileLocation(file_path="src/api.py", line_start=25),
            recommendation="Batch",
            agent_role="performance",
            confidence=0.85,
        )
        sarif = _build_sarif(self._make_report(findings=(f1, f2)))
        results = sarif["runs"][0]["results"]
        assert len(results) == 2
        assert results[0]["ruleId"] == "spectra/security/sec-001"
        assert results[0]["level"] == "error"
        assert results[1]["ruleId"] == "spectra/performance/perf-001"
        assert results[1]["level"] == "warning"

    def test_sarif_line_start_zero_clamped_to_one(self):
        """line_start=0 is clamped to 1 via max(1, ...)."""
        finding = Finding(
            id="q-001",
            dimension="quality",
            severity="info",
            title="Title",
            description="Desc",
            location=FileLocation(file_path="f.py", line_start=0),
            recommendation="Rec",
            agent_role="quality",
            confidence=0.8,
        )
        sarif = _build_sarif(self._make_report(findings=(finding,)))
        region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 1

    def test_provision_cache_only_returns_sqlite_adapter(self, tmp_path):
        """_provision_cache_only returns a usable SqliteCacheAdapter."""
        from spectra.infrastructure.cache_adapter import SqliteCacheAdapter
        from spectra.infrastructure.main import _provision_cache_only

        with patch(
            "spectra.infrastructure.main.default_cache_path",
            return_value=tmp_path / "cache.db",
        ):
            cache = _provision_cache_only()
        assert isinstance(cache, SqliteCacheAdapter)

    def test_provision_cache_only_does_not_require_anthropic_api_key(
        self,
        tmp_path,
    ):
        """The cache CLI must work in environments without an API key."""
        from spectra.infrastructure.main import _provision_cache_only

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "spectra.infrastructure.main.default_cache_path",
                return_value=tmp_path / "cache.db",
            ),
        ):
            # Must not raise — the cache subcommands have no LLM dependency.
            cache = _provision_cache_only()
        assert cache is not None

    def test_sarif_is_json_serializable(self):
        """SARIF output can be serialized to JSON without errors."""
        finding = Finding(
            id="a-001",
            dimension="architecture",
            severity="high",
            title="Circular dependency",
            description="A imports B imports A",
            location=FileLocation(file_path="src/a.py", line_start=5),
            recommendation="Break the cycle",
            agent_role="architecture",
            confidence=0.88,
            estimated_hours=4.0,
        )
        sarif = _build_sarif(self._make_report(findings=(finding,)))
        serialized = json.dumps(sarif, indent=2)
        roundtripped = json.loads(serialized)
        assert roundtripped["version"] == "2.1.0"
