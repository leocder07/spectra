# System Context Diagram (C4 Level 1)

Spectra in its environment — the actors who invoke it and the external systems it depends on.

> **Editor's choice:** the Excalidraw version at [`excalidraw/system-context.excalidraw`](excalidraw/system-context.excalidraw) is the polished hand-laid-out edition. The Mermaid version below is the source of truth for CI rendering and review.

```mermaid
flowchart LR
    classDef person      fill:#dbeafe,stroke:#1e3a8a,stroke-width:2px,color:#1e293b
    classDef system      fill:#ede9fe,stroke:#7C3AED,stroke-width:4px,color:#1e293b
    classDef external    fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#1e293b
    classDef storage     fill:#dcfce7,stroke:#166534,stroke-width:2px,color:#1e293b
    classDef distribution fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#1e293b

    Dev["<b>Developer</b><br/>[Person]<br/>Runs spectra analyze<br/>from a terminal"]:::person
    PR["<b>GitHub PR</b><br/>[External CI]<br/>pull_request event<br/>invokes the Action"]:::person

    Spectra(["<b>Spectra CLI</b><br/>[Software System]<br/>8 AI agents · 6 dimensions<br/>Clean Architecture · Python 3.12+<br/>6-stage pipeline + cache"]):::system

    Anthropic["<b>Anthropic API</b><br/>[External SaaS]<br/>Claude Opus 4.7<br/>all 8 agents"]:::external
    GitHub["<b>GitHub.com</b><br/>[External Service]<br/>Git clone source<br/>HTTPS only"]:::external
    PyPI["<b>PyPI</b><br/>[Distribution]<br/>pip install spectra-ai<br/>also installed by Action"]:::distribution
    FS[("<b>Local Filesystem</b><br/>[OS]<br/>~/.cache/spectra/cache.db (SQLite WAL)<br/>spectra-report.{html,json,sarif}")]:::storage

    Dev      -- "spectra analyze ."          --> Spectra
    PR       -- "uses: spectra-ai/spectra@v1" --> Spectra
    Spectra  -- "HTTPS · streaming /messages" --> Anthropic
    Spectra  -- "git clone (depth=1)"        --> GitHub
    Spectra  <-- "cache R/W · report write"  --> FS
    PyPI     -. "install (cold path)"        .-> Spectra
```

## Actors and external systems

| Element | Type | Why it matters |
|---------|------|----------------|
| **Developer** | Person | Primary user — invokes `spectra analyze .` against a local checkout or HTTPS URL |
| **GitHub PR** | External CI actor | Downstream consumers wire the composite Action into `.github/workflows/*.yml` and Spectra runs on every PR |
| **Spectra CLI** | Software system in scope | The 4-layer Clean Architecture Python package distributed on PyPI |
| **Anthropic API** | External SaaS | All 8 agents call `https://api.anthropic.com/v1/messages` via the streaming endpoint |
| **GitHub.com** | External service | `GitAdapter` clones repos via HTTPS only — `git://`, `ssh://`, `file://` are rejected at the protocol layer |
| **PyPI** | Distribution channel | Single canonical artifact (`spectra-ai`); the GitHub Action installs from here on every run |
| **Local Filesystem** | OS storage | SQLite cache DB (`cache.db` + WAL sidecars) and rendered reports are local-only |

## Distribution model

Two install paths, one PyPI package:

```
                ┌──────────────────┐
                │  spectra-ai      │   <- single source artifact
                │  (PyPI package)  │
                └────────┬─────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
┌───────▼─────────┐               ┌───────▼─────────┐
│ pip install     │               │ Composite Action│
│ spectra-ai      │               │ spectra-ai/     │
│ + run locally   │               │ spectra@v1      │
└─────────────────┘               └─────────────────┘
   Local developer                       CI / PR
```

The Action is just YAML that installs `spectra-ai` on the runner and shells out to `spectra analyze`. Versioning lives at the PyPI release; the Action consumes whatever is published. See [ADR-007](../architecture/adr/ADR-007-github-action-distribution.md).

## Deliberate non-dogfooding

This repo's own CI does not run `spectra-ai/spectra@v1` on its own pull requests. The reasoning is recorded in [ADR-010](../architecture/adr/ADR-010-no-self-dogfooding.md) — token-abuse risk on PR-triggered workflows. Downstream consumers are expected to wire the Action into their own repos with their own API keys; we publish the Action and exercise it externally rather than on this repository.

---

*Last updated: 2026-04-29 — initial system-context diagram covering the cache pipeline + Action distribution.*
