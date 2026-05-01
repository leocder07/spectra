"""Tests for ``SlackWebhookAdapter`` — Layer 4 implementation of NotifierPort (#27 + #34).

The adapter POSTs Block Kit JSON to a Slack incoming webhook. Failure
modes (timeout, 5xx, malformed URL) are logged + swallowed so a dead
webhook can never abort an analysis run.
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest

from spectra.entities.models import NotifierMessage
from spectra.infrastructure.notifiers import SlackWebhookAdapter


def _capture_transport() -> tuple[list[httpx.Request], httpx.MockTransport]:
    """Build a MockTransport that records every request it sees."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="ok")

    return captured, httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_send_posts_block_kit_json() -> None:
    """``send`` POSTs JSON containing a ``blocks`` array to the webhook URL."""
    captured, transport = _capture_transport()
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/T0/B0/SECRET",
        transport=transport,
    )
    await adapter.send(
        NotifierMessage(
            title="Spectra: drift detected",
            body_markdown="`service-payments` dropped from **A** to **B+**",
            severity="high",
            link_url="https://spectra.example/report/abc",
        )
    )
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert req.url.host == "hooks.slack.com"
    payload = json.loads(req.content)
    assert "blocks" in payload
    assert isinstance(payload["blocks"], list)
    assert len(payload["blocks"]) >= 1


@pytest.mark.asyncio
async def test_send_includes_title_and_body_in_blocks() -> None:
    """The message body and title both appear in the rendered blocks."""
    captured, transport = _capture_transport()
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/T0/B0/SECRET",
        transport=transport,
    )
    await adapter.send(
        NotifierMessage(
            title="Spectra: critical finding",
            body_markdown="SQL injection in `auth/login.py`",
            severity="critical",
        )
    )
    payload = json.loads(captured[0].content)
    text_blob = json.dumps(payload)
    assert "Spectra: critical finding" in text_blob
    assert "SQL injection" in text_blob


@pytest.mark.asyncio
async def test_send_attaches_link_button_when_url_present() -> None:
    """When ``link_url`` is set, an ``actions`` block with a button is added."""
    captured, transport = _capture_transport()
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/X/Y/Z",
        transport=transport,
    )
    await adapter.send(
        NotifierMessage(
            title="t",
            body_markdown="b",
            severity="info",
            link_url="https://spectra.example/report/123",
        )
    )
    payload = json.loads(captured[0].content)
    block_types = [b.get("type") for b in payload["blocks"]]
    assert "actions" in block_types
    actions = next(b for b in payload["blocks"] if b["type"] == "actions")
    elements = actions["elements"]
    assert any(e.get("type") == "button" for e in elements)
    assert any(e.get("url") == "https://spectra.example/report/123" for e in elements)


@pytest.mark.asyncio
async def test_send_omits_actions_block_without_link_url() -> None:
    """No ``actions`` block when no link is provided."""
    captured, transport = _capture_transport()
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/X/Y/Z",
        transport=transport,
    )
    await adapter.send(NotifierMessage(title="t", body_markdown="b", severity="medium"))
    payload = json.loads(captured[0].content)
    block_types = [b.get("type") for b in payload["blocks"]]
    assert "actions" not in block_types


@pytest.mark.asyncio
async def test_send_swallows_5xx_so_pipeline_never_aborts() -> None:
    """A 500 from Slack must not raise — the pipeline must keep running."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/X/Y/Z",
        transport=transport,
    )
    # The contract is "never raise" — so this call returns cleanly.
    await adapter.send(NotifierMessage(title="t", body_markdown="b", severity="info"))


@pytest.mark.asyncio
async def test_send_swallows_transport_errors() -> None:
    """A network error (timeout, connection refused) must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        msg = "boom"
        raise httpx.ConnectError(msg)

    transport = httpx.MockTransport(handler)
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/X/Y/Z",
        transport=transport,
    )
    await adapter.send(NotifierMessage(title="t", body_markdown="b", severity="info"))


@pytest.mark.asyncio
async def test_color_attachment_derived_from_severity() -> None:
    """Severity maps to an attachment color when ``color`` is unset."""
    captured, transport = _capture_transport()
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/X/Y/Z",
        transport=transport,
    )
    await adapter.send(NotifierMessage(title="t", body_markdown="b", severity="critical"))
    payload = json.loads(captured[0].content)
    # attachments carry the colored side-bar in Slack
    attachments = payload.get("attachments")
    assert isinstance(attachments, list)
    assert attachments[0]["color"].lower() in {"#ef4444", "danger"}


@pytest.mark.asyncio
async def test_explicit_color_overrides_severity_default() -> None:
    """An explicit ``color`` on the message wins over the severity default."""
    captured, transport = _capture_transport()
    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/X/Y/Z",
        transport=transport,
    )
    await adapter.send(
        NotifierMessage(
            title="t",
            body_markdown="b",
            severity="info",
            color="#7C3AED",
        )
    )
    payload = json.loads(captured[0].content)
    assert payload["attachments"][0]["color"] == "#7C3AED"


def test_constructor_rejects_non_slack_url() -> None:
    """Slack adapter rejects URLs that do not match the Slack webhook host."""
    with pytest.raises(ValueError, match=r"hooks\.slack\.com"):
        SlackWebhookAdapter(webhook_url="https://example.com/foo")


def test_satisfies_notifier_port_structurally() -> None:
    """Adapter is structurally compatible with NotifierPort."""
    from spectra.use_cases.interfaces import NotifierPort

    adapter = SlackWebhookAdapter(
        webhook_url="https://hooks.slack.com/services/X/Y/Z",
    )
    port = cast("NotifierPort", adapter)
    # Just confirm the structural cast doesn't blow up — no-op runtime check.
    assert port is not None
    _: Any = port.send  # the attribute exists as the spec requires
