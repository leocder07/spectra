# Hacker News post — Spectra v0.9.1

> Refreshed 2026-06-12 for the v0.9.1 release and the Direction-C positioning
> (signed point-in-time audit, complementary to inline reviewers). Numbers
> below are real and verifiable against `docs/launch/leaderboard.md`. Two items
> still need a value before posting — they are flagged **[MEASURE FIRST]**;
> do not post with a guessed number.

## Recommended title (60 chars max — HN cuts off after this):

> Show HN: I graded 5 popular Python repos with 8 Claude agents

(58 chars. The receipts and the panel do the work.)

## Alternative titles

1. `Show HN: Spectra — a signed, graded audit of any GitHub repo` (59 chars)
2. `Show HN: 8 Claude agents grade a whole repo, with a signed receipt` (66 — over the safe limit; only if confident)

---

## Body (200-400 words, conversational, no marketing voice)

Hi HN,

I built Spectra — a CLI that fans out 8 Claude agents over a whole GitHub repo
and returns a graded report (A+ to F) across six dimensions: architecture,
security, quality, documentation, maintainability, and performance. It is not an
inline PR reviewer — CodeRabbit, Greptile, and Copilot already do that well.
Spectra answers a different question: *"what shape is this entire codebase in,
right now, and can I prove the grade came from the tool and not from me?"* The
job I built it for is the moment you inherit a codebase, do technical
due-diligence on an acquisition, accept a contractor's handoff, or want to grade
a service an AI wrote.

To show it survives real code, I ran it once each — no cherry-picking — on five
widely used Python repos. Every grade ships with an Ed25519-signed receipt you
can verify with `spectra verify`:

| Repo | Grade | Findings | Cost |
|---|---|---|---|
| FastAPI | A (92) | 44 | $2.61 |
| Spectra (self-scan) | A (92) | 55 | $6.62 |
| HTTPX | B+ (85) | 67 | $6.77 |
| Aider | B- (79) | 49 | $6.16 |
| Simon Willison's LLM | B- (77) | 57 | $9.02 |

$31.18 of real Anthropic spend, all eight agents on Opus 4.7. Full panel and
methodology: https://github.com/leocder07/spectra/blob/main/docs/launch/leaderboard.md

What is different from "ask Claude to review my code":

- **A MetaPrompter plans focus areas first** from the file tree only (≤5K
  tokens, never the source), so the specialists get focused prompts instead of
  "review this whole repo."
- **6 specialist agents run in parallel** via `asyncio.gather`, one per dimension.
- **A CritiqueAgent with adaptive thinking** validates every finding before it
  reaches the report.
- **Signed, reproducible output** — Ed25519 receipt, dual-mode (confidential /
  public) reports, SARIF, SBOM, and a `min-score`/`fail-on` CI gate.

How to try it:

```bash
pip install spectra-ai
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze .
```

One self-contained HTML report, works offline. Honest caveat I will state up
front: the overall score is a ~5-point band on re-runs — the critical/high
counts are the trustworthy signal, and tightening that band with a published
benchmark is the next thing I am working on.

GitHub: https://github.com/leocder07/spectra
PyPI: https://pypi.org/project/spectra-ai/

Things I would like feedback on:

- Is the "grade the whole repo, signed" job one you actually have — DD, handoff,
  AI-codegen QA — or is inline review enough?
- The 8-agent split: 6 specialists too many, too few, wrong dimensions?
- What would make a signed audit grade credible enough for you to act on?

---

## First comment (post within 5 minutes of submission)

A specific decision I will defend: **adaptive thinking is limited to the
CritiqueAgent — none of the 6 specialists get it.**

The first version had every specialist on extended thinking. Findings got better
per-agent but the false-positive rate went up, because each specialist had
enough rope to talk itself into edge cases that were not in the code. What worked:
keep the specialists fast and a little overconfident, then put one slow, skeptical
critic at the end with a task budget to filter. Six fast agents plus one thinking
critic is also cheaper than seven thinking agents.

I am being deliberately honest about the grade band above because a grading tool
that hides its variance does not deserve to be a CI gate. The roadmap item I care
most about is publishing a seeded-bug catch-rate and false-positive benchmark so
the grade is defensible, not just confident.

---

## Reply variants (paste if the obvious questions come up)

**"What does it cost per run?"**

> $1–10 of your own Anthropic spend depending on repo size — $2.61 on FastAPI,
> $9.02 on Simon Willison's LLM in the panel above. Warm re-runs are far cheaper
> because of a per-file composite-key cache; `spectra cache stats` shows your hit
> rate. CI runs typically use `--no-cache` for a clean grade every time.

**"Why not just use CodeRabbit / Greptile / Copilot review / SonarQube?"**

> Different job. Those review your diffs, continuously, inline. Spectra grades the
> whole repo at a point in time and hands you a signed report — for due diligence,
> a handoff, or a release gate. I would run both: the inline reviewer on every PR,
> Spectra when you need the audit. The signed receipt is the part they do not do.

**"Is it open source?"**

> MIT. Source on GitHub, package on PyPI as `spectra-ai`. PRs welcome — Clean
> Architecture is enforced.

**"How accurate is it really?"**

> Honest answer: the critical/high counts are the trustworthy signal; the overall
> score is a ~5-point band on re-runs. I have an adversarial eval harness and the
> next release publishes a catch-rate / false-positive benchmark on a seeded-bug
> corpus so this is a number, not a vibe. **[MEASURE FIRST]** — do not quote a
> rejection percentage here until the benchmark run exists.

**"Does it work on monorepos?"**

> Yes for repos up to roughly tens of thousands of files; the MetaPrompter caps
> the file-tree input at 5K tokens, so very large monorepos get a sampled view.
> **[MEASURE FIRST]** — confirm the largest repo you have actually tested before
> stating a file-count ceiling.

**"What models does it use?"**

> All 8 agents on Claude Opus 4.7. MetaPrompter `effort=medium`, the 6 specialists
> `effort=xhigh`, the CritiqueAgent `effort=high` plus adaptive thinking with a
> task budget. No Sonnet in the current release.
