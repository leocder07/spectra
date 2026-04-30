"""Tests for the AuditEvent + Identity domain entities (Layer 1).

These cover:
    - AuditEvent frozen + immutable (Pydantic ``frozen=True``)
    - Forbidden payload keys raise validation errors at construction
    - Payload value types restricted to primitives (no nested dicts)
    - Identity precedence + confidence labels
    - UUIDv7-shaped event_id (sortable hex string, length 32)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from spectra.entities.audit import (
    FORBIDDEN_PAYLOAD_KEYS,
    AuditEvent,
    AuditEventType,
    AuditTarget,
    Identity,
    new_event_id,
)


def _identity() -> Identity:
    return Identity(actor="alice@example.com", source="git", confidence="medium")


def _target() -> AuditTarget:
    return AuditTarget(repo_signature="a" * 32, run_id="r-001")


class TestAuditEventFrozen:
    def test_frozen_assignment_raises(self) -> None:
        event = AuditEvent(
            event_id=new_event_id(),
            ts=datetime.now(UTC),
            event="scan.started",
            actor=_identity(),
            target=_target(),
            payload={},
            spectra_version="0.6.0",
            run_id="r-001",
        )
        with pytest.raises(ValidationError):
            event.actor = _identity()  # type: ignore[misc]

    def test_event_id_is_32_hex_chars(self) -> None:
        event_id = new_event_id()
        assert len(event_id) == 32
        assert all(c in "0123456789abcdef" for c in event_id)

    def test_event_ids_are_unique(self) -> None:
        ids = {new_event_id() for _ in range(50)}
        assert len(ids) == 50


class TestAuditEventPayloadRefusal:
    @pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_PAYLOAD_KEYS))
    def test_forbidden_keys_rejected(self, forbidden: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AuditEvent(
                event_id=new_event_id(),
                ts=datetime.now(UTC),
                event="scan.started",
                actor=_identity(),
                target=_target(),
                payload={forbidden: "leak"},
                spectra_version="0.6.0",
            )
        assert forbidden in str(exc_info.value)

    def test_nested_payload_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AuditEvent(
                event_id=new_event_id(),
                ts=datetime.now(UTC),
                event="scan.started",
                actor=_identity(),
                target=_target(),
                payload={"nested": {"oops": 1}},  # type: ignore[dict-item]
                spectra_version="0.6.0",
            )

    def test_string_payload_value_truncated_at_500(self) -> None:
        with pytest.raises(ValidationError):
            AuditEvent(
                event_id=new_event_id(),
                ts=datetime.now(UTC),
                event="scan.started",
                actor=_identity(),
                target=_target(),
                payload={"q": "x" * 501},
                spectra_version="0.6.0",
            )

    def test_primitive_payload_accepted(self) -> None:
        event = AuditEvent(
            event_id=new_event_id(),
            ts=datetime.now(UTC),
            event="scan.completed",
            actor=_identity(),
            target=_target(),
            payload={"score": 88.0, "findings": 3, "ok": True, "label": "ok"},
            spectra_version="0.6.0",
        )
        assert event.payload["score"] == 88.0


class TestIdentity:
    @pytest.mark.parametrize(
        "source,confidence",
        [
            ("env", "medium"),
            ("git", "medium"),
            ("oidc", "high"),
            ("hostname", "low"),
        ],
    )
    def test_identity_source_confidence_pairs(self, source: str, confidence: str) -> None:
        ident = Identity(actor="user@host", source=source, confidence=confidence)  # type: ignore[arg-type]
        assert ident.source == source
        assert ident.confidence == confidence

    def test_identity_frozen(self) -> None:
        ident = _identity()
        with pytest.raises(ValidationError):
            ident.actor = "bob@example.com"  # type: ignore[misc]


class TestAuditEventTypeRegistry:
    def test_known_event_types_round_trip(self) -> None:
        valid: tuple[AuditEventType, ...] = (
            "scan.started",
            "scan.completed",
            "scan.degraded",
            "scan.compromised",
            "scan.budget_exceeded",
            "memory.write",
            "memory.forget",
            "memory.query",
            "cache.mac_mismatch",
            "cache.cleared",
            "report.classification_changed",
            "rule_pack.loaded",
            "plugin.loaded",
            "auth.identity_resolved",
            "agent.failed",
            "secret.detected",
            "prompt_injection.detected",
        )
        for event in valid:
            evt = AuditEvent(
                event_id=new_event_id(),
                ts=datetime.now(UTC),
                event=event,
                actor=_identity(),
                target=_target(),
                payload={},
                spectra_version="0.6.0",
            )
            assert evt.event == event

    def test_unknown_event_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AuditEvent(
                event_id=new_event_id(),
                ts=datetime.now(UTC),
                event="totally.invented",  # type: ignore[arg-type]
                actor=_identity(),
                target=_target(),
                payload={},
                spectra_version="0.6.0",
            )
