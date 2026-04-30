---
name: Diagram rendering tooling location
description: Where Mermaid sources live and how SVGs get regenerated
type: reference
---

Mermaid sources: `docs/diagrams/*.md` (each file contains one or more ```mermaid fences).

Generated SVGs (in the same directory): `Spectra-clean_architecture.svg`, `spectra-6-stage-analysis.svg`, `spectra-uml-sequence-full-6-agent-pipeline.svg`, `spectra-domain-model-er.svg`, `spectra-design-patterns.svg`.

There is no committed renderer script as of 2026-04-29 — regeneration is a manual step using `@mermaid-js/mermaid-cli` (`mmdc -i <source.md> -o <out.svg>`). The user has a TODO to commit a renderer script; until then, document staleness in `docs/diagrams/README.md` and flag it for the next person who runs the renderer locally.
