"""Tests for keyring-side shred — drops both the HMAC and encryption-key entries."""

from __future__ import annotations

import pytest

from spectra.entities.errors import AgentError
from spectra.infrastructure.keyring_adapter import KeyringSecretAdapter


class _FakeKeyring:
    """Stand-in for the real ``keyring`` module — store + lookup in memory."""

    def __init__(self, *, fail: bool = False) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self._fail = fail
        self.deletes: list[tuple[str, str]] = []

    def get_password(self, service: str, account: str) -> str | None:
        if self._fail:
            msg = "no keyring backend available"
            raise RuntimeError(msg)
        return self._store.get((service, account))

    def set_password(self, service: str, account: str, password: str) -> None:
        if self._fail:
            msg = "no keyring backend available"
            raise RuntimeError(msg)
        self._store[(service, account)] = password

    def delete_password(self, service: str, account: str) -> None:
        if self._fail:
            msg = "no keyring backend available"
            raise RuntimeError(msg)
        self.deletes.append((service, account))
        self._store.pop((service, account), None)


class TestKeyringShred:
    def test_shred_removes_the_hmac_entry(self) -> None:
        """``shred`` drops the per-user HMAC password from the keyring."""
        kr = _FakeKeyring()
        adapter = KeyringSecretAdapter(uid="42", backend=kr)
        adapter.get()  # generate + persist
        assert kr.get_password("spectra-cache-hmac", "42") is not None

        adapter.shred()

        assert kr.get_password("spectra-cache-hmac", "42") is None
        assert ("spectra-cache-hmac", "42") in kr.deletes

    def test_shred_is_idempotent_when_no_entry_exists(self) -> None:
        """Shredding a never-stored secret must not raise."""
        kr = _FakeKeyring()
        adapter = KeyringSecretAdapter(uid="42", backend=kr)
        # No prior get(); password was never written.
        adapter.shred()  # must not raise

    def test_shred_clears_in_memory_cache(self) -> None:
        """After shred, get() generates a fresh secret rather than returning the cached one."""
        kr = _FakeKeyring()
        adapter = KeyringSecretAdapter(uid="42", backend=kr)
        first = adapter.get()
        adapter.shred()
        second = adapter.get()
        # New random bytes — vanishingly small chance of collision.
        assert first.value != second.value

    def test_shred_failure_raises_spec_010(self) -> None:
        """Backend failures during shred surface as SPEC-010 (degrade at composition root)."""
        kr = _FakeKeyring()
        # Seed before flipping the failure switch.
        adapter = KeyringSecretAdapter(uid="42", backend=kr)
        adapter.get()
        kr._fail = True
        with pytest.raises(AgentError) as exc:
            adapter.shred()
        assert exc.value.error.code == "SPEC-010"
