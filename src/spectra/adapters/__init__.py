"""Layer 3 — CLI, progress, and presentation adapters."""

from spectra.adapters.analysis_presenter import present_scorecard
from spectra.adapters.cli_controller import (
    app,
    cli_entry,
    set_analyzer_factory,
)
from spectra.adapters.progress_reporter import RichProgressReporter

__all__ = [
    "RichProgressReporter",
    "app",
    "cli_entry",
    "present_scorecard",
    "set_analyzer_factory",
]
