---
type: decision
project: spectra
status: accepted
impact: critical
created: 2026-02-14
tags: [type/decision, project/spectra, priority/p0, pinned]
---

# ADR-002: Grand Prize Sprint Plan — 48 Hours

## Decision
Go for full 6-agent pipeline in 48 hours. Target grand prize ($50K).

## Key Changes from Original Plan
1. Opus 4.6 pricing is 3x cheaper ($5/$25 vs $15/$75) — COGS ~$7.84/run not $22.50
2. Budget is $500 (not $5,500) — gives ~63 runs, enough for dev + demo
3. Must be open source on GitHub
4. Video is the #1 judged artifact — invest heavily in recording
5. No prior code — everything from scratch starting NOW

## Sprint Milestones
| Hour | Must Have |
|------|----------|
| 2 | Repo created, deps installed, structure scaffolded |
| 8 | All entities, types, Zod schemas, interfaces done |
| 12 | MetaPrompter + 1 specialist producing valid output |
| 16 | All 4 specialists parallel + CritiqueAgent working |
| 20 | CLI `spectra analyze <repo>` works end-to-end |
| 28 | 3+ repos tested, README written |
| 34 | Video script ready, demo stable |
| 40 | Video recorded |
| 44 | Final polish, submission prep |
| 46 | SUBMIT (2 hours early for safety) |

## Cut Triggers
- Hour 16: No MetaPrompter + 2 specialists → drop to 3 agents
- Hour 22: No HTML report → terminal-only + Markdown
- Hour 28: < 3 repos → 1 repo demo, note others in README
- Hour 34: No video script → simpler demo, focus on live analysis
