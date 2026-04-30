"""Composition root tests: audit sink selection + keyring-backed receipt store."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from spectra.infrastructure.audit import (
    JsonLinesAuditAdapter,
    OtlpAuditAdapter,
    StdoutAuditAdapter,
)
from spectra.infrastructure.audit_wiring import (
    KeyringReceiptKeyStore,
    build_audit_adapter,
    parse_audit_sink_spec,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class _FakeKeyringBackend:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.store.get((service, account))

    def set_password(self, service: str, account: str, password: str) -> None:
        self.store[(service, account)] = password


@pytest.fixture
def public_key_path(tmp_path: Path) -> Iterator[Path]:
    return tmp_path / "receipt.pub"


class TestParseAuditSinkSpec:
    def test_stdout_sink(self) -> None:
        kind, value = parse_audit_sink_spec("stdout")
        assert kind == "stdout"
        assert value == ""

    def test_file_sink_with_path(self, tmp_path: Path) -> None:
        target = tmp_path / "audit.jsonl"
        kind, value = parse_audit_sink_spec(f"file:{target}")
        assert kind == "file"
        assert value == str(target)

    def test_otlp_sink_with_url(self) -> None:
        kind, value = parse_audit_sink_spec("otlp:https://collector.local/v1/logs")
        assert kind == "otlp"
        assert value == "https://collector.local/v1/logs"

    def test_unknown_sink_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown audit sink"):
            parse_audit_sink_spec("kafka:my.broker")


class TestBuildAuditAdapter:
    def test_stdout_returns_stdout_adapter(self) -> None:
        adapter = build_audit_adapter("stdout")
        assert isinstance(adapter, StdoutAuditAdapter)

    def test_file_returns_jsonl_adapter(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        adapter = build_audit_adapter(f"file:{path}")
        assert isinstance(adapter, JsonLinesAuditAdapter)
        assert adapter.path == path

    def test_otlp_returns_otlp_adapter(self) -> None:
        adapter = build_audit_adapter("otlp:https://collector.local/v1/logs")
        assert isinstance(adapter, OtlpAuditAdapter)


class TestKeyringReceiptKeyStore:
    def test_keypair_persists_across_instances(self, public_key_path: Path) -> None:
        backend = _FakeKeyringBackend()
        first = KeyringReceiptKeyStore(public_key_path=public_key_path, backend=backend)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        first.save_private_key(key)
        first.write_public_key(key.public_key())
        second = KeyringReceiptKeyStore(public_key_path=public_key_path, backend=backend)
        assert second.load_private_key() is not None

    def test_load_returns_none_when_unset(self, public_key_path: Path) -> None:
        store = KeyringReceiptKeyStore(
            public_key_path=public_key_path,
            backend=_FakeKeyringBackend(),
        )
        assert store.load_private_key() is None

    def test_public_key_written_to_disk(self, public_key_path: Path) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        store = KeyringReceiptKeyStore(
            public_key_path=public_key_path,
            backend=_FakeKeyringBackend(),
        )
        key = Ed25519PrivateKey.generate()
        store.write_public_key(key.public_key())
        assert public_key_path.exists()
        assert b"BEGIN PUBLIC KEY" in public_key_path.read_bytes()
