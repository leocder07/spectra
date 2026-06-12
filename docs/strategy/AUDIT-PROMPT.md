# Reusable project audit

A standing, multi-agent audit you can re-run any time you need an honest,
evidence-backed picture of where Spectra (or any project) actually stands. It is
the generalized, polished version of the three one-off sweeps run on 2026-06-12,
hardened so the numbers can be trusted: every claim is cited, every load-bearing
claim is adversarially re-verified, and recommendations are sequenced by the
demand signal that should unlock them — never dumped as a flat backlog.

## What it produces

1. **Engineering status** — roadmap (shipped vs planned, with the code that
   proves it), code health (real lint/type/test counts), git/release hygiene,
   issue backlog, and doc integrity (every internal contradiction with file:line).
2. **Business reality** — five consulting lenses (product / PMF / GTM / market /
   moat), each applying named frameworks (JTBD, Kano, Dunford, Sean Ellis,
   Superhuman, PLG/bowtie, Porter, 3 Horizons, Helmer 7 Powers, Playing-to-Win),
   web-researching competitors and traction.
3. **Agentic architecture** — SOTA research across five dimensions: agentic
   memory, context engineering, agentic security, controls/governance, and agent
   expansion. The last proposes new agents with pattern, pipeline slot, model
   tier, value-per-effort, and demand gate.
4. **Red-team pass** — a senior partner adversarially verifies every load-bearing
   claim, flags contradictions between lenses, and surfaces what the team missed.
5. **One prioritized list** — act-today exposures, the cheapest demand test with
   pre-committed kill gates, everything else sequenced by gate, and an explicit
   freeze list.

## How to run

```
# Full audit of the current repo
Workflow({ name: 'project-audit' })

# Just one scope
Workflow({ name: 'project-audit', args: { mode: 'status' } })       # engineering
Workflow({ name: 'project-audit', args: { mode: 'strategy' } })     # business lenses
Workflow({ name: 'project-audit', args: { mode: 'architecture' } }) # agentic-system research

# Scoped to a path, with ground-truth context the agents must honor
Workflow({ name: 'project-audit', args: {
  repo: '/abs/path',
  mode: 'full',
  context: 'Spectra v0.9.1, ~zero traction, solo founder; a freeze verdict is in effect — recommend no speculative engineering ahead of a demand signal.',
}})
```

`mode` ∈ `full` (default) · `status` · `strategy` · `architecture`.

> **Cost note.** `full` mode spawns ~16 research/lens agents plus a red-team and a
> synthesis pass, and the business + architecture lenses do live web research —
> it is a real spend. Run `status` for a cheap engineering-only check; reserve
> `full` for quarterly or pre-decision reviews.

## The two rules that make the output trustworthy

1. **Cite or it didn't happen.** Every external/market claim carries a URL + date;
   every repo claim a path/line or command output. The red-team exists to enforce
   this — it strips confidence-without-evidence, especially market-size numbers,
   PMF claims, and "ship this agent" proposals.
2. **Demand-gate every build recommendation.** No recommendation to write code
   ships without the signal that should gate it (`now / hygiene`,
   `post-demand-test`, `N paying users`). This is what keeps an audit from
   becoming a license to build the next speculative feature — the exact failure
   mode the 2026-06-12 audit diagnosed.

## Provenance

Generalized from `spectra-status-sweep`, `spectra-strategy-sweep`, and
`spectra-agentic-deep-research` (2026-06-12). The architecture dimensions encode
the memory / context / security / controls / agent-expansion research from that
session. Script: [`.claude/workflows/project-audit.js`](../../.claude/workflows/project-audit.js).
