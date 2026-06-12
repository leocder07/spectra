# Spectra Diagrams

All architecture and design diagrams for the Spectra project. The Mermaid sources in `.md` files are the source of truth; SVG and Excalidraw artifacts are generated from them.

## Tier 1 — System view (C4 Levels 1-2)

| File | Format | Description |
|------|--------|-------------|
| [`system-context.md`](system-context.md) | Mermaid `flowchart` | C4 L1: Spectra in its environment — Developer + GitHub PR upstream; Anthropic API + GitHub.com + PyPI + local filesystem downstream |
| [`excalidraw/system-context.excalidraw`](excalidraw/system-context.excalidraw) | Excalidraw JSON | Editorial copy of the same diagram, hand-laid for slides + workshops |
| [`container-view.md`](container-view.md) | Mermaid `flowchart` | C4 L2: Inside the Spectra package — 4 Clean Architecture layers, every module placed, dependency arrows pointing inward |

## Tier 2 — Pipeline + Cache

| File | Format | Description |
|------|--------|-------------|
| [`sequence-analysis-pipeline.md`](sequence-analysis-pipeline.md) | Mermaid `sequenceDiagram` + `flowchart` | Full pipeline sequence with Phase 2 (full-report) and Phase 3 (per-batch) cache decision points; cache-decision flowchart; SPEC-010 degrade path; decorator-chain call sequence |
| [`cache-architecture.md`](cache-architecture.md) | Mermaid `erDiagram` + `flowchart` | Cache deep-dive: 4-table SQLite schema, composite key composition per phase, invalidation matrix, `bind_run_context` flow, hit-log telemetry pipeline |
| [`excalidraw/cache-schema.excalidraw`](excalidraw/cache-schema.excalidraw) | Excalidraw JSON | Editorial 4-table layout suitable for slide-deck use |

## Tier 3 — Component / Class view

| File | Format | Description |
|------|--------|-------------|
| [`class-domain-model.md`](class-domain-model.md) | Mermaid `classDiagram` | All Pydantic models, Protocol interfaces, agent class hierarchy. Includes `BatchPrompt`, `BatchCacheKey`, `RepoCacheKey`, `CacheEntry`, `CacheStats`, `PipelineContext`, `CacheVersions`, `SchemaVersion`, and the full `CachePort` Protocol surface |
| [`er-domain-entities.md`](er-domain-entities.md) | Mermaid `erDiagram` | ER diagram of all domain entities |
| [`design-patterns-catalog.md`](design-patterns-catalog.md) | Mermaid (multiple) | All 11+ design patterns with diagrams + file:line refs |
| [`lld-component-interaction.md`](lld-component-interaction.md) | Mermaid | DI wiring, factory dispatch, decorator chain detail |
| [`lld-decorator-chain.md`](lld-decorator-chain.md) | Mermaid `classDiagram` + `sequenceDiagram` + `flowchart` | Dedicated `LLMGateway` / decorator chain LLD covering the Opus 4.7 surface (`effort` + `task_budget_tokens`), per-agent dispatch, and both standard and adaptive-thinking sequence paths |
| [`lld-data-flow.md`](lld-data-flow.md) | Mermaid | Data transformations across the 6 pipeline stages |

## Tier 4 — Distribution

| File | Format | Description |
|------|--------|-------------|
| [`github-action-flow.md`](github-action-flow.md) | Mermaid `sequenceDiagram` + `flowchart` | End-to-end PR flow for `leocder07/spectra@v1`, idempotent `<!-- SPECTRA -->` comment pattern, the token-abuse scenario this repo's CI deliberately avoids (per [ADR-010](../architecture/adr/ADR-010-no-self-dogfooding.md)) |

## Lifecycle / state diagrams

| File | Format | Description |
|------|--------|-------------|
| [`hld-system-architecture.md`](hld-system-architecture.md) | Mermaid (multiple) | High-level system architecture (4 layers, decorator chain, 6-stage pipeline, 8 agents) |
| [`state-pipeline.md`](state-pipeline.md) | Mermaid `stateDiagram` | Pipeline state machine (`PipelineState` transitions) |
| [`state-agent-lifecycle.md`](state-agent-lifecycle.md) | Mermaid `stateDiagram` | `BaseAgent` template lifecycle; specialist parallel execution; `CritiqueAgent` adaptive-thinking lifecycle |

## Generated SVG artifacts

These are downstream renders of the Mermaid sources above. They are checked in for inline previewing in places that don't render Mermaid (e.g. some package registries and PR review tools).

| SVG | Source-of-truth Mermaid block | Last regenerated |
|-----|------------------------------|------------------|
| `Spectra-clean_architecture.svg` | `hld-system-architecture.md` (Clean Architecture Layers section) | 2026-04-29 |
| `spectra-6-stage-analysis.svg` | `hld-system-architecture.md` (6-Stage Pipeline section) | 2026-04-29 |
| `spectra-uml-sequence-full-6-agent-pipeline.svg` | `sequence-analysis-pipeline.md` (Complete Pipeline Sequence) | 2026-04-29 (refreshed for cache decision points) |
| `spectra-domain-model-er.svg` | `er-domain-entities.md` | 2026-04-29 |
| `spectra-design-patterns.svg` | `design-patterns-catalog.md` (Patterns Overview) | 2026-04-29 |

The 4 new diagrams added in this docs refresh (`system-context.md`, `container-view.md`, `cache-architecture.md`, `lld-decorator-chain.md`, `github-action-flow.md`) do not yet have canonical SVG companions. Render on demand — the commands below produce SVG in one step.

## Regeneration commands

### Mermaid → SVG

The toolchain expects either a single mermaid block in a `.mmd` file or a `.md` file with one or more ```` ```mermaid ```` blocks. Two equivalent paths:

```bash
# Render every block in a doc into a single multi-image SVG
npx -y @mermaid-js/mermaid-cli mmdc -i docs/diagrams/system-context.md -o /tmp/sysctx.svg -b white

# Or extract a single block to a .mmd file first, then render
python3 - <<'PY'
import re
src = open('docs/diagrams/sequence-analysis-pipeline.md').read()
blocks = re.findall(r'```mermaid\n(.*?)```', src, flags=re.DOTALL)
open('/tmp/seq.mmd', 'w').write(blocks[0])  # the first block (full pipeline)
PY
npx -y @mermaid-js/mermaid-cli mmdc -i /tmp/seq.mmd -o docs/diagrams/spectra-uml-sequence-full-6-agent-pipeline.svg -b white
```

If `mmdc` is installed globally (`npm i -g @mermaid-js/mermaid-cli`), drop the `npx -y @mermaid-js/mermaid-cli` prefix.

### Excalidraw

Excalidraw files (`.excalidraw`) are JSON. Open them directly at https://excalidraw.com via **Open** → **From File**. To export to SVG/PNG, use the in-app **Export** menu — there is no recommended CLI workflow for the headless render of these.

To validate that an Excalidraw file parses (CI sanity check):

```bash
python3 -c "import json, sys; d = json.load(open(sys.argv[1])); assert d['type'] == 'excalidraw' and d['version'] == 2; print('OK', len(d['elements']), 'elements')" docs/diagrams/excalidraw/system-context.excalidraw
```

### Drawio

Drawio files (`.drawio`) are XML in the mxGraph format. Open at https://app.diagrams.net via **File → Open**. We currently have no `.drawio` files checked in — the team standardized on Mermaid for review-friendly text + Excalidraw for editorial polish.

To validate that a `.drawio` file parses:

```bash
python3 -c "import xml.etree.ElementTree as ET, sys; ET.parse(sys.argv[1]); print('OK')" path/to/diagram.drawio
```

## Conventions

- All diagrams use ` ```mermaid ` code fences in Markdown — no embedded HTML.
- Color palette follows the brand: violet `#7C3AED` (primary), amber `#F59E0B` (planning), red `#EF4444` (specialists), green `#22C55E` (success), blue `#3B82F6` (entities), light violet `#A78BFA` (decorators/reports).
- When a diagram becomes too dense, split it (e.g. cache flow vs critique flow) rather than packing everything into one chart.
- Each diagram file ends with a `*Last updated: YYYY-MM-DD — short reason*` footer.
- Avoid `;` and ` :` (colon-space-end-of-text-on-its-own-line) inside Mermaid `Note over` blocks and node labels — both confuse the parser. Use em-dashes (`—`) or commas instead.
- Avoid the keyword `call` as a `classDef` name in flowcharts — it is reserved.

---

*Last updated: 2026-04-29 — added system-context, container-view, cache-architecture, lld-decorator-chain, github-action-flow; regenerated the canonical sequence SVG for the cache pipeline.*
