"""Tests for TracerPort protocol surface (Layer 2, ADR-023).

Establishes the contract every adapter (NoopTracerAdapter,
OtelTracerAdapter, InMemoryTracerAdapter) must satisfy. The use case
imports ``TracerPort`` only — never ``opentelemetry.*``.
"""

from __future__ import annotations

from typing import cast

import pytest

from spectra.use_cases.interfaces import Span, TracerPort
from spectra.use_cases.tracing import NoopTracerAdapter, safe_span


class TestNoopTracerAdapter:
    def test_satisfies_tracer_port_protocol(self) -> None:
        port: TracerPort = NoopTracerAdapter()
        assert hasattr(port, "span")

    def test_span_is_context_manager_with_no_op_span(self) -> None:
        tracer = NoopTracerAdapter()
        with tracer.span("stage.ingest") as span:
            assert span is not None
            span.set_attribute("repo_signature", "abc123")
            span.set_attribute("file_count", 42)
            span.add_event("clone.started", {"target_dir": "workspace-1"})

    def test_span_accepts_initial_attributes(self) -> None:
        tracer = NoopTracerAdapter()
        with tracer.span("agent.security", {"agent.role": "security"}) as span:
            # No-op should not raise on any well-formed call.
            span.set_attribute("cost.usd", 0.42)
            span.set_attribute("tokens.input", 1000)
            span.set_attribute("tokens.output", 200)

    def test_record_exception_does_not_propagate(self) -> None:
        tracer = NoopTracerAdapter()
        with tracer.span("stage.report") as span:
            span.record_exception(ValueError("boom"))

    def test_nested_spans_are_supported(self) -> None:
        tracer = NoopTracerAdapter()
        with tracer.span("root") as root, tracer.span("child") as child:
            root.set_attribute("k", "v")
            child.set_attribute("k", "v")

    def test_set_attribute_accepts_all_scalar_types(self) -> None:
        tracer = NoopTracerAdapter()
        with tracer.span("stage.merge") as span:
            span.set_attribute("string", "value")
            span.set_attribute("int", 1)
            span.set_attribute("float", 1.5)
            span.set_attribute("bool", True)


class _RecordingSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, str | int | float | bool] = {}
        self.events: list[tuple[str, dict[str, object] | None]] = []
        self.exceptions: list[BaseException] = []

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, object] | None = None) -> None:
        self.events.append((name, attributes))

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class TestSafeSpan:
    def test_safe_span_swallows_set_attribute_error(self) -> None:
        class _BrokenTracer:
            def span(self, name: str, attributes: dict[str, str | int | float | bool] | None = None) -> object:
                del name, attributes
                msg = "tracer crashed"
                raise RuntimeError(msg)

        port = cast("TracerPort", _BrokenTracer())
        with safe_span(port, "stage.plan") as span:
            # Must not raise — observability contract.
            span.set_attribute("any", "value")
            span.add_event("any")
            span.record_exception(ValueError("x"))

    def test_safe_span_with_none_port_returns_no_op(self) -> None:
        with safe_span(None, "stage.plan") as span:
            assert span is not None
            span.set_attribute("k", "v")

    def test_safe_span_yields_underlying_span_on_success(self) -> None:
        recording = _RecordingSpan("stage.plan")

        class _RecordingTracer:
            def span(
                self,
                name: str,
                attributes: dict[str, str | int | float | bool] | None = None,
            ) -> object:
                from contextlib import contextmanager

                del name, attributes

                @contextmanager
                def _cm() -> object:  # type: ignore[misc]
                    yield recording

                return _cm()

        port = cast("TracerPort", _RecordingTracer())
        with safe_span(port, "stage.plan", {"x": "y"}) as span:
            span.set_attribute("k", "v")
        assert recording.attributes == {"k": "v"}


def test_span_protocol_is_structural() -> None:
    """``Span`` is a structural Protocol — any class with the methods satisfies."""
    span: Span = _RecordingSpan("test")
    span.set_attribute("k", "v")
    assert span.attributes["k"] == "v"


@pytest.mark.parametrize(
    "name",
    [
        "spectra.analyze_repository",
        "spectra.stage.ingest",
        "spectra.stage.plan",
        "spectra.stage.analyze",
        "spectra.stage.merge",
        "spectra.stage.critique",
        "spectra.stage.report",
        "spectra.agent.security",
    ],
)
def test_noop_accepts_canonical_span_names(name: str) -> None:
    tracer = NoopTracerAdapter()
    with tracer.span(name) as span:
        span.set_attribute("any", "ok")
