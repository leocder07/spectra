# Direction Decision — where Spectra plays and how it wins

**Date:** 2026-06-12
**Status:** Decided (supersedes the one-line pivot note in `.remember/recent.md`, 2026-05-15)
**Decision owner:** Vivek Kumar
**Inputs:** the 2026-06-12 strategy audit (product / PMF / GTM / market / moat lenses + partner red-team), `docs/strategy/product-roadmap.md`, `docs/strategy/q4-plan.md` open questions, `docs/sprint/Spectra-Pre-Sprint-Readiness-Report.md`, the M-series strategy pack.

---

## Why this memo exists

The 2026-05-15 session pivoted Spectra's positioning and evaluated "4 strategic
directions," but the only durable record was a single line: *"pivot from
AI-governance to code-review/SAST focus (competitors: CodeRabbit/Greptile/
Copilot); 4 strategic directions evaluated."* A pivotal decision that lives in
one sentence cannot be audited, defended, or revisited. This memo reconstructs
the four directions, records the call, and pre-commits the rule that decides
whether Spectra continues or stops. It is the source of truth from here.

---

## Situation (verified, 2026-06-12)

Spectra is an exceptionally engineered instrument that has never made contact
with a market.

- **Engineering:** 14 PyPI releases, 2,633 passing tests, Clean Architecture,
  SLSA L3 + Sigstore supply chain, Ed25519-signed receipts, SARIF, SBOM,
  policy gates, signed waivers, per-repo memory.
- **Traction:** 19 GitHub stars (release-day bursts, one self-star), 0 forks,
  0 externally-filed issues, ~750 mostly-mirror PyPI downloads/month whose
  peaks land on the author's own release days. Two external consumers of the
  package, one of them the author's own `warrantlabs/warrant-private`.
- **Distribution:** the launch was drafted and never fired (`docs/launch/*`
  still carries `[PLACEHOLDER]` tokens). The one documented CI surface pointed
  at an unregistered GitHub org (now repointed to the real repo — see
  `action.yml`).
- **Founder attention:** has moved to other ventures; the repo went dormant
  2026-05-22 → 2026-06-12.

The market itself is real and hot — CodeRabbit is past ~$40M ARR at a $550M
valuation with 8,000+ paying customers; the category consolidated (Sonar
acquired Gitar on 2026-05-21) while Spectra was dormant. The problem is not the
market and not the engineering. It is that Spectra has never been pointed at
anything.

---

## The four directions evaluated

| | Direction | One-line thesis | Verdict |
|---|---|---|---|
| **A** | **Head-on AI code review / SAST** | Compete with CodeRabbit / Greptile / Copilot on inline PR review. | **Reject.** Unwinnable for a solo part-timer: the incumbents own inline review with eight-figure funding and bundled distribution, and Spectra's own README concedes it "is not for inline PR comments." Spectra lacks every table-stake (inline diff comments, IDE, free tier) and a $1–10 full-repo scan per PR loses on economics to per-seat subscriptions. |
| **B** | **Compliance-evidence engine** | The signed, policy-gated, deterministically-mapped compliance artifact for AI-era codebases; timed to the EU CRA clock. | **Hold as the Horizon-2 expansion of C, not the entry.** It is the most defensible long-run position, but its keystone (ADR-027 deterministic compliance mapping) is unbuilt and the product currently disclaims itself as "not auditor-grade evidence." Building it now violates the freeze. |
| **C** | **Point-in-time graded audit / due-diligence instrument** | The verifiable A+–F report for the moments that matter: inheriting a codebase, pre-acquisition tech DD, agency/contractor handoff acceptance, grading AI-generated services. Explicitly complementary to inline reviewers. | **Chosen.** This is the job nobody in the June-2026 competitor set serves, and the one where every already-shipped differentiator (signed receipts, dual-mode reports, compliance scoring, debt quantification) is load-bearing. The founder's own ICP matrix scored VC/PE due diligence highest (pain 10/10, willingness-to-pay 10/10, competitive whitespace 9/10). |
| **D** | **Fold into Warrant / deliberate archive** | Treat Spectra as internal capability + portfolio/credibility asset rather than a standalone business. | **The kill-rule fallback.** Honorable and matches revealed time allocation. Selected automatically if the demand test (below) fails. |

---

## Decision

**Where to play:** Direction **C** — the point-in-time, evidence-grade codebase
audit. Buyers are PE/VC technical-diligence teams, acquirers doing pre-deal tech
DD, engineering leaders inheriting or accepting a codebase, and teams that need
to grade AI-generated services before they ship. Positioned **alongside, never
against** CodeRabbit / Greptile / Copilot: *"they review your diffs; Spectra
grades your repo."*

**How to win:** the one thing no funded competitor ships — a **signed,
verifiable, reproducible audit** with a graded scorecard, an Ed25519 receipt any
third party can verify, and dual-mode (confidential / public) reporting. The
velocity-focused, venture-funded inline reviewers have no incentive to build the
trust/evidence layer; that is the counter-position.

**Monetization:** services-led first — paid pilot DD reports (Spectra-run +
founder-reviewed), no billing surface required. Verified COGS is $1.30–$9.02 per
scan (Opus 4.7 at $5/$25 per MTok), so a $1,000–$3,000 report carries ~99% gross
margin. The hosted org/memory tier is the post-validation play, consistent with
the per-repo-free / per-org-paid line already set in `product-roadmap.md`
Conflict 5.

---

## What would have to be true (WWHTBT) for C to win

1. **Buyers feel the pain acutely and episodically.** PE/VC diligence, M&A, and
   handoff-acceptance are real, recurring, high-stakes events with budget. → Test
   with 10 discovery calls before building anything.
2. **A signed, graded report is credible enough to inform a real decision.** This
   requires the grade band to be tight and a published accuracy benchmark — today
   the grade swings ±5 points on identical code, which is a ceiling on the whole
   wedge. → The eval benchmark is the near-term trust unlock (see Defer/Build).
3. **The complement framing holds** — buyers run Spectra in addition to, not
   instead of, their inline reviewer. The README already says this; keep it.
4. **The founder allocates a fixed weekly block.** Direction C is services-led and
   low-engineering, but it is not zero-attention. If a fixed allocation alongside
   other ventures is not possible, Direction D is the honest call.

---

## Pre-committed kill rule

The decision to continue is settled **not by opinion but by a demand test**,
run once the Day-0/Week-1 hygiene is done (see below). Fire the already-written
Show HN positioned as Direction C, and book the 10 discovery calls.

**Gates (14-day window from launch):**

- ≥ 25 organic stars from accounts outside the author's network
- ≥ 5 issues/discussions filed by strangers
- non-mirror PyPI downloads holding ≥ 30/day at day 7 (vs the current 1–3/day trough)
- ≥ 3 second-scans by distinct external users **or** ≥ 1 paid pilot booked

**Rule:** if **fewer than 2 of 4** gates pass by day 14 → execute Direction **D**
(fold the IP into Warrant or archive deliberately with a write-up and a
"looking for a maintainer" pin). If **≥ 2** pass → instrument (opt-in anonymous
run-count ping + in-report Sean-Ellis "how disappointed would you be without
Spectra?" link), run the survey at n ≥ 40, and apply the Superhuman engine.

A silent zombie repo is the only outcome explicitly ruled out. Both ship and
deliberate-archive are acceptable; drift is not.

---

## Build / Defer

**Must fix before any launch (integrity, not feature work — in progress):**
1. ~~Repoint the phantom `spectra-ai/spectra@v1` org~~ — done (`action.yml` → `leocder07/spectra`).
2. ~~Delete the committed third-party confidential findings~~ — done; `.gitignore` guard added.
3. ~~Reconcile README contradictions~~ (test count, cost, timing, comparison table) — done.
4. Cut the `v1` tag so `uses: leocder07/spectra@v1` resolves.
5. Fill the launch `[PLACEHOLDER]`s with real v0.9.1 numbers.

**The near-term trust unlock (the one piece of real engineering justified pre-revenue, because it is what makes the grade credible to a DD buyer):**
- A published accuracy benchmark — seeded-bug catch-rate and false-positive rate before/after CritiqueAgent, the way Qodo publishes F1 — plus the determinism controls to tighten the ±5 grade band. This is a trust asset, not a feature; it directly de-risks WWHTBT #2.

**Frozen until a stranger pays or files an issue** (per the audit's unanimous freeze verdict and `product-roadmap.md`):
- All Q4 feature backlog: `#51 spectra ask`, `#52 spectra brief`, `#55 public knowledge skill`, `#60 compliance mapping` (Direction B's keystone — built only when a compliance buyer asks).
- All enterprise-surface work: Bedrock/Vertex (`#14`), ZDR (`#15`), RBAC, HIPAA mode.
- Any further strategy documents whose next unit does not contain a customer quote.

---

## Provenance

Reconstructed from the 2026-06-12 strategy audit (five-lens consulting sweep +
partner red-team), cross-checked against `product-roadmap.md` (the five
adjudicated persona conflicts), `q4-plan.md` open questions 1–5, and the
Pre-Sprint Readiness Report risk table. The directions A–D are the audit's
convergent framing; the ICP scores are the founder's own GTM matrix
(06-Spectra-GTM). Where the audit and the internal docs agreed, the call is
recorded as decided; where they conflicted (e.g. unit economics, stale at
"deeply negative" in M4 vs. viable at current Opus pricing), the verified
current number governs.
