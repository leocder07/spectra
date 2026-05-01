"""Tests for the ``--notify-webhook`` and ``--no-drift-alert`` CLI flags."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from spectra.adapters.cli_controller import app, set_analyzer_factory


def _wire_capturing_factory() -> tuple[AsyncMock, dict[str, Any]]:
    """Inject a fake analyzer that records every kwarg the CLI sent."""
    captured: dict[str, Any] = {}

    async def _fake_analyzer(**kwargs: Any) -> object:
        captured.update(kwargs)
        # Return a stub report-like object so the CLI's _print_summary
        # path doesn't blow up.

        class _Report:
            findings: tuple[Any, ...] = ()
            score_card = None

        return _Report()

    mock = AsyncMock(side_effect=_fake_analyzer)
    set_analyzer_factory(mock)
    return mock, captured


def test_notify_webhook_flag_passed_to_analyzer() -> None:
    """``--notify-webhook URL`` is forwarded into the analyzer kwargs."""
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: Awaitable[Any] | Any) -> object:
        captured.update(kwargs)

        class _R:
            findings: tuple[Any, ...] = ()
            score_card = None

        return _R()

    set_analyzer_factory(_fake)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "analyze",
            "https://github.com/octocat/spoon-knife",
            "--notify-webhook",
            "https://hooks.slack.com/services/T0/B0/SECRET",
        ],
    )
    # The CLI may exit with various codes (we don't have a real factory
    # to compute a score), but the kwargs must have been captured first.
    assert captured.get("notify_webhook") == "https://hooks.slack.com/services/T0/B0/SECRET"
    assert result.exit_code in (0, 1)


def test_no_drift_alert_flag_passed_to_analyzer() -> None:
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> object:
        captured.update(kwargs)

        class _R:
            findings: tuple[Any, ...] = ()
            score_card = None

        return _R()

    set_analyzer_factory(_fake)
    runner = CliRunner()
    runner.invoke(
        app,
        [
            "analyze",
            "https://github.com/octocat/spoon-knife",
            "--no-drift-alert",
        ],
    )
    assert captured.get("no_drift_alert") is True


def test_notify_defaults_to_none_when_flag_absent() -> None:
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> object:
        captured.update(kwargs)

        class _R:
            findings: tuple[Any, ...] = ()
            score_card = None

        return _R()

    set_analyzer_factory(_fake)
    runner = CliRunner()
    runner.invoke(app, ["analyze", "https://github.com/octocat/spoon-knife"])
    assert captured.get("notify_webhook") is None
    assert captured.get("no_drift_alert") is False
