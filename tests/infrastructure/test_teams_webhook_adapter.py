"""Tests for ``TeamsWebhookAdapter`` — Layer 4 implementation of NotifierPort (#34).

Renders ``NotifierMessage`` as a Microsoft Teams Adaptive Card payload.
Same failure-mode contract as the Slack adapter: webhook outage MUST
never abort the analysis pipeline.
"""

from __future__ import annotations

import json

import httpx
import pytest

from spectra.entities.models import NotifierMessage
from spectra.infrastructure.notifiers import TeamsWebhookAdapter


def _capture_transport() -> tuple[list[httpx.Request], httpx.MockTransport]:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="1")

    return captured, httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_send_posts_adaptive_card() -> None:
    """The body is an Adaptive Card wrapped in the connector envelope."""
    captured, transport = _capture_transport()
    adapter = TeamsWebhookAdapter(
        webhook_url="https://outlook.webhook.office.com/webhookb2/abc",
        transport=transport,
    )
    await adapter.send(
        NotifierMessage(
            title="Spectra: drift detected",
            body_markdown="`service-payments` dropped",
            severity="high",
            link_url="https://spectra.example/r/x",
        )
    )
    assert len(captured) == 1
    payload = json.loads(captured[0].content)
    assert payload["type"] == "message"
    attachments = payload["attachments"]
    assert len(attachments) == 1
    card = attachments[0]
    assert card["contentType"] == "application/vnd.microsoft.card.adaptive"
    body = card["content"]["body"]
    assert any(item.get("text") == "Spectra: drift detected" for item in body)


@pytest.mark.asyncio
async def test_open_url_action_attached_when_link_present() -> None:
    """An ``Action.OpenUrl`` action is added when a link_url is provided."""
    captured, transport = _capture_transport()
    adapter = TeamsWebhookAdapter(
        webhook_url="https://outlook.webhook.office.com/webhookb2/abc",
        transport=transport,
    )
    await adapter.send(
        NotifierMessage(
            title="t",
            body_markdown="b",
            severity="medium",
            link_url="https://spectra.example/r/x",
        )
    )
    payload = json.loads(captured[0].content)
    actions = payload["attachments"][0]["content"]["actions"]
    assert any(a["type"] == "Action.OpenUrl" and a["url"] == "https://spectra.example/r/x" for a in actions)


@pytest.mark.asyncio
async def test_send_swallows_500() -> None:
    """500 from Teams must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    adapter = TeamsWebhookAdapter(
        webhook_url="https://outlook.webhook.office.com/webhookb2/abc",
        transport=transport,
    )
    await adapter.send(NotifierMessage(title="t", body_markdown="b", severity="info"))


@pytest.mark.asyncio
async def test_send_swallows_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        msg = "boom"
        raise httpx.ConnectError(msg)

    transport = httpx.MockTransport(handler)
    adapter = TeamsWebhookAdapter(
        webhook_url="https://outlook.webhook.office.com/webhookb2/abc",
        transport=transport,
    )
    await adapter.send(NotifierMessage(title="t", body_markdown="b", severity="info"))


def test_constructor_rejects_non_teams_url() -> None:
    with pytest.raises(ValueError, match=r"webhook\.office"):
        TeamsWebhookAdapter(webhook_url="https://example.com/foo")
