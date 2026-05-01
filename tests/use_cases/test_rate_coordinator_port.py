"""Tests for the ``RateCoordinatorPort`` Protocol surface (#22, ADR-013).

The Port itself is a structural type — there is nothing to execute. The
tests here lock in the *contract*: the Protocol is importable, has the
expected method signature, and anything that implements ``acquire`` (a
single async coroutine accepting ``n_tokens: int``) satisfies it via
duck typing. Adapters live in Layer 4 and have their own dedicated test
modules.

No infrastructure imports — the use-case layer never reaches into
``spectra.infrastructure``. A test that does so would itself be a
dependency-rule violation.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import get_type_hints

import pytest

from spectra.use_cases.interfaces import RateCoordinatorPort

# ── Protocol shape ────────────────────────────────────────────


def test_protocol_is_importable() -> None:
    """``RateCoordinatorPort`` is exposed off the use-case interfaces module."""
    assert RateCoordinatorPort is not None


def test_protocol_declares_acquire() -> None:
    """The Port declares an ``acquire`` method — the only public surface."""
    assert hasattr(RateCoordinatorPort, "acquire")


def test_acquire_signature_takes_n_tokens_int_default_one() -> None:
    """``acquire(n_tokens: int = 1)`` is the contract; defaults to one token."""
    sig = inspect.signature(RateCoordinatorPort.acquire)
    params = list(sig.parameters.values())
    # self is the first parameter on a Protocol method
    assert [p.name for p in params] == ["self", "n_tokens"]
    n_tokens = params[1]
    assert n_tokens.default == 1
    hints = get_type_hints(RateCoordinatorPort.acquire)
    assert hints.get("n_tokens") is int
    assert hints.get("return") is type(None)


# ── Structural-type satisfaction ──────────────────────────────


class _StubCoordinator:
    """Minimal duck-type implementation used in pipeline integration tests."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def acquire(self, n_tokens: int = 1) -> None:
        self.calls.append(n_tokens)


@pytest.mark.asyncio
async def test_stub_satisfies_protocol_at_runtime() -> None:
    """Any object exposing ``async def acquire`` satisfies the Port."""
    coord: RateCoordinatorPort = _StubCoordinator()  # structural assignment
    await coord.acquire(1)
    await coord.acquire(3)
    assert coord.calls == [1, 3]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_acquire_returns_none() -> None:
    """The Port returns ``None`` — leases live inside adapters, not in ctx."""
    coord = _StubCoordinator()
    result = await coord.acquire(1)
    assert result is None


@pytest.mark.asyncio
async def test_acquire_is_a_coroutine_function() -> None:
    """``acquire`` MUST be awaitable — sync implementations would block the loop."""
    coord = _StubCoordinator()
    coro = coord.acquire(1)
    assert asyncio.iscoroutine(coro)
    await coro
