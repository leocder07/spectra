"""Composition-root tests for ``_build_rate_coordinator`` (#22, ADR-013).

The composition root selects between three outcomes from the CLI flag
pair (``--rate-limit-rpm``, ``--rate-coordinator``):

    1. No rate-limit-rpm    → ``None`` (no coordinator wired).
    2. ``inmemory`` (default) → ``InMemoryRateAdapter``.
    3. ``redis://...``       → ``RedisRateAdapter`` (or in-memory
       fallback on construction failure — SPEC-010 latent at acquire).

These tests are surgical so that an accidental change to the selection
rules surfaces immediately. The integration with the use-case layer is
covered by ``tests/use_cases/test_orchestrate_agents_rate_coord.py``;
the contract verified here is purely the wiring shape.
"""

from __future__ import annotations

import pytest

from spectra.infrastructure.inmemory_rate_adapter import InMemoryRateAdapter
from spectra.infrastructure.main import _build_rate_coordinator
from spectra.infrastructure.redis_rate_adapter import RedisRateAdapter


def test_no_rate_limit_returns_none() -> None:
    """Without ``--rate-limit-rpm`` the coordinator is unwired (fast path)."""
    assert _build_rate_coordinator(None, None) is None
    assert _build_rate_coordinator(None, "redis://localhost:6379/0") is None


def test_inmemory_default_when_rpm_set_without_url() -> None:
    """``--rate-limit-rpm 60`` alone picks the in-process adapter."""
    coord = _build_rate_coordinator(60, None)
    assert isinstance(coord, InMemoryRateAdapter)
    assert coord.rate_per_minute == 60


def test_inmemory_explicit_string() -> None:
    """The literal ``inmemory`` selector resolves to the in-process adapter."""
    coord = _build_rate_coordinator(60, "inmemory")
    assert isinstance(coord, InMemoryRateAdapter)


def test_redis_url_picks_redis_adapter() -> None:
    """A ``redis://...`` URL routes to the Redis-backed coordinator."""
    coord = _build_rate_coordinator(60, "redis://localhost:6379/0")
    assert isinstance(coord, RedisRateAdapter)
    assert coord.rate_per_minute == 60


def test_redis_init_failure_degrades_to_inmemory(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broken Redis URL falls back to in-memory + WARN — never aborts."""

    def _boom(*_a: object, **_k: object) -> None:
        msg = "bad url"
        raise ValueError(msg)

    monkeypatch.setattr(
        "spectra.infrastructure.redis_rate_adapter.RedisRateAdapter.from_url",
        _boom,
    )
    caplog.set_level("WARNING", logger="spectra.rate")
    coord = _build_rate_coordinator(60, "redis://broken")
    assert isinstance(coord, InMemoryRateAdapter)
    assert any("Rate coordinator" in r.getMessage() for r in caplog.records)
