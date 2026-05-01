"""OpenTelemetry adapter implementing ``TracerPort`` (ADR-023, #30 + #33).

Two concrete adapters live in this module:

- :class:`OtelTracerAdapter` — production adapter. OTLP/HTTP exporter
  routed through a ``BatchSpanProcessor``. Wired at the composition
  root only when ``--otel-endpoint`` is supplied.
- :class:`InMemoryTracerAdapter` — test-time adapter using the OTel
  SDK's ``InMemorySpanExporter``. Lets the trace-shape contract tests
  inspect the spans the production adapter would emit, without booting
  a collector.

Both adapters share the same TracerPort surface and the same
sensitive-attribute redaction rules so a Span behaves identically in
production and in tests.

Sensitive-attribute discipline (ADR-023 §5): keys whose name contains
``key``, ``secret``, ``token``, ``body``, ``content``, or ``code`` are
dropped before the span leaves the process. Same defensive posture as
``JsonlAuditAdapter``.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from spectra.use_cases.interfaces import Span

if TYPE_CHECKING:
    from collections.abc import Iterator

    from opentelemetry.sdk.trace import Span as OtelSpan

_LOG = logging.getLogger("spectra.tracing")

# ADR-023 §5 — sensitive substring fragments (case-insensitive).
_SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "secret",
    "session_token",
    "auth_token",
    "access_token",
    "refresh_token",
    "bearer",
    "password",
    "passwd",
    "credential",
    "private_key",
    "request_body",
    "response_body",
    "raw_body",
    "file_content",
    "file_contents",
    "raw_content",
    "raw_code",
    "source_code",
    "snippet",
)
"""Substrings that disqualify an attribute key. The list is intentionally
specific — substring-matching ``token`` alone would block legitimate
cost attributes like ``tokens.input`` and ``tokens.output``. Each
fragment captures a real leak vector documented in ADR-023 §5."""


def drop_sensitive_attributes(
    attributes: dict[str, str | int | float | bool],
) -> dict[str, str | int | float | bool]:
    """Filter ``attributes`` to remove any key matching the sensitive allowlist.

    Substring match (case-insensitive). The dropped keys are NOT logged
    by name (logging the key would defeat the redaction). A WARN is
    emitted exactly once per process the first time any key is dropped
    so operators see the boundary firing.

    Args:
        attributes: The attribute map a caller wants to set on a span.

    Returns:
        A new dict containing only keys that pass the redaction filter.
    """
    cleaned: dict[str, str | int | float | bool] = {}
    dropped = False
    for key, value in attributes.items():
        if _is_sensitive_key(key):
            dropped = True
            continue
        cleaned[key] = value
    if dropped:
        _warn_once_on_redaction()
    return cleaned


def _is_sensitive_key(key: str) -> bool:
    """True when ``key`` contains any sensitive fragment (case-insensitive)."""
    lowered = key.lower()
    return any(frag in lowered for frag in _SENSITIVE_KEY_FRAGMENTS)


_REDACTION_WARNED: bool = False


def _warn_once_on_redaction() -> None:
    """Log the sensitive-attribute boundary firing — at most once per process."""
    global _REDACTION_WARNED  # noqa: PLW0603 — single-fire process-wide flag
    if _REDACTION_WARNED:
        return
    _LOG.warning("ADR-023: dropped one or more sensitive span attributes; check call sites")
    _REDACTION_WARNED = True


# ── Span wrapper ─────────────────────────────────────────────


class _RedactingSpan:
    """Wraps an OTel span and applies the ADR-023 §5 redaction rules.

    Calls that would otherwise leak code, secrets, or token material are
    silently dropped at the boundary. Safe scalar attributes pass through.
    """

    def __init__(self, otel_span: OtelSpan) -> None:
        self._span = otel_span

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """Set ``key=value`` unless ``key`` matches the sensitive allowlist."""
        if _is_sensitive_key(key):
            _warn_once_on_redaction()
            return
        self._span.set_attribute(key, value)

    def add_event(self, name: str, attributes: dict[str, object] | None = None) -> None:
        """Append a named event; redact attribute keys that match the allowlist."""
        if attributes is None:
            self._span.add_event(name)
            return
        cleaned = {k: v for k, v in attributes.items() if not _is_sensitive_key(k)}
        if len(cleaned) != len(attributes):
            _warn_once_on_redaction()
        self._span.add_event(name, cleaned)

    def record_exception(self, exc: BaseException) -> None:
        """Record an exception under the standard OTel ``exception`` event."""
        self._span.record_exception(exc)


# ── Tracer adapters ──────────────────────────────────────────


class _BaseOtelTracerAdapter:
    """Shared lifecycle for OTel-backed adapters.

    Subclasses supply the ``SpanProcessor`` (BatchSpanProcessor →
    OTLP for production, SimpleSpanProcessor → InMemorySpanExporter
    for tests).
    """

    def __init__(self, provider: TracerProvider, instrumentation: str = "spectra") -> None:
        self._provider = provider
        self._tracer = provider.get_tracer(instrumentation)

    @contextmanager
    def span(
        self,
        name: str,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> Iterator[Span]:
        """Open a span as a context manager — yields a redacting Span wrapper.

        Initial attributes pass through ``drop_sensitive_attributes`` so
        a careless caller cannot leak code/secrets at construction time.
        Exceptions inside the body are auto-recorded by OTel via
        ``set_status(StatusCode.ERROR)`` — the wrapper does not need to
        re-implement it.
        """
        cleaned = drop_sensitive_attributes(attributes) if attributes else None
        with self._tracer.start_as_current_span(name, attributes=cleaned) as otel_span:
            yield _RedactingSpan(otel_span)


class OtelTracerAdapter(_BaseOtelTracerAdapter):
    """Production tracer — exports spans to an OTLP/HTTP collector.

    The ``BatchSpanProcessor`` flushes spans asynchronously in batches,
    so ``with tracer.span(...):`` adds < 1ms to the pipeline hot path.
    A failing collector never blocks the pipeline; the OTel SDK's
    internal queue drops spans under back-pressure with a metric.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        resource_attributes: dict[str, str] | None = None,
        timeout_seconds: int = 5,
    ) -> None:
        resource = Resource.create({"service.name": "spectra", **(resource_attributes or {})})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, timeout=timeout_seconds)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        super().__init__(provider, instrumentation="spectra")


class InMemoryTracerAdapter(_BaseOtelTracerAdapter):
    """Test-time tracer — keeps spans in process via ``InMemorySpanExporter``.

    Same Protocol surface as the production adapter so trace-shape
    contract tests run against the exact code that will execute in
    production. ``adapter.exporter.get_finished_spans()`` returns the
    recorded spans in finish order.
    """

    def __init__(self, *, resource_attributes: dict[str, str] | None = None) -> None:
        resource = Resource.create({"service.name": "spectra-test", **(resource_attributes or {})})
        provider = TracerProvider(resource=resource)
        self.exporter = InMemorySpanExporter()
        # SimpleSpanProcessor — synchronous flush so tests can read spans
        # immediately after the ``with`` block exits.
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        super().__init__(provider, instrumentation="spectra-test")
        # Each test instance gets its own provider; we deliberately do NOT
        # register it as the global ``trace`` provider — that would leak
        # state across tests. ``start_as_current_span`` is bound to the
        # local ``self._tracer`` so context propagation stays scoped.
