"""Tests for the disclaimer entity — single source of truth for indicative-analysis copy."""

from __future__ import annotations

from spectra.entities.disclaimer import (
    DISCLAIMER_TEXT,
    DISCLAIMER_URL,
    disclaimer_payload,
)


class TestDisclaimerText:
    def test_text_opens_with_indicative_phrase(self):
        # The phrase is what consumers grep for in HTML/JSON/SARIF — it
        # must remain stable so external integrations can detect it.
        assert DISCLAIMER_TEXT.startswith("Indicative analysis")

    def test_text_mentions_human_verification(self):
        assert "human verification" in DISCLAIMER_TEXT

    def test_text_substantial_length(self):
        # ≥50 chars per spec.
        assert len(DISCLAIMER_TEXT) >= 50


class TestDisclaimerUrl:
    def test_url_points_at_github_disclaimer_anchor(self):
        assert DISCLAIMER_URL.startswith("https://")
        assert DISCLAIMER_URL.endswith("#disclaimer")
        assert "leocder07/spectra" in DISCLAIMER_URL


class TestDisclaimerPayload:
    def test_payload_returns_text_and_url(self):
        payload = disclaimer_payload()
        assert payload == {"text": DISCLAIMER_TEXT, "url": DISCLAIMER_URL}

    def test_payload_returns_fresh_dict(self):
        # Mutating one payload must not contaminate the next caller.
        first = disclaimer_payload()
        first["text"] = "tampered"
        assert disclaimer_payload()["text"] == DISCLAIMER_TEXT
