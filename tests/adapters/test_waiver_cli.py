"""Tests for ``spectra waive`` + ``spectra approver register`` subcommands.

The keyring backend is faked so the test never touches the real OS
keychain. Round-trip: register approver → waive a finding → re-load
the waiver file via ``YamlWaiverAdapter`` → signature verifies.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from spectra.adapters.cli_controller import app
from spectra.adapters.waiver_cli import (
    InMemoryKeyring,
    set_keyring_backend,
)

runner = CliRunner()


@pytest.fixture
def keyring_backend() -> InMemoryKeyring:
    """Fresh in-memory keyring per test; restored after."""
    backend = InMemoryKeyring()
    previous = set_keyring_backend(backend)
    yield backend
    set_keyring_backend(previous)


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    """Run each CLI test from an isolated cwd so YAML files don't collide."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestApproverRegister:
    def test_register_creates_approvers_file_and_stores_key(
        self,
        keyring_backend: InMemoryKeyring,
        workdir: Path,
    ) -> None:
        result = runner.invoke(
            app,
            ["approver", "register", "--name", "alice", "--email", "alice@x.com"],
        )
        assert result.exit_code == 0, result.stdout
        approvers_file = workdir / ".spectra-approvers.yml"
        assert approvers_file.exists()
        data = yaml.safe_load(approvers_file.read_text())
        assert data["approvers"][0]["name"] == "alice"
        assert len(data["approvers"][0]["public_key"]) == 64
        # Private key in keyring under spectra-approver-key-alice
        assert keyring_backend.get_password("spectra-approvers", "alice") is not None

    def test_register_appends_a_second_approver(
        self,
        keyring_backend: InMemoryKeyring,
        workdir: Path,
    ) -> None:
        runner.invoke(
            app,
            ["approver", "register", "--name", "alice", "--email", "alice@x.com"],
        )
        result = runner.invoke(
            app,
            ["approver", "register", "--name", "bob", "--email", "bob@x.com"],
        )
        assert result.exit_code == 0
        data = yaml.safe_load((workdir / ".spectra-approvers.yml").read_text())
        names = {a["name"] for a in data["approvers"]}
        assert names == {"alice", "bob"}


class TestWaiveCommand:
    def test_waive_creates_signed_waiver_then_verifies(
        self,
        keyring_backend: InMemoryKeyring,
        workdir: Path,
    ) -> None:
        # Register approver first
        runner.invoke(
            app,
            ["approver", "register", "--name", "alice", "--email", "alice@x.com"],
        )
        # Now waive a finding
        result = runner.invoke(
            app,
            [
                "waive",
                "--file",
                "src/x.py",
                "--rule-id",
                "SEC-AUTH-101",
                "--severity",
                "high",
                "--reason",
                "documented bypass approved by team",
                "--waived-by",
                "alice",
            ],
        )
        assert result.exit_code == 0, result.stdout
        waivers_file = workdir / ".spectra-waivers.yml"
        assert waivers_file.exists()
        # Re-load via the adapter — round trip verifies signature
        from spectra.infrastructure.yaml_waiver_adapter import YamlWaiverAdapter

        adapter = YamlWaiverAdapter()
        active, expired = adapter.load(waivers_file, workdir / ".spectra-approvers.yml")
        assert len(active) == 1
        assert active[0].waived_by == "alice"
        assert expired == ()

    def test_waive_short_reason_rejected(
        self,
        keyring_backend: InMemoryKeyring,
        workdir: Path,
    ) -> None:
        runner.invoke(
            app,
            ["approver", "register", "--name", "alice", "--email", "alice@x.com"],
        )
        result = runner.invoke(
            app,
            [
                "waive",
                "--file",
                "src/x.py",
                "--rule-id",
                "SEC-AUTH-101",
                "--severity",
                "high",
                "--reason",
                "short",
                "--waived-by",
                "alice",
            ],
        )
        assert result.exit_code == 1
        assert "reason" in result.stdout.lower() or "10" in result.stdout

    def test_waive_without_registered_approver_errors(
        self,
        keyring_backend: InMemoryKeyring,
        workdir: Path,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "waive",
                "--file",
                "src/x.py",
                "--rule-id",
                "SEC-AUTH-101",
                "--severity",
                "high",
                "--reason",
                "documented bypass approved",
                "--waived-by",
                "ghost",
            ],
        )
        assert result.exit_code == 1
        # Brand-voice ✗ on missing approver
        assert "ghost" in result.stdout or "register" in result.stdout.lower()


# Smoke test: deterministic time so the test does not rely on system clock
def test_waiver_default_expiry_is_180_days_in_future(
    keyring_backend: InMemoryKeyring,
    workdir: Path,
) -> None:
    runner.invoke(app, ["approver", "register", "--name", "alice", "--email", "a@x.com"])
    runner.invoke(
        app,
        [
            "waive",
            "--file",
            "src/x.py",
            "--rule-id",
            "SEC",
            "--severity",
            "high",
            "--reason",
            "ten or more chars here",
            "--waived-by",
            "alice",
        ],
    )
    data = yaml.safe_load((workdir / ".spectra-waivers.yml").read_text())
    waiver = data["waivers"][0]
    expires = datetime.fromisoformat(waiver["expires_at"])
    waived = datetime.fromisoformat(waiver["waived_at"])
    delta = expires - waived
    assert 179 <= delta.days <= 181  # 180 +/- 1 day for timezone clock skew
