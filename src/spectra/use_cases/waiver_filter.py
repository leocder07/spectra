"""Waiver-based finding filter (#18) + inline-pragma scanner (#68 partial).

Pure functions only — no I/O, no infrastructure imports. Suppression is
keyed by ``compute_finding_signature(file_path, rule_id, severity)`` so
findings stay waivable across cosmetic id changes.

Inline pragma format::

    # spectra: ignore-next-line RULE-ID

The pragma applies to the immediately following line (line N+1 if the
pragma is on line N). One-shot, never persisted to disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from spectra.entities.models import Waiver, compute_finding_signature

if TYPE_CHECKING:
    from spectra.entities.models import Finding


_INLINE_PRAGMA_RE = re.compile(
    r"#\s*spectra:\s*ignore-next-line\s+([A-Za-z0-9_\-]+)"
)


@dataclass(frozen=True)
class InlinePragma:
    """One ``# spectra: ignore-next-line RULE`` directive in source.

    Attributes:
        file_path: Repo-relative path of the file containing the pragma.
        line: 1-based line number of the finding the pragma suppresses
            (i.e. the line AFTER the pragma comment).
        rule_id: The rule_id this pragma waives.
    """

    file_path: str
    line: int
    rule_id: str


def filter_findings_by_waivers(
    findings: tuple[Finding, ...],
    waivers: tuple[Waiver, ...],
) -> tuple[Finding, ...]:
    """Drop findings whose composite signature matches any waiver.

    Signature = ``compute_finding_signature(file_path, rule_id, severity)``.

    Args:
        findings: Validated, deduplicated findings from the pipeline.
        waivers: Verified, non-expired waivers (signature already checked
            by the loader). Both empty tuples are valid.

    Returns:
        Findings that survived the suppression pass — input order preserved.
    """
    if not waivers:
        return findings
    suppressed = {w.finding_signature for w in waivers}
    return tuple(
        f
        for f in findings
        if compute_finding_signature(f.location.file_path, f.rule_id, f.severity)
        not in suppressed
    )


def parse_inline_pragmas(file_path: str, source: str) -> tuple[InlinePragma, ...]:
    """Scan ``source`` for ``# spectra: ignore-next-line RULE`` directives.

    The matched pragma's ``line`` is the line the directive AFFECTS — the
    line immediately following the comment. A pragma at EOF (no line to
    suppress) is dropped silently.

    Args:
        file_path: Repo-relative path; recorded on each emitted pragma.
        source: Raw file text.

    Returns:
        Tuple of pragmas in source-order.
    """
    out: list[InlinePragma] = []
    lines = source.splitlines()
    for idx, line in enumerate(lines, start=1):
        match = _INLINE_PRAGMA_RE.search(line)
        if match is None:
            continue
        target_line = idx + 1
        if target_line > len(lines):
            continue  # pragma at EOF
        out.append(
            InlinePragma(file_path=file_path, line=target_line, rule_id=match.group(1))
        )
    return tuple(out)


def pragmas_to_ephemeral_waivers(
    pragmas: tuple[InlinePragma, ...],
    findings: tuple[Finding, ...],
) -> tuple[Waiver, ...]:
    """Convert pragmas into one-shot waivers bound to actual findings.

    Each pragma is matched against the findings list — only when a finding
    sits at exactly ``(pragma.file_path, pragma.line, pragma.rule_id)``
    is an ephemeral waiver minted. Unmatched pragmas are no-ops, so a
    pragma alone cannot suppress something that wasn't actually flagged.

    Args:
        pragmas: Parsed inline directives from ``parse_inline_pragmas``.
        findings: Findings to consider for suppression.

    Returns:
        Tuple of unsigned, in-memory waivers ready for
        ``filter_findings_by_waivers``.
    """
    if not pragmas:
        return ()
    out: list[Waiver] = []
    now = datetime.now(timezone.utc)
    for pragma in pragmas:
        for f in findings:
            if not _pragma_matches_finding(pragma, f):
                continue
            sig = compute_finding_signature(
                f.location.file_path, f.rule_id, f.severity
            )
            out.append(
                Waiver(
                    repo_signature="0" * 32,
                    finding_signature=sig,
                    reason="inline-pragma suppression",
                    waived_by="inline-pragma",
                    waived_at=now,
                    expires_at=now + timedelta(seconds=1),
                    signature="",  # ephemeral; never written to disk
                )
            )
    return tuple(out)


def _pragma_matches_finding(pragma: InlinePragma, finding: Finding) -> bool:
    """True when ``pragma`` targets the exact (file, line, rule) of ``finding``."""
    return (
        pragma.file_path == finding.location.file_path
        and pragma.line == finding.location.line_start
        and pragma.rule_id == finding.rule_id
    )


__all__ = [
    "InlinePragma",
    "filter_findings_by_waivers",
    "parse_inline_pragmas",
    "pragmas_to_ephemeral_waivers",
]
