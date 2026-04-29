# LLD — Decorator Chain and `LLMGateway` Protocol

The single LLM call path. Every agent goes through three decorators before reaching Anthropic; the gateway protocol is the contract that lets us swap pieces in and out.

## Class diagram

```mermaid
classDiagram
    direction LR

    class LLMGateway {
        <<Protocol — use_cases/interfaces.py>>
        +analyze(system_prompt, user_prompt, model, max_tokens, effort?)* str
        +analyze_with_thinking(system_prompt, user_prompt, model, max_tokens, effort?, task_budget_tokens?)* str
    }

    class LoggingDecorator {
        <<Layer 4>>
        -_inner: LLMGateway
        -_observer: ProgressObserver
        +analyze(... effort?) str
        +analyze_with_thinking(... effort?, task_budget_tokens?) str
    }

    class RetryDecorator {
        <<Layer 4>>
        -_inner: LLMGateway
        -_max_retries: int = 3
        -_backoff_base: float = 1.0
        +analyze(... effort?) str
        +analyze_with_thinking(... effort?, task_budget_tokens?) str
    }

    class AnthropicAdapter {
        <<Layer 4>>
        -_client: AsyncAnthropic
        -_last_usage: tuple~int,int~
        +analyze(... effort?) str
        +analyze_with_thinking(... effort?, task_budget_tokens?) str
        +close() None
    }

    class BaseAgent {
        <<Layer 4 ABC>>
        #_gateway: LLMGateway
        +execute_llm(prompt) str
    }

    BaseAgent --> LLMGateway : holds the OUTERMOST gateway
    LoggingDecorator ..|> LLMGateway : implements
    RetryDecorator ..|> LLMGateway : implements
    AnthropicAdapter ..|> LLMGateway : implements
    LoggingDecorator --> RetryDecorator : _inner
    RetryDecorator --> AnthropicAdapter : _inner

    note for LLMGateway "Same signature for all three implementations.\nStructural subtyping (PEP 544) — no inheritance.\nNew kwargs (Opus 4.7): effort, task_budget_tokens.\ntemperature was removed (HTTP 400 on Opus 4.7)."
```

## Wiring (composition root)

```python
# infrastructure/main.py — single DI wiring point
adapter = AnthropicAdapter(api_key=api_key)
retry   = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
gateway = LoggingDecorator(retry, observer=observer)
factory = AgentFactory(gateway)
```

The factory hands `gateway` to every `BaseAgent`. All 8 agents share one decorator chain — a single `AnthropicAdapter` connection pool serves the whole pipeline.

## Per-agent dispatch on the gateway

```mermaid
flowchart LR
    classDef agent fill:#fef3c7,stroke:#92400e,color:#1e293b
    classDef gateway fill:#ede9fe,stroke:#7C3AED,color:#1e293b
    classDef llmcall fill:#dbeafe,stroke:#1e3a8a,color:#1e293b

    MP[MetaPrompter<br/>effort=medium]:::agent
    Spec[SpecialistAgent ×6<br/>effort=xhigh]:::agent
    Crit[CritiqueAgent<br/>effort=high<br/>task_budget=80K<br/>adaptive · summarized]:::agent

    A[analyze<br/>system, user, model, max_tokens, effort]:::llmcall
    AT[analyze_with_thinking<br/>system, user, model, max_tokens, effort, task_budget_tokens]:::llmcall

    G[LLMGateway<br/>LoggingDecorator → RetryDecorator → AnthropicAdapter]:::gateway

    MP --> A
    Spec --> A
    Crit --> AT
    A --> G
    AT --> G
```

`analyze` and `analyze_with_thinking` are the only two methods on the protocol. Specialists and MetaPrompter use `analyze`; only CritiqueAgent uses `analyze_with_thinking`. That is the entire surface area.

## What each decorator owns

| Decorator | File | Responsibility | Errors raised |
|-----------|------|----------------|---------------|
| `LoggingDecorator` | `infrastructure/logging_decorator.py` | Wall-clock timing, token tally → `ProgressObserver`; sanitizes secrets in log lines | None — passes everything through |
| `RetryDecorator` | `infrastructure/retry_decorator.py` | Exponential backoff with jitter (1s/2s/4s, max 3); only retries `SpectraRetryError` with `retryable=True` | `SpectraRetryError(SPEC-002 / SPEC-003)` after exhaustion |
| `AnthropicAdapter` | `infrastructure/anthropic_adapter.py` | Streaming HTTP via httpx (10-conn pool); sets `output_config.effort`; sets `task_budget` and the `task-budgets-2026-03-13` beta header when present; maps SDK exceptions | `SpectraRetryError(SPEC-002)` (network), `SpectraRetryError(SPEC-003)` (429) |

## `LLMGateway` Protocol — Opus 4.7 surface

```python
class LLMGateway(Protocol):
    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,                 # "low|medium|high|xhigh|max"
    ) -> str: ...

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,     # min 20_000 — beta header
    ) -> str: ...
```

Two breaking changes from the pre-Opus-4.7 protocol:

1. **`temperature` removed.** Opus 4.7 returns HTTP 400 if `temperature` is present alongside `effort`. There is no compatibility mode. Reasoning depth is now steered exclusively via `effort`.
2. **`budget_tokens` → `task_budget_tokens`.** The deprecated per-call thinking budget is gone. The replacement is a *cumulative* loop budget gated behind the beta header `task-budgets-2026-03-13`. The model decides how to split between deeper reasoning and longer output, but the cumulative total cannot exceed the budget.

See [ADR-005](../architecture/adr/ADR-005-opus-4-7-migration.md) for the full migration rationale and per-role effort tuning.

## Sequence — single `analyze` call (specialist)

```mermaid
sequenceDiagram
    participant Agent as SpecialistAgent
    participant Log as LoggingDecorator
    participant Retry as RetryDecorator
    participant API as AnthropicAdapter
    participant Claude as Claude API

    Agent->>Log: analyze(sys, user, claude-opus-4-7, 80000, effort=xhigh)
    Log->>Log: t0 = time.monotonic()
    Log->>Retry: analyze(... effort=xhigh)

    loop attempt 0..3 (only on retryable SpectraRetryError)
        Retry->>API: analyze(... effort=xhigh)
        API->>Claude: POST /v1/messages<br/>output_config={effort: xhigh}
        alt 200 OK
            Claude-->>API: streamed text
            API-->>Retry: text
        else 429
            Claude-->>API: rate limit
            API-->>Retry: SpectraRetryError(SPEC-003)
            Note over Retry: sleep(backoff_base · 2^attempt + jitter)
        end
    end

    Retry-->>Log: text
    Log->>Log: dt = time.monotonic() - t0
    Log->>Log: observer.on_agent_success(role, dt)
    Log-->>Agent: text
```

## Sequence — single `analyze_with_thinking` call (critique)

```mermaid
sequenceDiagram
    participant Crit as CritiqueAgent
    participant Log as LoggingDecorator
    participant Retry as RetryDecorator
    participant API as AnthropicAdapter
    participant Claude as Claude API

    Crit->>Log: analyze_with_thinking(sys, user, claude-opus-4-7,<br/>64000, effort=high, task_budget=80000)
    Log->>Retry: analyze_with_thinking(... effort, task_budget)
    Retry->>API: analyze_with_thinking(... effort, task_budget)
    API->>API: extra_headers["anthropic-beta"] = "task-budgets-2026-03-13"
    API->>Claude: POST /v1/messages<br/>thinking={type: adaptive, display: summarized}<br/>output_config={effort: high}<br/>task_budget=80000
    Claude-->>API: streamed text (thinking blocks excluded)
    API-->>Retry: text
    Retry-->>Log: text
    Log-->>Crit: text
```

`display: "summarized"` keeps the SDK from streaming raw chain-of-thought back to the parser — only the final answer is delivered. See [ADR-008](../architecture/adr/ADR-008-adaptive-thinking-supersedes-extended.md).

---

*Last updated: 2026-04-29 — initial dedicated decorator-chain diagram covering the Opus 4.7 surface (effort + task_budget_tokens).*
