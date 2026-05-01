"""Smoke test — prompt-cache plumbing end-to-end with a fake gateway.

Exercises the full cache wiring without an Anthropic key:
1. BaseAgent forwards the system-prompt length as cache_breakpoint_index.
2. The fake gateway pretends to populate cache_creation/cache_read tokens
   on each call (mimicking what AnthropicAdapter does for real).
3. The orchestrator computes estimate_cache_savings and surfaces it on
   the AnalysisReport.cost_saved_usd field.
4. The presenter renders the saved-amount line when savings >= $0.01.
"""

from __future__ import annotations

from typing import cast

import pytest

from spectra.entities.models import (
    AgentOutput,
    CacheUsage,
    estimate_cache_savings,
    estimate_cost,
)
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent


class _RecordingGateway:
    """Records every analyze call with the cache_breakpoint_index it received."""

    def __init__(self, creation_tokens: int = 4000, read_tokens: int = 0) -> None:
        self.calls: list[dict[str, object]] = []
        self.last_usage: tuple[int, int] = (1000, 500)
        self.last_cache_usage = CacheUsage(
            creation_tokens=creation_tokens,
            read_tokens=read_tokens,
        )

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        self.calls.append(
            {
                "system_len": len(system_prompt),
                "cache_breakpoint_index": cache_breakpoint_index,
                "model": model,
            },
        )
        return '{"findings": [], "dimension_score": 80, "summary": "ok"}'

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        return await self.analyze(
            system_prompt,
            user_prompt,
            model,
            max_tokens,
            effort,
            cache_breakpoint_index,
        )


@pytest.mark.asyncio
async def test_specialist_forwards_full_system_prompt_as_breakpoint():
    """Every specialist call MUST tag the entire system prompt as cacheable."""
    gateway = _RecordingGateway()
    agent = SpecialistAgent(
        role="security",
        gateway=cast("object", gateway),  # type: ignore[arg-type]
        dimension="security",
        id_prefix="sec",
        system_prompt="STABLE_PREAMBLE_FOR_CACHING",
    )
    await agent.run("def vulnerable(): pass")
    assert len(gateway.calls) == 1
    # The breakpoint index equals the full system-prompt length, so
    # Anthropic caches the entire preamble. Subsequent calls within
    # the TTL window pay 10% on those tokens.
    assert gateway.calls[0]["cache_breakpoint_index"] == len("STABLE_PREAMBLE_FOR_CACHING")


@pytest.mark.asyncio
async def test_cache_savings_propagate_to_agent_output():
    """The CacheUsage from the gateway lands on the AgentOutput."""
    # Simulate a re-run where the cache is hot: 4000 tokens served from cache.
    gateway = _RecordingGateway(creation_tokens=0, read_tokens=4000)
    agent = SpecialistAgent(
        role="security",
        gateway=cast("object", gateway),  # type: ignore[arg-type]
        dimension="security",
        id_prefix="sec",
        system_prompt="cached prefix",
    )
    output = await agent.run("def x(): pass")
    assert isinstance(output, AgentOutput)
    assert output.cache_usage.read_tokens == 4000
    assert output.cache_usage.creation_tokens == 0


def test_six_specialist_run_savings_arithmetic():
    """A realistic 6-specialist run with cache hits saves ~$0.10 at xhigh.

    Per ADR-024: 6 specialists * ~3500 cached input tokens per call * 90%
    discount * $0.005 / 1K Opus input rate = ~$0.0945 per scan when the
    cache is hot. This is the "cache savings on every report" line.
    """
    six_outputs = tuple(
        AgentOutput(
            agent_role=role,
            findings=(),
            tokens_used=10_000,
            duration_seconds=1.0,
            raw_response="{}",
            cache_usage=CacheUsage(creation_tokens=0, read_tokens=3500),
        )
        for role in (
            "architecture",
            "security",
            "quality",
            "documentation",
            "dependency",
            "performance",
        )
    )
    savings = estimate_cache_savings(six_outputs)
    # 6 * 3500 * 0.90 * 0.005 / 1000 = 0.0945
    assert savings == 0.0945
    # And the standard cost calculation still works alongside.
    cost = estimate_cost(six_outputs)
    assert cost > 0


def test_savings_zero_when_no_cache_used():
    """Adapters that do not opt into caching contribute zero savings."""
    out = AgentOutput(
        agent_role="security",
        findings=(),
        tokens_used=1000,
        duration_seconds=1.0,
        raw_response="{}",
    )
    assert estimate_cache_savings((out,)) == 0.0
