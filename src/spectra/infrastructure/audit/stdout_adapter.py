"""Stdout audit adapter — one JSON line per emit, sys.stdout.

Default sink in interactive mode; downstream tools that already capture
``stdout`` (CI runners, container logs) ingest events without any extra
wiring.
"""

from __future__ import annotations

import sys

from spectra.entities.audit import AuditEvent


class StdoutAuditAdapter:
    """Print events as JSON lines on ``sys.stdout``.

    Uses ``sys.stdout`` directly (not the ``logging`` machinery) because
    audit events are structured data, not human-formatted log lines —
    handlers downstream need clean JSON.
    """

    async def emit(self, event: AuditEvent) -> None:
        """Write one JSON line for ``event`` and flush immediately."""
        sys.stdout.write(event.model_dump_json() + "\n")
        sys.stdout.flush()

    async def flush(self) -> None:
        """Stdout has no buffer the adapter owns."""
        return
