"""Report rendering adapter — implements ReportPort using Jinja2."""

from __future__ import annotations

import re
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

_SPECTRUM_COLOR: dict[str, str] = {
    "grade-a": "#22C55E",
    "grade-b": "#06B6D4",
    "grade-c": "#F59E0B",
    "grade-d": "#EF4444",
    "grade-f": "#EF4444",
}

_BADGE_COLOR: dict[str, str] = {
    "A": "22C55E",
    "B": "06B6D4",
    "C": "F59E0B",
    "D": "EF4444",
    "F": "EF4444",
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


def _severity_distribution(
    findings: tuple[Finding, ...],
) -> dict[str, int]:
    """Count findings per severity level."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    return counts


def _build_spectrum_segments(
    report: AnalysisReport,
) -> list[dict[str, object]]:
    """Build ordered spectrum bar segments from dimension scores."""
    segments: list[dict[str, object]] = []
    dim_lookup = {d.dimension: d for d in report.score_card.dimensions}
    for dim in _DIMENSIONS_ORDER:
        ds = dim_lookup.get(dim)
        if ds is None:
            continue
        gc = _grade_class(ds.grade)
        segments.append({
            "label": dim_label(dim),
            "score": int(ds.score),
            "grade": ds.grade,
            "weight_pct": ds.weight * 100,
            "color": _SPECTRUM_COLOR.get(gc, "#EF4444"),
        })
    return segments


def _top_findings(findings: tuple[Finding, ...]) -> list[Finding]:
    """Return the top 5 actionable findings by severity."""
    sorted_all = sorted(
        findings,
        key=lambda f: _SEVERITY_ORDER.get(f.severity, 5),
    )
    return sorted_all[:5]


def _total_hours(findings: tuple[Finding, ...]) -> float:
    """Sum estimated_hours across all findings."""
    return round(sum(f.estimated_hours for f in findings), 1)


def _dimension_hours(
    findings: tuple[Finding, ...],
) -> dict[Dimension, float]:
    """Sum estimated hours per dimension."""
    hours: dict[Dimension, float] = {}
    for f in findings:
        hours[f.dimension] = hours.get(f.dimension, 0.0) + f.estimated_hours
    return {k: round(v, 1) for k, v in hours.items()}


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
        "severity_dist": _severity_distribution(report.findings),
        "total_tech_debt_hours": _total_hours(report.findings),
        "dimension_hours": _dimension_hours(report.findings),
    }


_DEV_RATE_USD = 150  # Average hourly dev rate for cost estimation

# OWASP Top 10 (2021) identifiers
_OWASP_CATEGORIES: dict[str, str] = {
    "A01": "A01:2021 Broken Access Control",
    "A02": "A02:2021 Cryptographic Failures",
    "A03": "A03:2021 Injection",
    "A04": "A04:2021 Insecure Design",
    "A05": "A05:2021 Security Misconfiguration",
    "A06": "A06:2021 Vulnerable and Outdated Components",
    "A07": "A07:2021 Identification and Auth Failures",
    "A08": "A08:2021 Software and Data Integrity Failures",
    "A09": "A09:2021 Security Logging and Monitoring Failures",
    "A10": "A10:2021 Server-Side Request Forgery",
}

_OWASP_RE = re.compile(r"A0[1-9]|A10", re.IGNORECASE)
_CWE_RE = re.compile(r"CWE-(\d+)")


def _tech_debt_summary(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Aggregate tech debt data for the report template."""
    total_hours = sum(f.estimated_hours for f in findings)
    by_dimension: dict[str, float] = {}
    by_severity: dict[str, float] = {}
    for f in findings:
        by_dimension[f.dimension] = (
            by_dimension.get(f.dimension, 0.0) + f.estimated_hours
        )
        by_severity[f.severity] = (
            by_severity.get(f.severity, 0.0) + f.estimated_hours
        )
    return {
        "total_hours": round(total_hours, 1),
        "cost_usd": round(total_hours * _DEV_RATE_USD),
        "by_dimension": by_dimension,
        "by_severity": by_severity,
    }


def _dd_compliance_mapping(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Extract OWASP and CWE references from finding descriptions."""
    owasp_found: set[str] = set()
    cwes_found: set[str] = set()
    for f in findings:
        text = f"{f.description} {f.recommendation}"
        owasp_found.update(_OWASP_RE.findall(text))
        cwes_found.update(_CWE_RE.findall(text))

    owasp_coverage: list[dict[str, str | bool]] = []
    for code, label in _OWASP_CATEGORIES.items():
        covered = code.upper() in {o.upper() for o in owasp_found}
        owasp_coverage.append({
            "code": code,
            "label": label,
            "covered": covered,
        })

    return {
        "owasp_coverage": owasp_coverage,
        "owasp_covered_count": sum(
            1 for o in owasp_coverage if o["covered"]
        ),
        "owasp_total": len(_OWASP_CATEGORIES),
        "cwes": sorted(cwes_found, key=lambda x: int(x)),
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
            spectrum_segments=_build_spectrum_segments(report),
            top_findings=_top_findings(report.findings),
            tech_debt=_tech_debt_summary(report.findings),
            dd_compliance=_dd_compliance_mapping(report.findings),
            badge_svg=self.render_badge(report),
            has_mermaid=has_mermaid,
            generated_at=datetime.now(UTC).strftime(
                "%Y-%m-%d %H:%M UTC"
            ),
        )
        Path(output_path).write_text(html, encoding="utf-8")
        return output_path

    def render_badge(self, report: AnalysisReport) -> str:
        """Render a shields.io-style SVG badge for the overall grade."""
        grade = report.score_card.overall_grade
        score = int(report.score_card.overall_score)
        grade_color = _BADGE_COLOR.get(grade[0], "6B7280")
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="160"'
            f' height="20">'
            f'<rect width="80" height="20" rx="3" fill="#555"/>'
            f'<rect x="80" width="80" height="20" rx="3" fill="'
            f'#{grade_color}"/>'
            f'<text x="40" y="14" fill="#fff" text-anchor="middle"'
            f' font-size="11" font-family="Verdana">Spectra</text>'
            f'<text x="120" y="14" fill="#fff" text-anchor="middle"'
            f' font-size="11" font-family="Verdana">'
            f'{grade} {score}/100</text></svg>'
        )
