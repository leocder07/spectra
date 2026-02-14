"""Agent orchestration — parallel execution with failure state machine."""

from __future__ import annotations

import asyncio
from typing import Protocol

from spectra.entities.enums import AgentRole, PipelineState
from spectra.entities.models import AgentOutput


class AnalysisAgent(Protocol):
    """Structural type for any agent that the orchestrator can run."""

    @property
    def role(self) -> AgentRole: ...

    async def run(self, user_prompt: str) -> AgentOutput: ...


async def run_specialists(
    agents: list[AnalysisAgent],
    prompts: dict[AgentRole, str],
    timeout_seconds: float = 120.0,
    max_concurrency: int = 4,
) -> list[AgentOutput | Exception]:
    """Run specialist agents in parallel with individual timeouts.

    A semaphore limits concurrent API calls to avoid rate-limit bursts.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(agent: AnalysisAgent, prompt: str) -> AgentOutput:
        async with semaphore:
            return await asyncio.wait_for(
                agent.run(prompt),
                timeout=timeout_seconds,
            )

    tasks = [
        _run_one(agent, prompts.get(agent.role, ""))
        for agent in agents
    ]
    return await asyncio.gather(*tasks, return_exceptions=True)


def evaluate_results(
    results: list[AgentOutput | Exception],
    roles: list[AgentRole],
) -> tuple[list[AgentOutput], list[AgentRole], PipelineState]:
    """Apply failure state machine to agent results.

    Returns (successes, failed_roles, next_state).
    - 0 failures → "merging"
    - 1 failure → "merging" (reweight later)
    - 2+ failures → "degraded"
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
