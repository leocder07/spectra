"""Observability adapters — Layer 4 implementations of ``TracerPort`` (ADR-023).

The use-case layer (``spectra.use_cases.tracing``) defines ``TracerPort``
+ ``Span`` + ``NoopTracerAdapter`` (zero-overhead default). This package
provides the OpenTelemetry-backed adapters that ship spans to an OTLP
collector — and the in-memory adapter used by the trace-shape contract
tests.

Wiring (composition root, ``infrastructure/main.py``):

    --otel-endpoint http://collector:4318/v1/traces  →  OtelTracerAdapter
    (no flag)                                         →  NoopTracerAdapter
    tests                                             →  InMemoryTracerAdapter

ADR-023 §5 — sensitive-attribute boundary: every attribute set on a
real span passes through :func:`drop_sensitive_attributes`. Keys
containing ``key``, ``secret``, ``token``, ``body``, ``content``, or
``code`` are dropped before they leave the process.
"""

from spectra.infrastructure.observability.otel_tracer import (
    InMemoryTracerAdapter,
    OtelTracerAdapter,
    drop_sensitive_attributes,
)

__all__ = [
    "InMemoryTracerAdapter",
    "OtelTracerAdapter",
    "drop_sensitive_attributes",
]
