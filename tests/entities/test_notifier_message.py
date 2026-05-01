"""Tests for the ``NotifierMessage`` value object — Layer 1 entity (#27 + #34).

Shared payload that ``SlackWebhookAdapter`` and ``TeamsWebhookAdapter``
render into provider-specific JSON. Frozen (immutable) and severity-typed
so renderers can map severity to a colour without re-deriving.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spectra.entities.models import NotifierMessage


class TestNotifierMessage:
    def test_construct_minimum_fields(self) -> None:
        msg = NotifierMessage(
            title="Spectra: drift detected",
            body_markdown="`service-payments` dropped from **A** to **B+**.",
            severity="high",
        )
        assert msg.title == "Spectra: drift detected"
        assert "service-payments" in msg.body_markdown
        assert msg.severity == "high"
        assert msg.link_url is None
        assert msg.color is None

    def test_construct_full_fields(self) -> None:
        msg = NotifierMessage(
            title="Spectra: critical finding",
            body_markdown="SQL injection in `auth/login.py`",
            severity="critical",
            link_url="https://spectra.example/report/abc",
            color="#EF4444",
        )
        assert msg.link_url == "https://spectra.example/report/abc"
        assert msg.color == "#EF4444"

    def test_frozen(self) -> None:
        msg = NotifierMessage(
            title="x",
            body_markdown="y",
            severity="medium",
        )
        with pytest.raises(ValidationError):
            msg.title = "mutated"  # type: ignore[misc]

    def test_severity_must_be_valid_literal(self) -> None:
        with pytest.raises(ValidationError):
            NotifierMessage(  # type: ignore[arg-type]
                title="x",
                body_markdown="y",
                severity="urgent",
            )

    def test_equal_by_value(self) -> None:
        a = NotifierMessage(title="t", body_markdown="b", severity="info")
        b = NotifierMessage(title="t", body_markdown="b", severity="info")
        assert a == b
