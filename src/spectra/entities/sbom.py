"""SBOM domain entities (Layer 1, Q4 #58).

Implements the per-scan Software Bill of Materials shape consumed by
``CycloneDxSbomEmitter`` (Layer 4) and produced by the manifest
detectors in ``use_cases/sbom_detection.py`` (Layer 2 helpers).

The shape is intentionally provider-agnostic — components carry a
Package URL (``purl``) which the emitter renders verbatim into the
CycloneDX 1.5 ``components[].purl`` field. No CycloneDX-specific types
leak into Layer 1; if we add an SPDX 3 emitter later, the same entity
serves both.

The first slice supports three ecosystems (``pypi``, ``npm``, ``go``)
matching the three manifest detectors that ship in the same PR. The
``ecosystem`` Literal lists every value the emitter knows how to render
into a valid purl prefix; adding an ecosystem requires bumping this
Literal AND adding the corresponding detector (forces the change to
land in lockstep, no half-baked ecosystems).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SbomEcosystem = Literal[
    "pypi",
    "npm",
    "go",
    "cargo",
    "maven",
    "gem",
    "composer",
]


class SbomComponent(BaseModel):
    """One dependency component the analysed repo declares.

    Attributes:
        purl: Package URL per the spec — ``pkg:<type>/<name>@<version>``.
            Required and must be non-empty; emitters use it as the
            ``bom-ref`` so component cross-references stay stable.
        name: Human-readable package name (``react``, ``@anthropic-ai/sdk``,
            ``github.com/spf13/cobra``).
        version: Declared version string. ``None`` when the manifest
            pins by tag/branch (Go's pseudo-versions, npm tarball URLs)
            and the detector cannot resolve a semantic version.
        ecosystem: Closed Literal — see ``SbomEcosystem``. Adding a
            value requires a matching detector.
        evidence_path: Path within the analysed repo where this
            component's declaration was found (``pyproject.toml``,
            ``frontend/package.json``, ``go.mod``). Surfaced by the
            emitter as ``evidence.identity.methods[].value`` so an
            auditor can trace every component back to its source.
    """

    model_config = ConfigDict(frozen=True)

    purl: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str | None
    ecosystem: SbomEcosystem
    evidence_path: str = Field(min_length=1)


class SbomManifest(BaseModel):
    """The full SBOM for one scan — the unit the emitter writes to disk."""

    model_config = ConfigDict(frozen=True)

    repo_url: str = Field(min_length=1)
    repo_name: str = Field(min_length=1)
    components: tuple[SbomComponent, ...]
    generated_at: datetime
    spectra_version: str = Field(min_length=1)

    @field_validator("generated_at")
    @classmethod
    def _require_tz_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError(
                "SbomManifest.generated_at must be timezone-aware (UTC). "
                "Naive datetimes are rejected to prevent drift across "
                "machines reading the same SBOM file.",
            )
        return value if value.tzinfo == UTC else value.astimezone(UTC)


__all__ = ["SbomComponent", "SbomEcosystem", "SbomManifest"]
