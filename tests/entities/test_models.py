"""Tests for Pydantic frozen models in spectra.entities.models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from spectra.entities.models import (
    DEFAULT_DIMENSION_SCORE,
    EXCELLENT_SCORE,
    MIN_CONFIDENCE,
    PASSING_SCORE,
    AgentContext,
    AgentOutput,
    AnalysisReport,
    AnalysisRequest,
    BatchCacheKey,
    BatchPrompt,
    CacheEntry,
    CacheStats,
    Codebase,
    DimensionScore,
    FileLocation,
    Finding,
    RepoCacheKey,
    ScoreCard,
    TokenBudget,
    estimate_cost,
    score_to_grade,
)

# ── FileLocation ────────────────────────────────────────────────


class TestFileLocation:
    def test_create_with_required_fields(self):
        loc = FileLocation(file_path="src/main.py", line_start=10)
        assert loc.file_path == "src/main.py"
        assert loc.line_start == 10
        assert loc.line_end is None

    def test_create_with_line_end(self):
        loc = FileLocation(file_path="src/main.py", line_start=10, line_end=20)
        assert loc.line_end == 20

    def test_frozen_immutability(self):
        loc = FileLocation(file_path="src/main.py", line_start=10)
        with pytest.raises(ValidationError):
            loc.file_path = "other.py"

    def test_hashable(self):
        loc = FileLocation(file_path="src/main.py", line_start=10)
        assert hash(loc) is not None
        assert {loc}  # can be in a set


# ── Finding ─────────────────────────────────────────────────────


class TestFinding:
    def test_create_valid(self, sample_finding):
        assert sample_finding.id == "TEST-001"
        assert sample_finding.dimension == "security"
        assert sample_finding.severity == "high"
        assert sample_finding.confidence == 0.9
        assert sample_finding.validated_by_critique is False

    def test_frozen_immutability(self, sample_finding):
        with pytest.raises(ValidationError):
            sample_finding.title = "changed"

    def test_confidence_lower_bound(self, sample_finding_factory):
        with pytest.raises(ValidationError):
            sample_finding_factory(confidence=-0.1)

    def test_confidence_upper_bound(self, sample_finding_factory):
        with pytest.raises(ValidationError):
            sample_finding_factory(confidence=1.1)

    def test_confidence_boundaries(self, sample_finding_factory):
        zero = sample_finding_factory(confidence=0.0)
        one = sample_finding_factory(confidence=1.0)
        assert zero.confidence == 0.0
        assert one.confidence == 1.0

    def test_invalid_dimension(self, sample_finding_factory):
        with pytest.raises(ValidationError):
            sample_finding_factory(dimension="nonexistent")

    def test_invalid_severity(self, sample_finding_factory):
        with pytest.raises(ValidationError):
            sample_finding_factory(severity="urgent")

    def test_hash_same_location_dimension(self, sample_finding_factory):
        f1 = sample_finding_factory(id="A", title="First")
        f2 = sample_finding_factory(id="B", title="Second")
        assert hash(f1) == hash(f2)

    def test_hash_different_location(self, sample_finding_factory):
        f1 = sample_finding_factory(line_start=10)
        f2 = sample_finding_factory(line_start=20)
        assert hash(f1) != hash(f2)

    def test_hash_different_dimension(self, sample_finding_factory):
        f1 = sample_finding_factory(dimension="security")
        f2 = sample_finding_factory(dimension="quality", agent_role="quality")
        assert hash(f1) != hash(f2)

    def test_eq_same_location_dimension(self, sample_finding_factory):
        f1 = sample_finding_factory(id="A", title="First")
        f2 = sample_finding_factory(id="B", title="Second")
        assert f1 == f2

    def test_eq_different_location(self, sample_finding_factory):
        f1 = sample_finding_factory(line_start=10)
        f2 = sample_finding_factory(line_start=20)
        assert f1 != f2

    def test_eq_different_type(self, sample_finding):
        assert sample_finding != "not a finding"

    def test_dedup_in_set(self, sample_finding_factory):
        f1 = sample_finding_factory(id="A", title="First")
        f2 = sample_finding_factory(id="B", title="Second")
        deduped = {f1, f2}
        assert len(deduped) == 1

    def test_dedup_preserves_different(self, sample_finding_factory):
        f1 = sample_finding_factory(line_start=10)
        f2 = sample_finding_factory(line_start=20)
        deduped = {f1, f2}
        assert len(deduped) == 2

    def test_is_critical_true(self, sample_finding_factory):
        f = sample_finding_factory(severity="critical")
        assert f.is_critical() is True

    def test_is_critical_false(self, sample_finding_factory):
        f = sample_finding_factory(severity="high")
        assert f.is_critical() is False

    def test_is_actionable_critical(self, sample_finding_factory):
        f = sample_finding_factory(severity="critical")
        assert f.is_actionable() is True

    def test_is_actionable_medium(self, sample_finding_factory):
        f = sample_finding_factory(severity="medium")
        assert f.is_actionable() is True

    def test_is_actionable_low(self, sample_finding_factory):
        f = sample_finding_factory(severity="low")
        assert f.is_actionable() is False

    def test_is_actionable_info(self, sample_finding_factory):
        f = sample_finding_factory(severity="info")
        assert f.is_actionable() is False


# ── DimensionScore ──────────────────────────────────────────────


class TestDimensionScore:
    def test_create_valid(self):
        ds = DimensionScore(
            dimension="architecture",
            score=85.0,
            grade="B+",
            findings_count=3,
            weight=0.25,
        )
        assert ds.dimension == "architecture"
        assert ds.score == 85.0

    def test_score_lower_bound(self):
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension="security",
                score=-1.0,
                grade="F",
                findings_count=0,
                weight=0.25,
            )

    def test_score_upper_bound(self):
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension="security",
                score=101.0,
                grade="A+",
                findings_count=0,
                weight=0.25,
            )

    def test_frozen(self):
        ds = DimensionScore(
            dimension="security",
            score=90.0,
            grade="A",
            findings_count=2,
            weight=0.25,
        )
        with pytest.raises(ValidationError):
            ds.score = 50.0

    def test_is_passing_above_threshold(self):
        ds = DimensionScore(
            dimension="security",
            score=75.0,
            grade="C+",
            findings_count=2,
            weight=0.25,
        )
        assert ds.is_passing() is True

    def test_is_passing_at_boundary(self):
        ds = DimensionScore(
            dimension="security",
            score=60.0,
            grade="D",
            findings_count=2,
            weight=0.25,
        )
        assert ds.is_passing() is True

    def test_is_passing_below_threshold(self):
        ds = DimensionScore(
            dimension="security",
            score=59.9,
            grade="D-",
            findings_count=2,
            weight=0.25,
        )
        assert ds.is_passing() is False

    def test_is_excellent_above_threshold(self):
        ds = DimensionScore(
            dimension="security",
            score=95.0,
            grade="A+",
            findings_count=0,
            weight=0.25,
        )
        assert ds.is_excellent() is True

    def test_is_excellent_at_boundary(self):
        ds = DimensionScore(
            dimension="security",
            score=90.0,
            grade="A",
            findings_count=1,
            weight=0.25,
        )
        assert ds.is_excellent() is True

    def test_is_excellent_below_threshold(self):
        ds = DimensionScore(
            dimension="security",
            score=89.9,
            grade="A-",
            findings_count=2,
            weight=0.25,
        )
        assert ds.is_excellent() is False


# ── ScoreCard ───────────────────────────────────────────────────


class TestScoreCard:
    def test_create_valid(self, sample_scorecard):
        assert 0 <= sample_scorecard.overall_score <= 100
        assert len(sample_scorecard.dimensions) == 6
        assert sample_scorecard.total_findings == 18

    def test_frozen(self, sample_scorecard):
        with pytest.raises(ValidationError):
            sample_scorecard.overall_score = 0.0

    def test_dimensions_are_tuple(self, sample_scorecard):
        assert isinstance(sample_scorecard.dimensions, tuple)

    def test_overall_score_bounds(self):
        with pytest.raises(ValidationError):
            ScoreCard(
                overall_score=101.0,
                overall_grade="A+",
                dimensions=(),
                total_findings=0,
            )

    def test_worst_dimension(self, sample_scorecard):
        worst = sample_scorecard.worst_dimension()
        assert worst is not None
        assert worst.dimension == "documentation"
        assert worst.score == 70.0

    def test_worst_dimension_empty(self):
        sc = ScoreCard(
            overall_score=0.0,
            overall_grade="F",
            dimensions=(),
            total_findings=0,
        )
        assert sc.worst_dimension() is None

    def test_best_dimension(self, sample_scorecard):
        best = sample_scorecard.best_dimension()
        assert best is not None
        assert best.dimension == "security"
        assert best.score == 90.0

    def test_best_dimension_empty(self):
        sc = ScoreCard(
            overall_score=0.0,
            overall_grade="F",
            dimensions=(),
            total_findings=0,
        )
        assert sc.best_dimension() is None

    def test_grade_for_existing(self, sample_scorecard):
        grade = sample_scorecard.grade_for("architecture")
        assert grade == "B+"

    def test_grade_for_all_dimensions(self, sample_scorecard):
        assert sample_scorecard.grade_for("security") == "A"
        assert sample_scorecard.grade_for("documentation") == "C"

    def test_grade_for_missing(self, sample_scorecard):
        sc = ScoreCard(
            overall_score=0.0,
            overall_grade="F",
            dimensions=(),
            total_findings=0,
        )
        assert sc.grade_for("architecture") is None


# ── AgentOutput ─────────────────────────────────────────────────


class TestAgentOutput:
    def test_create_valid(self, sample_finding):
        output = AgentOutput(
            agent_role="security",
            findings=(sample_finding,),
            tokens_used=1000,
            duration_seconds=2.5,
            raw_response='{"findings": []}',
        )
        assert output.agent_role == "security"
        assert len(output.findings) == 1

    def test_frozen(self, sample_finding):
        output = AgentOutput(
            agent_role="security",
            findings=(sample_finding,),
            tokens_used=1000,
            duration_seconds=2.5,
            raw_response="{}",
        )
        with pytest.raises(ValidationError):
            output.tokens_used = 0


# ── AgentContext ────────────────────────────────────────────────


class TestAgentContext:
    def test_create_valid(self):
        ctx = AgentContext(
            agent_role="architecture",
            system_prompt="You are an architecture analyst.",
            user_prompt="Analyze this codebase.",
            model="claude-opus-4-7",
            max_tokens=4096,
        )
        assert ctx.agent_role == "architecture"
        assert ctx.max_tokens == 4096


# ── AnalysisReport ──────────────────────────────────────────────


class TestAnalysisReport:
    def test_create_valid(self, sample_scorecard, sample_finding):
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(sample_finding,),
            analysis_duration_seconds=45.0,
            total_tokens_used=50000,
            total_cost_usd=1.25,
            agents_used=("architecture", "security"),
        )
        assert report.is_degraded is False
        assert report.degraded_dimensions == ()

    def test_degraded_state(self, sample_scorecard, sample_finding):
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(sample_finding,),
            analysis_duration_seconds=45.0,
            total_tokens_used=50000,
            total_cost_usd=1.25,
            agents_used=("architecture",),
            is_degraded=True,
            degraded_dimensions=("security", "quality"),
        )
        assert report.is_degraded is True
        assert len(report.degraded_dimensions) == 2

    def test_critical_finding_count_with_criticals(
        self,
        sample_scorecard,
        sample_finding_factory,
    ):
        critical = sample_finding_factory(severity="critical")
        high = sample_finding_factory(severity="high", line_start=20)
        critical2 = sample_finding_factory(
            severity="critical",
            line_start=30,
        )
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(critical, high, critical2),
            analysis_duration_seconds=10.0,
            total_tokens_used=5000,
            total_cost_usd=0.10,
            agents_used=("security",),
        )
        assert report.critical_finding_count() == 2

    def test_critical_finding_count_no_criticals(
        self,
        sample_scorecard,
        sample_finding_factory,
    ):
        high = sample_finding_factory(severity="high")
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(high,),
            analysis_duration_seconds=10.0,
            total_tokens_used=5000,
            total_cost_usd=0.10,
            agents_used=("security",),
        )
        assert report.critical_finding_count() == 0

    def test_critical_finding_count_empty(self, sample_scorecard):
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(),
            analysis_duration_seconds=10.0,
            total_tokens_used=5000,
            total_cost_usd=0.10,
            agents_used=("security",),
        )
        assert report.critical_finding_count() == 0


# ── Codebase ────────────────────────────────────────────────────


class TestCodebase:
    def test_create_valid(self):
        cb = Codebase(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            local_path="/tmp/repo",  # noqa: S108
            file_tree=("src/main.py", "README.md"),
        )
        assert len(cb.file_tree) == 2

    def test_frozen(self):
        cb = Codebase(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            local_path="/tmp/repo",  # noqa: S108
            file_tree=("src/main.py",),
        )
        with pytest.raises(ValidationError):
            cb.repo_name = "changed"

    def test_file_count(self):
        cb = Codebase(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            local_path="/tmp/repo",  # noqa: S108
            file_tree=("src/main.py", "README.md", "setup.py"),
        )
        assert cb.file_count() == 3

    def test_file_count_empty(self):
        cb = Codebase(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            local_path="/tmp/repo",  # noqa: S108
            file_tree=(),
        )
        assert cb.file_count() == 0


# ── AnalysisRequest ─────────────────────────────────────────────


class TestAnalysisRequest:
    def test_defaults(self):
        req = AnalysisRequest(repo_url="https://github.com/test/repo")
        assert req.quick is False
        assert req.output_format == "rich"

    def test_quick_mode(self):
        req = AnalysisRequest(repo_url="https://github.com/test/repo", quick=True)
        assert req.quick is True


# ── TokenBudget ─────────────────────────────────────────────────


class TestTokenBudget:
    def test_defaults(self):
        budget = TokenBudget()
        assert budget.total == 800_000
        assert budget.meta_prompter == 5_000
        assert budget.specialists_pool == 500_000
        assert budget.critique_reserved == 200_000
        assert budget.buffer == 95_000

    def test_budget_sums_correctly(self):
        budget = TokenBudget()
        allocated = budget.meta_prompter + budget.specialists_pool + budget.critique_reserved + budget.buffer
        assert allocated == budget.total

    def test_has_remaining_true(self):
        budget = TokenBudget()
        assert budget.has_remaining(500_000) is True

    def test_has_remaining_false_at_limit(self):
        budget = TokenBudget()
        assert budget.has_remaining(800_000) is False

    def test_has_remaining_false_over_limit(self):
        budget = TokenBudget()
        assert budget.has_remaining(900_000) is False

    def test_remaining_under_budget(self):
        budget = TokenBudget()
        assert budget.remaining(300_000) == 500_000

    def test_remaining_at_budget(self):
        budget = TokenBudget()
        assert budget.remaining(800_000) == 0

    def test_remaining_over_budget_clamps_to_zero(self):
        budget = TokenBudget()
        assert budget.remaining(900_000) == 0


# ── Named Constants ────────────────────────────────────────────


class TestNamedConstants:
    def test_passing_score_value(self):
        assert PASSING_SCORE == 60.0

    def test_excellent_score_value(self):
        assert EXCELLENT_SCORE == 90.0

    def test_default_dimension_score_value(self):
        assert DEFAULT_DIMENSION_SCORE == 70.0

    def test_min_confidence_value(self):
        assert MIN_CONFIDENCE == 0.7


# ── score_to_grade ──────────────────────────────────────────────


class TestScoreToGrade:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (100.0, "A+"),
            (95.0, "A+"),
            (94.9, "A"),
            (90.0, "A"),
            (89.9, "A-"),
            (87.0, "A-"),
            (86.9, "B+"),
            (83.0, "B+"),
            (82.9, "B"),
            (80.0, "B"),
            (79.9, "B-"),
            (77.0, "B-"),
            (76.9, "C+"),
            (73.0, "C+"),
            (72.9, "C"),
            (70.0, "C"),
            (69.9, "C-"),
            (67.0, "C-"),
            (66.9, "D+"),
            (63.0, "D+"),
            (62.9, "D"),
            (60.0, "D"),
            (59.9, "D-"),
            (57.0, "D-"),
            (56.9, "F"),
            (0.0, "F"),
        ],
    )
    def test_grade_boundaries(self, score, expected):
        assert score_to_grade(score) == expected

    def test_perfect_score(self):
        assert score_to_grade(100.0) == "A+"

    def test_zero_score(self):
        assert score_to_grade(0.0) == "F"


# ── estimate_cost ──────────────────────────────────────────────


class TestEstimateCost:
    def test_empty_outputs(self):
        assert estimate_cost(()) == 0.0

    def test_single_output(self):
        output = AgentOutput(
            agent_role="security",
            findings=(),
            tokens_used=1000,
            duration_seconds=1.0,
            raw_response="{}",
        )
        cost = estimate_cost((output,))
        assert cost > 0

    def test_multiple_outputs(self):
        outputs = tuple(
            AgentOutput(
                agent_role=role,
                findings=(),
                tokens_used=1000,
                duration_seconds=1.0,
                raw_response="{}",
            )
            for role in ("architecture", "security", "quality")
        )
        cost = estimate_cost(outputs)
        assert cost > 0

    def test_meta_prompter_same_as_opus_specialist(self):
        """All 8 agents now run on Opus 4.7, so per-token cost is identical."""
        meta = AgentOutput(
            agent_role="meta_prompter",
            findings=(),
            tokens_used=1000,
            duration_seconds=1.0,
            raw_response="{}",
        )
        opus = AgentOutput(
            agent_role="security",
            findings=(),
            tokens_used=1000,
            duration_seconds=1.0,
            raw_response="{}",
        )
        assert estimate_cost((meta,)) == estimate_cost((opus,))

    def test_opus_cost_matches_anthropic_pricing(self):
        """Sanity-check the per-1K rates against Anthropic's public Opus 4.7
        pricing ($5/M input, $25/M output). At a 70/30 input/output split
        the blended rate per 1K tokens is 0.7*0.005 + 0.3*0.025 = 0.011.
        For 1000 tokens that's exactly 1.1 cents.

        This is the regression net for the v0.3.1 cost-overstatement bug
        where rates were 3x the real prices.
        """
        out = AgentOutput(
            agent_role="security",
            findings=(),
            tokens_used=1000,
            duration_seconds=1.0,
            raw_response="{}",
        )
        cost = estimate_cost((out,))
        # 0.7 * 0.005 + 0.3 * 0.025 = 0.011 USD per 1K tokens
        assert cost == 0.011, f"expected 0.011 USD/1K, got {cost}"

    def test_zero_tokens(self):
        output = AgentOutput(
            agent_role="security",
            findings=(),
            tokens_used=0,
            duration_seconds=1.0,
            raw_response="{}",
        )
        assert estimate_cost((output,)) == 0.0

    def test_cost_is_rounded(self):
        output = AgentOutput(
            agent_role="security",
            findings=(),
            tokens_used=1000,
            duration_seconds=1.0,
            raw_response="{}",
        )
        cost = estimate_cost((output,))
        assert cost == round(cost, 4)


# ── Finding edge cases ─────────────────────────────────────────


class TestFindingEdgeCases:
    def test_estimated_hours_default(self):
        f = Finding(
            id="F-1",
            dimension="security",
            severity="high",
            title="Test",
            description="Desc",
            location=FileLocation(file_path="a.py", line_start=1),
            recommendation="Fix",
            agent_role="security",
            confidence=0.8,
        )
        assert f.estimated_hours == 0.0

    def test_estimated_hours_set(self):
        f = Finding(
            id="F-1",
            dimension="security",
            severity="high",
            title="Test",
            description="Desc",
            location=FileLocation(file_path="a.py", line_start=1),
            recommendation="Fix",
            agent_role="security",
            confidence=0.8,
            estimated_hours=5.5,
        )
        assert f.estimated_hours == 5.5

    def test_validated_by_critique_default(self):
        f = Finding(
            id="F-1",
            dimension="security",
            severity="high",
            title="Test",
            description="Desc",
            location=FileLocation(file_path="a.py", line_start=1),
            recommendation="Fix",
            agent_role="security",
            confidence=0.8,
        )
        assert f.validated_by_critique is False

    def test_model_copy_preserves_fields(self):
        f = Finding(
            id="F-1",
            dimension="security",
            severity="high",
            title="Test",
            description="Desc",
            location=FileLocation(file_path="a.py", line_start=1),
            recommendation="Fix",
            agent_role="security",
            confidence=0.8,
        )
        f2 = f.model_copy(update={"severity": "critical", "validated_by_critique": True})
        assert f2.severity == "critical"
        assert f2.validated_by_critique is True
        assert f2.id == "F-1"
        assert f2.title == "Test"

    def test_eq_with_none(self, sample_finding):
        assert sample_finding != None  # noqa: E711

    def test_eq_with_int(self, sample_finding):
        assert sample_finding != 42


# ── AnalysisReport edge cases ──────────────────────────────────


class TestAnalysisReportEdgeCases:
    def test_cross_cutting_insights_default(self, sample_scorecard):
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(),
            analysis_duration_seconds=1.0,
            total_tokens_used=0,
            total_cost_usd=0.0,
            agents_used=(),
        )
        assert report.cross_cutting_insights == ()

    def test_hallucination_removed_count_default(self, sample_scorecard):
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(),
            analysis_duration_seconds=1.0,
            total_tokens_used=0,
            total_cost_usd=0.0,
            agents_used=(),
        )
        assert report.hallucination_removed_count == 0

    def test_with_cross_cutting_insights(self, sample_scorecard):
        report = AnalysisReport(
            repo_url="https://github.com/test/repo",
            repo_name="repo",
            score_card=sample_scorecard,
            findings=(),
            analysis_duration_seconds=1.0,
            total_tokens_used=0,
            total_cost_usd=0.0,
            agents_used=(),
            cross_cutting_insights=("Insight 1", "Insight 2"),
        )
        assert len(report.cross_cutting_insights) == 2


# ── CacheEntry ─────────────────────────────────────────────────


def _cache_finding() -> Finding:
    return Finding(
        id="CACHE-001",
        dimension="security",
        severity="high",
        title="Cached finding",
        description="From cache test",
        location=FileLocation(file_path="src/auth.py", line_start=42),
        recommendation="Fix it",
        agent_role="security",
        confidence=0.9,
    )


class TestCacheEntry:
    def test_create_with_required_fields(self):
        entry = CacheEntry(
            file_hash="abc123",
            file_path="src/auth.py",
            dimension="security",
            findings=(_cache_finding(),),
            model_version="claude-opus-4-7",
            prompt_version="security-v1",
            spectra_version="0.1.0",
            schema_version="v1",
            computed_at=datetime.now(UTC),
        )
        assert entry.file_hash == "abc123"
        assert entry.dimension == "security"
        assert len(entry.findings) == 1

    def test_frozen_immutability(self):
        entry = CacheEntry(
            file_hash="abc",
            file_path="src/x.py",
            dimension="quality",
            findings=(),
            model_version="m",
            prompt_version="p",
            spectra_version="0.1.0",
            schema_version="v1",
            computed_at=datetime.now(UTC),
        )
        with pytest.raises(ValidationError):
            entry.file_hash = "other"

    def test_findings_is_tuple_immutable(self):
        entry = CacheEntry(
            file_hash="abc",
            file_path="src/x.py",
            dimension="quality",
            findings=(_cache_finding(),),
            model_version="m",
            prompt_version="p",
            spectra_version="0.1.0",
            schema_version="v1",
            computed_at=datetime.now(UTC),
        )
        assert isinstance(entry.findings, tuple)


# ── CacheStats ─────────────────────────────────────────────────


class TestCacheStats:
    def test_create_with_required_fields(self):
        stats = CacheStats(
            total_entries=10,
            total_repos=2,
            db_size_bytes=4096,
            hit_rate_last_100=0.85,
            oldest_entry_at=datetime.now(UTC),
        )
        assert stats.total_entries == 10
        assert stats.total_repos == 2
        assert stats.db_size_bytes == 4096

    def test_oldest_entry_can_be_none(self):
        stats = CacheStats(
            total_entries=0,
            total_repos=0,
            db_size_bytes=0,
            hit_rate_last_100=0.0,
            oldest_entry_at=None,
        )
        assert stats.oldest_entry_at is None

    def test_frozen_immutability(self):
        stats = CacheStats(
            total_entries=1,
            total_repos=1,
            db_size_bytes=10,
            hit_rate_last_100=1.0,
            oldest_entry_at=None,
        )
        with pytest.raises(ValidationError):
            stats.total_entries = 99

    def test_cache_stats_extended_fields(self):
        """Phase 4: per-table breakdown + per-dimension hit rates exist + frozen."""
        now = datetime.now(UTC)
        stats = CacheStats(
            total_entries=10,
            total_repos=2,
            db_size_bytes=4096,
            hit_rate_last_100=0.5,
            oldest_entry_at=now,
            full_report_entries=3,
            batch_entries=5,
            hit_log_entries=2,
            hit_rate_by_dimension={"security": 0.8, "quality": 0.4},
            most_recent_activity_at=now,
        )
        assert stats.full_report_entries == 3
        assert stats.batch_entries == 5
        assert stats.hit_log_entries == 2
        assert stats.hit_rate_by_dimension["security"] == 0.8
        assert stats.most_recent_activity_at == now
        with pytest.raises(ValidationError):
            stats.full_report_entries = 99

    def test_cache_stats_hit_rate_by_dimension_typed(self):
        """Phase 4: dict[Dimension, float] rejects non-Dimension keys."""
        # Valid dimension keys are accepted
        stats = CacheStats(
            total_entries=0,
            total_repos=0,
            db_size_bytes=0,
            hit_rate_last_100=0.0,
            oldest_entry_at=None,
            full_report_entries=0,
            batch_entries=0,
            hit_log_entries=0,
            hit_rate_by_dimension={"architecture": 0.5},
            most_recent_activity_at=None,
        )
        assert stats.hit_rate_by_dimension["architecture"] == 0.5
        # Invalid dimension key is rejected by the Literal type validator
        with pytest.raises(ValidationError):
            CacheStats(
                total_entries=0,
                total_repos=0,
                db_size_bytes=0,
                hit_rate_last_100=0.0,
                oldest_entry_at=None,
                full_report_entries=0,
                batch_entries=0,
                hit_log_entries=0,
                hit_rate_by_dimension={"not-a-dimension": 0.5},
                most_recent_activity_at=None,
            )


# ── RepoCacheKey ───────────────────────────────────────────────


def _repo_cache_key(**overrides: object) -> RepoCacheKey:
    """Build a RepoCacheKey with sane defaults so each test can override one field."""
    base: dict[str, object] = {
        "repo_signature": "abcd1234",
        "spectra_version": "0.1.0",
        "model_versions": "claude-opus-4-7|claude-opus-4-7",
        "prompt_versions": "blake2b-of-prompts",
        "schema_version": "v1",
    }
    base.update(overrides)
    return RepoCacheKey(**base)  # type: ignore[arg-type]


class TestRepoCacheKey:
    def test_create_with_required_fields(self):
        key = _repo_cache_key()
        assert key.repo_signature == "abcd1234"
        assert key.spectra_version == "0.1.0"
        assert key.schema_version == "v1"

    def test_frozen_immutability(self):
        key = _repo_cache_key()
        with pytest.raises(ValidationError):
            key.repo_signature = "other"  # type: ignore[misc]

    def test_equal_keys_compare_equal(self):
        a = _repo_cache_key()
        b = _repo_cache_key()
        assert a == b

    def test_changing_repo_signature_breaks_equality(self):
        a = _repo_cache_key()
        b = _repo_cache_key(repo_signature="ffff9999")
        assert a != b

    def test_changing_spectra_version_breaks_equality(self):
        a = _repo_cache_key()
        b = _repo_cache_key(spectra_version="0.2.0")
        assert a != b

    def test_changing_model_versions_breaks_equality(self):
        a = _repo_cache_key()
        b = _repo_cache_key(model_versions="claude-opus-5-0|claude-opus-5-0")
        assert a != b

    def test_changing_prompt_versions_breaks_equality(self):
        a = _repo_cache_key()
        b = _repo_cache_key(prompt_versions="different-hash")
        assert a != b

    def test_changing_schema_version_breaks_equality(self):
        a = _repo_cache_key()
        b = _repo_cache_key(schema_version="v2")
        assert a != b

    def test_hashable(self):
        # Frozen Pydantic models with hashable fields are hashable; needed for dict keys.
        key = _repo_cache_key()
        assert hash(key) == hash(_repo_cache_key())


# ── BatchPrompt (Phase 3) ─────────────────────────────────────


def _batch_prompt(**overrides: object) -> BatchPrompt:
    base: dict[str, object] = {
        "batch_id": "batch-aabbcc",
        "file_paths": ("src/auth/login.py", "src/auth/logout.py"),
        "file_hashes": ("hash-1", "hash-2"),
        "prompt_text": "analyze these files",
    }
    base.update(overrides)
    return BatchPrompt(**base)  # type: ignore[arg-type]


class TestBatchPrompt:
    def test_batch_prompt_frozen_and_hashable(self):
        b = _batch_prompt()
        with pytest.raises(ValidationError):
            b.batch_id = "x"  # type: ignore[misc]
        assert hash(b) == hash(_batch_prompt())


# ── BatchCacheKey (Phase 3) ───────────────────────────────────


def _batch_key(**overrides: object) -> BatchCacheKey:
    base: dict[str, object] = {
        "batch_id": "batch-aabbcc",
        "dimension": "security",
        "model_version": "claude-opus-4-7",
        "prompt_version": "prompt-hash-v1",
        "schema_version": "v1",
        "spectra_version": "0.2.0",
    }
    base.update(overrides)
    return BatchCacheKey(**base)  # type: ignore[arg-type]


class TestBatchCacheKey:
    def test_batch_cache_key_frozen_with_six_components(self):
        key = _batch_key()
        with pytest.raises(ValidationError):
            key.batch_id = "other"  # type: ignore[misc]
        assert {
            "batch_id",
            "dimension",
            "model_version",
            "prompt_version",
            "schema_version",
            "spectra_version",
        } == set(BatchCacheKey.model_fields)

    def test_batch_cache_key_equality_value_based(self):
        assert _batch_key() == _batch_key()
        assert _batch_key() != _batch_key(model_version="claude-opus-5-0")
        assert _batch_key() != _batch_key(prompt_version="other")
        assert _batch_key() != _batch_key(spectra_version="0.3.0")
