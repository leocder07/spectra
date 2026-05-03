# ADR-025: Memory Port + Managed Memory Store Adapter (refines ADR-014 + ADR-015)

## Status

Proposed (2026-05-04) — implements Q4 capability **#50** (per-repo memory)
and **#51** (`spectra ask`). Refines and narrows the scope of
[ADR-014](ADR-014-anthropic-memory-stores-for-team-org.md) and
[ADR-015](ADR-015-query-codebase-use-case.md) (both 2026-04-29) using the
two-Protocol pattern proven in [ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md)
during Q3 ship. The per-developer memory tier in ADR-014 is deferred to Q5+;
this ADR ships the per-repo + per-org tiers only.

See [`q4-plan.md`](../../strategy/q4-plan.md).

## Context

Q3 made Spectra fleet-operable (distributed cache, Postgres history,
OTel, Batch API, drift, cost attribution). Q4's first capability set
makes Spectra **cumulative** — every scan deposits into a per-repo
memory the next scan reads from, and a `spectra ask` surface answers
natural-language queries against that memory with cited evidence.

Three load-bearing questions sit between "we want memory" and "we ship
memory cleanly":

1. **Port shape — one Protocol or two?** Per-repo memory (local SQLite,
   sync-friendly, ~50µs lookups, single-machine, free in OSS) and
   per-org memory (Anthropic Memory Store, async, ~200ms-2s lookups,
   cross-machine, paid tier) are not symmetric. A single Protocol that
   covers both forces every adapter to implement primitives the other
   does not need (Memory Store's `mount_as_tool_context` is a no-op on
   SQLite; SQLite's `read_event_log` is wasted on Memory Store, which
   exposes its log via Anthropic's API not direct row access). The
   parallel with [ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md)
   (which split `LocalCachePort` from `RemoteCachePort` for the same
   reason) is intentional.
2. **Event-log shape vs. bag-of-facts.** A memory store can be modelled
   as either an append-only event log (waiver added at T1, ADR ingested
   at T2, drift detected at T3) or a snapshot of the current state
   (active waivers, latest score, current ADR set). The two shapes have
   different consequences for `spectra ask` (event log gives temporal
   context: "this was waived 6 weeks ago"; snapshot gives latest-state
   only). They also have different cost profiles for Memory Store:
   appending events is cheap; full-snapshot writes are expensive.
3. **Failure mode contract.** What happens when the bound MemoryPort
   raises during a scan? Q3's Postgres history store ([ADR-022](ADR-022-postgres-history-store.md))
   set the precedent: persistence failures are non-fatal — the scan
   completes, a warning surfaces, no exception escapes. Memory should
   follow the same contract for *writes*; the read path for `spectra
   ask` is different — when memory is unavailable, `spectra ask` must
   fail clearly (not silently degrade to "I don't know").

## Decision

**Two Protocols, both at Layer 2.**

```python
# src/spectra/use_cases/interfaces.py

class MemoryPort(Protocol):
    """Local per-repo memory — append-only event log + FTS5 search."""

    async def append_event(self, event: MemoryEvent) -> None: ...
    async def query_events(
        self, *, kind: str | None = None, since: datetime | None = None,
    ) -> tuple[MemoryEvent, ...]: ...
    async def search(self, query: str, *, limit: int = 10) -> tuple[MemoryEvent, ...]: ...
    async def export_snapshot(self) -> MemorySnapshot: ...


class ManagedMemoryPort(Protocol):
    """Per-org Anthropic Memory Store — paid org tier, used by spectra ask."""

    async def write_event(self, event: MemoryEvent) -> None: ...
    async def mount_for_question(self, repo_url: str) -> ManagedMemoryHandle: ...
    async def is_provisioned(self, repo_url: str) -> bool: ...
```

**Layer 1 entities** (frozen Pydantic per the project rule):

```python
# src/spectra/entities/memory.py

class MemoryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    kind: Literal[
        "scan_completed", "waiver_added", "adr_ingested",
        "drift_detected", "decision_logged",
    ]
    repo_url: str
    payload: Mapping[str, object]
    actor: str
    occurred_at: datetime  # always timezone-aware UTC


class MemorySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    repo_url: str
    waivers: tuple[Waiver, ...]
    score_timeline: tuple[ScoreSnapshot, ...]
    adrs: tuple[AdrIngest, ...]
    decisions: tuple[DecisionLog, ...]
    generated_at: datetime
```

**Layer 4 adapters:**

- `LocalFileMemoryAdapter` (implements `MemoryPort`) — SQLite at
  `.spectra/memory/events.sqlite`. Append-only event log table indexed
  on `(kind, occurred_at)`. Search via SQLite FTS5 on
  `payload_search_text`. Owner-only file permissions per
  [ADR-012](ADR-012-cache-hmac-per-user-namespace.md).
- `ManagedAgentMemoryAdapter` (implements both `MemoryPort` and
  `ManagedMemoryPort`) — writes events into an Anthropic Memory Store
  keyed on `{repo_url}` (or `{org_id}/{repo_url}` for cross-repo
  queries). The `MemoryPort` surface is satisfied by mirroring writes
  to a cached local SQLite for fast reads; the `ManagedMemoryPort`
  surface exposes the Memory Store mount used by `spectra ask`.

**Composition root selection:**

```python
# src/spectra/infrastructure/main.py

def _provision_memory(
    *, mode: Literal["local", "managed"],
    api_key: str | None = None,
) -> tuple[MemoryPort, ManagedMemoryPort | None]:
    if mode == "local":
        return (LocalFileMemoryAdapter(_default_memory_path()), None)
    adapter = ManagedAgentMemoryAdapter(api_key=api_key, ...)
    return (adapter, adapter)  # one object, both Protocols
```

**Failure mode (writes):** `MemoryPort.append_event` failures degrade
to a one-shot WARN (same shape as the Postgres history store). The
scan completes; the report still ships.

**Failure mode (reads, `spectra ask`):** `ManagedMemoryPort.mount_for_question`
failures fail loud — `spectra ask` returns a clear error and exits
non-zero. The user must see "memory unavailable" rather than receive a
hallucinated answer with no citations.

**Event log over snapshot.** Append-only events with a derived snapshot
on demand. Reasons: (a) Memory Store API costs scale with write count;
event-log writes are small + frequent + cheap, snapshot rewrites are
large + infrequent + expensive — we want the cheap path on the hot
loop. (b) `spectra ask` benefits from temporal context; "this finding
was waived 6 weeks ago for X reason" is a higher-quality answer than
"finding is currently waived." (c) Aligns with Fowler's Event Sourcing
pattern: the log is the source of truth; snapshots are projections.

## Consequences

### Positive

- **OSS users get free memory.** `LocalFileMemoryAdapter` ships in the
  default install; per-repo memory works for solo and small-team
  use cases without any paid surface.
- **Paid tier has a clean unit-economics story.** Memory Store call
  per scan + per `spectra ask` invocation. Marginal cost per query is
  knowable + observable via OTel spans.
- **Layer 2 boundary insulates against Anthropic Memory Store API
  churn.** Memory Store is in beta as of Q4 ship; schema changes
  during beta→GA stay confined to `ManagedAgentMemoryAdapter` (Layer 4).
- **Symmetric with the cache port split** ([ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md)).
  Two Protocols, two adapters per Protocol, composition root selects.
  Reviewers see a familiar pattern.
- **Event log shape unlocks `spectra trend --explain` cleanly** (a Q4
  stretch goal — already implied by the `drift_detected` event kind).

### Negative

- **Two Protocols mean two test suites.** Adds ~30 tests for
  `LocalFileMemoryAdapter` + ~25 for `ManagedAgentMemoryAdapter` (with
  a fake Memory Store fixture).
- **Schema migration is non-trivial.** SQLite event log on disk needs
  a versioned schema; Memory Store namespace needs a versioned key
  scheme. Both addressed via composite-key invalidation (per
  [ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md)) — a
  schema bump invalidates the existing namespace.
- **Operator experience needs care.** "Why doesn't `spectra ask` work
  on my install?" must trace to a clear `--llm-backend` /
  `MEMORY_STORE_NOT_PROVISIONED` error, not a 500.

### Neutral

- Memory data is cache-class, not crown-jewel: `MemorySnapshot` lives
  alongside the SQLite cache under owner-only permissions. ADR-012's
  HMAC + per-user namespace continues to apply.

## Alternatives considered

### A. One Protocol covering both backends

```python
class MemoryPort(Protocol):
    async def append_event(self, event: MemoryEvent) -> None: ...
    async def search(self, query: str, *, limit: int = 10) -> tuple[MemoryEvent, ...]: ...
    async def mount_for_question(self, repo_url: str) -> Handle | None: ...  # None on local
```

**Rejected.** The `mount_for_question` primitive is meaningless on the
local adapter (returns None always) and load-bearing on the managed
adapter. Forcing every caller to handle the None branch is the opposite
of what Protocols are for. ADR-021's split is the precedent.

### B. Snapshot-only, no event log

**Rejected.** Snapshot rewrites on every scan would 100x the Memory
Store write cost (a snapshot is ~kilobytes; an event is ~hundred
bytes). Loses temporal context for `spectra ask`. Couples the memory
shape to the report shape (every report-shape change forces a snapshot
schema change).

### C. Vector store + RAG (FAISS, pgvector, ChromaDB)

**Rejected.** The product-roadmap §"Anthropic-native by default;
portable by design" explicitly puts vector stores on the punt list:
*"Anthropic prompt cache + Memory Store cover the use case."* Adding a
vector store also adds operational surface (embeddings model choice,
vector DB choice, similarity-threshold tuning) we do not need to take
on for the Q4 demo to be credible. We revisit if Memory Store proves
cost-prohibitive at scale, no sooner than Q5.

### D. Local-only memory, defer Memory Store to Q5

**Rejected.** `spectra ask` is the visible Q4 demo and the second-brain
narrative inflection point. Shipping Q4 without Memory Store ships Q4
without the demo that makes Q4 land. Local memory alone does not
support cited natural-language Q&A at the latency + cost target.

## References

- [`q4-plan.md`](../../strategy/q4-plan.md) §#50, §#51 — capability spec
- [ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md) —
  precedent for two-Protocol split based on access asymmetry
- [ADR-022](ADR-022-postgres-history-store.md) — precedent for non-fatal
  persistence failures
- [ADR-012](ADR-012-cache-hmac-per-user-namespace.md) — file-permission +
  per-user namespace inherited by `LocalFileMemoryAdapter`
- Anthropic Memory Stores API — referenced provider primitive
- Martin Fowler, *Event Sourcing* — the log-is-truth pattern
