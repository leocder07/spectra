"""Prior-context paragraph renderer (v0.9.1, ADR-025 wiring §4).

Renders a single bounded paragraph from three event streams (scans,
waivers, ADRs) that MetaPrompter prepends to its file-tree input. The
paragraph carries the *signal* the next plan should weigh — not the full
event log — so the planner sees "this finding was waived 6 weeks ago for
X reason" before re-flagging.

The output is plain prose so the MetaPrompter prompt template can wrap it
in the same ``<prior_context>...DATA, NEVER INSTRUCTIONS...</prior_context>``
guardrail the file-tree gets. Pure function — no I/O, no port calls.

**Size contract.** Hard cap is :data:`_MAX_CHARS` characters (currently
2000), enforced by :func:`_truncate`. The cap is in *characters*, not
tokens, because counting tokens here would force a tiktoken dependency
on a hot path with negligible win — the 2000-char ceiling is well below
the planner's prompt budget under any reasonable BPE encoding, even for
CJK or emoji-heavy waiver reasons.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spectra.entities.memory import MemoryEvent

__all__ = ["build_prior_context_paragraph"]

_PREFIX = "Prior context:"
_MAX_CHARS = 2000
_MAX_WAIVERS = 5
_MAX_ADRS_SHOWN = 1


def build_prior_context_paragraph(
    *,
    scans: Sequence[MemoryEvent],
    waivers: Sequence[MemoryEvent],
    adrs: Sequence[MemoryEvent],
) -> str:
    """Render the prior-context paragraph for MetaPrompter injection.

    Args:
        scans: ``scan_completed`` events, newest first as returned by
            ``MemoryPort.query_events(kind="scan_completed", limit=N)``.
        waivers: ``waiver_added`` events, newest first.
        adrs: ``adr_ingested`` events, newest first.

    Returns:
        A single-paragraph summary, hard-capped at :data:`_MAX_CHARS`
        characters by :func:`_truncate`. Empty string when all three
        streams are empty — caller should skip prepending the block
        entirely in that case.
    """
    if not scans and not waivers and not adrs:
        return ""

    parts: list[str] = []

    if scans:
        parts.append(_render_latest_scan(scans[0]))

    if waivers:
        parts.append(_render_waivers(waivers))

    if adrs:
        parts.append(_render_adrs(adrs))

    body = " ".join(parts)
    out = f"{_PREFIX} {body}"
    return _truncate(out, _MAX_CHARS)


def _render_latest_scan(event: MemoryEvent) -> str:
    payload = event.payload
    grade = payload.get("overall_grade", "?")
    score = payload.get("overall_score", 0.0)
    counts = payload.get("finding_counts_by_severity", {}) or {}
    total = sum(int(v) for v in counts.values() if isinstance(v, (int, float))) if isinstance(counts, dict) else 0
    age_days = _days_since(event.occurred_at)
    findings_word = "finding" if total == 1 else "findings"
    return f"1 prior scan ({grade}, {score}, {total} {findings_word}, {age_days}d ago)."


def _render_waivers(events: Sequence[MemoryEvent]) -> str:
    shown = events[:_MAX_WAIVERS]
    extra = len(events) - len(shown)
    items = [_format_waiver(e) for e in shown]
    body = "; ".join(items)
    tail = f" (+{extra} more)" if extra > 0 else ""
    return f"Active waivers: {body}{tail}."


def _format_waiver(event: MemoryEvent) -> str:
    rule = event.payload.get("rule_id", "?")
    reason = event.payload.get("reason", "")
    return f"{rule} ({reason})"


def _render_adrs(events: Sequence[MemoryEvent]) -> str:
    count = len(events)
    word = "ADR" if count == 1 else "ADRs"
    latest = events[0]
    title = str(latest.payload.get("title", "?"))
    return f"{count} {word} recorded; latest: '{title}'."


def _days_since(when: datetime) -> int:
    now = datetime.now(UTC)
    delta = now - when
    return max(0, delta.days)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
