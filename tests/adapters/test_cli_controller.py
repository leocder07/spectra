"""Tests for CLI controller — Typer argument parsing and error handling."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from spectra.adapters.cli_controller import app, set_analyzer_factory
from spectra.entities.errors import (
    ERRORS,
    AgentError,
    GitError,
    SecretDetectedError,
    SpectraRetryError,
)
from spectra.entities.models import (
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    SecretFinding,
    score_to_grade,
)

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _fake_report(*, overall: float = 83.0, findings: tuple = ()):
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
        findings=findings,
        total_findings=18,
        analysis_duration_seconds=42.0,
        total_cost_usd=0.15,
        is_degraded=False,
        degraded_dimensions=(),
    )


def _finding_at(severity: str, *, idx: int = 1) -> Finding:
    """Build a minimal Finding at a given severity for --fail-on tests."""
    return Finding(
        id=f"f-{severity}-{idx}",
        dimension="security",
        severity=severity,
        title=f"{severity} test finding",
        description="Test",
        location=FileLocation(file_path=f"src/file{idx}.py", line_start=idx),
        recommendation="Fix",
        agent_role="security",
        confidence=0.9,
    )


# ── Basic CLI navigation ─────────────────────────────────────


class TestCLIController:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # no_args_is_help=True causes Typer to exit with code 0 or 2
        assert result.exit_code in (0, 2)
        assert "analyze" in result.output.lower() or "usage" in result.output.lower()

    def test_version_flag(self):
        from spectra import __version__

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert f"v{__version__}" in result.output

    def test_version_short_flag(self):
        from spectra import __version__

        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert f"v{__version__}" in result.output

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
        _make_local_repo(tmp_path / "home-repo")
        monkeypatch.setenv("HOME", str(tmp_path))
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "~/home-repo"])
        assert result.exit_code == 0, result.output
        factory.assert_called_once()


# ── Phase 2: --force / --no-cache flags ──────────────────────


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes and collapse whitespace.

    Rich wraps narrow terminals by inserting ANSI sequences mid-token
    (e.g. ``--force`` → ``-\\x1b[0m\\x1b[1;36m-force``). Substring
    assertions need normalized text.
    """
    return re.sub(r"\x1b\[[\d;]*m", "", text).replace("\n", " ")


class TestCLICacheFlags:
    def test_force_flag_help_listed(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert "--force" in _strip_ansi(result.output)

    def test_no_cache_flag_help_listed(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert "--no-cache" in _strip_ansi(result.output)

    def test_cli_force_flag_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--force"],
        )
        assert result.exit_code == 0
        factory.assert_called_once()
        assert factory.call_args.kwargs["force"] is True
        assert factory.call_args.kwargs["no_cache"] is False

    def test_cli_no_cache_flag_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--no-cache"],
        )
        assert result.exit_code == 0
        factory.assert_called_once()
        assert factory.call_args.kwargs["force"] is False
        assert factory.call_args.kwargs["no_cache"] is True

    def test_cli_default_flags_off(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["force"] is False
        assert kwargs["no_cache"] is False

    def test_force_and_no_cache_can_combine(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--force",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["force"] is True
        assert kwargs["no_cache"] is True


# ── Phase 4: spectra cache stats|clear|prune ────────────────────


class _StubCachePort:
    """Lightweight stub satisfying the CachePort surface used by Phase 4 CLI."""

    def __init__(
        self,
        *,
        stats_obj: object | None = None,
        clear_all_returns: int = 0,
        clear_by_repo_returns: int = 0,
        prune_returns: dict[str, int] | None = None,
    ) -> None:
        from datetime import UTC, datetime

        from spectra.entities.models import CacheStats

        self._stats = stats_obj or CacheStats(
            total_entries=7,
            total_repos=2,
            db_size_bytes=8192,
            hit_rate_last_100=0.75,
            oldest_entry_at=datetime.now(UTC),
            full_report_entries=2,
            batch_entries=4,
            hit_log_entries=1,
            hit_rate_by_dimension={"security": 0.9},
            most_recent_activity_at=datetime.now(UTC),
        )
        self._clear_all_returns = clear_all_returns
        self._clear_by_repo_returns = clear_by_repo_returns
        self._prune_returns = prune_returns or {
            "findings_cache": 0,
            "full_report_cache": 0,
            "findings_batches": 0,
        }
        self.clear_all_called = False
        self.clear_by_repo_calls: list[str] = []
        self.prune_calls: list[tuple[object, bool]] = []

    def stats(self):
        return self._stats

    def clear_all(self) -> int:
        self.clear_all_called = True
        return self._clear_all_returns

    def clear_by_repo(self, sig: str) -> int:
        self.clear_by_repo_calls.append(sig)
        return self._clear_by_repo_returns

    def prune_older_than(
        self,
        cutoff: object,
        include_hit_log: bool = False,
    ) -> dict[str, int]:
        self.prune_calls.append((cutoff, include_hit_log))
        return self._prune_returns

    def compute_repo_signature(self, file_tree: tuple[str, ...]) -> str:
        del file_tree
        return "deadbeefdeadbeefdeadbeefdeadbeef"

    @property
    def db_path(self):
        from pathlib import Path

        return Path("/tmp/cache.db")  # noqa: S108

    @property
    def has_secret(self) -> bool:
        return True

    def count_rows(self) -> dict:
        return {
            "findings_cache": {"total": 5, "verified": 5, "failed": 0},
            "full_report_cache": {"total": 1, "verified": 1, "failed": 0},
            "findings_batches": {"total": 3, "verified": 2, "failed": 1},
        }


class TestCacheStatsCommand:
    def test_cache_stats_command_renders_table(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "stats"])
        assert result.exit_code == 0
        # The Rich table renders the dimension header label and entry totals.
        assert "Total" in result.output or "total" in result.output.lower()
        assert "7" in result.output  # total_entries seeded above

    def test_cache_stats_default_behavior_unchanged(self):
        """Regression: without --json the Rich table still renders."""
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "stats"])
        assert result.exit_code == 0
        assert "Total" in result.output or "total" in result.output.lower()
        assert "7" in result.output

    def test_cache_stats_json_flag_outputs_valid_json(self):
        import json

        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "stats", "--json"])
        assert result.exit_code == 0
        # Output must parse as JSON without error.
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)

    def test_cache_stats_json_includes_all_fields(self):
        import json

        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "stats", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        expected_keys = {
            "total_entries",
            "total_repos",
            "db_size_bytes",
            "hit_rate_last_100",
            "oldest_entry_at",
            "full_report_entries",
            "batch_entries",
            "hit_log_entries",
            "hit_rate_by_dimension",
            "most_recent_activity_at",
        }
        assert expected_keys.issubset(parsed.keys())

    def test_cache_stats_json_no_rich_codes(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "stats", "--json"])
        assert result.exit_code == 0
        # No ANSI escape sequences (Rich color codes) in JSON output.
        assert "\x1b" not in result.output

    def test_cache_stats_json_help_describes_flag(self):
        result = runner.invoke(app, ["cache", "stats", "--help"])
        assert result.exit_code == 0
        lowered = result.output.lower()
        assert "json" in lowered or "ci-friendly" in lowered


class TestCacheClearCommand:
    def test_cache_clear_command_no_arg_prompts_for_confirm(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort(clear_all_returns=4)
        set_cache_provider(lambda: port)
        # Reply 'n' to the confirm prompt → no clear performed.
        result = runner.invoke(app, ["cache", "clear"], input="n\n")
        assert result.exit_code == 0
        assert not port.clear_all_called

    def test_cache_clear_command_with_yes_skips_prompt(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort(clear_all_returns=4)
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "clear", "--yes"])
        assert result.exit_code == 0
        assert port.clear_all_called

    def test_cache_clear_command_with_repo_arg_clears_only_that_repo(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort(clear_by_repo_returns=2)
        set_cache_provider(lambda: port)
        result = runner.invoke(
            app,
            [
                "cache",
                "clear",
                "https://github.com/test/repo",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert not port.clear_all_called
        assert len(port.clear_by_repo_calls) == 1

    def test_cache_clear_returns_row_count_in_output(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort(clear_all_returns=47)
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "clear", "--yes"])
        assert result.exit_code == 0
        assert "47" in result.output


class TestCachePruneCommand:
    def test_cache_prune_command_parses_30d(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort(
            prune_returns={
                "findings_cache": 1,
                "full_report_cache": 0,
                "findings_batches": 2,
            }
        )
        set_cache_provider(lambda: port)
        result = runner.invoke(
            app,
            ["cache", "prune", "--older-than", "30d"],
        )
        assert result.exit_code == 0
        assert len(port.prune_calls) == 1

    def test_cache_prune_command_parses_4w(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(
            app,
            ["cache", "prune", "--older-than", "4w"],
        )
        assert result.exit_code == 0
        assert len(port.prune_calls) == 1

    def test_cache_prune_command_dry_run_does_not_modify_cache(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(
            app,
            ["cache", "prune", "--older-than", "30d", "--dry-run"],
        )
        assert result.exit_code == 0
        assert len(port.prune_calls) == 0

    def test_cache_prune_invalid_duration_returns_friendly_error(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(
            app,
            ["cache", "prune", "--older-than", "blarg"],
        )
        assert result.exit_code == 1
        assert "duration" in result.output.lower() or "older-than" in result.output.lower()
        assert len(port.prune_calls) == 0


# ── Per-agent model + effort overrides ───────────────────────


class TestCLIModelEffortFlags:
    def test_cli_model_flag_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--model", "claude-sonnet-4-6"],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        assert overrides is not None
        assert overrides.get("global_model") == "claude-sonnet-4-6"

    def test_cli_effort_flag_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--model",
                "claude-sonnet-4-6",
                "--effort",
                "high",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        assert overrides.get("global_effort") == "high"

    def test_cli_per_agent_security_model_flag_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--security-model",
                "claude-opus-4-6",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        assert overrides["models"]["security"] == "claude-opus-4-6"

    def test_cli_per_agent_documentation_effort_flag_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--documentation-effort",
                "low",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        assert overrides["efforts"]["documentation"] == "low"

    def test_cli_meta_and_critique_flags_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--meta-effort",
                "low",
                "--critique-model",
                "claude-opus-4-6",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        assert overrides["efforts"]["meta_prompter"] == "low"
        assert overrides["models"]["critique"] == "claude-opus-4-6"

    def test_cli_model_overrides_json_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--model-overrides",
                '{"security":"claude-opus-4-6","documentation":"claude-haiku-4-5"}',
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        assert overrides["models"]["security"] == "claude-opus-4-6"
        assert overrides["models"]["documentation"] == "claude-haiku-4-5"

    def test_cli_effort_overrides_json_parsed(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--effort-overrides",
                '{"security":"max","quality":"low"}',
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        assert overrides["efforts"]["security"] == "max"
        assert overrides["efforts"]["quality"] == "low"

    def test_cli_invalid_model_returns_error(self):
        set_analyzer_factory(AsyncMock(return_value=None))
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--model", "gpt-4"],
        )
        assert result.exit_code == 1
        assert "claude-opus-4-7" in result.output  # Allowed list shown

    def test_cli_invalid_effort_returns_error(self):
        set_analyzer_factory(AsyncMock(return_value=None))
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--effort",
                "ultra",
            ],
        )
        assert result.exit_code == 1
        assert "low" in result.output  # Allowed effort levels referenced

    def test_cli_max_effort_on_haiku_returns_error(self):
        set_analyzer_factory(AsyncMock(return_value=None))
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--documentation-model",
                "claude-haiku-4-5",
                "--documentation-effort",
                "max",
            ],
        )
        assert result.exit_code == 1
        assert "max" in result.output.lower() or "opus" in result.output.lower()

    def test_cli_json_overrides_take_precedence_over_per_flag(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--security-model",
                "claude-opus-4-6",
                "--model-overrides",
                '{"security":"claude-sonnet-4-6"}',
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        # JSON wins
        assert overrides["models"]["security"] == "claude-sonnet-4-6"

    def test_cli_no_flags_keeps_existing_behavior(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        overrides = kwargs.get("agent_overrides")
        # Either omitted entirely or empty
        assert (
            overrides is None
            or overrides == {}
            or (
                not overrides.get("global_model")
                and not overrides.get("global_effort")
                and not overrides.get("models")
                and not overrides.get("efforts")
            )
        )

    def test_cli_invalid_model_overrides_json_returns_error(self):
        set_analyzer_factory(AsyncMock(return_value=None))
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--model-overrides",
                "not-json",
            ],
        )
        assert result.exit_code == 1
        assert "json" in result.output.lower() or "invalid" in result.output.lower()


# ── ADR-012: spectra cache doctor ──────────────────────────────


class TestCacheDoctorCommand:
    def test_cache_doctor_prints_path_uid_and_backend(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "doctor"])
        assert result.exit_code == 0
        # Path is rendered in the output table — the stub returns
        # ``/tmp/cache.db`` (Rich may wrap; check filename only).
        assert "cache.db" in result.output
        # UID label is printed (host-dependent value, just check the label).
        assert "UID" in result.output or "uid" in result.output.lower()
        # Backend label appears.
        assert "backend" in result.output.lower()

    def test_cache_doctor_prints_per_table_verified_and_failed(self):
        from spectra.adapters.cli_controller import set_cache_provider

        port = _StubCachePort()
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "doctor"])
        assert result.exit_code == 0
        # Stub seeds 1 failed batch row; the count must surface.
        assert "1" in result.output
        assert "findings_batches" in result.output


# ── Pre-flight flag wiring ───────────────────────────────────


class TestCLIPreflightFlags:
    """CLI surface for capability #6 — secret pre-flight + .gitignore."""

    def test_analyze_command_registers_no_gitignore(self):
        import typer

        click_app = typer.main.get_command(app)
        analyze = click_app.get_command(None, "analyze")
        flags = {opt for p in analyze.params if hasattr(p, "opts") for opt in p.opts}
        assert "--no-gitignore" in flags

    def test_analyze_command_registers_allow_secrets(self):
        import typer

        click_app = typer.main.get_command(app)
        analyze = click_app.get_command(None, "analyze")
        flags = {opt for p in analyze.params if hasattr(p, "opts") for opt in p.opts}
        assert "--allow-secrets" in flags

    def test_default_passes_flags_safely(self):
        """No --no-gitignore means honor_gitignore=True; no --allow-secrets means False."""
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        kwargs = factory.call_args.kwargs
        assert kwargs["honor_gitignore"] is True
        assert kwargs["allow_secrets"] is False

    def test_no_gitignore_flag_inverts_honor_flag(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--no-gitignore"],
        )
        assert result.exit_code == 0
        assert factory.call_args.kwargs["honor_gitignore"] is False

    def test_allow_secrets_flag_propagates(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--allow-secrets"],
        )
        assert result.exit_code == 0
        assert factory.call_args.kwargs["allow_secrets"] is True

    def test_secret_detected_error_renders_brand_voice_failure(self):
        findings = (
            SecretFinding(file_path=".env", line=1, pattern_name="aws_access_key"),
            SecretFinding(file_path="src/leak.py", line=42, pattern_name="github_pat"),
        )
        factory = AsyncMock(side_effect=SecretDetectedError(findings))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "SPEC-011" in result.output
        # Per-finding listing
        assert "aws_access_key" in result.output
        assert ".env" in result.output
        assert "github_pat" in result.output
        assert "src/leak.py" in result.output
        # Escape hatch hint
        assert "--allow-secrets" in result.output

    def test_secret_detected_message_no_trailing_period(self):
        findings = (SecretFinding(file_path=".env", line=1, pattern_name="aws_access_key"),)
        factory = AsyncMock(side_effect=SecretDetectedError(findings))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        # Find the SPEC-011 line and check no trailing period
        for line in result.output.splitlines():
            if "SPEC-011" in line:
                # strip trailing whitespace/Rich markup remnants
                stripped = re.sub(r"\s+$", "", line)
                assert not stripped.endswith(".")
                break
        else:
            pytest.fail("SPEC-011 line not found in output")


# ── Q2 #19: --fail-on severity gate ──────────────────────────


class TestFailOnSeverityGate:
    """``--fail-on <severity>`` exits 1 when any finding is at or above
    the threshold; ``none`` disables the gate (always exit 0).

    Severity ordering (worst first): critical > high > medium > low.
    """

    def test_analyze_command_registers_fail_on(self):
        import typer

        click_app = typer.main.get_command(app)
        analyze = click_app.get_command(None, "analyze")
        flags = {opt for p in analyze.params if hasattr(p, "opts") for opt in p.opts}
        assert "--fail-on" in flags

    def test_default_fail_on_is_none_so_no_gating(self):
        report = _fake_report(findings=(_finding_at("critical"),))
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0

    def test_fail_on_critical_with_critical_finding_exits_1(self):
        report = _fake_report(findings=(_finding_at("critical"),))
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "critical"],
        )
        assert result.exit_code == 1
        assert "fail-on" in result.output.lower() or "severity" in result.output.lower()

    def test_fail_on_critical_with_only_high_findings_exits_0(self):
        report = _fake_report(
            findings=(_finding_at("high", idx=1), _finding_at("high", idx=2)),
        )
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "critical"],
        )
        assert result.exit_code == 0

    def test_fail_on_high_with_only_high_findings_exits_1(self):
        report = _fake_report(findings=(_finding_at("high"),))
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "high"],
        )
        assert result.exit_code == 1

    def test_fail_on_high_with_only_medium_findings_exits_0(self):
        report = _fake_report(findings=(_finding_at("medium"),))
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "high"],
        )
        assert result.exit_code == 0

    def test_fail_on_medium_with_low_findings_exits_0(self):
        report = _fake_report(findings=(_finding_at("low"),))
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "medium"],
        )
        assert result.exit_code == 0

    def test_fail_on_low_with_low_findings_exits_1(self):
        report = _fake_report(findings=(_finding_at("low"),))
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "low"],
        )
        assert result.exit_code == 1

    def test_fail_on_none_with_critical_findings_exits_0(self):
        report = _fake_report(findings=(_finding_at("critical"),))
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "none"],
        )
        assert result.exit_code == 0

    def test_fail_on_invalid_severity_rejected(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "BOGUS"],
        )
        assert result.exit_code == 1
        assert "fail-on" in result.output.lower() or "invalid" in result.output.lower()
        assert "critical" in result.output.lower()
        assert "none" in result.output.lower()

    def test_fail_on_critical_with_no_findings_exits_0(self):
        report = _fake_report(findings=())
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "critical"],
        )
        assert result.exit_code == 0

    def test_fail_on_message_names_offending_severity_count(self):
        report = _fake_report(
            findings=(
                _finding_at("critical", idx=1),
                _finding_at("critical", idx=2),
            ),
        )
        factory = AsyncMock(return_value=report)
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            ["analyze", "https://github.com/test/repo", "--fail-on", "critical"],
        )
        assert result.exit_code == 1
        assert "2" in result.output


# ── Capability #56 — --classification flag ───────────────────


class TestCLIClassificationFlag:
    """The CLI exposes --classification {confidential,public}.

    Default is ``confidential`` (regression: existing users keep current
    behavior). The chosen mode reaches the analyzer factory and the
    output filename is suffixed accordingly.
    """

    def test_analyze_command_registers_classification(self):
        import typer

        click_app = typer.main.get_command(app)
        analyze = click_app.get_command(None, "analyze")
        flags = {opt for p in analyze.params if hasattr(p, "opts") for opt in p.opts}
        assert "--classification" in flags

    def test_default_classification_is_confidential(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 0
        kwargs = factory.call_args[1]
        assert kwargs["classification"] == "confidential"

    def test_explicit_public_classification_is_threaded_through(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--classification",
                "public",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args[1]
        assert kwargs["classification"] == "public"

    def test_invalid_classification_value_rejected(self):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--classification",
                "secret",
            ],
        )
        assert result.exit_code == 1
        assert "classification" in result.output.lower()

    def test_output_path_suffixed_for_confidential(self, tmp_path):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        out = tmp_path / "spectra-report.html"
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args[1]
        assert kwargs["output_path"].endswith("spectra-report-confidential.html")

    def test_output_path_suffixed_for_public(self, tmp_path):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        out = tmp_path / "spectra-report.html"
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--output",
                str(out),
                "--classification",
                "public",
            ],
        )
        assert result.exit_code == 0
        kwargs = factory.call_args[1]
        assert kwargs["output_path"].endswith("spectra-report-public.html")

    def test_summary_prints_suffixed_path(self, tmp_path):
        factory = AsyncMock(return_value=_fake_report())
        set_analyzer_factory(factory)
        out = tmp_path / "spectra-report.html"
        result = runner.invoke(
            app,
            [
                "analyze",
                "https://github.com/test/repo",
                "--output",
                str(out),
                "--classification",
                "public",
            ],
        )
        assert result.exit_code == 0
        # Rich line-wraps long paths on narrow terminals — flatten output.
        flat_output = "".join(result.output.split())
        assert "spectra-report-public.html" in flat_output
