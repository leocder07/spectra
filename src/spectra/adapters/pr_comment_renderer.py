"""Markdown-safe PR comment renderer — Layer 3 adapter.

Composes the body of the GitHub PR comment posted by the Spectra Action
from an ``AnalysisReport``. Three security guarantees protect the host
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
   (``![..](..)``), inline links (``[t](u)``), reference-style
   definitions (``[ref]: u``), autolinks (``<http..>``), bare URLs,
   GitHub @mentions, ``#issue`` refs, or commit SHAs are dropped
   entirely so attacker-controlled URLs / notification triggers never
   reach a reviewer's browser.

3. **Visual-spoofing defense.** BiDi override codepoints (U+202A-E,
   U+2066-9) and zero-width characters (U+200B-D, U+FEFF) are
   stripped from every text field before HTML-escape. In titles —
   which cannot be dropped because they are the only human-readable
   identifier — inline / reference markdown link syntax is broken by
   inserting a space, bare URLs are replaced with ``[url removed]``,
   and ``@username`` / ``#1234`` GitHub-autolink triggers are
   neutralized by inserting a single U+200B between the trigger
   character and the rest of the token (re-introduced *after*
   invisible-stripping ran) so the reader still sees the model's
   text but GitHub no longer renders it as a clickable mention or
   issue reference.

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

# Inline markdown link: ``[text](url)`` — a clickable anchor that GitHub
# renders as ``<a href="url">text</a>``. An attacker could ship a phishing
# link or exfil URL through any free-form text field this way.
_INLINE_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[[^\]]*\]\([^)]*\)")

# Reference-style markdown link USE: ``[text][ref]``. The matching
# ``[ref]: url`` definition can live anywhere in the rendered comment —
# including a different finding's description — so any occurrence is
# treated as exfil risk.
_REFERENCE_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[[^\]]*\]\[[^\]]*\]")

# Reference-style link DEFINITION: ``[ref]: https://...``. Even without a
# matching use site in the same comment, a definition can be resolved by
# a sibling comment in the same PR thread, so we drop on definition too.
_REFERENCE_DEF_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[[^\]]+\]:\s*\S+")

# Bare URL: ``http(s)://...``. GitHub auto-linkifies these in PR comments
# even without explicit markdown syntax, so they must not survive.
_BARE_URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://\S+", re.IGNORECASE)

# GitHub @mention: ``@username``. A poisoned finding could spam-tag
# arbitrary maintainers / @everyone / @org/team via a notification.
# GitHub usernames are 1-39 chars: alphanumeric + single hyphens.
_MENTION_PATTERN: Final[re.Pattern[str]] = re.compile(r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\b")

# GitHub issue / PR reference: ``#123`` — auto-links to issue #123 in
# the host repo, which the attacker does not own. Drop to prevent
# misleading cross-references.
_ISSUE_REF_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<![A-Za-z0-9_])#\d+\b")

# Git commit SHA reference: 7-40 hex chars. GitHub auto-linkifies these
# as commit references in the host repo.
_COMMIT_SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)

# Unicode visual-spoofing characters — BiDi overrides + zero-width chars.
# Stripped from every text field before HTML-escape so they cannot reorder
# or hide content in the rendered comment.
#   U+200B ZERO WIDTH SPACE
#   U+200C ZERO WIDTH NON-JOINER
#   U+200D ZERO WIDTH JOINER
#   U+202A LEFT-TO-RIGHT EMBEDDING
#   U+202B RIGHT-TO-LEFT EMBEDDING
#   U+202C POP DIRECTIONAL FORMATTING
#   U+202D LEFT-TO-RIGHT OVERRIDE
#   U+202E RIGHT-TO-LEFT OVERRIDE
#   U+2066 LEFT-TO-RIGHT ISOLATE
#   U+2067 RIGHT-TO-LEFT ISOLATE
#   U+2068 FIRST STRONG ISOLATE
#   U+2069 POP DIRECTIONAL ISOLATE
#   U+FEFF ZERO WIDTH NO-BREAK SPACE (BOM)
_INVISIBLE_CHARS: Final[re.Pattern[str]] = re.compile(r"[​‌‍‪‫‬‭‮⁦⁧⁨⁩﻿]")

# Patterns that, if present in a description, cause the entire summary to
# be dropped. Mirrors the original "drop on image/autolink" philosophy:
# we never partially sanitize a URL-bearing field.
_SUMMARY_DROP_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    _IMAGE_PATTERN,
    _AUTOLINK_PATTERN,
    _INLINE_LINK_PATTERN,
    _REFERENCE_LINK_PATTERN,
    _REFERENCE_DEF_PATTERN,
    _BARE_URL_PATTERN,
    _MENTION_PATTERN,
    _COMMIT_SHA_PATTERN,
)

_URL_REMOVED: Final[str] = "[url removed]"
"""Placeholder substituted for any URL-like substring in a title."""


def _strip_invisibles(text: str) -> str:
    """Strip BiDi overrides + zero-width chars before any other handling."""
    return _INVISIBLE_CHARS.sub("", text)


def _neuter_title_links(title: str) -> str:
    """Break markdown link syntax + bare URLs in a title.

    A title cannot be dropped (it is the only identifier surfaced for
    the finding), so URL-bearing constructs are broken in place:

    - ``[text](url)`` and ``[text][ref]`` — a space is inserted between
      ``]`` and the following ``(`` / ``[`` so GitHub no longer parses
      it as a link.
    - ``http(s)://...`` bare URLs are replaced with ``[url removed]``
      so neither the URL nor any auto-linkified anchor reaches the
      reviewer's browser.
    """
    # Break inline + reference link syntax first (order matters — we want
    # to neutralize the structural patterns before any URL replacement).
    cleaned = title.replace("](", "] (").replace("][", "] [")
    # Drop reference-style definitions outright — they have no purpose
    # inside a single-line title.
    cleaned = _REFERENCE_DEF_PATTERN.sub(_URL_REMOVED, cleaned)
    # Replace any remaining bare URL with the placeholder.
    return _BARE_URL_PATTERN.sub(_URL_REMOVED, cleaned)


def _neuter_title_autolink_triggers(title: str) -> str:
    """Break GitHub @mention / #issue / commit-SHA auto-link triggers.

    A single U+200B ZERO WIDTH SPACE is inserted between the trigger
    character and the rest of the token (``@​everyone``, ``#​1337``)
    so GitHub no longer recognises the auto-link prefix, while the
    reader still sees roughly what the model wrote. Commit SHAs are
    replaced with ``[ref removed]`` since there is no benign rendering
    of an opaque hex blob in a finding title.

    NOTE: this function is the ONE place that intentionally emits
    U+200B *after* ``_strip_invisibles`` has already run — the strip
    happens earlier in the pipeline so a model-emitted U+200B cannot
    survive, but our own controlled ZWSP insertion here is what
    breaks the auto-link.
    """
    cleaned = _MENTION_PATTERN.sub(lambda m: m.group(0).replace("@", "@​", 1), title)
    cleaned = _ISSUE_REF_PATTERN.sub(lambda m: m.group(0).replace("#", "#​", 1), cleaned)
    return _COMMIT_SHA_PATTERN.sub("[ref removed]", cleaned)


def _sanitize_title(title: str) -> str:
    """Make a finding title safe to embed in the comment body.

    Pipeline: strip invisible spoofing chars → neutralize URL/link
    syntax → neutralize GitHub auto-link triggers → replace backticks
    with U+02CB → HTML-escape.

    The ordering is load-bearing: ``_strip_invisibles`` runs first so
    a model-emitted ZWSP/RLO cannot ride along inside a token that
    later steps would otherwise sanitize. The auto-link-trigger step
    re-introduces a single ZWSP after the ``@``/``#`` *after* the
    strip has already run — that one controlled invisible is what
    keeps the rendered title human-readable while still breaking
    GitHub's auto-link parser.
    """
    cleaned = _strip_invisibles(title)
    cleaned = _neuter_title_links(cleaned)
    cleaned = _neuter_title_autolink_triggers(cleaned)
    cleaned = cleaned.replace("`", _BACKTICK_REPLACEMENT)
    return html.escape(cleaned, quote=False)


def _sanitize_summary(description: str) -> str | None:
    """Return a safe truncated summary, or ``None`` to drop the field.

    Returns ``None`` when the description contains any URL- or
    auto-link-bearing pattern (image, autolink, inline link,
    reference-style link / definition, bare URL, @mention, commit
    SHA) — the entire summary is dropped rather than sanitized so
    attacker URLs / notification triggers never appear, even quoted.

    Note that ``#issue`` references are NOT in the drop list — the
    digits-after-hash pattern is too common in legitimate finding text
    (line numbers, sizes, counts) and we accept the residual risk of a
    misleading issue cross-reference inside a description bullet.
    """
    cleaned = _strip_invisibles(description)
    for pattern in _SUMMARY_DROP_PATTERNS:
        if pattern.search(cleaned):
            return None
    truncated = cleaned if len(cleaned) <= SUMMARY_MAX_CHARS else cleaned[:SUMMARY_MAX_CHARS] + "…"
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
