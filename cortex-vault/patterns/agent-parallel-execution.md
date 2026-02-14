---
type: pattern
project: spectra
created: 2026-02-14
tags: [type/pattern, project/spectra, domain/agents]
---

# Agent Parallel Execution Pattern

## Rule
4 specialist agents ALWAYS run in parallel:
```typescript
const [arch, sec, qual, doc] = await Promise.all([
  architectureAgent.analyze(),
  securityAgent.analyze(),
  qualityAgent.analyze(),
  documentationAgent.analyze()
]);
```

## Timeout
`Promise.race` with 30s timeout per agent.

## Failure Policy
If 2+ agents fail → abort with partial report. Never hang.

## Validation
Every agent output validated against Zod schema BEFORE merge.

## LLM Call Chain
All calls go through: LoggingDecorator → RetryDecorator → AnthropicLLMAdapter
Retry: exponential backoff 1s → 2s → 4s (max 3 attempts)
