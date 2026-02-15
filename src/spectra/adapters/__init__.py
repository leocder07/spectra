"""Layer 3 — CLI, progress, and presentation adapters."""

from spectra.adapters.analysis_presenter import (
    BAR_WIDTH,
    GRADE_COLORS,
    present_scorecard,
)
from spectra.adapters.brand import (
    AMBER,
    CYAN,
    DIMENSION_LABELS,
    GRAY,
    GREEN,
    RED,
    VIOLET,
    build_verdict,
    dim_label,
)
from spectra.adapters.cli_controller import (
    app,
    cli_entry,
    set_analyzer_factory,
)
from spectra.adapters.progress_reporter import (
    AGENT_DISPLAY_NAMES,
    SPECTRA_THEME,
    RichProgressReporter,
)

__all__ = [
    # brand colors
    "AMBER",
    "CYAN",
    "GRAY",
    "GREEN",
    "RED",
    "VIOLET",
    # brand helpers
    "DIMENSION_LABELS",
    "build_verdict",
    "dim_label",
    # presenter
    "BAR_WIDTH",
    "GRADE_COLORS",
    "present_scorecard",
    # CLI
    "app",
    "cli_entry",
    "set_analyzer_factory",
    # progress reporter
    "AGENT_DISPLAY_NAMES",
    "RichProgressReporter",
    "SPECTRA_THEME",
]
