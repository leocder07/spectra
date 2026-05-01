"""Outbound webhook notifier adapters — Layer 4 (#27 + #34).

Two adapters that satisfy ``NotifierPort``:

- :class:`SlackWebhookAdapter` — POSTs Slack Block Kit JSON to an
  incoming webhook URL (``hooks.slack.com``).
- :class:`TeamsWebhookAdapter` — POSTs Microsoft Teams Adaptive Card
  JSON to an Office connector webhook URL (``webhook.office.com``).

Both adapters share a contract: webhook outages MUST never abort the
analysis pipeline. Transport errors and 5xx responses are logged at
DEBUG and swallowed. Programmer errors at construction time (malformed
URL, wrong host) raise ``ValueError`` so misconfiguration fails fast.

Why no new dep: Spectra already ships ``httpx`` (see ``pyproject.toml``)
for the Anthropic adapter; we reuse the same client class so the
runtime install stays exactly the same size as before #27 + #34.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse

import httpx

from spectra.entities.enums import Severity

if TYPE_CHECKING:
    from spectra.entities.models import NotifierMessage
    from spectra.use_cases.interfaces import NotifierPort

_LOG = logging.getLogger("spectra.notifiers")

# Conservative timeout — webhook calls are best-effort, not on the
# critical path. Long enough for slow corporate proxies, short enough
# that a hung endpoint cannot stall the pipeline.
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0

# Maps severity → Slack attachment color (hex). Defaults track the
# Spectra brand palette (see CLAUDE.md §Brand Voice).
_SEVERITY_COLOR: Final[dict[Severity, str]] = {
    "critical": "#EF4444",  # red
    "high": "#F59E0B",  # amber
    "medium": "#F59E0B",  # amber
    "low": "#7C3AED",  # violet
    "info": "#22C55E",  # green
}

# Slack-friendly emoji prefixes by severity — used in the section header.
_SEVERITY_EMOJI: Final[dict[Severity, str]] = {
    "critical": ":rotating_light:",
    "high": ":warning:",
    "medium": ":warning:",
    "low": ":information_source:",
    "info": ":white_check_mark:",
}

_SLACK_HOST_SUFFIX: Final[str] = "hooks.slack.com"
_TEAMS_HOST_SUBSTRING: Final[str] = "webhook.office"


class SlackWebhookAdapter:
    """``NotifierPort`` implementation for Slack incoming webhooks (#27).

    Constructor validates the URL host so a wrong webhook (e.g. a Teams
    URL pasted by mistake) fails fast rather than silently 404-ing.
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Wire the webhook target. Raises ValueError on a non-Slack URL.

        Args:
            webhook_url: ``https://hooks.slack.com/services/...`` URL.
            timeout_seconds: Per-request timeout. Defaults to 5s.
            transport: Optional ``httpx.AsyncBaseTransport`` used by
                tests to capture requests without real network I/O.
        """
        host = (urlparse(webhook_url).hostname or "").lower()
        if not host.endswith(_SLACK_HOST_SUFFIX):
            msg = f"Not a Slack webhook URL (expected hooks.slack.com host): {webhook_url!r}"
            raise ValueError(msg)
        self._webhook_url = webhook_url
        self._timeout = timeout_seconds
        self._transport = transport

    async def send(self, message: NotifierMessage) -> None:
        """POST a Block Kit payload to Slack; never raises on outage."""
        payload = _render_slack_payload(message)
        await _post_json_safe(
            url=self._webhook_url,
            payload=payload,
            timeout=self._timeout,
            transport=self._transport,
            channel_label="slack",
        )


class TeamsWebhookAdapter:
    """``NotifierPort`` implementation for Microsoft Teams Office connectors (#34)."""

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Wire the webhook target. Raises ValueError on a non-Teams URL."""
        host = (urlparse(webhook_url).hostname or "").lower()
        if _TEAMS_HOST_SUBSTRING not in host:
            msg = f"Not a Teams webhook URL (expected webhook.office.com host): {webhook_url!r}"
            raise ValueError(msg)
        self._webhook_url = webhook_url
        self._timeout = timeout_seconds
        self._transport = transport

    async def send(self, message: NotifierMessage) -> None:
        """POST an Adaptive Card payload to Teams; never raises on outage."""
        payload = _render_teams_payload(message)
        await _post_json_safe(
            url=self._webhook_url,
            payload=payload,
            timeout=self._timeout,
            transport=self._transport,
            channel_label="teams",
        )


def notifier_from_url(webhook_url: str) -> NotifierPort:
    """Auto-detect Slack vs Teams from the URL and return the matching adapter.

    Slack URLs include ``hooks.slack.com``; Teams URLs include
    ``webhook.office.com``. Anything else raises ``ValueError`` so a
    typo fails fast at the CLI seam.
    """
    host = (urlparse(webhook_url).hostname or "").lower()
    if host.endswith(_SLACK_HOST_SUFFIX):
        return SlackWebhookAdapter(webhook_url=webhook_url)
    if _TEAMS_HOST_SUBSTRING in host:
        return TeamsWebhookAdapter(webhook_url=webhook_url)
    msg = f"Unrecognized webhook URL host {host!r}: expected Slack (hooks.slack.com) or Teams (webhook.office.com)"
    raise ValueError(msg)


# ── Renderers ────────────────────────────────────────────────


def _render_slack_payload(message: NotifierMessage) -> dict[str, object]:
    """Build the Slack Block Kit JSON payload for ``message``."""
    color = message.color or _SEVERITY_COLOR.get(message.severity, "#7C3AED")
    emoji = _SEVERITY_EMOJI.get(message.severity, "")
    blocks: list[dict[str, object]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {message.title}".strip(),
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message.body_markdown,
            },
        },
    ]
    if message.link_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open report"},
                        "url": message.link_url,
                    }
                ],
            }
        )
    return {
        "blocks": blocks,
        "attachments": [{"color": color, "blocks": []}],
    }


def _render_teams_payload(message: NotifierMessage) -> dict[str, object]:
    """Build the Microsoft Teams Adaptive Card JSON payload for ``message``."""
    body: list[dict[str, object]] = [
        {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": message.title,
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": message.body_markdown,
            "wrap": True,
        },
    ]
    actions: list[dict[str, object]] = []
    if message.link_url:
        actions.append(
            {
                "type": "Action.OpenUrl",
                "title": "Open report",
                "url": message.link_url,
            }
        )
    card: dict[str, object] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "actions": actions,
    }
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }


# ── HTTP plumbing ────────────────────────────────────────────


async def _post_json_safe(
    *,
    url: str,
    payload: dict[str, object],
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
    channel_label: str,
) -> None:
    """POST ``payload`` to ``url``; log + swallow every transport error."""
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(url, json=payload)
        if response.status_code >= 400:
            _LOG.debug(
                "Notifier %s POST returned %d: %s",
                channel_label,
                response.status_code,
                response.text[:200],
            )
    except (httpx.TransportError, httpx.HTTPError, OSError) as exc:
        _LOG.debug("Notifier %s POST failed: %s", channel_label, exc)


__all__ = [
    "SlackWebhookAdapter",
    "TeamsWebhookAdapter",
    "notifier_from_url",
]
