"""Pydantic frozen models for the Spectra domain.

All models use ``frozen=True`` to guarantee immutability across the
pipeline.  Constants define scoring thresholds shared by use-case and
infrastructure layers.
"""

from __future__ import annotations

import bisect
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spectra.entities.enums import (
    AgentRole,
    Dimension,
    Grade,
    SchemaVersion,
    Severity,
)
from spectra.entities.receipt import ScanReceipt

# ── Named Constants ────────────────────────────────────────────
PASSING_SCORE: float = 60.0
"""Minimum score (0-100) for a dimension to be considered passing."""

Classification = Literal["confidential", "public"]
"""Report classification — controls watermark, banner, and findings redaction.

``confidential`` (default) renders the full report with all findings,
code snippets, and file paths plus a CONFIDENTIAL watermark and DLP
meta tag. ``public`` strictly redacts every individual finding,
keeping only the overall grade, dimension scores, and findings counts —
suitable for sharing outside the organization. See capability #56.
"""

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
    rule_id: str = ""
    """Stable identifier for sentinel findings (ADR-011 §2). Default is
    the empty string so existing findings remain valid. Set to
    ``"SPEC-PROMPT-INJECTION-DETECTED"`` by the CritiqueAgent when an
    injection attempt is detected; the orchestrator uses this sentinel
    to mark the run compromised."""

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


class SecretFinding(BaseModel, frozen=True):
    """Pre-flight secret-scan match — distinct from a code-quality ``Finding``.

    Pre-flight secrets are detected before any LLM call so they never land in
    a prompt. They are surfaced as their own value object (not a ``Finding``)
    because they are owned by the workspace boundary, not by an analysis
    dimension, and they are the trigger for SPEC-011 abort behavior.

    Attributes:
        file_path: Repository-relative path of the file containing the secret.
        line: 1-based line number of the match.
        pattern_name: Stable identifier of the regex that matched
            (e.g. ``aws_access_key``, ``github_pat``, ``private_key``).
            Used for grouping in CLI output and tests; never the secret itself.
    """

    file_path: str
    line: int = Field(ge=1)
    pattern_name: str


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


ValidationStatus = Literal[
    "validated",
    "non-validated:critique-skipped",
    "non-validated:quick-mode",
]
"""Q2 #20: trust-stamp on the report.

- ``validated``: full pipeline ran, CritiqueAgent confirmed every finding.
- ``non-validated:quick-mode``: caller passed ``--quick``; critique never ran.
- ``non-validated:critique-skipped``: critique was skipped for another
  reason (e.g. ``--no-critique``, degraded run that bypassed critique).

The HTML banner, JSON top-level field, and SARIF
``runs[0].properties.validation_status`` all surface the same string so
SAST consumers know whether the adversarial input check ran."""


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
        validation_status: Q2 #20 trust stamp — see ``ValidationStatus``.
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
    is_compromised: bool = False
    """ADR-011 §2: True when the CritiqueAgent detected a prompt-injection
    attempt and emitted a ``SPEC-PROMPT-INJECTION-DETECTED`` finding.
    The report renderer surfaces a banner; public-mode reports refuse to
    publish a grade for compromised runs."""
    validation_status: ValidationStatus = "validated"

    receipt: ScanReceipt | None = None
    """Roadmap #57: tamper-evident Ed25519 signature over the score card.
    Embedded in JSON output and surfaced as a verification command in HTML.
    ``None`` when the receipt signer was unavailable (degrade, never fail)."""

    classification: Classification = "confidential"
    """Capability #56: ``confidential`` (default, full findings + watermark
    + DLP meta tag) or ``public`` (strictly redacted summary suitable for
    sharing). Render pipelines pick the template, emit the file suffix,
    and choose the watermark + banner text from this single field."""

    waived_finding_count: int = 0
    """#18: count of findings suppressed by validated waivers + inline pragmas."""
    expired_waiver_count: int = 0
    """#18: count of expired waivers found in ``.spectra-waivers.yml`` —
    surfaced so the team rotates them before they're needed again."""

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


class CacheSecret(BaseModel, frozen=True):
    """Per-user 32-byte HMAC key bound to the cache adapter.

    Wraps the random secret returned by ``SecretBackend``. Construction
    enforces the 32-byte length contract — any other length is rejected
    so a misconfigured backend cannot silently weaken the MAC strength.
    The secret is never serialized to disk or surfaced in error messages;
    the wrapping entity exists to keep the use-case layer free of raw
    ``bytes`` plumbing.

    Attributes:
        value: 32 random bytes from ``secrets.token_bytes(32)``.
    """

    model_config = ConfigDict(frozen=True)

    value: bytes = Field(min_length=32, max_length=32)


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
        nonce: Per-batch random token (``secrets.token_urlsafe(16)``) used
            to fence analyzed file content in the specialist user prompt.
            ADR-011 §1: the nonce is unguessable per call so an attacker
            cannot pre-craft a closing fence inside their own source. The
            nonce is intentionally NOT part of any cache ``prompt_version``
            key so caching survives across runs.
    """

    batch_id: str
    file_paths: tuple[str, ...]
    file_hashes: tuple[str, ...]
    prompt_text: str
    nonce: str = Field(default_factory=lambda: secrets.token_urlsafe(16))


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


# ── Per-Agent Run Configuration ───────────────────────────────

ModelId = Literal[
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]
"""Anthropic model identifiers accepted by Spectra's --model flag."""

EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
"""Reasoning effort levels accepted by Spectra's --effort flag."""

# Effort levels reserved for Opus-tier models (Sonnet/Haiku reject these).
_OPUS_TIER_MODELS: frozenset[str] = frozenset({"claude-opus-4-7", "claude-opus-4-6"})
_OPUS_ONLY_EFFORTS: frozenset[str] = frozenset({"xhigh", "max"})


class AgentRunConfig(BaseModel, frozen=True):
    """Per-agent runtime configuration: model + effort + optional task budget.

    Frozen so the resolved configs can be shared across asyncio tasks
    without risk of mutation. The ``model``/``effort`` validation rejects
    unknown models, unknown effort levels, and the Opus-tier-only effort
    levels (``xhigh``, ``max``) when paired with a Sonnet or Haiku model.

    Attributes:
        model: Anthropic model id (one of ``ModelId``).
        effort: Reasoning effort level (one of ``EffortLevel``).
        task_budget_tokens: Adaptive-thinking budget in tokens; only
            populated for the CritiqueAgent today.
    """

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    model: ModelId
    effort: EffortLevel
    task_budget_tokens: int | None = None

    @model_validator(mode="after")
    def _validate_opus_tier_effort(self) -> AgentRunConfig:
        """Reject ``xhigh``/``max`` effort on non-Opus models."""
        if self.effort in _OPUS_ONLY_EFFORTS and self.model not in _OPUS_TIER_MODELS:
            msg = (
                f"effort={self.effort!r} is Opus-tier only — "
                f"model={self.model!r} does not support it. "
                f"Use one of: {sorted(_OPUS_TIER_MODELS)}."
            )
            raise ValueError(msg)
        return self


_DEFAULT_AGENT_CONFIGS: dict[AgentRole, AgentRunConfig] = {
    "meta_prompter": AgentRunConfig(model="claude-opus-4-7", effort="medium"),
    "architecture": AgentRunConfig(model="claude-opus-4-7", effort="xhigh"),
    "security": AgentRunConfig(model="claude-opus-4-7", effort="xhigh"),
    "quality": AgentRunConfig(model="claude-opus-4-7", effort="xhigh"),
    "documentation": AgentRunConfig(model="claude-opus-4-7", effort="xhigh"),
    "dependency": AgentRunConfig(model="claude-opus-4-7", effort="xhigh"),
    "performance": AgentRunConfig(model="claude-opus-4-7", effort="xhigh"),
    "critique": AgentRunConfig(
        model="claude-opus-4-7",
        effort="high",
        task_budget_tokens=80_000,
    ),
}
"""Hardcoded defaults — every agent's model + effort prior to PR #31."""


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


# ── Policy + Waiver (Capabilities #17, #18) ───────────────────

SeverityGate = Literal["critical", "high", "medium", "low", "none"]
"""Highest severity level allowed in a passing run.

``"none"`` disables the severity gate entirely (the default for
``EmptyPolicy``); ``"critical"`` fails the run on any critical finding;
``"low"`` fails on any non-info finding."""

ViolationKind = Literal[
    "severity_gate",
    "forbidden_rule_id",
    "min_score_overall",
    "required_dimension",
]
"""Why the policy gate rejected the run."""

_VALID_DIMENSIONS: frozenset[str] = frozenset(
    {
        "architecture",
        "security",
        "quality",
        "documentation",
        "maintainability",
        "performance",
    }
)


class Policy(BaseModel, frozen=True):
    """Org governance: severity gates, weight overrides, required dimensions.

    Loaded from ``.spectra-policy.yml`` at the repo root via
    ``YamlPolicyAdapter``. Empty file → ``EmptyPolicy()`` no-op.

    Attributes:
        version: Schema version (currently 1). Bumped on breaking change.
        severity_gate: Highest severity allowed; ``"none"`` disables the gate.
        dimension_overrides: Override default dimension weights. Keys must
            be one of the six known ``Dimension`` literals; values must be
            non-negative floats. Empty dict means use the defaults.
        min_score_overall: Optional floor for the ScoreCard's overall_score.
            ``None`` disables the check.
        forbidden_rule_ids: Tuple of ``rule_id`` values that fail the run on
            any single occurrence — independent of the severity gate.
        required_dimensions: Tuple of dimensions that must appear in
            ``score_card.dimensions``. A missing dimension fails the gate
            even if no findings exist (catches silent agent failures).
    """

    model_config = ConfigDict(frozen=True)

    version: int = 1
    severity_gate: SeverityGate = "none"
    dimension_overrides: dict[Dimension, float] = Field(default_factory=dict)
    min_score_overall: float | None = Field(default=None, ge=0.0, le=100.0)
    forbidden_rule_ids: tuple[str, ...] = ()
    required_dimensions: tuple[Dimension, ...] = ()

    @field_validator("dimension_overrides")
    @classmethod
    def _validate_overrides(cls, value: dict[str, float]) -> dict[str, float]:
        """Reject unknown dimensions or negative weights."""
        for dim, weight in value.items():
            if dim not in _VALID_DIMENSIONS:
                msg = f"unknown dimension in override: {dim!r}"
                raise ValueError(msg)
            if weight < 0:
                msg = f"dimension weight must be non-negative: {dim}={weight}"
                raise ValueError(msg)
        return value


def EmptyPolicy() -> Policy:  # noqa: N802 — Capital E intentional; reads as constructor
    """No-op policy used when ``.spectra-policy.yml`` is absent."""
    return Policy()


class Violation(BaseModel, frozen=True):
    """One reason the policy gate rejected the run.

    Attributes:
        kind: Which rule fired (severity_gate, forbidden_rule_id, …).
        message: Human-readable, ≤80 chars, brand-voice ✗-style.
        finding_id: Optional Finding.id when the violation cites a specific finding.
        rule_id: Optional rule_id for forbidden-rule violations.
        dimension: Optional dimension for required-dimension violations.
    """

    model_config = ConfigDict(frozen=True)

    kind: ViolationKind
    message: str
    finding_id: str | None = None
    rule_id: str | None = None
    dimension: Dimension | None = None


# ── Waivers (#18) ─────────────────────────────────────────────

_DEFAULT_WAIVER_TTL_DAYS: int = 180
_MIN_WAIVER_REASON_LEN: int = 10


def _default_waiver_expiry() -> datetime:
    """Return ``utcnow + 180d`` for the default waiver TTL."""
    return datetime.now(UTC) + timedelta(days=_DEFAULT_WAIVER_TTL_DAYS)


class Waiver(BaseModel, frozen=True):
    """One signed entry in ``.spectra-waivers.yml``.

    The ``finding_signature`` is a stable hash of
    ``blake2b(file_path || rule_id || severity)`` so waivers survive
    cosmetic finding renumbering. The ``signature`` field is an Ed25519
    signature over the canonical JSON of every other field; verified by
    the loader against the public keys in ``.spectra-approvers.yml``.

    Attributes:
        repo_signature: 32-hex blake2b of the repo's file tree at waiver time.
        finding_signature: blake2b(file_path||rule_id||severity) — 16 hex chars.
        reason: Human-readable justification (>=10 chars).
        waived_by: Approver display name (must match ``.spectra-approvers.yml``).
        waived_at: UTC datetime the waiver was signed.
        expires_at: UTC datetime the waiver becomes void (default +180d).
        signature: Hex-encoded Ed25519 signature (64 bytes → 128 hex chars).
    """

    model_config = ConfigDict(frozen=True)

    repo_signature: str
    finding_signature: str
    reason: str = Field(min_length=_MIN_WAIVER_REASON_LEN)
    waived_by: str
    waived_at: datetime
    expires_at: datetime = Field(default_factory=_default_waiver_expiry)
    signature: str = ""
    """Hex-encoded Ed25519 signature. Empty string allowed for the
    canonical-payload step that PRECEDES signing; loaders reject any
    waiver with an empty signature on disk."""

    def is_expired(self, now: datetime) -> bool:
        """Return True when ``now`` is at or past ``expires_at``."""
        return now >= self.expires_at


class Approver(BaseModel, frozen=True):
    """One entry in ``.spectra-approvers.yml`` — public keys for waiver verification.

    Attributes:
        name: Display name (matches ``Waiver.waived_by``).
        email: Contact email for audit.
        public_key: 32-byte Ed25519 public key, hex-encoded (64 chars).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    email: str
    public_key: str = Field(min_length=64, max_length=64)


def compute_finding_signature(
    file_path: str,
    rule_id: str,
    severity: str,
) -> str:
    """Stable blake2b hash used to identify a waivable finding.

    Defined in entities so both the use-case layer (filtering during
    pipeline) and the CLI seam (signing waivers) share one definition.

    Args:
        file_path: Repo-relative path of the finding's location.
        rule_id: Rule identifier; empty string for findings without one.
        severity: Severity literal value.

    Returns:
        16-character hex digest.
    """
    import hashlib

    h = hashlib.blake2b(digest_size=8)
    h.update(file_path.encode("utf-8"))
    h.update(b"\x00")
    h.update(rule_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(severity.encode("utf-8"))
    return h.hexdigest()
