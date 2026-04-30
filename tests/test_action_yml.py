"""Tests for the GitHub composite Action manifest (``action.yml``).

These checks lock in the wire format the Action presents to consumers
so a YAML refactor (e.g. reordering keys) cannot accidentally drop the
``fail-on`` input or stop forwarding it to the CLI.

The tests parse ``action.yml`` with ``yaml.safe_load`` rather than
shelling out to ``yq`` so they run anywhere ``pyyaml`` is installed
(every dev environment ships it transitively via Anthropic SDK).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_YML = REPO_ROOT / "action.yml"


@pytest.fixture(scope="module")
def action_manifest() -> dict:
    """Parse action.yml once per test module."""
    raw = ACTION_YML.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict), "action.yml must parse to a mapping"
    return parsed


def _run_step_script(manifest: dict) -> str:
    """Return the bash script of the 'Run Spectra' composite step."""
    steps = manifest["runs"]["steps"]
    for step in steps:
        if step.get("id") == "run":
            return step["run"]
    pytest.fail("'Run Spectra' step (id=run) not found in action.yml")


# ── Q2 #19: fail-on input ────────────────────────────────────


class TestFailOnActionInput:
    def test_inputs_block_declares_fail_on(self, action_manifest):
        assert "fail-on" in action_manifest["inputs"]

    def test_fail_on_default_is_critical(self, action_manifest):
        # Action default: protect main from critical findings out of the box.
        # Distinct from the CLI default (none) so existing local scripts
        # don't silently start failing.
        assert action_manifest["inputs"]["fail-on"]["default"] == "critical"

    def test_fail_on_is_optional(self, action_manifest):
        # required: false (or omitted) so consumers can rely on the default.
        assert action_manifest["inputs"]["fail-on"].get("required", False) is False

    def test_fail_on_has_one_line_description(self, action_manifest):
        desc = action_manifest["inputs"]["fail-on"]["description"]
        assert isinstance(desc, str)
        assert desc.strip()
        # One-line guidance — prefer concise over multi-line YAML literals.
        assert "\n" not in desc.strip()

    def test_fail_on_description_lists_choices(self, action_manifest):
        desc = action_manifest["inputs"]["fail-on"]["description"].lower()
        # All five accepted values must be discoverable from the input doc
        # (CRITICAL is the load-bearing one for CI).
        for value in ("critical", "high", "medium", "low", "none"):
            assert value in desc, (
                f"--fail-on description must mention {value!r} so consumers "
                "can discover all allowed values from the marketplace UI"
            )

    def test_run_step_forwards_fail_on_to_cli(self, action_manifest):
        # The composite step must pass --fail-on so the CLI severity gate
        # actually fires; without this line the input is dead weight.
        script = _run_step_script(action_manifest)
        assert "--fail-on" in script
        assert "${{ inputs.fail-on }}" in script


# ── Smoke checks (anti-regression for the rest of the inputs) ─


class TestActionManifestSmoke:
    def test_existing_inputs_still_present(self, action_manifest):
        # If anyone refactors and accidentally drops a public input, this
        # catches the contract break before users see it.
        inputs = action_manifest["inputs"]
        for required_input in (
            "anthropic-api-key",
            "path",
            "format",
            "quick-mode",
            "comment-on-pr",
            "python-version",
            "spectra-version",
        ):
            assert required_input in inputs, f"Public input {required_input!r} must remain in action.yml"

    def test_run_step_invokes_spectra_analyze(self, action_manifest):
        script = _run_step_script(action_manifest)
        assert "spectra analyze" in script
