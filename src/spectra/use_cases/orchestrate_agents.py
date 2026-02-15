"""Agent orchestration — parallel execution with failure state machine.

Provides the ``run_specialists`` coroutine that fans out 6 agents via
``asyncio.gather`` and the ``evaluate_results`` function that applies
the failure state machine (0-1 failures → merging, 2+ → degraded).
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
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(agent: AnalysisAgent, prompt: str) -> AgentOutput:
        async with semaphore:
            return await asyncio.wait_for(
                agent.run(prompt),
                timeout=timeout_seconds,
            )

    tasks = [_run_one(agent, prompts.get(agent.role, "")) for agent in agents]
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

    for result, role in zip(results, roles, strict=False):
        if isinstance(result, Exception):
            failed_roles.append(role)
        else:
            successes.append(result)

    if len(failed_roles) >= 2:
        return successes, failed_roles, "degraded"
    return successes, failed_roles, "merging"
