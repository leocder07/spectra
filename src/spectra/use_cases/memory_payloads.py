"""Memory payload builders (v0.9.1, ADR-025 wiring §5).

Three builder functions that translate domain values into :class:`MemoryEvent`
instances with stable, idempotent ids:

  - ``build_scan_completed_event(report, scan_id, repo_url, actor)``
  - ``build_waiver_added_event(...)``
  - ``build_adr_ingested_event(adr_path, title, status, date, body_excerpt, repo_url, actor)``

These live in Layer 2 (use_cases) because the writers — the post-Stage-6
pipeline hook, the ``spectra waive`` enhancement, and the composition-root
ADR scanner — all need to compose the same shape. The entity layer
(``entities/memory.py``) is intentionally untouched: ``MemoryEvent.payload``
is a free-form ``dict[str, object]`` so a future paid adapter can carry a
richer payload without an entity migration.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, TypedDict

from spectra.entities.memory import MemoryEvent

if TYPE_CHECKING:
    from spectra.entities.models import AnalysisReport

__all__ = [
    "AdrIngestedPayload",
    "ScanCompletedPayload",
    "WaiverAddedPayload",
    "build_adr_ingested_event",
    "build_scan_completed_event",
    "build_waiver_added_event",
]


_SEVERITY_KEYS: tuple[Literal["critical", "high", "medium", "low", "info"], ...] = (
    "critical",
    "high",
    "medium",
    "low",
    "info",
)

_DIMENSION_KEYS = (
    "architecture",
    "security",
    "quality",
    "documentation",
    "maintainability",
    "performance",
)


class ScanCompletedPayload(TypedDict):
    """Payload shape for ``MemoryEvent(kind="scan_completed")``."""

    scan_id: str
    overall_score: float
    overall_grade: str
    finding_counts_by_severity: dict[str, int]
    dimension_scores: dict[str, float]
    cost_usd: float
    duration_seconds: float
    is_degraded: bool


class WaiverAddedPayload(TypedDict):
    """Payload shape for ``MemoryEvent(kind="waiver_added")``."""

    waiver_id: str
    rule_id: str
    file_path: str
    line_start: int
    reason: str
    approved_by: str
    expires_at: str | None


class AdrIngestedPayload(TypedDict):
    """Payload shape for ``MemoryEvent(kind="adr_ingested")``."""

    adr_path: str
    title: str
    status: str
    date: str | None
    body_excerpt: str


def build_scan_completed_event(
    *,
    report: AnalysisReport,
    scan_id: str,
    repo_url: str,
    actor: str,
) -> MemoryEvent:
    """Build the post-Stage-6 ``scan_completed`` event.

    The ``id`` is ``f"scan:{scan_id}"`` so a retried Stage-6 hook is an
    INSERT OR IGNORE no-op (idempotency contract from ADR-025).
    """
    severities = Counter(f.severity for f in report.findings)
    finding_counts = {key: int(severities.get(key, 0)) for key in _SEVERITY_KEYS}

    dim_scores: dict[str, float] = dict.fromkeys(_DIMENSION_KEYS, 0.0)
    for dim_score in report.score_card.dimensions:
        dim_scores[dim_score.dimension] = round(dim_score.score, 2)

    payload: ScanCompletedPayload = {
        "scan_id": scan_id,
        "overall_score": round(report.score_card.overall_score, 2),
        "overall_grade": report.score_card.overall_grade,
        "finding_counts_by_severity": finding_counts,
        "dimension_scores": dim_scores,
        "cost_usd": round(report.total_cost_usd, 4),
        "duration_seconds": round(report.analysis_duration_seconds, 2),
        "is_degraded": report.is_degraded,
    }
    return MemoryEvent(
        id=f"scan:{scan_id}",
        kind="scan_completed",
        repo_url=repo_url,
        payload=dict(payload),
        actor=actor,
        occurred_at=datetime.now(UTC),
    )


def build_waiver_added_event(
    *,
    waiver_id: str,
    rule_id: str,
    file_path: str,
    line_start: int,
    reason: str,
    approved_by: str,
    expires_at: str | None,
    repo_url: str,
    actor: str,
) -> MemoryEvent:
    """Build a ``waiver_added`` event. ``id = f"waiver:{waiver_id}"``."""
    payload: WaiverAddedPayload = {
        "waiver_id": waiver_id,
        "rule_id": rule_id,
        "file_path": file_path,
        "line_start": line_start,
        "reason": reason,
        "approved_by": approved_by,
        "expires_at": expires_at,
    }
    return MemoryEvent(
        id=f"waiver:{waiver_id}",
        kind="waiver_added",
        repo_url=repo_url,
        payload=dict(payload),
        actor=actor,
        occurred_at=datetime.now(UTC),
    )


def build_adr_ingested_event(
    *,
    adr_path: str,
    title: str,
    status: str,
    date: str | None,
    body_excerpt: str,
    repo_url: str,
    actor: str,
) -> MemoryEvent:
    """Build an ``adr_ingested`` event. ``id = f"adr:{sha256(adr_path)[:16]}"``."""
    digest = hashlib.sha256(adr_path.encode("utf-8")).hexdigest()[:16]
    payload: AdrIngestedPayload = {
        "adr_path": adr_path,
        "title": title,
        "status": status,
        "date": date,
        "body_excerpt": body_excerpt,
    }
    return MemoryEvent(
        id=f"adr:{digest}",
        kind="adr_ingested",
        repo_url=repo_url,
        payload=dict(payload),
        actor=actor,
        occurred_at=datetime.now(UTC),
    )
