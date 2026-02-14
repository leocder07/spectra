"""Report rendering adapter — implements ReportPort using Jinja2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import jinja2

from spectra.adapters.brand import build_verdict, dim_label
from spectra.entities.enums import Dimension, Grade
from spectra.entities.models import AnalysisReport, Finding

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "templates"

_DIMENSIONS_ORDER: tuple[Dimension, ...] = (
    "architecture",
    "security",
    "quality",
    "documentation",
    "maintainability",
    "performance",
)

_GRADE_CLASS: dict[str, str] = {
    "A+": "grade-a", "A": "grade-a", "A-": "grade-a",
    "B+": "grade-b", "B": "grade-b", "B-": "grade-b",
    "C+": "grade-c", "C": "grade-c", "C-": "grade-c",
    "D+": "grade-d", "D": "grade-d", "D-": "grade-d",
    "F": "grade-f",
}

_BAR_CLASS: dict[str, str] = {
    "A+": "bar-a", "A": "bar-a", "A-": "bar-a",
    "B+": "bar-b", "B": "bar-b", "B-": "bar-b",
    "C+": "bar-c", "C": "bar-c", "C-": "bar-c",
    "D+": "bar-d", "D": "bar-d", "D-": "bar-d",
    "F": "bar-f",
}

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


def _grade_class(grade: Grade) -> str:
    return _GRADE_CLASS.get(grade, "grade-f")


def _bar_class(grade: Grade) -> str:
    return _BAR_CLASS.get(grade, "bar-f")


def _critical_count(findings: tuple[Finding, ...]) -> int:
    return sum(1 for f in findings if f.severity == "critical")


def _sort_by_severity(findings: list[Finding]) -> list[Finding]:
    """Sort findings: critical → high → medium → low → info."""
    return sorted(
        findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 5),
    )


def _build_executive_summary(report: AnalysisReport) -> dict[str, object]:
    """Compute executive summary data for the HTML template."""
    dims = sorted(
        report.score_card.dimensions,
        key=lambda d: d.score,
        reverse=True,
    )
    bottom = dims[-3:] if len(dims) >= 3 else dims
    return {
        "verdict": build_verdict(report),
        "strengths": dims[:3],
        "concerns": list(reversed(bottom)),
        "critical_count": _critical_count(report.findings),
        "total_findings": len(report.findings),
        "agents_count": len(report.agents_used),
        "duration": report.analysis_duration_seconds,
    }


class ReportAdapter:
    """Renders analysis reports to HTML via Jinja2."""

    def __init__(self, template_dir: Path = _TEMPLATE_DIR) -> None:
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=True,
        )
        self._env.globals["_grade_class"] = _grade_class
        self._env.globals["_bar_class"] = _bar_class
        self._env.globals["_dim_label"] = dim_label
        self._env.globals["_critical_count"] = _critical_count
        self._env.globals["_sort_by_severity"] = _sort_by_severity
        self._env.globals["dimensions_order"] = _DIMENSIONS_ORDER

    def render(self, report: AnalysisReport, output_path: str) -> str:
        template = self._env.get_template("report.html.j2")
        has_mermaid = any(
            "```mermaid" in f.description for f in report.findings
        )
        html = template.render(
            report=report,
            summary=_build_executive_summary(report),
            has_mermaid=has_mermaid,
            generated_at=datetime.now(UTC).strftime(
                "%Y-%m-%d %H:%M UTC"
            ),
        )
        Path(output_path).write_text(html, encoding="utf-8")
        return output_path
