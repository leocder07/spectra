# Twitter/X launch thread — Spectra v0.3.0

8 tweets. Each one ≤ 280 chars. Tweet 1 must work standalone (will be RT'd without context). Tweet 8 is the call-to-action.

Character counts in brackets are pre-link, since X auto-shortens URLs to 23 chars.

---

## 1/8 — Hook (must work standalone if RT'd)

> I ran 8 Claude Opus agents against [PLACEHOLDER: famous repo, e.g. `expressjs/express`] in parallel.
>
> They found [PLACEHOLDER: N] issues a single-pass LLM review missed — including [PLACEHOLDER: one concrete finding, e.g. "a TOCTOU bug in the symlink check"].
>
> v0.3.0 of Spectra ships today. Thread ↓

[~240 chars]

---

## 2/8 — What it is

> Spectra is a CLI that fans out 8 AI agents on any GitHub repo and returns a graded report across 6 dimensions:
>
> · architecture
> · security
> · quality
> · documentation
> · maintainability
> · performance
>
> All 8 agents on Opus 4.7. Under 5 minutes end-to-end.

[~270 chars]

---

## 3/8 — Why now (the killer feature)

> What changed in v0.3.0: a per-`focus_area` batch cache.
>
> Edit one file, re-run Spectra → only the batches touching that file re-analyze.
>
> Warm runs are ~[PLACEHOLDER: 95]% cheaper.
>
> That's the difference between "neat one-shot demo" and "I run this on every commit."

[~270 chars]

---

## 4/8 — How it works (architecture in one tweet)

> The pipeline:
>
> 1. Meta-prompter plans focus areas (file tree only, never source)
> 2. 6 specialists run in parallel via `asyncio.gather`
> 3. Critic with adaptive thinking validates findings, rejects ~[PLACEHOLDER: 30]% as false positives
> 4. Graded HTML report

[~270 chars]

---

## 5/8 — One concrete result

> Sample finding from running it on [PLACEHOLDER: well-known repo]:
>
> > [PLACEHOLDER: short paste of one real finding — title + 1-line rationale + file path with line number]
>
> Permalink: [PLACEHOLDER: github.com/org/repo/blob/SHA/path#L123]
>
> The full report is one HTML file. Works offline.

[~270 chars]

---

## 6/8 — GitHub Action one-liner

> Drops into PR CI as a single step:
>
> ```yaml
> - uses: leocder07/spectra@v1
>   with:
>     min-score: 70
>   env:
>     ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
> ```
>
> Fails the PR if the weighted score drops below your floor.

[~265 chars including code block]

---

## 7/8 — What's open

> Open questions I'd love takes on:
>
> · 6 specialists — too many, too few, wrong split?
> · Should the critic see specialist disagreement, not just findings?
> · Cache key tuple is `(file_hash, dim, model_v, prompt_v, schema_v, spectra_v)` — too aggressive?
>
> Replies welcome.

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
> MIT licensed. Star if it's useful. RTs appreciated — trying to find out if anyone else needs this shape of tool.

[~270 chars]

---

## Reply-tweet variants (for if someone asks the obvious question)

**"Cost?"**

> ~$[PLACEHOLDER: X-Y] cold per repo, ~$[PLACEHOLDER: Z] warm thanks to the cache. Run `spectra cache stats` to see your hit rate. Most folks turn caching off in CI (`--no-cache`) and on locally.

**"Why not just use ESLint/SonarQube/Snyk/CodeClimate?"**

> Different tool. Static analyzers catch what they have rules for. Spectra is semantic LLM review — finds the stuff you didn't think to write a rule for and writes a rationale. I run both.

**"Is it open source?"**

> MIT. Source: github.com/leocder07/spectra. Package: pypi.org/project/spectra-ai. PRs welcome — Clean Architecture is enforced.

**"Does it work on monorepos?"**

> [PLACEHOLDER: Verify before posting.] Yes for repos up to ~[PLACEHOLDER: 50K] files; the meta-prompter caps file-tree input at 5K tokens so very large repos get a sampled view. `--scope <path>` ships in 0.4.0 to point it at one package.

**"How does it handle false positives?"**

> Critic agent with adaptive thinking + an 80K-token task budget validates every finding before it reaches the report. In testing it filters ~[PLACEHOLDER: 30]% of specialist findings as not-real.

**"What models?"**

> All 8 on Claude Opus 4.7. Meta-prompter `effort=medium`, 6 specialists `effort=xhigh`, critic `effort=high` with adaptive thinking and `task_budget=80K`. Nothing on Sonnet in 0.3.0.
