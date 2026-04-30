"""Tests for OtelTracerAdapter + InMemoryTracerAdapter (Layer 4, ADR-023).

The InMemoryTracerAdapter is the test-time tracer; it satisfies
``TracerPort`` against the OTel SDK's ``InMemorySpanExporter`` so the
trace-shape contract tests live close to the production wiring.

ADR-023 §5 — sensitive-attribute boundary: the OTel adapter MUST drop
attribute keys matching ``*key*``, ``*secret*``, ``*token*``, ``*body*``,
``*content*``, ``*code*`` before they leave the process.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from spectra.infrastructure.observability import (
    InMemoryTracerAdapter,
    OtelTracerAdapter,
    drop_sensitive_attributes,
)
from spectra.use_cases.interfaces import TracerPort


def _spans(adapter: InMemoryTracerAdapter) -> tuple[ReadableSpan, ...]:
    return adapter.exporter.get_finished_spans()


class TestInMemoryTracerAdapter:
    def test_satisfies_tracer_port(self) -> None:
        port: TracerPort = InMemoryTracerAdapter()
        assert hasattr(port, "span")

    def test_records_one_finished_span(self) -> None:
        tracer = InMemoryTracerAdapter()
        with tracer.span("spectra.stage.ingest"):
            pass
        recorded = _spans(tracer)
        assert len(recorded) == 1
        assert recorded[0].name == "spectra.stage.ingest"

    def test_initial_attributes_are_attached(self) -> None:
        tracer = InMemoryTracerAdapter()
        with tracer.span("spectra.stage.plan", {"agent.role": "meta_prompter"}):
            pass
        recorded = _spans(tracer)
        assert recorded[0].attributes is not None
        assert recorded[0].attributes["agent.role"] == "meta_prompter"

    def test_set_attribute_after_open(self) -> None:
        tracer = InMemoryTracerAdapter()
        with tracer.span("spectra.agent.security") as span:
            span.set_attribute("cost.usd", 0.42)
            span.set_attribute("tokens.input", 1000)
            span.set_attribute("tokens.output", 200)
        attrs = _spans(tracer)[0].attributes
        assert attrs is not None
        assert attrs["cost.usd"] == 0.42
        assert attrs["tokens.input"] == 1000
        assert attrs["tokens.output"] == 200

    def test_nested_spans_are_recorded_with_parentage(self) -> None:
        tracer = InMemoryTracerAdapter()
        with tracer.span("root"), tracer.span("child"):
            pass
        recorded = _spans(tracer)
        names = sorted(s.name for s in recorded)
        assert names == ["child", "root"]
        # Identify child + root by name (both spans are present).
        root_span = next(s for s in recorded if s.name == "root")
        child_span = next(s for s in recorded if s.name == "child")
        assert child_span.parent is not None
        assert child_span.parent.span_id == root_span.context.span_id

    def test_record_exception_does_not_swallow(self) -> None:
        tracer = InMemoryTracerAdapter()

        def _raise_inside_span() -> None:
            with tracer.span("stage.x") as span:
                try:
                    msg = "boom"
                    raise ValueError(msg)
                except ValueError as exc:
                    span.record_exception(exc)
                    raise

        with pytest.raises(ValueError, match="boom"):
            _raise_inside_span()
        # Span is still recorded.
        recorded = _spans(tracer)
        assert len(recorded) == 1
        # Events include the standard OTel "exception" entry.
        events = recorded[0].events
        assert any(e.name == "exception" for e in events)

    def test_add_event_attaches_attributes(self) -> None:
        tracer = InMemoryTracerAdapter()
        with tracer.span("stage.ingest") as span:
            span.add_event("clone.started", {"target": "workspace-1"})
        events = _spans(tracer)[0].events
        assert events[0].name == "clone.started"
        assert events[0].attributes is not None
        assert events[0].attributes["target"] == "workspace-1"


class TestDropSensitiveAttributes:
    @pytest.mark.parametrize(
        "key",
        [
            "api_key",
            "x_api_key_y",
            "anthropic_secret",
            "session_token",
            "auth_token",
            "access_token",
            "refresh_token",
            "bearer_credential",
            "request_body",
            "raw_body",
            "file_content",
            "file_contents",
            "raw_content",
            "raw_code",
            "source_code_excerpt",
            "snippet_text",
            "user_password",
            "passwd",
            "private_key",
        ],
    )
    def test_sensitive_keys_are_dropped(self, key: str) -> None:
        attrs = {key: "should-not-leak", "cost.usd": 0.1}
        cleaned = drop_sensitive_attributes(attrs)
        assert key not in cleaned
        assert cleaned["cost.usd"] == 0.1

    @pytest.mark.parametrize(
        "key",
        [
            "agent.role",
            "cost.usd",
            "tokens.input",
            "tokens.output",
            "tokens.cache_read",
            "spectra.team",
            "spectra.repo_signature",
            "agent.model",
            "llm.model",
        ],
    )
    def test_safe_keys_pass_through(self, key: str) -> None:
        attrs: dict[str, str | int | float | bool] = {key: "ok"}
        assert drop_sensitive_attributes(attrs) == attrs

    def test_empty_input_returns_empty_dict(self) -> None:
        assert drop_sensitive_attributes({}) == {}


class TestInMemoryAdapterEnforcesAttributeBoundary:
    def test_initial_attribute_with_secret_key_is_dropped(self) -> None:
        tracer = InMemoryTracerAdapter()
        with tracer.span("agent.security", {"api_key": "leak", "agent.role": "security"}):
            pass
        attrs = _spans(tracer)[0].attributes
        assert attrs is not None
        assert "api_key" not in attrs
        assert attrs["agent.role"] == "security"

    def test_set_attribute_with_secret_key_is_dropped(self) -> None:
        tracer = InMemoryTracerAdapter()
        with tracer.span("agent.security") as span:
            span.set_attribute("session_token", "leak")
            span.set_attribute("cost.usd", 0.42)
        attrs = _spans(tracer)[0].attributes
        assert attrs is not None
        assert "session_token" not in attrs
        assert attrs["cost.usd"] == 0.42


class TestOtelTracerAdapterConstruction:
    def test_constructs_with_endpoint(self) -> None:
        # Should not require a live collector — exporter init is lazy.
        adapter = OtelTracerAdapter(endpoint="http://localhost:4318/v1/traces")
        assert isinstance(adapter, OtelTracerAdapter)

    def test_constructs_with_resource_attributes(self) -> None:
        adapter = OtelTracerAdapter(
            endpoint="http://localhost:4318/v1/traces",
            resource_attributes={"spectra.team": "payments-platform"},
        )
        assert isinstance(adapter, OtelTracerAdapter)

    def test_satisfies_tracer_port(self) -> None:
        port: TracerPort = OtelTracerAdapter(endpoint="http://localhost:4318/v1/traces")
        assert hasattr(port, "span")


class TestInMemoryReusesProcessor:
    """Regression: rebuilding the in-memory adapter must not crash on shutdown."""

    def test_can_construct_multiple_adapters(self) -> None:
        a = InMemoryTracerAdapter()
        b = InMemoryTracerAdapter()
        with a.span("a-span"):
            pass
        with b.span("b-span"):
            pass
        assert len(_spans(a)) == 1
        assert len(_spans(b)) == 1

    def test_simple_processor_can_be_attached(self) -> None:
        # Sanity check that the OTel SDK shape we depend on still exists.
        exporter = InMemorySpanExporter()
        processor = SimpleSpanProcessor(exporter)
        assert processor is not None
