"""Audit-log domain entities (Layer 1).

Implements the structured audit-event surface described in ADR-018:

- :class:`Identity` — who triggered the action; resolved at startup.
- :class:`AuditTarget` — what the action was performed against (signature,
  not URL).
- :class:`AuditEvent` — the append-only event itself; frozen, JSON-safe.

The privacy boundary is enforced at construction time: a configurable set of
forbidden payload keys is rejected by Pydantic before any adapter sees the
event. String values are bounded at 500 characters so SIEM ingestion stays
predictable.

UUIDv7 is preferred for ``event_id`` because it is sortable; the standard
library does not yet ship UUIDv7, so we degrade to ``uuid4`` which keeps
global uniqueness without sortability — documented trade-off, revisit when
``uuid7`` lands in stdlib.
"""

from __future__ import annotations

import uuid
from datetime import datetime  # noqa: TC003 — used by Pydantic at runtime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Type aliases ─────────────────────────────────────────────

AuditEventType = Literal[
    # Pipeline lifecycle
    "scan.started",
    "scan.completed",
    "scan.degraded",
    "scan.compromised",
    "scan.budget_exceeded",
    "scan.failed",
    # Agent lifecycle
    "agent.failed",
    # Memory + Q&A (ADR-014, ADR-015)
    "memory.write",
    "memory.forget",
    "memory.query",
    # Cache (ADR-012, ADR-018)
    "cache.mac_mismatch",
    "cache.cleared",
    "cache.hit",
    "cache.miss",
    # Reporting / governance
    "report.classification_changed",
    "rule_pack.loaded",
    "plugin.loaded",
    # Identity + security
    "auth.identity_resolved",
    "secret.detected",
    "prompt_injection.detected",
    "run.compromised",
]
"""Closed enum of audit-event types. Adding one is a deliberate, reviewable
edit — collectors map types to alerts, so silent additions break dashboards."""


IdentitySource = Literal["env", "git", "oidc", "hostname"]
IdentityConfidence = Literal["high", "medium", "low"]


# ── Privacy boundary ─────────────────────────────────────────

FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "code",
        "content",
        "secret",
        "key",
        "token",
        "body",
        "raw",
        "snippet",
        "source",
    }
)
"""Payload keys that an adapter must never receive (ADR-018 §4).

Enforced at the entity boundary so a misbehaving call site cannot leak
content into a SIEM. The list is conservative; widen with care because every
addition is a breaking change for emitters that already used the key."""

_MAX_PAYLOAD_STRING_LEN = 500
"""ADR-018 cap: free-form payload strings (e.g. question prefixes) MUST be
≤500 chars so a SIEM row cannot blow up under prompt-shaped input."""


# ── Entities ──────────────────────────────────────────────────


class Identity(BaseModel, frozen=True):
    """Resolved actor identity for audit events.

    Attributes:
        actor: Human-readable identifier — e.g. ``"alice@example.com"`` for
            git, ``"ci:gh-actions:org/repo@ref"`` for OIDC, or
            ``"unknown@hostname"`` for the fallback.
        source: Where the identity came from (env > git > oidc > hostname
            in resolution priority, but each source produces its own label).
        confidence: ``high`` for OIDC, ``medium`` for env or git, ``low``
            for hostname fallback. Auditors filter on this field.
    """

    actor: str = Field(min_length=1, max_length=200)
    source: IdentitySource
    confidence: IdentityConfidence


class AuditTarget(BaseModel, frozen=True):
    """What an audit event was performed against.

    Attributes:
        repo_signature: 32-hex blake2b digest of the file tree. Never the
            URL — see ADR-018 §4.
        run_id: Optional cross-reference to the analysis run; lets a
            reviewer reconstruct one scan's lifecycle from the audit log.
        resource: Optional finer-grained identifier (e.g. memory key,
            cache MAC fingerprint prefix).
    """

    repo_signature: str = Field(min_length=1, max_length=128)
    run_id: str | None = Field(default=None, max_length=64)
    resource: str | None = Field(default=None, max_length=200)


class AuditEvent(BaseModel, frozen=True):
    """Append-only structured audit event.

    Construction validates that every payload key is allowed and every
    value is a primitive ≤500 chars (for strings). Adapters serialize the
    event verbatim; they MUST NOT re-validate.
    """

    event_id: str = Field(min_length=32, max_length=64)
    ts: datetime
    event: AuditEventType
    actor: Identity
    target: AuditTarget
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)
    spectra_version: str = Field(min_length=1, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)

    @field_validator("payload")
    @classmethod
    def _refuse_forbidden_keys(
        cls,
        value: dict[str, str | int | float | bool],
    ) -> dict[str, str | int | float | bool]:
        """Reject forbidden payload keys + over-long string values."""
        for k, v in value.items():
            if k in FORBIDDEN_PAYLOAD_KEYS:
                msg = f"Payload key {k!r} is forbidden (ADR-018 §4 privacy boundary)"
                raise ValueError(msg)
            if isinstance(v, str) and len(v) > _MAX_PAYLOAD_STRING_LEN:
                msg = f"Payload value for {k!r} exceeds {_MAX_PAYLOAD_STRING_LEN} chars"
                raise ValueError(msg)
        return value


# ── Helpers ───────────────────────────────────────────────────


def new_event_id() -> str:
    """Return a 32-char hex event id.

    Prefers UUIDv7 (sortable) when the runtime exposes it; degrades to
    UUIDv4 (random, not sortable) on Python ≤3.13. Documented in ADR-018:
    callers MUST NOT depend on sortability for correctness — the timestamp
    field carries authoritative ordering.
    """
    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        return str(uuid7().hex)
    return uuid.uuid4().hex


__all__ = [
    "FORBIDDEN_PAYLOAD_KEYS",
    "AuditEvent",
    "AuditEventType",
    "AuditTarget",
    "Identity",
    "IdentityConfidence",
    "IdentitySource",
    "new_event_id",
]
