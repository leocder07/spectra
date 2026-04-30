---
name: ADR discipline (append-only, supersede via new ADR)
description: How to handle ADR changes — never edit Accepted ADRs, always supersede with a new one
type: feedback
---

ADRs are append-only once Accepted. When a decision changes:
- Write a NEW ADR with status "Accepted" that explicitly says "Supersedes ADR-NNN".
- Leave the original ADR untouched (do not flip its status, do not edit its body).
- The new ADR's "References" should link back to the superseded one.

**Why:** ADRs are a historical record. Editing them in place destroys the trail of how the team's thinking evolved. Future readers want to see both the old decision (why we made it) and the new one (why we changed). The user explicitly asked for option (a) — append-only — when ADR-003's terminology became wrong with the Opus 4.7 migration.

**How to apply:** If a future task asks to "update" an ADR, push back: write a new ADR that supersedes the old one instead. Only typo/link fixes are acceptable as in-place edits to Accepted ADRs.
