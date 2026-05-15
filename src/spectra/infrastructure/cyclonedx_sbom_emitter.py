"""``CycloneDxSbomEmitter`` — write an ``SbomManifest`` as CycloneDX 1.5 JSON (Q4 #58).

Builds the JSON document manually rather than pulling in
``cyclonedx-python-lib`` — the schema is small enough that the
adapter cost is lower than the dep-management cost (transitive supply
chain, version pinning, lockfile churn).

Schema reference: CycloneDX 1.5 (the 2024 standard).
https://cyclonedx.org/docs/1.5/json/

The emitter targets the load-bearing fields auditors and SCA tools
read first:

- ``bomFormat`` + ``specVersion`` + ``serialNumber`` + ``version`` —
  document identity. ``serialNumber`` is a stable URN (uuid4) per
  emission so consumers can dedupe.
- ``metadata.tools`` — Spectra's own provenance (version, vendor).
- ``metadata.component`` — root component representing the analysed
  repo (so the SBOM is self-describing).
- ``components[]`` — the dependency rows, each with a ``purl``
  (canonical identity) and ``evidence.identity`` proving where in
  the source we found the declaration.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from spectra.entities.sbom import SbomComponent, SbomManifest


class CycloneDxSbomEmitter:
    """Layer 4 adapter that serializes ``SbomManifest`` to CycloneDX 1.5 JSON."""

    def emit(self, manifest: SbomManifest, out_path: Path) -> None:
        """Write the SBOM JSON to ``out_path``.

        Overwrites any existing file. The caller is responsible for
        choosing a sibling-of-report path (``<report>.cdx.json``).
        """
        doc = self._build_document(manifest)
        out_path.write_text(json.dumps(doc, indent=2, sort_keys=False))

    def _build_document(self, manifest: SbomManifest) -> dict[str, object]:
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": f"urn:uuid:{uuid.uuid4()}",
            "version": 1,
            "metadata": self._build_metadata(manifest),
            "components": [self._build_component(c) for c in manifest.components],
        }

    def _build_metadata(self, manifest: SbomManifest) -> dict[str, object]:
        return {
            "timestamp": manifest.generated_at.isoformat(),
            "tools": [
                {
                    "vendor": "Anthropic",
                    "name": "spectra-ai",
                    "version": manifest.spectra_version,
                },
            ],
            "component": {
                "type": "application",
                "name": manifest.repo_name,
                "purl": self._root_purl(manifest),
            },
        }

    @staticmethod
    def _root_purl(manifest: SbomManifest) -> str:
        # The analysed repo is itself a "component" in CycloneDX terms.
        # We synthesise a purl from the repo URL when it's a git URL,
        # otherwise fall back to a generic local-source purl.
        if manifest.repo_url.startswith(("https://github.com/", "git@github.com:")):
            slug = manifest.repo_name.replace(" ", "-").lower()
            return f"pkg:github/{slug}"
        return f"pkg:generic/{manifest.repo_name}"

    @staticmethod
    def _build_component(component: SbomComponent) -> dict[str, object]:
        row: dict[str, object] = {
            "type": "library",
            "bom-ref": component.purl,
            "purl": component.purl,
            "name": component.name,
            "evidence": {
                "identity": {
                    "field": "purl",
                    "confidence": 1.0,
                    "methods": [
                        {
                            "technique": "manifest-analysis",
                            "confidence": 1.0,
                            "value": component.evidence_path,
                        },
                    ],
                },
            },
        }
        if component.version is not None:
            row["version"] = component.version
        return row


__all__ = ["CycloneDxSbomEmitter"]
