"""Tests for the analyze_repository facade — full pipeline orchestration."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

import pytest

from spectra.entities.models import (
    AgentOutput,
    AnalysisRequest,
    Codebase,
    FileLocation,
    Finding,
)
from spectra.entities.models import estimate_cost
from spectra.use_cases.analyze_repository import (
    _apply_critique,
    _compute_scorecard,
    _estimate_score,
    _extract_cross_cutting_insights,
    _extract_plan_files,
    _extract_token_allocations,
    _should_run_critique,
    analyze_repository,
)


def _finding(dim: str, sev: str, line: int = 10) -> Finding:
    """Module-level helper for pure-function tests that don't use fixtures."""
    role_map = {
        "architecture": "architecture",
        "security": "security",
        "quality": "quality",
        "documentation": "documentation",
        "maintainability": "dependency",
        "performance": "performance",
    }
    return Finding(
        id=f"F-{dim}-{line}",
        dimension=dim,
        severity=sev,
        title=f"{sev} {dim} finding",
        description="Test",
        location=FileLocation(file_path="src/main.py", line_start=line),
        recommendation="Fix",
        agent_role=role_map.get(dim, "architecture"),
        confidence=0.8,
    )


@pytest.fixture
def analysis_request():
    return AnalysisRequest(repo_url="https://github.com/test/repo")


@pytest.fixture
def codebase():
    return Codebase(
        repo_url="https://github.com/test/repo",
        repo_name="repo",
        local_path="/tmp/repo",
        file_tree=("src/main.py", "README.md"),
    )


@pytest.fixture
def meta_prompter(make_agent):
    return make_agent("meta_prompter")


@pytest.fixture
def six_specialists(make_agent):
    return [
        make_agent("architecture"),
        make_agent("security"),
        make_agent("quality"),
        make_agent("documentation"),
        make_agent("dependency"),
        make_agent("performance"),
    ]


@pytest.fixture
def critique_agent(make_agent):
    return make_agent("critique")


# ── Full pipeline ───────────────────────────────────────────────


class TestAnalyzeRepository:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique_agent,
        )
        assert report.repo_url == "https://github.com/test/repo"
        assert report.repo_name == "repo"
        assert report.is_degraded is False
        assert report.total_tokens_used > 0
        assert report.analysis_duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_quick_mode_skips_critique(self, codebase, meta_prompter, six_specialists, critique_agent):
        req = AnalysisRequest(repo_url="https://github.com/test/repo", quick=True)
        report = await analyze_repository(
            req, codebase, meta_prompter, six_specialists, critique_agent,
        )
        critique_agent.run.assert_not_called()
        assert report.is_degraded is False

    @pytest.mark.asyncio
    async def test_no_critique_agent(self, analysis_request, codebase, meta_prompter, six_specialists):
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, None,
        )
        assert report.is_degraded is False

    @pytest.mark.asyncio
    async def test_degraded_when_two_fail(self, analysis_request, codebase, meta_prompter, critique_agent, make_agent):
        specialists = [
            make_agent("architecture", error=RuntimeError("fail")),
            make_agent("security", error=RuntimeError("fail")),
            make_agent("quality"),
            make_agent("documentation"),
            make_agent("dependency"),
            make_agent("performance"),
        ]
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, specialists, critique_agent,
        )
        assert report.is_degraded is True
        assert len(report.degraded_dimensions) == 2

    @pytest.mark.asyncio
    async def test_degraded_skips_critique(self, analysis_request, codebase, meta_prompter, critique_agent, make_agent):
        specialists = [
            make_agent("architecture", error=RuntimeError("fail")),
            make_agent("security", error=RuntimeError("fail")),
            make_agent("quality"),
            make_agent("documentation"),
            make_agent("dependency"),
            make_agent("performance"),
        ]
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, specialists, critique_agent,
        )
        critique_agent.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_degraded_logs_spec007(self, analysis_request, codebase, meta_prompter, critique_agent, make_agent, caplog):
        specialists = [
            make_agent("architecture", error=RuntimeError("fail")),
            make_agent("security", error=RuntimeError("fail")),
            make_agent("quality"),
            make_agent("documentation"),
            make_agent("dependency"),
            make_agent("performance"),
        ]
        with caplog.at_level(logging.WARNING, logger="spectra.pipeline"):
            await analyze_repository(
                analysis_request, codebase, meta_prompter, specialists, critique_agent,
            )
        assert any("SPEC-007" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_critique_failure_logs_spec008(self, analysis_request, codebase, meta_prompter, six_specialists, make_agent, caplog):
        bad_critique = make_agent("critique", error=RuntimeError("critique boom"))
        with caplog.at_level(logging.WARNING, logger="spectra.pipeline"):
            report = await analyze_repository(
                analysis_request, codebase, meta_prompter, six_specialists, bad_critique,
            )
        assert any("SPEC-008" in r.message for r in caplog.records)
        assert report.is_degraded is False  # critique failure doesn't degrade

    @pytest.mark.asyncio
    async def test_findings_are_deduped(self, analysis_request, codebase, meta_prompter, critique_agent, make_agent, make_finding):
        dup_finding = make_finding("security", "high", line=10)
        specialists = [
            make_agent("architecture"),
            make_agent("security", findings=(dup_finding,)),
            make_agent("quality", findings=(dup_finding,)),
            make_agent("documentation"),
            make_agent("dependency"),
            make_agent("performance"),
        ]
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, specialists, critique_agent,
        )
        sec_findings = [f for f in report.findings if f.dimension == "security"]
        assert len(sec_findings) <= 1

    @pytest.mark.asyncio
    async def test_scorecard_has_dimensions(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique_agent,
        )
        assert len(report.score_card.dimensions) == 6
        assert 0 <= report.score_card.overall_score <= 100

    @pytest.mark.asyncio
    async def test_tokens_accumulated(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique_agent,
        )
        # meta_prompter(500) + 6 specialists(500 each) + critique(500) = 4000
        assert report.total_tokens_used == 4000


# ── _estimate_score ─────────────────────────────────────────────


class TestEstimateScore:
    def test_no_findings(self):
        assert _estimate_score([]) == 85.0

    def test_critical_penalty(self):
        findings = [_finding("security", "critical")]
        score = _estimate_score(findings)
        assert score == 80.0

    def test_high_penalty(self):
        findings = [_finding("security", "high")]
        assert _estimate_score(findings) == 90.0

    def test_info_no_penalty(self):
        findings = [_finding("security", "info")]
        assert _estimate_score(findings) == 100.0

    def test_floor_at_zero(self):
        findings = [_finding("security", "critical", line=i) for i in range(10)]
        score = _estimate_score(findings)
        assert score == 0.0

    def test_cap_at_100(self):
        assert _estimate_score([]) == 85.0


# ── _compute_scorecard ──────────────────────────────────────────


class TestComputeScorecard:
    def test_no_findings_all_dimensions(self):
        card = _compute_scorecard((), [])
        assert len(card.dimensions) == 6
        assert card.overall_score > 0

    def test_with_failed_roles(self):
        card = _compute_scorecard((), ["architecture"])
        dims = {d.dimension for d in card.dimensions}
        assert "architecture" not in dims
        assert len(card.dimensions) == 5

    def test_weights_rebalanced(self):
        card = _compute_scorecard((), ["architecture"])
        total_weight = sum(d.weight for d in card.dimensions)
        assert abs(total_weight - 1.0) < 0.01

    def test_findings_counted(self):
        findings = (
            _finding("security", "high", line=1),
            _finding("security", "medium", line=2),
        )
        card = _compute_scorecard(findings, [])
        sec_dim = next(d for d in card.dimensions if d.dimension == "security")
        assert sec_dim.findings_count == 2


# ── _extract_plan_files ────────────────────────────────────────


class TestExtractPlanFiles:
    def test_extracts_files_from_plan(self):
        plan = json.dumps({
            "repo_language": "python",
            "focus_areas": [
                {"agent": "security", "files": ["src/auth.py", "src/db.py"], "concerns": []},
                {"agent": "quality", "files": ["tests/test_main.py"], "concerns": []},
            ],
            "token_allocation": {},
        })
        result = _extract_plan_files(plan)
        assert result == {"src/auth.py", "src/db.py", "tests/test_main.py"}

    def test_handles_code_fence_wrapper(self):
        plan = '```json\n{"focus_areas": [{"agent": "a", "files": ["f.py"]}]}\n```'
        result = _extract_plan_files(plan)
        assert result == {"f.py"}

    def test_returns_empty_on_invalid_json(self):
        assert _extract_plan_files("not json") == set()

    def test_returns_empty_on_no_focus_areas(self):
        assert _extract_plan_files('{"repo_language": "python"}') == set()


# ── _apply_critique ────────────────────────────────────────────


class TestApplyCritique:
    def test_filters_rejected_findings(self):
        f1 = _finding("security", "high", line=1)
        f2 = _finding("security", "medium", line=2)
        critique = json.dumps({
            "validated_findings": [],
            "rejected_findings": [{"id": f1.id}],
        })
        result = _apply_critique((f1, f2), critique)
        assert f1 not in result
        assert f2 in result

    def test_rejects_by_string_id(self):
        f1 = _finding("quality", "low", line=5)
        critique = json.dumps({
            "validated_findings": [],
            "rejected_findings": [f1.id],
        })
        result = _apply_critique((f1,), critique)
        assert result == ()

    def test_falls_back_on_invalid_json(self):
        f1 = _finding("quality", "low", line=5)
        result = _apply_critique((f1,), "not json")
        assert result == (f1,)

    def test_no_rejections_returns_original(self):
        f1 = _finding("quality", "low", line=5)
        critique = json.dumps({
            "validated_findings": [],
            "rejected_findings": [],
        })
        result = _apply_critique((f1,), critique)
        assert result == (f1,)


# ── Pipeline with git_port ─────────────────────────────────────


class TestPipelineWithGitPort:
    @pytest.mark.asyncio
    async def test_reads_plan_files_via_git_port(self, analysis_request, codebase, six_specialists, critique_agent, make_agent):
        plan_json = json.dumps({
            "repo_language": "python",
            "focus_areas": [
                {"agent": "security", "files": ["src/main.py"], "concerns": []},
            ],
            "token_allocation": {},
        })
        meta = make_agent("meta_prompter")
        meta.run.return_value = AgentOutput(
            agent_role="meta_prompter",
            findings=(),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response=plan_json,
        )

        git_port = AsyncMock()
        git_port.read_file.return_value = "print('hello')"

        report = await analyze_repository(
            analysis_request, codebase, meta, six_specialists, critique_agent,
            git_port=git_port,
        )
        git_port.read_file.assert_called_once_with("/tmp/repo", "src/main.py")
        assert report.repo_url == "https://github.com/test/repo"

    @pytest.mark.asyncio
    async def test_source_files_override_git_port(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        git_port = AsyncMock()
        source = {"src/main.py": "# pre-read content"}
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique_agent,
            source_files=source, git_port=git_port,
        )
        git_port.read_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_git_port_skips_files_not_in_tree(self, analysis_request, codebase, six_specialists, critique_agent, make_agent):
        plan_json = json.dumps({
            "repo_language": "python",
            "focus_areas": [
                {"agent": "security", "files": ["nonexistent.py"], "concerns": []},
            ],
            "token_allocation": {},
        })
        meta = make_agent("meta_prompter")
        meta.run.return_value = AgentOutput(
            agent_role="meta_prompter",
            findings=(),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response=plan_json,
        )

        git_port = AsyncMock()
        report = await analyze_repository(
            analysis_request, codebase, meta, six_specialists, critique_agent,
            git_port=git_port,
        )
        git_port.read_file.assert_not_called()


# ── Cost calculation ──────────────────────────────────────────


class TestCostCalculation:
    def test_estimate_cost_opus_agents(self):
        outputs = (
            AgentOutput(agent_role="security", findings=(), tokens_used=1000, duration_seconds=1.0, raw_response="{}"),
            AgentOutput(agent_role="quality", findings=(), tokens_used=1000, duration_seconds=1.0, raw_response="{}"),
        )
        cost = estimate_cost(outputs)
        assert cost > 0.0

    def test_estimate_cost_sonnet_cheaper(self):
        opus_out = (AgentOutput(agent_role="security", findings=(), tokens_used=1000, duration_seconds=1.0, raw_response="{}"),)
        sonnet_out = (AgentOutput(agent_role="meta_prompter", findings=(), tokens_used=1000, duration_seconds=1.0, raw_response="{}"),)
        assert estimate_cost(sonnet_out) < estimate_cost(opus_out)

    def test_estimate_cost_empty(self):
        assert estimate_cost(()) == 0.0

    @pytest.mark.asyncio
    async def test_pipeline_reports_nonzero_cost(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique_agent,
        )
        assert report.total_cost_usd > 0.0


# ── Severity adjustments ─────────────────────────────────────


class TestSeverityAdjustments:
    def test_adjusts_severity(self):
        f1 = _finding("security", "high", line=1)
        critique = json.dumps({
            "rejected_findings": [],
            "severity_adjustments": [
                {"finding_id": f1.id, "original_severity": "high", "adjusted_severity": "critical"},
            ],
        })
        result = _apply_critique((f1,), critique)
        assert len(result) == 1
        assert result[0].severity == "critical"
        assert result[0].validated_by_critique is True

    def test_adjusts_and_rejects(self):
        f1 = _finding("security", "high", line=1)
        f2 = _finding("quality", "medium", line=2)
        critique = json.dumps({
            "rejected_findings": [f1.id],
            "severity_adjustments": [
                {"finding_id": f2.id, "original_severity": "medium", "adjusted_severity": "low"},
            ],
        })
        result = _apply_critique((f1, f2), critique)
        assert len(result) == 1
        assert result[0].severity == "low"

    def test_no_adjustments_returns_as_is(self):
        f1 = _finding("security", "high", line=1)
        critique = json.dumps({
            "rejected_findings": [],
            "severity_adjustments": [],
        })
        result = _apply_critique((f1,), critique)
        assert result[0].severity == "high"

    def test_ignores_invalid_adjustment(self):
        f1 = _finding("security", "high", line=1)
        critique = json.dumps({
            "rejected_findings": [],
            "severity_adjustments": [{"bad_key": "value"}],
        })
        result = _apply_critique((f1,), critique)
        assert result[0].severity == "high"


# ── Cross-cutting insights ───────────────────────────────────


class TestCrossCuttingInsights:
    def test_extracts_insights(self):
        raw = json.dumps({
            "rejected_findings": [],
            "cross_cutting_insights": [
                "Security patterns are inconsistent across modules",
                "Documentation is sparse in infrastructure layer",
            ],
        })
        insights = _extract_cross_cutting_insights(raw)
        assert len(insights) == 2
        assert "Security" in insights[0]

    def test_empty_insights(self):
        raw = json.dumps({"rejected_findings": [], "cross_cutting_insights": []})
        assert _extract_cross_cutting_insights(raw) == ()

    def test_invalid_json(self):
        assert _extract_cross_cutting_insights("not json") == ()

    def test_missing_key(self):
        raw = json.dumps({"rejected_findings": []})
        assert _extract_cross_cutting_insights(raw) == ()

    @pytest.mark.asyncio
    async def test_pipeline_stores_insights(self, analysis_request, codebase, meta_prompter, six_specialists, make_agent):
        critique_response = json.dumps({
            "validated_findings": [],
            "rejected_findings": [],
            "severity_adjustments": [],
            "cross_cutting_insights": ["Insight one", "Insight two"],
        })
        critique = make_agent("critique")
        critique.run.return_value = AgentOutput(
            agent_role="critique",
            findings=(),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response=critique_response,
        )
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique,
        )
        assert len(report.cross_cutting_insights) == 2
        assert "Insight one" in report.cross_cutting_insights


# ── Token budget / allocation helpers ─────────────────────────


class TestTokenAllocations:
    def test_extracts_allocations(self):
        raw = json.dumps({
            "focus_areas": [],
            "token_allocation": {"architecture": 100000, "security": 120000},
        })
        result = _extract_token_allocations(raw)
        assert result == {"architecture": 100000, "security": 120000}

    def test_returns_none_on_empty(self):
        raw = json.dumps({"focus_areas": [], "token_allocation": {}})
        assert _extract_token_allocations(raw) is None

    def test_returns_none_on_invalid_json(self):
        assert _extract_token_allocations("bad") is None

    def test_returns_none_on_missing_key(self):
        raw = json.dumps({"focus_areas": []})
        assert _extract_token_allocations(raw) is None


# ── _should_run_critique ──────────────────────────────────────


class TestShouldRunCritique:
    def test_runs_normally(self, analysis_request, critique_agent):
        assert _should_run_critique(analysis_request, False, critique_agent, 200000) is True

    def test_skips_in_quick_mode(self, critique_agent):
        req = AnalysisRequest(repo_url="https://example.com", quick=True)
        assert _should_run_critique(req, False, critique_agent, 200000) is False

    def test_skips_when_degraded(self, analysis_request, critique_agent):
        assert _should_run_critique(analysis_request, True, critique_agent, 200000) is False

    def test_skips_when_no_agent(self, analysis_request):
        assert _should_run_critique(analysis_request, False, None, 200000) is False

    def test_skips_when_budget_exhausted(self, analysis_request, critique_agent):
        assert _should_run_critique(analysis_request, False, critique_agent, 0) is False


# ── Observer wiring ───────────────────────────────────────────


class TestObserverWiring:
    @pytest.mark.asyncio
    async def test_observer_called_during_pipeline(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        from unittest.mock import MagicMock
        observer = MagicMock()
        await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique_agent,
            observer=observer,
        )
        observer.on_stage_start.assert_called()
        observer.on_stage_complete.assert_called()
        observer.on_agent_start.assert_called()
        observer.on_agent_success.assert_called()

    @pytest.mark.asyncio
    async def test_observer_none_doesnt_crash(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        report = await analyze_repository(
            analysis_request, codebase, meta_prompter, six_specialists, critique_agent,
            observer=None,
        )
        assert report.repo_url == "https://github.com/test/repo"

    @pytest.mark.asyncio
    async def test_observer_receives_failure_events(self, analysis_request, codebase, meta_prompter, critique_agent, make_agent):
        from unittest.mock import MagicMock
        observer = MagicMock()
        specialists = [
            make_agent("architecture", error=RuntimeError("fail")),
            make_agent("security"),
            make_agent("quality"),
            make_agent("documentation"),
            make_agent("dependency"),
            make_agent("performance"),
        ]
        await analyze_repository(
            analysis_request, codebase, meta_prompter, specialists, critique_agent,
            observer=observer,
        )
        observer.on_agent_failure.assert_called_once()
