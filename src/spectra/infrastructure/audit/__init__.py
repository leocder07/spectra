"""Audit-port adapters (Layer 4).

Three implementations of :class:`spectra.use_cases.interfaces.AuditPort`:

- :class:`JsonLinesAuditAdapter` — append to a file with daily rotation.
  Default sink for OSS / single-machine devs.
- :class:`StdoutAuditAdapter` — print each event as one JSON line on
  ``stdout``. Default in interactive mode + the CI-friendly choice for
  pipelines that already capture stdout.
- :class:`OtlpAuditAdapter` — POST events to an OpenTelemetry-compatible
  HTTP collector. Minimal stub today; full OTLP semantics belong to the
  customer's collector.

All three swallow nothing internally — the contract is enforced at the
caller via :func:`spectra.use_cases.audit.safe_emit`. Adapters MAY raise
on a sink failure; the helper turns that into a DEBUG log.
"""

from __future__ import annotations

from spectra.infrastructure.audit.jsonl_adapter import JsonLinesAuditAdapter
from spectra.infrastructure.audit.otlp_adapter import OtlpAuditAdapter
from spectra.infrastructure.audit.stdout_adapter import StdoutAuditAdapter

__all__ = [
    "JsonLinesAuditAdapter",
    "OtlpAuditAdapter",
    "StdoutAuditAdapter",
]
