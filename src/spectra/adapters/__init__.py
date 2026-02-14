"""Layer 3 — CLI, progress, and presentation adapters."""

from spectra.adapters.analysis_presenter import present_scorecard
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
from spectra.adapters.progress_reporter import RichProgressReporter

__all__ = [
    "AMBER",
    "CYAN",
    "DIMENSION_LABELS",
    "GRAY",
    "GREEN",
    "RED",
    "RichProgressReporter",
    "VIOLET",
    "app",
    "build_verdict",
    "cli_entry",
    "dim_label",
    "present_scorecard",
    "set_analyzer_factory",
]
