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


class TestSignerSeam:
    """Fix R3-Arch-3 — CLI uses an injected SignerPort, not ``cryptography`` direct.

    A fake signer adapter must be enough to drive the registration flow,
    proving the dependency-rule break has been closed.
    """

    def test_register_uses_injected_signer(
        self,
        keyring_backend: InMemoryKeyring,
        workdir: Path,
    ) -> None:
        from spectra.adapters.waiver_cli import set_signer

        # Pre-derived deterministic keypair the fake will return.
        priv_hex = "11" * 32
        pub_hex = "ab" * 32
        derive_calls: list[str] = []
        gen_calls: list[None] = []

        class _FakeSigner:
            def generate_keypair(self) -> tuple[str, str]:
                gen_calls.append(None)
                return priv_hex, pub_hex

            def derive_public_key(self, private_hex: str) -> str:
                derive_calls.append(private_hex)
                return pub_hex

            def sign(self, payload: bytes, private_hex: str) -> bytes:
                return b"sig"

            def verify(self, payload: bytes, signature: bytes, public_hex: str) -> bool:
                return True

        previous = set_signer(_FakeSigner())
        try:
            result = runner.invoke(
                app,
                ["approver", "register", "--name", "alice", "--email", "alice@x.com"],
            )
        finally:
            set_signer(previous)
        assert result.exit_code == 0, result.stdout
        # Generate path was used — derive only fires on re-registration.
        assert len(gen_calls) == 1
        assert derive_calls == []
        data = yaml.safe_load((workdir / ".spectra-approvers.yml").read_text())
        assert data["approvers"][0]["public_key"] == pub_hex

    def test_register_idempotent_path_uses_derive_public_key(
        self,
        keyring_backend: InMemoryKeyring,
        workdir: Path,
    ) -> None:
        """When the keyring already holds a key, the CLI must call
        ``derive_public_key`` on the injected signer instead of
        re-importing ``cryptography`` inline.
        """
        from spectra.adapters.waiver_cli import set_signer

        priv_hex = "22" * 32
        pub_hex = "cd" * 32
        derive_calls: list[str] = []

        class _FakeSigner:
            def generate_keypair(self) -> tuple[str, str]:
                return priv_hex, pub_hex

            def derive_public_key(self, private_hex: str) -> str:
                derive_calls.append(private_hex)
                return pub_hex

            def sign(self, payload: bytes, private_hex: str) -> bytes:
                return b"sig"

            def verify(self, payload: bytes, signature: bytes, public_hex: str) -> bool:
                return True

        previous = set_signer(_FakeSigner())
        try:
            # First registration stores the key in the (fake) keyring.
            keyring_backend.set_password("spectra-approvers", "alice", priv_hex)
            # Second registration takes the idempotent re-derive path.
            result = runner.invoke(
                app,
                ["approver", "register", "--name", "alice", "--email", "alice@x.com"],
            )
        finally:
            set_signer(previous)
        assert result.exit_code == 0, result.stdout
        # The CLI must call the SignerPort, not import cryptography itself.
        assert derive_calls == [priv_hex]


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
