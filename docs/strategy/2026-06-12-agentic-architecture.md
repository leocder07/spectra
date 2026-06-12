# Agentic architecture — SOTA research, demand-gated

**Date:** 2026-06-12
**Method:** five SOTA research lenses (agentic memory, context engineering, agentic
security, controls/governance, agent expansion) → principal synthesis →
adversarial architecture critic (YAGNI + Last-Responsible-Moment + the active
freeze verdict). Full transcript in the `spectra-agentic-deep-research` workflow
output.
**One-line verdict (architecture critic):** *Build nothing past the integrity
cluster below until a user pays or files an issue.*

This memo is paired with [`2026-06-12-direction-decision.md`](2026-06-12-direction-decision.md)
(the where-to-play/how-to-win decision) and feeds the reusable
[`project-audit`](AUDIT-PROMPT.md) workflow, whose Architecture phase now runs
these five dimensions on demand.

---

## The integrity cluster — ship now, because it repairs behavior the product already claims

These are not features. Each is a fix to shipped-but-broken behavior, verified
against the code by the research and re-verified by the critic. This is the only
work that survives the freeze.

| # | Repair | Evidence | Effort | Caveat |
|---|---|---|---|---|
| 1 | **Close the dead waiver-writer loop** — wire `build_waiver_added_event` + `append_event` into `waiver_cli.py` on `waive`. | `waiver_cli.py` has zero `append_event` references; the builder at `memory_payloads.py:135` is orphaned. "Waived stays waived" breaks across machines and the Stage-2 "Active waivers" line is permanently empty. | S | The single clearest must-fix — it makes the v0.9.x memory headline actually work. |
| 2 | **Fail the quality gate closed when `flagged_files` is non-empty** on the quick/degraded path. | The regex pre-scan computes `flagged_files` unconditionally, but on `--quick`/degraded the CritiqueAgent is skipped and a passing `min-score` can still be reported with injection markers present. | S | Surgical — the data is already computed; the gate just needs to consult it. |
| 3 | **Swap the stale `claude-opus-4-7` model id → `claude-opus-4-8`** across the agent seams (meta_prompter, critique_agent, specialist_agent, specialist_prompts, main). | Hardcoded and load-bearing; a wrong id risks a 404 or wrong tier. | S | **Founder decision** — "Opus 4.7" is an intentional choice throughout the docs and changing the production model affects cost and output. Verify the id is actually invalid before flipping; do not bundle the tokenizer rewrite (rabbit hole). |
| 4 | **De-tautologize the adversarial CI test** — the fake gateway keyed to the plant's own marker proves nothing. | Test-correctness fix, not a feature. | S | Make the harness honest about what it does and does not catch. |
| 5 | **Make the self-graded leaderboard claim honest.** | `leaderboard.md` already caveats the self-scan as "biased by definition — treat as a sanity check." | XS | Already disclaimed; the stronger move is to publish an *external* benchmark before leaning on any grade number (deferred — see below). |

> **Correction to the synthesis (do NOT apply blindly):** the research recommended
> defaulting `--max-cost-usd` to ~$5. That would abort the documented leaderboard
> scans, which cost $6.16–$9.02. The `cost_tracker` is already wired; the only real
> gap is the *default-off* cap. If a default is added at all, set it well above the
> largest real scan (e.g. $15–$25, matching the leaderboard's own `--max-cost-usd 25`
> reproduce command) — not $5.

---

## SOTA findings by dimension (the durable research)

**Agentic memory.** The field converged on the CoALA four-type taxonomy (working /
episodic / semantic / procedural) and two shifts that matter for Spectra: do the
work at *write* time (extract, relate, dedupe, invalidate) not at every read, and
expose memory as agent-callable *tools* rather than a fixed flat pre-step inject.
Zep/Graphiti's bi-temporal invalidate-not-delete is exactly the mechanism a
"waived 6 weeks ago / regressed since last scan" loop needs — and Spectra already
owns the primitive (`compute_finding_signature`). The flat 2000-char paragraph is
*fine for now* (tiny per-repo logs); memory-as-tool is a post-traction upgrade.
The real gap is the unclosed writer (integrity item #1), not the retrieval engine.

**Context engineering.** Anthropic's context-engineering guidance plus prompt
caching (5-min TTL, cache-read ≪ cache-write) means a six-way fan-out should put
the stable, shared guidance *first* in the prompt so the cached prefix is reused
across specialists. Worth auditing whether the adapter exploits prompt caching at
all — but this is a COGS optimization with zero spend at zero traction, so it is
deferred, not "integrity."

**Agentic security.** The product analyzes untrusted third-party code, so every
filename, ADR, and manifest fed to an LLM is attacker-controlled. The existing
per-call nonce + unconditional regex pre-scan is the right *floor*; the elaborate
base64/zero-width/NFKC datamarking pipeline the synthesis proposed is over-built
for zero-traction threat exposure (critic flag). The genuine security gap is the
*fail-open gate* (integrity item #2), not a content-security pipeline.

**Controls / governance.** For a grading product, the near-term trust unlock is an
*external* seeded-bug benchmark (precision/recall/F1 over real merged PRs with
open judge prompts) to replace the self-graded number — but that is a multi-week
eval project, so the honest cheap move now is to stop leaning on the biased number
(item #5), and build the benchmark only when a prospect asks for accuracy. OTel
spans should follow the GenAI semantic conventions, but nobody is reading the
traces yet — deferred.

**Agent expansion.** Mapping the pipeline onto Anthropic's effective-agents
patterns: MetaPrompter = planner, 6 specialists = parallelization, CritiqueAgent =
evaluator. The highest-value *new* surface is a **PR-scoped review mode** (route
the existing six specialists at a changeset) — but it is net-new (no
`base_ref`/`head_ref`/`changed_files` exists today), so it is a real build, not a
"thin probe." Test the demand with a landing page or a manual run for one team
before building it.

---

## Deferred — the ranked agent backlog (build NOTHING here until a named signal)

Enumerated for the record only; the freeze stops this design work.

| Agent | Pattern | Slot | Tier | Gate |
|---|---|---|---|---|
| PR-scoped review mode | routing + parallelization on a changeset | new entrypoint → existing 6 specialists | unchanged | validate demand first (landing page / manual run) |
| Remediation Fix-PR agent | evaluator-optimizer, world-acting | new stage after critique | Opus xhigh + adaptive thinking | only if a one-week probe converts; **never without the Verifier** |
| Verifier/Reproducer agent | evaluator-optimizer + adversarial reproduction (one failing test per finding) | escalation tier in critique | Opus xhigh + adaptive thinking | bundle with Fix-PR |
| Cost-Governor model-tier router | routing + cascade (Haiku/Sonnet/Opus by risk) | wraps plan stage | Sonnet governor | first 10 paying users |
| Dependency/CVE agent | DB-lookup CVE join + reachability | SBOM→vuln adapter | no-LLM / Haiku | post-demand-test |
| Managed-memory curator + `ask`/`brief` | managed memory + decay | paid memory-port impl | Haiku/Sonnet | org/paid tier |
| Code-graph / router / navigation | — | breaks the file-tree-only planner invariant | — | **cut** until enterprise/large-monorepo |

---

## What this fed back into the toolchain

The five dimensions are now permanent lenses in the reusable
[`project-audit`](AUDIT-PROMPT.md) workflow (`mode: 'architecture'`), plus six new
audit checks the research itself proved valuable: a **memory-integrity** lens
(trace the writer, not just the reader — this pass found the dead waiver write-path
and a notifier-only drift signal), a **fail-open security-gate** lens, a
**benchmark-honesty** lens (separate self-graded from external F1), a
**context-economics** lens (prompt-cache prefix stability, model-id currency,
tokenizer-correct caps), an **agent-design YAGNI** lens (rank every proposed agent
by value-per-effort with its hard dependency and demand gate), and an
**observability-conformance** lens (GenAI semconv).
