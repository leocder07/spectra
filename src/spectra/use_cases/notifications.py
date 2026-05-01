"""Best-effort notifier emit helper — capability #27 + #34.

Mirrors the ``safe_emit`` pattern from ``spectra.use_cases.audit``: a
``None`` port is a valid configuration (notifier disabled), and any
exception from the adapter is logged at DEBUG and swallowed. The
analysis pipeline must never abort because a Slack/Teams webhook is
down or misconfigured.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spectra.entities.models import NotifierMessage
    from spectra.use_cases.interfaces import NotifierPort

_LOG = logging.getLogger("spectra.notifications")


async def safe_send(port: NotifierPort | None, message: NotifierMessage) -> None:
    """Send ``message`` via ``port`` without ever propagating an error.

    A ``None`` port is a valid configuration (notifier disabled). Any
    exception from the adapter is logged at DEBUG and swallowed — the
    analysis pipeline must keep running.
    """
    if port is None:
        return
    try:
        await port.send(message)
    except Exception as exc:
        _LOG.debug("Notifier send failed (title=%s): %s", message.title, exc)


__all__ = ["safe_send"]
