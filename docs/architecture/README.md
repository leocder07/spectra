# Spectra — Architecture

**Author:** Vivek Kumar, Head of Engineering · **Last revised:** 2026-04-30
**Baseline:** v0.6.0 · **Q1 + Q2 capabilities:** shipped · **Q3+ capabilities:** designed

This directory is the canonical, source-controlled architecture reference for Spectra. Every document is paired with a PlantUML source under [`diagrams/`](./diagrams/) and a rendered SVG. The text describes the contract; the diagrams are the picture; the code under [`src/spectra/`](../../src/spectra/) is the truth.

The 10 [Architecture Decision Records](./adr/) under `docs/architecture/adr/` capture the original architectural calls. The 10 strategy ADRs (ADR-011 through ADR-020, in `spectra-wt-strategy`) capture the Q1 + Q2 capability designs — every one of them is now shipped in v0.6.0.

---

## Document map

| # | Document | Status | Purpose |
|---|----------|--------|---------|
| 01 | [System Context](./01-system-context.md) | Stable | Who Spectra serves; what surrounds it (C4 L1) |
| 02 | [Component Architecture](./02-component-architecture.md) | Stable | The 4 Clean-Architecture layers + ports (C4 L2 + L3) |
| 03 | [Domain Model](./03-domain-model.md) | Stable | Frozen Pydantic entities + value objects + invariants (Q2 entities now shipped) |
| 04 | [Pipeline Flow](./04-pipeline-flow.md) | Stable | The 6-stage pipeline (+ Stage 1.5), happy / cached / compromised |
| 05 | [Agent Architecture](./05-agent-architecture.md) | Stable | 8 agents, parallelism, decorator chain |
| 06 | [Cache Architecture](./06-cache-architecture.md) | Stable | 4-phase cache, per-row HMAC, per-`$UID` namespace, SQLCipher (v0.6.0) |
| 07 | [Security Architecture](./07-security-architecture.md) | Stable | Threat model, v0.5.0 hardening, v0.6.0 audit + receipts + policy + waivers |
| 08 | [Data Flow & Privacy](./08-data-flow-and-privacy.md) | Stable | Per-data-class flow, retention, privacy boundary, audit edges (v0.6.0) |
| 09 | [Extensibility](./09-extensibility.md) | Q6 designed | Plugin system (Skills, Specialists, MCP) |
| 10 | [Deployment & Release](./10-deployment-and-release.md) | Stable | CLI, GitHub Action, PyPI, Sigstore, OIDC |

Status legend:
- **Stable** — shipped in the current baseline (v0.6.0); the documented contract.
- **Q3 designed**, **Q4 designed**, **Q6 designed** — captured in ADRs but not on the immediate runway. The status flips when the corresponding release lands.

---

## Status table — capability ↔ ADR ↔ ship

| Capability | Source ADR | v0.5.0 (Q1) | v0.6.0 (Q2) | Beyond |
|------------|-----------|-------------|-------------|--------|
| Per-file nonce data fences | [ADR-011](../../docs/architecture/adr/) (strategy 011) | Shipped | Carried | — |
| CritiqueAgent adversarial check | strategy ADR-011 §2 | Shipped | Carried | — |
| Adversarial harness (≥80% catch) | strategy ADR-011 §4 | 100% (20/20) | Maintained | Quarterly refresh |
| Per-row HMAC cache | strategy ADR-012 | Shipped | Carried | — |
| Per-`$UID` cache namespace | strategy ADR-012 | Shipped | Carried | — |
| Secret pre-flight + `.gitignore` | roadmap #6 | Shipped | Carried | — |
| Markdown-safe PR comment | roadmap #4 | Shipped | Carried | — |
| Indicative-analysis disclaimer | roadmap #61 | Shipped | Carried | — |
| SLSA L3 + Sigstore + SECURITY.md | roadmap #7-#10 | Shipped | Carried | — |
| `task_budget` per-agent + cost tracker | strategy ADR-013 | Critique only | Shipped (`CostTrackerPort`) | — |
| `--max-cost-usd` budget enforcement | roadmap #5 | — | Shipped (SPEC-014) | — |
| Audit log (JSON Lines + OTLP) | strategy ADR-018 | — | Shipped (`AuditPort`) | — |
| Ed25519 signed scan receipt | roadmap #57 | — | Shipped (`spectra verify`) | — |
| Encrypted cache (SQLCipher) | roadmap #13 | — | Shipped (`spectra cache shred`) | — |
| `.spectra-policy.yml` + waivers | roadmap #17 + #18 | — | Shipped (SPEC-013, signed waivers, inline pragma) | — |
| Severity-gate + non-validated stamp | roadmap #19 + #20 | — | Shipped (`--fail-on`, `validation_status`) | — |
| Dual-mode classification render | strategy ADR-018 + roadmap #56 | — | Shipped (`--classification`) | — |
| DPA + sub-processor docs | roadmap #11 | — | Shipped (legal pack) | — |
| `.spectra.yml` config substrate | strategy ADR-020 | — | Shipped (YAML policy + waivers) | — |
| Anthropic Memory Stores per-team | strategy ADR-014 | — | — | Q4 designed |
| `query_codebase` use case | strategy ADR-015 | — | — | Q4 designed |
| Distributed cache adapters | strategy ADR-019 | — | — | Q3 designed |
| Managed Agents gateway | strategy ADR-016 | — | — | Q5 designed |
| Plugin architecture + Skills | strategy ADR-017 | — | — | Q6 designed |

---

## Diagrams

All 19 source diagrams are in [`diagrams/`](./diagrams/), authored in PlantUML and committed alongside the rendered SVGs. PlantUML was chosen because the source is text (diff-able, version-controllable), the renderer is deterministic, and the output is print-quality. Mermaid was rejected for limited expressiveness on C4 + sequence diagrams; Excalidraw was rejected for being binary-first and inappropriately hand-drawn.

### Render locally

```bash
# macOS
brew install plantuml

# Linux
sudo apt install plantuml

# Render every diagram in this directory
plantuml -tsvg docs/architecture/diagrams/*.puml

# Render a single diagram
plantuml -tsvg docs/architecture/diagrams/04-pipeline-sequence.puml
```

The render command takes ~10 seconds for the full set on a 2024 MacBook. CI does not currently render diagrams — humans regenerate them when sources change and commit both `.puml` and `.svg`.

---

## Conventions

- **Color palette** is consistent across diagrams: violet `#7C3AED` for Spectra components, amber `#F59E0B` for ports, green `#22C55E` for healthy paths and adapters, red `#EF4444` for security boundaries / failed paths, grey `#9CA3AF` for designed-but-not-shipped elements (Q3+).
- **ADR cross-reference** uses absolute paths to the strategy worktree where the ADRs live: e.g. `../../spectra-wt-strategy/docs/strategy/architecture/ADR-011-prompt-injection-isolation.md`.
- **Code references** use `path:line` form pointing at the v0.6.0 baseline (`src/spectra/...`).
- **Q3+-designed elements** are stated as such inline. They are present in the diagrams (greyed/dashed) so the documents can be promoted to "shipped" with a single status flip per element when the corresponding release lands.

---

## How to use this directory

| If you are… | Read first |
|-------------|------------|
| New to the codebase | [01-system-context](./01-system-context.md) → [02-component-architecture](./02-component-architecture.md) → [04-pipeline-flow](./04-pipeline-flow.md) |
| Reviewing a security finding | [07-security-architecture](./07-security-architecture.md) → [08-data-flow-and-privacy](./08-data-flow-and-privacy.md) |
| Auditing for procurement | [07-security-architecture](./07-security-architecture.md) → [10-deployment-and-release](./10-deployment-and-release.md) → SECURITY.md |
| Adding a new specialist | [05-agent-architecture](./05-agent-architecture.md) → [09-extensibility](./09-extensibility.md) |
| Touching the cache | [06-cache-architecture](./06-cache-architecture.md) → strategy ADR-012 |
| Wiring an integration | [01-system-context](./01-system-context.md) → [10-deployment-and-release](./10-deployment-and-release.md) → action.yml |

---

## Maintenance

These documents are part of the codebase. They are reviewed alongside the code changes that affect them. The CI pipeline does not lint Markdown today; the responsibility for keeping the docs in sync with the code lives with whoever lands the change. Stale documents are a defect.

When a designed-but-unshipped capability ships:
1. Flip the entry in the status table in this README.
2. Flip the document-level status banner in the relevant `0X-*.md`.
3. Promote the dashed-grey element in the affected diagram to solid.
4. Re-render the diagram.
5. Add a `### Documentation` line to the CHANGELOG entry.
