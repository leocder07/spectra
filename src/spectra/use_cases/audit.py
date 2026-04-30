"""Best-effort emit helper + a no-op adapter for audit events.

The pipeline's contract with audit (ADR-018) is that audit emission must
NEVER abort a scan. :func:`safe_emit` enforces that contract at the call
site so adapters do not have to catch every conceivable error themselves.
"""

from __future__ import annotations

import logging

from spectra.entities.audit import AuditEvent
from spectra.use_cases.interfaces import AuditPort

_LOG = logging.getLogger("spectra.audit")


async def safe_emit(port: AuditPort | None, event: AuditEvent) -> None:
    """Emit ``event`` without ever propagating an error.

    A ``None`` port is a valid configuration (audit disabled). Any
    exception from the adapter is logged at DEBUG and swallowed — the
    analysis pipeline must keep running.
    """
    if port is None:
        return
    try:
        await port.emit(event)
    except Exception as exc:
        _LOG.debug("Audit emit failed (event=%s): %s", event.event, exc)


async def safe_flush(port: AuditPort | None) -> None:
    """Flush ``port`` without ever propagating an error."""
    if port is None:
        return
    try:
        await port.flush()
    except Exception as exc:
        _LOG.debug("Audit flush failed: %s", exc)


class NoopAuditAdapter:
    """``AuditPort`` implementation that drops every event silently.

    Useful as a default when no sink is configured, and as a fixture in
    tests that want to exercise the emit path without observing output.
    """

    async def emit(self, event: AuditEvent) -> None:
        """Drop the event — no sink wired."""
        return

    async def flush(self) -> None:
        """No buffer to flush."""
        return


__all__ = [
    "NoopAuditAdapter",
    "safe_emit",
    "safe_flush",
]
