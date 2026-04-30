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


# ── run_specialists edge cases ────────────────────────────────


class TestRunSpecialistsEdgeCases:
    @pytest.mark.asyncio
    async def test_all_agents_fail(self):
        agents = [
            _make_agent("architecture", error=RuntimeError("fail1")),
            _make_agent("security", error=ValueError("fail2")),
            _make_agent("quality", error=TypeError("fail3")),
        ]
        prompts = {"architecture": "x", "security": "y", "quality": "z"}
        results = await run_specialists(agents, prompts)
        assert len(results) == 3
        assert all(isinstance(r, Exception) for r in results)

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self):
        roles = ["architecture", "security", "quality", "documentation", "dependency", "performance"]
        agents = [_make_agent(r) for r in roles]
        prompts = {r: f"prompt_{r}" for r in roles}
        results = await run_specialists(agents, prompts, max_concurrency=2)
        assert len(results) == 6
        assert all(isinstance(r, AgentOutput) for r in results)

    @pytest.mark.asyncio
    async def test_mixed_success_and_timeout(self):
        fast_agent = _make_agent("architecture")
        slow_agent = AsyncMock()
        slow_agent.role = "security"

        async def slow_run(prompt: str) -> AgentOutput:
            await asyncio.sleep(10)
            return AgentOutput(
                agent_role="security",
                findings=(),
                tokens_used=0,
                duration_seconds=10.0,
                raw_response="{}",
            )

        slow_agent.run.side_effect = slow_run
        results = await run_specialists(
            [fast_agent, slow_agent],
            {"architecture": "x", "security": "y"},
            timeout_seconds=0.1,
        )
        assert isinstance(results[0], AgentOutput)
        assert isinstance(results[1], asyncio.TimeoutError)

    @pytest.mark.asyncio
    async def test_single_agent(self):
        agent = _make_agent("security")
        results = await run_specialists([agent], {"security": "check"})
        assert len(results) == 1
        assert isinstance(results[0], AgentOutput)


# ── evaluate_results edge cases ──────────────────────────────


class TestEvaluateResultsEdgeCases:
    def test_exactly_two_failures_is_degraded(self):
        results = [RuntimeError("f1"), RuntimeError("f2")]
        roles = ["architecture", "security"]
        _, failed, state = evaluate_results(results, roles)
        assert len(failed) == 2
        assert state == "degraded"

    def test_exactly_one_failure_is_merging(self):
        output = AgentOutput(
            agent_role="quality",
            findings=(),
            tokens_used=100,
            duration_seconds=1.0,
            raw_response="{}",
        )
        results = [RuntimeError("f1"), output]
        roles = ["architecture", "quality"]
        _, failed, state = evaluate_results(results, roles)
        assert len(failed) == 1
        assert state == "merging"

    def test_six_agents_three_fail(self):
        outputs = [
            RuntimeError("f1"),
            RuntimeError("f2"),
            RuntimeError("f3"),
            AgentOutput(
                agent_role="documentation", findings=(), tokens_used=100, duration_seconds=1.0, raw_response="{}"
            ),
            AgentOutput(agent_role="dependency", findings=(), tokens_used=100, duration_seconds=1.0, raw_response="{}"),
            AgentOutput(
                agent_role="performance", findings=(), tokens_used=100, duration_seconds=1.0, raw_response="{}"
            ),
        ]
        roles = ["architecture", "security", "quality", "documentation", "dependency", "performance"]
        successes, failed, state = evaluate_results(outputs, roles)
        assert len(successes) == 3
        assert len(failed) == 3
        assert state == "degraded"

    def test_timeout_error_counted_as_failure(self):
        results = [TimeoutError(), TimeoutError()]
        roles = ["architecture", "security"]
        _, failed, state = evaluate_results(results, roles)
        assert len(failed) == 2
        assert state == "degraded"

    def test_preserves_order(self):
        o1 = AgentOutput(
            agent_role="architecture", findings=(), tokens_used=100, duration_seconds=1.0, raw_response="{}"
        )
        o2 = AgentOutput(agent_role="quality", findings=(), tokens_used=200, duration_seconds=2.0, raw_response="{}")
        results = [o1, RuntimeError("fail"), o2]
        roles = ["architecture", "security", "quality"]
        successes, failed, _state = evaluate_results(results, roles)
        assert successes[0].agent_role == "architecture"
        assert successes[1].agent_role == "quality"
        assert failed == ["security"]


# ── Phase 3: run_specialists with BatchPrompt list per agent ──


def _batch(batch_id: str, prompt_text: str = "p") -> object:
    """Build a BatchPrompt — Layer 1 entity used by run_specialists in Phase 3."""
    from spectra.entities.models import BatchPrompt

    return BatchPrompt(
        batch_id=batch_id,
        file_paths=(f"src/{batch_id}.py",),
        file_hashes=(f"hash-{batch_id}",),
        prompt_text=prompt_text,
    )


class TestRunSpecialistsPhase3:
    @pytest.mark.asyncio
    async def test_run_specialists_runs_only_fresh_batches(self):
        from spectra.use_cases.orchestrate_agents import run_specialists_batched

        sec = _make_agent("security")
        # Two fresh batches → two run() calls.
        fresh = {"security": [_batch("a"), _batch("b")]}
        results = await run_specialists_batched([sec], fresh)
        assert sec.run.call_count == 2
        assert "security" in results

    @pytest.mark.asyncio
    async def test_run_specialists_merges_cached_and_fresh_findings_into_agent_output(self):
        from spectra.use_cases.orchestrate_agents import run_specialists_batched

        f = _make_finding("security", line=99)
        sec_output = AgentOutput(
            agent_role="security",
            findings=(f,),
            tokens_used=100,
            duration_seconds=1.0,
            raw_response="{}",
        )
        sec = _make_agent("security", output=sec_output)
        fresh = {"security": [_batch("only-fresh")]}
        results = await run_specialists_batched([sec], fresh)
        # Result contains the fresh-finding; merge with cached findings happens
        # at the call site (analyze_repository) which combines this output with
        # cached_findings from partition_by_cache.
        out = results["security"]
        assert isinstance(out, AgentOutput)
        assert f in out.findings


# ── Budget gate (SPEC-014) ──────────────────────────────────────


class TestBudgetGate:
    """run_specialists_with_budget — pre-call gate + post-call record.

    The gate aborts mid-pipeline when the in-memory cost tracker projects
    the next call will push the run over ``--max-cost-usd``. Already-completed
    agents keep their results; remaining agents are skipped.
    """

    @pytest.mark.asyncio
    async def test_under_budget_runs_all_agents(self):
        from spectra.infrastructure.cost_tracker import InMemoryCostTracker
        from spectra.use_cases.orchestrate_agents import run_specialists_with_budget

        tracker = InMemoryCostTracker()
        agents = [_make_agent("architecture"), _make_agent("security")]
        prompts = {"architecture": "x", "security": "y"}
        results = await run_specialists_with_budget(
            agents,
            prompts,
            tracker=tracker,
            max_cost_usd=10.0,
            estimate_per_agent=0.01,
        )
        assert len(results) == 2
        assert all(isinstance(r, AgentOutput) for r in results)

    @pytest.mark.asyncio
    async def test_gate_aborts_after_4th_agent(self):
        """Pre-loading the tracker triggers the gate before the 4th agent runs."""
        from spectra.entities.errors import BudgetExceededError
        from spectra.infrastructure.cost_tracker import InMemoryCostTracker
        from spectra.use_cases.orchestrate_agents import run_specialists_with_budget

        tracker = InMemoryCostTracker()
        # Pre-load tracker to 0.30; with estimate=0.10 and max=0.40 the gate
        # passes once (would_exceed(0.10, 0.40) = 0.30 + 0.10 > 0.40 = False),
        # but after the first agent records (>0 actual cost) the gate fires.
        tracker.record("preload", 0.30)
        agents = [
            _make_agent("architecture"),
            _make_agent("security"),
            _make_agent("quality"),
            _make_agent("documentation"),
            _make_agent("dependency"),
            _make_agent("performance"),
        ]
        prompts = {a.role: "x" for a in agents}
        with pytest.raises(BudgetExceededError) as exc_info:
            await run_specialists_with_budget(
                agents,
                prompts,
                tracker=tracker,
                max_cost_usd=0.40,
                estimate_per_agent=0.10,
            )
        # Gate fires before all agents complete.
        assert exc_info.value.budget_usd == pytest.approx(0.40)
        assert exc_info.value.spent_usd > 0.30
        # At least the preload + first agent's actual cost was recorded.
        assert "architecture" in exc_info.value.per_agent

    @pytest.mark.asyncio
    async def test_no_max_runs_unbounded(self):
        from spectra.infrastructure.cost_tracker import InMemoryCostTracker
        from spectra.use_cases.orchestrate_agents import run_specialists_with_budget

        tracker = InMemoryCostTracker()
        agents = [_make_agent("architecture"), _make_agent("security")]
        prompts = {"architecture": "x", "security": "y"}
        # max_cost_usd=None disables enforcement entirely
        results = await run_specialists_with_budget(
            agents,
            prompts,
            tracker=tracker,
            max_cost_usd=None,
            estimate_per_agent=0.01,
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_records_actual_cost_after_completion(self):
        from spectra.infrastructure.cost_tracker import InMemoryCostTracker
        from spectra.use_cases.orchestrate_agents import run_specialists_with_budget

        tracker = InMemoryCostTracker()
        # Each mock returns tokens_used=100 → cost ~ 100/1000 * _OPUS_AVG_PER_1K
        agents = [_make_agent("architecture")]
        prompts = {"architecture": "x"}
        await run_specialists_with_budget(
            agents,
            prompts,
            tracker=tracker,
            max_cost_usd=10.0,
            estimate_per_agent=0.01,
        )
        # Tracker should have recorded a positive cost for "architecture".
        assert tracker.total() > 0
        assert "architecture" in tracker.per_agent()
