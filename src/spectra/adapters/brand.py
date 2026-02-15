"""Shared brand constants and helper functions — Layer 3 adapter.

Centralizes Spectra's visual identity: hex colors, dimension labels,
and the verdict builder used by both the CLI presenter and the HTML
report renderer.
"""

from __future__ import annotations

from spectra.entities.enums import Dimension

# ── Brand Palette ──────────────────────────────────────────────
VIOLET = "#7C3AED"
"""Primary brand color (Spectrum Violet)."""

AMBER = "#F59E0B"
"""Accent color (Prism Amber)."""

RED = "#EF4444"
"""Signal color for critical/error states."""

GREEN = "#22C55E"
"""Signal color for success/passing states."""

CYAN = "#06B6D4"
"""Secondary accent for B-range grades."""

GRAY = "#6B7280"
"""Muted color for secondary text."""

# ── Dimension Display Labels ───────────────────────────────────
DIMENSION_LABELS: dict[Dimension, str] = {
    "architecture": "Architecture",
    "security": "Security",
    "quality": "Quality",
    "documentation": "Documentation",
    "maintainability": "Maintainability",
    "performance": "Performance",
}


def dim_label(dimension: Dimension) -> str:
    """Return the human-readable label for a dimension.

    Args:
        dimension: Analysis dimension key.

    Returns:
        Display-friendly label (e.g. ``"Architecture"``).
    """
    return DIMENSION_LABELS.get(dimension, dimension.capitalize())


def build_verdict(report: object) -> str:
    """Generate a one-line executive verdict from an analysis report.

    Args:
        report: An ``AnalysisReport`` (or any duck-typed equivalent).

    Returns:
        Verdict string like ``"Your codebase scores B+ (84/100)
        — strong security with documentation gaps"``, or empty
        string if no scorecard is available.
    """
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
    return f"Your codebase scores {grade} ({score:.0f}/100) \u2014 strong {top} with {bottom} gaps"
