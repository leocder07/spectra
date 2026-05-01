"""Protocol-shape tests for ``RemoteCachePort`` (ADR-021, capability #21).

The port lives in Layer 2; these tests assert the surface area is async,
covers the same composite-key contract as ``CachePort``, and holds the
minimum methods every distributed adapter has to honour
(get/put findings + full report + health). The Protocol itself is
structurally typed — a stub class with the right method shapes
satisfies it; a mismatch surfaces at type-check time, not run time.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import get_type_hints

import pytest

from spectra.entities.models import AnalysisReport, BatchCacheKey, Finding, RepoCacheKey
from spectra.use_cases.interfaces import RemoteCachePort


class _StubRemoteCache:
    """Minimal in-memory stand-in used to assert Protocol satisfaction."""

    def __init__(self) -> None:
        self._batches: dict[BatchCacheKey, tuple[Finding, ...]] = {}
        self._reports: dict[RepoCacheKey, AnalysisReport] = {}
        self._healthy = True

    async def get_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        await asyncio.sleep(0)
        return self._batches.get(key)

    async def put_findings(self, key: BatchCacheKey, findings: tuple[Finding, ...]) -> None:
        await asyncio.sleep(0)
        self._batches[key] = findings

    async def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        await asyncio.sleep(0)
        return self._reports.get(key)

    async def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        await asyncio.sleep(0)
        self._reports[key] = report

    async def health(self) -> bool:
        await asyncio.sleep(0)
        return self._healthy


def test_remote_cache_port_is_a_protocol() -> None:
    """``RemoteCachePort`` must be a Protocol so adapters opt-in structurally."""
    assert hasattr(RemoteCachePort, "_is_protocol"), "RemoteCachePort must inherit from typing.Protocol"


def test_stub_satisfies_remote_cache_port() -> None:
    """The minimal stub must satisfy the Protocol via duck-typing."""
    stub: RemoteCachePort = _StubRemoteCache()
    assert isinstance(stub, _StubRemoteCache)


@pytest.mark.parametrize(
    "method",
    ["get_findings", "put_findings", "get_full_report", "put_full_report", "health"],
)
def test_protocol_method_is_async(method: str) -> None:
    """Every method must be a coroutine — ADR-021 §1: async-mandatory."""
    impl = getattr(RemoteCachePort, method)
    assert inspect.iscoroutinefunction(impl), f"{method} must be async"


def test_get_findings_signature() -> None:
    """``get_findings(key: BatchCacheKey) -> tuple[Finding, ...] | None``."""
    hints = get_type_hints(RemoteCachePort.get_findings)
    assert hints["key"] is BatchCacheKey
    # The return is tuple[Finding, ...] | None (Optional). Compare via str
    # so we sidestep typing-internal Union variants across Python minor
    # versions.
    assert "Finding" in str(hints["return"])
    assert "None" in str(hints["return"])


def test_put_findings_signature() -> None:
    """``put_findings(key: BatchCacheKey, findings: tuple[Finding, ...]) -> None``."""
    hints = get_type_hints(RemoteCachePort.put_findings)
    assert hints["key"] is BatchCacheKey
    assert "Finding" in str(hints["findings"])
    assert hints["return"] is type(None)


def test_full_report_signatures() -> None:
    """Full-report get/put accept a ``RepoCacheKey`` and return Optional report."""
    get_hints = get_type_hints(RemoteCachePort.get_full_report)
    put_hints = get_type_hints(RemoteCachePort.put_full_report)
    assert get_hints["key"] is RepoCacheKey
    assert put_hints["key"] is RepoCacheKey
    assert "AnalysisReport" in str(get_hints["return"])
    assert "None" in str(get_hints["return"])
    assert put_hints["report"] is AnalysisReport


def test_health_returns_bool() -> None:
    """``health() -> bool`` — adapters report liveness for circuit-breaker logic."""
    hints = get_type_hints(RemoteCachePort.health)
    assert hints["return"] is bool


@pytest.mark.asyncio
async def test_stub_round_trip_findings() -> None:
    """The stub adapter round-trips findings through the Protocol contract."""
    cache = _StubRemoteCache()
    key = BatchCacheKey(
        batch_id="b1",
        dimension="security",
        model_version="claude-opus-4-7",
        prompt_version="p1",
        schema_version="v1",
        spectra_version="0.7.0",
    )
    assert await cache.get_findings(key) is None
    await cache.put_findings(key, ())
    assert await cache.get_findings(key) == ()


@pytest.mark.asyncio
async def test_stub_health_reports_state() -> None:
    """``health`` must reflect the current liveness state for breaker logic."""
    cache = _StubRemoteCache()
    assert await cache.health() is True
    cache._healthy = False
    assert await cache.health() is False
