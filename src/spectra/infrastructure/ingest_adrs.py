"""ADR scanner (v0.9.1, ADR-025 wiring §3, Layer 4).

The composition root calls :func:`scan_adrs` after ``_ingest_workspace``
returns the prepared workspace path. The scanner walks the conventional
ADR locations, parses title/status/date, and returns a tuple of
:class:`MemoryEvent` ready for deposit through ``MemoryPort.append_event``.

Idempotency: each event's ``id`` is derived from the workspace-relative
ADR path, so re-ingesting on subsequent scans is an INSERT OR IGNORE
no-op per the adapter contract.

Failure mode: per-file read failures are logged at DEBUG and skipped —
one malformed ADR never blocks the rest. Missing ADR directories return
an empty tuple silently.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path  # noqa: TC003 — used at runtime via Path.glob / Path.read_text

from spectra.entities.memory import MemoryEvent
from spectra.use_cases.memory_payloads import build_adr_ingested_event

__all__ = ["scan_adrs"]

_LOG = logging.getLogger("spectra.memory.adr_ingest")

_ADR_DIRS = (
    "docs/architecture/adr",
    "doc/adr",
    "docs/adrs",
)

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_STATUS_HEADING_RE = re.compile(r"^##\s+Status\s*$", re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_BODY_EXCERPT_CHARS = 500


def scan_adrs(*, workspace: Path, repo_url: str, actor: str) -> tuple[MemoryEvent, ...]:
    """Scan conventional ADR directories under ``workspace``.

    Args:
        workspace: Repository root (post-clone or local-path).
        repo_url: Canonical URL to stamp on each :class:`MemoryEvent`.
        actor: Identity string (``Identity.display_name`` style).

    Returns:
        Tuple of ``adr_ingested`` events, one per parsed ADR file. Empty
        tuple when no conventional ADR directory exists.
    """
    events: list[MemoryEvent] = []
    for rel_dir in _ADR_DIRS:
        adr_dir = workspace / rel_dir
        if not adr_dir.is_dir():
            continue
        for md_path in sorted(adr_dir.glob("*.md")):
            event = _parse_one(md_path=md_path, workspace=workspace, repo_url=repo_url, actor=actor)
            if event is not None:
                events.append(event)
    return tuple(events)


def _parse_one(
    *,
    md_path: Path,
    workspace: Path,
    repo_url: str,
    actor: str,
) -> MemoryEvent | None:
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        _LOG.debug("ADR read failed for %s: %s", md_path, exc)
        return None

    rel_path = md_path.relative_to(workspace).as_posix()
    title = _extract_title(text, fallback=md_path.stem)
    status = _extract_status(text)
    date = _extract_date(filename=md_path.name, status_block=status, body=text)
    body_excerpt = text[:_BODY_EXCERPT_CHARS]

    return build_adr_ingested_event(
        adr_path=rel_path,
        title=title,
        status=status,
        date=date,
        body_excerpt=body_excerpt,
        repo_url=repo_url,
        actor=actor,
    )


def _extract_title(text: str, *, fallback: str) -> str:
    match = _H1_RE.search(text)
    if match:
        return match.group(1).strip()
    return fallback


def _extract_status(text: str) -> str:
    heading = _STATUS_HEADING_RE.search(text)
    if heading is None:
        return "unknown"
    body_start = heading.end()
    next_heading = _NEXT_HEADING_RE.search(text, body_start)
    body_end = next_heading.start() if next_heading is not None else len(text)
    body = text[body_start:body_end].strip()
    if not body:
        return "unknown"
    first_line = next((line for line in body.splitlines() if line.strip()), "")
    return first_line.strip() or "unknown"


def _extract_date(*, filename: str, status_block: str, body: str) -> str | None:
    for source in (filename, status_block, body):
        match = _ISO_DATE_RE.search(source)
        if match:
            return match.group(1)
    return None
