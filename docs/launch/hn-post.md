# Hacker News post — Spectra v0.3.0

## Recommended title (60 chars max — HN cuts off after this):

> Show HN: I scored 100 popular Python repos with 8 AI agents

(60 chars exactly. The number does the work — it implies the tool runs at scale and survives real codebases.)

## Alternative titles (A/B test in comments or a follow-up Show HN if this one flops):

1. `Show HN: Spectra — 8-agent code analysis for any GitHub repo` (61 chars)
2. `Show HN: I built a tool that runs 8 Claude Opus agents on your repo` (66 chars — over the safe limit, only if confident)
3. `Show HN: Per-file cache makes 8-agent code review actually re-runnable` (70 chars — leads with the cache)

---

## Body (200-400 words, conversational, no marketing voice)

Hi HN,

I built Spectra — a CLI that fans out 8 AI agents in parallel against any GitHub repo and returns a graded report across 6 dimensions: architecture, security, quality, documentation, maintainability, and performance.

The thing that made me write this post is that v0.3.0 finally made it cheap enough to run daily. I ran it against [PLACEHOLDER: a well-known repo, e.g. `pallets/flask`] on a clean clone and on a 2-line edit back to back — the second run was [PLACEHOLDER: e.g. ~94%] cheaper because the per-`focus_area` batch cache only re-analyzes batches whose files actually changed. Before that, the tool was technically correct but practically a one-shot — nobody runs a $5 audit on every push.

What's different from "ask Claude to review my code":

- **6 specialist agents run in parallel** via `asyncio.gather` — Opus 4.7 with `effort=xhigh` on each
- **A meta-prompter plans focus areas first** from the file tree only (≤5K tokens, never sees source). The specialists get focused prompts instead of "review this whole repo"
- **A critic agent with adaptive thinking** validates every finding before it reaches the report — in my testing it rejects [PLACEHOLDER: e.g. ~30%] of specialist findings as false positives
- **Incremental cache** with composite-key invalidation — the key is `(file_hash, dimension, model_ver, prompt_ver, schema_ver, spectra_ver)`. There's no invalidation logic to maintain; stale rows simply never match
- **Drops into PR CI** as `leocder07/spectra@v1` — a 6-line workflow with a `min-score: 70` gate

How to try it:

```bash
pip install spectra-ai
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze .
```

Open the generated `spectra-report.html`. One file, works offline, includes a radar chart, hotspot heatmap, and OWASP/SOC2/PCI/NIST mapping.

Things I'd love feedback on:

- The 8-agent split — are 6 specialists too many? Too few? I considered merging Documentation + Maintainability and went the other way
- The cache key tuple — too aggressive on the version components, or about right?
- Anything you'd want from a code-review CI tool that I'm missing

GitHub: https://github.com/leocder07/spectra
PyPI: https://pypi.org/project/spectra-ai/
Docs: https://github.com/leocder07/spectra/tree/main/docs

---

## First comment (post within 5 minutes of submission, while still on /newest)

A specific decision I'd defend: **adaptive thinking is intentionally limited to the critique agent — none of the 6 specialists get it.**

The first version of Spectra had every specialist on extended thinking. The findings got *better* per-agent but the false-positive rate went *up*, because each specialist now had enough rope to talk itself into edge cases that didn't actually exist in the code. The pattern that worked: keep the specialists fast and a little overconfident, then put a single slow, skeptical critic at the end with `task_budget=80K` to filter.

Concretely: critic with adaptive thinking rejects ~[PLACEHOLDER: 30]% of incoming findings, and the survivors are noticeably tighter. Cost dropped because 6 fast agents + 1 thinking agent is cheaper than 7 thinking agents.

Happy to discuss why I went this direction over (a) thinking on every agent, (b) thinking on none, or (c) thinking only on the security agent.

---

## Reply variants (paste these if the obvious questions come up)

**"What does it cost per run?"**

> [PLACEHOLDER: $X-$Y depending on repo size]. The cache makes warm re-runs ~95% cheaper — `spectra cache stats` shows your hit rate. CI mode (`--no-cache`) costs full price every time, so most teams run cache-on locally and `--no-cache` in PR checks.

**"Why not just use SonarQube / CodeClimate / DeepSource?"**

> Different shape of tool. Those are static analyzers — fast, deterministic, narrow. Spectra is doing semantic review with an LLM and gives you "this file is your archaeology zone" + a written rationale, not a rule violation. I run both. SonarQube catches what it knows; Spectra finds the things you didn't think to write a rule for.

**"Is it open source?"**

> MIT. Source on GitHub, package on PyPI as `spectra-ai`. I'd love help — the cache subsystem is well-tested but the OWASP mapping has gaps in the auth section.

**"Does it work on monorepos?"**

> [PLACEHOLDER: Verify before posting.] Yes for repos under [PLACEHOLDER: ~50K files]; the meta-prompter caps file-tree input at 5K tokens, so very large monorepos get a sampled view. There's a `--scope <path>` flag in 0.4.0 that lets you point it at one package.

**"What models does it use?"**

> All 8 agents run Opus 4.7. The meta-prompter uses `effort=medium`, the 6 specialists use `effort=xhigh`, and the critic uses `effort=high` plus adaptive thinking with `task_budget=80K`. No Sonnet anywhere in 0.3.0 — moved off it for cost-vs-quality reasons after the cache landed.

**"How accurate is it really?"**

> Honestly, ask the critic agent — that's its whole job. False-positive rate before critic ≈ [PLACEHOLDER: X]%, after ≈ [PLACEHOLDER: Y]%. I publish the self-analysis report on the README so you can read it picking apart its own codebase.
