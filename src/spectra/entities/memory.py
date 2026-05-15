"""Memory-layer domain entities (Layer 1, Q4 #50, ADR-025).

Implements the per-repo memory entities described in ADR-025:

- :class:`MemoryEvent` — one append-only entry in the memory log. Frozen,
  JSON-safe, validates that ``kind`` is a closed Literal and that
  ``occurred_at`` is timezone-aware UTC.

The full :class:`MemorySnapshot` view (waivers + score timeline + ADRs +
decisions) is deferred to a follow-up PR — it depends on three entities
that do not yet exist (``ScoreSnapshot``, ``AdrIngest``, ``DecisionLog``)
and bundling them all in one PR makes review hard.

Privacy boundary: the same forbidden-payload-keys discipline applied to
``AuditEvent`` (ADR-018) applies here in spirit. Memory is cache-class data
on disk under owner-only permissions (ADR-012); we do not enforce a
separate forbidden-keys list at construction time because the call sites
are internal pipeline events, not third-party input.

Naming aligns with the Event Sourcing pattern: every fact written to
memory is an immutable event; the snapshot is a projection over the log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Closed Literal — every kind that can be written to memory. Adding a new
# kind is intentional surgery: bump this Literal, add a field validator
# downstream if the payload shape needs constraining, document in ADR-025.
MemoryEventKind = Literal[
    "scan_completed",
    "waiver_added",
    "adr_ingested",
    "drift_detected",
    "decision_logged",
]


class MemoryEvent(BaseModel):
    """One entry in the per-repo memory log.

    Attributes:
        id: Stable identifier for this event. Defaults to a uuid4 hex when
            omitted. Used by adapters to dedupe replays and by the FTS5
            search to return event handles.
        kind: One of the documented event kinds. Closed set; new kinds
            require an ADR-025 amendment.
        repo_url: The repository the event pertains to. Used as the
            partition key by ``ManagedAgentMemoryAdapter`` and as the
            row tag by ``LocalFileMemoryAdapter``.
        payload: Event-specific payload. Must be JSON-serialisable
            (Pydantic enforces this at write time when adapters serialize).
            Empty mappings are valid.
        actor: Identity that produced the event — typically an
            ``Identity.display_name`` from ADR-018 (e.g. ``"vivek@org"``).
        occurred_at: UTC timestamp. Naive datetimes are rejected; non-UTC
            tz-aware datetimes are normalised to UTC at validation time.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1)
    kind: MemoryEventKind
    repo_url: str = Field(min_length=1)
    payload: dict[str, object] = Field(default_factory=dict)
    actor: str = Field(min_length=1)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _require_tz_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError(
                "MemoryEvent.occurred_at must be timezone-aware (UTC). "
                "Naive datetimes are rejected to prevent timezone drift "
                "across machines reading the same memory log.",
            )
        return value if value.tzinfo == UTC else value.astimezone(UTC)

    def __hash__(self) -> int:
        # BaseModel(frozen=True) provides equality but not __hash__ when
        # the model contains a mutable container (dict). Explicit hash
        # over the deterministic identity tuple keeps MemoryEvent usable
        # in sets and as a dict key.
        return hash((self.id, self.kind, self.repo_url, self.actor, self.occurred_at))


__all__ = ["MemoryEvent", "MemoryEventKind"]
