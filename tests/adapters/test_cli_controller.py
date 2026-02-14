"""Tests for CLI controller — Typer argument parsing and error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from spectra.adapters.cli_controller import app, set_analyzer_factory
from spectra.entities.errors import ERRORS, AgentError, GitError, SpectraRetryError

runner = CliRunner()


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

    def test_analyze_without_factory_fails(self):
        set_analyzer_factory(None)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "Not initialized" in result.output

    def test_analyze_invalid_format(self):
        set_analyzer_factory(AsyncMock(return_value=None))
        result = runner.invoke(app, [
            "analyze", "https://github.com/test/repo", "--format", "xml",
        ])
        assert result.exit_code == 1
        assert "Invalid format" in result.output

    def test_analyze_help(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "repo-url" in result.output.lower() or "REPO_URL" in result.output


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

    def test_unexpected_error_shows_message(self):
        factory = AsyncMock(side_effect=RuntimeError("something went wrong"))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        assert result.exit_code == 1
        assert "Unexpected error" in result.output
        assert "something went wrong" in result.output

    def test_error_output_uses_red_marker(self):
        factory = AsyncMock(side_effect=GitError(ERRORS["SPEC-001"]))
        set_analyzer_factory(factory)
        result = runner.invoke(app, ["analyze", "https://github.com/test/repo"])
        # Rich markup contains red color code for error indicator
        assert "✗" in result.output
