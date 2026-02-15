"""Agent orchestration — parallel execution with failure state machine.

All specialists execute in parallel via ``asyncio.gather`` with a configurable
semaphore. The semaphore bounds concurrency to prevent API rate-limit bursts.

This module is the concurrency core of Spectra's analysis pipeline (Layer 2).
It handles the parallel execution of 6 specialist agents and the failure
state machine that determines pipeline health.

Concurrency model (TRUE PARALLELISM — not sequential):
    - All 6 specialist agents are launched concurrently via ``asyncio.gather``
      with ``return_exceptions=True`` so that individual agent failures do not
      abort the entire batch.
    - A ``asyncio.Semaphore(max_concurrency)`` (default 4) limits the number
      of simultaneous Anthropic API calls, preventing rate-limit bursts when
      analyzing large repositories that generate heavy prompts.
    - Each agent gets an independent ``asyncio.wait_for(timeout=120s)``
      to prevent any single slow agent from blocking the pipeline. This is
      critical for large repos where a single dimension (e.g. security
      scanning a 10K-file monorepo) could otherwise stall indefinitely.

Failure state machine:
    - 0-1 agent failures → ``"merging"`` state: proceed with available results
      and reweight dimension scores to exclude the failed dimension.
    - 2+ agent failures → ``"degraded"`` state: produce a partial report with
      a degraded quality warning. The pipeline does NOT abort entirely — users
      still get actionable findings from the agents that succeeded.

Performance characteristics:
    - **Parallel I/O**: All 6 agents share the event loop; while one agent
      awaits an API response, others proceed — zero idle CPU time.
    - **Semaphore throttling**: Prevents overwhelming the Anthropic API with
      6 concurrent requests, which could trigger 429 rate limits on large repos.
    - **Bounded latency**: Per-agent ``asyncio.wait_for(timeout=120s)`` ensures
      the pipeline completes within a bounded time (target: 90s for typical
      repos, up to 120s per agent for very large codebases).
    - **Fault isolation**: ``return_exceptions=True`` avoids cascading failures:
      if one agent hits an OOM or timeout, the other 5 continue unaffected.
    - **No thread overhead**: Pure async/await — no threads, no GIL contention,
      no context-switching overhead.

Dependencies:
    - Imports only from ``spectra.entities`` (Layer 1).
    - Defines the ``AnalysisAgent`` protocol used by the use-case layer to
      decouple from concrete agent implementations in infrastructure.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from spectra.entities.enums import AgentRole, PipelineState
from spectra.entities.models import AgentOutput


class AnalysisAgent(Protocol):
    """Structural type for any agent that the orchestrator can run.

    Both ``BaseAgent`` subclasses and test doubles satisfy this
    protocol by exposing a ``role`` property and an async ``run``
    method.
    """

    @property
    def role(self) -> AgentRole:
        """The agent's role identifier."""
        ...

    async def run(self, user_prompt: str) -> AgentOutput:
        """Execute the agent and return validated output."""
        ...


async def run_specialists(
    agents: list[AnalysisAgent],
    prompts: dict[AgentRole, str],
    timeout_seconds: float = 120.0,
    max_concurrency: int = 4,
) -> list[AgentOutput | Exception]:
    """Run specialist agents in parallel with individual timeouts.

    A semaphore limits concurrent API calls to avoid rate-limit
    bursts. Each agent gets its own ``asyncio.wait_for`` timeout.

    Args:
        agents: List of specialist agents to execute.
        prompts: Role-keyed prompt strings for each agent.
        timeout_seconds: Per-agent timeout (default 120s).
        max_concurrency: Maximum concurrent LLM calls.

    Returns:
        List of ``AgentOutput`` or ``Exception`` per agent,
        preserving input order.
    """
    # Semaphore limits concurrent API calls to avoid rate-limit bursts
    # on large repos. Default 4 concurrent calls balances throughput
    # vs. Anthropic API rate limits (Tier 2: 4000 RPM).
    # All 6 agents start immediately; the semaphore only gates the LLM call.
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(agent: AnalysisAgent, prompt: str) -> AgentOutput:
        # Each agent acquires the semaphore before calling the LLM,
        # then gets an independent timeout to prevent stalling
        async with semaphore:
            return await asyncio.wait_for(
                agent.run(prompt),
                timeout=timeout_seconds,
            )

    # Build all coroutines upfront — O(n) list comprehension, no I/O yet
    tasks = [_run_one(agent, prompts.get(agent.role, "")) for agent in agents]
    # asyncio.gather launches ALL tasks concurrently on the event loop.
    # return_exceptions=True: individual failures don't cancel siblings,
    # so 5 agents can succeed even if 1 times out or errors.
    return await asyncio.gather(*tasks, return_exceptions=True)


def evaluate_results(
    results: list[AgentOutput | Exception],
    roles: list[AgentRole],
) -> tuple[list[AgentOutput], list[AgentRole], PipelineState]:
    """Apply the failure state machine to agent results.

    Args:
        results: Outputs or exceptions from ``run_specialists``.
        roles: Ordered role list matching the results.

    Returns:
        A 3-tuple of (successes, failed_roles, next_state):
        - 0-1 failures → ``"merging"`` (reweight later)
        - 2+ failures → ``"degraded"`` (partial report)
    """
    successes: list[AgentOutput] = []
    failed_roles: list[AgentRole] = []

    # O(n) single-pass classification — no re-iteration needed
    for result, role in zip(results, roles, strict=True):
        if isinstance(result, Exception):
            failed_roles.append(role)
        else:
            successes.append(result)

    if len(failed_roles) >= 2:
        return successes, failed_roles, "degraded"
    return successes, failed_roles, "merging"
