---
type: project
name: spectra
status: active
created: 2026-02-14
tags: [type/project, project/spectra, status/active, pinned]
---

# Spectra

**What:** CLI tool — 6 AI agents analyze entire repositories across 6 dimensions in 90 seconds.
**Tagline:** "The full spectrum of your codebase."
**Stack:** TypeScript strict, Clean Architecture, Anthropic Claude API

## The 6-Stage Pipeline

INGEST → PLAN (MetaPrompter) → ANALYZE (4 parallel specialists) → CRITIQUE → SCORE → REPORT

## The 6 Dimensions

| Dimension | Weight | Agent |
|-----------|--------|-------|
| Architecture | 25% | [[agents/profiles/architecture-agent|ArchitectureAgent]] |
| Security | 25% | SecurityAgent |
| Quality | 20% | QualityAgent |
| Documentation | 10% | DocumentationAgent |
| Maintainability | 10% | QualityAgent (secondary) |
| Performance | 10% | ArchitectureAgent (secondary) |

## Key Metrics

- Cost per run: ~$6.75 (full), ~$1.80 (quick mode)
- Runtime: 90-120s (full), ~45s (quick)
- Token budget: 800K per repo
- Agent timeout: 30s each

## Architecture

4-layer Clean Architecture: entities → use-cases → adapters → infrastructure
**The Dependency Rule is absolute** — violations = immediate rejection.

## Brand

Voice: Clear, Confident, Sharp, Warm
Colors: Spectrum Violet `#7C3AED`, Prism Amber `#F59E0B`

## Related

- [[projects/spectra/context|Team & Tools Context]]
- [[projects/spectra/stack|Tech Stack]]
- [[projects/spectra/changelog|Changelog]]
