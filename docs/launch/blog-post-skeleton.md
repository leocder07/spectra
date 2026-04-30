# Building an 8-agent code analysis pipeline (with Claude Opus 4.7)

Skeleton, not a finished post. Each section is 2-3 sentences of intent so the user can flesh it out from real session notes and report screenshots.

Target length: ~1,100 words. Target audience: engineers who already know what an LLM is and want to know how to wire one (or eight) into a code-review tool that survives a daily-driver schedule.

---

## 1. The problem with single-pass code review tools

[~150 words]

Frame the gap between two failure modes. On one side: a single LLM call that "reviews the repo" sees too much surface area and produces lukewarm, generic findings — half-true, half-hallucinated, all unactionable. On the other side: traditional static analyzers (ESLint, SonarQube, Snyk) that catch what they have rules for and miss everything else — including most architecture and documentation issues.

Land the thesis: the answer isn't a smarter single agent or a denser ruleset. It's a small *team* of agents with different jobs and a critic at the end.

[PLACEHOLDER: Lead with one screenshot of a generic, useless single-LLM code review for contrast.]

---

## 2. Why 8 agents, not 1?

[~200 words]

Three reasons:

1. **Separation of concerns.** Architecture, security, documentation, and performance are different cognitive tasks with different prompts, different failure modes, and different reference frames (OWASP vs. SOLID vs. JSDoc vs. async patterns). A single agent doing all four context-switches badly.
2. **Parallel execution.** With `asyncio.gather` over six specialists, end-to-end latency is roughly the time of the slowest specialist plus the critic, not the sum of all six. That's the difference between a 30-second tool and a 3-minute tool.
3. **False-positive filtering as its own stage.** Each specialist is allowed to be a little overconfident — that's fine, because a critic agent with adaptive thinking validates every finding before it reaches the report. In testing the critic rejects [PLACEHOLDER: ~30]% of incoming findings.

[PLACEHOLDER: Reference Anthropic's own multi-agent guidance — link to their multi-agent research engineering post once published, or the "research" post from the engineering blog.]

---

## 3. The architecture in 5 minutes

[~250 words]

Spectra is Clean Architecture, four layers, dependency rule strictly enforced. The reason this matters for the post: it's what made the cache subsystem cheap to add later (a port in Layer 2, an adapter in Layer 4 — zero changes to the use-case orchestration logic).

Layers:

- **Layer 1 — Entities.** Frozen Pydantic models. Zero spectra imports.
- **Layer 2 — Use Cases.** `analyze_repository` (Facade), `orchestrate_agents` (`asyncio.gather`), and Protocol-based ports (`LLMGateway`, `GitPort`, `CachePort`).
- **Layer 3 — Adapters.** Typer CLI, Rich progress reporter, presenter.
- **Layer 4 — Infrastructure.** `AnthropicAdapter`, `SqliteCacheAdapter`, `GitAdapter`, `ReportAdapter`. Composition root wires everything in `main.py`.

The decorator chain on the LLM gateway is worth a sentence: every Anthropic call goes through `LoggingDecorator → RetryDecorator → AnthropicAdapter`. Adding observability or rate-limiting later was a one-class change.

[PLACEHOLDER: Embed the system-context Mermaid block from `docs/diagrams/system-context.md` here.]

---

## 4. The cache that makes it daily-drivable

[~300 words — this is the differentiator, give it the most space]

The original Spectra was technically correct but practically a one-shot — nobody runs a $5 audit on every push. The 0.3.0 release introduces a per-`focus_area` batch cache that flips the economics.

**The insight.** The natural unit of caching isn't "the whole report" (too coarse — invalidated by any one-line change) and isn't "per file" (too fine — duplicates overlap across batches). It's the per-`focus_area` batch the meta-prompter already produces. Each batch is a dimension + a list of files; if those files' hashes haven't changed and the prompt/model versions match, the cached findings are reusable.

**The invalidation matrix.** The composite primary key is `(file_hash, dimension, model_version, prompt_version, schema_version, spectra_version)`. There is no invalidation logic to maintain. Stale rows simply never match a current-context lookup. Physical deletion is deferred to `spectra cache prune`. This was the decision I'm proudest of — turning invalidation from a runtime concern into a key-design concern.

**The numbers.** On a representative test repo, warm runs after a 2-line edit are ~[PLACEHOLDER: 95]% cheaper and complete in [PLACEHOLDER: ~10]s instead of [PLACEHOLDER: ~3] minutes. The CLI surfaces the per-dimension hit rate during the run via `ProgressObserver.on_cache_lookup` — `security cache 7/8 hits` is the signal that the tool is working.

[PLACEHOLDER: One screenshot of the terminal showing the per-dimension cache hit lines from a real warm run.]

The cache also has a non-fatal failure mode (SPEC-010): SQLite I/O errors degrade to no-cache for the rest of the run, never abort the pipeline.

---

## 5. What I learned

[~200 words]

Three things, in increasing order of "I would not have predicted this":

1. **Adaptive thinking on every agent makes findings worse, not better.** First version had extended thinking on all 8 agents. Findings got more detailed per-agent but the false-positive rate went *up* — each specialist had enough rope to talk itself into edge cases that didn't exist. Moving thinking to the critic-only stage was the single biggest quality jump in the project.
2. **`task_budget` is the right knob for runaway thinking on Opus 4.7.** Without it the critic occasionally burned 200K tokens on a 40-finding report. With `task_budget=80K` it makes a forced choice — "you have this much, spend it well" — and the outputs are tighter. [PLACEHOLDER: cost-per-run before/after numbers.]
3. **Cache invalidation is a key-design problem, not a runtime problem.** Once the composite key was right, there was no "cache logic" to write or test. This is obvious in retrospect and was non-obvious at the time.

What I'd do differently: ship the GitHub Action in 0.1 instead of 0.3. CI is where the tool earns its keep.

---

## Call to action

Try it:

```bash
pip install spectra-ai
spectra analyze .
```

Source: https://github.com/leocder07/spectra
Package: https://pypi.org/project/spectra-ai/
Docs: https://github.com/leocder07/spectra/tree/main/docs

If you ship it in CI, I'd love to know — open an issue or DM me.
