"""Tests for agent orchestration — parallel execution and failure states."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from spectra.entities.models import AgentOutput, FileLocation, Finding
from spectra.use_cases.orchestrate_agents import evaluate_results, run_specialists


def _make_agent(role: str, output: AgentOutput | None = None, error: Exception | None = None) -> AsyncMock:
    """Create a mock AnalysisAgent with the given role."""
    agent = AsyncMock()
    agent.role = role
    if error:
        agent.run.side_effect = error
    elif output:
        agent.run.return_value = output
    else:
        agent.run.return_value = AgentOutput(
            agent_role=role,
            findings=(),
            tokens_used=100,
            duration_seconds=1.0,
            raw_response="{}",
        )
    return agent


def _make_finding(dimension: str, line: int = 10) -> Finding:
    return Finding(
        id=f"F-{dimension}-{line}",
        dimension=dimension,
        severity="medium",
        title="Test",
        description="Test finding",
        location=FileLocation(file_path="src/main.py", line_start=line),
        recommendation="Fix",
        agent_role="architecture",
        confidence=0.8,
    )


# ── run_specialists ─────────────────────────────────────────────


class TestRunSpecialists:
    @pytest.mark.asyncio
    async def test_all_succeed(self):
        agents = [_make_agent("architecture"), _make_agent("security")]
        prompts = {"architecture": "analyze", "security": "check"}
        results = await run_specialists(agents, prompts)
        assert len(results) == 2
        assert all(isinstance(r, AgentOutput) for r in results)

    @pytest.mark.asyncio
    async def test_one_fails(self):
        good = _make_agent("architecture")
        bad = _make_agent("security", error=RuntimeError("API down"))
        results = await run_specialists([good, bad], {"architecture": "x", "security": "y"})
        assert isinstance(results[0], AgentOutput)
        assert isinstance(results[1], RuntimeError)

    @pytest.mark.asyncio
    async def test_timeout(self):
        slow_agent = AsyncMock()
        slow_agent.role = "quality"

        async def slow_run(prompt: str) -> AgentOutput:
            await asyncio.sleep(5)
            return AgentOutput(
                agent_role="quality",
                findings=(),
                tokens_used=0,
                duration_seconds=5.0,
                raw_response="{}",
            )

        slow_agent.run.side_effect = slow_run
        results = await run_specialists(
            [slow_agent],
            {"quality": "x"},
            timeout_seconds=0.1,
        )
        assert len(results) == 1
        assert isinstance(results[0], asyncio.TimeoutError)

    @pytest.mark.asyncio
    async def test_empty_agents(self):
        results = await run_specialists([], {})
        assert results == []

    @pytest.mark.asyncio
    async def test_missing_prompt_uses_empty_string(self):
        agent = _make_agent("architecture")
        results = await run_specialists([agent], {})
        assert len(results) == 1
        agent.run.assert_called_once_with("")


# ── evaluate_results ────────────────────────────────────────────


class TestEvaluateResults:
    def test_all_succeed(self):
        outputs = [
            AgentOutput(
                agent_role="architecture", findings=(), tokens_used=100, duration_seconds=1.0, raw_response="{}"
            ),
            AgentOutput(agent_role="security", findings=(), tokens_used=100, duration_seconds=1.0, raw_response="{}"),
        ]
        roles = ["architecture", "security"]
        successes, failed, state = evaluate_results(outputs, roles)
        assert len(successes) == 2
        assert len(failed) == 0
        assert state == "merging"

    def test_one_failure(self):
        output = AgentOutput(
            agent_role="architecture", findings=(), tokens_used=100, duration_seconds=1.0, raw_response="{}"
        )
        results = [output, RuntimeError("fail")]
        roles = ["architecture", "security"]
        successes, failed, state = evaluate_results(results, roles)
        assert len(successes) == 1
        assert failed == ["security"]
        assert state == "merging"

    def test_two_failures_degraded(self):
        results = [
            RuntimeError("fail1"),
            RuntimeError("fail2"),
            AgentOutput(
                agent_role="quality",
                findings=(),
                tokens_used=100,
                duration_seconds=1.0,
                raw_response="{}",
            ),
        ]
        roles = ["architecture", "security", "quality"]
        successes, failed, state = evaluate_results(results, roles)
        assert len(successes) == 1
        assert len(failed) == 2
        assert state == "degraded"

    def test_all_failures_degraded(self):
        results = [RuntimeError("f1"), RuntimeError("f2"), RuntimeError("f3")]
        roles = ["architecture", "security", "quality"]
        successes, failed, state = evaluate_results(results, roles)
        assert len(successes) == 0
        assert len(failed) == 3
        assert state == "degraded"

    def test_empty_results(self):
        successes, failed, state = evaluate_results([], [])
        assert len(successes) == 0
        assert len(failed) == 0
        assert state == "merging"
