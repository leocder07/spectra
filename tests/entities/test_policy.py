"""Tests for the Policy entity (RICE-65 / Capability #17 — `.spectra-policy.yml`).

Covers schema validation, default-empty construction, and the six policy
fields (severity_gate, dimension_overrides, min_score_overall,
forbidden_rule_ids, required_dimensions, version).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spectra.entities.models import EmptyPolicy, Policy


class TestPolicyConstruction:
    """Frozen Pydantic Policy model — schema and defaults."""

    def test_empty_policy_is_constructible_with_no_args(self) -> None:
        policy = EmptyPolicy()
        assert policy.severity_gate == "none"
        assert policy.dimension_overrides == {}
        assert policy.min_score_overall is None
        assert policy.forbidden_rule_ids == ()
        assert policy.required_dimensions == ()
        assert policy.version == 1

    def test_policy_is_frozen(self) -> None:
        policy = EmptyPolicy()
        with pytest.raises(ValidationError):
            policy.severity_gate = "critical"  # type: ignore[misc]

    def test_policy_accepts_known_severity_gates(self) -> None:
        for level in ("critical", "high", "medium", "low", "none"):
            p = Policy(severity_gate=level)
            assert p.severity_gate == level

    def test_policy_rejects_unknown_severity_gate(self) -> None:
        with pytest.raises(ValidationError):
            Policy(severity_gate="catastrophic")  # type: ignore[arg-type]

    def test_policy_accepts_dimension_overrides(self) -> None:
        p = Policy(dimension_overrides={"security": 0.5, "architecture": 0.2})
        assert p.dimension_overrides["security"] == 0.5

    def test_policy_rejects_negative_dimension_weight(self) -> None:
        with pytest.raises(ValidationError):
            Policy(dimension_overrides={"security": -0.1})

    def test_policy_rejects_unknown_dimension(self) -> None:
        with pytest.raises(ValidationError):
            Policy(dimension_overrides={"vibes": 0.5})

    def test_policy_min_score_in_range(self) -> None:
        p = Policy(min_score_overall=80.0)
        assert p.min_score_overall == 80.0

    def test_policy_min_score_rejects_above_100(self) -> None:
        with pytest.raises(ValidationError):
            Policy(min_score_overall=101.0)

    def test_policy_forbidden_rule_ids_normalises_to_tuple(self) -> None:
        p = Policy(forbidden_rule_ids=("SEC-AUTH-101", "SEC-XSS-204"))
        assert p.forbidden_rule_ids == ("SEC-AUTH-101", "SEC-XSS-204")

    def test_policy_required_dimensions_must_be_known(self) -> None:
        p = Policy(required_dimensions=("security", "architecture"))
        assert "security" in p.required_dimensions

    def test_policy_required_dimensions_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            Policy(required_dimensions=("vibes",))  # type: ignore[arg-type]
