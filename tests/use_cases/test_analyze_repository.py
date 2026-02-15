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
    estimate_cost,
)
from spectra.use_cases.analyze_repository import (
    _apply_critique,
    _build_source_context,
    _compute_scorecard,
    _estimate_score,
    _extract_cross_cutting_insights,
    _extract_plan_context,
    _extract_plan_files,
    _extract_token_allocations,
    _merge_findings,
    _role_to_dimension,
    _should_run_critique,
    _validate_finding_paths,
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
        local_path="/tmp/repo",  # noqa: S108
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
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
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
            req,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
        )
        critique_agent.run.assert_not_called()
        assert report.is_degraded is False

    @pytest.mark.asyncio
    async def test_no_critique_agent(self, analysis_request, codebase, meta_prompter, six_specialists):
        report = await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            None,
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
            analysis_request,
            codebase,
            meta_prompter,
            specialists,
            critique_agent,
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
        await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            specialists,
            critique_agent,
        )
        critique_agent.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_degraded_logs_spec007(
        self, analysis_request, codebase, meta_prompter, critique_agent, make_agent, caplog
    ):
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
                analysis_request,
                codebase,
                meta_prompter,
                specialists,
                critique_agent,
            )
        assert any("SPEC-007" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_critique_failure_logs_spec008(
        self, analysis_request, codebase, meta_prompter, six_specialists, make_agent, caplog
    ):
        bad_critique = make_agent("critique", error=RuntimeError("critique boom"))
        with caplog.at_level(logging.WARNING, logger="spectra.pipeline"):
            report = await analyze_repository(
                analysis_request,
                codebase,
                meta_prompter,
                six_specialists,
                bad_critique,
            )
        assert any("SPEC-008" in r.message for r in caplog.records)
        assert report.is_degraded is False  # critique failure doesn't degrade

    @pytest.mark.asyncio
    async def test_findings_are_deduped(
        self, analysis_request, codebase, meta_prompter, critique_agent, make_agent, make_finding
    ):
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
            analysis_request,
            codebase,
            meta_prompter,
            specialists,
            critique_agent,
        )
        sec_findings = [f for f in report.findings if f.dimension == "security"]
        assert len(sec_findings) <= 1

    @pytest.mark.asyncio
    async def test_scorecard_has_dimensions(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ):
        report = await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
        )
        assert len(report.score_card.dimensions) == 6
        assert 0 <= report.score_card.overall_score <= 100

    @pytest.mark.asyncio
    async def test_tokens_accumulated(self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent):
        report = await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
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
        assert score == 85.0  # 100 - 15 = 85

    def test_high_penalty(self):
        findings = [_finding("security", "high")]
        assert _estimate_score(findings) == 92.0  # 100 - 8 = 92

    def test_info_no_penalty(self):
        findings = [_finding("security", "info")]
        assert _estimate_score(findings) == 100.0

    def test_penalty_capped_at_55(self):
        # 10 criticals = 150 raw penalty, but capped at 55
        findings = [_finding("security", "critical", line=i) for i in range(10)]
        score = _estimate_score(findings)
        assert score == 45.0  # 100 - 55 (cap)

    def test_blended_with_llm_score(self):
        findings = [_finding("security", "high")]
        # penalty_score = 92, llm_score = 80 → 0.4*80 + 0.6*92 = 32 + 55.2 = 87.2
        assert _estimate_score(findings, llm_score=80.0) == 87.2

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
        plan = json.dumps(
            {
                "repo_language": "python",
                "focus_areas": [
                    {"agent": "security", "files": ["src/auth.py", "src/db.py"], "concerns": []},
                    {"agent": "quality", "files": ["tests/test_main.py"], "concerns": []},
                ],
                "token_allocation": {},
            }
        )
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
        critique = json.dumps(
            {
                "validated_findings": [],
                "rejected_findings": [{"id": f1.id}],
            }
        )
        result = _apply_critique((f1, f2), critique)
        assert f1 not in result
        assert f2 in result

    def test_rejects_by_string_id(self):
        f1 = _finding("quality", "low", line=5)
        critique = json.dumps(
            {
                "validated_findings": [],
                "rejected_findings": [f1.id],
            }
        )
        result = _apply_critique((f1,), critique)
        assert result == ()

    def test_falls_back_on_invalid_json(self):
        f1 = _finding("quality", "low", line=5)
        result = _apply_critique((f1,), "not json")
        assert result == (f1,)

    def test_no_rejections_returns_original(self):
        f1 = _finding("quality", "low", line=5)
        critique = json.dumps(
            {
                "validated_findings": [],
                "rejected_findings": [],
            }
        )
        result = _apply_critique((f1,), critique)
        assert result == (f1,)


# ── Pipeline with git_port ─────────────────────────────────────


class TestPipelineWithGitPort:
    @pytest.mark.asyncio
    async def test_reads_plan_files_via_git_port(
        self, analysis_request, codebase, six_specialists, critique_agent, make_agent
    ):
        plan_json = json.dumps(
            {
                "repo_language": "python",
                "focus_areas": [
                    {"agent": "security", "files": ["src/main.py"], "concerns": []},
                ],
                "token_allocation": {},
            }
        )
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
            analysis_request,
            codebase,
            meta,
            six_specialists,
            critique_agent,
            git_port=git_port,
        )
        git_port.read_file.assert_called_once_with("/tmp/repo", "src/main.py")  # noqa: S108
        assert report.repo_url == "https://github.com/test/repo"

    @pytest.mark.asyncio
    async def test_source_files_override_git_port(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ):
        git_port = AsyncMock()
        source = {"src/main.py": "# pre-read content"}
        await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
            source_files=source,
            git_port=git_port,
        )
        git_port.read_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_git_port_skips_files_not_in_tree(
        self, analysis_request, codebase, six_specialists, critique_agent, make_agent
    ):
        plan_json = json.dumps(
            {
                "repo_language": "python",
                "focus_areas": [
                    {"agent": "security", "files": ["nonexistent.py"], "concerns": []},
                ],
                "token_allocation": {},
            }
        )
        meta = make_agent("meta_prompter")
        meta.run.return_value = AgentOutput(
            agent_role="meta_prompter",
            findings=(),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response=plan_json,
        )

        git_port = AsyncMock()
        await analyze_repository(
            analysis_request,
            codebase,
            meta,
            six_specialists,
            critique_agent,
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
        opus_out = (
            AgentOutput(agent_role="security", findings=(), tokens_used=1000, duration_seconds=1.0, raw_response="{}"),
        )
        sonnet_out = (
            AgentOutput(
                agent_role="meta_prompter", findings=(), tokens_used=1000, duration_seconds=1.0, raw_response="{}"
            ),
        )
        assert estimate_cost(sonnet_out) < estimate_cost(opus_out)

    def test_estimate_cost_empty(self):
        assert estimate_cost(()) == 0.0

    @pytest.mark.asyncio
    async def test_pipeline_reports_nonzero_cost(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ):
        report = await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
        )
        assert report.total_cost_usd > 0.0


# ── Severity adjustments ─────────────────────────────────────


class TestSeverityAdjustments:
    def test_adjusts_severity(self):
        f1 = _finding("security", "high", line=1)
        critique = json.dumps(
            {
                "rejected_findings": [],
                "severity_adjustments": [
                    {"finding_id": f1.id, "original_severity": "high", "adjusted_severity": "critical"},
                ],
            }
        )
        result = _apply_critique((f1,), critique)
        assert len(result) == 1
        assert result[0].severity == "critical"
        assert result[0].validated_by_critique is True

    def test_adjusts_and_rejects(self):
        f1 = _finding("security", "high", line=1)
        f2 = _finding("quality", "medium", line=2)
        critique = json.dumps(
            {
                "rejected_findings": [f1.id],
                "severity_adjustments": [
                    {"finding_id": f2.id, "original_severity": "medium", "adjusted_severity": "low"},
                ],
            }
        )
        result = _apply_critique((f1, f2), critique)
        assert len(result) == 1
        assert result[0].severity == "low"

    def test_no_adjustments_returns_as_is(self):
        f1 = _finding("security", "high", line=1)
        critique = json.dumps(
            {
                "rejected_findings": [],
                "severity_adjustments": [],
            }
        )
        result = _apply_critique((f1,), critique)
        assert result[0].severity == "high"

    def test_ignores_invalid_adjustment(self):
        f1 = _finding("security", "high", line=1)
        critique = json.dumps(
            {
                "rejected_findings": [],
                "severity_adjustments": [{"bad_key": "value"}],
            }
        )
        result = _apply_critique((f1,), critique)
        assert result[0].severity == "high"


# ── Cross-cutting insights ───────────────────────────────────


class TestCrossCuttingInsights:
    def test_extracts_insights(self):
        raw = json.dumps(
            {
                "rejected_findings": [],
                "cross_cutting_insights": [
                    "Security patterns are inconsistent across modules",
                    "Documentation is sparse in infrastructure layer",
                ],
            }
        )
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
    async def test_pipeline_stores_insights(
        self, analysis_request, codebase, meta_prompter, six_specialists, make_agent
    ):
        critique_response = json.dumps(
            {
                "validated_findings": [],
                "rejected_findings": [],
                "severity_adjustments": [],
                "cross_cutting_insights": ["Insight one", "Insight two"],
            }
        )
        critique = make_agent("critique")
        critique.run.return_value = AgentOutput(
            agent_role="critique",
            findings=(),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response=critique_response,
        )
        report = await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique,
        )
        assert len(report.cross_cutting_insights) == 2
        assert "Insight one" in report.cross_cutting_insights


# ── Token budget / allocation helpers ─────────────────────────


class TestTokenAllocations:
    def test_extracts_allocations(self):
        raw = json.dumps(
            {
                "focus_areas": [],
                "token_allocation": {"architecture": 100000, "security": 120000},
            }
        )
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
    async def test_observer_called_during_pipeline(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ):
        from unittest.mock import MagicMock

        observer = MagicMock()
        await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
            observer=observer,
        )
        observer.on_stage_start.assert_called()
        observer.on_stage_complete.assert_called()
        observer.on_agent_start.assert_called()
        observer.on_agent_success.assert_called()

    @pytest.mark.asyncio
    async def test_observer_none_doesnt_crash(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ):
        report = await analyze_repository(
            analysis_request,
            codebase,
            meta_prompter,
            six_specialists,
            critique_agent,
            observer=None,
        )
        assert report.repo_url == "https://github.com/test/repo"

    @pytest.mark.asyncio
    async def test_observer_receives_failure_events(
        self, analysis_request, codebase, meta_prompter, critique_agent, make_agent
    ):
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
            analysis_request,
            codebase,
            meta_prompter,
            specialists,
            critique_agent,
            observer=observer,
        )
        observer.on_agent_failure.assert_called_once()


# ── _merge_findings ─────────────────────────────────────────────


class TestMergeFindings:
    def test_empty_successes(self):
        result = _merge_findings([])
        assert result == ()

    def test_single_output_with_findings(self):
        f1 = _finding("security", "high", line=1)
        output = AgentOutput(
            agent_role="security",
            findings=(f1,),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response="{}",
        )
        result = _merge_findings([output])
        assert len(result) == 1

    def test_deduplicates_same_findings(self):
        f1 = _finding("security", "high", line=10)
        out1 = AgentOutput(
            agent_role="security",
            findings=(f1,),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response="{}",
        )
        out2 = AgentOutput(
            agent_role="quality",
            findings=(f1,),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response="{}",
        )
        result = _merge_findings([out1, out2])
        assert len(result) == 1

    def test_keeps_different_findings(self):
        f1 = _finding("security", "high", line=1)
        f2 = _finding("quality", "medium", line=2)
        out1 = AgentOutput(
            agent_role="security", findings=(f1,), tokens_used=500, duration_seconds=1.0, raw_response="{}"
        )
        out2 = AgentOutput(
            agent_role="quality", findings=(f2,), tokens_used=500, duration_seconds=1.0, raw_response="{}"
        )
        result = _merge_findings([out1, out2])
        assert len(result) == 2


# ── _validate_finding_paths ────────────────────────────────────


class TestValidateFindingPaths:
    def test_valid_path_kept(self):
        f = _finding("security", "high", line=1)
        result = _validate_finding_paths((f,), ("src/main.py",))
        assert len(result) == 1

    def test_invalid_path_removed(self):
        f = Finding(
            id="F-1",
            dimension="security",
            severity="high",
            title="test",
            description="test",
            location=FileLocation(file_path="nonexistent.py", line_start=1),
            recommendation="fix",
            agent_role="security",
            confidence=0.8,
        )
        result = _validate_finding_paths((f,), ("src/main.py",))
        assert len(result) == 0

    def test_empty_findings(self):
        result = _validate_finding_paths((), ("src/main.py",))
        assert result == ()

    def test_empty_file_tree(self):
        f = _finding("security", "high", line=1)
        result = _validate_finding_paths((f,), ())
        assert len(result) == 0

    def test_partial_path_match(self):
        f = Finding(
            id="F-1",
            dimension="security",
            severity="high",
            title="test",
            description="test",
            location=FileLocation(file_path="main.py", line_start=1),
            recommendation="fix",
            agent_role="security",
            confidence=0.8,
        )
        result = _validate_finding_paths((f,), ("src/main.py",))
        assert len(result) == 1

    def test_empty_path_kept(self):
        f = Finding(
            id="F-1",
            dimension="security",
            severity="high",
            title="test",
            description="test",
            location=FileLocation(file_path="", line_start=1),
            recommendation="fix",
            agent_role="security",
            confidence=0.8,
        )
        result = _validate_finding_paths((f,), ("src/main.py",))
        assert len(result) == 1


# ── _role_to_dimension ──────────────────────────────────────────


class TestRoleToDimension:
    def test_architecture(self):
        assert _role_to_dimension("architecture") == "architecture"

    def test_security(self):
        assert _role_to_dimension("security") == "security"

    def test_quality(self):
        assert _role_to_dimension("quality") == "quality"

    def test_documentation(self):
        assert _role_to_dimension("documentation") == "documentation"

    def test_dependency_maps_to_maintainability(self):
        assert _role_to_dimension("dependency") == "maintainability"

    def test_performance(self):
        assert _role_to_dimension("performance") == "performance"

    def test_unknown_defaults_to_architecture(self):
        assert _role_to_dimension("unknown") == "architecture"


# ── _build_source_context ──────────────────────────────────────


class TestBuildSourceContext:
    def test_none_returns_empty(self):
        assert _build_source_context(None) == ""

    def test_empty_dict_returns_empty(self):
        assert _build_source_context({}) == ""

    def test_single_file(self):
        result = _build_source_context({"src/main.py": "print('hello')"})
        assert "SOURCE CODE:" in result
        assert "src/main.py" in result
        assert "print('hello')" in result

    def test_multiple_files(self):
        result = _build_source_context({"src/a.py": "a_content", "src/b.py": "b_content"})
        assert "src/a.py" in result
        assert "src/b.py" in result


# ── _extract_plan_context ─────────────────────────────────────


class TestExtractPlanContext:
    def test_valid_plan_with_focus_areas(self):
        plan = json.dumps(
            {
                "focus_areas": [
                    {"agent": "security", "files": ["auth.py"], "concerns": ["injection"]},
                ],
            }
        )
        result = _extract_plan_context(plan)
        assert result is not None
        assert "security" in result

    def test_invalid_json_returns_none(self):
        assert _extract_plan_context("bad json") is None

    def test_empty_focus_areas_returns_none(self):
        plan = json.dumps({"focus_areas": []})
        assert _extract_plan_context(plan) is None

    def test_missing_focus_areas_returns_none(self):
        plan = json.dumps({"repo_language": "python"})
        assert _extract_plan_context(plan) is None

    def test_focus_area_with_no_agent_skipped(self):
        plan = json.dumps({"focus_areas": [{"files": ["a.py"], "concerns": ["test"]}]})
        assert _extract_plan_context(plan) is None

    def test_focus_area_with_no_files_or_concerns_skipped(self):
        plan = json.dumps({"focus_areas": [{"agent": "security"}]})
        assert _extract_plan_context(plan) is None


# ── _estimate_score edge cases ─────────────────────────────────


class TestEstimateScoreEdgeCases:
    def test_single_info_finding(self):
        findings = [_finding("security", "info")]
        assert _estimate_score(findings) == 100.0

    def test_multiple_severities(self):
        findings = [
            _finding("security", "critical", line=1),
            _finding("security", "high", line=2),
            _finding("security", "medium", line=3),
        ]
        # 15 + 8 + 3 = 26 penalty
        assert _estimate_score(findings) == 74.0

    def test_blended_score_with_no_findings(self):
        # No findings = default 85, but with llm_score
        assert _estimate_score([], llm_score=90.0) == 85.0  # no findings returns default

    def test_llm_score_high_penalty_low(self):
        findings = [_finding("security", "low", line=1)]
        # penalty_score = 99, llm = 100 → 0.4*100 + 0.6*99 = 40 + 59.4 = 99.4
        assert _estimate_score(findings, llm_score=100.0) == 99.4

    def test_llm_score_boundary_zero(self):
        findings = [_finding("security", "high", line=1)]
        # penalty = 92, llm = 0 → 0.4*0 + 0.6*92 = 55.2
        assert _estimate_score(findings, llm_score=0.0) == 55.2


# ── _compute_scorecard edge cases ──────────────────────────────


class TestComputeScorecardEdgeCases:
    def test_all_roles_failed(self):
        failed = ["architecture", "security", "quality", "documentation", "dependency", "performance"]
        card = _compute_scorecard((), failed)
        assert len(card.dimensions) == 0

    def test_single_dimension_remaining(self):
        failed = ["architecture", "quality", "documentation", "dependency", "performance"]
        card = _compute_scorecard((), failed)
        assert len(card.dimensions) == 1
        assert card.dimensions[0].dimension == "security"

    def test_with_llm_scores(self):
        output = AgentOutput(
            agent_role="security",
            findings=(),
            tokens_used=500,
            duration_seconds=1.0,
            raw_response="{}",
            dimension_score=90.0,
        )
        card = _compute_scorecard((), [], agent_outputs=[output])
        sec_dim = next(d for d in card.dimensions if d.dimension == "security")
        # Should blend llm_score with penalty score
        assert sec_dim.score > 0


# ── Parametrized _estimate_score ─────────────────────────────


class TestEstimateScoreParametrized:
    @pytest.mark.parametrize(
        ("score", "expected_min", "expected_max"),
        [
            (0, 45.0, 45.0),
            (25, 45.0, 100.0),
            (50, 45.0, 100.0),
            (75, 45.0, 100.0),
            (100, 85.0, 100.0),
        ],
    )
    def test_score_range_with_varying_criticals(self, score, expected_min, expected_max):
        n_critical = max(0, (100 - score) // 10)
        findings = [_finding("security", "critical", line=i) for i in range(n_critical)]
        result = _estimate_score(findings)
        assert expected_min <= result <= expected_max

    @pytest.mark.parametrize("llm_score", [0, 25, 50, 75, 100])
    def test_blended_with_various_llm_scores(self, llm_score):
        findings = [_finding("security", "high", line=1)]
        result = _estimate_score(findings, llm_score=float(llm_score))
        assert 0.0 <= result <= 100.0

    @pytest.mark.parametrize(
        "sev,penalty",
        [
            ("critical", 15.0),
            ("high", 8.0),
            ("medium", 3.0),
            ("low", 1.0),
            ("info", 0.0),
        ],
    )
    def test_individual_severity_penalty(self, sev, penalty):
        findings = [_finding("security", sev, line=1)]
        expected = round(100.0 - penalty, 1)
        assert _estimate_score(findings) == expected

    def test_all_zero_llm_with_zero_findings(self):
        assert _estimate_score([]) == 85.0

    def test_blended_formula_exact(self):
        findings = [_finding("security", "medium", line=1)]
        result = _estimate_score(findings, llm_score=50.0)
        assert result == 78.2


# ── Parametrized _validate_repo_url ──────────────────────────


class TestValidateRepoUrlParametrized:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/user/repo",
            "https://github.com/user/repo.git",
            "https://gitlab.com/org/project",
            "https://bitbucket.org/user/repo",
            "https://github.com/user/my-repo-123",
            "https://github.com/user/repo/tree/main",
        ],
    )
    def test_valid_urls(self, url):
        from spectra.adapters.cli_controller import _validate_repo_url

        assert _validate_repo_url(url) is None

    @pytest.mark.parametrize(
        ("url", "expected_fragment"),
        [
            ("", "empty"),
            ("   ", "empty"),
            ("http://github.com/user/repo", "HTTPS"),
            ("ftp://example.com/repo", "HTTPS"),
            ("git@github.com:user/repo.git", "HTTPS"),
            ("ssh://github.com/user/repo", "HTTPS"),
            ("not-a-url", "HTTPS"),
            ("https://", "Invalid URL"),
            ("https:// spaces.com/repo", "Invalid URL"),
        ],
    )
    def test_invalid_urls(self, url, expected_fragment):
        from spectra.adapters.cli_controller import _validate_repo_url

        result = _validate_repo_url(url)
        assert result is not None
        assert expected_fragment.lower() in result.lower()

    def test_url_exceeds_max_length(self):
        from spectra.adapters.cli_controller import _validate_repo_url

        long_url = "https://github.com/" + "a" * 2048
        result = _validate_repo_url(long_url)
        assert result is not None
        assert "2048" in result

    def test_url_at_max_length(self):
        from spectra.adapters.cli_controller import _validate_repo_url

        url = "https://github.com/" + "a" * (2048 - len("https://github.com/"))
        result = _validate_repo_url(url)
        assert result is None

    def test_url_with_special_chars(self):
        from spectra.adapters.cli_controller import _validate_repo_url

        result = _validate_repo_url("https://github.com/user/repo-name_v2.0")
        assert result is None
