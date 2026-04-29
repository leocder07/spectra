"""Tests for CLI controller — Typer argument parsing and error handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from spectra.adapters.cli_controller import app, set_analyzer_factory
from spectra.entities.errors import ERRORS, AgentError, GitError, SpectraRetryError
from spectra.entities.models import DimensionScore, ScoreCard, score_to_grade

runner = CliRunner()


def _fake_report(*, overall: float = 83.0):
    """Build a minimal report-shaped object for successful analysis flow."""
    dims = (
        DimensionScore(dimension="architecture", score=90.0, grade="A", findings_count=2, weight=0.25),
        DimensionScore(dimension="security", score=85.0, grade="B+", findings_count=3, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="B-", findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C", findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    sc = ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
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


# ── Basic CLI navigation ─────────────────────────────────────


class TestCLIController:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # no_args_is_help=True causes Typer to exit with code 0 or 2
        assert result.exit_code in (0, 2)
        assert "analyze" in result.output.lower() or "usage" in result.output.lower()

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "v0.1.0" in result.output

    def test_version_short_flag(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "v0.1.0" in result.output

    def test_version_contains_spectra_name(self):
        result = runner.invoke(app, ["--version"])
        assert "spectra" in result.output.lower()

    def test_analyze_without_factory_fails(self):
        set_analyzer_factory(None)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "Not initialized" in result.output

    def test_analyze_invalid_format_xml(self):
        set_analyzer_factory(AsyncMock(return_value=None))
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--format",
                "xml",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid format" in result.output

    def test_analyze_invalid_format_csv(self):
        set_analyzer_factory(AsyncMock(return_value=None))
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--format",
                "csv",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid format" in result.output

    def test_analyze_valid_format_html(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--format",
                "html",
            ],
        )
        assert result.exit_code == 0

    def test_analyze_valid_format_json(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0

    def test_analyze_help(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "repo-url" in result.output.lower() or "REPO_URL" in result.output

    def test_analyze_help_contains_quick_option(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert "--quick" in result.output or "-q" in result.output

    def test_analyze_help_contains_format_option(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert "--format" in result.output or "-f" in result.output


# ── Successful analyze flow ──────────────────────────────────


class TestCLISuccessFlow:
    def test_successful_analyze_shows_scorecard(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        assert "SPECTRA SCORECARD" in result.output

    def test_successful_analyze_shows_repo_name(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert "repo" in result.output

    def test_successful_analyze_shows_report_saved(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert "Report saved" in result.output or "report" in result.output.lower()

    def test_successful_analyze_shows_banner(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        # The banner contains the ASCII art
        assert "SPECTRA" in result.output or "spectra" in result.output

    def test_quick_mode_shows_quick_scan(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--quick",
            ],
        )
        assert result.exit_code == 0
        assert "quick" in result.output.lower()

    def test_factory_called_with_correct_args(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--quick",
                "--format",
                "json",
            ],
        )
        factory.assert_called_once()
        call_kwargs = factory.call_args[1]
        assert call_kwargs["repo_url"] == "https://github.com/test/repo"
        assert call_kwargs["skip_critique"] is True
        assert call_kwargs["output_format"] == "json"

    def test_json_format_shows_json_written(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert "JSON written" in result.output or "json" in result.output.lower()

    def test_factory_returns_none_exits_with_1(self):
        factory = AsyncMock(return_value=None)
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1


# ── Error type handling ──────────────────────────────────────


class TestCLIErrorHandling:
    def test_git_error_displays_code(self):
        factory = AsyncMock(side_effect=GitError(ERRORS["SPEC-001"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "SPEC-001" in result.output
        assert "Git clone failed" in result.output

    def test_retry_error_displays_code(self):
        factory = AsyncMock(side_effect=SpectraRetryError(ERRORS["SPEC-002"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "SPEC-002" in result.output

    def test_rate_limit_error_displays_code(self):
        factory = AsyncMock(side_effect=SpectraRetryError(ERRORS["SPEC-003"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "SPEC-003" in result.output

    def test_agent_error_displays_code(self):
        factory = AsyncMock(side_effect=AgentError(ERRORS["SPEC-005"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "SPEC-005" in result.output

    def test_timeout_error_displays_code(self):
        factory = AsyncMock(side_effect=AgentError(ERRORS["SPEC-006"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "SPEC-006" in result.output

    def test_pipeline_error_displays_code(self):
        factory = AsyncMock(side_effect=AgentError(ERRORS["SPEC-007"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "SPEC-007" in result.output

    def test_unexpected_error_shows_message(self):
        factory = AsyncMock(side_effect=RuntimeError("something went wrong"))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "Unexpected error" in result.output
        assert "something went wrong" in result.output

    def test_unexpected_error_type_error(self):
        factory = AsyncMock(side_effect=TypeError("bad type"))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "Unexpected error" in result.output
        assert "bad type" in result.output

    def test_error_output_uses_red_marker(self):
        factory = AsyncMock(side_effect=GitError(ERRORS["SPEC-001"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        # Rich markup contains red color code for error indicator
        assert "\u2717" in result.output

    def test_keyboard_interrupt_exits_130(self):
        factory = AsyncMock(side_effect=KeyboardInterrupt)
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 130

    def test_keyboard_interrupt_shows_cancelled(self):
        factory = AsyncMock(side_effect=KeyboardInterrupt)
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert "cancelled" in result.output.lower()


# ── Edge cases ───────────────────────────────────────────────


class TestCLIEdgeCases:
    def test_repo_url_with_trailing_slash(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/my-repo/",
            ],
        )
        assert result.exit_code == 0
        # Repo name should be extracted correctly (no trailing slash issue)
        assert "my-repo" in result.output

    def test_repo_url_with_git_suffix(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/my-repo.git",
            ],
        )
        assert result.exit_code == 0
        # .git suffix should be removed from repo name
        assert "my-repo" in result.output

    def test_analyze_all_error_codes(self):
        """Every SPEC error code should be displayable by the CLI."""
        for code in ("SPEC-001",):
            factory = AsyncMock(side_effect=GitError(ERRORS[code]))
            set_analyzer_factory(factory)
            result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
            assert code in result.output

        for code in ("SPEC-002", "SPEC-003"):
            factory = AsyncMock(side_effect=SpectraRetryError(ERRORS[code]))
            set_analyzer_factory(factory)
            result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
            assert code in result.output

        for code in ("SPEC-005", "SPEC-006", "SPEC-007", "SPEC-008", "SPEC-009"):
            factory = AsyncMock(side_effect=AgentError(ERRORS[code]))
            set_analyzer_factory(factory)
            result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
            assert code in result.output


# ── URL validation edge cases ───────────────────────────────


class TestCLIUrlValidation:
    def test_empty_url(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", ""])
        assert result.exit_code == 1
        assert "empty" in result.output.lower() or "URL" in result.output

    def test_http_not_https(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "http://github.com/test/repo"])
        assert result.exit_code == 1
        assert "HTTPS" in result.output

    def test_url_with_fragment(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo#readme"],
        )
        # Fragments in URL should be accepted (valid HTTPS URL)
        assert result.exit_code == 0

    def test_url_with_query_string(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo?tab=code"],
        )
        assert result.exit_code == 0

    def test_ssh_url_rejected(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "git@github.com:test/repo.git"],
        )
        assert result.exit_code == 1

    def test_plain_text_rejected(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "not-a-url-at-all"])
        assert result.exit_code == 1

    def test_ftp_url_rejected(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "ftp://example.com/repo"])
        assert result.exit_code == 1


# ── Format edge cases ───────────────────────────────────────


class TestCLIFormatEdgeCases:
    def test_format_yaml_invalid(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--format", "yaml"],
        )
        assert result.exit_code == 1
        assert "Invalid format" in result.output

    def test_format_empty_string(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--format", ""],
        )
        assert result.exit_code == 1

    def test_format_uppercase_html(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--format", "HTML"],
        )
        # Uppercase should be rejected (case-sensitive)
        assert result.exit_code == 1

    def test_format_markdown_invalid(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--format", "markdown"],
        )
        assert result.exit_code == 1


# ── Verbose mode ─────────────────────────────────────────────


class TestCLIVerbose:
    def test_verbose_on_unexpected_error(self):
        factory = AsyncMock(side_effect=RuntimeError("kaboom"))
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--verbose"],
        )
        assert result.exit_code == 1
        assert "kaboom" in result.output

    def test_verbose_flag_accepted(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--verbose"],
        )
        assert result.exit_code == 0


# ── Degraded report display ──────────────────────────────────


class TestCLIDegradedReport:
    def test_degraded_report_still_displays(self):
        report = _fake_report()
        report.is_degraded = True
        report.degraded_dimensions = ("architecture", "security")
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0


# ── Local-path acceptance ────────────────────────────────────


def _make_local_repo(root: Path) -> Path:
    """Create a directory that looks like a git checkout."""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return root


class TestCLILocalPath:
    def test_local_path_accepted_relative(self, tmp_path, monkeypatch):
        """`spectra analyze .` is accepted when cwd is a git repo."""
        repo = _make_local_repo(tmp_path / "myrepo")
        monkeypatch.chdir(repo)
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "."])
        assert result.exit_code == 0, result.output
        factory.assert_called_once()
        # The CLI must forward the literal path, not rewrite it.
        assert factory.call_args[1]["repo_url"] == "."

    def test_local_path_accepted_absolute(self, tmp_path):
        """`spectra analyze /abs/path` is accepted when path holds a git repo."""
        repo = _make_local_repo(tmp_path / "abs-repo")
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", str(repo)])
        assert result.exit_code == 0, result.output
        factory.assert_called_once()
        assert factory.call_args[1]["repo_url"] == str(repo)

    def test_local_path_rejected_no_git_dir(self, tmp_path):
        """A directory without .git/ is rejected with a clear message."""
        bare = tmp_path / "bare"
        bare.mkdir()
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", str(bare)])
        assert result.exit_code == 1
        assert "git" in result.output.lower() or "not a" in result.output.lower()
        factory.assert_not_called()

    def test_local_path_rejected_traversal(self, tmp_path):
        """Paths containing `..` segments are rejected outright."""
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "../etc"])
        assert result.exit_code == 1
        factory.assert_not_called()

    def test_local_path_rejected_nonexistent(self, tmp_path):
        """A path that does not exist is rejected before invoking the factory."""
        missing = tmp_path / "does-not-exist"
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", str(missing)])
        assert result.exit_code == 1
        factory.assert_not_called()

    def test_local_path_rejected_when_file(self, tmp_path):
        """A regular file (not a directory) is rejected."""
        f = tmp_path / "file.txt"
        f.write_text("hi", encoding="utf-8")
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", str(f)])
        assert result.exit_code == 1
        factory.assert_not_called()

    def test_https_url_still_works(self):
        """Regression: existing HTTPS URL flow remains unchanged."""
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        factory.assert_called_once()
        assert factory.call_args[1]["repo_url"] == "https://github.com/test/repo"

    def test_tilde_path_accepted(self, tmp_path, monkeypatch):
        """A `~`-prefixed path expands and is accepted as a local path."""
        repo = _make_local_repo(tmp_path / "home-repo")
        monkeypatch.setenv("HOME", str(tmp_path))
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "~/home-repo"])
        assert result.exit_code == 0, result.output
        factory.assert_called_once()
