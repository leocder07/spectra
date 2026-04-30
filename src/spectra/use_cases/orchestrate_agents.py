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
from dataclasses import dataclass
from typing import Protocol

from spectra.entities.enums import AgentRole, PipelineState
from spectra.entities.errors import BudgetExceededError
from spectra.entities.models import AgentOutput, BatchPrompt, estimate_cost
from spectra.use_cases.interfaces import CostTrackerPort


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
    # so the remaining specialists can complete even if one times out
    # or errors. SPEC-007 fires only if 2+ specialists fail (see merge stage).
    return await asyncio.gather(*tasks, return_exceptions=True)


@dataclass(frozen=True)
class _BatchExecConfig:
    """Bundled config for batched specialist execution.

    Bundling keeps ``run_specialists_batched`` and helpers within the
    ≤3-parameter rule (Fowler: Replace Long Parameter List with Parameter Object).
    """

    semaphore: asyncio.Semaphore
    timeout_seconds: float


async def run_specialists_batched(
    agents: list[AnalysisAgent],
    fresh_batches: dict[AgentRole, list[BatchPrompt]],
    timeout_seconds: float = 120.0,
    max_concurrency: int = 4,
) -> dict[AgentRole, AgentOutput | Exception]:
    """Run only the fresh batches for each specialist, gathered in parallel.

    Phase 3 entry point. For each (agent, batch) pair the agent's
    ``run`` is invoked with the batch's prompt; results are merged
    into a single ``AgentOutput`` per agent so the rest of the
    pipeline (merge, scoring, critique) is unchanged.
    """
    config = _BatchExecConfig(asyncio.Semaphore(max_concurrency), timeout_seconds)
    tasks = _schedule_batch_tasks(agents, fresh_batches, config)
    flat = await asyncio.gather(*tasks, return_exceptions=True)
    return _collapse_batch_results(agents, fresh_batches, flat)


async def _run_one_batch(
    agent: AnalysisAgent,
    prompt: str,
    config: _BatchExecConfig,
) -> AgentOutput:
    """Acquire the semaphore then run a single batched call with timeout."""
    async with config.semaphore:
        return await asyncio.wait_for(agent.run(prompt), timeout=config.timeout_seconds)


def _schedule_batch_tasks(
    agents: list[AnalysisAgent],
    fresh_batches: dict[AgentRole, list[BatchPrompt]],
    config: _BatchExecConfig,
) -> list[object]:
    """Build the list of asyncio coroutines, one per (agent x batch) pair."""
    tasks: list[object] = []
    for agent in agents:
        tasks.extend(_run_one_batch(agent, b.prompt_text, config) for b in fresh_batches.get(agent.role, []))
    return tasks


def _collapse_batch_results(
    agents: list[AnalysisAgent],
    fresh_batches: dict[AgentRole, list[BatchPrompt]],
    flat: list[object],
) -> dict[AgentRole, AgentOutput | Exception]:
    """Merge per-batch outputs into one AgentOutput per agent role.

    Failures bubble through unchanged so the use case treats them as
    specialist failures and skips the cache write for that agent.
    """
    results: dict[AgentRole, AgentOutput | Exception] = {}
    cursor = 0
    for agent in agents:
        batches = fresh_batches.get(agent.role, [])
        slice_ = flat[cursor : cursor + len(batches)]
        cursor += len(batches)
        results[agent.role] = _merge_agent_batches(agent.role, slice_)
    return results


def _merge_agent_batches(
    role: AgentRole,
    batch_results: list[object],
) -> AgentOutput | Exception:
    """Combine per-batch AgentOutputs into one; first exception wins."""
    first_error = next((r for r in batch_results if isinstance(r, Exception)), None)
    if first_error is not None:
        return first_error
    outputs: list[AgentOutput] = list(batch_results)  # type: ignore[arg-type]
    return AgentOutput(
        agent_role=role,
        findings=tuple(f for o in outputs for f in o.findings),
        tokens_used=sum(o.tokens_used for o in outputs),
        duration_seconds=sum(o.duration_seconds for o in outputs),
        raw_response="{}",
    )


async def run_specialists_with_budget(
    agents: list[AnalysisAgent],
    prompts: dict[AgentRole, str],
    *,
    tracker: CostTrackerPort,
    max_cost_usd: float | None,
    estimate_per_agent: float,
    timeout_seconds: float = 120.0,
) -> list[AgentOutput | Exception]:
    """Run specialists sequentially with a per-agent budget gate (SPEC-012).

    Sequential execution is intentional here: the gate must observe each
    completed agent's actual cost before deciding whether the next call
    fits the cap. ``--max-cost-usd`` is fundamentally serial — racing 6
    agents past the line would defeat the cap by ``cost(6th agent)``.

    Args:
        agents: Specialists to execute, in run order.
        prompts: Role-keyed prompt strings.
        tracker: Cost ledger; ``record`` is called after each success.
        max_cost_usd: Per-run cap. ``None`` disables enforcement.
        estimate_per_agent: USD projection for the next call (input to
            ``would_exceed``). Conservative; the actual cost from
            ``estimate_cost(output)`` is recorded post-call.
        timeout_seconds: Per-agent timeout (default 120s).

    Returns:
        Per-agent ``AgentOutput`` or ``Exception`` in input order.

    Raises:
        BudgetExceededError: SPEC-012 when the gate fires before a call.
    """
    results: list[AgentOutput | Exception] = []
    for agent in agents:
        if _gate_would_block(tracker, max_cost_usd, estimate_per_agent):
            raise BudgetExceededError(
                spent_usd=tracker.total(),
                budget_usd=max_cost_usd or 0.0,
                per_agent=_per_agent_breakdown(tracker),
            )
        prompt = prompts.get(agent.role, "")
        result = await _run_one_with_record(agent, prompt, tracker, timeout_seconds)
        results.append(result)
    return results


def _gate_would_block(
    tracker: CostTrackerPort,
    max_cost_usd: float | None,
    estimate_per_agent: float,
) -> bool:
    """Return True when ``--max-cost-usd`` would be exceeded by the next call."""
    if max_cost_usd is None:
        return False
    return tracker.would_exceed(estimate_per_agent, max_cost_usd)


def _per_agent_breakdown(tracker: CostTrackerPort) -> dict[str, float]:
    """Return the tracker's per-agent dict, or empty if unsupported."""
    per_agent = getattr(tracker, "per_agent", None)
    if per_agent is None:
        return {}
    return per_agent()


async def _run_one_with_record(
    agent: AnalysisAgent,
    prompt: str,
    tracker: CostTrackerPort,
    timeout_seconds: float,
) -> AgentOutput | Exception:
    """Execute a single agent, capture exceptions, record actual cost."""
    try:
        output = await asyncio.wait_for(agent.run(prompt), timeout=timeout_seconds)
    except Exception as exc:
        # Orchestrator captures all to preserve fault isolation; the
        # caller (evaluate_results) classifies failures downstream.
        return exc
    tracker.record(agent.role, estimate_cost((output,)))
    return output


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
