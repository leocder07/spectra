# ADR-003: Extended Thinking for CritiqueAgent Only

## Status

Accepted

## Date

2025-01-20

## Context

Anthropic's extended thinking feature enables models to reason step-by-step before producing output. It improves accuracy for complex tasks but increases latency and token usage. We need to decide which agents, if any, should use extended thinking.

## Decision

**Only the CritiqueAgent uses extended thinking.** No other agent in the pipeline enables it.

### Rationale

1. **CritiqueAgent validates ALL findings** — It must reason about whether each finding is a true positive, whether severity is correct, and whether cross-cutting patterns exist. This multi-step reasoning is exactly what extended thinking excels at.

2. **Specialist agents produce, CritiqueAgent verifies** — Specialists benefit more from detailed system prompts and structured output formats than from thinking time. Their task is generation (structured findings), not verification.

3. **MetaPrompter is planning-only** — It sees only the file tree and produces a lightweight JSON plan. Extended thinking would add latency without meaningful quality improvement.

4. **Token budget constraint** — Extended thinking increases token usage. Reserving it for a single agent (200K token budget) keeps total pipeline cost predictable.

### Implementation

```python
# CritiqueAgent overrides execute_llm to use thinking
async def execute_llm(self, prompt: str) -> str:
    return await self._gateway.analyze_with_thinking(...)

# All other agents use the default BaseAgent.execute_llm
async def execute_llm(self, prompt: str) -> str:
    return await self._gateway.analyze(...)
```

The `LLMGateway` protocol exposes both `analyze()` and `analyze_with_thinking()`. The `AnthropicAdapter` implements thinking via `thinking={"type": "adaptive"}`.

## Consequences

### Positive

- CritiqueAgent achieves <5% false positive rate on validated findings.
- Pipeline cost stays predictable — thinking tokens are bounded.
- Clear separation: specialists generate, critique validates.

### Negative

- CritiqueAgent is the slowest stage (extended thinking adds latency).
- If critique fails (SPEC-008), findings are returned unvalidated.

### Mitigation

- `--quick` flag skips CritiqueAgent entirely for fast iteration.
- Budget check before critique — skip if tokens are exhausted.
- Degraded state bypasses critique automatically.
