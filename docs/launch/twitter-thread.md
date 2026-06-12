# Twitter/X launch thread — Spectra v0.9.1

> Refreshed 2026-06-12 for v0.9.1 and Direction-C positioning. All numbers are
> verifiable against `docs/launch/leaderboard.md`. 8 tweets, each ≤ 280 chars.
> Tweet 1 must stand alone (it gets RT'd without context). Tweet 8 is the CTA.
> Character counts are pre-link (X shortens URLs to 23 chars).

---

## 1/8 — Hook (must work standalone if RT'd)

> I pointed 8 Claude agents at FastAPI, HTTPX, Aider and Simon Willison's LLM and
> graded each whole repo A+ to F.
>
> One shot each. $31 of real API spend. Every grade ships with a signed receipt
> you can verify.
>
> Spectra v0.9.1, today ↓

[~250 chars]

---

## 2/8 — What it is

> Spectra is a CLI that fans out 8 Claude agents over an entire repo and returns
> a graded report across 6 dimensions:
>
> · architecture
> · security
> · quality
> · documentation
> · maintainability
> · performance
>
> All 8 on Opus 4.7. One signed report.

[~260 chars]

---

## 3/8 — What it is NOT (the positioning)

> It is not an inline PR reviewer. CodeRabbit, Greptile and Copilot already do
> that well, on every diff.
>
> Spectra grades the WHOLE repo at a point in time — for due diligence, a handoff,
> a release gate, or QA-ing AI-written code. Run both.

[~270 chars]

---

## 4/8 — The receipts (real panel)

> Five popular Python repos, one shot each, no cherry-picking:
>
> FastAPI — A (92)
> HTTPX — B+ (85)
> Aider — B- (79)
> simonw/llm — B- (77)
> Spectra itself — A (92)
>
> $31.18 total, all on Opus 4.7. Every grade is Ed25519-signed.

[~265 chars]

---

## 5/8 — How it works (architecture in one tweet)

> The pipeline:
>
> 1. MetaPrompter plans focus areas from the file tree only (never source)
> 2. 6 specialists run in parallel via asyncio.gather
> 3. A CritiqueAgent with adaptive thinking validates every finding
> 4. Signed, graded HTML report

[~270 chars]

---

## 6/8 — The trust layer (the differentiator)

> The part the inline reviewers do not do: every report carries an Ed25519
> receipt, so anyone can verify the grade came from Spectra and not from you.
>
> `spectra verify report.json`
>
> Plus SARIF, SBOM, and a min-score CI gate.

[~260 chars]

---

## 7/8 — Honest caveat

> Straight answer on accuracy: the critical/high counts are the trustworthy
> signal. The overall score is a ~5-point band on re-runs.
>
> Next release publishes a seeded-bug catch-rate + false-positive benchmark, so
> the grade is a number, not a vibe.

[~270 chars]

---

## 8/8 — Try it (call to action)

> Try it:
>
> ```
> pip install spectra-ai
> spectra analyze <your-repo>
> ```
>
> GitHub: github.com/leocder07/spectra
> PyPI: pypi.org/project/spectra-ai
>
> MIT. If the "grade the whole repo, signed" job is one you have — DD, handoff,
> AI-codegen QA — I want to hear it. RTs welcome.

[~275 chars]

---

## Reply-tweet variants (for the obvious questions)

**"Cost?"**

> $1–10 of your own Anthropic spend by repo size — $2.61 on FastAPI, $9.02 on
> simonw/llm in the panel. Warm re-runs are far cheaper via a per-file cache.
> `spectra cache stats` shows your hit rate.

**"Why not CodeRabbit / Greptile / Copilot / SonarQube?"**

> Different job. They review diffs, inline, continuously. Spectra grades the whole
> repo at a point in time and hands you a signed report. Run both — inline on
> every PR, Spectra when you need the audit.

**"Is it open source?"**

> MIT. Source: github.com/leocder07/spectra. Package: pypi.org/project/spectra-ai.
> PRs welcome — Clean Architecture is enforced.

**"How does it handle false positives?"**

> A CritiqueAgent with adaptive thinking + a task budget validates every finding
> before it lands. [MEASURE FIRST — do not post a rejection % until the seeded-bug
> benchmark run exists.]

**"What models?"**

> All 8 on Claude Opus 4.7. MetaPrompter effort=medium, 6 specialists effort=xhigh,
> CritiqueAgent effort=high with adaptive thinking + a task budget. No Sonnet in
> the current release.
