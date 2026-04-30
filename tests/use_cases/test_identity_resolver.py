"""Tests for the IdentityResolver helper (Layer 2 use-case)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from spectra.use_cases.identity_resolver import (
    HASHED_ID_LEN,
    hash_actor,
    resolve_actor,
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in (
        "SPECTRA_USER_ID",
        "SPECTRA_ACTOR",
        "GITHUB_ACTIONS",
        "GITHUB_REPOSITORY",
        "GITHUB_REF",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


class TestResolveActorPrecedence:
    def test_env_var_wins_over_git(self, monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
        monkeypatch.setenv("SPECTRA_ACTOR", "alice@enterprise.com")
        with patch("spectra.use_cases.identity_resolver._git_email", return_value="bob@laptop"):
            ident = resolve_actor()
        assert ident.actor == "alice@enterprise.com"
        assert ident.source == "env"
        assert ident.confidence == "medium"

    def test_legacy_env_var_recognized(self, monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
        monkeypatch.setenv("SPECTRA_USER_ID", "ci@build")
        ident = resolve_actor()
        assert ident.actor == "ci@build"
        assert ident.source == "env"

    def test_oidc_takes_precedence_over_git_when_in_ci(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_REPOSITORY", "leocder07/spectra")
        monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
        with patch("spectra.use_cases.identity_resolver._git_email", return_value="bob@laptop"):
            ident = resolve_actor()
        assert ident.source == "oidc"
        assert ident.confidence == "high"
        assert "leocder07/spectra" in ident.actor
        assert "main" in ident.actor

    def test_git_email_fallback(self, monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
        with patch("spectra.use_cases.identity_resolver._git_email", return_value="dev@laptop"):
            ident = resolve_actor()
        assert ident.actor == "dev@laptop"
        assert ident.source == "git"
        assert ident.confidence == "medium"

    def test_hostname_fallback_when_nothing_else(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
    ) -> None:
        with (
            patch("spectra.use_cases.identity_resolver._git_email", return_value=None),
            patch("spectra.use_cases.identity_resolver._login_user", return_value="dev"),
            patch("spectra.use_cases.identity_resolver._hostname", return_value="laptop"),
        ):
            ident = resolve_actor()
        assert ident.actor == "dev@laptop"
        assert ident.source == "hostname"
        assert ident.confidence == "low"


class TestHashActor:
    def test_hash_is_16_chars(self) -> None:
        h = hash_actor("alice@example.com")
        assert len(h) == HASHED_ID_LEN

    def test_hash_is_deterministic(self) -> None:
        assert hash_actor("alice@example.com") == hash_actor("alice@example.com")

    def test_hash_differs_for_different_inputs(self) -> None:
        assert hash_actor("alice@example.com") != hash_actor("bob@example.com")

    def test_hash_matches_blake2b_truncation(self) -> None:
        expected = hashlib.blake2b(b"alice@example.com", digest_size=8).hexdigest()
        assert hash_actor("alice@example.com") == expected
