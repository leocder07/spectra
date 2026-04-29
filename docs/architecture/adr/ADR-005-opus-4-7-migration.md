# ADR-005: Migrate All 8 Agents to Claude Opus 4.7

## Status

Accepted (2026-04-23)

## Context

Spectra's pipeline previously ran a mix of models — `claude-sonnet-4-5` for the MetaPrompter (planning) and `claude-opus-4-6` for the six specialist agents and the CritiqueAgent. The split was originally chosen to keep planning cheap while reserving the higher-capability model for the heavy analysis stages.

Three pressures forced a re-evaluation in April 2026:

1. **Anthropic released `claude-opus-4-7`** with both stronger coding/agentic performance and a new `output_config.effort` knob (`low|medium|high|xhigh|max`) that lets a single model serve cost-sensitive and capability-sensitive workloads from the same identifier.
2. **Two parameters we relied on were removed.** Opus 4.7 rejects `temperature` (HTTP 400) — reasoning depth is now steered exclusively via `effort`. The per-call thinking budget knob `budget_tokens` was deprecated in favor of a cumulative loop budget called `task_budget` (gated behind the beta header `task-budgets-2026-03-13`).
3. **Operational simplification.** Maintaining two model families meant two sets of prompt-engineering quirks, two cost projections, and two upgrade cadences. Collapsing to one model family removes that cost.

Anthropic's public guidance for coding/agentic workloads on Opus 4.7 is `effort=xhigh` (one tier below the maximum). For lighter-weight structured extraction (e.g. our planning step), `medium` is more than sufficient.

## Decision

**Migrate all 8 agents to `claude-opus-4-7` with per-role `effort` tuning.** Remove `temperature` from every call site. Replace the deprecated `budget_tokens` mechanism with `task_budget` (Critique only).

| Agent | Model | Effort | Thinking | Max Tokens | Task Budget |
|-------|-------|--------|----------|------------|-------------|
| MetaPrompter | `claude-opus-4-7` | `medium` | Off | 5,000 | — |
| 6 SpecialistAgents | `claude-opus-4-7` | `xhigh` | Off | ~80,000 | — |
| CritiqueAgent | `claude-opus-4-7` | `high` | Adaptive (`display: summarized`) | 64,000 | 80,000 |

### Per-role effort tuning rationale

- **MetaPrompter — `medium`.** Planning is structured JSON extraction over a file tree (≤5K tokens of input, no source code). Higher effort would burn latency without measurably improving the focus-area allocation. Medium is the right cost/quality tradeoff.
- **Specialists — `xhigh`.** This is Anthropic's recommended setting for coding/agentic workloads on Opus 4.7. `xhigh` gives the model significant reasoning headroom for finding subtle issues (architecture violations, security defects, performance traps) without paying the unbounded cost of `max`.
- **CritiqueAgent — `high`.** Critique reasons over already-structured findings — the input is finding JSON, not raw source. `high` plus adaptive thinking with a `task_budget=80K` ceiling gives the model enough room to deeply reason about validity without runaway cost. The `task_budget` is a hard cumulative cap on thinking + output tokens; the model decides how to split between the two.

### LLMGateway protocol surface change

Both `analyze` and `analyze_with_thinking` gain optional kwargs:

```python
async def analyze(
    self,
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    effort: str | None = None,            # NEW
) -> str: ...

async def analyze_with_thinking(
    self,
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    effort: str | None = None,            # NEW
    task_budget_tokens: int | None = None, # NEW (replaces deprecated budget_tokens)
) -> str: ...
```

The kwargs are optional to keep the protocol backwards-compatible for any future adapter that doesn't support effort knobs. `temperature` is gone entirely — there is no transitional period.

### Adaptive thinking surface change

The CritiqueAgent's adaptive thinking call now sets:

```python
"thinking": {"type": "adaptive", "display": "summarized"}
```

`display: "summarized"` keeps the SDK from streaming raw chain-of-thought to the client. The parser only sees the final answer, which keeps the existing JSON extraction code unchanged. The terminology shift from "extended thinking" to "adaptive thinking" is formalized in [ADR-008](ADR-008-adaptive-thinking-supersedes-extended.md), which supersedes [ADR-003](ADR-003-extended-thinking-critique-only.md).

## Consequences

### Positive

- **One model family.** Cost projections, prompt iteration, and upgrade cadence are all simpler.
- **Per-role effort knob is a new dimension of cost control.** We can demote planning to `medium` and only pay `xhigh` rates where it matters. `task_budget` makes Critique's worst-case cost predictable.
- **Better baseline quality.** Opus 4.7 outperforms 4.6 on the coding/agentic benchmarks we care about. Self-analysis hit rate (the dogfood test on Spectra itself) improved from ~67% to ~78% true-positive without prompt changes.
- **`display: "summarized"` simplifies the streaming path.** The parser no longer has to filter out `thinking` blocks at the SDK layer.

### Negative

- **Breaking change to LLMGateway.** Every existing caller had to pass the new kwargs (or accept defaults). Any third-party adapter implementing `LLMGateway` needs the same signature change.
- **`temperature` removal lost a familiar knob.** Engineers used to nudging temperature for determinism testing have to learn the `effort` axis instead. Opus 4.7 is more deterministic by default, which mostly compensates.
- **`task_budget` is behind a beta header.** If Anthropic rolls back the beta, the CritiqueAgent stops working. We caught this risk in code review and added a feature flag to degrade to `effort` alone if the header is unsupported (not yet exercised).
- **Cost shifts.** `xhigh` on the specialists costs more per call than Opus 4.6 default. Net effect on a typical 90s analysis is +20–30% per run, partially offset by demoting MetaPrompter and removing the second model's overhead.

### Neutral

- The model identifier in cache keys changes once (`claude-opus-4-6` → `claude-opus-4-7`). When the cache lands ([ADR-006](ADR-006-cache-port-incremental-analysis.md)), `model_version` is part of the composite primary key, so the cache will naturally invalidate at the cutover.

## Alternatives Considered

| Alternative | Verdict |
|-------------|---------|
| **Stay on Opus 4.6 + Sonnet 4.5.** | Rejected. Continued maintenance burden of two model families, no access to the `effort` knob, and the gap to Opus 4.7 on agentic benchmarks was widening. |
| **Move only the Critique to Opus 4.7, keep the rest on 4.6/Sonnet.** | Rejected. We'd own the worst of both worlds — three model families to reason about, and the protocol churn (effort/task_budget) lands either way. |
| **Use `effort=max` everywhere.** | Rejected. `max` has no cost ceiling and the gain over `xhigh` on our workloads was indistinguishable in spot-checks. We can revisit if a specific dimension under-performs. |
| **Keep `temperature` and only set `effort`.** | Not feasible. Opus 4.7 returns 400 if `temperature` is present alongside `effort`. There is no compatibility mode. |
| **Replace `budget_tokens` with a manual loop limit in our own code.** | Rejected. `task_budget` is server-enforced and exits cleanly. Our own loop limit would be a lossy reimplementation. |

## References

- Code: `src/spectra/use_cases/interfaces.py:23-76` (LLMGateway protocol with new kwargs)
- Code: `src/spectra/infrastructure/anthropic_adapter.py:240-265` (effort + task_budget wiring; adaptive thinking config)
- Code: `src/spectra/infrastructure/agents/meta_prompter.py:143-146` (model + effort=medium)
- Code: `src/spectra/infrastructure/agents/specialist_agent.py:32-56` (model + effort=xhigh defaults)
- Code: `src/spectra/infrastructure/agents/critique_agent.py:131-178` (max_tokens=64K, effort=high, task_budget=80K)
- Code: `src/spectra/infrastructure/agents/specialist_prompts.py:739` (`_OPUS = "claude-opus-4-7"`)
- Related: [ADR-002](ADR-002-parallel-agent-pipeline.md) — the pipeline shape this migration preserves
- Related: [ADR-008](ADR-008-adaptive-thinking-supersedes-extended.md) — terminology change ("extended" → "adaptive" thinking)
- Anthropic beta header: `task-budgets-2026-03-13`

---

*Last updated: 2026-04-29.*
