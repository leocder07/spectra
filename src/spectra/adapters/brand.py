"""Shared brand constants — Layer 3 adapter."""

from __future__ import annotations

from spectra.entities.enums import Dimension

# Brand colors
VIOLET = "#7C3AED"
AMBER = "#F59E0B"
RED = "#EF4444"
GREEN = "#22C55E"
CYAN = "#06B6D4"
GRAY = "#6B7280"

# Display labels for analysis dimensions
DIMENSION_LABELS: dict[Dimension, str] = {
    "architecture": "Architecture",
    "security": "Security",
    "quality": "Quality",
    "documentation": "Documentation",
    "maintainability": "Maintainability",
    "performance": "Performance",
}


def dim_label(dimension: Dimension) -> str:
    """Human-readable label for a dimension."""
    return DIMENSION_LABELS.get(dimension, dimension.capitalize())


def build_verdict(report: object) -> str:
    """Generate a one-line executive verdict from an analysis report."""
    sc = getattr(report, "score_card", None)
    if sc is None:
        return ""
    grade = sc.overall_grade
    score = sc.overall_score
    dims = sorted(sc.dimensions, key=lambda d: d.score, reverse=True)
    if not dims:
        return f"Your codebase scores {grade} ({score:.0f}/100)"
    top = dim_label(dims[0].dimension).lower()
    bottom = dim_label(dims[-1].dimension).lower()
    if top == bottom:
        return f"Your codebase scores {grade} ({score:.0f}/100)"
    return (
        f"Your codebase scores {grade} ({score:.0f}/100)"
        f" \u2014 strong {top} with {bottom} gaps"
    )
