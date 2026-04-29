# Spectra Diagrams

All architecture and design diagrams for the Spectra project.

> **SVGs are stale as of 2026-04-29.** Mermaid sources in `.md` files are the source of truth and have been updated for the Opus 4.7 migration, the new `LLMGateway` surface, the adaptive-thinking terminology, and the planned `CachePort`. The `.svg` siblings have *not* been re-rendered. Regenerate with a Mermaid CLI tool (TODO: commit a renderer script — for now use `npx -y @mermaid-js/mermaid-cli mmdc -i <source.md> -o <out.svg>`) on the diagrams listed under "Mermaid sources (current)" below.

## Mermaid sources (current)

These `.md` files contain the live Mermaid definitions. Edit these, not the SVGs.

| File | Description | Last updated |
|------|-------------|--------------|
| [`hld-system-architecture.md`](hld-system-architecture.md) | High-level system architecture (4 layers, decorator chain, 6-stage pipeline, 8 agents) | 2026-04-29 — Opus 4.7 |
| [`lld-component-interaction.md`](lld-component-interaction.md) | DI wiring, factory dispatch, decorator chain detail | 2026-04-29 — Opus 4.7 surface |
| [`lld-data-flow.md`](lld-data-flow.md) | Data transformations across the 6 pipeline stages | 2026-04-29 — Opus 4.7 labels |
| [`sequence-analysis-pipeline.md`](sequence-analysis-pipeline.md) | Full UML sequence; error path; decorator-chain call sequence | 2026-04-29 — `effort` + `task_budget` on calls |
| [`state-agent-lifecycle.md`](state-agent-lifecycle.md) | BaseAgent template lifecycle; specialist parallel execution; CritiqueAgent adaptive-thinking lifecycle | 2026-04-29 — adaptive thinking |
| [`state-pipeline.md`](state-pipeline.md) | Pipeline state machine (PipelineState transitions) | 2026-04-29 — footer notes SPEC-010 incoming |
| [`class-domain-model.md`](class-domain-model.md) | UML class diagram of all entities, ports, agents, decorators | 2026-04-29 — `LLMGateway` kwargs + planned cache entities |
| [`er-domain-entities.md`](er-domain-entities.md) | ER diagram of all domain entities | 2026-04-29 — `AgentContext` reflects new fields |
| [`design-patterns-catalog.md`](design-patterns-catalog.md) | All 11 design patterns with diagrams + file:line refs | 2026-04-29 — Factory updated; chain unchanged |

## Generated artifacts (SVG — stale)

| File | Source of truth (Mermaid) | Status |
|------|---------------------------|--------|
| `Spectra-clean_architecture.svg` | `hld-system-architecture.md` (Clean Architecture Layers section) | **Stale** — regenerate after Opus 4.7 doc update |
| `spectra-6-stage-analysis.svg` | `hld-system-architecture.md` (6-Stage Pipeline section) | **Stale** |
| `spectra-uml-sequence-full-6-agent-pipeline.svg` | `sequence-analysis-pipeline.md` | **Stale** |
| `spectra-domain-model-er.svg` | `er-domain-entities.md` | **Stale** |
| `spectra-design-patterns.svg` | `design-patterns-catalog.md` | **Stale** |

## Conventions

- All diagrams use ` ```mermaid ` code fences in Markdown — no embedded HTML.
- Color palette follows the brand: violet `#7C3AED` (primary), amber `#F59E0B` (planning), red `#EF4444` (specialists), green `#22C55E` (success), blue `#3B82F6` (entities), light violet `#A78BFA` (decorators/reports).
- When a diagram becomes too dense, split it (e.g. cache flow vs critique flow) rather than packing everything into one chart.
- Each diagram file ends with a `*Last updated: YYYY-MM-DD — short reason*` footer.

---

*Last updated: 2026-04-29 — index refresh for Opus 4.7 + CachePort doc cycle.*
