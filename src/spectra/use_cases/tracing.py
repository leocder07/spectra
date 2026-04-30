"""Tracing primitives for the use-case layer (ADR-023, #30 + #33).

The pipeline's contract with tracing is identical to its contract with
audit emission (ADR-018): observability MUST NEVER abort a scan.
:func:`safe_span` enforces that contract at the call site so adapters
(OpenTelemetry, third-party APMs) do not have to defend against every
conceivable failure mode themselves.

This module also provides :class:`NoopTracerAdapter` — the
zero-overhead default wired when no ``--otel-endpoint`` is supplied.
The Noop adapter is in Layer 2 (not Layer 4) because it has no
infrastructure dependencies and lets the pipeline default to a wired
``TracerPort`` instead of branching on ``None`` everywhere.

ADR references in this module: ADR-023 (OpenTelemetry tracing + cost
attribution). See ``docs/architecture/adr/`` and ``docs/glossary.md``
for the at-a-glance ADR index.
"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING

from spectra.use_cases.interfaces import Span, TracerPort

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOG = logging.getLogger("spectra.tracing")


class _NoopSpan:
    """Span implementation that drops every method call silently.

    Wired as the fallback whenever tracing is disabled or a tracer
    raises during ``span()`` construction. Carries no state; the same
    instance can be reused (returned by ``NoopTracerAdapter``).
    """

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """Drop the attribute — no sink wired."""
        return

    def add_event(self, name: str, attributes: dict[str, object] | None = None) -> None:
        """Drop the event — no sink wired."""
        return

    def record_exception(self, exc: BaseException) -> None:
        """Drop the exception — no sink wired."""
        return


# Module-level singleton — the no-op span is stateless and reusable.
_NOOP_SPAN: Span = _NoopSpan()


class NoopTracerAdapter:
    """``TracerPort`` implementation that yields a no-op span.

    Default tracer when no ``--otel-endpoint`` is set. Same shape as
    ``NoopAuditAdapter`` — both let the pipeline default to a wired
    Port instead of branching on ``None`` everywhere.
    """

    @contextmanager
    def span(
        self,
        name: str,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> Iterator[Span]:
        """Yield a no-op span; never raises. ``name`` and ``attributes`` are ignored by design."""
        # Touch args so the linter sees them as intentionally unused.
        del name, attributes
        yield _NOOP_SPAN


@contextmanager
def safe_span(
    port: TracerPort | None,
    name: str,
    attributes: dict[str, str | int | float | bool] | None = None,
) -> Iterator[Span]:
    """Open a span without ever propagating an error.

    A ``None`` port is a valid configuration (tracing disabled). Any
    exception from the adapter's ``span`` constructor is logged at
    DEBUG and degrades to the no-op span — the analysis pipeline must
    keep running.

    Args:
        port: The wired tracer, or ``None`` to disable.
        name: Dotted span name (``spectra.stage.analyze``).
        attributes: Optional initial attribute set.

    Yields:
        A :class:`Span` — either the adapter's real span or the no-op
        fallback. Either way, ``set_attribute`` / ``add_event`` /
        ``record_exception`` are safe to call.
    """
    if port is None:
        yield _NOOP_SPAN
        return
    try:
        cm: AbstractContextManager[Span] = port.span(name, attributes)
    except Exception as exc:
        _LOG.debug("Tracer span constructor failed (name=%s): %s", name, exc)
        yield _NOOP_SPAN
        return
    try:
        with cm as span:
            yield span
    except Exception as exc:
        # Span body completed with an exception — the adapter is responsible
        # for recording it on the span; we never swallow it here. The log
        # captures the span name for forensic correlation.
        _LOG.debug("Span body raised (name=%s): %s", name, exc)
        raise


__all__ = [
    "NoopTracerAdapter",
    "safe_span",
]
