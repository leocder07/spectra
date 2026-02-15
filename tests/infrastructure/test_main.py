"""Tests for the composition root — main.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from spectra.infrastructure.main import ReportError, _run_analysis, cli

# ── ReportError ───────────────────────────────────────────────


class TestReportError:
    def test_has_error_attribute(self):
        from spectra.entities.errors import ERRORS

        err = ReportError(ERRORS["SPEC-009"])
        assert err.error.code == "SPEC-009"

    def test_message_contains_code(self):
        from spectra.entities.errors import ERRORS

        err = ReportError(ERRORS["SPEC-009"])
        assert "SPEC-009" in str(err)

    def test_message_contains_description(self):
        from spectra.entities.errors import ERRORS

        err = ReportError(ERRORS["SPEC-009"])
        assert "Report render failed" in str(err)

    def test_is_exception(self):
        from spectra.entities.errors import ERRORS

        err = ReportError(ERRORS["SPEC-009"])
        assert isinstance(err, Exception)


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
