# ADR-026: Multi-cloud LLM Gateway (Bedrock + Vertex Sibling Adapters)

## Status

Proposed (2026-05-04) — implements Q4 capability **#14** (region pinning
+ Bedrock + Vertex backends). See [`q4-plan.md`](../../strategy/q4-plan.md).

## Context

Q1 through Q3 ship Spectra exclusively on Anthropic's direct API. The
v0.7.0 self-scan and the M6 founder office both flagged this as the
gating technical work for the first regulated-vertical buyer
(HealthTech / FinTech / Defense). Bedrock and Vertex are not exotic —
they are the standard procurement-approved LLM access path in those
verticals.

The architectural cost of multi-cloud is low *if* we resist the
temptation to abstract differences away. The `LLMGateway` Protocol
([Layer 2](../../../src/spectra/use_cases/interfaces.py)) already
describes a provider-agnostic call shape. Three concrete questions
gate the work:

1. **Which features survive the abstraction?** Adaptive thinking,
   prompt caching, Memory Stores, Skills — each Anthropic-native
   primitive has a different parity story across Bedrock and Vertex.
   Bedrock added prompt caching in 2026-Q1 but lacks Memory Stores;
   Vertex still lacks both as of Q4 ship date. A naive least-common-
   denominator gateway loses 50%+ of the cost advantage on Anthropic.
2. **Where does region pinning live?** Anthropic has no region
   selector — it routes globally. Bedrock and Vertex both require
   explicit region selection at call time. A single CLI flag must do
   the right thing on each backend without surfacing the per-provider
   nomenclature drift (`us-east-1` vs `us-central1`).
3. **What does failure look like when the operator's chosen backend
   doesn't support a requested feature?** `spectra ask` on a Vertex
   backend has no Memory Store to mount. The product-roadmap
   commitment is **degrade visibly, never silently**. The shape of
   that visibility is this ADR.

## Decision

**Three sibling adapters at Layer 4, all implementing the existing
`LLMGateway` Protocol.** No new Protocol; no abstraction over the
existing one.

```
src/spectra/infrastructure/
├── anthropic_adapter.py     (existing — direct Anthropic API)
├── bedrock_adapter.py       (NEW — boto3 + Bedrock model IDs)
└── vertex_adapter.py        (NEW — google-cloud-aiplatform + Vertex)
```

**Per-adapter capability flags.** Each adapter exposes a
`Capabilities` dataclass describing what the backend supports:

```python
# src/spectra/use_cases/interfaces.py

@dataclass(frozen=True)
class GatewayCapabilities:
    supports_prompt_cache: bool
    supports_memory_store: bool
    supports_adaptive_thinking: bool
    supports_zero_data_retention: bool
    supports_batch_api: bool


class LLMGateway(Protocol):
    capabilities: GatewayCapabilities

    async def stream_message(self, request: GatewayRequest) -> AsyncIterator[GatewayChunk]: ...
```

**Composition root reads capability flags at startup** and:

- Skips `cache_control` markers when `supports_prompt_cache=False`.
- Wires `LocalFileMemoryAdapter` (degraded `spectra ask`) when
  `supports_memory_store=False`.
- Substitutes `effort: "high"` for adaptive thinking when
  `supports_adaptive_thinking=False`.
- Refuses startup with a clear error when `--zero-data-retention` is
  set but `supports_zero_data_retention=False` (no silent degradation
  on the ZDR path — see [ADR-027](ADR-027-deterministic-compliance-mapping.md)
  for the symmetric compliance argument).

**CLI surface:**

```
--llm-backend  anthropic|bedrock|vertex   (env: SPECTRA_LLM_BACKEND)
--region       <provider-region>           (env: SPECTRA_LLM_REGION)
--llm-model    <provider-model-id>         (env: SPECTRA_LLM_MODEL)
```

**Region pinning policy:**

- Anthropic: `--region` is a no-op (warned at startup if set; Anthropic
  routes globally).
- Bedrock: `--region` is the AWS region string; defaults to the
  ambient `AWS_REGION` env or boto3 profile region.
- Vertex: `--region` is the GCP region string (`us-central1`, etc.);
  defaults to the GCP project default location.

**Auth credential surfaces:**

- Anthropic: `ANTHROPIC_API_KEY` (existing, unchanged).
- Bedrock: standard AWS credential chain — env vars
  (`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_SESSION_TOKEN`),
  shared credentials file, IAM instance role. We do not introduce a
  Spectra-specific Bedrock credential; the operator's existing AWS
  posture is the source of truth.
- Vertex: GCP Application Default Credentials (ADC) — service-account
  JSON via `GOOGLE_APPLICATION_CREDENTIALS`, gcloud login, GCE
  metadata server. Same posture rule: ADC is the source of truth.

**Model ID translation table.** A small `MODEL_ID_MAP` per adapter
translates the canonical Spectra model name (`opus-4-7`, `sonnet-4-6`,
`haiku-4-5`) into the provider-specific ID. Composition root takes the
canonical name; the adapter translates. New models land via a single
edit to one map.

**Feature-parity matrix lives in `docs/compatibility-matrix.md`.** A
single canonical doc that the README links to and the CLI references
in error messages. The matrix is hand-maintained; integration tests
assert each row matches the live `Capabilities` flag.

## Consequences

### Positive

- **No abstraction tax on the Anthropic path.** Operators on Anthropic
  pay zero overhead for the multi-cloud surface — capability flags are
  set once at adapter init, branches are evaluated once at composition
  root.
- **Adding a fourth backend is mechanical.** Future Azure OpenAI / OCI
  Generative AI / etc. backends ship as new sibling adapters with
  their own `Capabilities` row. No Protocol changes; no use-case
  changes.
- **Regulated-vertical readiness is explicit.** Compliance reviewers
  read `docs/compatibility-matrix.md`, see ZDR + region pinning + their
  preferred provider, sign off without a Spectra-specific procurement
  exception.
- **Provider feature drift is absorbed at the adapter layer.** When
  Vertex ships prompt caching (expected 2026-Q3 per public roadmap),
  one boolean flips on `vertex_adapter.py`; no other code changes.

### Negative

- **Three adapters means three sets of integration tests.** Hermetic
  tests use VCR-style HTTP fixtures per adapter. Live-provider tests
  are gated by env vars (`SPECTRA_BEDROCK_LIVE=1` /
  `SPECTRA_VERTEX_LIVE=1`) the same way Redis live tests are gated
  today.
- **Operator confusion when a feature is unavailable.** Mitigation: a
  one-line CLI message when a flag is requested on a backend that
  doesn't support it ("--zero-data-retention requires Anthropic or
  Bedrock; current backend is Vertex; falling back to /
  refusing to start"). Plus the canonical compatibility matrix.
- **Auth surface area.** Two new credential chains (AWS + GCP) means
  two new failure modes at startup. We catch + translate to a clear
  SPEC-XXX before the agent loop runs.

### Neutral

- The Anthropic path stays the recommended default. `docs/
  compatibility-matrix.md` makes this explicit. We are not introducing
  multi-cloud as a uniform substitute; we are introducing multi-cloud
  as the procurement-compliant alternative for buyers who require it.

## Alternatives considered

### A. Lowest-common-denominator gateway

Strip `cache_control`, Memory Stores, adaptive thinking, ZDR header
from the gateway entirely; ship a portable surface across all three
providers.

**Rejected.** Loses ~50-75% of Anthropic's cost advantage (prompt
cache + Batch API are the v0.8.0 unit-economics story). The product-
roadmap §"Anthropic-native by default; portable by design" rejects
this position explicitly: *"Vendor-neutrality is a pre-2024 ideal; in
2026 every serious LLM platform has divergent native primitives, and
the only honest answer is pick one and adapt at the boundary."*

### B. Bedrock-only multi-cloud (defer Vertex)

Ship Bedrock in Q4; defer Vertex to Q5+.

**Rejected** for the Q4 plan. Vertex parity is mostly free once Bedrock
ships — both are HTTP-with-extra-headers wrappers around an Anthropic-
flavoured API; the boto3-vs-google-cloud-aiplatform delta is the
auth chain and the model ID format. Adding Vertex separately later
costs more than adding both now (each adapter must be re-validated
against the cross-cap regression suite).

### C. Single configurable adapter with provider switch

```python
class LLMGateway:
    def __init__(self, provider: Literal["anthropic", "bedrock", "vertex"]) -> None: ...
```

**Rejected.** Three different SDKs, three different auth chains,
three different model ID schemes, three different region semantics —
"one class with branches" is the classic Big Ball of Mud anti-pattern.
Sibling adapters keep each provider's concerns isolated.

### D. Wait for Anthropic to publish a multi-cloud SDK

**Rejected.** No such SDK is on Anthropic's public roadmap as of Q4
ship date. Waiting blocks the regulated-vertical wedge indefinitely.

## References

- [`q4-plan.md`](../../strategy/q4-plan.md) §#14 — capability spec
- [`product-roadmap.md`](../../strategy/product-roadmap.md) §"Anthropic-
  native by default; portable by design" — strategic frame
- [ADR-001](ADR-001-clean-architecture.md) — Layer 4 sibling adapter
  pattern is the precedent
- AWS Bedrock Anthropic models documentation — provider-side reference
- Google Cloud Vertex AI Anthropic models documentation — provider-side
  reference
