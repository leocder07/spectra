# ADR-002: 8-Agent Parallel Analysis Pipeline

## Status

Accepted

## Date

2025-01-15

## Context

Spectra needs to analyze repositories across 6 dimensions (architecture, security, quality, documentation, maintainability, performance) quickly. Sequential analysis would take 6x longer since each dimension requires a separate LLM call with a specialized system prompt.

## Decision

Implement an 8-agent pipeline with 3 distinct phases:

```
MetaPrompter (1 agent, Sonnet 4.5)
    |
    v
6 Specialists (parallel via asyncio.gather, all Opus 4.6)
    |
    v
CritiqueAgent (1 agent, Opus 4.6 with extended thinking)
```

### Key Design Choices

1. **MetaPrompter uses Sonnet 4.5** — Planning from file tree only (never full code) requires fast inference, not deep reasoning. 5K token budget.

2. **6 specialists run in parallel** — `asyncio.gather(*agents, return_exceptions=True)` with a semaphore (max 4 concurrent) to avoid rate-limit bursts. Each agent gets `asyncio.wait_for(timeout=120)`.

3. **Parameterized SpecialistAgent** — A single `SpecialistAgent` class is configured per dimension via `SPECIALIST_CONFIGS`, eliminating 6 identical class definitions.

4. **Failure state machine** — 0-1 agent failures = continue with reweighting. 2+ failures = DEGRADED state with partial report.

5. **CritiqueAgent validates all findings** — Uses extended thinking to reject false positives, adjust severity, and surface cross-cutting insights.

### Decorator Chain

Every LLM call passes through: `LoggingDecorator -> RetryDecorator -> AnthropicAdapter`

- **LoggingDecorator** — Records model, tokens, duration. Redacts secrets.
- **RetryDecorator** — Exponential backoff (1s, 2s, 4s) for transient errors.
- **AnthropicAdapter** — Streaming API calls with connection pooling.

## Consequences

### Positive

- 6 dimensions analyzed in ~90 seconds (parallel) vs ~9 minutes (sequential).
- Graceful degradation — partial results are better than complete failure.
- Single agent class for all specialists reduces code duplication.
- Decorator pattern makes cross-cutting concerns composable.

### Negative

- Rate limiting requires the concurrency semaphore.
- Parallel failures are harder to debug than sequential ones.
- Token budget must be split across agents (managed by `manage_token_budget`).

### Mitigation

- Structured logging with agent role and duration per call.
- `ProgressObserver` protocol provides real-time terminal feedback.
- `SPEC-007` error code triggers when 2+ agents fail.
