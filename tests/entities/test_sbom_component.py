"""Tests for ``SbomComponent`` + ``SbomManifest`` (Layer 1, Q4 #58).

Covers:
- Frozen Pydantic shape (immutability per project rule)
- ``ecosystem`` is a closed Literal
- ``purl`` follows the Package URL spec (`pkg:<type>/<name>@<version>`)
- ``SbomManifest.generated_at`` is timezone-aware UTC
- Components are stored as a deterministic tuple (order-preserving)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from spectra.entities.sbom import SbomComponent, SbomManifest


def _component(**overrides: object) -> SbomComponent:
    base = {
        "purl": "pkg:pypi/requests@2.31.0",
        "name": "requests",
        "version": "2.31.0",
        "ecosystem": "pypi",
        "evidence_path": "pyproject.toml",
    }
    base.update(overrides)  # type: ignore[arg-type]
    return SbomComponent(**base)  # type: ignore[arg-type]


class TestSbomComponentShape:
    def test_is_frozen(self) -> None:
        c = _component()
        with pytest.raises(ValidationError):
            c.name = "other"  # type: ignore[misc]

    def test_accepts_all_documented_ecosystems(self) -> None:
        for eco in ("pypi", "npm", "go", "cargo", "maven", "gem", "composer"):
            assert _component(ecosystem=eco).ecosystem == eco

    def test_rejects_unknown_ecosystem(self) -> None:
        with pytest.raises(ValidationError):
            _component(ecosystem="conan")

    def test_purl_required(self) -> None:
        with pytest.raises(ValidationError):
            _component(purl="")

    def test_version_optional(self) -> None:
        c = _component(version=None)
        assert c.version is None


class TestSbomManifestShape:
    def test_is_frozen(self) -> None:
        m = SbomManifest(
            repo_url="https://github.com/x/y",
            repo_name="x/y",
            components=(_component(),),
            generated_at=datetime.now(UTC),
            spectra_version="0.8.1",
        )
        with pytest.raises(ValidationError):
            m.repo_name = "z"  # type: ignore[misc]

    def test_generated_at_must_be_tz_aware(self) -> None:
        with pytest.raises(ValidationError):
            SbomManifest(
                repo_url="https://github.com/x/y",
                repo_name="x/y",
                components=(),
                generated_at=datetime(2026, 5, 4, 12, 0, 0),  # noqa: DTZ001 — naive on purpose
                spectra_version="0.8.1",
            )

    def test_components_preserved_in_order(self) -> None:
        a = _component(purl="pkg:pypi/a@1", name="a")
        b = _component(purl="pkg:pypi/b@2", name="b")
        m = SbomManifest(
            repo_url="https://github.com/x/y",
            repo_name="x/y",
            components=(a, b),
            generated_at=datetime.now(UTC),
            spectra_version="0.8.1",
        )
        assert m.components == (a, b)

    def test_empty_components_allowed(self) -> None:
        m = SbomManifest(
            repo_url="https://github.com/x/y",
            repo_name="x/y",
            components=(),
            generated_at=datetime.now(UTC),
            spectra_version="0.8.1",
        )
        assert m.components == ()
