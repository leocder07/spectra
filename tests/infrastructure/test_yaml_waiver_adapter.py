"""Tests for ``YamlWaiverAdapter`` — Ed25519-signed waiver loading.

Covers:
    - missing files → empty tuples
    - signing → re-load → signature verifies → active set contains it
    - unsigned waiver → rejected (logged + dropped, never silently accepted)
    - invalid signature → rejected
    - expired waiver → ``expired`` tuple, NOT ``active``
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from spectra.entities.models import Approver, Waiver
from spectra.infrastructure.yaml_waiver_adapter import (
    YamlWaiverAdapter,
    canonical_waiver_payload,
    generate_keypair,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_signed_waiver(
    *,
    finding_signature: str = "f" * 16,
    name: str = "alice",
    expires_in: timedelta = timedelta(days=30),
    repo_signature: str = "a" * 32,
) -> tuple[Waiver, Approver]:
    """Mint an Approver + sign a Waiver — returns the pair ready for the adapter."""
    private_hex, public_hex = generate_keypair()
    waiver = Waiver(
        repo_signature=repo_signature,
        finding_signature=finding_signature,
        reason="documented-bypass approved",
        waived_by=name,
        waived_at=_now(),
        expires_at=_now() + expires_in,
    )
    sig = YamlWaiverAdapter().sign_waiver(waiver, private_hex)
    signed = waiver.model_copy(update={"signature": sig})
    approver = Approver(name=name, email=f"{name}@x.com", public_key=public_hex)
    return signed, approver


def _write_waivers_yaml(path: Path, waivers: list[Waiver]) -> None:
    """Serialize waivers to YAML at ``path`` in the schema the adapter expects."""
    data = {
        "version": 1,
        "waivers": [
            {
                "repo_signature": w.repo_signature,
                "finding_signature": w.finding_signature,
                "reason": w.reason,
                "waived_by": w.waived_by,
                "waived_at": w.waived_at.isoformat(),
                "expires_at": w.expires_at.isoformat(),
                "signature": w.signature,
            }
            for w in waivers
        ],
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _write_approvers_yaml(path: Path, approvers: list[Approver]) -> None:
    data = {
        "version": 1,
        "approvers": [
            {"name": a.name, "email": a.email, "public_key": a.public_key}
            for a in approvers
        ],
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


class TestLoadEmpty:
    def test_missing_files_return_empty_tuples(self, tmp_path: Path) -> None:
        adapter = YamlWaiverAdapter()
        active, expired = adapter.load(
            tmp_path / "absent.yml",
            tmp_path / "absent-approvers.yml",
        )
        assert active == ()
        assert expired == ()

    def test_missing_approvers_drops_all_waivers(self, tmp_path: Path) -> None:
        # No approvers file means no public keys to verify against.
        signed, _ = _build_signed_waiver()
        wpath = tmp_path / "waivers.yml"
        _write_waivers_yaml(wpath, [signed])
        adapter = YamlWaiverAdapter()
        active, expired = adapter.load(wpath, tmp_path / "no-approvers.yml")
        assert active == ()
        assert expired == ()


class TestSignAndLoadRoundTrip:
    def test_signed_waiver_loads_and_verifies(self, tmp_path: Path) -> None:
        signed, approver = _build_signed_waiver()
        wpath = tmp_path / "waivers.yml"
        apath = tmp_path / "approvers.yml"
        _write_waivers_yaml(wpath, [signed])
        _write_approvers_yaml(apath, [approver])
        adapter = YamlWaiverAdapter()
        active, expired = adapter.load(wpath, apath)
        assert len(active) == 1
        assert active[0].finding_signature == signed.finding_signature
        assert expired == ()


class TestSignatureRejection:
    def test_unsigned_waiver_rejected(self, tmp_path: Path) -> None:
        signed, approver = _build_signed_waiver()
        unsigned = signed.model_copy(update={"signature": ""})
        wpath = tmp_path / "waivers.yml"
        apath = tmp_path / "approvers.yml"
        _write_waivers_yaml(wpath, [unsigned])
        _write_approvers_yaml(apath, [approver])
        adapter = YamlWaiverAdapter()
        active, expired = adapter.load(wpath, apath)
        assert active == ()
        assert expired == ()

    def test_corrupted_signature_rejected(self, tmp_path: Path) -> None:
        signed, approver = _build_signed_waiver()
        # Flip a hex char in the signature to invalidate it
        broken_sig = ("0" if signed.signature[0] != "0" else "1") + signed.signature[1:]
        broken = signed.model_copy(update={"signature": broken_sig})
        wpath = tmp_path / "waivers.yml"
        apath = tmp_path / "approvers.yml"
        _write_waivers_yaml(wpath, [broken])
        _write_approvers_yaml(apath, [approver])
        adapter = YamlWaiverAdapter()
        active, _ = adapter.load(wpath, apath)
        assert active == ()

    def test_signature_from_unknown_approver_rejected(
        self, tmp_path: Path
    ) -> None:
        signed_alice, _ = _build_signed_waiver(name="alice")
        # Approvers file lists bob — alice is unknown
        _, bob = _build_signed_waiver(name="bob")
        wpath = tmp_path / "waivers.yml"
        apath = tmp_path / "approvers.yml"
        _write_waivers_yaml(wpath, [signed_alice])
        _write_approvers_yaml(apath, [bob])
        adapter = YamlWaiverAdapter()
        active, _ = adapter.load(wpath, apath)
        assert active == ()


class TestExpiredWaivers:
    def test_expired_waiver_goes_to_expired_tuple(self, tmp_path: Path) -> None:
        signed, approver = _build_signed_waiver(
            expires_in=timedelta(days=-1),  # already expired
        )
        wpath = tmp_path / "waivers.yml"
        apath = tmp_path / "approvers.yml"
        _write_waivers_yaml(wpath, [signed])
        _write_approvers_yaml(apath, [approver])
        adapter = YamlWaiverAdapter()
        active, expired = adapter.load(wpath, apath)
        assert active == ()
        assert len(expired) == 1


class TestCanonicalPayload:
    def test_payload_excludes_signature_field(self) -> None:
        signed, _ = _build_signed_waiver()
        payload = canonical_waiver_payload(signed)
        # The signature value must NOT appear in the canonical payload —
        # otherwise we couldn't sign it without circular-dep.
        assert signed.signature not in payload.decode("utf-8")
        # The dict key 'signature' (with quote) must not be present
        assert b'"signature":' not in payload
        # Still includes the substantive fields
        assert signed.finding_signature in payload.decode("utf-8")

    def test_payload_is_deterministic(self) -> None:
        signed, _ = _build_signed_waiver()
        p1 = canonical_waiver_payload(signed)
        p2 = canonical_waiver_payload(signed)
        assert p1 == p2
