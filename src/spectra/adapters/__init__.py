"""Adapter layer — Layer 3 of Clean Architecture (imports from entities/ and use_cases/).

This layer bridges the use-case layer with the outside world. Adapters handle
user interaction (CLI), terminal display (Rich), and brand identity without
containing any business logic.

Key modules:

- **cli_controller.py** — Typer CLI application defining ``spectra analyze``
  commands. The CLI does NOT wire dependencies — the composition root
  (``infrastructure/main.py``) injects the analyzer callable via
  ``set_analyzer_factory()`` before the CLI runs.
- **progress_reporter.py** — ``RichProgressReporter`` implementing the
  ``ProgressObserver`` protocol with Rich Progress bars, panels, and
  box-drawing characters for a premium terminal aesthetic.
- **analysis_presenter.py** — ``present_scorecard()`` renders the ScoreCard
  as a Rich Panel with colored grade badges and block-character score bars.
- **brand.py** — Shared brand constants (hex colors, dimension labels) and
  the ``build_verdict()`` helper used by both CLI and HTML report renderers.

**Dependency rule**: This layer imports from ``entities/`` and ``use_cases/``
only. It never imports from ``infrastructure/``.
"""

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
    # progress reporter
    "AGENT_DISPLAY_NAMES",
    # brand colors
    "AMBER",
    # presenter
    "BAR_WIDTH",
    "CYAN",
    # brand helpers
    "DIMENSION_LABELS",
    "GRADE_COLORS",
    "GRAY",
    "GREEN",
    "RED",
    "SPECTRA_THEME",
    "VIOLET",
    "RichProgressReporter",
    # CLI
    "app",
    "build_verdict",
    "cli_entry",
    "dim_label",
    "present_scorecard",
    "set_analyzer_factory",
]
