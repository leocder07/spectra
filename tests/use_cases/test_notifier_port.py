"""Contract tests for ``NotifierPort`` — Layer 2 outbound notification port.

Shared by capability #27 (drift detection + Slack alerts) and capability
#34 (Slack/Teams digest + per-finding alert). Two real adapters live in
Layer 4 (``SlackWebhookAdapter``, ``TeamsWebhookAdapter``); both
implement this port via structural subtyping.
"""

from __future__ import annotations

import inspect

import pytest

from spectra.entities.models import NotifierMessage
from spectra.use_cases.interfaces import NotifierPort


def test_notifier_port_is_protocol() -> None:
    """``NotifierPort`` exposes a single ``send`` method."""
    assert hasattr(NotifierPort, "send")


def test_notifier_port_send_is_async() -> None:
    """``send`` is a coroutine — webhook POSTs are network I/O."""
    assert inspect.iscoroutinefunction(NotifierPort.send)


@pytest.mark.asyncio
async def test_in_memory_stub_satisfies_port() -> None:
    """A trivial stub satisfies ``NotifierPort`` by structural typing."""
    from typing import cast

    class _Stub:
        def __init__(self) -> None:
            self.sent: list[NotifierMessage] = []

        async def send(self, message: NotifierMessage) -> None:
            self.sent.append(message)

    stub = _Stub()
    port: NotifierPort = cast("NotifierPort", stub)
    msg = NotifierMessage(title="t", body_markdown="b", severity="info")
    await port.send(msg)
    # The stub still records the message for the runtime assertion.
    assert stub.sent == [msg]
