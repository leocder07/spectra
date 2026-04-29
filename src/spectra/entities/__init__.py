"""Spectra domain entities — Layer 1 of Clean Architecture (zero spectra-internal imports).

This is the innermost layer of Spectra's Clean Architecture. It contains:

- **Literal type aliases** (``enums.py``): ``Severity``, ``Dimension``, ``Grade``,
  ``AgentRole``, and ``PipelineState`` — using ``Literal`` for JSON-safe enums.
- **Error hierarchy** (``errors.py``): ``SpectraError`` descriptors with retry
  metadata (SPEC-001 through SPEC-009), plus ``AgentError``, ``GitError``, and
  ``SpectraRetryError`` exception classes.
- **Frozen Pydantic models** (``models.py``): All domain objects are immutable
  (``frozen=True``). Key models include ``Finding`` (dedupable by file/line/dim),
  ``ScoreCard``, ``AnalysisReport``, ``Codebase``, and ``TokenBudget``.

**Dependency rule**: This layer imports NOTHING from the ``spectra`` package.
All other layers depend on entities, but entities depend on no one.

All public symbols are re-exported here via ``__all__`` for convenient access
from outer layers (e.g. ``from spectra.entities import Finding, ScoreCard``).
"""

from spectra.entities.enums import (
    AgentRole,
    Dimension,
    Grade,
    PipelineState,
    SchemaVersion,
    Severity,
)
from spectra.entities.errors import (
    ERRORS,
    AgentError,
    GitError,
    SpectraError,
    SpectraRetryError,
    strip_code_fence,
)
from spectra.entities.models import (
    DEFAULT_DIMENSION_SCORE,
    EXCELLENT_SCORE,
    MIN_CONFIDENCE,
    PASSING_SCORE,
    AgentContext,
    AgentOutput,
    AnalysisReport,
    AnalysisRequest,
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

__all__ = [
    # constants
    "DEFAULT_DIMENSION_SCORE",
    # errors
    "ERRORS",
    "EXCELLENT_SCORE",
    "MIN_CONFIDENCE",
    "PASSING_SCORE",
    # models
    "AgentContext",
    "AgentError",
    "AgentOutput",
    # enums
    "AgentRole",
    "AnalysisReport",
    "AnalysisRequest",
    "CacheEntry",
    "CacheStats",
    "Codebase",
    "Dimension",
    "DimensionScore",
    "FileLocation",
    "Finding",
    "GitError",
    "Grade",
    "PipelineState",
    "RepoCacheKey",
    "SchemaVersion",
    "ScoreCard",
    "Severity",
    "SpectraError",
    "SpectraRetryError",
    "TokenBudget",
    "estimate_cost",
    "score_to_grade",
    "strip_code_fence",
]
