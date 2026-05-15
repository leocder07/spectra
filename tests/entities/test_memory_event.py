"""Tests for ``MemoryEvent`` (Layer 1, ADR-025 #50).

Covers:
- Frozen Pydantic shape (immutability per project rule)
- ``kind`` is a closed Literal — invalid kinds rejected at construction
- ``occurred_at`` must be timezone-aware UTC (no naive datetimes)
- ``id`` defaults to a sortable identifier (UUIDv7-flavoured)
- ``payload`` accepts arbitrary JSON-serializable mappings
- ``actor`` is required (matches ``Identity.display_name`` shape)
- Equality + hashing for use in sets / dict keys
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from spectra.entities.memory import MemoryEvent

# ── Helpers ────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _make_event(**overrides: object) -> MemoryEvent:
    base = {
        "kind": "scan_completed",
        "repo_url": "https://github.com/leocder07/spectra",
        "payload": {"score": 92, "grade": "A"},
        "actor": "leocder07@spectra-ai",
        "occurred_at": _now(),
    }
    base.update(overrides)  # type: ignore[arg-type]
    return MemoryEvent(**base)  # type: ignore[arg-type]


# ── Frozen / immutable shape ───────────────────────────────────


class TestFrozenShape:
    def test_is_frozen_per_project_rule(self) -> None:
        event = _make_event()
        with pytest.raises(ValidationError):
            event.kind = "waiver_added"  # type: ignore[misc]

    def test_two_events_with_identical_fields_are_equal(self) -> None:
        ts = _now()
        a = _make_event(id="evt-1", occurred_at=ts)
        b = _make_event(id="evt-1", occurred_at=ts)
        assert a == b

    def test_events_are_hashable(self) -> None:
        ts = _now()
        a = _make_event(id="evt-1", occurred_at=ts)
        b = _make_event(id="evt-1", occurred_at=ts)
        assert {a, b} == {a}


# ── kind validation ────────────────────────────────────────────


class TestKindValidation:
    @pytest.mark.parametrize(
        "kind",
        [
            "scan_completed",
            "waiver_added",
            "adr_ingested",
            "drift_detected",
            "decision_logged",
        ],
    )
    def test_accepts_each_documented_kind(self, kind: str) -> None:
        event = _make_event(kind=kind)
        assert event.kind == kind

    def test_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValidationError):
            _make_event(kind="totally_made_up_event_kind")

    def test_rejects_empty_kind(self) -> None:
        with pytest.raises(ValidationError):
            _make_event(kind="")


# ── occurred_at validation ─────────────────────────────────────


class TestOccurredAtValidation:
    def test_accepts_utc_aware_datetime(self) -> None:
        event = _make_event(occurred_at=datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC))
        assert event.occurred_at.tzinfo is UTC

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            _make_event(occurred_at=datetime(2026, 5, 4, 12, 0, 0))  # noqa: DTZ001

    def test_accepts_non_utc_tz_but_normalizes_to_utc(self) -> None:
        ist = timezone(timedelta(hours=5, minutes=30))
        event = _make_event(occurred_at=datetime(2026, 5, 4, 17, 30, 0, tzinfo=ist))
        # Stored time-of-day is what was supplied; tz must equal UTC.
        assert event.occurred_at.tzinfo == UTC


# ── payload validation ─────────────────────────────────────────


class TestPayload:
    def test_accepts_arbitrary_json_serializable_mapping(self) -> None:
        payload = {
            "score": 92,
            "grade": "A",
            "tags": ["security", "quality"],
            "nested": {"a": 1, "b": [True, None]},
        }
        event = _make_event(payload=payload)
        assert event.payload == payload

    def test_accepts_empty_payload(self) -> None:
        event = _make_event(payload={})
        assert event.payload == {}


# ── actor + repo_url + id ──────────────────────────────────────


class TestRequiredFields:
    def test_actor_required(self) -> None:
        with pytest.raises(ValidationError):
            _make_event(actor="")

    def test_repo_url_required(self) -> None:
        with pytest.raises(ValidationError):
            _make_event(repo_url="")

    def test_id_defaults_when_omitted(self) -> None:
        event = MemoryEvent(
            kind="scan_completed",
            repo_url="https://github.com/leocder07/spectra",
            payload={},
            actor="leocder07@spectra-ai",
            occurred_at=_now(),
        )
        # Should generate a non-empty id deterministically (uuid-flavoured).
        assert event.id
        assert len(event.id) >= 8

    def test_two_default_ids_differ(self) -> None:
        a = MemoryEvent(
            kind="scan_completed",
            repo_url="https://github.com/leocder07/spectra",
            payload={},
            actor="leocder07@spectra-ai",
            occurred_at=_now(),
        )
        b = MemoryEvent(
            kind="scan_completed",
            repo_url="https://github.com/leocder07/spectra",
            payload={},
            actor="leocder07@spectra-ai",
            occurred_at=_now(),
        )
        assert a.id != b.id
