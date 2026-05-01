"""Tests for the notifier factory — auto-detects Slack vs Teams from URL host."""

from __future__ import annotations

import pytest

from spectra.infrastructure.notifiers import (
    SlackWebhookAdapter,
    TeamsWebhookAdapter,
    notifier_from_url,
)


def test_slack_url_routes_to_slack_adapter() -> None:
    adapter = notifier_from_url("https://hooks.slack.com/services/T0/B0/SECRET")
    assert isinstance(adapter, SlackWebhookAdapter)


def test_teams_url_routes_to_teams_adapter() -> None:
    adapter = notifier_from_url("https://outlook.webhook.office.com/webhookb2/abc")
    assert isinstance(adapter, TeamsWebhookAdapter)


def test_unknown_url_raises() -> None:
    with pytest.raises(ValueError, match=r"Slack|Teams"):
        notifier_from_url("https://example.com/wat")
