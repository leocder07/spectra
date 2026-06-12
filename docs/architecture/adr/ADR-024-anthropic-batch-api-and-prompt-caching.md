# ADR-024: Anthropic Batch API + Prompt Caching for Cost Compression

## Status

Accepted (2026-04-30) — Anthropic Batch API adapter shipped (Q3)

## Context

The CTO's #1 cost lever ([cto-findings.md §1, §6](../../strategy/cto-findings.md),
[product-roadmap.md #23](../../strategy/product-roadmap.md), RICE 80) is to
adopt two Anthropic-native primitives:

- **Prompt caching** (`cache_control: ephemeral`). Anthropic discounts cached
  input tokens to ~10% of standard input price. Our specialist system prompts
  (~3,000-5,000 tokens each, stable per release) and the MetaPrompter system
  prompt (~2,000 tokens, stable per release) are perfect cache breakpoints.
  Six specialists × five batches × 4,000 cached tokens = 120,000 tokens/scan
  at 10× discount → ~$1.50 savings per scan at xhigh effort.
- **Batch API** (`/v1/messages/batches`). Anthropic charges 50% of
  standard pricing for asynchronous batch jobs that complete within 24
  hours. Wrong fit for interactive `spectra analyze` (users wait
  ≤5 minutes per [CLAUDE.md](../../../CLAUDE.md)). **Right fit for the Q3
  portfolio scheduler** ([ADR-022](ADR-022-postgres-history-store.md), #26)
  where 50-300 repos scan overnight.

The two primitives are complementary, not alternative: Batch API halves
*every* token; prompt caching further halves the *cached* tokens within a
batch. Stacked, the cost win is real.

Three architectural questions:

1. **`LLMGateway` extension.** The current Protocol has one method:
   `analyze(prompt) -> Response`. Batch is async-by-design (submit, poll,
   collect); prompt caching is a per-block annotation. Both need to flow
   into the gateway without the use case importing Anthropic SDK types.
2. **Cache breakpoint discipline.** Where exactly do we put
   `cache_control` markers? Get it wrong and we pay full price for
   tokens we expected to cache (Anthropic's discount only applies on
   *exact prefix matches* — even one trailing whitespace flush flips
   pricing).
3. **When does Spectra route through Batch vs sync?** Interactive
   `spectra analyze` cannot wait 24h. Portfolio scheduler can.
   Unconditional batch routing breaks the interactive UX; unconditional
   sync forfeits the savings on the workload that *can* tolerate
   batching.

## Decision

Six commitments.

### 1. `LLMGateway` extends with `cache_breakpoint()` + `analyze_batch()`

The existing `LLMGateway` Protocol stays backward-compatible; we add two
methods with default-noop fallbacks for non-Anthropic adapters
(Bedrock, Vertex):

```python
# src/spectra/use_cases/interfaces.py — additive

class LLMGateway(Protocol):
    """Existing methods unchanged."""
    async def analyze(self, request: LLMRequest) -> LLMResponse: ...
    async def analyze_with_thinking(self, request: ThinkingRequest) -> ThinkingResponse: ...

    # NEW
    def cache_breakpoint(
        self, content: str, ttl: CacheBreakpointTtl = "5m"
    ) -> PromptBlock:
        """Returns a prompt block tagged for prompt caching at the
        provider boundary. Adapters that do not support prompt caching
        return an untagged block — the call still works, the discount
        does not apply. The use case never has to special-case provider
        capabilities.
        """
        ...

    async def submit_batch(
        self, requests: tuple[LLMRequest, ...], deadline: datetime
    ) -> BatchHandle:
        """Submits a batch of requests for asynchronous completion within
        24h. Adapters that do not support batch raise NotImplementedError;
        the use case decides whether to fall back to sync or surface the
        limitation."""
        ...

    async def poll_batch(self, handle: BatchHandle) -> BatchResult: ...
```

`PromptBlock`, `LLMRequest`, `BatchHandle`, `BatchResult`, and
`CacheBreakpointTtl` are frozen Layer-1 entities. `CacheBreakpointTtl`
is `Literal["5m", "1h"]` — the two values Anthropic supports.

The use case never imports `anthropic.types`; it composes prompts using
`gateway.cache_breakpoint(...)` for the cacheable prefix and concatenates
the dynamic suffix. The adapter translates to provider-specific
`cache_control` markers. A Bedrock adapter (Q4) returns the block
untagged — no error, no discount, same correctness.

### 2. Cache breakpoint placement — three stable prefixes per release

The discount only applies on *exact prefix matches*. Anthropic's prompt
cache key is the first N tokens up to the most-recent `cache_control`
breakpoint. For Spectra this gives three deterministic breakpoint sites:

| Breakpoint | Content | Stability | Estimated cached tokens |
|-----------|---------|-----------|-------------------------|
| **A. Specialist system prompt** | `specialist_prompts.py:SECURITY_SYSTEM_PROMPT` etc. (one per dimension) | Stable per Spectra release × per dimension | ~3,000-5,000 per agent |
| **B. MetaPrompter system prompt** | `meta_prompter.py:META_SYSTEM_PROMPT` | Stable per Spectra release | ~2,000 |
| **C. Critique system prompt** | `critique_agent.py:CRITIQUE_SYSTEM_PROMPT` | Stable per Spectra release | ~4,000 |

The dynamic suffix (the `BatchPrompt` from
[ADR-009](ADR-009-batch-granularity-per-focus-area.md)) carries the file
contents and follows the breakpoint. It is *never* cached (it is unique
per scan and per file).

Discipline: the prompt builder MUST place the breakpoint *exactly* at
the system-prompt / user-message boundary, with no trailing whitespace,
no version-string interpolation, no per-call mutation of the cached
prefix. A unit test asserts byte-for-byte stability of each prefix
across hash-known fixture inputs. Failing the test fails the build.

```python
# src/spectra/infrastructure/agents/specialist_agent.py
def build_request(self, batch: BatchPrompt) -> LLMRequest:
    return LLMRequest(
        system=[
            self.gateway.cache_breakpoint(
                content=SPECIALIST_SYSTEM_PROMPTS[self.dimension],
                ttl="1h",   # 1h cache for the system prompt — survives a
                            # fast portfolio scan that touches the same
                            # specialist 50 times in 30 minutes
            ),
        ],
        messages=[
            {"role": "user", "content": batch.to_user_message()},
            # User message is dynamic — no cache_control here
        ],
        model=self.model,
        max_tokens=...,
        task_budget_tokens=...,   # ADR-013
    )
```

### 3. Routing rule — interactive sync, portfolio batch

```python
# src/spectra/use_cases/orchestrate_agents.py — pseudocode

async def run(self, run_mode: RunMode, requests: tuple[LLMRequest, ...]):
    match run_mode:
        case RunMode.INTERACTIVE:
            # Default for `spectra analyze` — sync, latency-bound
            return await asyncio.gather(*[
                self.gateway.analyze(r) for r in requests
            ])
        case RunMode.PORTFOLIO_BATCH:
            # Default for `spectra portfolio scan --schedule overnight`
            # ADR-022 + Q3 #26
            handle = await self.gateway.submit_batch(
                requests, deadline=now() + timedelta(hours=20)
            )
            return await self._poll_until_complete(handle, timeout_h=24)
        case RunMode.PORTFOLIO_INTERACTIVE:
            # Customer asks "scan all 312 repos now"; falls back to sync
            # but with prompt caching across the fan-out
            return await asyncio.gather(*[
                self.gateway.analyze(r) for r in requests
            ])
```

`RunMode` is a Layer-1 enum:

```python
RunMode = Literal["interactive", "portfolio_batch", "portfolio_interactive"]
```

The CLI maps:

- `spectra analyze <repo>` → `interactive`
- `spectra portfolio scan` (no flag) → `portfolio_batch` (default)
- `spectra portfolio scan --interactive` → `portfolio_interactive`

`portfolio_batch` is the cost-optimised path — 50% Batch discount
*plus* prompt caching on the (up to 312 × 6) specialist calls. For a
312-repo portfolio at ~$7/scan today, this reduces fleet cost from
~$2,180/run to ~$700-800/run — the precise number depends on cache hit
rate, which the CTO's #1 ask is built around.

### 4. Cost reporting — surface savings as a first-class report field

The `ScoreCard` already shows `cost_usd`. We add two siblings:

```python
class CostBreakdown(BaseModel, frozen=True):
    cost_usd_actual: float        # what Anthropic billed
    cost_usd_baseline: float      # what it would have cost without caching/batch
    cost_usd_saved: float         # baseline - actual
    cached_input_tokens: int
    batch_discount_applied: bool

class ScoreCard(BaseModel, frozen=True):
    # ... existing fields
    cost: CostBreakdown
```

The HTML report renders a one-liner: "Cost: $4.20 (saved $2.80 via prompt
caching + Batch API)." Customers see the savings on every report — no
separate dashboard required.

Span attributes (per [ADR-023](ADR-023-opentelemetry-tracing-and-cost-attribution.md))
gain `llm.cached_tokens` and `llm.batch_discount_applied` so the same
data is queryable in the trace backend.

### 5. Failure semantics — graceful degradation per primitive

| Primitive | When it fails | Behaviour |
|-----------|---------------|-----------|
| Prompt cache | Anthropic returns no cached tokens (cache evicted, prefix mismatch) | Pay full input price; emit `llm.cache_breakpoint_miss` audit event ([ADR-018](ADR-018-audit-log-and-identity.md)); pipeline continues |
| Prompt cache | `cache_breakpoint()` adapter call raises | Adapter returns the prompt without `cache_control` marker; pipeline continues; one-line WARN |
| Batch API | Submit fails | Surface `SPEC-002` (Anthropic API unreachable); retry via existing decorator; if persistent, fall back to sync (`portfolio_interactive`) with WARN banner |
| Batch API | Job exceeds 24h deadline | Surface `SPEC-006` (timeout) per scan; partial results render per `pipeline_state = degraded`; no automatic retry |
| Batch API | Adapter does not implement (Bedrock, Vertex) | `submit_batch` raises `NotImplementedError`; `orchestrate_agents` catches and falls back to `portfolio_interactive` with WARN banner |

The contract: **no failure mode of these primitives is fatal.** The
fallback path is always sync analysis at full cost. The only escalation
is "the CFO sees a higher bill than expected," which is operationally
visible via [ADR-023](ADR-023-opentelemetry-tracing-and-cost-attribution.md)
cost attribution.

### 6. Composition + diagram

```mermaid
flowchart TB
    subgraph layer2[Layer 2 — Use Cases]
        OA[orchestrate_agents]
        Mode{RunMode}
        Gateway[LLMGateway Protocol<br/>+ cache_breakpoint<br/>+ submit_batch / poll_batch]
    end

    subgraph layer4[Layer 4 — Adapters]
        AnthSync[AnthropicAdapter<br/>analyze: sync<br/>+ cache_control markers]
        AnthBatch[AnthropicAdapter<br/>submit_batch: async]
        Bed[BedrockAdapter<br/>cache_breakpoint = noop<br/>submit_batch = NotImpl]
        Ver[VertexAdapter<br/>same as Bedrock]
    end

    subgraph anth[Anthropic API]
        Sync[/v1/messages]
        Batch[/v1/messages/batches]
        Cache[Server-side prompt cache<br/>5m or 1h TTL]
    end

    OA --> Mode
    Mode -- interactive --> Gateway
    Mode -- portfolio_batch --> Gateway
    Mode -- portfolio_interactive --> Gateway

    Gateway -. impl .- AnthSync
    Gateway -. impl .- AnthBatch
    Gateway -. impl .- Bed
    Gateway -. impl .- Ver

    AnthSync --> Sync
    AnthBatch --> Batch
    Sync -. discount .- Cache
    Batch -. 50% discount .- Sync
    Batch -. discount .- Cache

    Bed -. fallback to sync .-> AnthSync
    Ver -. fallback to sync .-> AnthSync
```

## Consequences

### Positive

- **Two cost levers, one extension.** `cache_breakpoint()` enables prompt
  cache; `submit_batch()` enables Batch API. Both flow through the
  existing `LLMGateway` boundary.
- **The portfolio narrative becomes economic.** A 312-repo overnight
  scan drops from ~$2,180 to ~$700-800 — the unit economics that make
  the CTO's portfolio mode ([ADR-022](ADR-022-postgres-history-store.md))
  shippable instead of theoretical.
- **Cost savings are user-visible.** Every report shows the saved
  amount, every span carries the cached-token count. No "do we get
  the discount?" mystery for the CFO.
- **Graceful degradation across providers.** Bedrock + Vertex keep
  working; they just do not get the discount. No customer is locked
  out by this ADR.
- **Cache breakpoint discipline is testable.** Byte-for-byte prefix
  stability is a unit test we can run on every PR. No "we thought we
  were caching but we weren't" surprises.
- **Stacks with [ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md).**
  Spectra cache short-circuits Stages 3-5 entirely on cache hit; for
  the misses that *do* hit the LLM, prompt cache + Batch compress the
  remaining cost. Two layers of cost defence.

### Negative

- **Prompt cache requires byte-perfect prefix discipline.** A trailing
  whitespace, a date interpolation, a release-version bump in the
  system prompt — any of these flushes the cache for everyone. We
  guard with a unit test, but a careless commit could regress
  silently.
- **Batch API has a 24h deadline; no faster.** Customers who want
  "portfolio scan in 1h" must use `portfolio_interactive` and pay
  full sync price. We surface the trade-off in CLI help text.
- **Bedrock + Vertex eat the unit-economics gap.** A regulated
  customer on Bedrock pays ~3× the per-scan cost of an
  Anthropic-direct customer (no batch, no cache discount). Documented;
  not solvable by us; revisit when Bedrock adds equivalents.
- **Cache TTL is 5m or 1h.** A scan that takes 2h (rare, but possible
  on a 10K-file repo at xhigh) loses the cache mid-run. We pick `1h`
  default; longer scans pay full price for late calls.
- **Anthropic price changes invalidate `cost_usd_baseline`.** The
  baseline is computed against `PRICING_TABLE` at write-time; an
  Anthropic price drop next quarter does not retroactively reduce
  what we recorded as "saved." Documented; the alternative
  (recompute on every report read) is worse.

### Neutral

- The `cache_breakpoint()` shape mirrors Anthropic's `cache_control`
  semantics intentionally. Choosing the SDK shape as our reference is
  the same "stable upstream" bet as choosing OTel for tracing.
- `submit_batch()` returns a `BatchHandle`; the use case polls. We
  deliberately do not abstract polling away as a callback — `await
  poll_batch(handle)` until done is the simplest shape and matches
  every CLI flow we have.
- Prompt caching applies on Anthropic's *Server-Side*; Spectra has no
  cache state for it. Our cache ([ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md))
  is per-finding-batch, an entirely different layer. The two compose
  cleanly.

## Alternatives Considered

| Alternative | Verdict |
|-------------|---------|
| **Adopt only prompt caching; skip Batch API.** | Rejected. Prompt caching alone covers ~25% savings on interactive scans; Batch covers another 50% on portfolio. Skipping Batch leaves the portfolio narrative unaffordable. |
| **Adopt only Batch API; skip prompt caching.** | Rejected. Prompt caching is a 1-day implementation (one Protocol method, three breakpoint sites). Skipping it forfeits ~$1.50/scan for free. |
| **Always route through Batch API regardless of `RunMode`.** | Rejected. Interactive `spectra analyze` cannot wait 24h. Customers experience batch as a regression. |
| **Always route through sync; never use Batch.** | Rejected. CFO bill on portfolio mode becomes impossible to defend. |
| **Build our own request batching layer (group N requests into one).** | Rejected. Anthropic Batch API is purpose-built; rolling our own loses the 50% discount and adds complexity. |
| **Hide `cache_breakpoint()` from the use case; mark prefixes inside the adapter.** | Rejected. Adapter would need to know which content is cacheable; that is a use-case concern (the use case knows which strings are stable). |
| **Use `cache_control: 5m` everywhere (cheapest).** | Rejected. Portfolio scans of 50+ repos exceed 5m for the same specialist; the longer 1h TTL is worth the marginal price difference for the cache to survive the workload. |
| **Skip `BatchHandle` polling; use webhooks.** | Rejected. Webhooks require a public endpoint Spectra (CLI-only) does not have. Polling is the right shape. |
| **Make `submit_batch` raise on adapters that do not support it; let the caller fall back.** | Accepted in part. We raise `NotImplementedError` and `orchestrate_agents` catches and falls back. The Protocol contract documents this. |
| **Compute cost savings as `1 - actual/baseline` and surface as a percentage.** | Accepted as a *display* — both the dollar amount and the percentage render in the report. |

## Implementation effort

**M (5-7 days).** Breakdown: `LLMGateway` Protocol extension + `PromptBlock`
+ `LLMRequest` (refactor existing) + `BatchHandle` + `BatchResult` +
`RunMode` (S, ~1 day); `cache_breakpoint()` impl in `AnthropicAdapter`
(`cache_control: ephemeral`) + byte-stability test (S, ~1 day);
`submit_batch` / `poll_batch` impl against `/v1/messages/batches` (M, ~2
days); orchestrator routing logic (RunMode dispatch + 24h timeout +
sync fallback) (S, ~1 day); `CostBreakdown` entity + report rendering
+ span attributes (S, ~1 day); CLI surface
(`spectra portfolio scan [--interactive]`) (S, ~0.5 day); failure-mode
tests (cache miss, batch timeout, adapter NotImpl) (M, ~1 day).

## References

- Code: `src/spectra/use_cases/interfaces.py` — extend `LLMGateway`
- Code: `src/spectra/infrastructure/anthropic_adapter.py` —
  `cache_breakpoint`, `submit_batch`, `poll_batch`
- Code: `src/spectra/infrastructure/agents/specialist_prompts.py` —
  byte-stable system prompts (no version interpolation)
- Code: `src/spectra/infrastructure/agents/meta_prompter.py`,
  `critique_agent.py` — same discipline
- Code: `src/spectra/use_cases/orchestrate_agents.py` — `RunMode`
  routing
- Code: `src/spectra/entities/models.py` — `CostBreakdown`,
  `BatchHandle`, `BatchResult`, `PromptBlock`, `RunMode`
- Findings: [`docs/strategy/cto-findings.md`](../../strategy/cto-findings.md) §1
  (cost), §6 (build vs buy)
- Roadmap: [`docs/strategy/q3-plan.md`](../../strategy/q3-plan.md)
  capability #23
- Roadmap: [`docs/strategy/product-roadmap.md`](../../strategy/product-roadmap.md)
  capability #23 (RICE 80, Q3 — top-3 cost win)
- Anthropic API: [Prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching),
  [Batch API](https://docs.anthropic.com/en/docs/build-with-claude/batch-processing)
- Related: [ADR-013](ADR-013-task-budget-and-rate-coordination.md) —
  `PRICING_TABLE` source of `cost_usd_baseline`
- Related: [ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md) —
  Spectra cache short-circuits before LLM calls; this ADR optimises the
  remaining LLM calls
- Related: [ADR-022](ADR-022-postgres-history-store.md) — portfolio
  scheduler (#26) routes through Batch API
- Related: [ADR-023](ADR-023-opentelemetry-tracing-and-cost-attribution.md) —
  `llm.cached_tokens`, `llm.batch_discount_applied` span attributes

---

*Last updated: 2026-04-30.*
