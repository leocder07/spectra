"""Tests for rate-coordinator wiring in the orchestrator (#22, ADR-013).

The rate coordinator gates every Anthropic call: ``acquire(1)`` is
awaited before each ``agent.run`` so 50 CI runners against a shared
Redis honour one fleet-wide RPM ceiling. The orchestrator integration
verified here is the single seam that turns the Layer-2 Port into a
real per-call await.

Three runner functions are exercised:
    - ``run_specialists`` — the Phase 1 parallel path
    - ``run_specialists_batched`` — the Phase 3 per-batch path
    - ``run_specialists_with_budget`` — the SPEC-014 sequential path
All three honour the same ``rate_coordinator`` keyword argument; the
tests below enforce the contract.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from spectra.entities.models import AgentOutput, BatchPrompt
from spectra.infrastructure.inmemory_rate_adapter import InMemoryRateAdapter
from spectra.use_cases.orchestrate_agents import (
    run_specialists,
    run_specialists_batched,
    run_specialists_with_budget,
)


def _make_agent(role: str) -> AsyncMock:
    """Create a mock AnalysisAgent with the given role."""
    agent = AsyncMock()
    agent.role = role
    agent.run.return_value = AgentOutput(
        agent_role=role,
        findings=(),
        tokens_used=100,
        duration_seconds=1.0,
        raw_response="{}",
    )
    return agent


class _CountingCoordinator:
    """RateCoordinatorPort spy that counts ``acquire`` invocations."""

    def __init__(self) -> None:
        self.acquired: list[int] = []

    async def acquire(self, n_tokens: int = 1) -> None:
        self.acquired.append(n_tokens)


# ── run_specialists ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_specialists_acquires_one_token_per_agent() -> None:
    """6 specialists → 6 ``acquire(1)`` calls before LLM invocations."""
    agents = [_make_agent(r) for r in ("architecture", "security", "quality")]
    prompts = {a.role: "x" for a in agents}
    coord = _CountingCoordinator()
    await run_specialists(agents, prompts, rate_coordinator=coord)
    assert coord.acquired == [1, 1, 1]


@pytest.mark.asyncio
async def test_run_specialists_no_coordinator_skips_acquire() -> None:
    """Backward compat: ``rate_coordinator=None`` is the no-op default."""
    agents = [_make_agent("architecture"), _make_agent("security")]
    prompts = {a.role: "x" for a in agents}
    results = await run_specialists(agents, prompts)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_run_specialists_acquire_serialises_workers() -> None:
    """A 1-RPM bucket forces the 6 specialists to land at 1-RPM cadence.

    With a 60-RPM coordinator (1 RPS) and ``capacity=1``, only one agent
    can complete per second. The test asserts the total wall-clock for
    3 agents lands in the [1.7s, 3.5s] band — two refill ticks past the
    initial token consumed by the bucket-full state.
    """
    coord = InMemoryRateAdapter(rate_per_minute=60, capacity=1)
    agents = [_make_agent(r) for r in ("architecture", "security", "quality")]
    prompts = {a.role: "x" for a in agents}
    start = asyncio.get_event_loop().time()
    await run_specialists(agents, prompts, rate_coordinator=coord)
    elapsed = asyncio.get_event_loop().time() - start
    # 3 acquires; first is immediate, second + third wait one tick each.
    assert 1.7 <= elapsed <= 3.5, f"expected ~2s (3 ticks), got {elapsed:.2f}s"


# ── run_specialists_batched ───────────────────────────────────


def _bp(batch_id: str) -> BatchPrompt:
    return BatchPrompt(
        batch_id=batch_id,
        file_paths=(f"src/{batch_id}.py",),
        file_hashes=(f"hash-{batch_id}",),
        prompt_text="p",
    )


@pytest.mark.asyncio
async def test_run_specialists_batched_acquires_one_per_batch() -> None:
    """Each (agent, batch) pair triggers one ``acquire(1)`` call."""
    agents = [_make_agent("architecture"), _make_agent("security")]
    fresh = {
        "architecture": [_bp("b1"), _bp("b2")],
        "security": [_bp("b3")],
    }
    coord = _CountingCoordinator()
    await run_specialists_batched(agents, fresh, rate_coordinator=coord)
    # 3 batches across 2 agents → 3 acquires.
    assert coord.acquired == [1, 1, 1]


@pytest.mark.asyncio
async def test_run_specialists_batched_no_coordinator_unchanged() -> None:
    """Default ``rate_coordinator=None`` preserves Phase 3 behaviour."""
    agents = [_make_agent("architecture")]
    fresh = {"architecture": [_bp("b1")]}
    results = await run_specialists_batched(agents, fresh)
    assert "architecture" in results


# ── run_specialists_with_budget ──────────────────────────────


class _StubTracker:
    """Minimal CostTrackerPort for the gated path."""

    def __init__(self) -> None:
        self._total = 0.0

    def record(self, _agent: str, cost_usd: float) -> None:
        self._total += cost_usd

    def total(self) -> float:
        return self._total

    def would_exceed(self, additional: float, max_usd: float) -> bool:
        return self._total + additional > max_usd

    def last_hour_total(self) -> float:
        return self._total


@pytest.mark.asyncio
async def test_run_specialists_with_budget_acquires_per_agent() -> None:
    """Sequential budget-gated path also threads through the rate coordinator."""
    agents = [_make_agent(r) for r in ("architecture", "security")]
    prompts = {a.role: "x" for a in agents}
    coord = _CountingCoordinator()
    await run_specialists_with_budget(
        agents,
        prompts,
        tracker=_StubTracker(),
        max_cost_usd=10.0,
        estimate_per_agent=0.001,
        rate_coordinator=coord,
    )
    assert coord.acquired == [1, 1]


@pytest.mark.asyncio
async def test_run_specialists_with_budget_no_coordinator_unchanged() -> None:
    """Backward compat for the budget-gated path."""
    agents = [_make_agent("architecture")]
    prompts = {"architecture": "x"}
    results = await run_specialists_with_budget(
        agents,
        prompts,
        tracker=_StubTracker(),
        max_cost_usd=10.0,
        estimate_per_agent=0.001,
    )
    assert len(results) == 1
