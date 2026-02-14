"""Pydantic frozen models for the Spectra domain."""

from __future__ import annotations

from pydantic import BaseModel, Field

from spectra.entities.enums import (
    AgentRole,
    Dimension,
    Grade,
    PipelineState,
    Severity,
)

# ── Named Constants ────────────────────────────────────────────
PASSING_SCORE: float = 60.0
EXCELLENT_SCORE: float = 90.0
DEFAULT_DIMENSION_SCORE: float = 85.0
MIN_CONFIDENCE: float = 0.7


class FileLocation(BaseModel, frozen=True):
    """Value object for a source code location."""

    file_path: str
    line_start: int
    line_end: int | None = None


class Finding(BaseModel, frozen=True):
    """Core domain entity — immutable, dedupable by location + dimension."""

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

    def __hash__(self) -> int:
        return hash((self.location.file_path, self.location.line_start, self.dimension))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Finding):
            return False
        return (
            self.location.file_path == other.location.file_path
            and self.location.line_start == other.location.line_start
            and self.dimension == other.dimension
        )

    def is_critical(self) -> bool:
        return self.severity == "critical"

    def is_actionable(self) -> bool:
        return self.severity in ("critical", "high", "medium")


class DimensionScore(BaseModel, frozen=True):
    """Score for a single analysis dimension."""

    dimension: Dimension
    score: float = Field(ge=0.0, le=100.0)
    grade: Grade
    findings_count: int
    weight: float

    def is_passing(self) -> bool:
        return self.score >= PASSING_SCORE

    def is_excellent(self) -> bool:
        return self.score >= EXCELLENT_SCORE


class ScoreCard(BaseModel, frozen=True):
    """Aggregate scores across all dimensions."""

    overall_score: float = Field(ge=0.0, le=100.0)
    overall_grade: Grade
    dimensions: tuple[DimensionScore, ...]
    total_findings: int

    def worst_dimension(self) -> DimensionScore | None:
        if not self.dimensions:
            return None
        return min(self.dimensions, key=lambda d: d.score)

    def best_dimension(self) -> DimensionScore | None:
        if not self.dimensions:
            return None
        return max(self.dimensions, key=lambda d: d.score)

    def grade_for(self, dimension: Dimension) -> Grade | None:
        for d in self.dimensions:
            if d.dimension == dimension:
                return d.grade
        return None


class AgentOutput(BaseModel, frozen=True):
    """Validated output from a single agent run."""

    agent_role: AgentRole
    findings: tuple[Finding, ...]
    tokens_used: int
    duration_seconds: float
    raw_response: str


class AgentContext(BaseModel, frozen=True):
    """Input context passed to an agent for analysis."""

    agent_role: AgentRole
    system_prompt: str
    user_prompt: str
    model: str
    max_tokens: int
    extended_thinking: bool = False


class AnalysisReport(BaseModel, frozen=True):
    """Final report combining all agent results."""

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

    def critical_finding_count(self) -> int:
        return sum(1 for f in self.findings if f.is_critical())


class Codebase(BaseModel, frozen=True):
    """Representation of a cloned repository."""

    repo_url: str
    repo_name: str
    local_path: str
    file_tree: tuple[str, ...]

    def file_count(self) -> int:
        return len(self.file_tree)


class AnalysisRequest(BaseModel, frozen=True):
    """User-initiated analysis request."""

    repo_url: str
    quick: bool = False
    output_format: str = "rich"


class TokenBudget(BaseModel, frozen=True):
    """Token allocation across pipeline stages."""

    total: int = 800_000
    meta_prompter: int = 5_000
    specialists_pool: int = 500_000
    critique_reserved: int = 200_000
    buffer: int = 95_000

    def has_remaining(self, used: int) -> bool:
        return used < self.total

    def remaining(self, used: int) -> int:
        return max(0, self.total - used)


def score_to_grade(score: float) -> Grade:
    """Map a numeric score (0-100) to a letter grade."""
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 87:
        return "A-"
    if score >= 83:
        return "B+"
    if score >= 80:
        return "B"
    if score >= 77:
        return "B-"
    if score >= 73:
        return "C+"
    if score >= 70:
        return "C"
    if score >= 67:
        return "C-"
    if score >= 63:
        return "D+"
    if score >= 60:
        return "D"
    if score >= 57:
        return "D-"
    return "F"
