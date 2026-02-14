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
from spectra.use_cases.analyze_repository import (
    _apply_critique,
    _compute_scorecard,
    _estimate_score,
    _extract_plan_files,
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
