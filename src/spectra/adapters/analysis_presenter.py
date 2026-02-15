"""Rich Console ScoreCard presenter — Layer 3 adapter."""

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

GRADE_COLORS: dict[str, str] = {
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
    """Render a score as a block-character bar."""
    filled = round(score / BAR_WIDTH)
    empty = BAR_WIDTH - filled
    return "█" * filled + "░" * empty


def _grade_text(grade: Grade) -> Text:
    """Color-coded grade text."""
    color = GRADE_COLORS.get(grade, GRAY)
    return Text(grade, style=f"bold {color}")


def _build_header_grid(
    repo_name: str,
    overall_grade: Grade,
    overall_score: float,
) -> Table:
    """Build the scorecard header with repo name and overall grade."""
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


def _build_dimensions_table(dimensions: tuple[object, ...]) -> Table:
    """Build the dimension scores table."""
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
    """Build the summary footer line with stats."""
    total = getattr(report, "total_findings", None)
    if total is None:
        total = len(getattr(report, "findings", ()))
    critical = sum(1 for f in getattr(report, "findings", ()) if getattr(f, "severity", "") == "critical")
    duration = getattr(report, "analysis_duration_seconds", 0.0)
    cost = getattr(report, "total_cost_usd", 0.0)
    parts = [
        f"{total} findings",
        f"{critical} critical",
        f"{duration:.0f}s",
        f"${cost:.2f}",
    ]
    return Text(" · ".join(parts), style=GRAY)


def present_scorecard(report: object, console: Console) -> None:
    """Render the ScoreCard as a Rich Panel + Table.

    Accepts an AnalysisReport (or any object matching its shape)
    and prints a formatted ScoreCard to the console.
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
