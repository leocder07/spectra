"""Pydantic frozen models for the Spectra domain.

All models use ``frozen=True`` to guarantee immutability across the
pipeline.  Constants define scoring thresholds shared by use-case and
infrastructure layers.
"""

from __future__ import annotations

import bisect
from datetime import datetime  # noqa: TC003 — used by Pydantic at runtime

from pydantic import BaseModel, ConfigDict, Field

from spectra.entities.enums import (
    AgentRole,
    Dimension,
    Grade,
    SchemaVersion,
    Severity,
)

# ── Named Constants ────────────────────────────────────────────
PASSING_SCORE: float = 60.0
"""Minimum score (0-100) for a dimension to be considered passing."""

EXCELLENT_SCORE: float = 90.0
"""Threshold for an excellent dimension score."""

DEFAULT_DIMENSION_SCORE: float = 70.0
"""Score assigned to a dimension with zero findings."""

MIN_CONFIDENCE: float = 0.7
"""Minimum confidence for a finding to be included in the report."""


class FileLocation(BaseModel, frozen=True):
    """Value object pinpointing a source code location.

    Attributes:
        file_path: Repository-relative path (e.g. ``src/main.py``).
        line_start: First line of the relevant span (1-based).
        line_end: Last line, or ``None`` for single-line locations.
    """

    file_path: str
    line_start: int
    line_end: int | None = None


class Finding(BaseModel, frozen=True):
    """Core domain entity — an immutable, dedupable analysis finding.

    Two findings are equal when they share the same file path, start
    line, and dimension, which prevents duplicate reports from
    overlapping agents.

    Attributes:
        id: Unique identifier (e.g. ``sec-001``).
        dimension: Analysis dimension that owns this finding.
        severity: Impact level from critical to info.
        title: Short human-readable summary.
        description: Detailed explanation with evidence.
        location: Source code location reference.
        recommendation: Actionable fix suggestion.
        agent_role: The agent that produced this finding.
        confidence: Agent confidence in the finding (0.0-1.0).
        validated_by_critique: Whether CritiqueAgent confirmed this.
        estimated_hours: Estimated remediation effort in hours.
    """

    id: str
    dimension: Dimension
    severity: Severity
    title: str
    description: str
    location: FileLocation
    recommendation: str
    agent_role: AgentRole
    confidence: float = Field(ge=0.0, le=1.0)
    validated_by_critique: bool = False
    estimated_hours: float = 0.0
    code_snippet: str = ""

    def __hash__(self) -> int:
        """Hash by (file_path, line_start, dimension) for deduplication."""
        return hash((self.location.file_path, self.location.line_start, self.dimension))

    def __eq__(self, other: object) -> bool:
        """Equality by location + dimension to collapse duplicate reports."""
        if not isinstance(other, Finding):
            return False
        return (
            self.location.file_path == other.location.file_path
            and self.location.line_start == other.location.line_start
            and self.dimension == other.dimension
        )

    def is_critical(self) -> bool:
        """Return True if this finding has critical severity."""
        return self.severity == "critical"

    def is_actionable(self) -> bool:
        """Return True if severity is critical, high, or medium."""
        return self.severity in ("critical", "high", "medium")


class DimensionScore(BaseModel, frozen=True):
    """Score for a single analysis dimension.

    Attributes:
        dimension: Which dimension this score represents.
        score: Numeric score from 0 to 100.
        grade: Letter grade derived from score.
        findings_count: Number of findings in this dimension.
        weight: Normalized weight used for overall score calculation.
    """

    dimension: Dimension
    score: float = Field(ge=0.0, le=100.0)
    grade: Grade
    findings_count: int
    weight: float

    def is_passing(self) -> bool:
        """Return True if score meets the passing threshold (60)."""
        return self.score >= PASSING_SCORE

    def is_excellent(self) -> bool:
        """Return True if score meets the excellent threshold (90)."""
        return self.score >= EXCELLENT_SCORE


class ScoreCard(BaseModel, frozen=True):
    """Aggregate scores across all analysis dimensions.

    Attributes:
        overall_score: Weighted average of all dimension scores.
        overall_grade: Letter grade for the overall score.
        dimensions: Per-dimension breakdown.
        total_findings: Sum of findings across all dimensions.
    """

    overall_score: float = Field(ge=0.0, le=100.0)
    overall_grade: Grade
    dimensions: tuple[DimensionScore, ...]
    total_findings: int

    def worst_dimension(self) -> DimensionScore | None:
        """Return the dimension with the lowest score, or None if empty."""
        if not self.dimensions:
            return None
        return min(self.dimensions, key=lambda d: d.score)

    def best_dimension(self) -> DimensionScore | None:
        """Return the dimension with the highest score, or None if empty."""
        if not self.dimensions:
            return None
        return max(self.dimensions, key=lambda d: d.score)

    def grade_for(self, dimension: Dimension) -> Grade | None:
        """Look up the letter grade for a specific dimension.

        Args:
            dimension: The dimension to query.

        Returns:
            The grade if found, otherwise None.
        """
        for d in self.dimensions:
            if d.dimension == dimension:
                return d.grade
        return None


class AgentOutput(BaseModel, frozen=True):
    """Validated output from a single agent run.

    Attributes:
        agent_role: Which agent produced this output.
        findings: Validated findings extracted from the LLM response.
        tokens_used: Total tokens consumed (input + output).
        duration_seconds: Wall-clock time for the LLM call.
        raw_response: Unprocessed LLM response text.
        dimension_score: Optional LLM-assigned holistic score (0-100).
    """

    agent_role: AgentRole
    findings: tuple[Finding, ...]
    tokens_used: int
    duration_seconds: float
    raw_response: str
    dimension_score: float | None = None


class AgentContext(BaseModel, frozen=True):
    """Input context passed to an agent for analysis.

    Attributes:
        agent_role: Target agent role.
        system_prompt: System prompt defining agent behavior.
        user_prompt: User prompt with repository data.
        model: Anthropic model identifier.
        max_tokens: Maximum tokens for the response.
    """

    agent_role: AgentRole
    system_prompt: str
    user_prompt: str
    model: str
    max_tokens: int


class AnalysisReport(BaseModel, frozen=True):
    """Final report combining all agent results.

    Attributes:
        repo_url: URL of the analyzed repository.
        repo_name: Short name derived from the URL.
        score_card: Aggregate scores across all dimensions.
        findings: Deduplicated, validated findings.
        analysis_duration_seconds: Total pipeline wall-clock time.
        total_tokens_used: Sum of tokens across all agents.
        total_cost_usd: Estimated API cost in USD.
        agents_used: Roles of agents that contributed.
        is_degraded: True if 2+ agents failed.
        degraded_dimensions: Dimensions missing due to agent failure.
        cross_cutting_insights: CritiqueAgent cross-dimension notes.
        hallucination_removed_count: Findings removed by path validation.
    """

    repo_url: str
    repo_name: str
    score_card: ScoreCard
    findings: tuple[Finding, ...]
    analysis_duration_seconds: float
    total_tokens_used: int
    total_cost_usd: float
    agents_used: tuple[AgentRole, ...]
    is_degraded: bool = False
    degraded_dimensions: tuple[Dimension, ...] = ()
    cross_cutting_insights: tuple[str, ...] = ()
    hallucination_removed_count: int = 0

    def critical_finding_count(self) -> int:
        """Return the number of findings with critical severity."""
        return sum(1 for f in self.findings if f.is_critical())


class Codebase(BaseModel, frozen=True):
    """Representation of a cloned repository on disk.

    Attributes:
        repo_url: Original remote URL.
        repo_name: Short name (last path segment).
        local_path: Absolute path to the clone directory.
        file_tree: Sorted list of repository-relative file paths.
    """

    repo_url: str
    repo_name: str
    local_path: str
    file_tree: tuple[str, ...]

    def file_count(self) -> int:
        """Return the total number of files in the repository."""
        return len(self.file_tree)


class AnalysisRequest(BaseModel, frozen=True):
    """User-initiated analysis request.

    Attributes:
        repo_url: Git HTTPS URL to analyze.
        quick: Skip CritiqueAgent when True.
        output_format: Report format (``rich``, ``html``, or ``json``).
    """

    repo_url: str
    quick: bool = False
    output_format: str = "rich"


class TokenBudget(BaseModel, frozen=True):
    """Token allocation across pipeline stages.

    The total budget is split between MetaPrompter (planning),
    the 6 specialist agents, CritiqueAgent, and a safety buffer.

    Attributes:
        total: Maximum tokens for the entire pipeline.
        meta_prompter: Tokens reserved for planning.
        specialists_pool: Shared pool for all 6 specialists.
        critique_reserved: Tokens reserved for CritiqueAgent.
        buffer: Safety margin to avoid overruns.
    """

    total: int = 800_000
    meta_prompter: int = 5_000
    specialists_pool: int = 500_000
    critique_reserved: int = 200_000
    buffer: int = 95_000

    def has_remaining(self, used: int) -> bool:
        """Return True if tokens remain in the budget.

        Args:
            used: Tokens consumed so far.
        """
        return used < self.total

    def remaining(self, used: int) -> int:
        """Return tokens remaining, clamped to zero.

        Args:
            used: Tokens consumed so far.
        """
        return max(0, self.total - used)


class CacheEntry(BaseModel, frozen=True):
    """One cached row: findings for a (file_hash, dimension) pair.

    The composite cache key — ``(file_hash, dimension, model_version,
    prompt_version, schema_version)`` — guarantees that any change to
    file contents, model identity, prompt text, or schema shape misses
    the cache and triggers re-analysis. Entries are written by
    ``put_findings`` and never mutated.

    Attributes:
        file_hash: blake2b digest (16 bytes → 32 hex chars) of file bytes.
        file_path: Repo-relative path captured at write time.
        dimension: Analysis dimension this row belongs to.
        findings: Validated findings produced for this file + dimension.
        model_version: LLM model identifier (e.g. ``claude-opus-4-7``).
        prompt_version: Per-dimension prompt version tag.
        spectra_version: ``spectra.__version__`` at write time.
        schema_version: ``Finding`` schema version (see ``SchemaVersion``).
        computed_at: UTC timestamp of the original analysis.
    """

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    file_hash: str
    file_path: str
    dimension: Dimension
    findings: tuple[Finding, ...]
    model_version: str
    prompt_version: str
    spectra_version: str
    schema_version: SchemaVersion
    computed_at: datetime


class CacheStats(BaseModel, frozen=True):
    """Aggregate cache metrics surfaced by ``CachePort.stats``.

    Attributes:
        total_entries: Row count in ``findings_cache``.
        total_repos: Distinct ``repo_signature`` values present.
        db_size_bytes: On-disk size of ``cache.db``.
        hit_rate_last_100: Rolling cache hit rate over the last 100 lookups.
        oldest_entry_at: Earliest ``computed_at`` across all rows.
        full_report_entries: Phase 2 ``full_report_cache`` row count.
        batch_entries: Phase 3 ``findings_batches`` row count.
        hit_log_entries: Telemetry ``hit_log`` row count.
        hit_rate_by_dimension: Rolling per-dimension hit rate (last 100 lookups
            per dimension). Empty for dimensions with no logged lookups.
        most_recent_activity_at: Most recent ``computed_at`` across all
            cache rows; ``None`` for an empty cache.
    """

    model_config = ConfigDict(frozen=True)

    total_entries: int
    total_repos: int
    db_size_bytes: int
    hit_rate_last_100: float = Field(ge=0.0, le=1.0)
    oldest_entry_at: datetime | None = None
    full_report_entries: int = 0
    batch_entries: int = 0
    hit_log_entries: int = 0
    hit_rate_by_dimension: dict[Dimension, float] = Field(default_factory=dict)
    most_recent_activity_at: datetime | None = None


class BatchPrompt(BaseModel, frozen=True):
    """Per-``focus_area`` analysis batch — Phase 3 cache unit.

    Each ``BatchPrompt`` represents one specialist call: the prompt text
    that will be sent to the LLM, the files it covers, and the
    deterministic ``batch_id`` (``blake2b`` of sorted file hashes) used
    as the cache key. Tuples preserve immutability so the value object
    remains hashable and safe to share across asyncio tasks.

    Attributes:
        batch_id: ``blake2b(sorted(file_hashes))`` hex digest.
        file_paths: Repo-relative paths covered by this batch.
        file_hashes: Per-file blake2b digests, same order as ``file_paths``.
        prompt_text: Fully composed user prompt for the specialist call.
    """

    batch_id: str
    file_paths: tuple[str, ...]
    file_hashes: tuple[str, ...]
    prompt_text: str


class BatchCacheKey(BaseModel, frozen=True):
    """Composite key for the per-batch findings cache (Phase 3).

    A row in ``findings_cache`` is reused only when every component
    matches. Bumping any of model, prompt, schema, or spectra version
    naturally misses the cache without touching disk — invalidation
    is implicit, not policy.

    Attributes:
        batch_id: Deterministic batch identifier (see ``BatchPrompt``).
        dimension: Analysis dimension that produced the findings.
        model_version: LLM model id for this dimension's specialist.
        prompt_version: ``blake2b`` of ``specialist_prompt + shared + critique``.
        schema_version: ``Finding`` schema version literal.
        spectra_version: ``spectra.__version__`` at lookup time.
    """

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    batch_id: str
    dimension: Dimension
    model_version: str
    prompt_version: str
    schema_version: str
    spectra_version: str


class RepoCacheKey(BaseModel, frozen=True):
    """Composite key for the repo-level full-report cache (Phase 2).

    Bundles every signal that must invalidate a cached ``AnalysisReport``
    when it changes. Two ``RepoCacheKey`` instances compare equal iff all
    five fields match, so a model bump, prompt edit, schema change, or
    spectra version update naturally misses the cache and forces a rerun.

    Attributes:
        repo_signature: Deterministic blake2b digest of the file tree.
        spectra_version: ``spectra.__version__`` at write time.
        model_versions: Canonical sort of model IDs across all 8 agents.
        prompt_versions: blake2b digest of the shared guidance + each
            specialist prompt + the critique system prompt.
        schema_version: ``Finding`` schema version literal.
    """

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    repo_signature: str
    spectra_version: str
    model_versions: str
    prompt_versions: str
    schema_version: str  # plain str — matches the TEXT column in cache.db


_GRADE_THRESHOLDS = [57, 60, 63, 67, 70, 73, 77, 80, 83, 87, 90, 95]
_GRADE_LABELS: list[Grade] = [
    "F",
    "D-",
    "D",
    "D+",
    "C-",
    "C",
    "C+",
    "B-",
    "B",
    "B+",
    "A-",
    "A",
    "A+",
]


def score_to_grade(score: float) -> Grade:
    """Map a numeric score (0-100) to a letter grade.

    Args:
        score: Numeric score between 0 and 100.

    Returns:
        Letter grade from ``A+`` (95-100) down to ``F`` (0-56).
    """
    idx = bisect.bisect_right(_GRADE_THRESHOLDS, score)
    return _GRADE_LABELS[idx]


# ── Cost Estimation ───────────────────────────────────────────

# Per-1K-token pricing (USD)
_OPUS_INPUT_PER_1K: float = 0.005
_OPUS_OUTPUT_PER_1K: float = 0.025
_SONNET_INPUT_PER_1K: float = 0.003
_SONNET_OUTPUT_PER_1K: float = 0.015

# Without input/output split, use weighted average per 1K tokens.
# Assumes ~70% input / 30% output ratio.
_OPUS_AVG_PER_1K: float = 0.7 * _OPUS_INPUT_PER_1K + 0.3 * _OPUS_OUTPUT_PER_1K
_SONNET_AVG_PER_1K: float = 0.7 * _SONNET_INPUT_PER_1K + 0.3 * _SONNET_OUTPUT_PER_1K

_MODEL_COST: dict[AgentRole, float] = {
    "meta_prompter": _OPUS_AVG_PER_1K,  # Opus 4.7, effort=medium
    "architecture": _OPUS_AVG_PER_1K,
    "security": _OPUS_AVG_PER_1K,
    "quality": _OPUS_AVG_PER_1K,
    "documentation": _OPUS_AVG_PER_1K,
    "dependency": _OPUS_AVG_PER_1K,
    "performance": _OPUS_AVG_PER_1K,
    "critique": _OPUS_AVG_PER_1K,  # Opus 4.7, adaptive thinking + task_budget
}


def estimate_cost(outputs: tuple[AgentOutput, ...]) -> float:
    """Estimate total USD cost from agent outputs.

    Uses per-1K-token pricing with a 70/30 input/output ratio
    assumption. Sonnet is used for MetaPrompter; Opus for all others.

    Args:
        outputs: Completed agent outputs with token counts.

    Returns:
        Estimated cost in USD, rounded to 4 decimal places.
    """
    total = 0.0
    for out in outputs:
        rate = _MODEL_COST.get(out.agent_role, _OPUS_AVG_PER_1K)
        total += (out.tokens_used / 1000.0) * rate
    return round(total, 4)
