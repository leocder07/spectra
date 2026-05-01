"""Tests for the ``safe_send`` helper — never propagates a notifier error."""

from __future__ import annotations

import pytest

from spectra.entities.models import NotifierMessage
from spectra.use_cases.notifications import safe_send


class _RaisingNotifier:
    async def send(self, message: NotifierMessage) -> None:
        msg = "transport boom"
        raise RuntimeError(msg)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[NotifierMessage] = []

    async def send(self, message: NotifierMessage) -> None:
        self.sent.append(message)


@pytest.mark.asyncio
async def test_safe_send_with_none_port_is_noop() -> None:
    msg = NotifierMessage(title="t", body_markdown="b", severity="info")
    # No port wired = no notification, no exception.
    await safe_send(None, msg)


@pytest.mark.asyncio
async def test_safe_send_swallows_exceptions() -> None:
    msg = NotifierMessage(title="t", body_markdown="b", severity="info")
    # The notifier raises but safe_send must NOT propagate.
    await safe_send(_RaisingNotifier(), msg)


@pytest.mark.asyncio
async def test_safe_send_delivers_to_real_port() -> None:
    notifier = _RecordingNotifier()
    msg = NotifierMessage(title="hi", body_markdown="hey", severity="medium")
    await safe_send(notifier, msg)
    assert notifier.sent == [msg]
