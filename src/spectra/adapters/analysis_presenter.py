"""Rich Console ScoreCard presenter — Layer 3 adapter.

Renders the ScoreCard as a terminal panel with colored grade badges,
block-character score bars, and dimension breakdown using the Rich
library.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from spectra.adapters.brand import (
    AMBER,
    CYAN,
    DIMENSION_LABELS,
    GRAY,
    GREEN,
    RED,
    VIOLET,
    build_verdict,
)
from spectra.entities.enums import Grade
from spectra.entities.models import DimensionScore

GRADE_COLORS: dict[str, str] = {  # Maps letter grade to Rich hex color
    "A+": GREEN,
    "A": GREEN,
    "A-": GREEN,
    "B+": CYAN,
    "B": CYAN,
    "B-": CYAN,
    "C+": AMBER,
    "C": AMBER,
    "C-": AMBER,
    "D+": RED,
    "D": RED,
    "D-": RED,
    "F": RED,
}

BAR_WIDTH = 10


def _score_bar(score: float) -> str:
    """Render a 0-100 score as a 10-character block bar.

    Args:
        score: Numeric score (0-100).

    Returns:
        String of filled (``█``) and empty (``░``) blocks.
    """
    filled = round(score / BAR_WIDTH)
    empty = BAR_WIDTH - filled
    return "█" * filled + "░" * empty


def _grade_text(grade: Grade) -> Text:
    """Return a color-coded Rich Text for the given grade.

    Args:
        grade: Letter grade (A+ through F).

    Returns:
        Rich ``Text`` object with bold grade-appropriate color.
    """
    color = GRADE_COLORS.get(grade, GRAY)
    return Text(grade, style=f"bold {color}")


def _build_header_grid(
    repo_name: str,
    overall_grade: Grade,
    overall_score: float,
) -> Table:
    """Build the scorecard header grid with repo name and overall grade.

    Args:
        repo_name: Short repository name.
        overall_grade: Overall letter grade.
        overall_score: Overall numeric score (0-100).

    Returns:
        Rich ``Table`` grid for the panel header.
    """
    grade_color = GRADE_COLORS.get(overall_grade, GRAY)
    header = Table.grid(padding=(0, 1))
    header.add_column(justify="left")
    header.add_row(Text("SPECTRA SCORECARD", style=f"bold {VIOLET}"))
    header.add_row(Text(f"repo: {repo_name}", style=GRAY))
    header.add_row(
        Text.assemble(
            "Overall: ",
            Text(
                f"{overall_grade} ({overall_score:.0f}/100)",
                style=f"bold {grade_color}",
            ),
        ),
    )
    return header


def _build_dimensions_table(dimensions: tuple[DimensionScore, ...]) -> Table:
    """Build the dimension scores table with bars and grades.

    Args:
        dimensions: Tuple of ``DimensionScore`` objects.

    Returns:
        Rich ``Table`` with one row per dimension.
    """
    table = Table(
        show_header=False,
        show_edge=False,
        pad_edge=False,
        box=None,
        padding=(0, 1),
    )
    table.add_column("Dimension", min_width=16)
    table.add_column("Bar", min_width=12)
    table.add_column("Score", justify="right", min_width=4)
    table.add_column("Grade", min_width=3)
    for dim in dimensions:
        label = DIMENSION_LABELS.get(dim.dimension, dim.dimension)
        table.add_row(
            Text(label, style="bold"),
            Text(_score_bar(dim.score), style=VIOLET),
            Text(f"{dim.score:.0f}", style="bold"),
            _grade_text(dim.grade),
        )
    return table


def _build_summary_text(report: object) -> Text:
    """Build the summary footer line with finding count, timing, and cost.

    Args:
        report: An ``AnalysisReport`` (or duck-typed equivalent).

    Returns:
        Rich ``Text`` with stats joined by ``·`` separators.
    """
    total = getattr(report, "total_findings", None)
    if total is None:
        total = len(getattr(report, "findings", ()))
    critical = sum(1 for f in getattr(report, "findings", ()) if getattr(f, "severity", "") == "critical")
    duration = getattr(report, "analysis_duration_seconds", 0.0)
    cost = getattr(report, "total_cost_usd", 0.0)
    saved = getattr(report, "cost_saved_usd", 0.0)
    parts = [
        f"{total} findings",
        f"{critical} critical",
        f"{duration:.0f}s",
        f"${cost:.2f}",
    ]
    # ADR-024: surface prompt-cache savings on the summary line when
    # the run actually saved money (>= $0.01 — sub-cent savings are noise).
    if saved >= 0.01:
        parts.append(f"saved ${saved:.2f} via prompt cache")
    return Text(" · ".join(parts), style=GRAY)


def present_scorecard(report: object, console: Console) -> None:
    """Render the ScoreCard as a Rich Panel with dimension breakdown.

    Accepts an ``AnalysisReport`` (or any duck-typed equivalent)
    and prints a formatted ScoreCard panel to the console with
    verdict, dimension bars, grades, and summary stats.

    Args:
        report: Analysis report with a ``score_card`` attribute.
        console: Rich Console instance for output.
    """
    score_card = getattr(report, "score_card", None)
    if score_card is None:
        console.print(f"[{RED}]✗[/] No scorecard data available")
        return

    verdict = build_verdict(report)
    if verdict:
        console.print(f"\n[bold {VIOLET}]\u25b8[/] {verdict}\n")

    repo_name = getattr(report, "repo_name", "unknown")
    header = _build_header_grid(
        repo_name,
        score_card.overall_grade,
        score_card.overall_score,
    )
    dim_table = _build_dimensions_table(score_card.dimensions)
    summary = _build_summary_text(report)

    body = Table.grid()
    body.add_row(header)
    body.add_row(Text(""))
    body.add_row(dim_table)
    body.add_row(Text(""))
    body.add_row(summary)

    console.print(Panel(body, border_style=VIOLET, padding=(1, 2)))

    if getattr(report, "is_degraded", False):
        degraded = getattr(report, "degraded_dimensions", ())
        dims = ", ".join(str(d) for d in degraded)
        console.print(f"[{AMBER}]\u26a0[/] Degraded analysis \u2014 missing dimensions: {dims}")
