# Spectra

**What:** CLI tool — 6 AI agents analyze entire repositories across 6 dimensions in 90 seconds.
**Tagline:** "The full spectrum of your codebase."
**Stack:** TypeScript strict, Clean Architecture, Anthropic Claude API

## The 6-Stage Pipeline
INGEST → PLAN (MetaPrompter) → ANALYZE (4 parallel specialists) → CRITIQUE → SCORE → REPORT

## The 6 Dimensions
Architecture (25%), Security (25%), Quality (20%), Documentation (10%), Maintainability (10%), Performance (10%)

## Key Metrics
- Cost per run: ~$6.75 (full), ~$1.80 (quick mode)
- Runtime: 90-120s (full), ~45s (quick)
- Token budget: 800K per repo
- Agent timeout: 30s each

## Architecture
4-layer Clean Architecture: entities → use-cases → adapters → infrastructure
Dependency Rule is absolute — violations = immediate rejection.

## Brand
Voice: Clear, Confident, Sharp, Warm
Colors: Spectrum Violet #7C3AED, Prism Amber #F59E0B
