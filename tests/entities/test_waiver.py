"""Tests for the Waiver entity (RICE-72 / Capability #18 — `.spectra-waivers.yml`).

Covers the schema validations on Waiver + Approver, the
``compute_finding_signature`` helper, and the default 180-day TTL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from spectra.entities.models import (
    Approver,
    Waiver,
    compute_finding_signature,
)


def _now() -> datetime:
    return datetime.now(UTC)


class TestWaiverConstruction:
    def test_minimum_valid_waiver(self) -> None:
        w = Waiver(
            repo_signature="a" * 32,
            finding_signature="b" * 16,
            reason="long enough reason",
            waived_by="alice",
            waived_at=_now(),
            signature="c" * 128,
        )
        assert w.waived_by == "alice"

    def test_reason_too_short_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Waiver(
                repo_signature="a" * 32,
                finding_signature="b" * 16,
                reason="short",
                waived_by="alice",
                waived_at=_now(),
                signature="c" * 128,
            )

    def test_default_expiry_is_180_days(self) -> None:
        now = _now()
        w = Waiver(
            repo_signature="a" * 32,
            finding_signature="b" * 16,
            reason="long enough reason",
            waived_by="alice",
            waived_at=now,
            signature="c" * 128,
        )
        delta = w.expires_at - now
        # within a few seconds of 180 days
        assert abs(delta - timedelta(days=180)) < timedelta(seconds=5)

    def test_is_expired(self) -> None:
        past = datetime(2024, 1, 1, tzinfo=UTC)
        w = Waiver(
            repo_signature="a" * 32,
            finding_signature="b" * 16,
            reason="long enough reason",
            waived_by="alice",
            waived_at=past,
            expires_at=past + timedelta(days=1),
            signature="c" * 128,
        )
        assert w.is_expired(_now()) is True
        assert w.is_expired(past) is False

    def test_waiver_is_frozen(self) -> None:
        w = Waiver(
            repo_signature="a" * 32,
            finding_signature="b" * 16,
            reason="long enough reason",
            waived_by="alice",
            waived_at=_now(),
            signature="c" * 128,
        )
        with pytest.raises(ValidationError):
            w.reason = "different"  # type: ignore[misc]


class TestApprover:
    def test_valid_approver(self) -> None:
        a = Approver(name="alice", email="alice@x.com", public_key="d" * 64)
        assert a.name == "alice"

    def test_public_key_must_be_64_hex(self) -> None:
        with pytest.raises(ValidationError):
            Approver(name="x", email="x@y.com", public_key="too-short")


class TestComputeFindingSignature:
    def test_deterministic_for_same_inputs(self) -> None:
        s1 = compute_finding_signature("src/x.py", "SEC-AUTH-101", "high")
        s2 = compute_finding_signature("src/x.py", "SEC-AUTH-101", "high")
        assert s1 == s2

    def test_differs_on_path(self) -> None:
        s1 = compute_finding_signature("src/x.py", "SEC-AUTH-101", "high")
        s2 = compute_finding_signature("src/y.py", "SEC-AUTH-101", "high")
        assert s1 != s2

    def test_differs_on_rule_id(self) -> None:
        s1 = compute_finding_signature("src/x.py", "SEC-AUTH-101", "high")
        s2 = compute_finding_signature("src/x.py", "SEC-AUTH-102", "high")
        assert s1 != s2

    def test_differs_on_severity(self) -> None:
        s1 = compute_finding_signature("src/x.py", "SEC-AUTH-101", "high")
        s2 = compute_finding_signature("src/x.py", "SEC-AUTH-101", "critical")
        assert s1 != s2

    def test_returns_16_hex(self) -> None:
        sig = compute_finding_signature("a", "b", "c")
        assert len(sig) == 16
        int(sig, 16)  # parses
