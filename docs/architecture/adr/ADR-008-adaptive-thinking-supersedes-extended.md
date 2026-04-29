# ADR-008: Adaptive Thinking for CritiqueAgent (Supersedes ADR-003)

## Status

Accepted (2026-04-23)
Supersedes [ADR-003: Extended Thinking for CritiqueAgent Only](ADR-003-extended-thinking-critique-only.md)

## Context

[ADR-003](ADR-003-extended-thinking-critique-only.md) established that the CritiqueAgent — and only the CritiqueAgent — uses Anthropic's reasoning-time-thinking feature. That decision is still correct in spirit: the verification stage benefits from deep reasoning in a way that the generation stages do not. The justification (specialists generate, critique verifies; cost predictability; bounded token budget) survives intact.

What changed is the **mechanism**, and the change is large enough that the ADR's title, code snippets, and parameter names are now wrong:

1. **Terminology.** Anthropic renamed "extended thinking" to "adaptive thinking" with the Opus 4.7 release. The wire-level config is now `thinking={"type": "adaptive", ...}`. The old name is deprecated but still appears in some documentation.
2. **`display: "summarized"`.** Adaptive thinking adds a `display` field that controls whether raw chain-of-thought is streamed back to the client. We pick `summarized` so the parser only sees the final answer (no thinking blocks to filter at the SDK layer).
3. **`task_budget` replaces `budget_tokens`.** The old per-call `budget_tokens` knob is deprecated. Its replacement is `task_budget` — a cumulative cap on thinking + output across the whole reasoning loop, gated behind the beta header `task-budgets-2026-03-13`. The model decides how to split between deeper reasoning and longer output, but the cumulative total cannot exceed the budget.
4. **`effort` joins the picture.** Adaptive thinking pairs naturally with `output_config.effort`. For Critique, we use `effort="high"` plus `task_budget=80_000` and `max_tokens=64_000`. (See [ADR-005](ADR-005-opus-4-7-migration.md) for the broader effort tuning rationale.)

Per the project's append-only ADR discipline, ADR-003 is **not edited in place** even though its title is now wrong. Instead, this ADR supersedes it. ADR-003 stands as the historical record of the original 2025 decision; ADR-008 is the current authority.

## Decision

**Adopt adaptive thinking for the CritiqueAgent, with `display: "summarized"`, `effort: "high"`, `max_tokens: 64_000`, and `task_budget_tokens: 80_000`.** No other agent uses thinking, in keeping with the original ADR-003 commitment.

### Implementation

```python
# AnthropicAdapter._call_with_thinking — sets the adaptive thinking config
"thinking": {"type": "adaptive", "display": "summarized"},
# task_budget is gated behind a beta header
if task_budget_tokens is not None:
    extra_headers["anthropic-beta"] = "task-budgets-2026-03-13"

# CritiqueAgent.execute_llm — passes effort and task_budget through the gateway
return await self._gateway.analyze_with_thinking(
    system_prompt=self._system_prompt,
    user_prompt=prompt,
    model=self._model,                         # claude-opus-4-7
    max_tokens=self._max_tokens,               # 64_000
    effort=self._effort,                       # "high"
    task_budget_tokens=_TASK_BUDGET_TOKENS,    # 80_000
)
```

### What Carries Over from ADR-003

The reasoning that put thinking exclusively on the CritiqueAgent is unchanged:

- **Verification needs reasoning more than generation does.** Specialists produce structured findings; Critique reasons about whether each finding is a true positive, whether severity is correct, and whether cross-cutting patterns exist. That's the multi-step reasoning thinking is designed for.
- **Cost predictability.** Restricting thinking to one agent keeps total pipeline cost projectable. With `task_budget=80_000`, even worst-case Critique runs have a hard ceiling.
- **Skip conditions.** `--quick`, degraded state, exhausted token budget — all the same skip paths from ADR-003 still apply.

### What's New

- **Terminology.** Every doc, prompt comment, and code reference says "adaptive thinking" rather than "extended thinking" going forward. ADR-003 is preserved as-is for historical context.
- **`display: "summarized"`.** Removes a class of bugs where the parser had to filter `thinking` blocks out of the SDK's streaming events. The SDK now only emits the final answer.
- **`task_budget` semantics.** The old `budget_tokens` was a per-thinking-call ceiling. `task_budget` is cumulative across the loop, which means we no longer have to reason about how many tool-use cycles a single call might trigger.
- **`effort: "high"`.** Steers the model's reasoning depth in lieu of `temperature` (which Opus 4.7 doesn't accept).

## Consequences

### Positive

- **Terminology matches Anthropic's current docs.** New engineers reading our code don't have to translate from a deprecated name.
- **Cleaner streaming code.** `display: "summarized"` lets us delete the SDK-event filtering logic that previously stripped thinking blocks before parsing.
- **Hard cumulative cap on reasoning + output.** `task_budget=80_000` makes Critique's worst-case cost a known quantity, regardless of how the model splits between reasoning and answer.
- **Original ADR-003 commitment preserved.** No other agent uses thinking. The pipeline shape is unchanged.

### Negative

- **`task_budget` is behind a beta header.** If Anthropic rolls back the beta, the parameter starts being rejected. We mitigate by feature-flagging the header in the adapter — degrade to `effort` alone if the header is unsupported.
- **Two ADRs cover one decision now.** ADR-003 and ADR-008 must be read together to get the full history. The append-only discipline trades short-term redundancy for long-term audit clarity.
- **Migration cost.** Every doc, diagram, and prompt comment that said "extended thinking" had to be rewritten. (Most of that work is in this PR.)

### Neutral

- The `analyze_with_thinking` method signature on `LLMGateway` gained `effort` and `task_budget_tokens` (see [ADR-005](ADR-005-opus-4-7-migration.md)). The default is `None` for both, so non-Critique callers (none today) would be unaffected.

## Alternatives Considered

| Alternative | Verdict |
|-------------|---------|
| **Edit ADR-003 in place.** | Rejected. ADRs are append-only once Accepted. Editing destroys the historical trail of how thinking evolved on this project. |
| **Mark ADR-003 as Deprecated and stop linking to it.** | Rejected for the same reason. Status changes are also a form of edit. The supersede-via-new-ADR pattern is cleaner. |
| **Stay on the old `extended thinking` config.** | Not feasible. Opus 4.7 routes "extended" requests through the adaptive path automatically; the config keys differ; `budget_tokens` is deprecated. There is no compatibility mode. |
| **Use `display: "raw"` to expose chain-of-thought.** | Rejected. Our parser doesn't need the thinking blocks; exposing them creates an attack surface (prompt-injection content reaching the parser) and bloats logs. `summarized` is strictly better. |
| **Skip `task_budget`; use `max_tokens` alone.** | Rejected. `max_tokens` is a per-response cap; `task_budget` is cumulative. Without the latter, a multi-step thinking call could blow well past our cost projections even with a small `max_tokens`. |
| **Apply adaptive thinking to specialists too.** | Rejected. Original ADR-003 reasoning still holds — generation tasks don't need reasoning time, they need detailed prompts. Adding thinking to all 6 specialists would multiply latency without measurable quality gain on our benchmarks. |

## References

- Supersedes: [ADR-003](ADR-003-extended-thinking-critique-only.md)
- Related: [ADR-005](ADR-005-opus-4-7-migration.md) — the broader Opus 4.7 migration that motivated this terminology change
- Code: `src/spectra/infrastructure/anthropic_adapter.py:240-265` (adaptive thinking config; task_budget beta header)
- Code: `src/spectra/infrastructure/agents/critique_agent.py:131-178` (effort, max_tokens, task_budget choices)
- Anthropic beta header: `task-budgets-2026-03-13`

---

*Last updated: 2026-04-29.*
