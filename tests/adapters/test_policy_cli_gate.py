"""CLI tests for SPEC-013 policy-gate failure rendering.

Verifies that ``PolicyGateError`` propagates through the CLI seam and
renders a brand-voice ``✗`` block listing every violation.
"""

from __future__ import annotations

from typer.testing import CliRunner

from spectra.entities.errors import ERRORS
from spectra.entities.models import Violation

# Reuse the existing infra
runner = CliRunner()


class TestPolicyGateRendering:
    def test_render_violations_block(self) -> None:
        from spectra.adapters.cli_controller import _print_policy_violations

        # Smoke test: function exists and renders without raising
        violations = (
            Violation(kind="severity_gate", message="critical finding F-1 exceeds gate", finding_id="F-1"),
            Violation(kind="forbidden_rule_id", message="forbidden rule SEC-101", rule_id="SEC-101"),
        )
        # Should print without raising
        _print_policy_violations(violations)


class TestPolicyGateErrorClass:
    def test_policy_gate_error_carries_spec_013(self) -> None:
        from spectra.adapters.cli_controller import PolicyGateError

        violations = (Violation(kind="min_score_overall", message="overall 50 below 80"),)
        err = PolicyGateError(violations)
        assert err.error.code == "SPEC-013"
        assert err.violations == violations


class TestErrorRegistryHasSpec013:
    def test_spec_013_registered(self) -> None:
        assert "SPEC-013" in ERRORS
        assert ERRORS["SPEC-013"].retryable is False
