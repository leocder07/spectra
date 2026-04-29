"""Markdown-safe PR comment renderer — Layer 3 adapter.

Composes the body of the GitHub PR comment posted by the Spectra Action
from an ``AnalysisReport``. Two security guarantees protect the host
repository from a malicious finding (Red Team T3):

1. **Field allowlist.** Only six finding fields ever surface in the
   rendered markdown — ``title``, ``severity``, ``dimension``,
   ``file_path``, ``line_start``/``line_end``, and a truncated
   ``summary`` derived from ``description``. Free-form prose fields
   (``recommendation``, ``code_snippet``) are dropped wholesale; the
   model cannot ship arbitrary text into the comment via those fields.

2. **Sanitization.** Every allowlisted text field is HTML-escaped via
   ``html.escape`` so script/img injection becomes inert. Backticks in
   titles are replaced with U+02CB (modifier grave) so a finding
   cannot break out of an enclosing codeblock fence. File paths are
   rendered inside an inline code span with ``[``, ``]``, ``(``, and
   ``)`` backslash-escaped so they cannot terminate the span and
   inject a fake link. Summaries containing markdown image syntax
   (``![..](..)``) or autolinks (``<http..>``) are dropped entirely
   so attacker-controlled URLs never reach a reviewer's browser.

The renderer is a pure function — no I/O, no globals — and produces a
deterministic ``str`` for a given ``AnalysisReport``. It is invoked
from the ``spectra render pr-comment`` CLI subcommand, which writes
the output to stdout for the GitHub Action to forward to ``gh pr
comment``.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Final

from spectra import __version__
from spectra.adapters.brand import dim_label
from spectra.entities.models import AnalysisReport, DimensionScore, Finding

if TYPE_CHECKING:
    from collections.abc import Iterable

# ── Public constants ─────────────────────────────────────────

PR_COMMENT_SENTINEL: Final[str] = "<!-- SPECTRA -->"
"""Idempotency marker — the GitHub Action looks for this to update the
existing comment instead of posting a new one on every re-run."""

SUMMARY_MAX_CHARS: Final[int] = 200
"""Maximum length of a finding's rendered summary before truncation."""

TOP_FINDINGS_LIMIT: Final[int] = 20
"""Maximum number of findings rendered in the comment body. Anything
beyond this surfaces as a ``+N more`` count so the comment stays
readable on a phone."""

# ── Internal sanitization helpers ────────────────────────────

# U+02CB MODIFIER LETTER GRAVE ACCENT — visually a backtick but not a
# markdown metacharacter, so it cannot fence a codeblock.
# (RUF001 suppressed: the visual-similarity to U+0060 GRAVE ACCENT is the
# entire point — we want a glyph that looks like a backtick to the reader
# but is inert to markdown parsers.)
_BACKTICK_REPLACEMENT: Final[str] = "ˋ"  # noqa: RUF001

# Severity ordering — critical and high come first so the top-N slice
# always favors the most actionable findings.
_SEVERITY_RANK: Final[dict[str, int]] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

# Markdown image: ``![alt](url)`` — a finding with this in its summary
# could exfil reviewer telemetry to an attacker-controlled host.
_IMAGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# Autolinks: ``<https://...>`` — same exfil risk via referrer/click.
_AUTOLINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"<https?://[^>]+>", re.IGNORECASE)


def _sanitize_title(title: str) -> str:
    """Make a finding title safe to embed in the comment body.

    HTML-escapes all metacharacters and replaces backticks with a
    visually identical but inert codepoint so a malicious title cannot
    break an enclosing codeblock fence.
    """
    cleaned = title.replace("`", _BACKTICK_REPLACEMENT)
    return html.escape(cleaned, quote=False)


def _sanitize_summary(description: str) -> str | None:
    """Return a safe truncated summary, or ``None`` to drop the field.

    Returns ``None`` when the description contains markdown image
    syntax or autolinks — the entire summary is dropped rather than
    sanitized so attacker URLs never appear, even quoted.
    """
    if _IMAGE_PATTERN.search(description) or _AUTOLINK_PATTERN.search(description):
        return None
    truncated = description if len(description) <= SUMMARY_MAX_CHARS else description[:SUMMARY_MAX_CHARS] + "…"
    return html.escape(truncated, quote=False)


def _sanitize_file_path(path: str) -> str:
    """Backslash-escape link metacharacters so the path is safe inside
    an inline code span.
    """
    return path.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]").replace("(", r"\(").replace(")", r"\)")


def _format_location(finding: Finding) -> str:
    """Render the finding location as ``path:line`` inside a code span."""
    loc = finding.location
    safe_path = _sanitize_file_path(loc.file_path)
    if loc.line_end and loc.line_end != loc.line_start:
        return f"`{safe_path}:{loc.line_start}-{loc.line_end}`"
    return f"`{safe_path}:{loc.line_start}`"


def _sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Stable-sort findings by severity rank then by file then by line.

    Stability matters: identical inputs MUST produce identical output
    so the GitHub Action's idempotent-update logic does not flap.
    """
    return sorted(
        findings,
        key=lambda f: (
            _SEVERITY_RANK.get(f.severity, 99),
            f.location.file_path,
            f.location.line_start,
        ),
    )


# ── Block builders ───────────────────────────────────────────


def _render_header(report: AnalysisReport) -> list[str]:
    """Sentinel + title block — first lines of the comment."""
    return [
        PR_COMMENT_SENTINEL,
        "## Spectra Analysis",
        "",
        f"**Grade:** `{report.score_card.overall_grade}` "
        f"({report.score_card.overall_score:.1f}/100) · "
        f"**Findings:** {report.score_card.total_findings}",
        "",
    ]


def _render_dimension_table(dimensions: tuple[DimensionScore, ...]) -> list[str]:
    """Markdown table of per-dimension scores."""
    if not dimensions:
        return []
    rows = ["| Dimension | Score | Grade |", "| --- | --- | --- |"]
    rows.extend(f"| {dim_label(d.dimension)} | {d.score:.1f} | `{d.grade}` |" for d in dimensions)
    rows.append("")
    return rows


def _render_finding(finding: Finding) -> list[str]:
    """Render a single finding as a bullet list entry."""
    sev = finding.severity.upper()
    title = _sanitize_title(finding.title)
    location = _format_location(finding)
    lines = [f"- **[{sev}]** {title} — {location} _(`{finding.dimension}`)_"]
    summary = _sanitize_summary(finding.description)
    if summary:
        lines.append(f"  - {summary}")
    return lines


def _render_findings_block(report: AnalysisReport) -> list[str]:
    """Render the top-N findings list and an overflow footer."""
    findings = _sort_findings(report.findings)
    total = len(findings)
    top = findings[:TOP_FINDINGS_LIMIT]
    lines = [f"### Top findings ({len(top)} of {total})", ""]
    for f in top:
        lines.extend(_render_finding(f))
    remaining = total - len(top)
    if remaining > 0:
        lines.extend(["", f"_+{remaining} more — see the full report artifact._"])
    return lines


def _render_empty(report: AnalysisReport) -> str:
    """Render the comment body for a report with zero findings."""
    body = [
        *_render_header(report),
        f"✓ No findings — Spectra v{__version__}",
    ]
    return "\n".join(body) + "\n"


# ── Public API ───────────────────────────────────────────────


def render_pr_comment(report: AnalysisReport) -> str:
    """Render an ``AnalysisReport`` as a markdown-safe PR comment body.

    The output always starts with ``PR_COMMENT_SENTINEL`` so the
    GitHub Action's update-existing-comment logic stays idempotent
    across re-runs of the same workflow.

    Args:
        report: Validated ``AnalysisReport`` produced by the pipeline.

    Returns:
        A markdown string safe to post via ``gh pr comment``.
    """
    if not report.findings:
        return _render_empty(report)
    body: list[str] = [
        *_render_header(report),
        *_render_dimension_table(report.score_card.dimensions),
        *_render_findings_block(report),
    ]
    return "\n".join(body) + "\n"


__all__ = [
    "PR_COMMENT_SENTINEL",
    "SUMMARY_MAX_CHARS",
    "TOP_FINDINGS_LIMIT",
    "render_pr_comment",
]
