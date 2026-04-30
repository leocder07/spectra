"""Tests for the composition root tracer wiring (#30 + #33, ADR-023 Part E)."""

from __future__ import annotations

import inspect
import logging

import pytest

from spectra.infrastructure.main import _build_tracer
from spectra.infrastructure.observability import OtelTracerAdapter
from spectra.use_cases.tracing import safe_span


@pytest.fixture(autouse=True)
def _silence_otel_exporter_noise() -> None:
    """Silence the OTel exporter logger during tracer-wiring tests.

    The BatchSpanProcessor periodically flushes to the configured
    OTLP endpoint. In CI / dev there is no collector listening on
    localhost:4318, so the SDK logs ConnectionRefused at the WARNING
    level on shutdown — pure noise for these unit tests, which only
    care that the adapter constructs and threads attributes correctly.
    """
    for name in (
        "opentelemetry",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.sdk.trace.export",
        "urllib3",
        "urllib3.connectionpool",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def _shutdown(adapter: OtelTracerAdapter) -> None:
    """Force the BatchSpanProcessor to drop pending exports.

    Called explicitly so the daemon-thread flush doesn't fire after the
    test finishes (which would log ConnectionError and pollute the
    pytest output even though no test failed).
    """
    provider = adapter._provider
    provider.shutdown()


class TestBuildTracer:
    def test_returns_none_when_endpoint_missing(self) -> None:
        assert _build_tracer(None, "default") is None

    def test_returns_none_when_endpoint_empty(self) -> None:
        assert _build_tracer("", "default") is None

    def test_returns_otel_adapter_for_valid_endpoint(self) -> None:
        adapter = _build_tracer("http://localhost:4318/v1/traces", "default")
        assert isinstance(adapter, OtelTracerAdapter)
        _shutdown(adapter)

    def test_team_attribute_is_passed_into_resource(self) -> None:
        adapter = _build_tracer("http://localhost:4318/v1/traces", "payments")
        assert isinstance(adapter, OtelTracerAdapter)
        # The resource is held on the underlying provider — exposed via the
        # internal _provider attribute of the base adapter.
        provider = adapter._provider
        resource_attrs = dict(provider.resource.attributes)
        assert resource_attrs["spectra.team"] == "payments"
        _shutdown(adapter)

    def test_signature_keeps_two_required_arguments(self) -> None:
        sig = inspect.signature(_build_tracer)
        assert list(sig.parameters) == ["endpoint", "team"]


class TestSafeSpanWithBuiltTracer:
    """Smoke test: built tracer + safe_span survives a complete span lifecycle."""

    def test_safe_span_with_otel_adapter_runs_clean(self) -> None:
        adapter = _build_tracer("http://localhost:4318/v1/traces", "smoke")
        assert adapter is not None
        with safe_span(adapter, "spectra.smoke.test", {"agent.role": "smoke"}) as span:
            span.set_attribute("cost.usd", 0.0)
            span.add_event("smoke.event")
        _shutdown(adapter)

    def test_safe_span_with_none_tracer_is_noop(self) -> None:
        with safe_span(None, "x") as span:
            span.set_attribute("k", "v")
