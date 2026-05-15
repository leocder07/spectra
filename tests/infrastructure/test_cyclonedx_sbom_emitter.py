"""Tests for ``CycloneDxSbomEmitter`` (Layer 4, Q4 #58).

Validates the CycloneDX 1.5 JSON shape emitted by the adapter without
pulling in ``cyclonedx-python-lib`` — the schema is well-documented
and a few load-bearing fields are easy to assert on directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from spectra.entities.sbom import SbomComponent, SbomManifest
from spectra.infrastructure.cyclonedx_sbom_emitter import CycloneDxSbomEmitter


@pytest.fixture
def manifest() -> SbomManifest:
    return SbomManifest(
        repo_url="https://github.com/leocder07/spectra",
        repo_name="leocder07/spectra",
        components=(
            SbomComponent(
                purl="pkg:pypi/requests@2.31.0",
                name="requests",
                version="2.31.0",
                ecosystem="pypi",
                evidence_path="pyproject.toml",
            ),
            SbomComponent(
                purl="pkg:npm/react@18.2.0",
                name="react",
                version="18.2.0",
                ecosystem="npm",
                evidence_path="frontend/package.json",
            ),
        ),
        generated_at=datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC),
        spectra_version="0.8.1",
    )


class TestCycloneDxShape:
    def test_emits_cyclonedx_format_marker(self, tmp_path: Path, manifest: SbomManifest) -> None:
        out = tmp_path / "report.cdx.json"
        CycloneDxSbomEmitter().emit(manifest, out)
        doc = json.loads(out.read_text())
        assert doc["bomFormat"] == "CycloneDX"
        assert doc["specVersion"] == "1.5"

    def test_includes_serial_number_uuid_urn(self, tmp_path: Path, manifest: SbomManifest) -> None:
        out = tmp_path / "report.cdx.json"
        CycloneDxSbomEmitter().emit(manifest, out)
        doc = json.loads(out.read_text())
        assert doc["serialNumber"].startswith("urn:uuid:")
        # The bom version field is required as 1 for first emission.
        assert doc["version"] == 1

    def test_metadata_tools_includes_spectra(self, tmp_path: Path, manifest: SbomManifest) -> None:
        out = tmp_path / "report.cdx.json"
        CycloneDxSbomEmitter().emit(manifest, out)
        doc = json.loads(out.read_text())
        tools = doc["metadata"]["tools"]
        # CycloneDX 1.5 supports either a list-of-tool-objects or an
        # object with components — we use list-of-tool-objects for
        # backward compatibility with consumers that haven't migrated.
        assert any((t.get("name") == "spectra-ai") and (t.get("version") == "0.8.1") for t in tools)

    def test_metadata_root_component_describes_repo(self, tmp_path: Path, manifest: SbomManifest) -> None:
        out = tmp_path / "report.cdx.json"
        CycloneDxSbomEmitter().emit(manifest, out)
        doc = json.loads(out.read_text())
        root = doc["metadata"]["component"]
        assert root["type"] == "application"
        assert root["name"] == "leocder07/spectra"


class TestComponentRows:
    def test_each_component_has_purl_and_bom_ref(self, tmp_path: Path, manifest: SbomManifest) -> None:
        out = tmp_path / "report.cdx.json"
        CycloneDxSbomEmitter().emit(manifest, out)
        doc = json.loads(out.read_text())
        comps = doc["components"]
        assert len(comps) == 2
        for row in comps:
            assert row["type"] == "library"
            assert row["purl"].startswith("pkg:")
            assert row["bom-ref"] == row["purl"]

    def test_component_evidence_records_manifest_path(self, tmp_path: Path, manifest: SbomManifest) -> None:
        out = tmp_path / "report.cdx.json"
        CycloneDxSbomEmitter().emit(manifest, out)
        doc = json.loads(out.read_text())
        for row in doc["components"]:
            evidence = row["evidence"]["identity"]
            assert evidence["field"] == "purl"
            assert evidence["confidence"] == 1.0
            methods = evidence["methods"]
            assert any(m["technique"] == "manifest-analysis" for m in methods)

    def test_empty_manifest_emits_valid_doc_with_no_components(self, tmp_path: Path) -> None:
        empty = SbomManifest(
            repo_url="https://github.com/x/y",
            repo_name="x/y",
            components=(),
            generated_at=datetime.now(UTC),
            spectra_version="0.8.1",
        )
        out = tmp_path / "report.cdx.json"
        CycloneDxSbomEmitter().emit(empty, out)
        doc = json.loads(out.read_text())
        assert doc["components"] == []
