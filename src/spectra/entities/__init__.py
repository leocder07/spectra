"""Spectra domain entities — Layer 1 (zero spectra-internal imports)."""

from spectra.entities.enums import (
    AgentRole,
    Dimension,
    Grade,
    PipelineState,
    Severity,
)
from spectra.entities.errors import ERRORS, Result, SpectraError
from spectra.entities.models import (
    DEFAULT_DIMENSION_SCORE,
    EXCELLENT_SCORE,
    MIN_CONFIDENCE,
    PASSING_SCORE,
    AgentContext,
    AgentOutput,
    AnalysisReport,
    AnalysisRequest,
    Codebase,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    TokenBudget,
    score_to_grade,
)

__all__ = [
    # enums
    "AgentRole",
    "Dimension",
    "Grade",
    "PipelineState",
    "Severity",
    # errors
    "ERRORS",
    "Result",
    "SpectraError",
    # constants
    "DEFAULT_DIMENSION_SCORE",
    "EXCELLENT_SCORE",
    "MIN_CONFIDENCE",
    "PASSING_SCORE",
    # models
    "AgentContext",
    "AgentOutput",
    "AnalysisReport",
    "AnalysisRequest",
    "Codebase",
    "DimensionScore",
    "FileLocation",
    "Finding",
    "ScoreCard",
    "TokenBudget",
    "score_to_grade",
]
